---
version: "1.7.0"
severity: minor
kind: incremental
scope: [machine, project]
status: FRAGMENT — NOT READY TO SHIP
---

# Upgrading to doctrine 1.7.0

> # ⚠ THIS GUIDE IS AN INCOMPLETE FRAGMENT
>
> **Do not hand this to `project-upgrade`. Do not cut 1.7.0 against it.**
>
> These are **notes written during the work**, captured so that nothing
> important is lost between now and the real cut. Per
> [`README.md § One Guide Per Release`](./README.md#one-guide-per-release) a
> guide is authored once at cut time and never revised — this file breaks that
> rule deliberately and temporarily, because 1.7.0 carries **two** independent
> `cicl_version` 2 → 3 changes and only **one of them is done**.
>
> | Change | State |
> | ------ | ----- |
> | The codebase / core-service rename (this document) | **implemented + verified** |
> | [`uses_relation_merge`](../docex/plans/advances/005_process_type_solidification/uses_relation_merge.md) — merge `depends_on` + `consumes` into `uses` | **NOT STARTED** |
>
> Both rewrite every `infra.yml`. They must ship in one cut with **one** guide,
> or a downstream project performs two migrations and reads two runbooks for one
> release. See [Before this ships](#before-this-ships) for the checklist that
> converts these notes into the real guide.

## Summary

This release swaps the two central nouns of the doctrine's service vocabulary.
What 1.6.0 called a **core service** is now a **codebase**; what 1.6.0 called a
**process type** is now a **core service**.

Nothing structural changes. There is still one image per codebase, still N
invocations of it, each with its own role, `command`, port, networks, and
resources. Only the names move — in the doctrine, in `infra.yml`, in `docex`, and
in two emitted key sets.

The motivation, in one line: after 1.6.0 the doctrine's "core service" had no
port, no command, no replica count, and nothing routed to it — so it was not a
service, and the things that *were* deployed had no noun of their own. 1.6.0's own
prose never absorbed the "process type" vocabulary; the runtime-facing documents
kept saying "core service" for the running thing because that is what it is. This
release makes the names match what the doctrine already says.

See [`cicl.md § Core Services`](../doctrine/infrastructure/cicl.md#core-services)
for the model and the [design record](../docex/plans/advances/005_process_type_solidification/codebase_core_service_rename.md)
for the decisions and their rationale.

**Why this is `incremental` and unusually cheap.** Unlike 1.6.0 — which renamed
every emitted resource and forced a replace on first apply — **this release
changes no emitted name.** Container names, ECS service names, task definitions,
log groups, hostnames, image refs, contract paths, target groups, and every
`Name` tag render **byte-identically**. Verified by recompiling both test projects
and diffing against a pre-rename compile: 21/21 artifacts, zero differences
outside the four intended key renames. Nothing is replaced.

## Machine sync

`git pull` + `setup.sh` handle the resident stratum, the skills, and the `docex`
image. No manual machine-side step.

## Project upgrade

### What does not move

Worth stating plainly, because the rename's blast radius *sounds* larger than it is:

- **`$pr/core/`** — the source directory keeps its name. A codebase root is still
  `$pr/core/<name>/`.
- **`/service`** — the in-container working directory is unchanged, as is the
  `migrate.sh` contract path `/service/migrate.sh`.
- **Every emitted name.** See above. No resource is renamed or replaced.
- **`shape_name` tag values** (`core_service`, `backing_service`) — these name a
  *deployed* resource, so `core_service` is already correct under the new
  vocabulary.
- **`consumes:` target syntax** — still dotted `<codebase>.<service>`, e.g.
  `api.web`. The spelling is unchanged; only what the segments are *called*
  changed. *(⚠ superseded if `uses` lands — see [Before this ships](#before-this-ships).)*
- **`schema_owned_by`** — same key, same value. It named a codebase before and
  still does; only the doctrine's wording for it changed.

### 1. Repin + sync the shim

Standard: bump `docex_version` in `project.yml` to `1.7.0` and re-run the shim
install. `cicl_version` is bumped in step 5 — **not yet**, or every compile fails
until the rest of the edits land.

### 2. Rename the two `infra.yml` keys

Top-level `core_services:` → `codebases:`. The nested `processes:` → `core_services:`.

```yml
# BEFORE (cicl_version 2)
core_services:
  api:
    secrets: { ... }
    env:     { ... }
    processes:
      web:
        role: web
        command: [...]

# AFTER (cicl_version 3)
codebases:
  api:
    secrets: { ... }
    env:     { ... }
    core_services:
      web:
        role: web
        command: [...]
```

Nesting, indentation, and every field inside are unchanged. The codebase-level
block still accepts exactly `{core_services, secrets, config, env}`.

> **Do not do this with a single `s/core_services/codebases/`.** The old top-level
> key and the new *nested* key share the spelling `core_services`, so an
> order-independent replace produces `codebases: api: codebases:`. Rename the
> **nested** `processes:` first, or anchor the top-level replace to column 0.

### 3. Qualify core magic refs — five segments

Core refs gain the literal `core_services` collection segment, making a ref an
exact path walk through the document:

```
# BEFORE — four segments
${core_services.api.worker.host}

# AFTER — five segments
${codebases.api.core_services.worker.host}
```

Backing refs are **unchanged** at three segments: `${backing_services.appdb.host}`.

The compiler rejects the old form with a message naming the exact replacement,
and rejects `processes` in the collection slot specifically — which is the
mistake a hand-migration makes:

```
${codebases.api.worker.host}
  -> This looks like the pre-1.7.0 four-segment form.
     Did you mean ${codebases.api.core_services.worker.host}?

${codebases.api.processes.worker.host}
  -> Body segment 2 must be the literal `core_services`, not 'processes'
     — a core ref is a path walk through the document.
```

### 4. `domain_default_process` → `domain_default_service`

Same value (`api.web`), same meaning (the core service answering the bare
`<env>.<project>.<apex>` host).

> **A trap for anyone reading old configs.** 1.6.0 renamed this field the *other*
> direction — `domain_default_service` → `domain_default_process` — so the 1.7.0
> name is the **pre-1.6.0 spelling with a different value shape**:
>
> | Version | Field | Value |
> | ------- | ----- | ----- |
> | < 1.6.0 | `domain_default_service` | `web` — **bare** |
> | 1.6.0 | `domain_default_process` | `api.web` — dotted |
> | ≥ 1.7.0 | `domain_default_service` | `api.web` — dotted |
>
> So the *name* round-trips but the *value* does not. A pre-1.6.0 config carrying
> `domain_default_service: web` is **not** valid 1.7.0 config, and it will not
> look wrong at a glance. Rule 12 rejects the bare form, so the error is loud —
> but do not assume a `domain_default_service` in an old file means what it means
> now.

### 5. Bump `cicl_version` to `"3"`

Last, after steps 2–4. Previous generations are **rejected, not shimmed**.

### 6. Recompile and diff before deploying

```sh
./bin/docex compile
git diff infra/output/
```

**Expect differences in exactly four places, and nothing else:**

| Where | Before | After |
| ----- | ------ | ----- |
| Elastic env tag key | `service = "api"` | `codebase = "api"` |
| Elastic env tag key | `process = "web"` | `service = "web"` |
| OTel resource attr | `docex.core_service=api` | `docex.codebase=api` |
| OTel resource attr | `docex.process_type=web` | `docex.service=web` |

Any change to a container name, hostname, image ref, contract path, `Name` tag,
or `role` value is a **defect** — stop and investigate rather than deploying.

Two harmless artifacts to expect:
- **Tag blocks reorder** in `main.tf`. Tags render alphabetically, and `codebase`
  sorts before `descriptor` where `service` sorted after `role`. HCL `tags` is a
  map, compared order-insensitively — no churn.
- `tofu plan` shows **tag updates in place**, not replacements, because tag
  *values* are unchanged.

### 7. Redeploy

Nothing special. No teardown, no state surgery.

### 8. ⚠ REQUIRED — update saved telemetry queries, dashboards, and alerts

**This is a manual action, not a note.** It cannot be automated and it fails
silently if skipped.

The OTel resource attribute keys change:

```
docex.core_service  ->  docex.codebase
docex.process_type  ->  docex.service
```

Consequences:

- **Every existing time series splits at the upgrade boundary.** Signals emitted
  before carry the old keys; signals after carry the new. Nothing reconciles them.
- **Saved HyperDX queries, dashboards, and alerts filtering on the old keys stop
  matching new data without erroring.** They return an empty or truncated result
  set, which reads as *"no traffic"* rather than *"wrong key"*.
- **An alert built on an old key therefore fails silent and green** — it stops
  firing, and nothing announces that it stopped.

Go through every saved query, dashboard panel, and alert rule that filters or
groups on `docex.core_service` or `docex.process_type` and move it to the new
key. Do this **at the same time** as the deploy, not after.

Dual-writing both key sets for one release was considered and rejected: it
doubles the attribute payload on every signal and defers this same work rather
than removing it.

## Doctrine / behavior notes

- **`docex` error messages now use the new nouns.** Several messages previously
  said "core service" where they meant the codebase — e.g. *"core service 'api'
  declares no process type 'nope'"* is now *"codebase 'api' declares no core
  service 'nope'"*. If you grep logs or CI output for message text, update the
  patterns.
- **`docex build <name>`** now names a **codebase** in its help text and usage
  string. Positional, so no invocation breaks.
- **`docex describe --format llm`** emits `"codebase"` where it emitted
  `"core_service"`, and `"service"` where it emitted `"process"`. The `"kind"`
  value stays `core_service` / `backing_service` (a shape name).
- **The `/health` fan-out path is documented as `/health/<codebase>/<service>`.**
  The rendered paths (`/health/api/worker`) are unchanged; only the placeholder
  spelling in the doctrine and contracts moved.
- **Lexicon:** the `Process Type` entry is **deleted**. `Codebase` is promoted to
  the primary noun; `Core Service` is redefined as the deployment unit. The
  old→new mapping lives here, in this guide, and nowhere else.
- **Historical records keep the old vocabulary on purpose** — mod docs, prior
  upgrade guides, and past `CHANGELOG` entries were true when written and are not
  rewritten.

## Verification

1. `./bin/docex compile` succeeds and `git diff infra/output/` shows only the
   four key renames from step 6.
2. `./bin/docex check` passes.
3. Grep your `infra.yml` for zero occurrences of `processes:`,
   `domain_default_process`, and `${core_services.`.
4. After deploying, confirm a **new** signal in the observability backend carries
   `docex.codebase` and `docex.service`, and that at least one dashboard you
   migrated in step 8 is populating.
5. On elastic, confirm `tofu plan` is clean after apply (no pending replacements).

## Before this ships

The checklist that turns these notes into the real 1.7.0 guide. **Nothing here is
optional.**

- [ ] **Fold in `uses_relation_merge`.** It is the other `cicl_version` 2 → 3
      change. Its steps interleave with step 2 (both edit every service block) and
      it **supersedes** two things written above: the `consumes:` row in
      [What does not move](#what-does-not-move), and any `depends_on` mention.
      Decide the step order deliberately — the rename should be applied *first*
      so `uses` is authored in the new vocabulary.
- [ ] **Re-verify the byte-diff claim after `uses` lands.** The "no emitted name
      changes" guarantee is this rename's property alone. `uses` removes the
      compose `depends_on` / `condition:` emission, which **does** change emitted
      output — so step 6's "expect exactly four differences" table must be
      rewritten, not merely extended.
- [ ] **Re-run the full verification sweep** on the combined change: unit +
      integration suites, compile byte-diff vs a pristine-HEAD compile, protected
      token counts vs `git archive HEAD`, and the anchor-integrity check.
- [ ] **Decide the `severity`.** Currently `minor`, mirroring how 1.6.0 shipped a
      breaking change as a minor. If `uses` plus the rename together feel like a
      major, this frontmatter and `VERSION` move together.
- [ ] **Confirm `CURRENT_CICL_VERSION` in `cicl/model.py` is `"3"`** and that the
      test projects' `infra.yml` files carry `cicl_version: "3"`. They must move
      as a pair; either alone fails every compile. **Both are still `"2"` as of
      this fragment.**
- [ ] **Add the `CHANGELOG.md` 1.7.0 entry** with the old→new vocabulary mapping.
      Past entries stay as written.
- [ ] **Resolve the 6 dangling anchors** created by in-flight edits to `cicl.md`
      and `infrastructure.md` (removed `#### Field scoping`,
      `#### Naming convention`, `#### Dots for reference, hyphens for emission`;
      renamed `## Codebase Structure` → `## Repository Structure`). Listed in the
      [plan](../docex/plans/advances/005_process_type_solidification/codebase_core_service_rename_plan.md#anchors-are-load-bearing).
- [ ] **Run the smoke walk** on both foundations. The rename touched the tag
      filters `docex` uses for teardown and Service-Connect reconcile; a filter
      left on an old key matches zero resources and fails *silently*. The unit
      suite cannot catch that — only a real walk can.
- [ ] **Delete this banner and the `status:` frontmatter field.**

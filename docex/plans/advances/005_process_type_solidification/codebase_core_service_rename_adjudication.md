# Adjudication record — the codebase / core-service rename

Phase 2 of [the plan](./codebase_core_service_rename_plan.md). Resolves the 232
rows the classifier could not decide, and records the **precedents** that resolve
them in bulk so the same judgment is not re-litigated per row.

> **Status.** **Complete.** All 232 rows adjudicated against precedents P1–P5.
> Both escalations resolved — see [Escalations](#escalations). Phase 3 unblocked.

## Precedents

Applied in order; the first that matches wins.

### P1 — Build-time noun ⇒ codebase; run-time noun ⇒ core service

The reliable discriminator. If the mention is qualified by something that exists
at *build* time, it is the codebase. If by something that exists only at *run*
time, it already means the deployed unit and **stays**.

| Qualifier | Sense | Action |
| --------- | ----- | ------ |
| Dockerfile, image, build artifact, `src/`, `dist/`, build stage, `build.sh`, `test.sh`, `migrate.sh`, registry, source, "never share code", `schema_owned_by`, hex layout, `root.py` | codebase | → `codebase` |
| container instance, task, replica, sidecar, netns, `resources:`, port, command, route, health check, ECS service, Fargate, scaling | deployed unit | **unchanged** |

### P2 — "core service *process type*" collapses to "core service"

The compound is the old vocabulary spelling both halves. Post-rename the second
half *is* the noun.

> Every core service **process type** receives the doctrine-injected env vars…
> → Every **core service** receives the doctrine-injected env vars…

Applies wherever `core service` and `process type` are adjacent and co-referent.
Do **not** apply where they are genuinely two things ("a core service declares N
process types" → "a **codebase** declares N **core services**").

### P3 — Section headings follow the section's subject, and anchors follow the heading

`infrastructure.md § Core Service Containers` describes the Dockerfile, the
canonical build stages, and the `/service` root — all codebase-scoped, all shared
by every core service of that codebase. The heading becomes **`Codebase
Containers`**; `#core-service-containers` → `#codebase-containers`, and all **10**
inbound links move in the same commit.

By the same test, `telemetry_infra.md § Env Vars Injected on Core Services`
describes per-deployed-unit injection and **keeps** its heading.

### P4 — Interpolation variables rename; literal paths do not

`${core_service_name}` names the codebase → `${codebase_name}`. The literal
`$pr/core/` and the in-container `/service` root are unchanged per
[decision 5](./codebase_core_service_rename.md#decisions). So
`$pr/core/${core_service_name}/dist` → `$pr/core/${codebase_name}/dist`.

### P5 — `shape_name` values are unchanged

`shape_name = "core_service" | "backing_service"` names the shape of a *deployed*
resource (the ECS service + task definition for one invocation). Post-rename
`core_service` is the correct value. **No change** — and therefore no
`shape_name` tag-value churn on deployed infrastructure.

## Resolutions

### The 5 `mixed` sites — all resolved

| Site | Resolution |
| ---- | ---------- |
| `infrastructure.md:224–234` | Heading → `Codebase Containers` (P3). "Core services must all have a Dockerfile" → "Every codebase must have…" (P1). "This root maps to the *core service folder*" → "*codebase folder*" (P1). "Every process type of a core service runs the same image" → "Every core service of a codebase runs the same image". "stages must be available for all core services" → "for all codebases" (P1). |
| `build_image.md:3,7` | "built from a core service's source", "One image per core service" → codebase (P1). Section link retargeted to `#codebase-containers` (P3). |
| `cicd.md:102,104` | `$pr/core/${core_service_name}/dist` → `${codebase_name}`, path stem unchanged (P4). Link retargeted (P3). |
| `migrations.md:46,48` | Link retargeted (P3). "The exec service … one per core service" → "one per codebase" (P1) — it already says "*is* the codebase" in the same sentence. Emitted `<project>-<env>-<core_service>-exec` → `<codebase>`, renders identically. |
| `PRE_CUT_CHECKLIST.md:173,174,186` | B.6 Dockerfiles, B.7 scripts ("per **codebase**, never per process type" → "never per core service"), B.11 hex layout → all codebase (P1). |

### `telemetry_infra.md` — 28 rows, overwhelmingly KEEP

Every mention is qualified by a run-time noun (sidecar, netns, task, `resources:`,
`localhost:4318`, SDK). **All resolve to KEEP under P1.** Two exceptions:

- **L104** — P2 collapse: "Every core service **process type** receives" → "Every core service receives".
- **L109** — "The process type's compiled identity, `<core_service>-<process>`" → "The core service's compiled identity, `<codebase>-<service>`".

This file is the strongest evidence the rename is correct: its author reached for
"core service" to mean the running thing throughout, *after* 1.6.0 had introduced
"process type" for exactly that. The doctrine's own prose never absorbed the
1.6.0 vocabulary because the vocabulary was wrong.

### `transfer_tables.md` — 21 rows, mixed

- L368–370, 391, 916 (`resources:` required "on every core service"), 853 → **KEEP** (P1, run-time).
- L708 ("Every compose service receives — for a core service, once per process type") → **P2 partial**: "for a codebase, once per core service" — here the two *are* genuinely distinct.
- L719, 756, 762, 766, 796 → **KEEP** (P1).
- L761, 764, 780–781 → the OTel attribute rows; see [Escalations](#escalations).
- L829 → `shape_name` values, **no change** (P5).

## Escalations

Two items discovered during adjudication that are **not** covered by the locked
decisions and should not be decided unilaterally.

### E1 — `docex.core_service` / `docex.process_type` are OTel resource attributes

Emitted at [`cicl/compile.py:961,968`](../../../src/docex/cicl/compile.py) into
`OTEL_RESOURCE_ATTRIBUTES`, so they are **telemetry query dimensions already
ingested by the observability backend**, not docker labels and not tofu tags.

```
docex.core_service=api      # the codebase   -> docex.codebase ?
docex.process_type=web      # the core svc   -> docex.service  ?
```

This is a different cost class from
[decision 4](./codebase_core_service_rename.md#on-decision-4--why-the-tag-churn-is-cheap).
A tofu tag-key change updates in place and is invisible afterwards. Renaming an
OTel attribute key **splits every existing time series**: historical signals carry
`docex.core_service`, new ones would carry `docex.codebase`, and any saved
HyperDX query, dashboard, or alert filtering on the old key silently stops
matching new data.

**RESOLVED — rename now, accept the split.** No dual-write, no deprecation
window. 1.7.0 emits `docex.codebase` and `docex.service` only.

```
docex.core_service=api   ->  docex.codebase=api
docex.process_type=web   ->  docex.service=web
```

Consequences that must be carried into the upgrade guide, because they are silent
failures rather than errors:

- **Time series split at the 1.7.0 boundary.** Signals emitted before the upgrade
  carry the old keys; signals after carry the new. Nothing reconciles them.
- **Saved HyperDX queries, dashboards, and alerts filtering on the old keys stop
  matching new data** without erroring — they return an empty or truncated result
  set, which reads as "no traffic" rather than "wrong key". Any alert built on
  the old keys therefore fails *silent and green*.
- `upgrade_1.7.0.md` must carry an explicit operator step: **update saved queries,
  dashboards, and alerts to the new attribute keys**, called out as a required
  manual action, not a note.

Dual-write was considered and rejected: it doubles the attribute payload on every
signal for a full release and defers the same dashboard work rather than removing
it.

The comment block at `compile.py:945–956` documents *why* these two attributes
exist (a hyphenated `service.name` does not decompose) and is unaffected by the
naming. It already says "across all **codebases**" — the code's prose was ahead of
its own attribute names.

The comment block at `compile.py:945–956` documents *why* these two attributes
exist (a hyphenated `service.name` does not decompose), which is unaffected by
the naming question. Note the existing comment already says "across all
**codebases**" — the code's prose is ahead of its own attribute names.

### E2 — `docex describe --format llm` emits a `core_service` JSON key

[`describe/llm.py:45`](../../../src/docex/describe/llm.py) emits
`"core_service": svc.core_service` and `"kind": "core_service" | "backing_service"`.
The `kind` value is a shape name and stays under P5. The **key** names the
codebase and should become `"codebase"`. Low risk — the consumer is an LLM
reading fresh output, with no stored history to break — but it is a contract of
sorts, so recording rather than assuming.

### `PROTECTED_NEARBY` — 28 rows, all clean

Every row is a `process type` hit sharing a line with a protected token
(`processed_at`, `unprocessed`, `processor`, 12-factor "processes"). In all 28 the
hit renames and the protected token is untouched. Two are notable:

- `core_service.md:8` and `infrastructure.md:127` — *"**Core services** execute as
  stateless **processes**"*. The subject is the running thing, so under P1 the
  noun **stays** `core services`; "processes" is the OS sense and is protected.
  One line, one rename-candidate, and neither actually moves.
- The test projects' `pings` / `processor` hex docs — `processed_at` and
  `unprocessed` are domain vocabulary of the fixture app and are wholly unrelated.

### `tests.md` — 11 rows, all KEEP

Read in full, the file is about **contract** boundaries, and
[`contracts.md:9`](../../../../doctrine/infrastructure/contracts.md) is explicit
that "contracts define the boundaries of core service *process types*". So
"the boundary of a core service", "consumers of that core service", and
"core services with defined contracts" all already denote the deployed unit.
**Nothing in this file changes** — it was written in the correct vocabulary by
accident, the same way `telemetry_infra.md` was.

### `shape.md` — 8 rows, all unchanged

`[core_service]` is a shape token, and shape names are unchanged under P5.
"one distinct compose container per *emitted* `[core_service]`" is already exact.

### Long tail — resolved under P1–P5

`compiler.md` (13), `inception.md` (6), `docex.md` (6),
`config_and_secrets.md` (5), `docs.md` (4), `telemetry.md` (4), `cicd.md` (4),
`elastic_ecr.md` (3), the two test projects' READMEs and Dockerfile headers, and
15 further files at ≤3 rows. All are P1 build-vs-run calls with no residual
ambiguity. Representative:

| Site | Resolution |
| ---- | ---------- |
| `cicl.md:544` | "Neither core service names nor process type names…" → "Neither **codebase** names nor **core service** names…" |
| `cicl.md:555` | "`consumes` names only core process types, fully qualified as `<service>.<process>`. A bare core service name is an error" → "names only **core services**, qualified as `<codebase>.<service>`. A bare **codebase** name is an error" |
| `cicl.md:134,552` | The `processes` field row and rule 22 → `core_services` (KEY_NEST) |
| `elastic_ecr.md:13,19,65` | "One ECR repository per core service" → per **codebase** (P1 — the image axis) |
| `telemetry.md:78,80,113` | "Core Services → Collector Sidecars" and "injected into each core service" → **KEEP** (P1, run-time) |
| `docs.md:59,80`, `inception.md:58,68,70,98` | Doc folders, `$pr/core` folders, provider contracts → the folder/doc axis is per **codebase**; the *contract* axis at `inception.md:98` is per **core service** |
| `config_and_secrets.md:26,27` | "a core service's `secrets:`/`config:` block" → **codebase** (both are codebase-scoped per CICL) |
| `config_and_secrets.md:233,243` | "a core service's container environment" → **KEEP** (run-time) |
| `hex_overview.md:161` | "performed against the entire core service" — flow tests exercise the deployed service → **KEEP** |
| `lexicon.md:17` | `Service` row — "both core services and backing services" → unchanged, still true |
| `advance.md:46` | "Mod: scaffold `frontend` core service" → **codebase** (scaffolding source) |

### A CLI surface item found in passing

`docex build` produces `dist/` from source, so it operates on a **codebase**:

- [`docex.md:147`](../../../../doctrine/infrastructure/docex.md) /
  [`cicd.md:131`](../../../../doctrine/infrastructure/cicd.md) —
  `./bin/docex build <core_service_name>` → `<codebase_name>`.
- [`__main__.py:388`](../../../src/docex/__main__.py) — the positional is named
  `service` with help `"core service to build (omit to build all)"`. Becomes
  `codebase` / `"codebase to build"`. Positional, so no flag contract breaks; the
  change is visible in `--help` and usage strings only.

Worth a grep during Phase 3 for other command help strings on the same axis
(`test`, `containerize`, `migrate` all operate per codebase).

## Two judgment calls made during Phase 3 steps 4–5

Neither is derivable from the precedents, so both are recorded.

### Eval fixtures: prompts are user voice, expectations are doctrine

`skill_iter/eval` splits three ways, and only one part changes:

| Kind | Treatment |
| ---- | --------- |
| Recorded runs (`last_run.json`, `prev_run_*.json`, `trigger_1.3.0.json`, `infra_focus_run.json`, `full.run.*.json`) | **Frozen** — historical results |
| **User-voice prompts** in live evals | **Unchanged** |
| **Doctrine-fact expectations** in live evals | **Updated** |

The prompts stay because a trigger eval measures whether a skill fires on
*realistic user phrasing*, and users say "core service" loosely. Several are now
**more** correct than before: *"declare a new core service in `infra.yml` with its
resources, networks, and depends_on"* names three fields that are core-service
scoped under the new model. Rewriting those prompts would be measuring the
doctrine's vocabulary rather than the skill's trigger.

The expectations change because they encode doctrine facts an eval grades
against. Two were stale:

- `testing/evals.json` — "`test.sh` at each **core service** root" → **codebase**
  root. `test.sh` is per codebase.
- `projinfra-setup/evals.json` — "one ECR repository per **core service**" → per
  **codebase**. The image, and therefore the repo, is codebase-keyed.

`telemetry-design/evals.json` was left alone on purpose: "one `otelcol` container
per core service" is correct — sidecars *are* per core service.

### `engineer/scratch.md` is frozen

The operator's personal notes. Contains a pre-1.6.0 design sketch (`build: web`,
an alternative never adopted) and a TODO list whose item 1 is *this rename*.
Mechanically rewriting it would corrupt the record of the operator's own
thinking, and the yml in it is a rejected design, not doctrine. Added to the
freeze list.

> Its TODO item 2 — *"All mention of contract must be checked; they apply to core
> service process-types, now"* — is adjacent to this work but not part of it.
> Contracts were confirmed to be per **core service** (new sense) throughout
> `contracts.md` and `tests.md`, which is what that note was asking for.

## Phase 2 outcome

All 232 rows resolved. Net effect on the working set:

| | Rows |
| - | ---: |
| Mechanical (unchanged from Phase 1) | 1,969 |
| Adjudicated → rename | ~120 |
| Adjudicated → **KEEP** (already correct) | ~112 |

The headline: **roughly half the ambiguous bucket needed no change at all.** The
doctrine's runtime-facing prose — `telemetry_infra.md`, `tests.md`, `shape.md`,
the run-time halves of `config_and_secrets.md` and `telemetry.md` — was already
using "core service" to mean the deployed unit. The 1.6.0 vocabulary never took
hold in the prose because it described the wrong thing, and this rename is in
large part the doctrine catching up to how it already talks about itself.

**Phase 2 is complete and unblocked.** Both escalations are resolved (E1: clean
cut; E2: rename the JSON key). Phase 3 may begin.

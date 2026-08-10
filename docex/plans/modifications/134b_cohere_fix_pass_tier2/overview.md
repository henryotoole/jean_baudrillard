# Mod 134b — Advance 006 Cohere Fix Pass, Tier 2

## Goal

The Tier 2 half of mod 134, split off by agreement: the code-side docstrings, the
`docex` core docs, and the seed-project residue. Same five sanctioned edit classes as
mod 134 — repair prose, correct a claim to match measured behavior, fix an example so
it obeys a rule already written, complete a list that has silently lost a member, or
repoint a citation. **No edit changes what a rule means.**

## Verification of the brief

Every claim was checked against the tree at `e026f34` before design. **All seventeen
verify.** Four carry corrections or narrowings, recorded inline at A3, A6, A9, B7.
Four *additional* defects of the identical class were found while verifying the ones
named; they are at Q3, Q4, and A1's second bullet, and three of them are escalated
rather than taken.

Baselines, both re-measured at `e026f34` with a clean tree, each as its own
invocation from `docex/`:

```
./.venv/bin/python -m pytest tests -q                  → 1199 passed, 21 deselected
./.venv/bin/python -m pytest tests -q -m integration   → 21 passed
```

---

## Design — A. Claims describing behavior that no longer exists

### A1. `compiler.md:498-500` + `tables/roles/worker.yml:66-70` — "with no second rule"

**Verified false, and the deleted check is load-bearing.** `validate.py:1886` emits a
dedicated `rule_33_health_check_path_off_web` in the `elif not on_web and declared is
not None` arm. It is not redundant with rule 4, because rule 4 acts at the *table*
layer: it rejects an undeclared field on the `worker` / `clock` engines, and it cannot
see the case where a `role: web` core service — whose engine declares the field
legally — sits off the `web` network. `tests/unit/test_validate.py:213`,
`test_rule_33_keys_on_network_membership_not_role`, is that case exactly, and its
docstring says it is "the distinction the doctrine calls out explicitly and the one a
reader will get wrong."

`cicl.md:619` (rule 33) states the network-membership keying correctly. The probe
section of `compiler.md` and the `worker.yml` comment are the two outliers, and both
say the same wrong thing, so both are fixed to the same true one: rule 4 stops it at
the table layer for `worker` / `clock`, and `validate.py`'s dedicated arm catches what
rule 4 structurally cannot.

`worker.yml`'s cross-reference — "the same mechanism `clock.yml` documents for
`schedules`" — **stays true and is not touched.** `schedules` really is rule-4-only:
it is declared on no other role, so there is no legal-declaration case for a second
rule to catch. That asymmetry is the reason the two are not the same mechanism, and
naming it is what stops the next reader re-deriving the wrong conclusion.

**Found while verifying:** `compiler.md:499`'s `[rule 33](#validation)` points at
`compiler.md`'s own `## Validation` section, not at `cicl.md § Validation Rules` where
rule 33 lives. Line `:493`, six lines above, cites it correctly with the full doctrine
path. Repointed — sanctioned class, repoint a citation.

### A2. `cicl/model.py::core_uses()` — names a reader that reads neither accessor

The docstring says "Both the validator (rule 7) and `check.py`'s contract / health
gates read through here". **`check.py` contains no reference to `core_uses` or
`backing_uses`** (grep across `src/`: the only readers are `validate.py:626`, inside
`_validate_refs`'s `scan` — rule 7 — and `validate.py:885`, inside
`_validate_uses_addressing` — rule 32).

The "health gate" it named was `_gate_health_endpoints`, deleted this advance; the
surviving `_gate_contract_health_path` (`check.py:486`) reads `svc.model_extra`, not
the `uses` set. Fix names the two real readers by rule number, which is also the
stronger form: the docstring's argument is that the dots-for-reference parse lives in
one place, and two validation rules depending on it is the fact that makes that
argument.

### A3. `orchestrate/build.py:66-71` — the `curl` requirement and its gate

Both halves withdrawn by mods 126/127. `infrastructure.md § Codebase Containers` now
requires only that an image "must be able to run `./health.sh <service>`". The only
surviving `curl` mentions in `src/` are two comments about the *collector* image being
`FROM scratch` and carrying no probe tool — unrelated.

**Correction to the brief, in the fix's favour.** The paragraph's argument — `find` is
deliberately *not* a doctrine rule, because an unenforced image requirement is a claim
in the rule of record that nothing verifies — survives intact and needs a true
example. There is one: `check.py:592-628` gates the *presence* of
`build.sh` / `test.sh` / `health.sh` in every codebase. So the honest restatement is
that the doctrine's one image requirement is the ability to run
`./health.sh <service>`, and `check` gates the shim's presence. That keeps the
argument's shape and stops asserting a gate that does not exist.

### A4. `aws/client.py:415` — dead citation

`cicl.md § Depends-On Relationships` → `§ Uses Relationships` (`cicl.md:382`, renamed
in advance 005).

### A5. `pipeline/stagetest.py:5-6` — two defects, per mod 134's record

1. Field name: `infra.yml`'s `domain` → `apex_domain` (`stagetest.py:74-92` reads
   `apex_domain`).
2. URL shape: `https://stage.<domain>` → the three-segment form the code builds,
   `f"https://stage.{dns_label(project_name)}.{apex_domain}"` (`:91-92`), which is the
   canonical bare-env host the comment at `:88-90` already names.

### A6. `pipeline/rollback.py:248-255` — a generation behind

Says "a pre-**v2** `infra.yml`" and "the **v1** boundary". The current generation is
`"3"` (`cicl.md:328`, rule 21; `model.py:455-464`), and the code itself already reads
`CURRENT_CICL_VERSION` at `:319`.

**Correction to the brief — the parenthetical must be dropped, not renumbered.** The
three examples it gives (no `core_services:`, `domain_default_service`,
core-service-level `resources:`) are *v1*-specific validation failures, and two of
them read as false against the current format: `core_services:` is the live v3 key
(`test_projects/fixed/infra/infra.yml:39`) and `resources:` is a declared v3
core-service field (`compiler.md:58`). Enumerating one superseded generation's
failure modes is precisely the thing that went stale here, so re-deriving the list for
v2 would re-arm it. The fix states the generation-agnostic fact — an `infra.yml` from
any older generation fails full validation for several unrelated reasons at once, and
which one pydantic reports first decides what the operator sees — and points at
`CURRENT_CICL_VERSION` rather than a literal. **Docstring only; no code changes.**

### A7. `errors.py` — three stale claims

- **`BootstrapFailed:232`** names `docex bootstrap`. That verb does not exist; the
  entry point is `docex projinfra up production` (`__main__.py:368-379`). See **Q3** —
  this is stale in eight code sites, not one, and I am asking before sweeping.
- **`EnvNotRunning:78-79`** says it is raised by `build` "and by `migrate dev/test`
  (which exec into a running container)". Both halves false: mod 099 moved migrate to
  a one-off container (`orchestrate/migrate.py:116`, `compose_run_one_off`; the module
  docstring at `:5` says so), and the only `raise EnvNotRunning` in the tree is
  `build.py:110`.
- **`MigrationFailed:88`** has no raiser anywhere in `src/` or `tests/`. See **Q1**.

### A8. `masterplan.md:165` — the release/migrate ordering

"`release` invokes `migrate` against the target env before applying new application
state." False twice:

- **First release** is apply → migrate (`release.py:667-670`, under `if
  first_release:`), and `release_flow.md:80` states the reason: migrate needs the ECS
  services and RDS to exist.
- **Rollback** never migrates at all. `pipeline/rollback.py` contains no reference to
  migrate; skipping migrations is the documented behavior
  (`release_flow.md § The skip-migrations toggle`).

Fix states the steady-state ordering as the rule, names both exceptions, and cites
`release_flow.md § The four sequences`, which already has it right — so masterplan
stays a navigation aid rather than acquiring a second copy of the reasoning.

### A9. `masterplan.md:201` — `CHANGELOG.md` "referenced by `merge`"

No code reads `CHANGELOG` (grep across `src/`: zero hits). See **Q2** — the choice
between deleting the claim and annotating it is a judgement about what an inventory
section is for, and there is a real question hiding behind it.

### A10. `compiler.md:587` — "the templates do not do naming translation themselves"

**Verified false, and harmful as written.** Four sites re-derive the project segment
inline:

| Site | Expression | `\| lower`? |
| ---- | ---------- | ----------- |
| `project.tf.j2:325` | `{{ project \| replace('_', '-') }}-traefik` | **no** |
| `main.tf.j2:63` | `{{ project \| replace('_', '-') }}-{{ env }}-{{ short }}` | **no** |
| `main.tf.j2:128` | `{{ project \| replace('_', '-') \| lower }}-{{ env }}` | yes |
| `main.tf.j2:130` | same, inside a description string | yes |

`project_dns_label` never enters HCL template context — grep shows it only in
`emit/compose.py` and `emit/ansible.py`, and neither `emit_hcl` nor `emit_hcl_project`
passes it. `naming.dns_label` is `name.replace("_", "-").lower()`
(`naming.py:135`), so the two un-`lower`ed sites are **not** equivalent to it for a
mixed-case project name, and nothing validates the project name to lowercase
(`context.py` applies no pattern).

The doc sentence is what would stop an author noticing. It is corrected to state the
four re-derivations and the two that omit `| lower`. **The templates are not touched**
— fixing them is a behavior change on any mixed-case project. Booked at **D2**.

**The concrete failure mode**, per the C.O.'s direction to state this as a failure
rather than an inconsistency. A project named `MyProject` compiles, in one `docex
compile` run, to two different data-plane spellings of its own project segment:

| Resource | Template site | Rendered segment |
| -------- | ------------- | ---------------- |
| project traefik ASG/instance name | `project.tf.j2:325` | `MyProject-traefik` |
| env-tier SGs and friends (`-{{ env }}-{{ short }}`) | `main.tf.j2:63` | `MyProject-prod-…` |
| Service Connect namespace | `main.tf.j2:128` | `myproject-prod` |
| its description string | `main.tf.j2:130` | `myproject prod` |

Everything routed through `naming.apply_policy` / `dns_label` — and everything on the
fixed side, which goes through `project_dns_label` — gets `myproject`. So the
divergence is not template-vs-template only; it is **template-vs-the-rest-of-docex**,
and on a case-sensitive AWS name (`aws_security_group.name`, ASG names) the two are
different resources. No test catches it because **no fixture has a capital letter**,
and nothing rejects one: `context.py` applies no pattern to `project.yml`'s `name`.

The fix is therefore **not** to patch four Jinja sites — that would leave the fifth
author to re-derive it. It is to validate or normalize the project name at the one
place it enters `docex`, so `dns_label` is idempotent on it and every downstream
spelling collapses to one. That is a behavior change (it rejects or silently
rewrites names that compile today), which is why it is booked and not taken here.

### A11. `hcl.py:1167`'s `traefik_acme_email` — booked, not fixed

Declared as a keyword parameter of `emit_hcl_project`, consumed at `:1253` with the
fallback `f"docex@{apex_domain}"` and rendered into
`ec2_traefik_user_data.sh.j2:142`. The only production call site,
`compile.py:1372-1379`, does not pass it — so on the `ec2_traefik` paths the Let's
Encrypt account email is permanently the placeholder. Class-3: documented, not
implemented. Booked at **D1**; wiring a real ACME account email is a behavior change
and not mine.

---

## Design — B. Lists that have silently lost a member

### B1. `masterplan.md:410-433` — the `src/` tree omits `registry/`

Twenty of the twenty-one packages under `src/docex/` are listed. `registry/`
(`client.py` + `urllib_client.py`) is the only absentee and the only client seam
unlisted — every other adapter package (`aws`, `docker`, `git`, `ssh`, `dns`,
`ansible`, `opentofu`, `secretsmgmt`) has a line. Its `pipeline/` line *was* updated
for `orchestrator_health`, which is what makes this a half-done mod-133 sweep rather
than an old omission.

### B2. The Service Connect consumer reconcile is missing from two enumerations

`release_flow.md:64` documents the step at length — four AWS calls
(`service_connect_endpoints`, `ecs_primary_deployment_times`,
`ecs_force_new_deployment`, `ecs_wait_services_stable`), one of them **mutating** —
and mods 109/114/123's history. But:

- `release_flow.md:70-76` § The four sequences omits it, in the same file whose prose
  describes it. It runs "after the final apply on every branch including rollback",
  so it is a row below the table's last, on both elastic columns.
- `masterplan.md` never mentions it anywhere. Its `release` elastic row (`:222`) reads
  "SSM push → `RunTask` migration → `tofu apply`", which stops one step short.

### B3. `compiler.md § Key types` — no surface entry at all

`:58`'s `CoreService` field list (`role`, `command`, `networks`, `resources`, `port`,
`uses`, `replicas`, `env`) omits **`surfaces`** — this advance's headline field. And
the section has no entry for `Surface` (`model.py:156`), `API_STYLE_FORMATS`
(`model.py:43`), or `IMPLEMENTED_CONTRACT_FORMATS` (`model.py:60`), though every other
first-class `cicl/` type has one. Add `surfaces` to the field list and one entry
covering the three, routing to `cicl.md § Surfaces` and rule 29 rather than restating
the style table.

### B4. `compiler.md:587` — template list omits `ec2_traefik_user_data.sh.j2`

Six files live in `emit/templates/`; five are enumerated. The sixth is named at
`compiler.md:642`, so the file already knows about it.

### B5. `compiler.md:39` — the pipeline diagram's emit list is wrong in both directions

Names `compose.py, hcl.py, ansible.py, secrets.py`.

- **`secrets.py` is not on the compile path.** `compiler.md:583` says so itself: it
  "retains only `render_manifest_env`", used by the `secrets` scaffold/status
  commands, "never written by `compile`".
- **Three modules on the path are missing**: `schedules.py` (`compose.py:51`,
  `hcl.py:45`, `compile.py:1264`), `otelcol.py` (`compose.py:50`, `hcl.py:44`), and
  `tags.py` (`compile.py:1216`, `hcl.py:46`).

### B6. `emit/tags.py` appears in no core doc

Every sibling `emit` module has a "Where to look when changing things" row.
`tags.py` has none, though it is called from `hcl.py`, `compile.py`, and
`pipeline/bootstrap.py`, and reaches both Jinja templates through `env.globals`. One
row added.

### B7. `effective_replicas` has three readers

`compose.py:480,512`, `hcl.py:757`, and `orchestrator_health.py:172`.

**Correction to the brief.** Only one site says "both emitters" — `compiler.md:176`.
The second site is `:648`, a "Where to look" row naming `compile.py` +
`compose.py` + `hcl.py`, which is short by the same reader without using that phrase.
Both are fixed. The stagetest pre-step's read is not incidental: it computes replica
container names to inspect (`:170-176`), with a comment saying it deliberately does
not assume one — so it is a reader of the clamp in the same sense the emitters are.

### B8. Three module docstrings enumerating their own surface

- **`aws/client.py:5-11`** — "the union of AWS operations Phase 4 needs", five
  bullets, against 34 declared methods. Unlisted whole families: ECR (auth token,
  image existence, image count), the RDS deletion-protection probe, Service Connect
  endpoint discovery, ECS deployment/task inspection (the stagetest pre-step and the
  consumer reconcile), and VPC/subnet discovery by tag. The fix generalizes the bullet
  list rather than trying to hold 34 methods in a docstring — an enumeration that
  cannot be kept current is the defect being repaired, so it must not be replaced with
  a longer one.
- **`opentofu/__init__.py:3`** — "Phase 4 needs four OpenTofu operations — init,
  validate, plan, apply". Five are exported and `__all__`-listed; `tofu_destroy` is
  live (`projinfra.py`'s elastic teardown, `envinfra down` for elastic stage/prod).
- **`ssh/client.py:3`** — "the single SSH operation". Two are declared: `run` and
  `capture`. `capture` is what the stagetest pre-step needs (`orchestrator_health.py:191`)
  precisely because `run`'s exit-code-only contract cannot carry `docker inspect`'s
  stdout.

### B9. `masterplan.md § Subcommand Surface` — three wrong *Reads* columns

- **`config` (`:110`)** reads only `infra/config/<env>.env`. `scaffold` and `status`
  read `infra.yml` + transfer tables through `config_manifest`
  (`secretsmgmt/engine.py:71`). The `secrets` row directly above gets the analogous
  fact right, which is what makes the omission visible.
- **`envinfra` (`:117`)** names `infra/secrets/<env>.env`. Bring-up reads the whole
  aggregate — TTE ∪ secrets ∪ config (`orchestrate/up.py:141-143`).
- **`migrate` (`:120`)** names "service images at current version,
  `infra/secrets/<env>.env`". `orchestrate/migrate.py:93-100` reads the compiled
  compose file (`ensure_compiled`, `compose_file_for`), the full aggregate, and
  `infra.yml` for the schema owners.

### B10. Credentials table — the SSH row omits `stagetest`

`:280`'s *Used by* is "`release` (fixed); `preinfra production` (fixed)". The
stagetest pre-step needs the same deploy key — `orchestrator_health.py:153-161`
raises `OrchestratorStateUnreadable` before any SSH if
`infra/deploy_creds/<env>` is absent — and additionally needs **passwordless sudo**
on the target, because the release playbook runs `become: true` and the containers
are root-owned (`:178-181`). The sudo requirement is a host-state fact the table
records for nothing else, so it goes in the row rather than being dropped.

### B11. Elastic `projinfra up production` stops short in two places

`masterplan.md:116` and `:219` both end at "S3 bucket + DynamoDB table for tofu
state". `bootstrap.py:119-166` then runs the two-phase project-tier `tofu apply`:
phase 1 targets the Route53 hosted zone alone so the operator can NS-delegate, phase 2
applies the full project tier. Both phases are idempotent; fixed short-circuits before
them (`bootstrap.py:28`). The two-phase shape is already load-bearing in the seeds'
own docs (`elastic/plans/core/masterplan.md:35`).

### B12. `masterplan.md § Ephemeral Git Worktrees` attributes them to `check` alone

`:302` reads "`docex check` (and defensively, `docex merge`)". `rollback.py:42-46`
imports the same `_worktree` helpers and `:166` creates
`rollback-<target_version>`; the mechanism has its own section in
`release_flow.md § Worktree mechanism`. Rollback's use is not defensive — recompiling
the target version's `infra.yml` with the current `docex` is the point of the command.

### B13. `naming.ecs_cluster_name` — narrowed per mod 134

`release_flow.md:62` and `:141` document it and its five readers thoroughly. It is
undocumented only in `compiler.md`, which is the file that owns naming flow. **One
"Where to look" row in `compiler.md`, nothing else.** Not added to `masterplan.md`:
that file enumerates no other naming helper, so a single entry would be the
inconsistency rather than the fix.

---

## Design — C. The seed projects

Both seeds are edited, so mod 130's cadence applies (see § Seed cadence below).

### C1. `plans/core/api/db_schema.md:13` (both) — `uuid7`

"Generated by `api.web` at write time (`uuid7` for time-ordered insertion)."
`hex/pings/domain/ping.py:7,24` imports and calls `uuid4()`. Both halves are false:
the function, and the *property* — v4 is random, so nothing about the insertion order
is time-ordered. Corrected to `uuid4`, with the ordering claim removed rather than
reassigned to another column.

### C2. `plans/core/api/db_schema.md:47` (both) — "idempotent and reversible"

`databases.md § Migrations`: migrations "should always be idempotent and
forward-only — the doctrine never reverses a schema, even on
[rollback](../infrastructure/cicd.md#rollback)". So the stated *doctrine requirement*
is wrong in the one word that matters.

The following sentence — "Each migration file declares both `-- migrate:up` and
`-- migrate:down`" — is **mechanically true** (both migrations in both seeds carry
both markers) and is kept, restated as a fact about dbmate's file format rather than
as evidence of a reversibility requirement. The two are consistent, and saying so is
the useful part: `docex rollback` runs no migration at all (`rollback.py` contains no
migrate call), which is what forward-only looks like in practice.

### C3. `elastic/plans/core/masterplan.md:38-41` — hostnames missing the codebase segment

Gives `<service>.dev.docex-smoke-elastic.luxrnd.tech` and three siblings. Compiled
output is `api-web.dev.…` — two segments in one DNS label, hyphen-joined. The fixed
companion states the canonical form verbatim at `fixed/plans/core/masterplan.md:33`
("`<codebase>-<service>.<env>.docex-smoke-fixed.luxrnd.tech` — two segments in one
DNS label, hyphen-joined, e.g. `api-web.prod.…`"), so this is also a cross-tree
inconsistency and the fix is to align to the tree that is right.

### C4. `docex/plans/core/test_projects.md:9-10` — wrong domains

`doctrine-fixed.luxrnd.tech` / `doctrine-elastic.luxrnd.tech` →
`docex-smoke-fixed.luxrnd.tech` / `docex-smoke-elastic.luxrnd.tech`. Every artifact
uses the latter: both seeds' `project.yml` names, both masterplans, the checklist, and
`verify_clean.sh`'s `PROJECT_NAME`. This file is in the `docex` half — **no seed
cadence.**

### C5. `core/api/test.sh` (both) — enumerates five of seven test files

The comment maps each test file to the core service it covers and names
`test_smoke.py`, `test_processor_smoke.py`, `test_jobs_smoke.py`,
`test_jobs_concurrency.py`, `test_clock_smoke.py`. Two are unlisted:

- `test_jobs_alogic.py` — alogic tier for `jobs`, driving `JobService` /
  `JobRunnerService` against a stubbed `QueueJobs` (its own docstring, `:1-8`) →
  `api.worker`.
- `test_jobs_drain.py` — "the drain boundary: `api.web` asking `api.worker` to drain"
  (`:1`) → spans both, and is recorded that way rather than assigned to one.

The script itself globs `/service/tests`, so behavior is correct and only the
enumeration is short — which is exactly why nothing caught it.

### C6. `plans/core/api/hex/processor.md:30` (both) — "out of scope for this seed"

"Real multi-worker coordination (advisory locks, `FOR UPDATE SKIP LOCKED`) is out of
scope for this seed." It is in scope and shipped:
`hex/jobs/adapters/driven/queue_jobs_postgres.py:68` issues
`FOR UPDATE SKIP LOCKED`, and four other seed docs treat it as load-bearing
(`db_schema.md:35`, `hex/jobs.md § Concurrency`, `api.md:127`, `masterplan.md:119`).

**The boundary itself stays.** `processor` polls `pings` and genuinely does not
coordinate with sibling replicas; that sentence is true of `processor`. The false part
is the parenthetical generalization to the whole seed, and the fix points at `jobs`,
where the coordination lives. That turns a wrong scope claim into a real module
boundary.

### C7. Four dead prose citations `linkcheck` cannot see

None are markdown links, so nothing mechanical resolves them.

| Site(s) | Written | Actual |
| ------- | ------- | ------ |
| `fixed/infra/infra.yml:30`, `elastic/infra/infra.yml:36` | `cicl.md § Field scoping` | `reasoning/cicl_reasoning.md § Field Scoping` (`:9`) — the string appears nowhere in `cicl.md` |
| `fixed/infra/infra.yml:163`, `elastic/infra/infra.yml:179` | `cicl.md § Three clarifications` | prose inside rule 7 (`cicl.md:593`), not a heading → `cicl.md § Validation Rules` rule 7 |
| `elastic/infra/infra.yml:17` | `cicl.md § Container Registry` | `cicl.md § Container Registry and Service Images` (`:305`) |
| `fixed/verify_clean.sh:21-23` | `transfer_tables.md § naming` | `transfer_tables.md § Naming Policies` (`:73`) |

---

## D. Booked, not fixed

Two brief *files* in `plans/advances/007_small_edges/`, following the existing
file-per-brief shape of that directory, carrying three findings.

- **D1 — `traefik_acme_email_unwired.md`.** Per A11: declared, defaulted, never
  supplied, so the ACME account email on both `ec2_traefik` variants is permanently
  `docex@<apex_domain>`. Records the three code sites, why it is invisible (the
  fallback makes the artifact *valid*, so no gate fires and the walks pass), and what
  the real question is — whether the account email belongs in `infra.yml`, in
  `project.yml`, or in config — without answering it.
- **D2 — folded into D1's brief as a second section, not a second file.** Per A10: two
  template sites re-derive the project DNS segment without `| lower` while two others
  include it, and nothing validates the project name to lowercase. Same file because
  it is the same root cause as D1 — `emit_hcl_project`'s context is assembled
  ad hoc at one call site rather than derived — and splitting them would hide that.
- **D3 — `merge_changelog_gate_unenforced.md`**, per the Q2 ruling. `version_control.md
  § Updating` obliges a changelog entry on every version bump; `merge` is the command
  that tags `v<version>`; no code reads `CHANGELOG.md`. Records the obligation, the
  absent enforcement, and the fact that `masterplan.md:201` asserted the gate existed —
  which is how the absence stayed invisible. Names but does not answer the real
  question: whether `merge` should gate on it, and if so on what (a `## [<version>]`
  heading matching `project.yml`, an `## [Unreleased]` section being non-empty, or
  neither).

**Not booked, deliberately:** nothing else.

---

## Seed cadence

C1, C2, C3, C5, C6, and C7 all edit inside the seeds, so mod 130's cadence is
required: an inner commit in each seed, `git tag -f v<version>`, then an outer
catchup commit. Walk precondition A.2.1 — *on `main`, clean, tag at HEAD* — must hold
when this mod finishes, and the smoke walks run right after.

**A.2.1 verified holding at design time**, with `git rev-parse --verify` rather than a
shell `||` fallback:

| Seed | Branch | Tree | Version | `v<version>` | HEAD |
| ---- | ------ | ---- | ------- | ------------ | ---- |
| `fixed` | `main` | clean | `0.0.19` | `e8dd4aa` | `e8dd4aa` |
| `elastic` | `main` | clean | `0.0.23` | `9443119` | `9443119` |

Both seeds bump one patch (`0.0.20` / `0.0.24`) with a CHANGELOG entry, matching mod
130's cadence, and the tag is force-moved to the new HEAD.

## Verification

Four verifiers, all four green and counted, each pytest run as its own invocation from
`docex/`:

1. `./.venv/bin/python -m pytest tests -q` → 1199 passed, 21 deselected
2. `./.venv/bin/python -m pytest tests -q -m integration` → 21 passed
3. `linkcheck.py`
4. `verify_examples.py`

Two commits in the outer repo, plus the seed cadence commits. **No manual-test
pause**, per the brief.

---

## Design questions — all four ruled

**Design approved. All four answered by the C.O.; decisions recorded inline below,
and the four corrections to the brief (A3, A6, A9/B7, B5) are ratified.**

### Q1. `MigrationFailed` — annotate as unraised, or delete the class? — RESOLVED

**DECISION: annotate, do not delete. It is exported, so removing it is a behavior
change and outside this mod's remit. Annotate it *usefully*: say it has no raiser AND
name what a migration failure actually surfaces as instead — an unraised error class
misleads only because a reader assumes it is the channel, so naming the real channel
is what removes the trap. If the real channel cannot be determined cheaply, say so in
the docstring rather than guessing.**

The real channel *was* determinable cheaply, so nothing is guessed. All three migrate
paths report by **non-zero return code propagated to the caller**, never by raising
this class:

| Path | Where | How a failure surfaces |
| ---- | ----- | ---------------------- |
| `dev` / `test` | `orchestrate/migrate.py:116-125` | `compose_run_one_off` rc, printed to stderr, returned |
| `stage` / `prod`, fixed | `migrate.py:190-195` | `ansible_runner(..., tags=["migrate"])` rc, returned |
| `stage` / `prod`, elastic | `_migrate_elastic` | raises **`ECSTaskFailed`** |

So the docstring will name the rc contract as the channel for two paths and
`ECSTaskFailed` for the third.

### Q2. `masterplan.md:201`'s `CHANGELOG.md` claim — delete, or annotate? — RESOLVED

**DECISION: delete the claim AND write the brief. The instinct behind the question is
itself the finding — `version_control.md` obliges a changelog entry on every version
bump, `merge` is what tags `v<version>`, and nothing enforces it. That is this
advance's signature defect arriving in the release process itself, and deleting the
false `Read` row without recording it would destroy the only evidence anybody
noticed. The brief is worth more than the deletion.**

So: the row goes from the *Read* inventory, and a third brief lands at **D3**.

### Q3. The `docex bootstrap` verb is stale in eight code sites — RESOLVED

**DECISION: approved, adopt the proposed rule. Fix every site naming a CLI verb an
operator types; leave every site naming the internal step or module. It draws the line
where the reader's *action* changes, and `compile.py:1369` already models the honest
form in the tree, so this propagates an existing convention rather than inventing one.
Do them all.**

Applying the rule to the eight sites found gives **six** fixes, not eight, and the
arithmetic is worth recording because two of the sites turn out to be already correct
or deliberately out of scope:

| Site | Text | Verdict |
| ---- | ---- | ------- |
| `errors.py:232` | ``docex bootstrap`` | **fix** |
| `opentofu/subprocess_runner.py:89` | "Used by ``docex bootstrap``" | **fix** |
| `opentofu/subprocess_runner.py:143` | "``docex bootstrap`` to determine which phase" | **fix** |
| `opentofu/subprocess_runner.py:161` | "Used by ``docex bootstrap`` to read … NS records" | **fix** |
| `pipeline/containerize.py:157` | "provisioned by `docex bootstrap`" | **fix** |
| `pipeline/bootstrap.py:1` | "``docex bootstrap`` — idempotent setup…" | **fix** (module header names the verb) |
| `pipeline/bootstrap.py:173-174` | "the command is `docex projinfra up production`, not the stale `docex bootstrap`" | **leave — already the honest form** (F13) |
| `aws/client.py:9,87,92,124,135` | "(used by ``bootstrap``)", "# S3 (bootstrap)" | **leave** — names the internal step, no `docex` prefix |

One incidental exception, declared rather than smuggled: `aws/client.py:9` is inside
the bullet list **B8 rewrites anyway**, so that bullet will name the verb honestly
(`docex projinfra up production`) as part of B8 rather than being left mid-rewrite.
Seven lines touched in total; the rule accounts for six of them and B8 for the
seventh.

`__main__.py:290` — "(formerly ``bootstrap``)" — is already correct and is not
touched; see Q4 for the *other* half of that same docstring, which is not.

### Q4. Two more "not yet implemented" claims of the identical class — RESOLVED

**DECISION: fix them here. Leaving them while B11 corrects `masterplan.md` on the same
point would leave the outer document ahead of the two modules it describes — a perverse
outcome for a mod whose entire purpose is doc/code alignment. Same class, same mod,
same commit.**

- `__main__.py:286-291` — "Mod 036 wires the fixed branch end-to-end… **the rest of
  elastic projinfra is stubbed until mods 037-039.**"
- `pipeline/projinfra.py:1-3` — "Mod 036 ships the fixed branch…; **mods 037-039 add
  elastic.**"

Elastic projinfra ships: `run_projinfra_elastic_down` exists, and `up production` runs
`run_bootstrap`'s two-phase project-tier apply (`bootstrap.py:119-166`).

## Two smaller items folded in per the C.O.

- **`compiler.md:499`'s `[rule 33](#validation)`** (A1's second bullet) — note *why*
  `linkcheck` cannot see it: the anchor **does** resolve, just not to what the words
  claim. `compiler.md § Validation` exists at `:589`, so every mechanical check passes
  while the citation sends a reader to the wrong document entirely. That is the
  citation class this advance has now found five times, and the note goes in the mod
  record because the class is worth more than the instance.
- **`test_rule_33_keys_on_network_membership_not_role`** is named explicitly in A1.
  "The deleted check is load-bearing" is worth more when a named test proves it, and
  the implementation instructs the executor to run that test by name as a spot check
  before editing either site.

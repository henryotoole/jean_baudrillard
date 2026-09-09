# Mod 116 — Retire `role: scheduler`

Delete `role: scheduler` and every carve-out it forced. Mod 115 landed
`role: clock` additively; at that boundary both roles compiled and the suite was
green. This mod removes the old one.

**Deliberately a deletion.** The 115/116 split exists so that any breakage here
is unambiguously a deletion error rather than a new-feature error. Nothing new
is designed. Where a deletion leaves a test without a subject, the test goes
with it; where it leaves a test whose subject was never really the scheduler,
the test is repointed and says so.

Rule of record: `doctrine/infrastructure/cicl.md` (rules 5, 25, 26, 27; the role
table) and `doctrine/infrastructure/specifics/clock.md`.

## Verified before design: the doctrine needs no edits

`grep -rniE 'scheduler|ofelia|eventbridge|scheduled_task' doctrine/ skills/`
returns **zero hits**. Mod 112 already did this work, and spot checks confirm
the rules this mod lands under are already written in their post-scheduler form:

| Rule | Committed text |
| --- | --- |
| 5 | derivatives are `-otelcol`, `-exec`, `-migrate`, `-1`…`-N` — **no `-scheduler`** |
| 25 | `uses` shape rule only; no scheduler clause |
| 26 | "`replicas` is not declared on a `clock` core service" — clock only |
| 27 | "`worker` and `clock` core services do not declare `web` in `networks`" |

`doctrine_excerpts/` likewise has zero scheduler entries. **This mod touches no
file under `doctrine/`, `skills/`, or `doctrine_excerpts/`.** The code is what
moves to meet the rule.

## What deletes

### Whole files

- `src/docex/cicl/cron.py` — 211 lines, scheduler-only (`to_aws_cron`,
  `to_ofelia_cron`, the Sunday-is-1 remap, `cron_validation_issue`).
- `tables/roles/scheduler.yml`.
- `tests/unit/test_scheduler.py` (**26** tests).
- `tests/unit/test_cron.py` (**27** tests — the advance plan's "15" is stale;
  measured by collection at `76c9da6`).
- `tests/fixtures/sample_project_scheduler_elastic/` (3 files).
- `tests/fixtures/sample_project_scheduler_fixed/` (3 files) — see
  [Q1](#q1-the-only-two-codebase-fixture-in-the-suite).

### The Ofelia machinery — `emit/compose.py`

Four contiguous blocks and three guards. Line numbers are against `76c9da6`
(shifted from the advance plan's anchors by Mod 115's additions).

| What | Where |
| --- | --- |
| `_SHELL_SAFE_RE` + `_shell_quote` | `:309-320` |
| `_wrapped_job_command` | `:323-360` |
| `_ofelia_ini` | `:363-444` |
| `_ofelia_block` | `:447-472` |
| `_RUNTIME_FULL_RE` | `:60` |
| `from docex import OFELIA_IMAGE` | `:45` |
| scheduler skip in the service-block loop | `:533-538` |
| scheduler skip in the sidecar loop | `:680-684` |
| `otelcol_config` guard `s.is_core and s.role != "scheduler"` → `s.is_core` | `:829-832` |
| the whole ofelia emission block + `env_file_source` | `:836-888` |

`_RUNTIME_FULL_RE` (`:60`) and `_shell_quote` (`:312`) are Ofelia-only —
verified by grep, their sole call sites are inside the deleted functions.
`_RUNTIME_RE` (`:55`) is the general `$[VAR]` translator and **stays**.

### The EventBridge path — `emit/hcl.py`

- `render_scheduled_task` (`:1013-1110`) — the `aws_scheduler_schedule`, the
  `scheduler.amazonaws.com` invocation IAM role, and its inline policy.
- `"scheduled_task": render_scheduled_task` from `_DESTINATION_RENDERERS`
  (`:1149`).
- `_RenderCtx.iam_policy` (`:218-222`) and its threading (`:1420`, `:1427`) —
  see [Q3](#q3-_renderctxiam_policy-becomes-dead).

### Orchestration

- `orchestrate/_common.py:110-137` — `scheduler_only_services`.
- `orchestrate/up.py:214-230` — both uses collapse. The `dev` pre-populate loop
  becomes an unguarded `for svc in codebases(ctx)`, and the
  `_ensure_codebase_image` loop disappears entirely.
- `orchestrate/up.py:78-127` — `_ensure_codebase_image` itself. Its only caller
  is the loop above; it is dead the moment that loop goes.
- `orchestrate/up.py:235-244` — `extra_env={"DOCEX_SECRETS_ENV_FILE": ...}`.
  See [Q2](#q2-docex_secrets_env_file-and-the-extra_env-carrier).

### Compiler plumbing

- `cicl/transfer.py:93` — `"scheduled_task"` out of elastic `EMIT_DESTINATIONS`.
- `cicl/compile.py:507-513` — `CompiledService.schedule`, now unreferenced
  (`svc.schedule` had exactly three readers, all in the deleted emitters).
- `cicl/compile.py:835-840` — the `fname == "schedule"` skip branch in the
  role-specific-field router. The sibling `schedules` branch (Mod 115) stays,
  and its comment stops referring to `schedule` "above".
- `__init__.py:37-46` — the `OFELIA_IMAGE` pin.

### Validation — `cicl/validate.py`

| Target | Where | Disposition |
| --- | --- | --- |
| `_validate_scheduler_services` + its call site | `:140`, `:1457-1497` | delete |
| rule 25's scheduler clause | `:654-671` | delete (doctrine rule 25 never had it) |
| rule 26's scheduler arm | `:1611-1621` | delete; the clock arm at `:1622-1636` stands alone, exactly as Mod 115 designed |
| `_NON_WEB_ROLES` | `:1587` | `{"worker", "scheduler", "clock"}` → `{"worker", "clock"}` |
| the `-scheduler` reserved suffix | `:823-833`, `:889` | see below |

**The `-scheduler` suffix.** Doctrine rule 5 no longer names it, so the code
must not seed it. `:823-833` is an `if role == "scheduler" → -scheduler / else
→ -otelcol` fork; it collapses to an unconditional `-otelcol` seed, and the
suffix list in the rule-5 message (`:889`) drops `-scheduler`. The rule stays
keyed on **collision, not on a reserved-name list**, which is what makes the
un-reservation safe: nothing is being permitted by fiat, a name simply stops
colliding with a derivative the compiler no longer emits.

### Skips and comments that lose their subject

Pure deletions:

- `pipeline/check.py:387-392` (contract gate), `:481-482` (fan-out),
  `:508-509`, `:529-530` (probeability).

Comment/docstring rewordings — the logic stays, the scheduler example goes:

`pipeline/check.py:110-111` · `pipeline/check.py:353` · `pipeline/release.py:277`
(see [Q4](#q4-the-ecs_service-guard-in-releasepy)) · `docker/client.py:105` ·
`docker/subprocess_client.py:143-146`, `:499-500` (removed with the parameter,
per Q2) · `orchestrate/test.py:118-121` · `cicl/compile.py:622-625`, `:918` ·
`emit/hcl.py:409`, `:467`, `:645`, `:697` · `cicl/validate.py:1457` (section
header).

### The transient-duplication notes retire with `cron.py`

Mod 115 duplicated 5-field cron validation into `cicl/cron_expr.py` rather than
importing from `cron.py`, and recorded that the duplication was expected and
would self-resolve here. Deleting `cron.py` resolves it, so both notes describe
a state that no longer exists and come out:

- `src/docex/cicl/cron_expr.py:14-20` — the `WHY a second cron validator` block.
  The rest of the docstring (what the module does, and the "no translation of
  any kind" statement) stays: that is a live property, not a transitional note.
- `docex/plans/core/compiler.md:411-417` — the
  `> **Transient duplication, self-resolving at mod 116.**` call-out block.

`compiler.md` is a core planning doc, so it is otherwise handled at the
documentation step; this one block is called out here so it is not missed.

## Tests

41 tests delete wholesale with their two modules. The remaining ~13 modules
split three ways.

### Deleted — subject removed

| Test | Module | Subject that no longer exists |
| --- | --- | --- |
| `test_8_scheduler_only_codebase_gets_an_exec_service` | `test_exec_service` | the scheduler-only codebase shape |
| `test_up_dev_builds_scheduler_only_codebase_image_from_dev_stage` | `test_orchestrate_up` | `_ensure_codebase_image` |
| `test_up_dev_builds_no_prod_stage_image` | `test_orchestrate_up` | ditto |
| `test_up_dev_does_not_rebuild_a_long_running_codebases_image` | `test_orchestrate_up` | `scheduler_only_services` scoping |
| `test_up_dev_passes_abs_secrets_env_file` | `test_orchestrate_up` | `DOCEX_SECRETS_ENV_FILE` |
| `test_up_dev_skips_initial_build_for_scheduler` | `test_orchestrate_up` | the bind-mount skip |
| `test_uses_scheduler_rejected` (+2 siblings) | `test_uses_relation` | rule 25's scheduler clause |
| `test_rule_5_rejects_collision_with_a_siblings_scheduler_trigger` | `test_service_nesting` | the `-scheduler` derivative |
| `test_15_replicas_on_scheduler_rejected` / `..._unset_on_scheduler_clean` | `test_service_nesting` | rule 26's scheduler arm |
| `test_scheduler_is_never_a_provider` | `test_contract_health_gates` | the contract exemption |
| `test_mod108_scheduler_run_task_emits_its_command` | `test_hcl_emitter` | RunTask task definitions |
| `test_scheduler_consumer_is_never_redeployed` | `test_service_connect_reconcile` | see [Q4](#q4-the-ecs_service-guard-in-releasepy) |

Mod 108's regression pin survives: its sibling
`test_mod108_each_core_service_emits_its_own_command` covers `web` + `worker`
on the same claim, and `test_mod108_string_command_normalizes_to_list` covers
the `shlex.split` half.

### Converted — the subject was never the scheduler

- **`test_service_expansion_emit.py`** — the module's three-core-service fixture
  is `web` + `worker` + a `scheduler`. `_NIGHTLY` becomes a second **`worker`**,
  not a clock: the module is about service *expansion*, and a clock would drag
  `schedules:` and the deployment percentages into a module that has nothing to
  say about them (`test_clock.py` owns those). Counts move — a worker emits a
  compose service, a sidecar, and an `ecs_service` where the scheduler emitted
  none of the three — so `test_26`, `test_27` and `test_31` gain assertions
  rather than losing them.
- **`test_replicas.py`** — same fixture shape, same conversion. `role: worker`
  is also the only correct choice here: rule 26 forbids `replicas` on a clock,
  and this module's whole subject is `replicas`.
- **`test_magic_refs.py::test_scheduler_service_ref_rejected`** — its subject is
  that an engine declaring `provides: {}` publishes no discovery surface. The
  resolver in that module is hand-built from an inline engines dict, so the
  test keeps its subject by declaring a **synthetic** `provides: {}` engine
  instead of naming `scheduler`. This matters because after the deletion **no
  bundled core role declares `provides: {}`** — `web`, `worker` and `clock` all
  publish parts — so without a synthetic the free behaviour loses its only pin.
- **`test_service_expansion_emit.py::test_25_iam_overflow_...`** — its subject
  is that an `iam` `max_len: 64, overflow: error` breach is a clean compile
  error rather than a silent truncation. Its *vehicle* was the
  `{global_name}_scheduler` role name. Repointed at the surviving `iam`
  consumer, `apply_policy(f"{project}_task_execution", iam_p)`
  (`hcl.py:1361-1366`), driven by a project name over 49 characters.
  `test_naming.py` covers `apply_policy` at unit level; this test's unique
  value is that the breach surfaces *through a compile*, which is worth keeping.
- **`test_orchestrate_test.py`** — three tests use the scheduler fixture for
  genuinely generic multi-codebase behaviour (per-codebase exec iteration,
  short-circuit before a later codebase, a failing `test.sh` returning its
  code). Renamed and repointed at the replacement fixture of
  [Q1](#q1-the-only-two-codebase-fixture-in-the-suite).
- **`test_exec_service.py::test_21_all_fixtures_still_compile`** — the
  parametrize list still names the two scheduler fixtures and, separately,
  **never gained the two clock fixtures Mod 115 added**. It is rewritten to
  list every bundled fixture, which is what its docstring already claims it
  does.
- **`test_exec_service_resolution.py`** — its `(module, attr)` parametrize is a
  deliberate anti-resurrection pin on functions previous mods deleted. It gains
  `("docex.orchestrate._common", "scheduler_only_services")`, which is exactly
  the pin this mod should leave behind.
- **`test_clock.py:233`, `:274` and `test_compose_emitter.py:246`** — docstrings
  that define a clock by contrast with a scheduler ("*is NOT skipped the way a
  scheduler is*"). Restated positively; a comparison to something that no longer
  exists teaches a reader nothing.

### Projected delta

Baseline **1052** (measured, `76c9da6`).

| | Δ |
| --- | --- |
| `test_scheduler.py` | −26 |
| `test_cron.py` | −27 |
| `test_orchestrate_up.py` | −5 |
| `test_uses_relation.py` | −3 |
| `test_service_nesting.py` | −3 |
| `test_exec_service.py` (−`test_8`, parametrize 4 → 5) | 0 |
| `test_contract_health_gates.py` | −1 |
| `test_hcl_emitter.py` | −1 |
| `test_service_connect_reconcile.py` | −1 |
| `test_exec_service_resolution.py` (parametrize +1) | +1 |
| converted modules | 0 |
| **projected** | **≈ 986** |

The implementor must reconcile the actual figure against this table and report
any unexplained difference rather than accepting the number.

## Not in scope

- **`test_projects/`.** Untouched entirely — Mod 117 owns the smoke-project
  migration. Both projects still declare `reaper.prune` with `role: scheduler`,
  so **after this mod both smoke projects are uncompilable, expectedly, until
  117.** Neither the unit nor the integration suite reads them, so both stay
  green. `test_projects/elastic/infra/output/dev/docker-compose.yml` carries a
  committed Ofelia INI; it is compiled output and is 117's to regenerate.
- `PRE_CUT_CHECKLIST.md`, `upgrades/upgrade_2.0.0.md` — Mod 117.
- `doctrine_excerpts/index.yml` — Mod 118 (and it has nothing to delete).
- The `docex build` bytecode-residue bug (integration 18/1) — Mod 119.
- `docex/plans/core/*.md` — the core planning docs are this mod's own
  documentation step (step 8), not `implementation.md`, per the mod process.

### Logged for a later mod

`docex/plans/core/test_projects.md:17` describes `reaper` as *"the only
end-to-end coverage of the scheduler path anywhere"*. That sentence is false the
moment this mod lands, but the file is listed under Mod 117's `Touches` in the
advance plan and 117 is the mod that knows what replaces `reaper`. **Owner: Mod
117.**

## Verification

1. `pytest tests/unit` green, with the delta reconciled against the table above.
2. `pytest -m integration` no worse than 18 passed / 1 failed.
3. `grep -rniE 'scheduler|ofelia|eventbridge|scheduled_task|OFELIA' src/ tables/
   tests/` returns **zero** hits. Any hit in those three trees is a miss.
   Historical mod/plan documents under `plans/` and the not-yet-migrated
   `test_projects/` are the only permitted survivors.
4. **The clock still compiles and emits on both foundations.** Compile
   `sample_project_clock_fixed` and `sample_project_clock_elastic` by hand and
   read the output: the compose service + sidecar + `configs`/env delivery on
   fixed, and `aws_ecs_task_definition` + `aws_ecs_service` + both deployment
   percentages on elastic. The deletion must not have taken anything the clock
   depends on with it — the two roles shared the `schedules`/`schedule` router
   branch, the sidecar loop, and rules 26/27, and each of those is being cut on
   one side only.
5. `docex roles` lists `clock`, `web`, `worker` and the backing roles, and does
   **not** list `scheduler`.

---

## Design questions

**Status: all four resolved — APPROVED by the C.O. as proposed.** The rulings
are folded into the sections above; each question below keeps its reasoning and
carries the ruling.

Two conditions attached at approval, both binding on `implementation.md`:

1. **Q1 — the replacement fixture is named and documented as what it is:** the
   suite's *two-codebase* fixture, with no tie to this advance. The next person
   deleting a role must not rediscover this the hard way.
2. **Q4 — the guard's WHY comment must state explicitly that the branch is now
   reachable *only* via a project-local role table emitting no `ecs_service`.**
   Without that sentence the next reader sees a branch no bundled role can
   trigger, correctly concludes it is dead, and deletes it — and the failure
   resurfaces in a downstream project with a custom role table, which is the
   hardest place to diagnose it. An uncommented defensive branch that *looks*
   dead is worse than no branch at all.

Also ruled at approval: if the actual unit-test count lands anywhere other than
the projection, **that discrepancy is a finding to report, not a number to
update.**

### Q1. The only two-codebase fixture in the suite

`sample_project_scheduler_{fixed,elastic}` are on the delete list, and the
`fixed` one is **the only multi-codebase fixture the unit suite has**:
`sample_project` and `sample_project_elastic` are single-codebase, and Mod 115's
clock fixtures are one codebase with three core services.

Three tests in `test_orchestrate_test.py` use it for behaviour that is not about
schedulers at all — `run_test` iterating one exec service per codebase, and
short-circuiting before reaching a *later* codebase. With a single-codebase
fixture, "short-circuits before a later codebase" cannot be written. This
compounds a loss the advance has already accepted knowingly: Mod 117 deletes
`reaper`, which drops two-codebase coverage from both smoke walks.

**Proposed:** delete both scheduler fixtures as instructed, and add one minimal
replacement, `tests/fixtures/sample_project_multi_fixed` — `api.web` plus a
second codebase whose single core service is an ordinary `worker`. Three files,
derived from the fixture being deleted, with `role: scheduler` + `schedule:`
replaced by `role: worker` + `port` + `health_check_path`. No elastic
counterpart: the elastic scheduler fixture's only non-scheduler consumer is the
`test_21` compile sweep, which does not need it.

**Alternative:** accept the loss and repoint those three tests at
`sample_project`, retiring the multi-codebase assertions.

I recommend the replacement. Per-codebase fan-out (`group_by_codebase`, the
exec service, `migrate.sh` / `test.sh` iteration) is doctrine the compiler still
fully supports, and after 117 the unit suite would be the *only* place it is
exercised at all.

### Q2. `DOCEX_SECRETS_ENV_FILE` and the `extra_env` carrier

**Verified: nothing else grew a dependency on it.** Its complete live footprint
is `emit/compose.py` (the Ofelia INI mount source), `orchestrate/up.py` (the
`extra_env` pass), `docker/subprocess_client.py` (the plumbing) and one unit
test. Every one dies with Ofelia. The only other occurrences in the tree are
historical mod documents and the stale compiled output under `test_projects/`
that Mod 117 will regenerate.

That leaves the **carrier** one hop past the named delete list: with
`DOCEX_SECRETS_ENV_FILE` gone, `DockerClient.compose_up(extra_env=...)`
(`docker/client.py:41`), `SubprocessDockerClient.compose_up`/`_run`
(`:134`, `:494-505`) and `FakeDocker`'s mirror (`tests/conftest.py:76-84`) have
**zero callers**.

**Proposed:** remove the parameter from the port, the implementation, and the
fake. Dead port surface is precisely the residue a deletion mod should take, and
leaving it invites a future reader to conclude the doctrine has a general
"extra env into compose" facility, which it does not.

**Alternative:** keep it as generic plumbing.

Flagged rather than assumed because it narrows a port interface, which is a
wider blast radius than the named list.

### Q3. `_RenderCtx.iam_policy` becomes dead

`render_scheduled_task` is its only reader (`hcl.py:1033-1035`). The other two
`iam` `apply_policy` calls are project-tier and read the policy directly from
`naming_policies`, never through the ctx.

**Proposed:** delete the field (`:218-222`) and its threading (`:1420`,
`:1427`). The `iam` naming policy itself, and `tables/naming_policies.yml`, are
untouched — they still name the task-execution role.

### Q4. The `ecs_service` guard in `release.py`

`_consumer_reconcile_set` skips a core service that emits no `ecs_service`
(`:277-281`), because `update_service` against a nonexistent service is an error
rather than a no-op. After this mod, **every bundled core role emits
`ecs_service`** — `web`, `worker`, `clock` — so no bundled role can reach the
guard, and `test_scheduler_consumer_is_never_redeployed` has no subject.

**Proposed:** **keep the guard**, reword its WHY to say what is now true (a
project-local transfer table may declare a core role that emits no
`ecs_service`; no bundled role does), and **delete the test**. Restoring
coverage would mean shipping a project-local role-table fixture purely to
exercise a defensive branch, which is a lot of machinery for a remote hazard.

**Alternative:** delete the guard too, on the grounds that an unexercised branch
is worse than an absent one. I am against it — the failure it prevents is a
release aborting mid-flight against a nonexistent ECS service, which is the
expensive end of the failure spectrum.

The sibling `test_clock_consumer_is_redeployed_on_the_same_terms` (Mod 115)
survives and keeps the positive half of the claim pinned.

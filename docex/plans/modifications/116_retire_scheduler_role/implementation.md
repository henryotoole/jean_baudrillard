# Mod 116 — Implementation Steps

Retire `role: scheduler` from `docex`. **This is a deletion mod.** Nothing new
is designed; the one addition (a replacement test fixture) exists solely to
preserve coverage a deletion would otherwise take by accident.

Read [`overview.md`](./overview.md) first — it carries the reasoning and the
four approved design rulings. This file is the mechanical sequence.

All paths are relative to `$jb/docex/` unless stated otherwise. Absolute repo
root: `/home/ubuntu/.claude/jean_baudrillard/docex`.

Line numbers are against commit `76c9da6` and are **navigation aids, not
addresses** — they will drift as you delete. Always locate by the quoted
symbol or comment text.

## Ground rules

1. **Do not touch `doctrine/`, `skills/`, or `doctrine_excerpts/`.** They are
   already correct — Mod 112 removed every scheduler reference and this mod's
   job is to make the code match the rule. If you find yourself wanting a
   doctrine edit, **stop and report it**; it means something was missed and
   that is a finding, not a patch.
2. **Do not touch `test_projects/` at all.** Mod 117 owns the entire smoke-project
   migration. Both smoke projects still declare `reaper.prune` with
   `role: scheduler` and **will not compile after this mod. That is expected.**
   Neither the unit nor the integration suite reads them.
3. **Do not touch `docex/plans/core/*.md`.** `compiler.md`, `masterplan.md` and
   `test_projects.md` all carry scheduler prose. Core planning docs are the mod
   cycle's *documentation* step and are updated by the C.O. after this
   implementation lands — not here.
4. **Do not touch `PRE_CUT_CHECKLIST.md`, `upgrades/`, or `CHANGELOG.md`.**
5. When a comment or docstring names the scheduler as an *example*, reword it —
   do not delete the logic it explains. Every such site is listed in Step 11.
6. Run `.venv/bin/python -m pytest` (there is no bare `python` on this machine).

## Phase A — delete the emitters

### Step 1. `src/docex/emit/compose.py` — the Ofelia machinery

Delete, in this order (all are contiguous blocks):

1. `_wrapped_job_command` — the whole function (`:323-360`), including its
   docstring.
2. `_ofelia_ini` — the whole function (`:363-444`), including the
   `from docex.cicl.cron import to_ofelia_cron` local import inside it.
3. `_ofelia_block` — the whole function (`:447-472`).
4. `_SHELL_SAFE_RE` and `_shell_quote` (`:309-320`) plus the
   `# Shell-safe characters that never need quoting…` comment above them. Their
   only call site was inside `_wrapped_job_command`.
5. `_RUNTIME_FULL_RE` (`:60`). **Keep `_RUNTIME_RE` at `:55`** — that is the
   general `$[VAR]` → `${VAR}` translator used by `_translate_tree` and is
   unrelated.
6. The `OFELIA_IMAGE` import at `:45`: change
   `from docex import OFELIA_IMAGE, OTEL_COLLECTOR_IMAGE, TRAEFIK_IMAGE` to
   `from docex import OTEL_COLLECTOR_IMAGE, TRAEFIK_IMAGE`.

Then the three guards:

7. **Service-block loop** (`:533-538`) — delete the whole
   `# Mod 055: a scheduler service does not run as a long-running…` comment and
   its `if svc.role == "scheduler": continue`.
8. **Sidecar loop** (`:680-684`) — delete the
   `# Mod 055: scheduler services have no long-running container…` comment and
   its `if svc.role == "scheduler": continue`.
9. **`otelcol_config` guard** (`:829-832`) — simplify

   ```py
   if any(
       s.is_core and s.role != "scheduler"
       for s in compiled.services.values()
   ):
   ```

   to `if any(s.is_core for s in compiled.services.values()):`.

10. **The emission block** (`:836-888`) — delete everything from the
    `# Mod 055: ofelia scheduler containers + their rendered INI configs.`
    comment through the end of the `if compiled.env != "test":` loop, inclusive.
    This includes the `env_file_source` assignment
    (`if compiled.env in ("dev", "test"): env_file_source = "${DOCEX_SECRETS_ENV_FILE}"`
    / `else: … /opt/{project}/{env}/.env`), which has no other reader.

    **Keep** `if configs: body_doc["configs"] = configs` immediately after it —
    Mod 115's schedule delivery and the otelcol config both still populate
    `configs`.

11. Fix the comment at `:718` (inside the exec-service pass): it ends
    *"(Only ofelia containers are emitted after this, and they are never exec
    targets.)"*. Nothing is emitted after that pass now. Replace the
    parenthetical with a statement that this pass is the last one to add
    service blocks.

### Step 2. `src/docex/emit/hcl.py` — the EventBridge path

1. Delete `render_scheduled_task` in full (`:1013-1110`) — the
   `from docex.cicl.cron import to_aws_cron_expression` local import, the
   `aws_iam_role` with `Principal = { Service = "scheduler.amazonaws.com" }`,
   the `aws_iam_role_policy`, and the `aws_scheduler_schedule`.
2. Delete the `"scheduled_task": render_scheduled_task,  # Mod 055` entry from
   `_DESTINATION_RENDERERS` (`:1149`).
3. Delete the `iam_policy: NamingPolicy | None = None` field and its
   `# Mod 055: IAM naming policy…` comment from `_RenderCtx` (`:218-222`), and
   the `iam_policy=iam_p,` argument where the ctx is constructed (`:1427`).
   Also delete the now-unused `iam_p = naming_policies.get("iam")` at `:1420`
   **inside `emit_hcl_env`**.

   **Critical:** `emit_hcl_project` has its *own* `iam_p = naming_policies.get("iam")`
   (`:1277`) feeding `apply_policy(f"{project}_task_execution", iam_p)` at
   `:1361-1366`. **That one stays.** Confirm you deleted the one in the *env*
   renderer, not the project renderer — a test in Step 9 depends on the
   project-tier one surviving.

### Step 3. `src/docex/cicl/cron.py` — delete the file

`git rm src/docex/cicl/cron.py`.

Three importers exist, all local imports inside functions: `emit/compose.py`
(`to_ofelia_cron`), `emit/hcl.py` (`to_aws_cron_expression`) and
`cicl/validate.py` (`cron_validation_issue`). The first two go in Steps 1-2;
the third goes in **Step 6**, so the tree will not import cleanly until Phase B
is finished. Run the verification grep at the end of Phase B, not here:

```
grep -rn 'cicl\.cron\b\|from docex\.cicl\.cron import' src/ tests/
```

Note `cicl.cron_expr` is a **different** module (Mod 115's 5-field validator)
and **stays** — write the grep so it does not match it.

### Step 4. `tables/roles/scheduler.yml` — delete the file

`git rm tables/roles/scheduler.yml`.

### Step 5. `src/docex/__init__.py` — the `OFELIA_IMAGE` pin

Delete `OFELIA_IMAGE` and its full comment block (`:37-46`). Leave
`OTEL_COLLECTOR_IMAGE` and `TRAEFIK_IMAGE` untouched.

## Phase B — validation and compiler plumbing

### Step 6. `src/docex/cicl/validate.py`

1. Delete the `issues.extend(_validate_scheduler_services(doc))` call at `:140`.
   **Keep** the `_validate_clock_services(doc)` line directly beneath it.
2. Delete `_validate_scheduler_services` in full, along with its section banner
   `# Mod 055 — scheduler role field rules.` (`:1456-1497`). Its
   `from docex.cicl.cron import cron_validation_issue` import goes with it.
3. **Rule 25** — delete the scheduler clause (`:654-671`): the whole
   `# KEPT knowingly out of step with committed rule 25…` comment, the
   `if target.core_services[ref.service].role == "scheduler":` block, and its
   `continue`. The preceding `if ref.service not in target.core_services:`
   block and its `continue` stay.
4. **Rule 26** — delete the scheduler arm (`:1609-1621`): the
   `# Rule 26. \`replicas\` defaults to 1…` comment stays (it explains
   `model_fields_set`, which the clock arm also relies on), but the
   `if svc.role == "scheduler" and "replicas" in svc.model_fields_set:` block
   and its `rule_26_replicas_on_scheduler` issue go. Then delete the now-stale
   preamble on the surviving clock arm — `# Rule 26, clock arm (Mod 115). A
   SEPARATE branch from the scheduler one above on purpose: Mod 116 deletes
   that branch outright, and a fused condition would turn that deletion into a
   rewrite.` — it describes a state that no longer exists.
5. **Rule 27** — `_NON_WEB_ROLES` (`:1587`) becomes
   `frozenset({"worker", "clock"})`.
6. **`_validate_service_role_rules` docstring** (`:1591-1604`) — rewrite. Rule
   26 is now the clock singleton rule alone (N replicas means N ticks and N
   enqueues per fire, `clock.md § Deployment`); rule 27 covers `worker` and
   `clock`. Remove the Ofelia sentence and the "Replaces the prose-only,
   unenforced note this file carried for scheduler" clause.
7. **Rule 5 — the `-scheduler` derivative** (`:823-833`). Replace the
   `if svc.role == "scheduler": … else: …` fork with the unconditional
   `-otelcol` seed:

   ```py
   # Compiler-emitted, per core service: the paired collector sidecar.
   buckets.setdefault(
       _normalized_identity(f"{ref.compiled}-otelcol"), []
   ).append(f"the collector sidecar for core service {ref.dotted!r}")
   ```

   Delete the `# Compiler-emitted, per core service. A scheduler has no
   long-running container…` comment that explained the fork.
8. **Rule 5 message** (`:889`) — drop `-scheduler` from the derivative list so
   it reads `(-otelcol, -exec, -migrate, and the -1..-N replica index)`,
   matching `cicl.md` rule 5 verbatim.
9. **`_validate_rendered_identity` docstring** (`:802-804`) — Mod 099's
   paragraph lists four derivatives including *"``-scheduler`` (Ofelia
   trigger)"*. Reduce it to three and keep the sentence count honest (it says
   "the derivatives"; it must no longer say "four holes" if that count moves —
   check the surrounding prose and adjust).

### Step 7. `src/docex/cicl/transfer.py`

Delete `"scheduled_task",  # Mod 055` from the `elastic` frozenset in
`EMIT_DESTINATIONS` (`:93`).

### Step 8. `src/docex/cicl/compile.py`

1. Delete the `CompiledService.schedule` field and its comment
   (`:507-513`, ending `schedule: str | None = None`). **Keep the `schedules`
   field immediately below it** — that is Mod 115's clock map.
2. Delete the `if fname == "schedule": … continue` branch in the
   role-specific-field router (`:835-840`) with its comment. Then fix the
   surviving `if fname == "schedules":` comment, which currently reads *"Kept
   as its OWN branch rather than fused with `schedule` above"* — there is no
   `schedule` above any more. Restate it as what the branch does.
3. Delete the assignment that carried `schedule` onto the compiled service.
   Locate it by `grep -n 'schedule=' src/docex/cicl/compile.py` — it sits
   beside the `schedules=` carry, which stays.
4. Reword two comments (logic unchanged):
   - `group_by_codebase` docstring (`:622-625`): *"``scheduler`` core services
     are INCLUDED: a scheduler-only codebase contributes no long-running
     compose service, but it still has a source tree…"*. The shape no longer
     exists. State the live rule: every core service's codebase gets an exec
     service because every codebase has a source tree to build, test and
     migrate.
   - The sidecar-accounting comment (`:918`): *"A one-shot scheduler RunTask
     has no sidecar…"*. **Keep the `has_sidecar` logic** — it is keyed on
     `ecs_service` emission and backing services still reach this code. Reword
     to say only long-running services (those emitting an `ecs_service`) carry
     a paired sidecar, so only they fold its overhead into the task totals.

## Phase C — orchestration and the docker port

### Step 9. `src/docex/orchestrate/`

**`_common.py`:** delete `scheduler_only_services` in full (`:110-137`),
including its docstring. Check whether `ProjectContext`/imports at the top of
the file become unused as a result (they will not — `codebases` above it uses
the same imports).

**`up.py`:**

1. Delete `_ensure_codebase_image` in full (`:78-127`). It is dead once its one
   caller goes.
2. Delete the `scheduler_only_services,` entry from the import block at `:27`.
3. In `run_up`'s dev branch (`:210-230`), collapse to:

   ```py
   if env == "dev":
       for svc in codebases(ctx):
           _ensure_initial_dev_build(ctx, docker, svc)
   ```

   Delete the `schedulers = set(scheduler_only_services(ctx))` line, the
   `if svc in schedulers: continue` guard and its comment, and the entire
   `# Mod 103: a scheduler-only codebase has no non-gated compose service…`
   block with its `for svc in scheduler_only_services(ctx):` loop.
4. Delete the `# Mod 075: pass the ABSOLUTE env-file path as
   DOCEX_SECRETS_ENV_FILE…` / `# Mod 080:` comment block (`:235-240`) and the
   `extra_env={"DOCEX_SECRETS_ENV_FILE": str(env_file)},` argument (`:244`) from
   the `docker.compose_up(...)` call. Every other argument stays.
5. Check whether `BuildFailed` is still imported-and-used in `up.py` after
   `_ensure_codebase_image` goes — it is (`:61`, `:72` in
   `_ensure_initial_dev_build`), so **keep the import**.

**`test.py`:** reword the comment at `:118-121`. The `build=True` and the
per-codebase loop stay; only the *"Mod 103: no scheduler carve-out … scheduler-only
ones included … (Mod 099's `test_8_scheduler_only_codebase_gets_an_exec_service`
pins the emission this depends on.)"* prose goes. That named test is deleted in
Step 15, so the cross-reference would dangle. State the live rule: every
codebase runs `test.sh` in its own exec service, which the compiler emits for
every codebase.

### Step 10. Remove the `extra_env` carrier (approved, Q2)

With `DOCEX_SECRETS_ENV_FILE` gone this parameter has zero callers. Remove it
from all four sites:

1. `src/docex/docker/client.py:41` — the `extra_env: dict[str, str] | None = None`
   parameter on the `compose_up` protocol method. Check the method's docstring
   for a mention and remove it if present.
2. `src/docex/docker/subprocess_client.py:134` — the parameter on
   `SubprocessDockerClient.compose_up`; `:143-146` — the
   `# extra_env (mod 075): DOCEX_SECRETS_ENV_FILE for scheduler env-file…`
   comment; the call becomes `return self._run(cmd)`.
3. `src/docex/docker/subprocess_client.py:493-505` — `_run`'s `extra_env`
   parameter, the `` ``extra_env`` (mod 075) is merged over…`` docstring
   paragraph, and the

   ```py
   env = None
   if extra_env:
       import os
       env = {**os.environ, **extra_env}
   ```

   block. The subprocess call becomes `subprocess.run(cmd, check=False)  # noqa: S603`.
   **Check whether `import os` is needed elsewhere in the module** before
   assuming the local import was the only one.
4. `tests/conftest.py:76,83-84` — the parameter on `FakeDocker.compose_up` and
   the `if extra_env is not None: self.calls.append(("compose_up_extra_env", …))`
   block.

### Step 11. Comment rewordings — logic unchanged

Each of these keeps its code and loses its scheduler example.

| File | Site | What to say instead |
| --- | --- | --- |
| `pipeline/check.py:110-111` | `_CONTRACT_FORMAT_BY_ROLE` comment ends *"`scheduler` is absent because a scheduler is never a provider"* | Drop that sentence. The map's remaining note (format follows the provider's role) stands on its own. `clock` is deliberately absent too — Mod 115's ruling, with the `openapi` fallback as the honest answer — so do **not** add a `clock` row. |
| `pipeline/check.py:353` | `_gate_contracts` docstring: *"…∪ (`web`-network core service)**, minus `scheduler` core service."* | Drop *"minus `scheduler` core service"*. The two-arm rule is unchanged. |
| `pipeline/release.py:277-279` | see Step 11a — **special handling** | |
| `docker/client.py:105` | `compose_run_one_off` docstring: *"For a codebase with no non-gated compose service (a scheduler-only one) that means nothing ever refreshes the tag — `up --build` has no block of that codebase to build."* | The `build=True` rationale survives on the `test`-env freshness argument alone (`compose run` reuses a stale image; in `test` the image *is* the artifact under test). Delete the scheduler-only sentence. |
| `emit/hcl.py:409` | *"split a string the same way the fixed side's scheduler wrapper does"* | The `shlex.split` normalization stays. Say only that one `infra.yml` `command` declaration must mean the same thing on both foundations. |
| `emit/hcl.py:467` | *"A one-shot task (scheduler RunTask, and implicitly the `_migrate` task below) has no place for it"* | The `has_ecs_service` gate stays. The `_migrate` task is now the only one-shot example; use it. |
| `emit/hcl.py:645` | *"…retires the OOM risk that motivated the old non-scheduler-first carve-out"* | Historical. Reword to name the retired carve-out without the role: the old "pick the lowest-sorted core service" bridge. |
| `emit/hcl.py:697` | *"(on the three-core-service fixture, role would flip `web` -> `scheduler`)"* | After Step 16 that fixture's third service is a `worker`. Update the example accordingly, or drop the parenthetical. |
| `cicl/cron_expr.py:14-20` | the `WHY a second cron validator while ``cicl/cron.py`` still exists:` paragraph | **Delete the whole paragraph.** It described a duplication that this mod resolves. **Keep** the rest of the docstring, especially the *"There is no translation of any kind here"* paragraph — that is a live property. |

### Step 11a. `pipeline/release.py` — the `ecs_service` guard (approved, Q4)

**Keep the guard.** Only its WHY comment changes, and the replacement is
load-bearing — write it carefully.

Current (`:277-279`):

```py
# WHY: a `scheduler` core service emits no `ecs_service`, so there is
# nothing to redeploy — and `update_service` against a service that
# does not exist is an error, not a no-op.
if "ecs_service" not in svc.emits.get("elastic", []):
```

The replacement **must state that after Mod 116 no *bundled* role can reach
this branch, and that it is reachable only via a project-local role table
declaring a core role that emits no `ecs_service`.** Without that sentence the
next reader sees a branch nothing can trigger, correctly concludes it is dead,
deletes it, and the failure resurfaces in a downstream project with a custom
transfer table — the hardest place to diagnose it. Keep the second half of the
existing WHY (`update_service` against a nonexistent service is an error, not a
no-op) — that is the *reason* the guard exists.

## Phase D — tests

### Step 12. Delete the two dedicated modules

`git rm tests/unit/test_scheduler.py tests/unit/test_cron.py`
(**26** and **27** tests respectively).

### Step 13. The replacement two-codebase fixture (approved, Q1)

`tests/fixtures/sample_project_scheduler_fixed` is the unit suite's **only
multi-codebase fixture**. `sample_project` and `sample_project_elastic` are
single-codebase; the clock fixtures are one codebase with three core services.
Three tests in `test_orchestrate_test.py` use it for behaviour that has nothing
to do with schedulers, and one of them — "short-circuits before a *later*
codebase" — cannot be expressed against a single-codebase fixture at all.

Create `tests/fixtures/sample_project_multi_fixed/`, three files, by copying
`sample_project_scheduler_fixed/` and converting:

- `project.yml` — copy verbatim (project `sample`, version `0.1.0`).
- `infra/secrets/dev.env` — copy, minus any scheduler-specific key. Check its
  one hit for `scheduler` and drop that line if it is a comment naming the role.
- `infra/infra.yml` —
  - keep `api` with its `web` core service and its codebase-level `env:`
    (`DATABASE_HOST` / `DATABASE_USER` / `DATABASE_PASSWORD` magic refs),
  - rename the second codebase `nightly_cleanup` → **`reporter`** and its core
    service → **`worker`**, with `role: worker`, `command: ["python", "-m",
    "entrypoints.worker"]`, `networks: [internal]`, `uses: [appdb]`,
    `port: 8081`, `health_check_path: /health`, and the same
    `resources: {cpu: 0.25, memory: 512MB}`,
  - keep `backing_services.appdb` exactly as-is (`schema_owned_by: api`),
  - keep `cicl_version: "3"`, `foundation: fixed`, `domain_default_service: api.web`.
  - Drop the codebase-level `env:` comments that explain the Ofelia
    secret-inlining split — they describe a mechanism that no longer exists.

**The header comment is required and is the point of the fixture.** Write it as
a top-of-file comment stating plainly that this is *the suite's two-codebase
fixture*: it exists so that per-codebase fan-out — `group_by_codebase`, one
exec service per codebase, the `migrate.sh` / `test.sh` iteration, and
first-failure short-circuit before a *later* codebase — has coverage, and it is
tied to no particular role. A reader deleting a role in future must be able to
see at a glance that this fixture is not theirs to remove.

Verify it compiles: `run_compile` returns 0 for all four envs.

### Step 14. Delete both scheduler fixtures

`git rm -r tests/fixtures/sample_project_scheduler_fixed tests/fixtures/sample_project_scheduler_elastic`.
Do this **after** Step 13 so you can copy from them.

### Step 15. Tests that delete — subject removed

| Module | Test(s) |
| --- | --- |
| `test_exec_service.py` | `test_8_scheduler_only_codebase_gets_an_exec_service`, plus the `scheduler_root` fixture (`:65-71`) and the `_SCHEDULER_FIXED` constant (`:27`) |
| `test_orchestrate_up.py` | `test_up_dev_builds_scheduler_only_codebase_image_from_dev_stage`, `test_up_dev_builds_no_prod_stage_image`, `test_up_dev_does_not_rebuild_a_long_running_codebases_image`, `test_up_dev_passes_abs_secrets_env_file`, `test_up_dev_skips_initial_build_for_scheduler`, plus the `scheduler_ctx` fixture (`:17-30`) |
| `test_uses_relation.py` | `test_uses_scheduler_rejected`, `test_uses_non_scheduler_in_the_same_document_is_clean`, `test_uses_scheduler_reported_once_not_alongside_an_unresolved`, plus the `_SCHEDULER` source constant and the `# Mod 101 — rule 25's scheduler clause.` section banner (`:604-660`) |
| `test_service_nesting.py` | `test_rule_5_rejects_collision_with_a_siblings_scheduler_trigger`, `test_15_replicas_on_scheduler_rejected`, `test_15_replicas_unset_on_scheduler_clean`, plus the `_SCHEDULER` source constant (`:410-422`) |
| `test_contract_health_gates.py` | `test_scheduler_is_never_a_provider`; also fix the module docstring at `:11` (*"minus schedulers"*) |
| `test_hcl_emitter.py` | `test_mod108_scheduler_run_task_emits_its_command` only. **Keep** `test_mod108_each_core_service_emits_its_own_command`, `test_mod108_string_command_normalizes_to_list` and `test_mod108_migrate_task_definition_command_unchanged` — Mod 108's pin survives through them. |
| `test_service_connect_reconcile.py` | `test_scheduler_consumer_is_never_redeployed` and the `_SCHEDULER` dict (`:62`). **Keep** `test_clock_consumer_is_redeployed_on_the_same_terms`, and update its docstring, which says *"unlike the scheduler above it *can* be redeployed"* — there is no scheduler above any more. |

After deleting `test_15_replicas_on_scheduler_rejected`, also fix
`test_service_nesting.py:439`: `@pytest.mark.parametrize("role", ["worker", "scheduler"])`
becomes `["worker", "clock"]`, and the inline `infra.yml` in that test drops its
`schedule: "0 3 * * *"` line (rule 4 would reject `schedule` on a clock, and
`clock` needs no `schedules:` to trip rule 27 — but confirm by running it; if
`_validate_clock_services` fires first and muddies the assertion, add a minimal
valid `schedules:` map instead).

### Step 16. Tests that convert — the subject was never the scheduler

**16a. `test_service_expansion_emit.py`** — `_NIGHTLY` (`:53-61`) becomes a
second **`worker`**, not a clock (a clock would drag `schedules:` and the
deployment percentages into a module about service *expansion*;
`test_clock.py` owns those). Keep the service key `nightly_cleanup` so the
compiled identities in every assertion stay stable, and keep its distinct
`resources: {cpu: 0.25, memory: 512MB, disk: 25GB}` — `test_33b` asserts the
three core services genuinely differ in size (`len(set(per_process.values())) > 1`).
Then update the assertions the conversion moves — a worker emits a compose
service, a sidecar and an `ecs_service` where the scheduler emitted none:

- `test_26` — `sample-dev-api-nightly_cleanup` is now **present**; the
  `…-scheduler` assertion goes. Rewrite the comment.
- `test_27` — sidecars become three, sorted:
  `api-nightly_cleanup-otelcol`, `api-web-otelcol`, `api-worker-otelcol`.
- `test_28` — the `ofelia_api-nightly_cleanup` config lookup goes; assert the
  third service's `image` alongside the other two instead.
- `test_29` — bind mounts and the build-context count (`contexts.count("./core/api")`
  moves from 3 to 4: web + worker + nightly_cleanup + exec).
- `test_30` — add the third key to the no-host-ports loop.
- `test_31` — `aws_ecs_service` becomes `["api-nightly_cleanup", "api-web", "api-worker"]`;
  `aws_lb_target_group` stays `["api-web"]`; the task-definition list is
  unchanged.
- `test_33b` docstring — drops *"which is what lets the rule drop the scheduler
  carve-out"*.
- `test_37`/`test_38` and any other per-service assertion — check each for a
  third-service case that now exists.
- The `_WEB_ONLY_KEY` comment at `:34-35` (*"the lowest-sorted non-scheduler
  core service"*) — reword.

Work through this module by **running it and reading each failure**, not by
predicting. Every failure here should be a count or a presence flip in the
expected direction; a failure of any other shape is a finding.

**16b. `test_service_expansion_emit.py::test_25_iam_overflow_fails_compile_with_the_policys_message`**
— repoint. Its subject is that an `iam` `max_len: 64, overflow: error` breach
is a clean compile error rather than a silent truncation; its *vehicle* was the
deleted `{global_name}_scheduler` role name. The surviving `iam` consumer is
`apply_policy(f"{project}_task_execution", iam_p)` in `emit_hcl_project`
(`hcl.py:1361-1366`), so drive it with a **project name over 49 characters**
(`64 - len("_task_execution")`). Rename only `project.yml`'s `name:` — the
core-service rename in the current test body is no longer needed. Assert
`"policy 'iam' max_len 64"` is in the message and that the offending name
(`<long_project>_task_execution`) is quoted in it. Update the docstring to name
the new vehicle.

**16c. `test_magic_refs.py::test_scheduler_service_ref_rejected`** — repoint to
a **synthetic** engine. Its subject is the free behaviour that an engine
declaring `provides: {}` publishes no discovery surface and can never be a
magic-ref target. After this mod **no bundled core role declares `provides: {}`**
— `web`, `worker` and `clock` all publish parts — so a synthetic is the only way
to keep the pin. `CoreService.role` is a plain `str` and the resolver's engine
map is hand-built, so this is a rename:

- `_engines()` (`:69-71`): `"api-nightly_cleanup": _container("scheduler", {})`
  → a synthetic role, e.g. `_container("opaque", {})`. Rewrite the comment to
  say the role is deliberately synthetic *because no bundled role declares
  `provides: {}` any more*, which is precisely why the pin still matters.
- `_make_doc()` (`:109`): `_proc("scheduler", networks=["internal"])` →
  `_proc("opaque", networks=["internal"])`.
- `_make_tables()` (`:150`): the `"scheduler"` key → `"opaque"`.
- `_ctx(...)` (`:182`): the `role` argument → `"opaque"`.
- Rename the test to `test_service_ref_to_a_provides_nothing_role_rejected` (or
  similar) and rewrite its docstring: the guard is against a future role table
  gaining a `provides: {}` engine and silently opening a discovery surface.

Consider renaming the service key `nightly_cleanup` too if it reads oddly — but
it appears in several assertion strings, so leaving the key and changing only
the role is acceptable and lower-risk.

**16d. `test_replicas.py`** — `_NIGHTLY` (`:59-67`) becomes `role: worker` for
the same reason as 16a, and here it is the *only* correct choice: rule 26
forbids `replicas` on a clock and this module's entire subject is `replicas`.
Update the fixture comment at `:48-52` (*"one web core service, one worker, one
scheduler"*). Run and read the failures; the compose unroll now has a third
long-running service to account for.

**16e. `test_orchestrate_test.py`** — repoint the three tests at the new
fixture. Rename the `scheduler_ctx` fixture to `multi_ctx`, point it at
`sample_project_multi_fixed`, and rewrite its docstring as "a fixed-foundation
two-codebase project (`api` + `reporter`)".

- `test_run_test_scheduler_only_codebase_uses_its_exec_service` → rename to
  `test_run_test_every_codebase_uses_its_own_exec_service`. The expected list
  becomes `["sample-test-api-exec", "sample-test-reporter-exec"]` (`codebases`
  is sorted, so `api` precedes `reporter`). Rewrite the docstring: the live
  rule is that every codebase runs `test.sh` one way — `compose run --rm`
  against its own exec service. Drop the whole `_run_scheduler_tests`
  archaeology paragraph. **Keep** the two closing assertions
  (`build_image == []`, `run_one_shot == []`) — they still pin that no other
  docker verb is reachable from `run_test`.
- `test_run_test_short_circuits_before_later_codebase` — body unchanged except
  the fixture name; rewrite the docstring to drop the "repurposed from" history
  and state the live subject (first-failure short-circuit before the next
  codebase's exec service, with teardown still running).
- `test_run_test_scheduler_run_failure_returns_code` → rename to
  `test_run_test_second_codebase_failure_returns_its_code`; the exit-code key
  becomes `"sample-test-reporter-exec"`.

**16f. `test_exec_service.py::test_21_all_fixtures_still_compile`** — the
parametrize list names the two scheduler fixtures and, separately, **never
gained the two clock fixtures Mod 115 added**. Rewrite it to list every bundled
fixture: `sample_project`, `sample_project_elastic`,
`sample_project_clock_fixed`, `sample_project_clock_elastic`,
`sample_project_multi_fixed`. Update the docstring, which currently says "all
four fixtures".

**16g. `test_exec_service_resolution.py`** — add
`("docex.orchestrate._common", "scheduler_only_services")` to the `_DELETED_103`
list (`:189-192`). This is the anti-resurrection pin this mod should leave
behind. Rename the list and the test if the `103` tag no longer fits (e.g.
`_DELETED_SCHEDULER_HELPERS` / `test_deleted_scheduler_helpers_are_gone`), and
extend the docstring with a third numbered entry naming
`scheduler_only_services` and what it did.

**16h. Docstrings that define a thing by contrast with a scheduler** — restate
positively. A comparison to something that no longer exists teaches a reader
nothing.

- `test_clock.py:233` — *"A clock is NOT skipped the way a scheduler is — it is
  a long-running…"*.
- `test_clock.py:274` — *"…`test`-env carve-out of the kind ofelia needed"*.
- `test_clock.py:342` — the assertion
  `assert 'resource "aws_scheduler_schedule" "api-clock"' not in hcl`.
  **Delete this assertion**: `aws_scheduler_schedule` is not a resource any
  emitter can produce now, so it asserts nothing. Keep the surrounding
  assertions about `aws_lb_target_group`.
- `test_compose_emitter.py:246` — *"A ``worker``/``scheduler`` core service's
  paired OTel sidecar shares…"* → `worker` / `clock`.

## Phase E — verify

### Step 17. The grep gate

```
grep -rniE 'scheduler|ofelia|eventbridge|scheduled_task|OFELIA' src/ tables/ tests/
```

**Must return zero hits.** Anything in those three trees is a miss. (`plans/`
and `test_projects/` are permitted survivors and are not in the grep path.)

Also confirm nothing dangles:

```
grep -rn 'cicl.cron\b\|from docex.cicl.cron import' src/ tests/
grep -rn 'extra_env\|DOCEX_SECRETS_ENV_FILE' src/ tests/
grep -rn 'sample_project_scheduler' tests/
```

All three must return nothing.

### Step 18. The suites

1. `.venv/bin/python -m pytest tests/unit -q` — **green**, and reconcile the
   count against the projection in `overview.md § Projected delta`
   (baseline **1052**, projected **≈ 986**).

   **If the actual lands anywhere other than the projection, that discrepancy
   is a finding to report — not a number to update.** Say which module's delta
   differed and why.

2. `.venv/bin/python -m pytest -m integration -q` — **no worse than 18 passed /
   1 failed.** The single failure is
   `test_build_refreshes_dist_after_src_edit`, the known `docex build`
   bytecode-residue bug assigned to Mod 119. **It is not yours; do not fix it.**
   Any *second* failure is a finding.

### Step 19. The clock still works — read the output, do not trust the tests

The two roles shared the `schedule`/`schedules` router branch, the sidecar loop
and rules 26/27, and each of those was cut on one side only. Compile both clock
fixtures by hand into a temp dir and **read** the output:

- **fixed** (`sample_project_clock_fixed`) — `infra/output/dev/docker-compose.yml`
  has an `api-clock` service block with its `-otelcol` sidecar and its
  `healthcheck`; `DOCEX_SCHEDULES_YAML` is in its `environment` with the `$$`
  escaping intact; the top-level `configs:` still carries `otelcol_config`;
  **no** `-scheduler` key and **no** `ofelia_*` config exists.
- **elastic** (`sample_project_clock_elastic`) — `infra/output/prod/main.tf` has
  `aws_ecs_task_definition.api-clock` and `aws_ecs_service.api-clock` carrying
  both `deployment_minimum_healthy_percent = 0` and
  `deployment_maximum_percent = 100`; the app container's `environment[]`
  carries `DOCEX_SCHEDULES_YAML`; **no** `aws_scheduler_schedule` and **no**
  `aws_iam_role` naming `scheduler.amazonaws.com`.
- `infra/output/<env>/schedules.yml` is written for all four envs on both.

Also run `./bin/docex roles` (or the equivalent in-process call) and confirm the
list carries `clock`, `web`, `worker` and the backing roles, and **not**
`scheduler`.

### Step 20. Report

Report to the C.O.:

1. The exact unit count and the per-module reconciliation against the
   projection, calling out any discrepancy explicitly.
2. The integration result.
3. The grep output (expected: empty for `src/`, `tables/`, `tests/`).
4. What Step 19's manual read showed on each foundation.
5. **Restate plainly that both smoke projects are now uncompilable pending Mod
   117**, so nobody mistakes it for breakage.
6. Anything you wanted to touch in `doctrine/`, `skills/`, `doctrine_excerpts/`,
   `test_projects/` or `plans/core/` and did not — as a finding.

# Mod 115 — Implementation Steps

Teach the compiler `role: clock`. Purely additive: **nothing under `role:
scheduler` may be touched** — not `tables/roles/scheduler.yml`, not
`cicl/cron.py`, not the Ofelia emitter in `emit/compose.py`, not
`render_scheduled_task` in `emit/hcl.py`, not `scheduler_only_services`. Mod 116
deletes all of it and it must still work when you finish.

Rule of record: `doctrine/infrastructure/specifics/clock.md`, plus `cicl.md`'s
`schedules` field row (`:149`), `replicas` row (`:148`), and rules 26/27
(`:557-558`). Read `clock.md` before starting. Where it and this document
disagree, **it wins — stop and report rather than reconciling them yourself.**

Design: [`overview.md`](./overview.md).

All paths are relative to `/home/ubuntu/.claude/jean_baudrillard/docex`.

## Step 0 — Preflight

1. Confirm the branch is `005_process_type_solidification` and the tree is
   clean apart from this mod's folder.
2. Record the baseline: `pytest tests/unit -q` → **1006 passed**.
   `pytest -m integration -q` → **17 passed, 1 failed**. The one failure is
   `tests/integration/test_build_real.py::test_build_refreshes_dist_after_src_edit`
   — a known `docex build` bytecode-residue bug assigned to Mod 119. **Do not
   fix it and do not let it block you.**

## Step 1 — `tables/roles/clock.yml`

New file. Copy `tables/roles/worker.yml` as the starting point — **not**
`scheduler.yml`. A clock is an ordinary long-running core service.

```yml
roles:
  clock:
    description: "Core-service role — the singleton cron loop that defers work onto its codebase's queue."
    container:
      foundation: both
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service, container_definition]
      defaults:
        fixed: {}
        elastic:
          launch_type: FARGATE
          network_mode: awsvpc
      fields:
        health_check_path:   # byte-identical to worker.yml's block
          ...
        schedules:
          fixed: {}
          elastic: {}
      provides:              # byte-identical to worker.yml's block
        host: ...
        port: ...
      env: {}
      naming: ecs
```

Header comment must state:

- A clock is a long-running singleton container on both foundations; a compose
  service on fixed, `task_definition` + `ecs_service` on elastic. **No
  `target_group`** — a clock takes no ingress (rule 27).
- `provides.{host,port}` mirrors `worker` deliberately. A clock is consumer-only
  in practice, but it gets **no exemptions**: a magic ref naming
  `api.clock.host` must resolve like any other.
- `schedules` is declared with **empty per-foundation translation bodies**,
  exactly as `scheduler`'s `schedule` marker is. The declaration is what makes
  rule 4 (`tt_rule_4_undeclared_field`) reject `schedules:` on every other role
  — that is how `clock.md`'s "rejected on every other role" is enforced, with
  no new rule. The *value* is handled procedurally by the emitters and is
  carried directly onto `CompiledService` (Step 3).
- Point at `doctrine/infrastructure/specifics/clock.md`.

## Step 2 — `src/docex/cicl/cron_expr.py`

New module: 5-field cron validation and **nothing else**.

- `validate_five_field(expr: str) -> None` raising `CronExprError`, and
  `cron_expr_issue(expr, *, where, rule) -> ValidationIssue | None`, mirroring
  the shapes at `cicl/cron.py:107` and `:196`.
- Field ranges: minute 0-59, hour 0-23, day-of-month 1-31, month 1-12,
  day-of-week 0-7. Accept `*`, `*/N`, `a-b`, `a-b/N`, comma lists, and the
  three-letter month / day names — the same token grammar `cron.py:65-106`
  accepts.
- **No translation of any kind.** No `to_aws_cron`, no `to_ofelia_cron`, no
  day-of-week remap. `clock.md § Cron format`: the expression passes through to
  the schedule table unchanged.

Carry this WHY comment at the top of the module, verbatim in substance:

> WHY a second cron validator while `cicl/cron.py` still exists: `cron.py` is on
> Mod 116's delete-outright list. Importing its validator would force that mod
> to disentangle a live dependency mid-deletion, which is exactly the coupling
> the 115/116 split exists to avoid. The duplication is **transient and
> self-resolving** — it spans one mod boundary and `cron.py`'s deletion ends it.
> `cron.py`'s translation half (`to_aws_cron`, `to_ofelia_cron`, the
> Sunday-is-1 remap) has no counterpart here and is never resurrected.

## Step 3 — Carry `schedules` onto the compiled service

`src/docex/cicl/compile.py`:

1. `CompiledService` (beside `schedule` at `:507-513`) gains
   `schedules: dict[str, str] | None = None`, with a comment saying it is
   carried verbatim from `infra.yml` because the emitters deliver it
   procedurally (its transfer-table body is an empty marker), and that it is
   `None` for every non-clock service.
2. The role-specific-field loop at `:801-810` currently `continue`s on
   `schedule`. Extend the same skip to `schedules`, with its own comment — do
   **not** merge the two branches into one condition; Mod 116 removes the
   `schedule` arm and a fused condition makes that a rewrite instead of a
   deletion.
3. The construction site at `:1091-1093` sets `schedule=`. Add `schedules=`
   alongside, reading `(svc.model_extra or {}).get("schedules")` and passing it
   through only when it is a dict of `str -> str` (validation has already
   rejected anything else; a malformed value must not reach an emitter).

## Step 4 — Validation

`src/docex/cicl/validate.py`:

1. **New `_validate_clock_services(doc)`**, registered in the validator list at
   `:132` (place it next to `_validate_scheduler_services` — do not modify that
   function). For every core service with `role == "clock"`:
   - `rule_clock_schedules_required` — `schedules` absent, not a mapping, or an
     empty mapping. Message names the service and points at
     `clock.md § What a clock core service is`.
   - `rule_clock_job_name_invalid` — a key that does not match
     `^[A-Za-z_][A-Za-z0-9_]*$`. Message says job names are the dispatch keys
     the clock's controller looks up, so they must be valid identifiers.
   - `rule_clock_cron_invalid` — a value that is not a string, or that
     `cron_expr_issue` rejects. `where` is
     `codebases.<cb>.core_services.<svc>.schedules.<job>`.

   One issue per offending job, not one per service — an author fixing three
   bad crons should see three messages.
2. **Rule 26** (`_validate_service_role_rules`, `:1501-1544`): add a **separate
   clock branch**, `rule_26_replicas_on_clock`, keyed on
   `svc.role == "clock" and "replicas" in svc.model_fields_set`. Message: a
   clock is a singleton (`clock.md § Deployment`), citing `cicl.md § Validation
   Rules` rule 26. **Leave the existing scheduler branch exactly as it is.**
3. **Rule 27**: add `"clock"` to `_NON_WEB_ROLES` (`:1498`). No other change —
   the existing message already interpolates `svc.role`.
4. **Reserved key**: add `"DOCEX_SCHEDULES_YAML"` to `_RESERVED_CORE_ENV_KEYS`
   (`:94-101`), with a comment naming `emit/schedules.py`'s `SCHEDULES_ENV_KEY`
   as the source of truth for the contract and citing `clock.md § How the
   schedule reaches the container` (this mirrors how the `OTEL_*` literals there
   are duplicated from `compile.py:968-970`). Rule 20 then rejects a project
   declaring it in `env:`, `secrets:`, or `config:`.

## Step 5 — `src/docex/emit/schedules.py` — renderer + delivery seam

New module, modelled on `emit/otelcol.py`: pure functions, strings out, no I/O.

**5a. Renderers.**

- `render_schedule_table(svc: CompiledService) -> str` — **the payload**: a flat
  YAML map of job name → cron string, deterministically ordered, with a
  `# Generated by \`docex compile\`. Do not edit by hand.` header.
- `render_schedules_file(compiled: CompiledEnv) -> str` — **the artifact**
  written to `infra/output/<env>/schedules.yml`: a map of
  `<codebase>.<service>` → that clock's flat job map, clocks in sorted order,
  same generated-by header plus the project/env/foundation lines the other
  emitters carry.

Docstring must state the asymmetry and why, because it is the thing a later
reader will try to "fix":

> The artifact is keyed by dotted clock ref; the payload delivered to a clock is
> its bare job map. **File shape ≠ payload shape, deliberately.** Byte-identity
> between the two is only purchasable by injecting the clock's own identity as
> an env var so it can find its own section — which charges the cost in the one
> place that matters most, the entrypoint every downstream project copies, in
> exchange for a property only the compiler cares about. An application must not
> need to know its own name to find its own schedules. The doctrine caps clocks
> at one per codebase-with-schedules (`clock.md § One clock per codebase with
> scheduled work`), so the artifact is a single-entry file in nearly every real
> project.

**5b. The delivery seam.** One function, called by both emitters, which contain
**no foundation test of their own**:

```python
SCHEDULES_ENV_KEY = "DOCEX_SCHEDULES_YAML"


def schedule_env(svc: CompiledService) -> dict[str, str] | None:
    """The env vars carrying this clock's schedule table, or None if not a clock.

    One variable, identical on both foundations, whose value is the LITERAL
    rendered YAML rather than a path to it (clock.md § How the schedule reaches
    the container). Returned UNESCAPED — escaping belongs to each emitter's own
    reader (compose interpolation on fixed, `_hcl_value` on elastic).
    """
```

Returns `{SCHEDULES_ENV_KEY: render_schedule_table(svc)}` for a clock, `None`
otherwise. **No `ScheduleDelivery` dataclass, no `config_key`, no
`mount_target`, no `foundation` parameter** — the operator's ruling is a single
mechanism, and permanently-`None` fields would be a standing invitation to
reintroduce the split.

The delivered value is the clock's **own flat job map**, never the aggregate.

## Step 5c — the two artifacts do different jobs

Guard against a later reader deleting the "unused" file. Say plainly, in the
`render_schedules_file` docstring:

> `schedules.yml` is the **visibility** artifact and `DOCEX_SCHEDULES_YAML` is
> the **delivery** mechanism. Nothing reads the file at runtime, and that is not
> an oversight: it is what makes schedules git-tracked and diff-visible per
> `cicl.md § Compiler Output`, which is one of the reasons schedules live in
> `infra.yml` at all. Do not delete it for being unmounted.

## Step 6 — Fixed delivery (`src/docex/emit/compose.py`)

Anchors: the service loop at `:524`, the `svc.env` merge at `:576-600`.

1. In the service loop, after the `svc.env` merge, call `schedule_env(svc)` and
   merge the result into `block["environment"]` **after** the project's own env,
   so a project key cannot shadow it (rule 20 already forbids the collision;
   this makes the emission order unambiguous rather than relying on it).
2. **Double `$` → `$$` in the value.** This did **not** go away with the
   `configs:` block: compose interpolates `environment:` values exactly as it
   interpolates `configs.content` (see the otelcol note at `:801-806`), and the
   payload is now *always* a compose env value on this foundation. An
   unescaped `$` would reach the container mangled. WHY comment says so
   explicitly, and says that only the *delivered* value is doubled —
   `infra/output/<env>/schedules.yml` keeps the true content.
3. The value is multi-line YAML inside a YAML file. Make sure `_dump_compose`
   emits it as a properly quoted / block scalar that round-trips: parse the
   emitted `docker-compose.yml` back with `yaml.safe_load`, undo the `$$`
   doubling, and the result must parse as the declared job map. If the dumper
   mangles it, fix the emission — do not flatten the payload to a single line to
   dodge the problem.
4. **No top-level `configs:` entry, no mount.** The `configs:` dict at
   `:807-868` is not touched by this mod at all.
5. **Do not touch** the scheduler skip at `:530-536`, the Ofelia block at
   `:815-865`, or the `role != "scheduler"` otelcol gate at `:808-811`. A clock
   is a core service with `role != "scheduler"`, so it already gets its sidecar
   with no change.

## Step 7 — Elastic delivery + deployment percentages (`src/docex/emit/hcl.py`)

1. **Env entry.** In `render_task_definition`, between the
   `_container_env_entries` call (`:331`) and the
   `container_def["environment"] = env_entries` assignment (`:354`), append
   `schedule_env(svc)` as `{"name": ..., "value": ...}` entries and keep the list
   deterministically ordered (re-sort by `name` if the existing entries are
   sorted — match whatever `_container_env_entries` already does). Assign
   `container_def["environment"]` when the merged list is non-empty.

   No escaping here: `_hcl_value` already does `$` → `$$` and `\n` → `\\n` for
   literal strings (module docstring `:87-93`), which is exactly how the
   otelcol YAML literal at `:468-469` survives today. **Do not pre-escape** —
   that would double-escape.
2. **Deployment percentages.** In `render_ecs_service` (`:693-765`), directly
   after `wait_for_steady_state` (`:722`), emit **for `svc.role == "clock"`
   only**:

   ```hcl
     deployment_minimum_healthy_percent = 0
     deployment_maximum_percent         = 100
   ```

   WHY comment must record: ECS's defaults (100 / 200) briefly run two tasks
   during a rolling deploy, and a tick landing in that window **fires twice**.
   Forcing stop-then-start trades a possible double fire for a possible
   **missed** fire — the right trade, because missed fires are already an
   accepted caveat (`clock.md § Caveats`) and jobs must be idempotent
   regardless. Also record that this composes with Mod 114's
   `wait_for_steady_state`: 0/100 is an ordinary recreate deployment, and the
   zero-running-tasks window is a state *during* the deployment rather than one
   the waiter can settle on.

   The existing comment at `:710-714` says no `deployment_configuration` block
   is emitted so ECS defaults apply — amend it to say "for every role but
   `clock`", so it does not become a lie.
3. **Do not touch** `render_scheduled_task` or the `scheduler.amazonaws.com` IAM
   role (`:976-1085`), or the `has_ecs_service` sidecar gate at `:454` — a clock
   emits `ecs_service`, so it gets a sidecar with no change.

## Step 8 — Write the artifact (`run_compile`)

`src/docex/cicl/compile.py:1267-1298`. Inside the per-env loop, **outside** the
fixed/elastic branch. The artifact is written on both foundations even though
**nothing mounts or reads it** — it is the *visibility* half of `clock.md § How
the schedule reaches the container`, and `DOCEX_SCHEDULES_YAML` is the *delivery*
half. Do not skip the write on the grounds that the env var already carries the
payload:

- If the compiled env contains at least one clock, write
  `render_schedules_file(compiled)` to `env_dir / "schedules.yml"` and increment
  `files_written`.
- If it contains none, write nothing (and do not leave a stale file behind — if
  one exists from a previous compile of a project that has since dropped its
  clock, delete it, matching how the emitters treat their own outputs; if the
  existing emitters do **not** clean up stale outputs, do not invent the
  behaviour here — just skip the write, and note it in your report).
- **All four envs.** There is no `test`-env suppression: `clock.md` says nothing
  about a clock is suppressed anywhere. Do not copy the Ofelia `test` guard at
  `compose.py:836-849`.

## Step 9 — Fixtures

Two new fixture projects, modelled on `tests/fixtures/sample_project_scheduler_fixed`
(`project.yml`, `infra/infra.yml`, `infra/secrets/dev.env`). **Do not modify any
existing fixture** — unchanged fixtures are what make the additive claim
checkable.

- `tests/fixtures/sample_project_clock_fixed` — `foundation: fixed`,
  `cicl_version: "3"`.
- `tests/fixtures/sample_project_clock_elastic` — `foundation: elastic`,
  `cicl_version: "3"`, mirroring `sample_project_elastic`'s top-level fields.

Both declare **one codebase `api`** with three core services, so "the clock does
not disturb ordinary services" and "the percentages are clock-only" are both
testable in one compile:

```yml
      web:     { role: web,    port: 8080, networks: [web, internal], uses: [appdb], ... }
      worker:  { role: worker, port: 8081, networks: [internal], health_check_path: /health, uses: [appdb], ... }
      clock:
        role: clock
        command: ["python", "-m", "entrypoints.clock"]
        port: 8082
        networks: [internal]
        health_check_path: /health
        resources: { cpu: 0.25, memory: 512MB }
        uses: [appdb, api.worker]
        schedules:
          nightly_cleanup: "0 3 * * *"
          hourly_rollup: "0 * * * *"
```

plus an `appdb` `relational_db` backing service with `schema_owned_by: api`.
Mirror `clock.md § What a clock core service is` — that block is the doctrine's
own example and the fixture should read as its sibling. Add whatever contract
files the `check` gates require **only if a test exercises them**; compile tests
do not.

## Step 10 — Tests

New `tests/unit/test_clock.py`, structured like `tests/unit/test_scheduler.py`
(fixture copied to `tmp_path`, `run_compile`, parse the emitted files).

**Validation** (build docs in-memory, as `test_scheduler.py` does with its
`_SCHEDULER` dict):
1. A valid clock produces **zero** issues.
2. `schedules` absent → `rule_clock_schedules_required`.
3. `schedules: {}` → same.
4. `schedules` as a list/string → same.
5. Job name `nightly-cleanup` (hyphen) and `2fast` → `rule_clock_job_name_invalid`,
   one issue each.
6. `"0 3 * *"` (4 fields) and `"0 99 * * *"` (out of range) →
   `rule_clock_cron_invalid`, one issue each.
7. `schedules:` on a `worker` → `tt_rule_4_undeclared_field` (assert the
   *existing* rule fires; do not add a new one).
8. `replicas: 2` on a clock → `rule_26_replicas_on_clock`.
9. `web` in a clock's `networks` → `rule_27_web_network_on_non_web_role`.

**Fixed emit** (compile `sample_project_clock_fixed`):
10. The clock is an ordinary compose service — image/build, command,
    `healthcheck`, `restart`, docex project label, logging anchor — and is
    **not** skipped the way a scheduler is.
11. A paired `<identity>-otelcol` sidecar exists for the clock.
12. The schedule table reaches the container **by the delivery mechanism**, not
    by the renderer's return value: read the compiled `docker-compose.yml`, take
    the clock block's `environment.DOCEX_SCHEDULES_YAML`, undo the `$$` doubling,
    and assert the parsed result equals the declared job map exactly. Write this
    against the file, never against `render_schedule_table`.
13. `web` and `worker` in the same file carry no `DOCEX_SCHEDULES_YAML`, and the
    top-level `configs:` block contains only `otelcol_config` — this mod adds no
    config entry.
13a. **The `$` round-trip.** Give a fixture (or an in-test mutation) a schedule
    whose payload contains a literal `$`, and assert the emitted compose value
    carries `$$` where the source had `$`, so the container receives it
    byte-identical after compose interpolation. Compose interpolates
    `environment:` values, so this is a live hazard, not a theoretical one, and
    it is far cheaper to pin here than to diagnose in the field.

**Elastic emit** (compile `sample_project_clock_elastic`):
14. `aws_ecs_task_definition.clock` and `aws_ecs_service.clock` are emitted;
    **no** `aws_scheduler_schedule`, no `aws_lb_target_group` for the clock.
15. Same as (12) against `main.tf`: locate the clock's task-definition
    `DOCEX_SCHEDULES_YAML` entry, undo HCL's `\n` / `$$` escaping, parse, and
    assert it equals the declared job map. Same variable name as fixed — assert
    that too; one name on both foundations is the point of the ruling.
16. The clock's `aws_ecs_service` carries **all three** of
    `deployment_minimum_healthy_percent = 0`, `deployment_maximum_percent = 100`,
    and `wait_for_steady_state = true`. Assert them together in one test — the
    interaction is the point.
17. `web` and `worker` services carry `wait_for_steady_state` and **neither**
    percentage.
18. The clock has an OTel sidecar container in its task definition.

**Artifact:**
19. `infra/output/<env>/schedules.yml` exists for **all four** envs on both
    foundations, is keyed by dotted clock ref (`api.clock`), and round-trips to
    the declared jobs.
20. A project with no clock (`sample_project`) emits no `schedules.yml`.

**Elastic release path** (prove the deployment interaction rather than reasoning
about it, per the C.O.'s instruction). In
`tests/unit/test_service_connect_reconcile.py`, add a fixture mutation that
inserts a clock core service (`uses: [appdb, api.worker]`) into
`sample_project_elastic` and drive `_release_elastic` through the existing
`_run` harness against `FakeAWSClient`. Assert the release completes and the
clock is treated as an **ordinary** service by the reconcile — it appears in the
same code paths as `web`/`worker`, with no role special-casing, and the redeploy
predicate applies to it on the same terms. Do not weaken or re-shape any
existing test in that module.

**Real compose interpolation** (integration, `@pytest.mark.integration`). The
unit test in (13a) pins what the *emitter writes*; this pins what *compose
reads*. `docker compose` is already available to the integration suite
(`tests/integration/test_up_down_real.py:29-52` runs it against a compiled
`docker-compose.yml`). Add a test that compiles the fixed clock fixture and runs
`docker compose -f <compiled> config`, then asserts the clock's resolved
`DOCEX_SCHEDULES_YAML` parses to the declared job map with a **single** literal
`$` where the source had one. `config` starts no containers, so this is cheap.
If `docker` is unavailable in the environment, skip the test the way the
existing integration tests do — do not delete it.

**Additive claim:**
21. `tests/unit/test_scheduler.py` and `test_cron.py` must pass **unmodified**.
    If either needs a change, stop and report — that is the additive claim
    failing, not a test needing an update.

## Step 11 — Verification

1. `pytest tests/unit -q` — green. Report the count delta (1006 + your new
   tests) and account for it.
2. `pytest -m integration -q` — no worse than 17 passed / 1 failed, with the
   failure being the known Mod 119 build bug.
3. **Compile both new fixtures by hand and read the output.** Print the clock's
   compose block, the top-level `configs:` section, the clock's task-definition
   env entry and its `aws_ecs_service` block, and `schedules.yml`. Paste the
   relevant excerpts into your report — the claim under review is *delivery*.
4. **Prove the additive claim by diff.** Compile
   `sample_project_scheduler_fixed` and `sample_project_scheduler_elastic` into
   a temp copy, `git stash` your work, compile them again into a second temp
   copy, restore, and diff the two output trees. **Expect zero differences.**
   Report the diff (or its emptiness) explicitly.

## Out of scope — do not do these

- Any change to `role: scheduler` machinery (Mod 116).
- The `check`-step assertion that every declared job name has a binding in the
  clock's dispatch table (Mod 117 — no smoke project has a dispatch table yet).
- `doctrine_excerpts/index.yml` entries (Mod 118's explicit decision).
- Smoke projects under `test_projects/`, `PRE_CUT_CHECKLIST.md`, the upgrade
  guide (Mod 117).
- Core planning docs (`docex/plans/core/*.md`) — the mod cycle's documentation
  step updates those, not you.
- Any edit to a doctrine file under `doctrine/`. If you believe the doctrine is
  wrong or silent on something you need, **stop and report**.

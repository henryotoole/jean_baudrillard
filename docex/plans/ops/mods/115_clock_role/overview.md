# Mod 115 — `role: clock` in the compiler (additive)

Teach the compiler the `clock` core-service role that Mod 112 wrote into the
doctrine: a new role table, the `schedules:` field with its validation, a
schedule-table renderer, delivery of that table to the container on both
foundations, and the elastic stop-then-start deployment percentages.

**Purely additive.** `role: scheduler` and everything under it — `cicl/cron.py`,
the Ofelia emitter, `scheduled_task`, `scheduler_only_services`, the
`tables/roles/scheduler.yml` table — are not touched. Mod 116 deletes them. At
this mod's boundary both roles compile and the suite is green.

Rule of record: [`doctrine/infrastructure/specifics/clock.md`](../../../../doctrine/infrastructure/specifics/clock.md),
plus `cicl.md`'s `schedules` field row (`:149`), `replicas` row (`:148`) and
rules 26/27 (`:557-558`). Where the advance's design record
(`clock_core_service.md`) and the doctrine differ, the doctrine wins.

**One doctrine edit is in scope**, approved by the operator with the Q1 ruling:
`clock.md § How the schedule reaches the container` described two per-foundation
delivery mechanisms, which the ruling supersedes. It is rewritten to the single
mechanism and states the contract. No other doctrine file is touched.

## What lands

### 1. `tables/roles/clock.yml` — a new role table

Modelled on `worker.yml`, not on `scheduler.yml`. A clock is an ordinary
long-running core service:

- `emits.fixed: [compose_service]`;
  `emits.elastic: [task_definition, ecs_service, container_definition]`.
  No `target_group` (a clock takes no ingress), no `scheduled_task`.
- `health_check_path` translates exactly as on `worker`: a compose
  `healthcheck:` on fixed, the ECS container-level `healthCheck` on elastic.
  A wedged clock gets its task killed and replaced.
- `provides: {host, port}` mirroring `worker`. A clock is consumer-only in
  practice, but "no exemptions" means nothing structurally special: if a magic
  ref names `api.clock.host`, it resolves.
- `naming: ecs`.
- `schedules` declared as a role-specific field with **empty per-foundation
  translation bodies**. The declaration is what makes rule 4
  (`tt_rule_4_undeclared_field`) reject `schedules:` on every other role — the
  doctrine's "rejected on every other role" is enforced by the existing
  mechanism, not by a new rule. The value is handled procedurally by the
  emitters, exactly as `scheduler`'s `schedule` marker is today.

### 2. Model + validation

`CoreService` keeps `schedules` in `model_extra` (like every role-specific
field). `CompiledService` gains `schedules: dict[str, str] | None`, carried
verbatim from `infra.yml` alongside the existing `schedule` carry
(`compile.py:507-513`, `:801-810`).

New validator (`_validate_clock_services`), reporting per-issue:

| Rule id | Condition |
| --- | --- |
| `rule_clock_schedules_required` | `role: clock` with `schedules` absent, not a mapping, or empty. |
| `rule_clock_job_name_invalid` | A job name that is not a valid identifier (`[A-Za-z_][A-Za-z0-9_]*`). These are dispatch keys the clock's controller looks up. |
| `rule_clock_cron_invalid` | A value that is not a well-formed 5-field cron expression, or is not a string. |

Rule 26 (`_validate_service_role_rules`) gains a **clock branch**
(`rule_26_replicas_on_clock`) alongside the existing scheduler branch, which
stays until Mod 116. Rule 27's `_NON_WEB_ROLES` gains `clock`.

Two keys are added to `_RESERVED_CORE_ENV_KEYS` (`validate.py:94-101`) —
see the delivery contract below — so a project cannot declare them itself
(rule 20).

### 3. `emit/schedules.py` — the renderer

Modelled on `emit/otelcol.py`: functions in, strings out, no I/O.

- `render_schedule_table(svc) -> str` — one clock's payload: a flat YAML map of
  job name → cron string, header-commented. This is what reaches the container.
- `render_schedules_file(compiled) -> str` — the aggregate written to
  `infra/output/<env>/schedules.yml`, a map of `<codebase>.<service>` → that
  clock's flat job map.

`run_compile` (`compile.py:1267-1298`) writes `schedules.yml` into
`infra/output/<env>/` for **every** env and **both** foundations whenever the
env has at least one clock, and writes nothing when it has none. Doctrine:
"nothing about a clock is suppressed anywhere" — there is no `test`-env
carve-out of the kind Ofelia needed.

### 4. Delivery — one literal env var, both foundations

**Operator ruling (Q1): one variable, both foundations.** The clock's own job
map is delivered in `DOCEX_SCHEDULES_YAML`, whose value is the **literal
rendered YAML** rather than a path to it. No mount, no path variable, no
per-foundation branch in any entrypoint. `clock.md § How the schedule reaches
the container` was written against the superseded two-mechanism assumption and
is rewritten by this mod to state the single mechanism and the contract — the
one doctrine edit in scope.

| Foundation | Where the variable is emitted |
| --- | --- |
| fixed | a compose `environment:` entry on the clock's service block |
| elastic | a task-definition env entry beside the sidecar's `OTEL_CONFIG_YAML` (`hcl.py:460-483`) |

The seam is one function — `schedule_env(svc) -> dict[str, str] | None` — called
by both emitters, which contain no foundation test of their own. It returns the
**unescaped** payload; escaping belongs to each emitter's reader. There is no
`ScheduleDelivery` dataclass: with a single mechanism, `config_key` and
`mount_target` would be permanently `None` and a standing invitation to
reintroduce the split.

**The `$` → `$$` doubling survives the ruling and gets sharper.** Compose
interpolates `environment:` values exactly as it interpolates `configs.content`,
and the payload is now *always* a compose env value on fixed rather than file
content — so an unescaped `$` is a live hazard on the delivery path itself. The
doubling is applied to the delivered value only; `infra/output/<env>/schedules.yml`
keeps the true content. Two tests pin it: a unit test that the emitter writes
`$$`, and an integration test that runs `docker compose config` and reads back a
single literal `$`. On elastic no pre-escaping is done — `_hcl_value` already
handles `$` and `\n` for literals (`hcl.py:87-93`), which is how the otelcol
YAML survives today.

**The artifact is not the delivery.** `schedules.yml` is still rendered on both
foundations even though nothing mounts or reads it: it is the *visibility* half
(git-tracked, diff-visible per `cicl.md § Compiler Output` — one of the reasons
schedules live in `infra.yml` at all), and the env var is the *delivery* half.
Both the renderer docstring and `compiler.md` say so, so nobody later removes
the "unused" file.

Both injections live in the **emitters**, not in `compile.py`'s env builder.
That keeps `cicl/` free of emitter concerns.

### 5. ECS deployment percentages — `role: clock` only

`render_ecs_service` (`hcl.py:693-765`) emits, for a clock and nothing else:

```hcl
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
```

with a WHY comment recording the trade: ECS's defaults (100/200) briefly run two
tasks during a rolling deploy and a tick landing in that window fires twice;
stop-then-start trades a possible **double fire** for a possible **missed
fire**, which is the right trade because missed fires are already an accepted
caveat (`clock.md § Caveats`) and jobs must be idempotent regardless.

**Composition with Mod 114's `wait_for_steady_state = true`** (`hcl.py:722`),
which is emitted for every service: the two are orthogonal and do not deadlock.
`wait_for_steady_state` waits for the deployment to *complete* with
`runningCount == desiredCount`; 0/100 makes ECS stop the old task before
starting the new one, which is an ordinary "recreate" deployment that converges
normally. The window with zero running tasks is a state *during* the
deployment, not a terminal state the wait can settle on. The two land in the
same function and are emitted as adjacent, independent attributes.

## Design decisions taken here

**Payload is the per-clock slice; the file is the aggregate.** With one clock
(the overwhelming case) the difference is one key of nesting. The alternative —
ship the whole file to every clock and inject a `DOCEX_CLOCK=<codebase>.<service>`
identity var so it can find its own section — buys byte-identity between file
and payload at the cost of a third env var, an app-side lookup, and every
clock seeing every other codebase's schedule. The flat map is the simplest
possible application contract and matches the shape the doctrine's own
`schedules:` example already has. The shape difference is documented in the
renderer's docstring.

**A fresh 5-field cron validator, not an import from `cron.py`.**
`cicl/cron.py` is on Mod 116's delete-outright list. Importing
`cron_validation_issue` from it would force 116 to salvage half a module
instead of deleting one, converting a pure deletion into a partial rewrite —
which is the exact property the 115/116 split exists to protect. Mod 115
instead adds a small, self-contained `cicl/cron_expr.py` (5-field split +
per-field range/token check, no dialect translation of any kind). The
duplication is real and lasts exactly one mod; `cron.py`'s translation half —
`to_aws_cron`, `to_ofelia_cron`, the Sunday-is-1 remap — has no counterpart in
the new module and is never resurrected. **Mod 116's delete list is unchanged
by this mod.**

**No `check.py` changes.** A clock is neither a `uses` target nor on the `web`
network, so it is in neither arm of the provider set — the contract and
health-fan-out gates already exclude it without a role test, which is what "no
exemptions" is supposed to look like. The `_CONTRACT_FORMAT_BY_ROLE` map is
deliberately left without a `clock` row: nothing should `uses:` a clock, and the
existing `openapi` fallback is an honest answer if something does.

**No `orchestrate/` changes.** A clock is a long-running container in every env,
so `scheduler_only_services` and the `up`/`down` special cases do not apply to
it.

## Tests

New `tests/unit/test_clock.py`, plus two new fixture projects
`tests/fixtures/sample_project_clock_{fixed,elastic}` modelled on the scheduler
fixtures (a `web` core service alongside the clock, so "the clock does not
disturb ordinary services" is testable). **Existing fixtures are not modified**
— that is what keeps the additive claim checkable.

1. **Validation** — schedules missing / empty / not a map; a bad job name; a
   4-field cron; an out-of-range field; `schedules:` on a `worker` (rule 4);
   `replicas:` on a clock (rule 26); `web` in a clock's `networks` (rule 27).
   A valid clock produces zero issues.
2. **Role table** — `clock` loads from the bundled tables and appears in
   `docex roles`.
3. **Fixed emit** — the clock is an ordinary compose service (image, command,
   healthcheck, restart, labels, logging); it has a paired `-otelcol` sidecar;
   the top-level `configs` carries `schedules_<identity>` whose content parses
   back to the declared job map; the clock's block mounts it at
   `/etc/docex/schedules.yml`; `DOCEX_SCHEDULES_PATH` is in its `environment`
   and `DOCEX_SCHEDULES_YAML` is not.
4. **Elastic emit** — `aws_ecs_task_definition` + `aws_ecs_service` are emitted
   and `aws_scheduler_schedule` / `aws_lb_target_group` are not; the app
   container's `environment[]` carries `DOCEX_SCHEDULES_YAML` whose unescaped
   value parses back to the declared job map; the sidecar is present; the
   service block carries both deployment percentages **and**
   `wait_for_steady_state`.
5. **Scoping** — a `web` and a `worker` service in the same fixture carry
   neither deployment percentage and neither schedule env var.
6. **Output file** — `infra/output/<env>/schedules.yml` is written for all four
   envs on both foundations, keyed by dotted clock ref, and is absent from a
   project that declares no clock.

## Verification (beyond pytest)

- Compile both new fixtures by hand and **read** `docker-compose.yml`,
  `main.tf`, and `schedules.yml`. The claim under test is *delivery* — that the
  table reaches the container through the compose mount and the task-def env
  entry — not the renderer's return value.
- Compile `sample_project_scheduler_{fixed,elastic}` before and after and
  **diff the output**. Byte-identical output is this mod's additive claim and
  what makes Mod 116 a clean deletion.
- `pytest tests/unit` green with the delta explained; `pytest -m integration`
  no worse than 17 passed / 1 failed (`test_build_refreshes_dist_after_src_edit`
  is the known `docex build` bytecode-residue bug, assigned to Mod 119).

## Deliberately not in scope

- **Anything scheduler.** Untouched, still working at this mod's boundary.
- **The `check`-step assertion that every declared job name has a binding in the
  clock's dispatch table.** Deferred to **Mod 117**, which is when a smoke
  project first has a dispatch table to read. `clock.md § How the schedule
  reaches the container` states the check as a capability ("can assert"), so
  nothing in the doctrine goes unimplemented by deferring it.
- **`doctrine_excerpts/index.yml`.** Whether `clock` earns a resource entry is
  Mod 118's explicit decision per the advance plan's logged-drift table.
- **Smoke projects, the upgrade guide, `PRE_CUT_CHECKLIST.md`** — Mod 117.
- **`describe`/`dag`/`llm` surfacing of schedules.** Not required by the
  doctrine; not added.

## Design questions

**Status: all three resolved.** Q2 and Q3 approved by the C.O.; **Q1 ruled by
the operator — Variant A**, one variable on both foundations, with the contract
stated in `clock.md` (doctrine). The delivery section above is written to the
ruling and the seam is collapsed accordingly.

Two documentation obligations recorded here so they are not lost at the
documentation step (they land in `docex/plans/core/compiler.md`, not in
`implementation.md`): the schedules artifact's keying, stating explicitly that
**file shape ≠ payload shape** and why, so a later reader does not "fix" it; and
that the `cron_expr.py` / `cron.py` duplication is **expected and
self-resolving** at Mod 116 rather than something that mod should reconcile.

**1. The delivery-contract names, and where they are written down.**
**RULED BY THE OPERATOR — Variant A.** One variable, `DOCEX_SCHEDULES_YAML`,
carrying the literal rendered YAML on both foundations; no mount, no path
variable, one branch in every entrypoint. The contract is stated in **doctrine**
(`clock.md § How the schedule reaches the container`), not only in
`compiler.md`, on the `telemetry_infra.md` precedent that names
`OTEL_CONFIG_YAML` in prose.

The question was raised because the section named the two *mechanisms* but
neither the variable nor the path, leaving the compiler↔application contract
without a durable statement — which Mod 117's reference entrypoint and every
downstream project's `entrypoints/clock.py` must read. The ruling both names it
and simplifies it: the section is rewritten by this mod to describe one
mechanism, and `DOCEX_SCHEDULES_YAML` is reserved under rule 20.

**2. Schedule-table shape when a project has more than one clock.**
**APPROVED** — aggregate file keyed by dotted clock ref; per-clock flat-map
payload. The governing reason, per the C.O.: *an application must not need to
know its own identity in order to find its own schedules.* A `DOCEX_CLOCK`
identity var would buy byte-identity between file and payload and charge for it
in the one place that matters most — the entrypoint every downstream project
copies — in exchange for a property only the compiler cares about. The
asymmetry is also small in practice: the doctrine caps clocks at one per
codebase-with-schedules, so the aggregate is a single-entry file in nearly every
real project.

**3. The one-mod cron-validator duplication** (`cicl/cron_expr.py` alongside
`cicl/cron.py`). **APPROVED.** The 115/116 split exists so that 116 is a *pure*
deletion; importing `cron_validation_issue` from a module on 116's delete list
would force that mod to disentangle a live dependency mid-deletion, which is
exactly the coupling the split avoids. The duplication is transient — it spans
one mod boundary and `cron.py`'s deletion resolves it.

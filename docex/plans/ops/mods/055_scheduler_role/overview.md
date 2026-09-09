# Mod 055 — Scheduler role

Second mod of the `001_skill_update` advance. Closes the planner's "No Scheduler
Role" item: the doctrine has no way to run a project's own code on a recurring
schedule. This mod adds a bundled `scheduler` role.

## What it is

A `scheduler` service is a **core service** (the project's image, its own code)
whose `role: scheduler`. It runs one `command` on a 5-field cron `schedule` and
exits — a cron job in the project's image. Not web-facing; no long-running
container/ECS service. New `infra.yml` surface: the `schedule:` field (and
`command:`, which already existed, becomes required for this role).

```yml
core_services:
  nightly_cleanup:
    role: scheduler
    schedule: "0 3 * * *"
    command: ["python", "-m", "jobs.cleanup"]
    resources: { cpu: 0.25, memory: 512MB }
    networks: [internal]
    env: { DATABASE_HOST: ${backing_services.appdb.host}, ... }
    depends_on: [appdb]
```

## Design (from discussion)

- **Fixed:** one `mcuadros/ofelia` container per scheduler service, configured via
  a rendered INI (delivered through compose `configs:`, like the OTel sidecar),
  mounting the docker socket and launching the job as a one-off container
  (`job-run`, `delete=true`) on schedule.
- **Elastic:** **EventBridge Scheduler** (`aws_scheduler_schedule`) → ECS
  `RunTask` on a reused `task_definition`, plus a per-service scheduler-invocation
  IAM role. No `ecs_service`.
- **Schedule:** standard 5-field cron in `infra.yml`, translated by the compiler
  to AWS `cron(...)` (6-field, `?`-day rule, **day-of-week 0–6→1–7 remap**) for
  elastic and to ofelia's `0 `-prefixed 6-field (seconds) for fixed.
- **No OTel sidecar** on either foundation (sidecars pair only with long-running
  services); job-level SDK telemetry is deferred. Diagnostics flow to
  `docker logs` (fixed) / CloudWatch (elastic).
- **Env/secret split (fixed):** non-secret resolved env inlined into the ofelia
  INI `environment`; secrets delivered by mounting the env's `.env` and sourcing
  it in a `sh -c '. /run/job.env && exec …'` command wrapper (mirrors the fixed
  migrate one-off). Elastic gets secrets free via the reused task-def `secrets[]`.

## Doctrine status (landed; rule-of-record first)

- **New** `doctrine/infrastructure/specifics/scheduler.md` — the full per-foundation
  mechanism, cron translation, env/secret delivery, lifecycle, caveats.
- `cicl.md § Service Fields` — `command` noted as required for `scheduler`.
  `schedule` is **not** in the general field table by design (operator's call):
  it is role-specific, so it lives in the transfer table and is surfaced by
  `docex role scheduler`.
- `transfer_tables.md` — `scheduler/container` added to the canonical-roles list;
  `scheduled_task` added to the documented elastic emit-destination set.

`schedule` being a role-specific transfer-table field means validation rule 4
("every role-specific field used must be declared in the engine's `fields:`")
gives "schedule rejected on non-scheduler roles" for free; "required on scheduler"
is an added compile check.

## Why this is large but one coherent mod

It touches a new bundled role file, a new emit destination + renderer (elastic),
a new compose emit path (fixed ofelia), a new cron-translation module, model +
validation, and tests — but all of it is the single feature "run project code on
a schedule." It reuses the existing `task_definition` machinery (elastic) and
the `configs:`/one-off-container patterns (fixed) rather than inventing new ones.

## Out of scope / deferred (documented in scheduler.md)

- Job-level SDK telemetry (batch-flush-before-exit).
- Backfill/catch-up of missed fires; per-job overlap guard.
- Consolidating the elastic invocation role to one-per-env (v1 is one-per-service).
- `test`-time scheduler suppression.
- Adding a scheduler to the smoke-test projects — left for the pre-cut smoke walk
  if the operator wants real-infra coverage; this mod proves the compiler via
  unit tests + a compile against a scratch fixture.

## Artifacts touched

- `doctrine/**` — see above (rule of record).
- `tables/roles/scheduler.yml` — new bundled role.
- `src/docex/cicl/transfer.py` — `scheduled_task` in `EMIT_DESTINATIONS["elastic"]`.
- `src/docex/cicl/cron.py` (new) — 5-field → AWS / ofelia translation + validation.
- `src/docex/cicl/validate.py` — scheduler `schedule`/`command` required rules.
- `src/docex/cicl/compile.py` — carry `schedule`; mark scheduler handling.
- `src/docex/emit/hcl.py` — `render_scheduled_task` (+ registry); omit sidecar for
  non-`ecs_service` task defs.
- `src/docex/emit/compose.py` — ofelia container + INI render for scheduler
  services; env/secret split.
- `tests/**` — cron translation, fixed ofelia emit, elastic scheduled_task emit,
  validation.

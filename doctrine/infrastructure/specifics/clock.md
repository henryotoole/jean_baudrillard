---
stratum: conditional
---

# Clock

This file answers one question: **how does the doctrine expect a project to schedule recurring work?**

The answer is a `clock` core service. It is an ordinary long-running singleton core service — a compose service on fixed, a `task_definition` + `ecs_service` on elastic — whose `command` invokes a clock entrypoint. That entrypoint reads a compiler-delivered schedule table and, when a job is due, calls a driving port that **enqueues**. The work itself happens in a `worker`.

There is no separate scheduling primitive. A schedule is a property of an *invocation*, not of a deployment, and a clock is simply the invocation that owns the cron loop.

Not to be confused with the [`Clock` driven port pattern](../../hexagonal_architecture/hex_overview.md#driven-port--adapter-patterns), which abstracts a module's access to the current time. The two are unrelated: this page is about a core service that *fires* scheduled work, not about reading the wall clock.

## What a clock core service is

```yml
codebases:
  api:
    core_services:
      clock:
        role: clock
        command: ["python", "-m", "entrypoints.clock"]
        networks: [internal]
        resources: { cpu: 0.25, memory: 512MB }
        uses: [appdb, api.worker]
        schedules:
          nightly_cleanup: "0 3 * * *"
          hourly_rollup: "0 * * * *"
```

`schedules:` is a map of **job name → cron expression**. It is required on a `clock` and rejected on every other role.

A clock is subject to every ordinary [core service](../cicl.md#core-services) rule, with **no exemptions**:

- **Health.** Its container runs `./health.sh clock` like any other core service. Because it owns a loop, [healthchecks.md](../healthchecks.md#what-the-probe-must-actually-check) already prescribes the tick-based liveness rule — record a monotonic tick each iteration, fail when stale, tick at least every 10 s even when idle, 30 s staleness threshold. A cron loop with a bounded ≤10 s wait is the natural way to write one, so the existing rule fits without amendment. A wedged clock fails its own probe. It is off the `web` network, so it declares no `health_check_path` and serves no HTTP at all ([rule 33](../cicl.md#validation-rules)).
- **Telemetry.** It gets a paired OTel collector sidecar like any other core service, so job telemetry is ordinary telemetry and the trace originates in the process that fired the job.
- **Contract.** It declares no [surfaces](../cicl.md#surfaces), so it has no contract. A clock is driven by time rather than from outside, which is exactly what having no surface means; and since only a surface-declaring core service can be a `uses` target, nothing can use a clock.
- **Networks.** It may not declare `web` ([rule 27](../cicl.md#validation-rules)). It serves no public boundary.
- **Replicas.** It may not declare `replicas` ([rule 26](../cicl.md#validation-rules)) — see [Deployment](#deployment).
- **`dev` and `test`.** A normal container with the normal bind mounts, in every environment. Nothing about a clock is suppressed anywhere.

## The clock defers; it does not work

**A clock's only job is to call a driving port that enqueues.** It performs no work itself.

The reason is that **only the codebase that owns a schema may write to it.** The doctrine's queue pattern is a library-backed queue whose tables are created by the schema-owning codebase's `migrate.sh` and declared by [`schema_owned_by`](../cicl.md#service-fields). Anything else writing to those tables is a non-owner writing an owned schema, hand-rolling SQL against a library's internal structures — the coupling [hex_overview.md § Shared Clients](../../hexagonal_architecture/hex_overview.md#shared-clients) forbids of an adapter, hoisted into infrastructure where no adapter can absorb the break. The library bumps its schema and the clock silently stops enqueueing.

So enqueueing must be an in-process call by code in the codebase that owns the schema, which is exactly what a core service of that codebase can do.

The rule earns its keep beyond that, too. A clock is a singleton with no replicas and no queue-level retry; heavy work run inside it has no retry story and no horizontal headroom. Deferring puts the work where retry and concurrency already exist.

The consequence — **a codebase with no queue cannot have scheduled work** — is correct pressure rather than a gap. It is also why "run an arbitrary argv on a schedule" is no longer available: scheduled work must be an operation on a driving port, which forces it into the composed, observable, tested application instead of a side door. Argv-against-the-image survives where it belongs, in the per-codebase [exec container](./exec_service.md) and `migrate.sh`.

## One clock per codebase with scheduled work

Not one per project. Codebases never share code, so a clock can only enqueue into its own codebase's queue. **Cross-codebase scheduling is out**: a codebase that needs scheduled work declares its own clock.

For most projects exactly one codebase has scheduled work, so this is largely theoretical — but it is a genuine narrowing, and it is stated here rather than left to be discovered.

## Architecture

Every element below is already doctrine; a clock is a composition of existing pieces, not a new pattern.

```
entrypoints/clock.py        runtime host — the cron loop
  → ContJobsCron            driving adapter: job name → port method
    → ContJobs              driving port (shared with ContJobsHttp, ContJobsCli)
      → alogic
        → QueueJobs         driven port — canonical `Queue` pattern
          → QueueJobsProcrastinate
```

The cron loop belongs to the **entrypoint**, not to an adapter: per [internal_dependency_rules.md § Entrypoints](../../hexagonal_architecture/internal_dependency_rules.md#entrypoints) the runtime host is the entrypoint's job, and a cron loop is the same species as a broker's consume loop. `ContJobsCron` is a real driving adapter rather than ceremony — it owns the job-name → port-method dispatch table and the fired/succeeded/failed translation, which keeps the entrypoint thin enough to satisfy the standing rule that an entrypoint needing its own test is doing too much. `QueueJobs` is the canonical [`Queue`](../../hexagonal_architecture/hex_overview.md#driven-port--adapter-patterns) driven pattern, and `Cron` is a canonical [controller mechanism](../../hexagonal_architecture/hex_overview.md#controller-mechanism).

**Side effect worth having.** Because the driving port is shared with the HTTP and CLI controllers, every scheduled job is also reachable over HTTP and on the command line. Firing a scheduled job by hand in `dev` stops being a special path.

## Cron format

`schedules:` values are **bare 5-field cron expressions** — `minute hour day-of-month month day-of-week` — in **UTC**.

There is **no dialect translation anywhere**. The compiler passes the expression through to the schedule table unchanged; whatever cron library the codebase uses parses it directly. This is a consequence of the clock being project code rather than a cloud primitive, and it removes an entire class of bug: no 6-field forms, no `?`-day substitution, no provider-specific day-of-week renumbering.

Job names are identifiers and must be valid as such — they are the dispatch keys the clock's controller looks up.

## How the schedule reaches the container

Two things happen, and they serve different purposes.

**Visibility.** The compiler renders `infra/output/<env>/schedules.yml` from the `schedules:` blocks — an aggregate of every clock in the environment, keyed by clock. Being compiler output, it is git-tracked and diff-visible per [cicl.md § Compiler Output](../cicl.md#compiler-output), so a schedule change shows up in review as an infrastructure change. Nothing reads this file at runtime; it exists so an operator can see what is scheduled.

**Delivery.** A clock receives its own job map — not the aggregate — in the environment variable `DOCEX_SCHEDULES_YAML`, whose value is the **literal rendered YAML** rather than a path to it. The variable is identical on both foundations: a compose `environment:` entry on fixed, a task-definition env entry on elastic. This is the same literal-env pattern the OTel sidecar's config already uses on elastic (see [telemetry_infra.md § Config Delivery](./telemetry_infra.md#config-delivery)), applied to both foundations rather than split between them, so a clock entrypoint reads one variable and parses it — no file to locate, no mount, no per-foundation branch.

`DOCEX_SCHEDULES_YAML` is doctrine-injected and reserved: a project may not declare it in its own `env:`, `secrets:`, or `config:` blocks ([rule 20](../cicl.md#validation-rules)). Cron expressions never enter application code.

**A clock validates its own schedule at startup and refuses to start if it cannot honour it.** Before entering its loop, the clock compares every name in `DOCEX_SCHEDULES_YAML` against its own dispatch table and exits non-zero if any name has no binding, logging both the offending names and the set the image implements. A schedule naming a job nobody implements therefore fails the **deploy**, visibly, while an operator is watching — rather than surfacing hours later as a logged failure on the job's first fire. The image is the only thing that knows what it implements, so the image is what asserts it.

The reverse direction is deliberately **not** checked: a job that is bound but unscheduled is legitimate, because the driving port is shared and a job reachable only over HTTP or CLI is a valid design.

## Deployment

On **elastic**, a `clock` service is emitted with `deployment_minimum_healthy_percent = 0` and `deployment_maximum_percent = 100`, forcing **stop-then-start**.

This is deliberate and applies to `role: clock` alone. ECS rolling-deploy defaults (minimum healthy 100%, maximum 200%) briefly run two tasks, and a tick landing in that window fires twice. Stop-then-start trades a possible **double fire** for a possible **missed fire** during a deploy. That is the right trade: missed fires are already an accepted caveat below, and jobs are required to be idempotent regardless.

`replicas` is forbidden on a clock for the same reason. A clock is a singleton.

## Caveats

- **No backfill or catch-up.** A missed fire — host down, task replacement, a deploy window — is not retroactively run. The clock fires forward-only.
- **No per-job concurrency guard.** If a job's runtime exceeds its interval, a second fire can occur before the first completes. Since a clock only enqueues, this means a duplicate *enqueue*, which is why jobs must be idempotent. Guard at the queue if a job genuinely cannot overlap.
- **A clock is invisible to staging tests.** It is not on `web`, so the stage tester cannot reach it by any route. This is no longer a special case: [staging tests](../tests.md#staging-tests) assert nothing about any core service's liveness, and every core service's health — a clock's included — is read from the orchestrator by `./bin/docex stagetest` before the tester runs. A wedged clock fails its container probe, is restarted, and fails the release if it stays down.
- **A scheduled job may fire before migrations have run.** Nothing gates a core service's startup on its backing services, and migrations run *after* the stack is up: in `dev` and `test` on both foundations ([`migrations.md § Invocation Timing`](./migrations.md#invocation-timing)), and after `tofu apply` on an elastic env's [first release](./migrations.md#first-time-release-of-an-env) — where a clock is **guaranteed** to meet the window rather than merely liable to. Because a clock fires on its own schedule rather than in response to a request, it is the service most likely to reach a cold schema first, and a `relation "…" does not exist` stack trace in a clock's log on a first bring-up is expected rather than a fault. Recovery is automatic: the loop treats a failed fire as a failed fire and not a failed loop, so the job retries on its own next slot — no operator action, and no effect on the clock's health probe. **The obligation this places on a job is that a fire must tolerate a cold schema**: it may fail before doing anything at all, and the next attempt must be able to proceed as if it had never been made.

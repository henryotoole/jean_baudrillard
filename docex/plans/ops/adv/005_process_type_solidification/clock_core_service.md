# Retire `role: scheduler`; the clock becomes a core service

A design record for deleting the `scheduler` core-service role and replacing it
with `role: clock` — a long-running singleton core service that reads a
compiler-delivered schedule table and defers work onto its own codebase's queue.

> **Status.** **Design settled; two minor open questions** (see
> [Open questions](#open-questions)). Breaking — every `infra.yml` declaring a
> `scheduler` service must be rewritten and the codebase must grow a clock
> entrypoint, so this rides the same `cicl_version` cut as the other breaking
> work in this advance. Touches CICL, contracts, transfer tables, resident
> hexagonal doctrine, `docex`, and `scheduler.md` (which mostly deletes).

## The change

Four moves, taken together:

1. **`role: scheduler` is deleted.** Not deprecated — removed. With it go the
   `scheduled_task` emit destination, the per-service scheduler-invocation IAM
   role, the Ofelia trigger container, and the whole env/secret delivery
   apparatus in
   [`scheduler.md`](../../../../doctrine/infrastructure/specifics/scheduler.md).
2. **`role: clock` replaces it** — an ordinary long-running core service, one
   per codebase that has scheduled work, whose `command` invokes a clock
   entrypoint. It is a container on both foundations: a compose service on
   fixed, `task_definition` + `ecs_service` on elastic.
3. **Schedules are declared in `infra.yml`** on the clock core service and
   delivered to the container by the compiler, using the OTel sidecar's existing
   config-delivery mechanism.
4. **The clock defers; it does not work.** Its only job is to call a driving
   port that enqueues. The work happens in a `worker`.

## Motivation

`role: scheduler` is a process type that isn't a process, and every exclusion
carved out for it traces to that one fact:

| Carve-out | Where |
| --- | --- |
| Exempt from `/health` | [`contracts.md`](../../../../doctrine/infrastructure/contracts.md#health-checks) — "no long-running container to probe" |
| May not be a `consumes` target | [`cicl.md`](../../../../doctrine/infrastructure/cicl.md#validation-rules) rule 25 |
| May not declare `replicas` | rule 26 |
| May not declare the `web` network | rule 27 |
| No OTel sidecar → job telemetry **deferred on both foundations** | [`telemetry_infra.md § Task-Level Resource Allocation`](../../../../doctrine/infrastructure/specifics/telemetry_infra.md#task-level-resource-allocation) |
| Trigger suppressed entirely in `test` | `scheduler.md § Caveats` |
| A scheduler-only codebase is the one shape no compose service builds | `scheduler.md § Fixed Foundation` |
| In `dev` the job runs the baked `dev`-stage artifact, not the bind-mounted `dist/` | ditto |

The last two are the tell. A cron schedule has metastasized into the build and
dev-iteration paths, which is not where a schedule belongs.

The root cause is historical: **a schedule is a property of an invocation, not of
a deployment**, and `infra.yml` modelled it as a deployment because before core
services split from codebases there was no other slot. That constraint is gone.
This advance is where it gets collected.

## The decisive constraint: only the codebase may enqueue

The obvious redesign — a `scheduler` **backing service** holding the clock and
poking core services over their contract boundaries — founders on how the
doctrine's projects actually queue work. The established pattern is a
postgres-backed library queue (`procrastinate`), where "publish a message" means
inserting into tables owned and migrated by a Python library.

A backing service cannot do that, and not merely because it is inconvenient:

1. **Schema ownership.** The database declares
   [`schema_owned_by`](../../../../doctrine/infrastructure/cicl.md#service-fields)
   naming a codebase, and that codebase's `migrate.sh` creates the queue tables.
   A backing service writing to them is a non-owner writing an owned schema.
   Nothing in the migration model contemplates a second writer.
2. **External types as truth.** Hand-writing SQL against a library's internal
   tables is exactly the coupling
   [`hex_overview.md § Shared Clients`](../../../../doctrine/hexagonal_architecture/hex_overview.md#shared-clients)
   forbids of adapters, hoisted into infrastructure where no adapter can absorb
   the break. The library bumps its schema and the clock silently stops
   enqueueing.

There is also no canonical thing to publish *to*: the bundled roles are
`relational_db`, `cache`, `object_store`, `web`, `worker`, and `scheduler`. The
doctrine ships **no broker role**.

So the only component that may legitimately enqueue is code in the codebase that
owns the schema, calling the library. Everything below follows from that.

## The architecture

The clock is a core service of the codebase whose queue it feeds, so enqueueing
is an ordinary in-process call:

```
entrypoints/clock.py        runtime host — the cron loop
  → ContJobsCron            driving adapter: job name → port method
    → ContJobs              driving port (shared with ContJobsHttp, ContJobsCli)
      → alogic
        → QueueJobs         driven port — canonical `Queue` pattern
          → QueueJobsProcrastinate
```

Every element is already doctrine.
[`internal_dependency_rules.md § Entrypoints`](../../../../doctrine/hexagonal_architecture/internal_dependency_rules.md#entrypoints)
already rules that the runtime host belongs to the entrypoint and is not an
adapter — a cron loop is the same species as a broker's consume loop. The
composition root already instantiates every driving controller for every
mechanism, including ones the running core service will never use. `Queue`
("producer-side access to an asynchronous task or message queue") is already a
canonical driven pattern.

The single addition to resident doctrine is a `Cron` row in the
[controller-mechanism table](../../../../doctrine/hexagonal_architecture/hex_overview.md#controller-mechanism)
alongside `Http` / `Queue` / `Cli` / `Ws` / `Grpc`.

`ContJobsCron` is a real adapter rather than ceremony: it owns the job-name →
port-method dispatch table and the fired/succeeded/failed translation, which
keeps the entrypoint thin enough to satisfy the standing rule that an entrypoint
needing its own test is doing too much.

**Side effect worth having.** Because the driving port is shared, the same job is
reachable over HTTP and CLI. Firing a scheduled job by hand in `dev` stops being
a special path.

## Schedules stay in `infra.yml`

The one genuine advantage of a backing-service clock was that schedules would
live in infrastructure config rather than application code. That advantage
survives here, because the sidecar has already proven the delivery mechanism on
both foundations
([`telemetry_infra.md § Config Delivery`](../../../../doctrine/infrastructure/specifics/telemetry_infra.md#config-delivery)):

- **fixed** — the rendered file is mounted via the compose top-level `configs:`
  block.
- **elastic** — the rendered config is embedded as a literal string in a
  task-definition env entry and read from there at startup.

So the compiler renders `infra/output/<env>/schedules.yml` from:

```yml
codebases:
  api:
    core_services:
      clock:
        role: clock
        command: ["python", "-m", "entrypoints.clock"]
        port: 8080
        health_check_path: /health
        networks: [internal]
        depends_on: [appdb]
        consumes: [api.worker]
        resources: { cpu: 0.25, memory: 512MB }
        schedules:
          nightly_cleanup: "0 3 * * *"
          hourly_rollup:   "0 * * * *"
```

and delivers it by the sidecar's exact pattern. Schedules are git-tracked and
diff-visible in compiler output per
[`cicl.md § Compiler Output`](../../../../doctrine/infrastructure/cicl.md#compiler-output),
`docex describe` can list them, and the
[check step](../../../../doctrine/infrastructure/cicd.md#check-step) can assert
that every declared job name has a binding in the dispatch table. Cron
expressions never enter application code.

> Under the sibling [`uses` merge](./uses_relation_merge.md) the two edge fields
> above collapse to `uses: [appdb, api.worker]`. The designs compose; neither
> depends on the other.

### Cron format simplifies

With EventBridge gone, the two translation hazards `scheduler.md` documents —
the 6-field `?`-day form and EventBridge's Sunday-is-1 day-of-week renumbering —
both disappear. The clock is project code reading a plain 5-field UTC
expression. Whatever cron library the codebase uses parses it directly, with no
compiler-side translation and no dialect-mismatch class of bug.

## Every carve-out dies, and dies honestly

The clock is a genuinely long-running, loop-owning process, so it falls under
existing doctrine with **no exemptions**:

- **Health.** It serves `GET /health` like any core service. Because it owns a
  loop, [`contracts.md`](../../../../doctrine/infrastructure/contracts.md#self-health)
  already prescribes the tick-based liveness rule: bump a monotonic tick each
  iteration, 503 when stale, tick at least every 10s even when idle. A cron loop
  with a bounded ≤10s wait is the obvious way to write one, so the existing rule
  fits without amendment. **A wedged clock now fails its own probe** — today
  "did last night's job fire" is unobservable.
- **Telemetry.** It gets a sidecar like any other core service, so job telemetry
  stops being deferred and the trace originates in the process that fired it.
- **Contract.** It is consumer-only, so it needs none — the provider set is
  (`consumes` targets) ∪ (`web`-network core services) and the clock is neither.
  Same status the doctrine already gives `frontend.web` in its own example.
- **Fan-out.** Not on `web`, so no `/health/<codebase>/<service>` obligation.
- **`dev`.** A normal container with the normal bind mounts. The stale-`dist/`
  behaviour and the "scheduler-only codebase nothing builds" special case both
  vanish.
- **`test`.** No suppression rule needed, because there is nothing pathological
  to suppress.
- **Service Connect.** The clock reaches the worker through postgres, not
  through the mesh, so it sits outside the
  [reconcile hazard](../../../../doctrine/infrastructure/cicl.md#resilience-covers-reachability-not-resolvability)
  entirely. (It still declares `consumes: [api.worker]` — the doctrine already
  requires that edge for a producer that reaches its consumer through a broker
  without holding a magic ref.)

Rules 25, 26 and 27 lose their scheduler clauses; the `contracts.md` exemption
paragraph deletes; `scheduler.md` shrinks to a short note on the clock role.

## Costs, and the rules that pay for them

**1. Singleton — and elastic will double-fire on deploy.** ECS rolling-deploy
defaults (minimum healthy 100%, maximum 200%) briefly run two tasks; a tick
landing in that window fires twice. Fix deterministically for `role: clock`:
`deployment_minimum_healthy_percent = 0`, `deployment_maximum_percent = 100`,
forcing stop-then-start. That trades a possible double-fire for a possible
missed fire during a deploy — the right trade, since missed fires are already an
accepted caveat and jobs are already required to be idempotent. Plus one
validation rule: `replicas` is forbidden (or pinned to 1) on `role: clock`,
**replacing** rule 26 rather than adding to the pile.

**2. One clock per codebase-with-schedules, not one per project.** Codebases
never share code, so a clock can only enqueue into its own. Cross-codebase
scheduling is out. For most projects exactly one codebase has scheduled work, so
this is largely theoretical — but it is a genuine narrowing versus a
project-wide backing service, and should be stated in the doctrine rather than
discovered.

**3. The clock defers; it does not work.** Make this a rule. Otherwise heavy
jobs run inside a singleton with no replicas and no queue-level retry. The
consequence — a codebase with no queue cannot have scheduled work — is correct
pressure rather than a gap.

**4. Losing "run an arbitrary argv on a schedule".** Scheduled work must now be
an operation on a driving port. That forces it into the composed, observable,
tested application instead of a side door. Argv-against-the-image survives where
it belongs: the per-codebase exec container and `migrate.sh`.

## Alternatives, and why they fail

**A `scheduler` backing service invoking core services over their contracts.**
The cleanest-looking option and the one this design was chosen against. It puts
schedules in one project-wide place and needs zero project code. It fails on
[the decisive constraint](#the-decisive-constraint-only-the-codebase-may-enqueue):
it cannot enqueue, so queue-shaped work has to be triggered by an HTTP POST to a
doctrine-fixed endpoint on the worker, which self-enqueues. That is workable —
workers already serve HTTP for `/health`, and
[`contracts.md`](../../../../doctrine/infrastructure/contracts.md#declared-by-fields-not-by-the-contract)
has already ruled that a queue-boundary service's HTTP-shaped operations are
declared by fields rather than by its AsyncAPI contract — but it costs, all of
which the clock core service avoids:

- A fire is **lost** if the target is down, where an insert would have persisted.
  Patchable with a bounded retry, not eliminable.
- A new auth surface: a minted `SCHEDULER_TOKEN`, plus a trigger endpoint that
  is internet-reachable whenever it sits on a `web`-network core service.
- A new backing engine and third-party image to pin and maintain.
- A patch to the Service Connect consumer reconcile, which keys on `consumes` —
  a field backing services cannot hold.

**Keep EventBridge on elastic.** Not viable once invocation targets an in-VPC
core service: EventBridge Scheduler lives outside the VPC and cannot reach a
Service-Connect-discoverable endpoint. Keeping it would also preserve the
fixed/elastic asymmetry (Ofelia + DooD vs. EventBridge + IAM role) that is half
the maintenance cost of the current design.

**Do nothing — use the queue library's own periodic feature.**
`procrastinate` supports `@app.periodic(cron=...)`, so the doctrine could
declare scheduling an application concern and delete `role: scheduler` with no
replacement. Cheap and honest, and worth rejecting deliberately rather than
overlooking: it cannot schedule anything that is not queue-shaped, it does not
survive a project changing queue libraries, and it removes schedules from
`infra.yml` entirely — losing the operational visibility that motivated the
redesign. It also needs a coordination table so N worker replicas do not each
defer the same job, a problem the singleton clock does not have.

## Blast radius

- **`cicl.md`** — new `role: clock`; new `schedules:` field; rules 25/26/27
  lose their scheduler clauses; rule 26 is replaced by the clock singleton rule;
  the `role: scheduler` row and the `nightly_cleanup` example are rewritten.
- **`contracts.md`** — the scheduler health-check exemption paragraph deletes.
- **`scheduler.md`** — most of the file deletes. What remains is short enough
  that it may fold into `cicl.md` and the role table rather than survive as its
  own specifics document.
- **`transfer_tables.md`** — `scheduler/container` becomes `clock/container`;
  the `scheduled_task` emit destination is removed from the recognized set; the
  bundled-roles list and the "a `scheduler` pays zero sidecar overhead" note
  update.
- **`telemetry_infra.md`** — the collector-count arithmetic drops its
  `non-scheduler` qualifier; the deferred job-telemetry caveat is retired.
- **`hex_overview.md`** — one `Cron` row in the controller-mechanism table.
- **`docex`** — delete the Ofelia emitter, the INI renderer, the
  `scheduled_task` renderer and its IAM role; add the clock role table, the
  schedule-table renderer (reusing the sidecar's two delivery paths), and the
  ECS deployment-percentage override. The cron translation code deletes outright.
- **Skills** — `infra-compile` mentions the scheduler and needs its pointer
  updated.
- **Upgrade guide** — every `role: scheduler` service becomes a `clock` core
  service plus one or more driving-port operations; each job's `command` argv
  becomes a port method.

## Open questions

1. **`schedules:` value shape.** Bare cron strings (as shown above) or a block
   per job, leaving room for later per-job options (jitter, timeout, overlap
   policy)? Bare strings are cleaner now; a block avoids a breaking change if
   options are ever wanted.
2. **"The clock defers only" — rule or convention?** Enforceable only weakly
   (the compiler cannot see what a port method does), so this may be doctrine
   prose rather than a validation rule.

Neither blocks implementation.

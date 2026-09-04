# Building-Block View

The interior is [`service_diagram.mmd`](./service_diagram.mmd) (codebase, core
services, backings) and, one level down, the api codebase's
[`module_diagram.mmd`](./api/module_diagram.mmd) (the four hex modules and the
core services that reach into them). This section is the router; per-module detail
lives in the module docs.

**One codebase, three core services.** `api` is a single source tree compiled to
one image and started three ways — `api.web` (the HTTP edge, `web` + `internal`
networks, port 8080), `api.worker` (the poll loop and the `rpc` surface,
`internal`, port 8081, `replicas: 2` in `prod` only), and `api.clock` (the cron
loop singleton, `internal`, no port and no surface). On `stage`/`prod` each is a
`task_definition` + `ecs_service`; only `api.web` carries an ALB target group,
`api.worker` is Service-Connect-registered by virtue of its `port`, and
`api.clock` — declaring no port — joins Service Connect client-only (it resolves
peers, nothing resolves it) and deploys stop-then-start
(`deployment_minimum_healthy_percent = 0` / `maximum = 100`) so a rolling deploy
cannot briefly double-fire. `api.web` is the `domain_default_service`, so in
`prod` the web edge answers at the canonical, bare-env, and bare-project hosts.
`api.web` **uses** `api.worker` (one direction: `POST /drain` against the
worker's `rpc` surface, resolved over Service Connect), plus the `appdb`, `probe`,
and `events` backings; the worker and clock reach the worker's queue through the
`jobs` table rather than the mesh. Full field-by-field reasoning is in the
`infra.yml` comments and the contracts under `infra/contracts/`.

**Composition root vs. entrypoints.** There is exactly one `src/root.py` per
codebase. The root **constructs** — it instantiates every driven adapter, every
alogic service, and every driving controller (including mechanisms the running
core service never uses) — and **does not activate**: it opens no socket, starts
no server, runs no loop. Activation lives in `src/entrypoints/`, one module per
core service, each invoked by that core service's `command`: `web.py` hands the
app to uvicorn; `worker.py` owns the poll loop, SIGTERM handling, the liveness
tick file, and the uvicorn host for the `rpc` surface; `clock.py` owns the cron
loop on a bounded 5 s wait, SIGTERM handling, and the liveness tick — and no
server of any kind. `clock.py` is the doctrine's reference implementation of a
clock runtime host and `worker.py` of a loop-owning consumer; downstream projects
copy both.

**The four hex modules** ([`module_diagram.mmd`](./api/module_diagram.mmd)):

- [`pings`](./api/module/pings.md) — the `Ping` entity and the `POST /pings`
  create flow. Driven by `api.web`.
- [`processor`](./api/module/processor.md) — claims unprocessed pings and marks
  them processed. Driven by `api.worker`.
- [`jobs`](./api/module/jobs.md) — the deferred-work queue, holding the defer
  side (driven by `api.clock`), the perform side (driven by `api.worker`), and a
  consumer half in `api.web`'s process (the `/jobs/drain` round trip).
- [`retention`](./api/module/retention.md) — deletes processed pings past the
  window; reached only through the `prune_pings` job.

None of the four imports another, with one deliberate exception the doctrine
permits: `jobs`' runner imports `retention`'s driving port. The relational schema
the modules share — the `pings` and `jobs` tables in `appdb` (RDS on
`stage`/`prod`) — is documented in
[`db_schema.md`](./api/specifics/db_schema.md).

# Runtime View

Eight flows trace information and action through the running project.

1. **Ping creation.** `POST /pings` on `api.web` → `ContPingsHttp` translates to a
   driving port call → `PingService.create_ping()` constructs a `Ping`, calls
   `RepoPings.save()` → row lands in postgres (RDS on `stage`/`prod`) with
   `processed_at = NULL` → 201 returned.
2. **Ping processing.** `entrypoints/worker.py`'s loop calls
   `ContProcessorCli.run_once()` once a second → `ProcessorService` claims
   `pings WHERE processed_at IS NULL` in batches of 32 → for each row the no-op
   business logic runs → `RepoPings.mark_processed(id)` sets `processed_at =
   now()` → the loop touches its tick file (flow 3) and sleeps.
3. **Self health.** `GET /health` on `api.web` returns `{"version": "<project
   version>"}`, straight from the process — and it survives on that core service
   **alone**, because the ALB target group reads it over the network and has no
   other way to ask (`healthchecks.md § web services also serve GET /health`). The
   other two core services own loops, and a loop's liveness has to be sourced from
   the loop: `entrypoints/{worker,clock}.py` touch `/tmp/<svc>.tick` at the end of
   each successful iteration, and `./health.sh <svc>` — which the orchestrator
   runs as a **separate process** (emitted as the task definition's container
   `healthCheck`) — stats that file and fails when it is absent or more than 30 s
   old. An **absent** file fails, deliberately: a loop that never completed an
   iteration was never alive, and reporting healthy until the first tick would
   hide a loop that never started. The 30 s threshold lives in `health.sh` because
   the probe is the only thing that judges it; the ≤10 s cadence lives in the
   entrypoints (1 s in the worker, 5 s in the clock) because the loop is the only
   thing that can honour it. **The two numbers are meaningless apart:** 30 is
   three times 10, so a healthy loop misses two consecutive ticks before it is
   called stale — slack for jitter and one slow iteration, without giving a wedged
   loop room to hide. On elastic a failed probe has teeth — ECS kills and replaces
   the task, and `startPeriod: 10` gives a loop time to complete its first
   iteration first.
4. **Deferred-job drain.** `POST /jobs/drain` on `api.web` → `ContJobDrainHttp` →
   `JobDrainService` → `GwyJobRunnerHttp`, which addresses the worker through the
   injected `WORKER_HOST` / `WORKER_PORT` → HTTP `POST /drain` against
   `api.worker`'s `rpc` surface → `ContJobRunnerHttp` → `ContJobRunner.run_once()`
   → `{"performed": N}` travels back out through the edge to the original caller.
   This is the **only** flow that crosses a process boundary between two core
   services, so it is the one that carries the `api.worker` entry in `api.web`'s
   `uses:`, the five-segment magic refs, and rule 32's positive arm — and on
   elastic it is what makes `api.worker`'s Service Connect registration
   load-bearing, because the whole round trip depends on `api.web → api.worker`
   name resolution. Its reply is a **count of work performed** — no liveness
   verdict and no staleness judgement — so it cannot be mistaken for the health
   fan-out that used to live at `/health/api/worker` and exists nowhere now.
5. **Project-local-backing reachability.** `GET /diagnostics/probe` confirms
   `api.web` can resolve and reach the `probe` nginx sidecar by service name;
   `GET /diagnostics/events` confirms it can open a TCP connection to the
   EFS-backed ClickHouse task. Both exercise Service Connect resolution and
   security-group reachability at the smoke-test layer. They sit under
   `/diagnostics` rather than `/health` because they probe *backing* services, and
   under `/health/*` a reader would conclude the fan-out survived — against
   `healthchecks.md`'s "No service reports on another."
6. **Scheduled deferral.** `entrypoints/clock.py`'s loop wakes at most every 5 s,
   finds a job whose cron expression is due, and calls `ContJobsCron.fire(name)` →
   the shared driving port `ContJobs` → `JobService` inserts a row into `jobs`
   (in RDS) → the fire returns. **That is the whole of the clock's involvement.**
   It performs no work, because a clock is a singleton with no replicas and no
   queue-level retry, and because only the codebase that owns a schema may write
   to it. Two jobs are scheduled: `prune_pings` at `0 3 * * *`, and `heartbeat`
   every minute so this flow is observable inside a smoke walk rather than only at
   03:00. **This flow is where the two foundations converge rather than diverge:**
   the clock is a plain `ecs_service` reading the same `DOCEX_SCHEDULES_YAML`
   literal it reads on fixed, enqueueing into RDS instead of a container postgres —
   nothing about it is foundation-shaped, which is the point of retiring
   `role: scheduler`, whose fixed (Ofelia) and elastic (EventBridge) halves shared
   no mechanism at all.
7. **Job draining.** The same `api.worker` pass as flow 2 calls
   `ContJobRunnerCli.run_once()` → `JobRunnerService` claims a batch
   `FOR UPDATE SKIP LOCKED` (exclusive against the second replica), looks each
   row's `name` up in its **perform-side** table, and runs the handler →
   `prune_pings` calls `retention`'s driving port, computing a cutoff from a
   30-day `RetentionWindow` and deleting expired *processed* pings (unprocessed
   and recently-processed rows survive); `heartbeat` logs and returns. Each row is
   stamped `finished_at`, with `error` set on failure and the drain continuing
   past it.
8. **Clock self health.** The clock's half of flow 3's tick mechanism.
   `entrypoints/clock.py`'s loop touches `/tmp/clock.tick` on each iteration
   whether or not anything fired — a clock with nothing due is perfectly alive,
   and that is what makes its bounded 5 s wait sufficient on its own — with one
   exception: a pass on which *every* due fire raised withholds the tick, for the
   same reason the worker's failing pass does. `./health.sh clock` stats it.
   Nothing external reaches the clock at all: it serves nothing, registers nothing
   in Service Connect, no route proxies it, and the stage tester cannot see it.
   The probe is therefore the clock's **only** liveness channel — acted on
   directly by ECS, which kills and replaces the task (docker merely *reports*
   `unhealthy` on the fixed companion). Local, but real, and stronger than the
   served route it replaced: the probe stats the loop's own trace from a separate
   process, so a wedged loop cannot answer on its own behalf.

# Deployment View

### Foundation

`elastic`. `dev` and `test` compile to fixed compose stacks and run as docker
containers on the operator's dev machine (always fixed-style per
`shape.md § Shape and Environment`); `stage` and `prod` compile to AWS HCL and run
on ECS Fargate in the shared master VPC, region `us-east-1`. On `stage`/`prod` ECS
**acts on** container health: a task whose essential container fails its probe is
killed and replaced, so the probe is a live restart trigger rather than a report,
and `docex stagetest` reads each core service's verdict from the ECS API — never
through an application route. In `dev`/`test`, which are fixed compose stacks, the
probe behaves the fixed way (docker only *reports* `unhealthy`).

### Domain

`apex_domain: luxrnd.tech` — the bare apex. The project segment derives from
`project.yml`'s `name`, yielding `docex-smoke-elastic.luxrnd.tech`. Per-env hosts
compile to the canonical
`<codebase>-<service>.<env>.docex-smoke-elastic.luxrnd.tech` form (two segments in
one DNS label, hyphen-joined), plus the bare-env and bare-project forms, both of
which route to `domain_default_service: api.web` in `prod`. A Route53 hosted zone
for `docex-smoke-elastic.luxrnd.tech` is provisioned by `docex projinfra up
production`; the operator NS-delegates it from the parent `luxrnd.tech` zone (also
Route53, same account) during projinfra's two-phase apply. ACM issues two certs
(stage + prod) with the doctrine-spec SANs, bound as SNI certificates on the
project ALB, which fronts the web edge.

### Core-service → infrastructure mapping

| Core service | Networks | Port | Elastic infrastructure |
| ------------ | -------- | ---- | ---------------------- |
| `api.web` | `web`, `internal` | 8080 | `task_definition` + `ecs_service` + ALB target group; `GET /health` probed by the target group and by the container `healthCheck` |
| `api.worker` | `internal` | 8081 | `task_definition` + `ecs_service`, no target group; Service-Connect-registered; `desired_count = 2` in `prod`, 1 elsewhere; tick-file probe |
| `api.clock` | `internal` | — | `task_definition` + `ecs_service`, no target group, not Service-Connect-registered; stop-then-start deploy; tick-file probe |
| `appdb` | `internal` | — | RDS postgres 15 |
| `probe` | `internal` | — | nginx `ecs_service` (Fargate task) |
| `events` | `internal` | — | clickhouse `ecs_service` (Fargate task) + EFS file system, mount target per private subnet, `aws_efs_backup_policy` |

One image per codebase: all three core services run the same tag started three
different ways, **one** ECR repo, and **one** `…-migrate` task-definition family
dispatched by `RunTask` per release.

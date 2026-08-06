# api — service architecture

## Purpose

One codebase, one image, **three core services**. `api` is the project's application core: it accepts `POST /pings` at its HTTP edge, processes those pings in a background loop, and fires scheduled jobs onto a queue that the same loop drains. All three invocations run the same build artifact, share the `appdb` schema, and read the same six `DATABASE_*` parts.

| Core service | Role | Command | Networks | Port |
| ------------ | ---- | ------- | -------- | ---- |
| `api.web` | `web` | `entrypoints/web.py` | `web`, `internal` | 8080 |
| `api.worker` | `worker` | `entrypoints/worker.py` | `internal` | 8081 (health only) |
| `api.clock` | `clock` | `entrypoints/clock.py` | `internal` | 8082 (health only) |

`api.web` is the project's `domain_default_service`, so prod's web edge answers at three hosts: `api-web.prod.docex-smoke-fixed.luxrnd.tech` (canonical), `prod.docex-smoke-fixed.luxrnd.tech` (bare-env), and `docex-smoke-fixed.luxrnd.tech` (bare-project ergonomic) — per `cicl.md § Domain`. Routing is handled by the per-project Traefik on fixed; the bare-env and bare-project forms only apply to prod.

`api.worker` is never routed. It carries a `port` and a `health_check_path` purely because it is a core `uses` target and must therefore be probeable (`contracts.md § Declared by fields`).

`api.clock` is never routed **and is not a `uses` target either** — nothing uses it. It carries a `port` and a `health_check_path` because a clock gets **no exemptions**: it is an ordinary long-running core service that serves `/health` off its loop's tick like any other. The consequence is worth stating plainly, because it is easy to misread as an oversight: nothing external can reach that endpoint. No fan-out proxies it and the stage tester cannot see it, so the clock's liveness is enforced by the **container healthcheck alone** — docker `healthcheck:` on fixed, ECS container health on elastic, both of which restart a wedged clock. That is real enforcement, but it is local (`clock.md § Caveats`).

### Why one codebase and not two

`web` and `worker` were two separate *codebases* until CICL v2, and that split was an artifact of the limitation v2 removes: they always shared a database, a table, and six identical magic refs, but pre-v2 CICL had no way to express "one artifact, two invocations". They are now what they always were.

`api.clock` arrived by a different route and is worth recording, because the shape it replaced looked reasonable. Scheduled pruning used to be its own codebase, `reaper`, running as a `role: scheduler` — a **core service** that was not a process. When `scheduler` was retired in favour of `role: clock`, `reaper` **could not simply become a clock**: a clock defers onto its own codebase's queue, only the codebase that owns a schema may enqueue, and `reaper` owned no schema, no worker, and no queue. `api` owns all three. So the clock folded in here as a third invocation of an artifact that already existed, `reaper` was deleted, and its retention rule became the [`retention`](./hex/retention.md) module.

## Hex modules

Four:

- [`pings`](./hex/pings.md) — the `Ping` entity and the `POST /pings` create flow. Driven by `api.web`.
- [`processor`](./hex/processor.md) — claims unprocessed pings and marks them processed. Driven by `api.worker`.
- [`jobs`](./hex/jobs.md) — the deferred-work queue, holding **both halves** of the deferral contract: the defer side driven by `api.clock`, the perform side driven by `api.worker`.
- [`retention`](./hex/retention.md) — the retired `reaper` codebase's rule: delete processed pings older than the window. Reached only through the `prune_pings` job.

None of the four imports another, with one deliberate exception: `jobs`' runner imports `retention`'s **driving port**, which is the single cross-module import the doctrine permits.

Future modules — none planned. The smoke test exists to exercise *doctrine surface*, not to grow an application.

## Composition root

`src/root.py`, and there is exactly **one** of it — not one per core service. Splitting the root would put two copies of the driven wiring in the tree, and they would drift (`internal_dependency_rules.md § Entrypoints`, rule 3).

**The root constructs; it does not activate.** It opens no socket, starts no server, and runs no loop. It exposes two build functions:

- `build_app() -> FastAPI` — `RepoPingsPostgres` → `PingService` → `ContPingsHttp`, plus `ContJobsHttp`'s router and the standalone `/health`, `/health/probe`, `/health/events`, and `/health/api/worker` routes.
- `build_processor() -> ContProcessorCli` — the processor module's `RepoPingsPostgres` → `ProcessorService` → `ContProcessorCli`, returned un-run.
- `build_clock() -> ContJobsCron` — `QueueJobsPostgres` → `JobService` → `ContJobsCron`, returned un-run.
- `build_job_runner() -> ContJobRunnerCli` — `QueueJobsPostgres` + retention's repo, window, and service → `JobRunnerService` → `ContJobRunnerCli`, returned un-run.
- `build_jobs_cli() -> ContJobsCli` — constructed and invoked by **no entrypoint**. That is correct, not dead code: the root instantiates every driving mechanism, including ones the running core service will never use (`internal_dependency_rules.md § Composition Root`, item 3). Controller construction is free — it captures a port reference and performs no I/O.

`_RETENTION_DAYS = 30` lives here too. It is a wiring decision, not a doctrine part and not a configurable value, so it is a constant in the root rather than a key in `env:`.

## Entrypoints

`src/entrypoints/`, one module per core service; each is what that core service's `command` invokes.

- `web.py` — calls `build_app()` and hands it to uvicorn. The runtime host belongs here, not in an adapter.
- `worker.py` — owns the three things a loop-owning core service owes and an adapter must not:
  1. the **poll loop** (1 s interval) driving `ContProcessorCli.run_once()`,
  2. the **signal handling** (SIGTERM/SIGINT set a stop flag; the loop exits after the current iteration),
  3. the **liveness surface** — a monotonic tick bumped once per successful iteration, and a `GET /health` on port 8081 that 503s once that tick is 30 s stale. Thresholds are doctrine-fixed (`contracts.md § Health Checks`): tick at least every 10 s even when idle, 30 s staleness. There is no knob.

  The tick is **not** bumped in the exception path. A loop that fails every iteration is not alive, and bumping there would report 200 forever while no work moved.

  uvicorn runs in a daemon thread and the loop in the main thread, because signals only reach the main thread and it is the loop that has to hear SIGTERM.

  Each pass runs `ContProcessorCli.run_once()` **and** `ContJobRunnerCli.run_once()` under one `try` and bumps **one** tick. A worker that cannot drain the job queue is not doing its job even if pings still move, so a failure in either half correctly withholds the tick.
- `clock.py` — **the doctrine's reference implementation of a clock runtime host**; downstream projects copy it. Same three responsibilities as `worker.py`, in the same shapes:
  1. the **cron loop**, waiting on a bounded 5 s interval. The bound is the whole liveness mechanism: the doctrine's "tick at least every 10 s even when idle" falls out of the loop's shape rather than from a keepalive bolted on beside it, which is what `clock.md` means by "a cron loop with a bounded ≤10 s wait is the natural way to write one".
  2. the **signal handling**, identical to the worker's.
  3. the **liveness surface** on port 8082, sourced from the loop's tick and 503ing at 30 s — so a wedged clock fails its own probe.

  It reads its job table from **`DOCEX_SCHEDULES_YAML`**, whose value is the *literal rendered YAML* and not a path. The variable is identical on both foundations, which is why this file contains no foundation branch and no mount handling. Schedules are seeded from **process start**: the clock is forward-only and does not backfill, so a clock that was down for six hours does not come up and stampede six hours of missed fires at the queue.

  A firing failure is logged and swallowed so one bad job cannot kill the loop — but the tick is withheld on a pass where *every* fire raised, for the same reason the worker withholds it.

## Contracts

Two, because the codebase has two boundaries and the contract path is keyed on the core service:

- `infra/contracts/api.web.openapi.yml` — `role: web` → OpenAPI. Declares `/pings`, `/health`, the doctrine-required `/health/api/worker` fan-out, and the two optional backing probes.
- `infra/contracts/api.worker.asyncapi.yml` — `role: worker` → AsyncAPI. Describes the two message boundaries it consumes — unprocessed `pings` rows and deferred `jobs` rows — and nothing else; the worker's probeability lives in its `port` + `health_check_path` fields, not here.

**`api.clock` has no contract, and that is the rule rather than an exemption.** The provider set is (core-service `uses` targets) ∪ (`web`-network core services). The clock is neither: nothing uses it, and it is not on `web`. It is consumer-only — the same status the doctrine gives `frontend.web` in its own worked example.

## Database

This codebase owns the schema (`schema_owned_by: api`). See [`db_schema.md`](./db_schema.md). Migrations live at `core/api/migrations/` and are driven by `core/api/migrate.sh` (dbmate), which runs **once per codebase**, not once per core service.

Because it runs per codebase, `migrate.sh` may read **codebase-level `env:` only**. The six `DATABASE_*` parts are declared at the `api` codebase level for exactly that reason; a core-service-scoped var such as `WORKER_HOST` would simply be absent, silently.

## Hard boundaries

- **The two hex modules do not import each other.** `pings` writes pings; `processor` consumes them. They are connected only by the `pings` table, and each reaches it through its own `RepoPingsPostgres`. Sharing a codebase does not make them one module.
- **No `api.web` entry in the worker's `uses:`.** `cicl.md`'s worked example declares the mutual `web ↔ worker` cycle, and it is legal — but *this* worker polls a table and never calls the web edge, so the reverse edge would be a false declaration in a file downstream projects copy.
- **`/health/api/worker` is one hop only.** It proxies the worker's own `/health` and never its fan-out endpoints; the `uses` graph may cycle.
- `/health/probe` and `/health/events` are exercise endpoints for the project-local backings — they are *not* doctrine-mandated (probe and events are backings, not core services). They exist so the stage tests can catch Service Connect / SG / EFS-mount wiring regressions on the elastic counterpart.
- **The clock never claims and never works.** `api.clock` drives `ContJobs` only; claiming and performing belong to `api.worker`. The rule is not decorative — a clock is a singleton with no replicas and no queue-level retry, so work run inside it would have neither.
- **The two dispatch tables in `jobs` stay separate.** Defer-side in `ContJobsCron`, perform-side in `JobRunnerService`. See [`hex/jobs.md`](./hex/jobs.md); merging them is the obvious cleanup and it destroys the deferral architecture.
- **No real broker.** Both queues are postgres tables — `pings` for ping work, `jobs` for deferred jobs. The doctrine ships no `queue` backing-service role, which is why the worker's AsyncAPI channels address tables rather than topics: the most visible loose end the CICL-v2 advance leaves.

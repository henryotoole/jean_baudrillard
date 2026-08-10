# api — service architecture

## Purpose

One codebase, one image, **three core services**. `api` is the project's application core: it accepts `POST /pings` at its HTTP edge, processes those pings in a background loop, and fires scheduled jobs onto a queue that the same loop drains. All three invocations run the same build artifact, share the `appdb` schema, and read the same six `DATABASE_*` parts.

| Core service | Role | Command | Networks | Port |
| ------------ | ---- | ------- | -------- | ---- |
| `api.web` | `web` | `entrypoints/web.py` | `web`, `internal` | 8080 |
| `api.worker` | `worker` | `entrypoints/worker.py` | `internal` | 8081 |
| `api.clock` | `clock` | `entrypoints/clock.py` | `internal` | — |

`api.web` is the project's `domain_default_service`, so prod's web edge answers at three hosts: `api-web.prod.docex-smoke-fixed.luxrnd.tech` (canonical), `prod.docex-smoke-fixed.luxrnd.tech` (bare-env), and `docex-smoke-fixed.luxrnd.tech` (bare-project ergonomic) — per `cicl.md § Domain`. Routing is handled by the per-project Traefik on fixed; the bare-env and bare-project forms only apply to prod.

`api.worker` is never routed, and it declares **no `health_check_path`** — rule 33 confines that field to `web`-network core services. It carries `port: 8081` because `api.web` **addresses its `rpc` surface** directly (`POST /drain`), and being directly addressed is what obliges a port under rule 32's positive arm. Not because a `uses` target must be probeable: probeability is a container concern, answered by `./health.sh worker`, and a non-`web` core service needs no HTTP surface of any kind for it (`healthchecks.md § What this doctrine does not do`).

`api.clock` is never routed **and is not a `uses` target either** — nothing uses it. It carries no `port`, no `health_check_path`, and no surface, and yet a clock gets **no exemptions**: it is an ordinary long-running core service and it supplies a container probe like every other one, `./health.sh clock`, sourced from its cron loop's tick file. The consequence is worth stating plainly, because it is easy to misread as an oversight: **nothing external can reach the clock at all.** It binds no application socket — inside the container the only `LISTEN` entry in `/proc/net/tcp` is docker's embedded DNS resolver at `127.0.0.11`, which every container has. Nothing proxies it and the stage tester cannot reach it, so **that probe is the only channel the clock's liveness has** — reported by docker here and read from `docker inspect` by `docex stagetest`, acted on directly by ECS on the elastic companion, which kills and replaces the task. That is real enforcement, but it is local: nothing observes it from outside the host (`clock.md § Caveats`).

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

**The root constructs; it does not activate.** It opens no socket, starts no server, and runs no loop. It exposes six build functions:

- `build_app() -> FastAPI` — `RepoPingsPostgres` → `PingService` → `ContPingsHttp`, plus the routers of `ContJobsHttp` and **`ContJobDrainHttp`**, and the three standalone routes `GET /health`, `GET /diagnostics/probe`, and `GET /diagnostics/events`. `ContJobDrainHttp` is built here rather than in a build function of its own, alongside the two other routers this app mounts; the gateway behind it, `GwyJobRunnerHttp`, is constructed even when `WORKER_HOST` is unset, because construction captures two strings and performs no I/O — which is what keeps `build_app()` callable inside the `test` container, where no worker address is injected.
- `build_processor() -> ContProcessorCli` — the processor module's `RepoPingsPostgres` → `ProcessorService` → `ContProcessorCli`, returned un-run.
- `build_clock() -> ContJobsCron` — `QueueJobsPostgres` → `JobService` → `ContJobsCron`, returned un-run. The clock's graph stops at the queue: no retention repo, no handler, because it defers and does not work.
- `build_job_runner() -> ContJobRunnerCli` — `QueueJobsPostgres` + retention's repo, window, and service → `JobRunnerService` → `ContJobRunnerCli`, returned un-run.
- `build_job_runner_http() -> ContJobRunnerHttp` — the **same** `JobRunnerService` graph behind the HTTP mechanism, which is `api.worker`'s `rpc` surface. Both this and `build_job_runner()` above go through one private `_job_runner_service()` factory, because two copies of that wiring would drift — the argument `internal_dependency_rules.md § Entrypoints` rule 3 makes against splitting the composition root, applied one level down. The root builds it **inside `api.web`'s process too**, where nothing mounts it, for the reason `build_jobs_cli` gives below; this is now the second instance of that item rather than a lone oddity.
- `build_jobs_cli() -> ContJobsCli` — constructed and invoked by **no entrypoint**. That is correct, not dead code: the root instantiates every driving mechanism, including ones the running core service will never use (`internal_dependency_rules.md § Composition Root`, item 3). Controller construction is free — it captures a port reference and performs no I/O.

`_RETENTION_DAYS = 30` lives here too. It is a wiring decision, not a doctrine part and not a configurable value, so it is a constant in the root rather than a key in `env:`.

## Entrypoints

`src/entrypoints/`, one module per core service; each is what that core service's `command` invokes.

- `web.py` — calls `build_app()` and hands it to uvicorn. The runtime host belongs here, not in an adapter.
- `worker.py` — owns four things a loop-owning core service owes and an adapter must not:
  1. the **poll loop** (1 s interval) driving `ContProcessorCli.run_once()`,
  2. the **signal handling** (SIGTERM/SIGINT set a stop flag; the loop exits after the current iteration),
  3. the **liveness tick** — a `touch` of `/tmp/worker.tick` once per successful iteration. It is a *file* and not an in-memory value because the probe, `./health.sh worker`, is run by docker and ECS as a **separate process** and has to be able to stat it. The cadence lives here (1 s, comfortably inside the doctrine's ≤10 s ceiling); the 30 s staleness threshold lives in `health.sh`, because the probe is the only thing that judges it. Both are doctrine-fixed with no knob (`healthchecks.md § What the probe must actually check`).
  4. the **runtime host for the `rpc` surface** — a uvicorn server on port 8081 carrying `ContJobRunnerHttp`'s router.

  **The uvicorn server is not a health server**, and this is the single most misreadable line in the file: liveness is the tick file and does not involve that thread at all — kill the server and `./health.sh worker` still tells the truth about the loop. The server exists because `api.web` **calls** this boundary (`POST /drain`), which is an application call. `api.clock`, which declares no surface, runs no server whatsoever.

  The tick is **not** bumped in the exception path. A loop that fails every iteration is not alive, and bumping there would keep the probe green forever while no work moved.

  uvicorn runs in a daemon thread and the loop in the main thread, because signals only reach the main thread and it is the loop that has to hear SIGTERM — and a daemon thread needs no join on the way out.

  Each pass runs `ContProcessorCli.run_once()` **and** `ContJobRunnerCli.run_once()` under one `try` and bumps **one** tick. A worker that cannot drain the job queue is not doing its job even if pings still move, so a failure in either half correctly withholds the tick.
- `clock.py` — **the doctrine's reference implementation of a clock runtime host**; downstream projects copy it. Three responsibilities, the same shapes as `worker.py`'s first three:
  1. the **cron loop**, waiting on a bounded 5 s interval. The bound is the whole cadence mechanism: the doctrine's "tick at least every 10 s even when idle" falls out of the loop's shape rather than from a keepalive bolted on beside it, which is what `clock.md` means by "a cron loop with a bounded ≤10 s wait is the natural way to write one".
  2. the **signal handling**, identical to the worker's.
  3. the **liveness tick** — a `touch` of `/tmp/clock.tick` on every iteration, fired or not, because a clock with nothing due is perfectly alive. `./health.sh clock` stats it.

  **This file loses uvicorn, fastapi, and its listener outright**, and it is the file that proves the change is real rather than cosmetic. Everywhere else in this codebase HTTP survives for a reason — `api.web` serves an edge, `api.worker` serves an `rpc` surface — and here, where the only reason was health, it is gone completely: no import, no thread, no bound socket.

  It reads its job table from **`DOCEX_SCHEDULES_YAML`**, whose value is the *literal rendered YAML* and not a path. The variable is identical on both foundations, which is why this file contains no foundation branch and no mount handling. Schedules are seeded from **process start**: the clock is forward-only and does not backfill, so a clock that was down for six hours does not come up and stampede six hours of missed fires at the queue.

  A firing failure is logged and swallowed so one bad job cannot kill the loop — but the tick is withheld on a pass where *every* fire raised, for the same reason the worker withholds it.

## Health

`core/api/health.sh` is this codebase's **fourth shim**, beside `build.sh`, `test.sh`, and `migrate.sh` — and the only one invoked **per core service**, as `./health.sh <service>`. The other three are properties of the source tree; health is a property of a running process, and this codebase's web edge, poll loop, and cron loop are three processes with three different failure modes. One file still, because four files to hold four branches of a `case` is worse, and the compiler supplies the argv so the script never has to guess where it is running (`healthchecks.md § The probe`).

**The exit code is the entire contract.** `0` means this core service is working; anything else means it is not. Nothing reads stdout — docker captures probe output and ECS does not, so it could never be a cross-foundation channel — and the script's stderr messages exist for a human reading `docker inspect` and promise nothing.

Three arms:

- **`web`** curls its own `http://localhost:8080/health`. A service driven by a request cycle is nearly self-checking: if it accepts a connection and routes a trivial request, it is serving. This is the one place in the file where curling yourself is legitimate.
- **`worker` / `clock`** stat their tick file, `/tmp/<service>.tick`, and fail when it is absent or more than 30 s old. An **absent** file fails deliberately — a loop that has never completed an iteration was never alive, and reporting healthy until the first tick would disarm the one arm that catches a loop that never started. Checking that the process exists would prove nothing (a deadlocked process exists) and a separate liveness thread would prove less than nothing (it answers healthy forever while no work moves).
- **anything else** exits **2, loudly**. Falling through to `0` on a typo in the emitted argv would report every core service healthy forever, which is the one outcome worse than a wrong probe.

**POSIX `sh`, not bash.** `python:3.12-slim` ships dash as `/bin/sh` and no bash. Staleness is computed with `stat -c %Y` plus `date +%s` rather than a python one-liner, so the probe pays no interpreter startup inside a 5 s timeout.

**Where the two numbers live, and why they are a pair.** The 30 s staleness threshold is in `health.sh`, because the probe is the only thing that judges it. The ≤10 s tick cadence is in `src/entrypoints/{worker,clock}.py` (1 s and 5 s respectively), because the loop is the only thing that can honour it. Neither is a per-project knob and neither means anything alone: 30 is three times 10, so a healthy loop misses two consecutive ticks before it is called stale — slack for scheduling jitter and one slow iteration without flapping, while still failing a wedged loop inside the window the orchestrator acts on.

**`curl` is in the image for the `web` arm and for nothing else.** The doctrine withdrew any blanket curl mandate; what an image needs is whatever *its own* `health.sh` uses, which is why the Dockerfile's `curl` install carries a comment naming the one line that justifies it.

**Foundation difference.** On fixed, docker only *reports*. A failing container is marked `unhealthy` and nothing in the compiled output acts on it: `restart: unless-stopped` reacts to a container **exiting**, not to a failed probe, and the emitted Traefik labels declare no health-aware load balancing. What does act on it is `docex` — `stagetest` reads `docker inspect`'s `.State.Health.Status` over SSH and fails the gate on anything that is not `healthy`, which is `healthchecks.md`'s "`docex` reads the orchestrator" in its fixed form. On elastic the orchestrator itself acts: ECS **kills and replaces** a task whose essential container fails, which is why the role tables carry `startPeriod: 10` there and only there — a start grace period is only worth having where a probe has a lethal consequence. Detection is not instantaneous on either foundation: the tick goes stale, the next scheduled probe fails, the retry count is exhausted. That lag is deliberate and is the price of not flapping (`healthchecks.md § The orchestrator carries the result`).

## Contracts

Three, one per declared **surface**. The path is `<codebase>.<service>.<surface>.<format>.<ext>` — keyed on the surface, not on the core service — and the format follows from that surface's `api_styles`, never from the core service's `role` (`cicl.md § Surfaces`):

- `infra/contracts/api.web.rest.openapi.yml` — from `api.web`'s `rest` surface. Declares `/pings`, `/jobs/prune_pings`, `/jobs/heartbeat`, `/jobs/drain`, `/health`, and the two `/diagnostics/*` backing probes. `GET /health` belongs here because `api.web` is on the `web` network **and** declares an `openapi` surface, which is the one case `healthchecks.md § web services also serve GET /health` describes — not because every long-running core service owes a health route.
- `infra/contracts/api.worker.rpc.asyncapi.yml` — from `api.worker`'s `rpc` surface. One operation: drain the deferred-job queue now, reply with the count performed. `Http` is the adapter's *mechanism* suffix and `rpc` is the *api_style*; the doctrine keys the format on the second, which is why a request/reply boundary spoken over HTTP is described by an AsyncAPI document rather than an OpenAPI one.
- `infra/contracts/api.worker.events.asyncapi.yml` — from `api.worker`'s `events` surface. The two queues it consumes, `pings` and `jobs`, live in this **one** document, per `cicl.md § Surfaces`' split table: one core service consuming two queues is one surface, and one AsyncAPI document carries both channels.

**Two surfaces, one format, and that is legal.** `rpc` and `events` both resolve to `asyncapi`; what makes them two surfaces rather than one is that their consumer sets are unrelated. `api.web` calls the `rpc` boundary synchronously and waits for a count; the queues are produced onto by `api.web` and `api.clock` and consumed here, asynchronously and with no reply. Collapsing them would describe two unrelated boundaries in one document.

**Spec-version floor: OpenAPI 3.2 or later, AsyncAPI 3.0 or later** (`contracts.md § Standards`). Nothing enforces it mechanically — `docex check` YAML-parses each document and reads its `paths`, and would accept a 3.0 OpenAPI file happily — so it is a discipline the project holds itself to. The AsyncAPI 3.0 floor is also what makes `reply` available, which is the whole reason `rpc` resolves to `asyncapi` at all.

**`api.clock` has no contract, and that is the rule rather than an exemption.** It **declares no surface**, and declaring none is what makes a core service not a provider. It is consumer-only — the same status the doctrine gives `frontend.web` in its own worked example.

## Database

This codebase owns the schema (`schema_owned_by: api`). See [`db_schema.md`](./db_schema.md). Migrations live at `core/api/migrations/` and are driven by `core/api/migrate.sh` (dbmate), which runs **once per codebase**, not once per core service.

Because it runs per codebase, `migrate.sh` may read **codebase-level `env:` only**. The six `DATABASE_*` parts are declared at the `api` codebase level for exactly that reason; a core-service-scoped var such as `WORKER_HOST` would simply be absent, silently.

## Hard boundaries

- **The two hex modules do not import each other.** `pings` writes pings; `processor` consumes them. They are connected only by the `pings` table, and each reaches it through its own `RepoPingsPostgres`. Sharing a codebase does not make them one module.
- **No `api.web` entry in the worker's `uses:`.** `cicl.md`'s worked example declares the mutual `web ↔ worker` cycle, and it is legal — but *this* worker polls a table and never calls the web edge, so the reverse edge would be a false declaration in a file downstream projects copy. The asymmetry is more interesting than it used to be, not less: `api.web` → `api.worker` is now a live HTTP call across a declared surface, and the reverse direction still does not exist.
- `/diagnostics/probe` and `/diagnostics/events` are exercise endpoints for the project-local backings — they are *not* doctrine-mandated (probe and events are backings, not core services). They exist so the stage tests can catch Service Connect / SG / EFS-mount wiring regressions on the elastic counterpart. They live under `/diagnostics` and **not** under `/health/*` because they report on *backing* services: left under `/health`, a reader would reasonably conclude the deleted health fan-out survived under a narrower name, which `healthchecks.md § What this doctrine does not do` forbids outright.
- **`POST /jobs/drain` is safe against the worker draining at the same moment**, and needs no lock. `QueueJobsPostgres` opens a connection per call and `claim` takes its batch with `SELECT … FOR UPDATE SKIP LOCKED` — the same guarantee that makes `replicas: 2` safe against itself, and this route is that identical race under a shorter name. The justification is written down once, in [`hex/jobs.md`](./hex/jobs.md) § Concurrency; this is its second consumer, not a second argument.
- **The clock never claims and never works.** `api.clock` drives `ContJobs` only; claiming and performing belong to `api.worker`. The rule is not decorative — a clock is a singleton with no replicas and no queue-level retry, so work run inside it would have neither.
- **The two dispatch tables in `jobs` stay separate.** Defer-side in `ContJobsCron`, perform-side in `JobRunnerService`. See [`hex/jobs.md`](./hex/jobs.md); merging them is the obvious cleanup and it destroys the deferral architecture.
- **No real broker.** Both queues are postgres tables — `pings` for ping work, `jobs` for deferred jobs. The doctrine ships no `queue` backing-service role, which is why the worker's AsyncAPI channels address tables rather than topics: the most visible loose end the CICL-v2 advance leaves.

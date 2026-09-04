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
loop singleton, `internal`, no port and no surface). `api.web` is the
`domain_default_service`, so in `prod` the web edge answers at the canonical,
bare-env, and bare-project hosts. `api.web` **uses** `api.worker` (one direction:
`POST /drain` against the worker's `rpc` surface), plus the `appdb`, `probe`, and
`events` backings; the worker and clock reach the worker's queue through the
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
the modules share — the `pings` and `jobs` tables in `appdb` — is documented in
[`db_schema.md`](./api/specifics/db_schema.md).

# Runtime View

Eight flows trace information and action through the running project.

1. **Ping creation.** `POST /pings` on `api.web` → `ContPingsHttp` translates to a
   driving port call → `PingService.create_ping()` constructs a `Ping`, calls
   `RepoPings.save()` → row lands in postgres with `processed_at = NULL` → 201
   returned.
2. **Ping processing.** `entrypoints/worker.py`'s loop calls
   `ContProcessorCli.run_once()` once a second → `ProcessorService` claims
   `pings WHERE processed_at IS NULL` in batches of 32 → for each row the no-op
   business logic runs → `RepoPings.mark_processed(id)` sets `processed_at =
   now()` → the loop touches its tick file (flow 3) and sleeps.
3. **Self health.** `GET /health` on `api.web` returns `{"version": "<project
   version>"}`, straight from the process — and it survives on that core service
   **alone**, because a load balancer reads it and has no other way to ask
   (`healthchecks.md § web services also serve GET /health`). The other two core
   services own loops, and a loop's liveness has to be sourced from the loop:
   `entrypoints/{worker,clock}.py` touch `/tmp/<svc>.tick` at the end of each
   successful iteration, and `./health.sh <svc>` — which the orchestrator runs as
   a **separate process** — stats that file and fails when it is absent or more
   than 30 s old. An **absent** file fails, deliberately: a loop that never
   completed an iteration was never alive, and reporting healthy until the first
   tick would hide a loop that never started. The 30 s threshold lives in
   `health.sh` because the probe is the only thing that judges it; the ≤10 s
   cadence lives in the entrypoints (1 s in the worker, 5 s in the clock) because
   the loop is the only thing that can honour it. **The two numbers are
   meaningless apart:** 30 is three times 10, so a healthy loop misses two
   consecutive ticks before it is called stale — slack for jitter and one slow
   iteration, without giving a wedged loop room to hide.
4. **Deferred-job drain.** `POST /jobs/drain` on `api.web` → `ContJobDrainHttp` →
   `JobDrainService` → `GwyJobRunnerHttp`, which addresses the worker through the
   injected `WORKER_HOST` / `WORKER_PORT` → HTTP `POST /drain` against
   `api.worker`'s `rpc` surface → `ContJobRunnerHttp` → `ContJobRunner.run_once()`
   → `{"performed": N}` travels back out through the edge to the original caller.
   This is the **only** flow that crosses a process boundary between two core
   services, so it is the one that carries the `api.worker` entry in `api.web`'s
   `uses:`, the five-segment magic refs, and rule 32's positive arm. Its reply is
   a **count of work performed** — no liveness verdict and no staleness judgement
   — so it cannot be mistaken for the health fan-out that used to live at
   `/health/api/worker` and exists nowhere now.
5. **Project-local-backing reachability.** `GET /diagnostics/probe` confirms
   `api.web` can resolve and reach the `probe` nginx sidecar by service name;
   `GET /diagnostics/events` confirms it can open a TCP connection to ClickHouse.
   Both exercise Service Connect / docker network DNS at the smoke-test layer.
   They sit under `/diagnostics` rather than `/health` because they probe
   *backing* services, and under `/health/*` a reader would conclude the fan-out
   survived — against `healthchecks.md`'s "No service reports on another."
6. **Scheduled deferral.** `entrypoints/clock.py`'s loop wakes at most every 5 s,
   finds a job whose cron expression is due, and calls `ContJobsCron.fire(name)` →
   the shared driving port `ContJobs` → `JobService` inserts a row into `jobs` →
   the fire returns. **That is the whole of the clock's involvement.** It performs
   no work, because a clock is a singleton with no replicas and no queue-level
   retry, and because only the codebase that owns a schema may write to it. Two
   jobs are scheduled: `prune_pings` at `0 3 * * *`, and `heartbeat` every minute
   so this flow is observable inside a smoke walk rather than only at 03:00.
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
   Nothing external reaches the clock at all: it serves nothing, no route proxies
   it, and the stage tester cannot see it. The probe is therefore the clock's
   **only** liveness channel — reported by docker here and read from `docker
   inspect` by `docex stagetest`, acted on directly by ECS on the elastic
   companion, which kills and replaces the task. Local, but real, and stronger
   than the served route it replaced: the probe stats the loop's own trace from a
   separate process, so a wedged loop cannot answer on its own behalf.

# Deployment View

### Foundation

`fixed`. Production runs as docker containers on a single host machine — for this
test project, the operator's dev machine. All four environments (`dev`, `test`,
`stage`, `prod`) run side-by-side on that one host; the per-project Traefik
distinguishes them by Host header. On `fixed`, docker only *reports* container
health: `docex stagetest` reads `docker inspect`'s `.State.Health.Status` over
SSH and fails the gate on anything that is not `healthy`.

### Domain

`apex_domain: luxrnd.tech` — the bare apex. The project segment derives from
`project.yml`'s `name`, yielding `docex-smoke-fixed.luxrnd.tech`. Per-env hosts
compile to the canonical `<codebase>-<service>.<env>.docex-smoke-fixed.luxrnd.tech`
form, plus the bare-env and bare-project forms, both of which route to
`domain_default_service: api.web`. TLS certs are issued by the per-project Traefik
via Let's Encrypt's DNS-01 challenge against the parent `luxrnd.tech` zone in
Route53. Inbound 443/80 reaches the host's HAProxy `web_demux` (preinfra), which
SNI-routes to the per-project Traefik via the `docex-ingress` bridge.

### Core-service → infrastructure mapping

| Core service | Networks | Port | Fixed infrastructure |
| ------------ | -------- | ---- | -------------------- |
| `api.web` | `web`, `internal` | 8080 | Traefik-routed container; `GET /health` probed by the reverse proxy |
| `api.worker` | `internal` | 8081 | container(s) — `replicas: 2` unrolled in `prod` only; tick-file probe |
| `api.clock` | `internal` | — | singleton container; tick-file probe; no ingress |
| `appdb` | `internal` | — | postgres 15 container |
| `probe` | `internal` | — | nginx sidecar container |
| `events` | `internal` | — | clickhouse container mounting a named docker volume |

One image per codebase: all three core services run the same tag started three
different ways, one registry repo, one `migrate.sh` run per release.

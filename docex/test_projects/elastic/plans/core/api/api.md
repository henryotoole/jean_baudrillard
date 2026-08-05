# api — service architecture

## Purpose

One codebase, one image, **two core services**. `api` is the project's application core: it accepts `POST /pings` at its HTTP edge and processes those pings in a background loop. Both invocations run the same build artifact, share the `pings` table, and read the same six `DATABASE_*` parts.

| Core service | Role | Command | Networks | Port |
| ------------ | ---- | ------- | -------- | ---- |
| `api.web` | `web` | `entrypoints/web.py` | `web`, `internal` | 8080 |
| `api.worker` | `worker` | `entrypoints/worker.py` | `internal` | 8081 (health only, Service-Connect-discoverable) |

`api.web` is the project's `domain_default_service`, so prod's web edge answers at three hosts: `api-web.prod.docex-smoke-elastic.luxrnd.tech` (canonical), `prod.docex-smoke-elastic.luxrnd.tech` (bare-env), and `docex-smoke-elastic.luxrnd.tech` (bare-project ergonomic) — per `cicl.md § Domain`. Routing is handled by the project ALB (mod 038's project-tier ALB with stage+prod ACM certs as SNI bindings); the bare-env and bare-project forms only apply to prod.

`api.worker` is never routed. It carries a `port` and a `health_check_path` purely because it is a `consumes` target and must therefore be probeable (`contracts.md § Declared by fields`).

### Why one codebase and not two

`web` and `worker` were two separate *core services* until CICL v2, and that split was an artifact of the limitation v2 removes: they always shared a database, a table, and six identical magic refs, but pre-v2 CICL had no way to express "one artifact, two invocations". They are now what they always were.

## Hex modules

Two:

- [`pings`](./hex/pings.md) — the `Ping` entity and the `POST /pings` create flow. Driven by `api.web`.
- [`processor`](./hex/processor.md) — claims unprocessed pings and marks them processed. Driven by `api.worker`.

Future modules — none planned. The smoke test exists to exercise *doctrine surface*, not to grow an application.

## Composition root

`src/root.py`, and there is exactly **one** of it — not one per core service. Splitting the root would put two copies of the driven wiring in the tree, and they would drift (`internal_dependency_rules.md § Entrypoints`, rule 3).

**The root constructs; it does not activate.** It opens no socket, starts no server, and runs no loop. It exposes two build functions:

- `build_app() -> FastAPI` — `RepoPingsPostgres` → `PingService` → `ContPingsHttp`, plus the standalone `/health`, `/health/probe`, `/health/events`, and `/health/api/worker` routes.
- `build_processor() -> ContProcessorCli` — the processor module's `RepoPingsPostgres` → `ProcessorService` → `ContProcessorCli`, returned un-run.

## Entrypoints

`src/entrypoints/`, one module per core service; each is what that core service's `command` invokes.

- `web.py` — calls `build_app()` and hands it to uvicorn. The runtime host belongs here, not in an adapter.
- `worker.py` — owns the three things a loop-owning core service owes and an adapter must not:
  1. the **poll loop** (1 s interval) driving `ContProcessorCli.run_once()`,
  2. the **signal handling** (SIGTERM/SIGINT set a stop flag; the loop exits after the current iteration),
  3. the **liveness surface** — a monotonic tick bumped once per successful iteration, and a `GET /health` on port 8081 that 503s once that tick is 30 s stale. Thresholds are doctrine-fixed (`contracts.md § Health Checks`): tick at least every 10 s even when idle, 30 s staleness. There is no knob.

  The tick is **not** bumped in the exception path. A loop that fails every iteration is not alive, and bumping there would report 200 forever while no work moved.

  uvicorn runs in a daemon thread and the loop in the main thread, because signals only reach the main thread and it is the loop that has to hear SIGTERM.

## Contracts

Two, because the codebase has two boundaries and the contract path is keyed on the core service:

- `infra/contracts/api.web.openapi.yml` — `role: web` → OpenAPI. Declares `/pings`, `/health`, the doctrine-required `/health/api/worker` fan-out, and the two optional backing probes.
- `infra/contracts/api.worker.asyncapi.yml` — `role: worker` → AsyncAPI. Describes only the message boundary; the worker's probeability lives in its `port` + `health_check_path` fields, not here.

## Database

This codebase owns the schema (`schema_owned_by: api`). See [`db_schema.md`](./db_schema.md). Migrations live at `core/api/migrations/` and are driven by `core/api/migrate.sh` (dbmate), which runs **once per codebase**, not once per core service. On `stage`/`prod`, the doctrine emits **one** migration ECS task-definition family per codebase (same image, command `migrate.sh`); `docex release <env>` dispatches it via `RunTask` per `release_flow.md`.

Because it runs per codebase, `migrate.sh` may read **service-level `env:` only**. The six `DATABASE_*` parts are declared at the `api` service level for exactly that reason; a service-scoped var such as `WORKER_HOST` would simply be absent, silently.

## Hard boundaries

- **The two hex modules do not import each other.** `pings` writes pings; `processor` consumes them. They are connected only by the `pings` table, and each reaches it through its own `RepoPingsPostgres`. Sharing a codebase does not make them one module.
- **No `consumes: [api.web]` on the worker.** `cicl.md`'s worked example declares the mutual `web ↔ worker` cycle, and it is legal — but *this* worker polls a table and never calls the web edge, so the reverse edge would be a false declaration in a file downstream projects copy.
- **`/health/api/worker` is one hop only.** It proxies the worker's own `/health` and never its fan-out endpoints; the `consumes` graph may cycle.
- `/health/probe` and `/health/events` are exercise endpoints for the project-local backings — they are *not* doctrine-mandated (probe and events are backings, not core services). They exist so the stage tests can catch Service Connect / SG / EFS-mount wiring regressions.
- **No real queue.** The `pings` table is the work queue. The doctrine ships no `queue` role, which is why the worker's AsyncAPI channel addresses a table rather than a topic — the most visible loose end the CICL-v2 advance leaves.

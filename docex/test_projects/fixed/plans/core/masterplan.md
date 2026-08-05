# docex_smoke_fixed — Masterplan

## Purpose

This is one of two **doctrine smoke-test projects** that ship inside the `docex/` tree. It is *not* a real product — it exists so that, before cutting a minor or major `docex` version, the operator can drive a real `fixed`-foundation project end-to-end through `projinfra → envinfra → check → merge → containerize → release stage → stagetest → release prod → teardown` and surface the bugs that only appear against real infrastructure.

The companion project at `docex/test_projects/elastic/` exercises the `elastic`-foundation path. Together they cover the two foundations the doctrine commits to.

## Objectives

1. **Exercise the fixed-foundation release path end-to-end** — the surface that unit tests structurally can't reach.
2. **Stay doctrine-faithful** — every artifact should be what current doctrine prescribes a fixed-foundation project to look like. If walking the inception flow surfaces an ambiguity, the fix lands in the doctrine, not in a workaround here.
3. **Exercise the project-local transfer-table feature** — `infra/transfer_tables/{sidecar,clickhouse}.yml` declare two project-local engines (a stateless nginx sidecar and a stateful ClickHouse analytics_db) so each cut exercises the deep-merge path, container-backings on the dispatch surface, and (on the elastic counterpart) the EFS persistent-storage machinery.

## Terms

| Term | Meaning |
| ---- | ------- |
| Ping | A small unit of work created by the `api.web` core service and consumed (processed) by the `api.worker` core service. Postgres-mediated; no real queue. |
| Codebase | A core service: one source tree, one build artifact, one image. `api` and `reaper` are the two codebases here. |
| Core service | One named way of invoking a codebase's artifact — its own role, command, port, networks, and resources. Emitted as `<codebase>-<process>`. |
| Smoke test | The operator-driven manual walk through `PRE_CUT_CHECKLIST.md` against this project before a `docex` cut. |

## Architecture

### Foundation

`fixed`. Production runs as docker containers on a single host machine — for this test project, the operator's dev machine. All four environments (`dev`, `test`, `stage`, `prod`) run side-by-side on that one host; the per-project Traefik distinguishes them by Host header.

### Domain

`apex_domain: luxrnd.tech` — the bare apex domain (`infra.yml` rule 13). The project segment is derived from `project.yml`'s `name` field DNS-labeled, yielding `docex-smoke-fixed.luxrnd.tech` as the project subdomain. Per-env hosts compile to the doctrine's canonical form `<service>-<process>.<env>.docex-smoke-fixed.luxrnd.tech` — two segments in one DNS label, hyphen-joined, e.g. `api-web.prod.docex-smoke-fixed.luxrnd.tech` — plus the bare-env (`<env>.docex-smoke-fixed.luxrnd.tech`) and bare-project (`docex-smoke-fixed.luxrnd.tech`) forms, both of which route to `domain_default_service: api.web`.

TLS certs are issued by the per-project Traefik via Let's Encrypt's DNS-01 challenge against the parent `luxrnd.tech` zone in Route53 (HTTP-01 won't work for wildcards). Traefik's Route53 credentials and ACME email are supplied at runtime as `TRAEFIK_DNS_PROVIDER`/`TRAEFIK_ACME_EMAIL` env vars on the project Traefik container (operator-side setup).

Inbound 443/80 reaches the host machine's HAProxy `web_demux` (preinfra; see `doctrine/infrastructure/preinfra/fixed_master_network.md`), which SNI-routes to the per-project Traefik via the `docex-ingress` bridge.

### Backing Services

| Service | Role | Engine | Purpose |
| ------- | ---- | ------ | ------- |
| `appdb` | `relational_db` | postgres 15 | Stores `pings` rows. `schema_owned_by: api` — a codebase, never a core service. |
| `probe` | `sidecar` (project-local) | nginx | Stateless sidecar reachability target. |
| `events` | `analytics_db` (project-local) | clickhouse | Stateful OLAP container backing; opts into AWS Backup on elastic. |

The two project-local backings exercise the project-local transfer-table feature: `infra/transfer_tables/{sidecar.yml, clickhouse.yml}`. On fixed, `events` mounts a named docker volume; on the elastic counterpart, the engine declares `persistent_storage` and emits an EFS filesystem with mount targets in each private subnet.

### Core Services

**Two codebases, three core services.** Both codebases are hexagonally-architectured per `doctrine/hexagonal_architecture/` and written in Python.

| Codebase | Core service | Role | Networks | Port | Trigger |
| -------- | ------------ | ---- | -------- | ---- | ------- |
| `api` | `web` | `web` | `web`, `internal` | 8080 | long-running |
| `api` | `worker` | `worker` | `internal` | 8081 (health only) | long-running |
| `reaper` | `prune` | `scheduler` | `internal` | — | cron `0 3 * * *` |

One image per **codebase**, so `api-web` and `api-worker` run the same tag started two different ways, and `reaper-prune` runs its own.

#### `api` — the application codebase

See [`api/api.md`](./api/api.md). Two core services on one artifact; they were two separate core services until CICL v2, purely because pre-v2 CICL could not express "one artifact, two invocations".

- **Hex modules**: [`pings`](./api/hex/pings.md) (driven by `api.web`) and [`processor`](./api/hex/processor.md) (driven by `api.worker`). They share a codebase but not a module boundary — no imports cross between them.
- **Contracts**: `api.web.openapi.yml` (role `web` → OpenAPI) and `api.worker.asyncapi.yml` (role `worker` → AsyncAPI). Two boundaries, two contracts; the path is keyed on the core service.
- **`consumes`**: `api.web consumes api.worker`, one direction only. `api.web` holds four-segment magic refs to `${codebases.api.core_services.worker.host}` / `.port`, which is what obliges the edge (rule 7); the worker never calls the web edge, so the reverse edge would be a false declaration.
- **Schema owner**: `schema_owned_by: api`. `migrate.sh` runs once for the codebase, not once per core service.

`api.web` is the `domain_default_service`, so prod's web edge answers at three hosts: `api-web.prod.docex-smoke-fixed.luxrnd.tech`, `prod.docex-smoke-fixed.luxrnd.tech` (bare-env), and `docex-smoke-fixed.luxrnd.tech` (bare-project).

`api.worker` is never routed and carries a `port` + `health_check_path` solely because a `consumes` target must be probeable. Its `/health` reports the **poll loop's** monotonic tick, not the process's aliveness: 503 once the tick is 30 s stale, tick at least every 10 s even when idle. Both thresholds are doctrine-fixed. `replicas: 2` is declared and honoured in `prod` only.

`api.web` exposes `/health` (doctrine-mandated), `/health/api/worker` (doctrine-mandated — the `consumes` fan-out, one hop, short hard timeout), and `/health/probe` + `/health/events` (**not** doctrine-mandated — probe and events are *backing services*, not core services; they let the stage tests catch wiring regressions in Service Connect, SG self-ingress, and EFS mount-target setup on the elastic counterpart).

#### `reaper` — the scheduler codebase

One core service, `prune`, named after the **job** rather than the role, per `cicl.md § Naming convention` — a scheduler codebase commonly carries several jobs. That is what makes the emitted name `reaper-prune` rather than the `reaper-reaper` a mechanical nesting would have produced.

- **Role**: `scheduler` — a cron-triggered, run-to-completion job, not a long-running server. On fixed, an Ofelia container launches it as a one-off container per fire; on the elastic counterpart, an EventBridge Scheduler invokes an ECS `RunTask` (no `ecs_service`). Suppressed entirely in the `test` env (the trigger is dropped so a job never fires inside the test window).
- **Schedule**: `0 3 * * *` (03:00 UTC daily).
- **Contract**: none. `scheduler` core services are exempt from both the contract and the health model — cron invokes them and nobody else does, so a scheduler is never a `consumes` target.
- **Driving adapters**: `ContReaperCli` (translates the job trigger into a single `reap()` call, then exits 0).
- **Driven adapters**: `RepoPingsPostgres` (its own minimal repo — a single `delete_processed_before` method; no code shared with `api` per the cross-module rule).
- **Hex modules**: **`reaper`** — domain value `RetentionWindow` (a positive-day window with a `cutoff(now)`); alogic `ReaperService.reap()` deletes processed pings older than the cutoff.

`reaper-prune` is the only end-to-end scheduler coverage that exists anywhere: no integration test covers a scheduler, so the fixed smoke walk is it.

### Composition Roots and Entrypoints

One `root.py` per **codebase** — not per core service. The root **constructs**: it instantiates `RepoPingsPostgres`, the alogic service, and the driving adapter, and returns them. It **does not activate**: it opens no socket, starts no server, and runs no loop.

Activation lives in `src/entrypoints/`, one module per core service, and each core service's `command` invokes exactly one of them:

| Core service | `command` | Entrypoint owns |
| ------------ | --------- | --------------- |
| `api.web` | `entrypoints/web.py` | uvicorn |
| `api.worker` | `entrypoints/worker.py` | poll loop, SIGTERM handling, liveness tick + health server |
| `reaper.prune` | `entrypoints/prune.py` | one pass, then `sys.exit` |

The Dockerfile `CMD` is deliberately irrelevant for core services: `command` is required on every core service and supersedes it.

## Flows

1. **Ping creation.** `POST /pings` on `api.web` → `ContPingsHttp` translates to a driving port call → `PingService.create_ping()` constructs a `Ping`, calls `RepoPings.save()` → row lands in postgres with `processed_at = NULL` → 201 returned.
2. **Ping processing.** `entrypoints/worker.py`'s loop calls `ContProcessorCli.run_once()` once a second → `ProcessorService` claims `pings WHERE processed_at IS NULL` in batches of 32 → for each row the no-op business logic runs → `RepoPings.mark_processed(id)` sets `processed_at = now()` → the loop bumps its monotonic tick and sleeps.
3. **Self health.** `GET /health` on `api.web` returns `{"version": "<project version>"}`, straight from the process. `GET /health` on `api.worker` returns the same shape but is gated on the tick from flow 2: stale by more than 30 s and it 503s, which is what makes a wedged loop fail its own probe rather than a liveness thread reporting health while nothing moves.
4. **Health fan-out.** `GET /health/api/worker` on `api.web` proxies the worker's own `/health` over the internal network with a hard 3 s timeout — one hop, never the target's fan-out, because the `consumes` graph may legally cycle. Doctrine-required, because `api.web` declares `consumes: [api.worker]` and the worker is not on the `web` network. This is the only externally-visible view of the worker's liveness.
5. **Project-local-backing reachability.** `GET /health/probe` confirms `api.web` can resolve and reach the `probe` nginx sidecar by service name; `GET /health/events` confirms it can open a TCP connection to ClickHouse. Both exercise Service Connect / docker network DNS at the smoke-test layer.
6. **Ping reaping.** Nightly (`0 3 * * *`), the `reaper.prune` job fires → `ReaperService.reap()` computes the cutoff from a 30-day `RetentionWindow` → `RepoPings.delete_processed_before(cutoff)` deletes expired *processed* pings (unprocessed and recently-processed rows survive) → the job exits 0. Suppressed in `test`.

## Hard Boundaries

- This project does **not** solve a real problem. The flows are minimal-by-design.
- This project does **not** carry custom transfer tables beyond `sidecar.yml` and `clickhouse.yml`. Those two exist specifically to keep the project-local-transfer-table surface exercised every cut; if a smoke walk surfaces an ambiguity in the doctrine's project-local mechanism, the fix lands in doctrine, not in additional tables here.
- This project does **not** consume a real broker. Its "queue" is the `pings` table, because the doctrine ships no `queue` role — the most visible loose end the CICL-v2 advance leaves, and recorded in `api.worker.asyncapi.yml`'s header rather than hidden.
- This project does **not** ship with custom observability, alerting, or anything in the Deferred section of `doctrine/infrastructure/infrastructure.md`. If the smoke test surfaces a need for one of those, that's a Deferred item being un-deferred.

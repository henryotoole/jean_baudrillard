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
| Job | A named unit of deferred work. `api.clock` enqueues one when a schedule fires; `api.worker` claims and performs it. Carries a name and no payload. |
| Codebase | One source tree, one build artifact, one image. `api` is the only codebase here. |
| Core service | One named way of invoking a codebase's artifact — its own role, command, port, networks, and resources. Emitted as `<codebase>-<service>`. |
| Smoke test | The operator-driven manual walk through `PRE_CUT_CHECKLIST.md` against this project before a `docex` cut. |

## Architecture

### Foundation

`fixed`. Production runs as docker containers on a single host machine — for this test project, the operator's dev machine. All four environments (`dev`, `test`, `stage`, `prod`) run side-by-side on that one host; the per-project Traefik distinguishes them by Host header.

### Domain

`apex_domain: luxrnd.tech` — the bare apex domain (`infra.yml` rule 13). The project segment is derived from `project.yml`'s `name` field DNS-labeled, yielding `docex-smoke-fixed.luxrnd.tech` as the project subdomain. Per-env hosts compile to the doctrine's canonical form `<codebase>-<service>.<env>.docex-smoke-fixed.luxrnd.tech` — two segments in one DNS label, hyphen-joined, e.g. `api-web.prod.docex-smoke-fixed.luxrnd.tech` — plus the bare-env (`<env>.docex-smoke-fixed.luxrnd.tech`) and bare-project (`docex-smoke-fixed.luxrnd.tech`) forms, both of which route to `domain_default_service: api.web`.

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

**One codebase, three core services.** It is hexagonally-architectured per `doctrine/hexagonal_architecture/` and written in Python.

| Codebase | Core service | Role | Networks | Port | Trigger |
| -------- | ------------ | ---- | -------- | ---- | ------- |
| `api` | `web` | `web` | `web`, `internal` | 8080 | long-running |
| `api` | `worker` | `worker` | `internal` | 8081 (health only) | long-running |
| `api` | `clock` | `clock` | `internal` | 8082 (health only) | long-running |

One image per **codebase**, so all three run the same tag started three different ways — one build, one registry repo, one `-exec` container, one `migrate.sh` run per release, three sidecars.

#### `api` — the application codebase

See [`api/api.md`](./api/api.md). Three core services on one artifact; `web` and `worker` were two separate codebases until CICL v2, purely because pre-v2 CICL could not express "one artifact, two invocations".

- **Hex modules**: [`pings`](./api/hex/pings.md) (driven by `api.web`), [`processor`](./api/hex/processor.md) (driven by `api.worker`), [`jobs`](./api/hex/jobs.md) (deferred by `api.clock`, performed by `api.worker`), and [`retention`](./api/hex/retention.md) (reached only through the `prune_pings` job). They share a codebase but not a module boundary; the sole cross-module import is `jobs`' runner taking `retention`'s **driving port**, which is the one the doctrine permits.
- **Contracts**: `api.web.openapi.yml` (role `web` → OpenAPI) and `api.worker.asyncapi.yml` (role `worker` → AsyncAPI). Two boundaries, two contracts; the path is keyed on the core service.
- **`uses`**: `api.web` uses `api.worker`, one direction only. `api.web` holds five-segment magic refs to `${codebases.api.core_services.worker.host}` / `.port`, which is what obliges the edge (rule 7); the worker never calls the web edge, so the reverse edge would be a false declaration.
- **Schema owner**: `schema_owned_by: api`. `migrate.sh` runs once for the codebase, not once per core service.

`api.web` is the `domain_default_service`, so prod's web edge answers at three hosts: `api-web.prod.docex-smoke-fixed.luxrnd.tech`, `prod.docex-smoke-fixed.luxrnd.tech` (bare-env), and `docex-smoke-fixed.luxrnd.tech` (bare-project).

`api.worker` is never routed and carries a `port` + `health_check_path` solely because a core `uses` target must be probeable. Its `/health` reports the **poll loop's** monotonic tick, not the process's aliveness: 503 once the tick is 30 s stale, tick at least every 10 s even when idle. Both thresholds are doctrine-fixed. `replicas: 2` is declared and honoured in `prod` only.

`api.web` exposes `/health` (doctrine-mandated), `/health/api/worker` (doctrine-mandated — the `uses` fan-out, one hop, short hard timeout), and `/health/probe` + `/health/events` (**not** doctrine-mandated — probe and events are *backing services*, not core services; they let the stage tests catch wiring regressions in Service Connect, SG self-ingress, and EFS mount-target setup on the elastic counterpart).

#### `api.clock` — the scheduler that is an ordinary core service

`api.clock` is a **long-running singleton container**, not a triggered job. That is the whole point of `role: clock`: a schedule is a property of an invocation, not of a deployment, so the clock is simply the invocation that owns the cron loop.

- **Schedules**: declared in `infra.yml` as bare 5-field UTC cron — `prune_pings: "0 3 * * *"` and `heartbeat: "* * * * *"`. The compiler delivers this clock's own job map to the container in **`DOCEX_SCHEDULES_YAML`**, whose value is the *literal rendered YAML* and not a path, identically on both foundations. It also renders `infra/output/<env>/schedules.yml` — a visibility artifact nothing reads at runtime, which is what makes a schedule change show up in review as an infrastructure change.
- **No dialect translation anywhere.** The expression reaches the container verbatim and the codebase's cron library parses it, which deletes a whole class of bug that a cloud scheduling primitive forces.
- **It validates its own schedule at startup.** Before entering the loop, the clock compares every scheduled name against `ContJobsCron`'s dispatch table and **exits non-zero** if any has no binding, naming both the offending job and the implemented set. A typo in `schedules:` fails the *deploy*, visibly, instead of surfacing at 03:00 as a logged failure. The reverse — a bound job with no schedule — is legitimate and deliberately unchecked, because `ContJobs` is shared and a job reachable only over HTTP or CLI is a design choice.
- **It defers; it does not work.** Each fire enqueues onto the `jobs` table and returns. The work is `api.worker`'s.
- **No exemptions.** It serves `/health` off its loop tick, gets an OTel sidecar like any other core service, and gets a container healthcheck. `replicas` is forbidden on a clock — it is a singleton — and on elastic it deploys stop-then-start (`deployment_minimum_healthy_percent = 0` / `maximum = 100`) so a rolling deploy cannot double-fire.
- **Contract**: none, and that is the ordinary rule rather than an exemption. The provider set is (core-service `uses` targets) ∪ (`web`-network core services), and the clock is neither.
- **`uses: [appdb, api.worker]`** — with **no** magic ref to the worker. The clock reaches it through the `jobs` table rather than the mesh, so there is nothing to reference; the edge declares the interface. A ref implies an edge, never the reverse.

#### Why there is only one codebase

Until the clock advance there were two: `api`, and a scheduler-only codebase named `reaper` whose single core service pruned expired pings on a nightly cron. When `role: scheduler` was retired, **`reaper` could not become a clock.** A clock defers onto its own codebase's queue, only the codebase that owns a schema may enqueue, and `reaper` owned no schema (it reached into `api`'s `pings` table), no worker, and no queue. `api` owns all three, so the clock folded in here and `reaper` was deleted; its retention rule became the [`retention`](./api/hex/retention.md) module.

The walk therefore stopped covering the two-codebase shape. That loss is deliberate and is recorded in `docex/plans/core/test_projects.md § Shape`, which is where a reader who finds one codebase should look before concluding the doc is stale.

### Composition Roots and Entrypoints

One `root.py` per **codebase** — not per core service. The root **constructs**: it instantiates `RepoPingsPostgres`, the alogic service, and the driving adapter, and returns them. It **does not activate**: it opens no socket, starts no server, and runs no loop.

Activation lives in `src/entrypoints/`, one module per core service, and each core service's `command` invokes exactly one of them:

| Core service | `command` | Entrypoint owns |
| ------------ | --------- | --------------- |
| `api.web` | `entrypoints/web.py` | uvicorn |
| `api.worker` | `entrypoints/worker.py` | poll loop (pings **and** the job queue), SIGTERM handling, liveness tick + health server |
| `api.clock` | `entrypoints/clock.py` | cron loop on a bounded 5 s wait, SIGTERM handling, liveness tick + health server |

`clock.py` is the doctrine's **reference implementation** of a clock runtime host, and `worker.py` of a loop-owning consumer. Downstream projects copy both, so changes there are made deliberately.

The Dockerfile `CMD` is deliberately irrelevant for core services: `command` is required on every core service and supersedes it.

## Flows

1. **Ping creation.** `POST /pings` on `api.web` → `ContPingsHttp` translates to a driving port call → `PingService.create_ping()` constructs a `Ping`, calls `RepoPings.save()` → row lands in postgres with `processed_at = NULL` → 201 returned.
2. **Ping processing.** `entrypoints/worker.py`'s loop calls `ContProcessorCli.run_once()` once a second → `ProcessorService` claims `pings WHERE processed_at IS NULL` in batches of 32 → for each row the no-op business logic runs → `RepoPings.mark_processed(id)` sets `processed_at = now()` → the loop bumps its monotonic tick and sleeps.
3. **Self health.** `GET /health` on `api.web` returns `{"version": "<project version>"}`, straight from the process. `GET /health` on `api.worker` returns the same shape but is gated on the tick from flow 2: stale by more than 30 s and it 503s, which is what makes a wedged loop fail its own probe rather than a liveness thread reporting health while nothing moves.
4. **Health fan-out.** `GET /health/api/worker` on `api.web` proxies the worker's own `/health` over the internal network with a hard 3 s timeout — one hop, never the target's fan-out, because the `uses` graph may legally cycle. Doctrine-required, because `api.web` declares `api.worker` in `uses:` and the worker is not on the `web` network. This is the only externally-visible view of the worker's liveness.
5. **Project-local-backing reachability.** `GET /health/probe` confirms `api.web` can resolve and reach the `probe` nginx sidecar by service name; `GET /health/events` confirms it can open a TCP connection to ClickHouse. Both exercise Service Connect / docker network DNS at the smoke-test layer.
6. **Scheduled deferral.** `entrypoints/clock.py`'s loop wakes at most every 5 s, finds a job whose cron expression is due, and calls `ContJobsCron.fire(name)` → the shared driving port `ContJobs` → `JobService` inserts a row into `jobs` → the fire returns. **That is the whole of the clock's involvement.** It performs no work, because a clock is a singleton with no replicas and no queue-level retry, and because only the codebase that owns a schema may write to it. Two jobs are scheduled: `prune_pings` at `0 3 * * *`, and `heartbeat` every minute so this flow is observable inside a smoke walk rather than only at 03:00.
7. **Job draining.** The same `api.worker` pass as flow 2 calls `ContJobRunnerCli.run_once()` → `JobRunnerService` claims a batch `FOR UPDATE SKIP LOCKED` (exclusive against the second replica), looks each row's `name` up in its **perform-side** table, and runs the handler → `prune_pings` calls `retention`'s driving port, computing a cutoff from a 30-day `RetentionWindow` and deleting expired *processed* pings (unprocessed and recently-processed rows survive); `heartbeat` logs and returns. Each row is stamped `finished_at`, with `error` set on failure and the drain continuing past it.
8. **Clock self health.** `GET /health` on `api.clock` reports the cron loop's monotonic tick, 503ing at 30 s stale, exactly as flow 3 does for the worker. Nothing external reaches it: no fan-out proxies it and the stage tester cannot see it, so this probe is consumed by the **container healthcheck alone**, which restarts a wedged clock. Local enforcement, but real.

## Hard Boundaries

- This project does **not** solve a real problem. The flows are minimal-by-design.
- This project does **not** carry custom transfer tables beyond `sidecar.yml` and `clickhouse.yml`. Those two exist specifically to keep the project-local-transfer-table surface exercised every cut; if a smoke walk surfaces an ambiguity in the doctrine's project-local mechanism, the fix lands in doctrine, not in additional tables here.
- This project does **not** consume a real broker. Both its queues are postgres tables — `pings` for ping work and `jobs` for deferred jobs — because the doctrine ships no `queue` backing-service role. That is the most visible loose end the CICL-v2 advance leaves, and it is recorded in `api.worker.asyncapi.yml`'s header rather than hidden.
- This project has **one codebase**, deliberately. It carried two until the clock advance: `reaper`, a scheduler-only codebase, was deleted when `role: scheduler` was retired. It could not become a clock — a clock defers onto its own codebase's queue, only the schema-owning codebase may enqueue, and `reaper` owned no schema, no worker, and no queue. **This is not drift and it must not be "restored".** What the second codebase used to cover, and what its loss costs the smoke walk, is recorded in `docex/plans/core/test_projects.md § Shape`.
- This project does **not** ship with custom observability, alerting, or anything in the Deferred section of `doctrine/infrastructure/infrastructure.md`. If the smoke test surfaces a need for one of those, that's a Deferred item being un-deferred.

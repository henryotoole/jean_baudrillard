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
| Ping | A small unit of work created by the `web` service and consumed (processed) by the `worker` service. Postgres-mediated; no real queue. |
| Smoke test | The operator-driven manual walk through `PRE_CUT_CHECKLIST.md` against this project before a `docex` cut. |

## Architecture

### Foundation

`fixed`. Production runs as docker containers on a single host machine — for this test project, the operator's dev machine. All four environments (`dev`, `test`, `stage`, `prod`) run side-by-side on that one host; the per-project Traefik distinguishes them by Host header.

### Domain

`apex_domain: luxrnd.tech` — the bare apex domain (`infra.yml` rule 13). The project segment is derived from `project.yml`'s `name` field DNS-labeled, yielding `docex-smoke-fixed.luxrnd.tech` as the project subdomain. Per-env hosts compile to the doctrine's canonical form `<service>.<env>.docex-smoke-fixed.luxrnd.tech`, plus the bare-env (`<env>.docex-smoke-fixed.luxrnd.tech`) and bare-project (`docex-smoke-fixed.luxrnd.tech`, prod's `domain_default_service`) forms.

TLS certs are issued by the per-project Traefik via Let's Encrypt's DNS-01 challenge against the parent `luxrnd.tech` zone in Route53 (HTTP-01 won't work for wildcards). Traefik's Route53 credentials and ACME email are supplied at runtime as `TRAEFIK_DNS_PROVIDER`/`TRAEFIK_ACME_EMAIL` env vars on the project Traefik container (operator-side setup).

Inbound 443/80 reaches the host machine's HAProxy `web_demux` (preinfra; see `doctrine/infrastructure/preinfra/fixed_master_network.md`), which SNI-routes to the per-project Traefik via the `docex-ingress` bridge.

### Backing Services

| Service | Role | Engine | Purpose |
| ------- | ---- | ------ | ------- |
| `appdb` | `relational_db` | postgres 15 | Stores `pings` rows. `schema_owned_by: web`. |
| `probe` | `sidecar` (project-local) | nginx | Stateless sidecar reachability target. |
| `events` | `analytics_db` (project-local) | clickhouse | Stateful OLAP container backing; opts into AWS Backup on elastic. |

The two project-local backings exercise the project-local transfer-table feature: `infra/transfer_tables/{sidecar.yml, clickhouse.yml}`. On fixed, `events` mounts a named docker volume; on the elastic counterpart, the engine declares `persistent_storage` and emits an EFS filesystem with mount targets in each private subnet.

### Core Services

Two services, each hexagonally-architectured per `doctrine/hexagonal_architecture/`. Both are written in Python.

#### `web`

- **Networks**: `web`, `internal`
- **Role**: `web` — the canonical core-service-container role. Routing (Traefik labels on fixed, ALB target groups on elastic) is **network-driven**, not role-static.
- **Contract**: `web.openapi.yml`
- **Driving adapters**: `ContPingsHttp` (FastAPI router)
- **Driven adapters**: `RepoPingsPostgres`
- **Hex modules**:
  - **`pings`** — domain entity `Ping` + alogic to create pings.

`web` is the `domain_default_service`, so prod's `web` answers at three hosts: `web.prod.docex-smoke-fixed.luxrnd.tech`, `prod.docex-smoke-fixed.luxrnd.tech` (bare-env), and `docex-smoke-fixed.luxrnd.tech` (bare-project).

`/health` is the doctrine-mandated liveness endpoint. `/health/probe` and `/health/events` exercise reachability of the project-local sidecar and analytics_db backings — they're not doctrine-mandated (probe and events are *backing services*, not core services) but they let the stage tests catch wiring regressions in Service Connect, SG self-ingress, and EFS mount-target setup on the elastic counterpart.

#### `worker`

- **Networks**: `internal` only
- **Role**: `web` (the same single core-service-container role used by `web` itself; routing is network-driven, so `worker` is on `internal` only and gets no Traefik/ALB exposure)
- **Contract**: none. `worker` does not provide an interface to other core services; it is purely a consumer of `appdb`.
- **Driving adapters**: `ContProcessorCli` (a long-running poll loop, started as the container's main process)
- **Driven adapters**: `RepoPingsPostgres`
- **Hex modules**:
  - **`processor`** — polls `pings` for unprocessed rows and marks them processed.

> **Doctrine readability note.** The `role: web` name is HTTP-flavored, but the role is in fact the single, network-neutral core-service-container role. A non-web core service like `worker` declaring `role: web` reads strangely — flagged for possible follow-up (rename to `role: container`? add a `role: worker` alias?), but not blocking this work.

### Composition Roots

Each core service has its own `root.py` per doctrine. The composition root instantiates `RepoPingsPostgres`, the alogic service, and the driving adapter, then registers any HTTP routes.

## Flows

1. **Ping creation.** `POST /pings` on `web` → `ContPingsHttp` translates to a driving port call → `PingService.create_ping()` constructs a `Ping`, calls `RepoPings.save()` → row lands in postgres with `processed_at = NULL` → 201 returned.
2. **Ping processing.** `worker` polls `pings WHERE processed_at IS NULL` every N seconds → for each row, `ProcessorService.process_ping()` runs (no-op business logic) → `RepoPings.mark_processed(id)` sets `processed_at = now()`.
3. **Health.** `GET /health` on `web` returns `{"version": "<project version>"}`. Doctrine-mandated; exercised by both stage tests and (on the elastic counterpart) the ALB target-group health check. `worker` is not in `web`'s in-process `depends_on` chain (postgres-mediated), so no `/health/worker` endpoint is required.
4. **Project-local-backing reachability.** `GET /health/probe` confirms `web` can resolve and reach the `probe` nginx sidecar by service name; `GET /health/events` confirms it can open a TCP connection to ClickHouse. Both exercise Service Connect / docker network DNS at the smoke-test layer.

## Hard Boundaries

- This project does **not** solve a real problem. The flows are minimal-by-design.
- This project does **not** carry custom transfer tables beyond `sidecar.yml` and `clickhouse.yml`. Those two exist specifically to keep the project-local-transfer-table surface exercised every cut; if a smoke walk surfaces an ambiguity in the doctrine's project-local mechanism, the fix lands in doctrine, not in additional tables here.
- This project does **not** ship with custom observability, alerting, or anything in the [Deferred section](../../../../doctrine/infrastructure/infrastructure.md#deferred) of doctrine. If the smoke test surfaces a need for one of those, that's a Deferred item being un-deferred.

# docex_smoke_fixed — Masterplan

## Purpose

This is one of two **doctrine smoke-test projects** that ship inside the `docex/` tree. It is *not* a real product — it exists so that, before cutting a minor or major `docex` version, the operator can drive a real `fixed`-foundation project end-to-end through `bootstrap → compile → containerize → release stage → stagetest → release prod → teardown` and surface the bugs that only appear against real infrastructure.

The companion project at `docex/test_projects/elastic/` exercises the `elastic`-foundation path. Together they cover the two foundations the doctrine commits to.

## Objectives

1. **Exercise the fixed-foundation release path end-to-end** — the surface that unit tests structurally can't reach.
2. **Stay doctrine-faithful** — every artifact should be what current doctrine prescribes a fixed-foundation project to look like. If walking the inception flow surfaces an ambiguity, the fix lands in the doctrine, not in a workaround here.
3. **Be minimal** — two cores + one schema-owning backing service. Just enough surface to exercise contracts, migrations, the `/health` endpoint gate, secrets, and the reverse-proxy routing path. Not enough to do anything real.

## Terms

| Term | Meaning |
| ---- | ------- |
| Ping | A small unit of work created by the `web` service and consumed (processed) by the `worker` service. Postgres-mediated; no real queue. |
| Smoke test | The operator-driven manual walk through `PRE_CUT_CHECKLIST.md` against this project before a `docex` cut. |

## Architecture

### Foundation

`fixed`. Production runs as docker containers on a single host machine — for this test project, the operator's dev machine (an AWS EC2 instance). All four environments (`dev`, `test`, `stage`, `prod`) run side-by-side on that one host; Traefik distinguishes them by Host header.

### Domain

`doctrine-fixed.luxrnd.tech`. The parent zone `luxrnd.tech` is managed in Route53 from the dev machine's AWS credentials. The operator configures Route53 records so that the four env subdomains resolve to the dev machine's public IP:

- `dev.doctrine-fixed.luxrnd.tech`
- `test.doctrine-fixed.luxrnd.tech`
- `stage.doctrine-fixed.luxrnd.tech`
- `www.doctrine-fixed.luxrnd.tech`

Plus wildcards under each (e.g. `*.dev.doctrine-fixed.luxrnd.tech`) so per-service subdomains resolve too. Wildcard A records keep this manageable. Exact DNS setup lives in `PRE_CUT_CHECKLIST.md`.

TLS certs are provisioned by Traefik via Let's Encrypt's DNS-01 challenge against the Route53 zone (HTTP-01 won't work for wildcards). Traefik's Route53 credentials are part of the host-machine prerequisite setup.

### Backing Services

| Service | Role | Engine | Purpose |
| ------- | ---- | ------ | ------- |
| `db` | `relational_db` | postgres 15 | Stores `pings` rows. `schema_owned_by: web`. |

One backing service. No cache, no object store. The smallest shape that exercises migrations + reserved-name validation + secrets-as-env-vars.

### Core Services

Two services, each hexagonally-architectured per `doctrine/hexagonal_architecture/`. Both are written in Python.

#### `web`

- **Networks**: `web`, `internal`
- **Role**: `web` — the canonical core-service container role. The role applies to any project core service; routing (Traefik labels on fixed, ALB target groups on elastic) is **network-driven**, not role-static.
- **Contract**: `web.openapi.yml`
- **Driving adapters**: `ContPingsHttp` (FastAPI router)
- **Driven adapters**: `RepoPingsPostgres`
- **Hex modules**:
  - **`pings`** — domain entity `Ping` + alogic to create pings.

`web` is the `domain_default_service`, so it answers at the bare env subdomain (`dev.doctrine-fixed.luxrnd.tech`, etc.) in addition to `web.<env>.doctrine-fixed.luxrnd.tech`.

#### `worker`

- **Networks**: `internal` only
- **Role**: `web` (the same single core-service-container role used by `web` itself; routing is network-driven, so `worker` is on `internal` only and gets no Traefik/ALB exposure)
- **Contract**: none. `worker` does not provide an interface to other core services; it is purely a consumer of `db`.
- **Driving adapters**: `ContProcessorCli` (a long-running poll loop, started as the container's main process)
- **Driven adapters**: `RepoPingsPostgres`
- **Hex modules**:
  - **`processor`** — polls `pings` for unprocessed rows and marks them processed.

> **Doctrine readability note.** The `role: web` name is HTTP-flavored (and the transfer table's docstring leans into "behind the reverse proxy") but the role is in fact the single, network-neutral core-service-container role. A non-web core service like `worker` declaring `role: web` is doctrine-correct but reads strangely. This is a clarity nit, not a doctrine bug — flagged for possible follow-up (rename to `role: container`? add a `role: worker` alias?), but not blocking this work.

### Composition Roots

Each core service has its own `root.py` per doctrine. The composition root instantiates `RepoPingsPostgres`, the alogic service, and the driving adapter, then registers any HTTP routes.

## Flows

1. **Ping creation.** `POST /pings` on `web` → `ContPingsHttp` translates to a driving port call → `PingService.create_ping()` constructs a `Ping`, calls `RepoPings.save()` → row lands in postgres with `processed_at = NULL` → 201 returned.
2. **Ping processing.** `worker` polls `pings WHERE processed_at IS NULL` every N seconds → for each row, `ProcessorService.process_ping()` runs (no-op business logic) → `RepoPings.mark_processed(id)` sets `processed_at = now()`.
3. **Health.** `GET /health` on `web` returns `{"version": "<project version from project.yml>"}`. This is the doctrine-mandated endpoint exercised by both stage tests and ALB health checks (the ALB path applies only in the elastic counterpart, but the endpoint exists identically here). `worker` is not in `web`'s `depends_on` chain, so no `/health/worker` endpoint is required by doctrine, and we don't add one — that interaction is exercised by the elastic project where the cluster reports it instead.

## Hard Boundaries

- This project does **not** solve a real problem. The flows are minimal-by-design.
- This project does **not** add custom transfer tables. If a project-local transfer table override would be needed for a real fixed-foundation project, that's a doctrine gap — flag it, don't paper over it.
- This project does **not** ship with custom observability, alerting, or anything in the [Deferred section](../../../../doctrine/infrastructure/infrastructure.md#deferred) of doctrine. If the smoke test surfaces a need for one of those, that's a Deferred item being un-deferred.

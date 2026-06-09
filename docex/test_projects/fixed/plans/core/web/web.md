# web — service architecture

## Purpose

The HTTP front for `docex_smoke_fixed`. Accepts `POST /pings` requests, persists each as a row in postgres for the `worker` to process, and exposes `/health` for liveness probes plus `/health/probe` and `/health/events` for project-local backing reachability checks.

This service is the project's `domain_default_service`, so prod's `web` answers at three hosts: `web.prod.docex-smoke-fixed.luxrnd.tech` (canonical), `prod.docex-smoke-fixed.luxrnd.tech` (bare-env), and `docex-smoke-fixed.luxrnd.tech` (bare-project ergonomic) — per `cicl.md § Domain`. Routing is handled by the per-project Traefik on fixed; the bare-env and bare-project forms only apply to prod.

## Hex modules

One: [`pings`](./hex/pings.md). It owns the `Ping` entity and the `POST /pings` create flow.

Future modules — none planned. The smoke test exists to exercise *doctrine surface*, not to grow an application.

## Composition root

`src/root.py` instantiates:
1. `RepoPingsPostgres` (driven adapter)
2. `PingService` (alogic, given the repo)
3. `ContPingsHttp` (driving adapter, given the service)
4. Registers the FastAPI router and the standalone `/health`, `/health/probe`, `/health/events` routes.

## Database

This service owns the schema. See [`db_schema.md`](./db_schema.md). Migrations live at `core/web/migrations/` and are driven by `core/web/migrate.sh` (dbmate).

## Hard boundaries

- No worker logic lives here. `web` writes pings; `worker` consumes them. They are connected only by the `pings` table.
- No `/health/worker` endpoint. `worker` is not in `web`'s `depends_on` chain (postgres-mediated communication, not in-process), so doctrine does not require it.
- `/health/probe` and `/health/events` are exercise endpoints for the project-local backings — they are *not* doctrine-mandated (probe and events are backings, not core services). They exist so the stage tests can catch Service Connect / SG / EFS-mount wiring regressions on the elastic counterpart.

# web — service architecture

## Purpose

The HTTP front for `docex_smoke_fixed`. Accepts `POST /pings` requests, persists each as a row in postgres for the `worker` to process, and exposes `/health` for liveness probes.

This service is the project's `domain_default_service` and is reached at both `<env>.doctrine-fixed.luxrnd.tech` and `web.<env>.doctrine-fixed.luxrnd.tech` via Traefik (per `cicl.md § Domain`).

## Hex modules

One: [`pings`](./hex/pings.md). It owns the `Ping` entity and the `POST /pings` create flow.

Future modules — none planned. The smoke test exists to exercise *doctrine surface*, not to grow an application.

## Composition root

`src/root.py` instantiates:
1. `RepoPingsPostgres` (driven adapter)
2. `PingService` (alogic, given the repo)
3. `ContPingsHttp` (driving adapter, given the service)
4. Registers the FastAPI router and the standalone `/health` route.

## Database

This service owns the schema. See [`db_schema.md`](./db_schema.md). Migrations live at `core/web/migrations/` and are driven by `core/web/migrate.sh` (dbmate).

## Hard boundaries

- No worker logic lives here. `web` writes pings; `worker` consumes them. They are connected only by the `pings` table.
- No `/health/worker` endpoint. `worker` is not in `web`'s `depends_on` chain (postgres-mediated communication, not in-process), so doctrine does not require it.

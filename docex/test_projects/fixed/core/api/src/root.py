"""Composition root for the `api` core service.

Per doctrine (internal_dependency_rules.md), this is the *only* file in
the codebase that constructs concrete adapters. It builds the dependency
graph and hands the driving adapters back — nothing more.

**The root constructs; it does not activate.** It builds no server, opens
no socket, and runs no loop. Binding a constructed adapter to something
that actually runs belongs to the entrypoints under `src/entrypoints/`,
one module per process type (`web`, `worker`).

There is exactly ONE composition root per codebase, not one per process
type: two copies of the driven wiring drift, which is precisely the bug
class module integration tests exist to catch
(internal_dependency_rules.md § Entrypoints, rule 3).
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request

from fastapi import FastAPI, HTTPException

from hex.pings.adapters.driven.repo_pings_postgres import RepoPingsPostgres
from hex.pings.adapters.driving.cont_pings_http import ContPingsHttp
from hex.pings.alogic.ping_service import PingService
from hex.processor.adapters.driven.repo_pings_postgres import (
    RepoPingsPostgres as RepoPingsPostgresProcessor,
)
from hex.processor.adapters.driving.cont_processor_cli import ContProcessorCli
from hex.processor.alogic.processor_service import ProcessorService


VERSION = os.environ["PROJECT_VERSION"]

# Project-local backing-service magic-ref consumers. Same env-var names
# resolve on both foundations: docker network DNS on fixed, ECS Service
# Connect on elastic. The advance-end smoke walk exercises these.
SIDECAR_HOST = os.environ.get("SIDECAR_HOST")
SIDECAR_PORT = os.environ.get("SIDECAR_PORT")
CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = os.environ.get("CLICKHOUSE_PORT")

# Four-segment core magic refs — ${core_services.api.worker.{host,port}}.
# Declared on the `api.web` process type's env only, which is exactly what
# obliges its `consumes: [api.worker]` entry (cicl.md validation rule 7).
WORKER_HOST = os.environ.get("WORKER_HOST")
WORKER_PORT = os.environ.get("WORKER_PORT")


def _dsn_from_env() -> str:
    """Build the postgres DSN from the doctrine-mandated parts-only env vars."""
    parts = {
        "host": os.environ["DATABASE_HOST"],
        "port": os.environ["DATABASE_PORT"],
        "dbname": os.environ["DATABASE_NAME"],
        "user": os.environ["DATABASE_USER"],
        "password": os.environ["DATABASE_PASSWORD"],
        "sslmode": os.environ["DATABASE_SSLMODE"],
    }
    return (
        f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
        f"user={parts['user']} password={parts['password']} "
        f"sslmode={parts['sslmode']}"
    )


def build_app() -> FastAPI:
    """Construct the `api.web` process type's graph and return its app.

    The app is returned un-served; `entrypoints/web.py` hands it to uvicorn.
    """
    app = FastAPI(title="api", version=VERSION)

    # Driven adapters.
    repo_pings = RepoPingsPostgres(dsn=_dsn_from_env())

    # Alogic.
    ping_service = PingService(repo=repo_pings)

    # Driving adapters.
    cont_pings = ContPingsHttp(service=ping_service)
    app.include_router(cont_pings.router)

    # Health check — doctrine-mandated for every long-running process type.
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"version": VERSION}

    # Reachability checks for the project-local container backings.
    # Exercises Service Connect resolution + SG reachability on elastic,
    # docker network DNS on fixed. Not doctrine-mandated (sidecar and
    # events are backing services, not core), but useful for the smoke
    # test to surface infrastructure misconfiguration.
    @app.get("/health/probe")
    def health_probe() -> dict[str, str | int]:
        if not SIDECAR_HOST or not SIDECAR_PORT:
            raise HTTPException(503, "SIDECAR_HOST/PORT not set")
        try:
            resp = urllib.request.urlopen(
                f"http://{SIDECAR_HOST}:{SIDECAR_PORT}/", timeout=3,
            )
            return {"reachable": "true", "status_code": resp.status}
        except (urllib.error.URLError, OSError) as exc:
            raise HTTPException(503, f"probe unreachable: {exc}")

    @app.get("/health/events")
    def health_events() -> dict[str, str | int]:
        if not CLICKHOUSE_HOST or not CLICKHOUSE_PORT:
            raise HTTPException(503, "CLICKHOUSE_HOST/PORT not set")
        try:
            with socket.create_connection(
                (CLICKHOUSE_HOST, int(CLICKHOUSE_PORT)), timeout=3,
            ):
                return {"reachable": "true", "port": int(CLICKHOUSE_PORT)}
        except OSError as exc:
            raise HTTPException(503, f"events unreachable: {exc}")

    # Health fan-out. Unlike the two probes above, this one IS
    # doctrine-mandated: contracts.md § Fan-out requires every
    # `web`-network process type to expose the health of each `consumes`
    # target that is not itself on the `web` network. `api.worker` sits on
    # `[internal]` alone, so nothing outside can reach its own /health —
    # `api.web` proxies it at /health/<service>/<process>.
    @app.get("/health/api/worker")
    def health_api_worker() -> dict[str, str]:
        if not WORKER_HOST or not WORKER_PORT:
            raise HTTPException(503, "WORKER_HOST/PORT not set")
        # WHY: one hop only — proxy the worker's OWN /health, never its
        # fan-out endpoints. The `consumes` graph may legally contain
        # cycles (cicl.md § The graph may contain cycles), so a fan-out
        # calling a fan-out would recurse without bound. The short hard
        # timeout is the other half of the guarantee: a wedged target must
        # fail this probe fast rather than stall the caller.
        try:
            resp = urllib.request.urlopen(
                f"http://{WORKER_HOST}:{WORKER_PORT}/health", timeout=3,
            )
        except (urllib.error.URLError, OSError) as exc:
            raise HTTPException(503, f"api.worker unreachable: {exc}")
        if resp.status != 200:
            raise HTTPException(503, f"api.worker unhealthy: {resp.status}")
        return {"version": json.loads(resp.read())["version"]}

    return app


def build_processor() -> ContProcessorCli:
    """Construct the `api.worker` process type's graph.

    Returns the driving adapter un-run: `entrypoints/worker.py` owns the
    poll loop, the signal handling, and the liveness surface.
    """
    repo_pings = RepoPingsPostgresProcessor(dsn=_dsn_from_env())
    processor = ProcessorService(repo=repo_pings)
    return ContProcessorCli(service=processor)

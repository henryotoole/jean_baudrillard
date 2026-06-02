"""Composition root for the `web` core service.

Per doctrine (internal_dependency_rules.md), this is the *only* file in
the service that constructs concrete adapters. It wires the dependency
graph and starts the HTTP server.
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.error
import urllib.request

import uvicorn
from fastapi import FastAPI, HTTPException

from hex.pings.adapters.driven.repo_pings_postgres import RepoPingsPostgres
from hex.pings.adapters.driving.cont_pings_http import ContPingsHttp
from hex.pings.alogic.ping_service import PingService


VERSION = os.environ["PROJECT_VERSION"]

# Project-local backing-service magic-ref consumers. Same env-var names
# resolve on both foundations: docker network DNS on fixed, ECS Service
# Connect on elastic. The campaign-end smoke walk exercises these.
SIDECAR_HOST = os.environ.get("SIDECAR_HOST")
SIDECAR_PORT = os.environ.get("SIDECAR_PORT")
CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = os.environ.get("CLICKHOUSE_PORT")


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
    app = FastAPI(title="web", version=VERSION)

    # Driven adapters.
    repo_pings = RepoPingsPostgres(dsn=_dsn_from_env())

    # Alogic.
    ping_service = PingService(repo=repo_pings)

    # Driving adapters.
    cont_pings = ContPingsHttp(service=ping_service)
    app.include_router(cont_pings.router)

    # Health check — doctrine-mandated for any service on the `web` network.
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

    return app


def main() -> None:
    app = build_app()
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())

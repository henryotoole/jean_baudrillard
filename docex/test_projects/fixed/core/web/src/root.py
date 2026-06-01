"""Composition root for the `web` core service.

Per doctrine (internal_dependency_rules.md), this is the *only* file in
the service that constructs concrete adapters. It wires the dependency
graph and starts the HTTP server.
"""

from __future__ import annotations

import os
import sys

import uvicorn
from fastapi import FastAPI

from hex.pings.adapters.driven.repo_pings_postgres import RepoPingsPostgres
from hex.pings.adapters.driving.cont_pings_http import ContPingsHttp
from hex.pings.alogic.ping_service import PingService


VERSION = os.environ.get("APP_VERSION", "0.0.1")


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

    return app


def main() -> None:
    app = build_app()
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())

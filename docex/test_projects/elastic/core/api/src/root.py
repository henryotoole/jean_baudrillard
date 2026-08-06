"""Composition root for the `api` codebase.

Per doctrine (internal_dependency_rules.md), this is the *only* file in
the codebase that constructs concrete adapters. It builds the dependency
graph and hands the driving adapters back — nothing more.

**The root constructs; it does not activate.** It builds no server, opens
no socket, and runs no loop. Binding a constructed adapter to something
that actually runs belongs to the entrypoints under `src/entrypoints/`,
one module per core service (`web`, `worker`, `clock`).

There is exactly ONE composition root per codebase, not one per core
service: two copies of the driven wiring drift, which is precisely the bug
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

from hex.jobs.adapters.driven.queue_jobs_postgres import QueueJobsPostgres
from hex.jobs.adapters.driving.cont_job_runner_cli import ContJobRunnerCli
from hex.jobs.adapters.driving.cont_jobs_cli import ContJobsCli
from hex.jobs.adapters.driving.cont_jobs_cron import ContJobsCron
from hex.jobs.adapters.driving.cont_jobs_http import ContJobsHttp
from hex.jobs.alogic.job_runner_service import JobRunnerService
from hex.jobs.alogic.job_service import JobService
from hex.pings.adapters.driven.repo_pings_postgres import RepoPingsPostgres
from hex.pings.adapters.driving.cont_pings_http import ContPingsHttp
from hex.pings.alogic.ping_service import PingService
from hex.processor.adapters.driven.repo_pings_postgres import (
    RepoPingsPostgres as RepoPingsPostgresProcessor,
)
from hex.processor.adapters.driving.cont_processor_cli import ContProcessorCli
from hex.processor.alogic.processor_service import ProcessorService
from hex.retention.adapters.driven.repo_pings_postgres import (
    RepoPingsPostgres as RepoPingsPostgresRetention,
)
from hex.retention.alogic.retention_service import RetentionService
from hex.retention.domain.retention_window import RetentionWindow


VERSION = os.environ["PROJECT_VERSION"]

# Processed pings are kept this many days, then pruned. A constant here
# (a composition-root wiring decision), not a doctrine secret/part, and
# deliberately NOT a value inside the `retention` module — how long to
# keep data is a deployment choice, not a domain rule.
_RETENTION_DAYS = 30

# Project-local backing-service magic-ref consumers. Same env-var names
# resolve on both foundations: docker network DNS on fixed, ECS Service
# Connect on elastic. The advance-end smoke walk exercises these.
SIDECAR_HOST = os.environ.get("SIDECAR_HOST")
SIDECAR_PORT = os.environ.get("SIDECAR_PORT")
CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = os.environ.get("CLICKHOUSE_PORT")

# Five-segment core magic refs — ${codebases.api.core_services.worker.{host,port}}.
# Declared on the `api.web` core service's env only, which is exactly what
# obliges the `api.worker` entry in its `uses:` list (cicl.md validation rule 7).
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
    """Construct the `api.web` core service's graph and return its app.

    The app is returned un-served; `entrypoints/web.py` hands it to uvicorn.
    """
    app = FastAPI(title="api", version=VERSION)

    # Driven adapters.
    repo_pings = RepoPingsPostgres(dsn=_dsn_from_env())
    queue_jobs = QueueJobsPostgres(dsn=_dsn_from_env())

    # Alogic.
    ping_service = PingService(repo=repo_pings)
    job_service = JobService(queue=queue_jobs)

    # Driving adapters.
    cont_pings = ContPingsHttp(service=ping_service)
    app.include_router(cont_pings.router)
    # The same ContJobs driving port the clock fires, exposed over HTTP —
    # so firing a scheduled job by hand in `dev` is an ordinary call rather
    # than a special path (clock.md § Architecture).
    cont_jobs = ContJobsHttp(service=job_service)
    app.include_router(cont_jobs.router)

    # Health check — doctrine-mandated for every long-running core service.
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
    # `web`-network core service to expose the health of each core `uses`
    # target that is not itself on the `web` network. `api.worker` sits on
    # `[internal]` alone, so nothing outside can reach its own /health —
    # `api.web` proxies it at /health/<codebase>/<service>.
    @app.get("/health/api/worker")
    def health_api_worker() -> dict[str, str]:
        if not WORKER_HOST or not WORKER_PORT:
            raise HTTPException(503, "WORKER_HOST/PORT not set")
        # WHY: one hop only — proxy the worker's OWN /health, never its
        # fan-out endpoints. The `uses` graph may legally contain
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
    """Construct the `api.worker` core service's ping-processing graph.

    Returns the driving adapter un-run: `entrypoints/worker.py` owns the
    poll loop, the signal handling, and the liveness surface.
    """
    repo_pings = RepoPingsPostgresProcessor(dsn=_dsn_from_env())
    processor = ProcessorService(repo=repo_pings)
    return ContProcessorCli(service=processor)


def build_clock() -> ContJobsCron:
    """Construct the `api.clock` core service's graph.

    Returns the cron driving adapter un-run: `entrypoints/clock.py` owns
    the cron loop, the signal handling, and the liveness surface. The
    clock's graph stops at the queue — it holds no retention repo and no
    handler, because it defers and does not work
    (clock.md § The clock defers; it does not work).
    """
    queue_jobs = QueueJobsPostgres(dsn=_dsn_from_env())
    job_service = JobService(queue=queue_jobs)
    return ContJobsCron(service=job_service)


def build_job_runner() -> ContJobRunnerCli:
    """Construct the `api.worker` core service's queue-draining graph.

    The perform side of the queue, and the one place the two hex modules
    meet: `JobRunnerService` holds a `ContRetention`, which is a DRIVING
    port of another module — the single legal cross-module import
    (internal_dependency_rules.md § Cross-Module Imports).
    """
    queue_jobs = QueueJobsPostgres(dsn=_dsn_from_env())
    retention = RetentionService(
        repo=RepoPingsPostgresRetention(dsn=_dsn_from_env()),
        window=RetentionWindow(days=_RETENTION_DAYS),
    )
    runner = JobRunnerService(queue=queue_jobs, retention=retention)
    return ContJobRunnerCli(service=runner)


def build_jobs_cli() -> ContJobsCli:
    """Construct the CLI mechanism for ContJobs.

    **Deliberately unused by every entrypoint**, and that is correct: the
    composition root instantiates every driving mechanism, including ones
    the running core service will never use
    (internal_dependency_rules.md § Composition Root, item 3).
    Construction is free — a controller captures a port reference and
    performs no I/O — and building it here is what keeps the full graph
    visible from one file instead of only the parts today's `command`
    happens to reach.
    """
    queue_jobs = QueueJobsPostgres(dsn=_dsn_from_env())
    return ContJobsCli(service=JobService(queue=queue_jobs))

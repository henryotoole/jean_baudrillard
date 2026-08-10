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

import os
import socket
import urllib.error
import urllib.request

from fastapi import FastAPI, HTTPException

from hex.jobs.adapters.driven.gwy_job_runner_http import GwyJobRunnerHttp
from hex.jobs.adapters.driven.queue_jobs_postgres import QueueJobsPostgres
from hex.jobs.adapters.driving.cont_job_drain_http import ContJobDrainHttp
from hex.jobs.adapters.driving.cont_job_runner_cli import ContJobRunnerCli
from hex.jobs.adapters.driving.cont_job_runner_http import ContJobRunnerHttp
from hex.jobs.adapters.driving.cont_jobs_cli import ContJobsCli
from hex.jobs.adapters.driving.cont_jobs_cron import ContJobsCron
from hex.jobs.adapters.driving.cont_jobs_http import ContJobsHttp
from hex.jobs.alogic.job_drain_service import JobDrainService
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
# Declared on the `api.web` core service's env only. This is the address at
# which `GwyJobRunnerHttp` reaches `api.worker`'s `rpc` surface (POST /drain) —
# an ordinary application call, not a probe of any kind.
#
# Holding these refs obliges two separate declarations in infra.yml:
#   - the `api.worker` entry in `api.web`'s `uses:` list (rule 7) — a ref
#     implies an edge;
#   - the worker's own `port:`, because holding an address is what makes it
#     DIRECTLY ADDRESSED (rule 32's positive arm). `api.clock` also `uses` the
#     worker and holds no ref at all, reaching it through the `jobs` table
#     instead — same target, two consumers, two kinds of edge.
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
    # The consumer side of `api.worker`'s `rpc` surface: POST /jobs/drain
    # here asks the worker to drain the queue in ITS process, because the
    # perform side of the queue belongs to the worker and an edge that
    # drained it itself would be performing rather than deferring.
    #
    # WHY the gateway is constructed even when WORKER_HOST is unset:
    # construction performs no I/O — it captures two strings and fails only
    # when called. That is what keeps `build_app()` importable and callable
    # from `tests/test_smoke.py` inside the `test` container, where no
    # worker address is injected.
    gwy_job_runner = GwyJobRunnerHttp(host=WORKER_HOST, port=WORKER_PORT)
    job_drain_service = JobDrainService(gateway=gwy_job_runner)
    cont_job_drain = ContJobDrainHttp(service=job_drain_service)
    app.include_router(cont_job_drain.router)

    # GET /health survives on THIS core service and no other. Not because
    # every long-running core service owes one — none of them do; a
    # non-`web` core service's liveness is its container probe
    # (`./health.sh <service>`). It is here because `api.web` is on the
    # `web` network and declares `health_check_path: /health`, so the
    # reverse proxy probes it there (the ALB target group on elastic, the
    # project traefik on fixed), and because this project's stage tests
    # assert its body against PROJECT_VERSION. That is the one case
    # healthchecks.md § web services also serve GET /health describes, and
    # `docex check`'s contract_health_path gate gets its assertion from it.
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"version": VERSION}

    # Reachability checks for the project-local container BACKING services:
    # `probe` (sidecar/nginx) and `events` (analytics_db/clickhouse). They
    # are the only exercise either seed gives those project-local engines,
    # and on elastic the only exercise of SG reachability to them —
    # Service Connect resolution there, docker network DNS on fixed.
    #
    # WHY THEY LIVE UNDER /diagnostics AND NOT /health: these are NOT a
    # health fan-out. There is no fan-out — no service reports on another,
    # and healthchecks.md § What this doctrine does not do forbids one.
    # Under /health/* a reader would reasonably conclude the fan-out
    # survived under a narrower name, so they were moved out precisely to
    # foreclose that reading. Neither route reports on a core service and
    # neither carries a liveness verdict.
    @app.get("/diagnostics/probe")
    def diagnostics_probe() -> dict[str, str | int]:
        if not SIDECAR_HOST or not SIDECAR_PORT:
            raise HTTPException(503, "SIDECAR_HOST/PORT not set")
        try:
            resp = urllib.request.urlopen(
                f"http://{SIDECAR_HOST}:{SIDECAR_PORT}/", timeout=3,
            )
            return {"reachable": "true", "status_code": resp.status}
        except (urllib.error.URLError, OSError) as exc:
            raise HTTPException(503, f"probe unreachable: {exc}")

    @app.get("/diagnostics/events")
    def diagnostics_events() -> dict[str, str | int]:
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


def build_processor() -> ContProcessorCli:
    """Construct the `api.worker` core service's ping-processing graph.

    Returns the driving adapter un-run: `entrypoints/worker.py` owns the
    poll loop, the signal handling, and the loop's tick file.
    """
    repo_pings = RepoPingsPostgresProcessor(dsn=_dsn_from_env())
    processor = ProcessorService(repo=repo_pings)
    return ContProcessorCli(service=processor)


def build_clock() -> ContJobsCron:
    """Construct the `api.clock` core service's graph.

    Returns the cron driving adapter un-run: `entrypoints/clock.py` owns
    the cron loop, the signal handling, and the loop's tick file. It owns
    no server: a clock declares no surface and listens on nothing. The
    clock's graph stops at the queue — it holds no retention repo and no
    handler, because it defers and does not work
    (clock.md § The clock defers; it does not work).
    """
    queue_jobs = QueueJobsPostgres(dsn=_dsn_from_env())
    job_service = JobService(queue=queue_jobs)
    return ContJobsCron(service=job_service)


def _job_runner_service() -> JobRunnerService:
    """The perform-side graph, built once and shared by both mechanisms.

    The perform side of the queue, and the one place the two hex modules
    meet: `JobRunnerService` holds a `ContRetention`, which is a DRIVING
    port of another module — the single legal cross-module import
    (internal_dependency_rules.md § Cross-Module Imports).

    WHY this is factored out rather than written twice: `ContJobRunner` has
    two mechanisms on `api.worker` — the CLI the poll loop drives and the
    HTTP router the `rpc` surface serves — and two copies of this wiring
    would drift. That is the same argument
    `internal_dependency_rules.md § Entrypoints` rule 3 makes against
    splitting the composition root, applied one level down.
    """
    queue_jobs = QueueJobsPostgres(dsn=_dsn_from_env())
    retention = RetentionService(
        repo=RepoPingsPostgresRetention(dsn=_dsn_from_env()),
        window=RetentionWindow(days=_RETENTION_DAYS),
    )
    return JobRunnerService(queue=queue_jobs, retention=retention)


def build_job_runner() -> ContJobRunnerCli:
    """Construct the CLI mechanism for ContJobRunner.

    Driven once per iteration by `entrypoints/worker.py`'s poll loop.
    """
    return ContJobRunnerCli(service=_job_runner_service())


def build_job_runner_http() -> ContJobRunnerHttp:
    """Construct `api.worker`'s `rpc` surface adapter.

    Returned un-served: `entrypoints/worker.py` mounts this router on a
    FastAPI app and hands it to uvicorn, because the runtime host is not an
    adapter (internal_dependency_rules.md § Entrypoints, rule 2).

    Built here even though `api.web` never uses it and `api.clock` never
    uses it — the composition root instantiates every driving mechanism
    (§ Composition Root, item 3), which is the argument `build_jobs_cli`
    below makes at length.
    """
    return ContJobRunnerHttp(service=_job_runner_service())


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

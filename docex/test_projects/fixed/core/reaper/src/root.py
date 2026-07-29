"""Composition root for the `reaper` core service.

Wires the postgres repo + reaper service + CLI controller and hands the
driving adapter back. **The root constructs; it does not activate**
(internal_dependency_rules.md § Entrypoints) — running the reap pass and
exiting with its status is `entrypoints/prune.py`'s job, that being the
module the `reaper.prune` process type's `command` invokes.

Env is the doctrine parts-only surface — identical to `api`'s — so the
same code runs unchanged on both foundations.
"""

from __future__ import annotations

import os

from hex.reaper.adapters.driven.repo_pings_postgres import RepoPingsPostgres
from hex.reaper.adapters.driving.cont_reaper_cli import ContReaperCli
from hex.reaper.alogic.reaper_service import ReaperService
from hex.reaper.domain.retention_window import RetentionWindow


# Processed pings are kept this many days, then reaped. A constant here
# (a composition-root wiring decision), not a doctrine secret/part.
_RETENTION_DAYS = 30


def _dsn_from_env() -> str:
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


def build_reaper() -> ContReaperCli:
    """Construct the `reaper.prune` process type's graph, un-run."""
    repo = RepoPingsPostgres(dsn=_dsn_from_env())
    service = ReaperService(repo=repo, window=RetentionWindow(days=_RETENTION_DAYS))
    return ContReaperCli(service=service)

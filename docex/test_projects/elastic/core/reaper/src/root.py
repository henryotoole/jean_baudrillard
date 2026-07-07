"""Composition root for the `reaper` scheduler core service.

Wires the postgres repo + reaper service + CLI controller, runs one reap
pass, and exits. This is the job entrypoint the scheduler (Ofelia on
fixed, EventBridge RunTask on elastic) launches on each fire.

Env is the doctrine parts-only surface — identical to `worker`'s — so
the same code runs unchanged on both foundations.
"""

from __future__ import annotations

import logging
import os
import sys

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


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    repo = RepoPingsPostgres(dsn=_dsn_from_env())
    service = ReaperService(repo=repo, window=RetentionWindow(days=_RETENTION_DAYS))
    cli = ContReaperCli(service=service)
    return cli.run_once()


if __name__ == "__main__":
    sys.exit(main())

"""Composition root for the `worker` core service."""

from __future__ import annotations

import logging
import os
import sys

from hex.processor.adapters.driven.repo_pings_postgres import RepoPingsPostgres
from hex.processor.adapters.driving.cont_processor_cli import ContProcessorCli
from hex.processor.alogic.processor_service import ProcessorService


def _dsn_from_env() -> str:
    parts = {
        "host": os.environ["DATABASE_HOST"],
        "port": os.environ["DATABASE_PORT"],
        "dbname": os.environ["DATABASE_NAME"],
        "user": os.environ["DATABASE_USER"],
        "password": os.environ["DATABASE_PASSWORD"],
    }
    return (
        f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
        f"user={parts['user']} password={parts['password']}"
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    repo_pings = RepoPingsPostgres(dsn=_dsn_from_env())
    processor = ProcessorService(repo=repo_pings)
    cli = ContProcessorCli(service=processor)
    cli.run_forever()


if __name__ == "__main__":
    sys.exit(main())

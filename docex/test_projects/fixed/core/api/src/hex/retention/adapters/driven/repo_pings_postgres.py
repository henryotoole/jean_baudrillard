"""RepoPingsPostgres — psycopg2-backed driven adapter for pruning.

One statement: delete processed pings older than the cutoff. Parallel
implementation to `pings`' / `processor`'s repos per the doctrine rule
that hex modules never share code — three modules read the same table,
each through its own adapter and its own interpretation of it.
"""

from __future__ import annotations

from datetime import datetime

import psycopg2

from hex.retention.ports.driven.repo_pings import RepoPings


class RepoPingsPostgres(RepoPings):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> psycopg2.extensions.connection:
        return psycopg2.connect(self._dsn)

    def delete_processed_before(self, cutoff: datetime) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pings WHERE processed_at IS NOT NULL "
                "AND processed_at < %s",
                (cutoff,),
            )
            return cur.rowcount

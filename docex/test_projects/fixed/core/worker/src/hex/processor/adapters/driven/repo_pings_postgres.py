"""RepoPingsPostgres — psycopg2-backed driven adapter for ping persistence.

Subset of `web`'s repo (no save method). Parallel implementation per the
doctrine rule that hex modules don't share code across services.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import psycopg2
import psycopg2.extras

from hex.processor.domain.ping import Ping
from hex.processor.ports.driven.repo_pings import RepoPings


class RepoPingsPostgres(RepoPings):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        psycopg2.extras.register_uuid()

    def _connect(self) -> psycopg2.extensions.connection:
        return psycopg2.connect(self._dsn)

    def claim_unprocessed(self, limit: int) -> list[Ping]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, payload, created_at, processed_at FROM pings"
                " WHERE processed_at IS NULL ORDER BY created_at ASC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [
            Ping(id=row[0], payload=row[1], created_at=row[2], processed_at=row[3])
            for row in rows
        ]

    def mark_processed(self, id: UUID, at: datetime) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE pings SET processed_at = %s WHERE id = %s AND processed_at IS NULL",
                (at, id),
            )

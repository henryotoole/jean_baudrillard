"""QueueJobsPostgres — psycopg2-backed driven adapter for the job queue.

The queue's transport is the `jobs` table in `appdb`, created by this
codebase's `migrate.sh`. That is not incidental: only the codebase that
owns a schema may write to it, which is the whole reason the clock lives
in `api` rather than in a codebase of its own
(clock.md § The clock defers; it does not work).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg2
import psycopg2.extras

from hex.jobs.domain.job import Job
from hex.jobs.ports.driven.queue_jobs import QueueJobs


class QueueJobsPostgres(QueueJobs):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        psycopg2.extras.register_uuid()

    def _connect(self) -> psycopg2.extensions.connection:
        # New connection per call, matching the other repos in this codebase.
        return psycopg2.connect(self._dsn)

    def enqueue(self, name: str) -> UUID:
        job_id = uuid4()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, name, enqueued_at) VALUES (%s, %s, %s)",
                (job_id, name, datetime.now(timezone.utc)),
            )
        return job_id

    def claim(self, limit: int) -> list[Job]:
        # WHY the lock clause, in two halves — do NOT simplify it.
        #
        # `FOR UPDATE` buys EXCLUSIVITY: no job is ever claimed twice.
        # `api.worker` runs `replicas: 2` in prod, so this is a genuine
        # two-consumer race against one queue, not a theoretical one.
        #
        # `SKIP LOCKED` buys LIVENESS: without it the second worker would
        # BLOCK behind the first worker's batch instead of taking different
        # rows — correct, but serialized, which defeats running two.
        #
        # tests/test_jobs_concurrency.py asserts the FIRST property and not
        # the second: drop `SKIP LOCKED` and that test still passes while
        # throughput quietly halves. The comment is the only thing standing
        # between this clause and a plausible "cleanup".
        #
        # Both statements below MUST be in the same transaction on the same
        # connection. A `SELECT ... FOR UPDATE` whose transaction ends
        # before the `UPDATE` holds no lock at all and the entire guarantee
        # evaporates.
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, enqueued_at FROM jobs"
                    " WHERE started_at IS NULL"
                    " ORDER BY enqueued_at ASC"
                    " LIMIT %s"
                    " FOR UPDATE SKIP LOCKED",
                    (limit,),
                )
                rows = cur.fetchall()
                if not rows:
                    conn.rollback()
                    return []
                started_at = datetime.now(timezone.utc)
                cur.execute(
                    "UPDATE jobs SET started_at = %s WHERE id = ANY(%s)",
                    (started_at, [row[0] for row in rows]),
                )
            conn.commit()
        finally:
            conn.close()

        # Reconstituted from the row, `started_at` included — an adapter
        # rebuilding a stored entity is not a caller mutating one, so it
        # sets the field rather than replaying `Job.start()`. Replaying it
        # would compare the WORKER's clock against the CLOCK container's,
        # and a few milliseconds of skew between two hosts would raise on a
        # perfectly valid job.
        return [
            Job(id=row[0], name=row[1], enqueued_at=row[2], started_at=started_at)
            for row in rows
        ]

    def complete(self, id: UUID, at: datetime) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET finished_at = %s, error = NULL"
                " WHERE id = %s AND finished_at IS NULL",
                (at, id),
            )

    def fail(self, id: UUID, at: datetime, error: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET finished_at = %s, error = %s"
                " WHERE id = %s AND finished_at IS NULL",
                (at, error, id),
            )

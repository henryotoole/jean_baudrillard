"""Smoke tests for the `jobs` module against the live test-env postgres.

Exercises the whole deferral path in one process — enqueue through
`JobService` (what the clock does), drain through `JobRunnerService` (what
`api.worker` does) — and asserts on the row itself, because the row IS the
transport.

These tolerate a concurrently-running `api.clock`: a clock is not
suppressed in `test` (clock.md § What a clock core service is), so the
minutely `heartbeat` is genuinely in this queue while the suite runs.
Every assertion is therefore scoped to job ids this test enqueued.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from uuid import UUID

import psycopg2


sys.path.insert(0, "/service/dist")

from hex.jobs.adapters.driven.queue_jobs_postgres import QueueJobsPostgres  # noqa: E402
from hex.jobs.alogic.job_runner_service import JobRunnerService  # noqa: E402
from hex.jobs.alogic.job_service import JobService  # noqa: E402
from root import _dsn_from_env  # noqa: E402


_DRAIN_PASSES = 12


class _StubRetention:
    """Stub ContRetention — the driving port `jobs`' runner imports."""

    def __init__(self, raises: bool = False) -> None:
        self.calls = 0
        self._raises = raises

    def prune(self) -> int:
        self.calls += 1
        if self._raises:
            raise RuntimeError("retention exploded")
        return 7


def _row(job_id: UUID) -> tuple:
    with psycopg2.connect(_dsn_from_env()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, started_at, finished_at, error FROM jobs WHERE id = %s",
            (str(job_id),),
        )
        row = cur.fetchone()
    assert row is not None, f"job {job_id} was never enqueued"
    return row


def _drain_until_finished(runner: JobRunnerService, ids: list[UUID]) -> None:
    """Run passes until every id has a finished_at, or give up.

    Bounded rather than unbounded: a hang here should fail the suite, not
    stall it.
    """
    for _ in range(_DRAIN_PASSES):
        if all(_row(job_id)[2] is not None for job_id in ids):
            return
        runner.run_once()
    raise AssertionError(f"jobs {ids} did not drain in {_DRAIN_PASSES} passes")


def test_enqueued_job_is_claimed_performed_and_completed() -> None:
    queue = QueueJobsPostgres(dsn=_dsn_from_env())
    retention = _StubRetention()
    job_id = JobService(queue=queue).prune_pings()

    # Not started until something claims it — the clock only defers.
    assert _row(job_id)[1] is None

    runner = JobRunnerService(queue=queue, retention=retention)
    _drain_until_finished(runner, [job_id])

    name, started_at, finished_at, error = _row(job_id)
    assert name == "prune_pings"
    assert started_at is not None
    assert finished_at is not None
    assert finished_at >= started_at
    assert error is None
    assert retention.calls >= 1


def test_a_failing_handler_records_the_error_and_the_next_job_still_runs() -> None:
    queue = QueueJobsPostgres(dsn=_dsn_from_env())
    service = JobService(queue=queue)

    # Order matters: claim is oldest-first, so the poisoned job is claimed
    # before the healthy one and must not stall it.
    poisoned = service.prune_pings()
    healthy = service.heartbeat()

    runner = JobRunnerService(queue=queue, retention=_StubRetention(raises=True))
    _drain_until_finished(runner, [poisoned, healthy])

    _, _, poisoned_finished, poisoned_error = _row(poisoned)
    assert poisoned_finished is not None
    assert poisoned_error is not None
    assert "retention exploded" in poisoned_error

    _, _, healthy_finished, healthy_error = _row(healthy)
    assert healthy_finished is not None
    assert healthy_error is None


def test_run_once_returns_the_number_performed() -> None:
    queue = QueueJobsPostgres(dsn=_dsn_from_env())
    service = JobService(queue=queue)
    ids = [service.heartbeat() for _ in range(3)]

    runner = JobRunnerService(queue=queue, retention=_StubRetention())
    total = 0
    for _ in range(_DRAIN_PASSES):
        total += runner.run_once()
        if all(_row(job_id)[2] is not None for job_id in ids):
            break
    # `>=` rather than `==`: a live api.clock may have deferred a heartbeat
    # of its own into the same batch.
    assert total >= len(ids)
    for job_id in ids:
        assert _row(job_id)[3] is None


def test_claim_returns_started_jobs() -> None:
    queue = QueueJobsPostgres(dsn=_dsn_from_env())
    job_id = JobService(queue=queue).heartbeat()

    claimed = {job.id: job for job in queue.claim(limit=32)}
    assert job_id in claimed, "an enqueued job must be claimable"
    assert claimed[job_id].started_at is not None

    # Leave the queue as we found it. Everything claimed here is now
    # started and would otherwise never be drained by the real worker,
    # including any heartbeat a live api.clock deferred alongside ours.
    now = datetime.now(timezone.utc)
    for claimed_id in claimed:
        queue.complete(id=claimed_id, at=now)

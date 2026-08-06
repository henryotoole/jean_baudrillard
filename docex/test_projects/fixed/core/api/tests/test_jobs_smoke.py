"""DB-tier smoke tests for the `jobs` module against the live test-env postgres.

Exercises the deferral path against the real `jobs` table — enqueue through
`JobService` (what the clock does), drain through `JobRunnerService` (what
`api.worker` does) — and asserts on the row itself, because the row IS the
transport.

**Two live actors share this queue while these tests run, not one.**
`docex test` brings the WHOLE stack up before running `test.sh`
(`cicd.md § Build Test Step`), so both are genuinely present:

- a live `api.clock`, which ADDS rows (a minutely `heartbeat`); and
- a live `api.worker`, which REMOVES them — it claims and performs rows
  from this same table on a ~1 s poll with `batch_size=8`.

The worker is the one that matters, and an earlier version of this
docstring mentioned only the clock. That half-truth is what let four
racing assertions live here: a clock only adds rows, so marker-scoping
survives it, while nothing survives another process taking your row.

**So this file asserts OUTCOMES in shared state, never AGENCY.** "The row
reached a finished state" is an outcome and holds no matter who performed
it. "We performed it", "we claimed it", "it was still unstarted when we
looked" are agency, and every one of them is false the moment the worker
wins. Assertions of that shape live in `test_jobs_alogic.py`, where the
queue is a stub and there is no third party by construction.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from uuid import UUID

import psycopg2


sys.path.insert(0, "/service/dist")

from hex.jobs.adapters.driven.queue_jobs_postgres import QueueJobsPostgres  # noqa: E402
from hex.jobs.alogic.job_runner_service import JobRunnerService  # noqa: E402
from hex.jobs.alogic.job_service import JobService  # noqa: E402
from root import _dsn_from_env  # noqa: E402


_DRAIN_PASSES = 12
# WHY a pause between drain passes: we are not the only drainer. If the
# live api.worker claimed the row first, our `run_once()` can no longer
# see it and the only thing that will finish it is the worker's own poll,
# which ticks at ~1 s. Twelve back-to-back passes complete in milliseconds
# and would fail this file against a queue that is working perfectly.
_DRAIN_PAUSE_SECONDS = 0.5

# Bounded wait for a row to be claimed by SOMEONE. Long enough to cover
# several worker polls; short enough that a dead queue fails the suite
# rather than stalling it.
_CLAIM_POLL_PASSES = 60
_CLAIM_POLL_SECONDS = 0.5


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

    Returning early because the rows are already finished is the EXPECTED
    outcome when the live worker wins the race, not a failure — this loop
    is a way to make progress, not a claim that we are the one making it.
    """
    for _ in range(_DRAIN_PASSES):
        if all(_row(job_id)[2] is not None for job_id in ids):
            return
        runner.run_once()
        time.sleep(_DRAIN_PAUSE_SECONDS)
    raise AssertionError(f"jobs {ids} did not drain in {_DRAIN_PASSES} passes")


def test_an_enqueued_job_reaches_a_finished_row() -> None:
    queue = QueueJobsPostgres(dsn=_dsn_from_env())
    job_id = JobService(queue=queue).prune_pings()

    runner = JobRunnerService(queue=queue, retention=_StubRetention())
    _drain_until_finished(runner, [job_id])

    # The whole assertion is on the ROW. Whoever performed the job — this
    # runner or the live api.worker — the deferral contract held: a name
    # was deferred, something claimed it, and it reached a terminal state
    # without error.
    name, started_at, finished_at, error = _row(job_id)
    assert name == "prune_pings"
    assert started_at is not None
    assert finished_at is not None
    assert finished_at >= started_at
    assert error is None

    # DELETED, deliberately — do not restore either of these:
    #
    #   assert _row(job_id)[1] is None   (before draining)
    #   assert retention.calls >= 1      (after draining)
    #
    # The first asserted that nothing had claimed the row yet; the live
    # worker polls the same table and can stamp `started_at` microseconds
    # after `enqueue` returns. The second asserted AGENCY — that *we*
    # performed it — and the worker has a real, working `prune_pings`
    # handler, so a row it wins finishes clean and our stub is never
    # called. Both properties are real and both are now asserted where
    # they hold unconditionally:
    # `test_jobs_alogic.py::test_the_clock_defers_and_does_not_work` and
    # `test_jobs_alogic.py::test_prune_pings_dispatches_to_retention`.


def test_claim_starts_the_rows_it_returns() -> None:
    queue = QueueJobsPostgres(dsn=_dsn_from_env())
    job_id = JobService(queue=queue).heartbeat()

    # The adapter's contract, and the part of it that is ours to assert:
    # whatever subset we win comes back ALREADY STARTED. True of the empty
    # set too, which is the point — the live worker may have taken every
    # claimable row a millisecond before this call.
    claimed = {job.id: job for job in queue.claim(limit=32)}
    for job in claimed.values():
        assert job.started_at is not None, f"claim() returned job {job.id} without started_at"

    # Separately: our row must be claimed by SOMEONE. That is an outcome in
    # shared state and holds whether we won it or the worker did. Bounded,
    # so a queue that never advances fails rather than hangs.
    for _ in range(_CLAIM_POLL_PASSES):
        if _row(job_id)[1] is not None:
            break
        time.sleep(_CLAIM_POLL_SECONDS)
    assert _row(job_id)[1] is not None, (
        f"job {job_id} was never claimed by anything in "
        f"{_CLAIM_POLL_PASSES * _CLAIM_POLL_SECONDS:.0f}s"
    )

    # Leave the queue as we found it. Everything claimed HERE is started
    # and would otherwise never be drained by the real worker, including
    # any heartbeat a live api.clock deferred alongside ours. Rows the
    # worker won are its own to finish and are not in `claimed`.
    now = datetime.now(timezone.utc)
    for claimed_id in claimed:
        queue.complete(id=claimed_id, at=now)

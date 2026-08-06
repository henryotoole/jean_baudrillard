"""Alogic-tier tests for the `jobs` module. No database, no `root`.

**The tier.** These drive `JobService` and `JobRunnerService` against a
stubbed `QueueJobs` driven port, which is what
`hex_overview.md § Tests` calls an alogic test: application logic
exercised with its driven collaborators replaced by stubs. That is why
nothing here connects to postgres and why `_dsn_from_env` is not imported.

**The rule this file exists to obey — a test running in the `test` env has
no sole agency.** `docex test` brings the *whole stack* up before running
`test.sh` (`cicd.md § Build Test Step`), so while this suite runs there is
a live `api.clock` deferring jobs into the `jobs` table and a live
`api.worker` claiming and performing them. Against that database a test
may assert on *outcomes* observable in shared state, and on *its own*
components' behaviour — never on being the only actor. Every assertion
whose truth requires "we were the one who did it" belongs **here**, where
the collaborator is a stub and there is no third party by construction.
Four such assertions were moved out of `test_jobs_smoke.py` into this
file for exactly that reason; each test below names the one it replaces.

**The filename deliberately breaks this tree's `…_smoke.py` habit.** The
other stub-based files here are `test_clock_smoke.py` and
`test_processor_smoke.py`. This one names its *tier* instead, because this
tree is reference material that downstream projects copy, and the tier is
the lesson: the doctrine's vocabulary outranks a local naming convention
in a file whose job is to teach. That is a choice, not an oversight.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4


sys.path.insert(0, "/service/dist")

from hex.jobs.alogic.job_runner_service import JobRunnerService  # noqa: E402
from hex.jobs.alogic.job_service import JobService  # noqa: E402
from hex.jobs.domain.job import Job  # noqa: E402


class _StubRetention:
    """Stub ContRetention — the driving port `jobs`' runner imports.

    Same shape as `test_jobs_smoke.py`'s, kept in both files rather than
    shared: these tests are reference material and a reader should be able
    to understand one file without opening another.
    """

    def __init__(self, raises: bool = False) -> None:
        self.calls = 0
        self._raises = raises

    def prune(self) -> int:
        self.calls += 1
        if self._raises:
            raise RuntimeError("retention exploded")
        return 7


class _StubQueue:
    """Stub QueueJobs. Records calls; stores nothing.

    `claim` hands back whatever the test seeded, oldest-first, and never
    returns the same job twice — the one behaviour of the real adapter
    that the logic under test depends on.
    """

    def __init__(self, claimable: list[Job] | None = None) -> None:
        self.calls: list[tuple] = []
        self._claimable: list[Job] = list(claimable or [])

    def enqueue(self, name: str) -> UUID:
        self.calls.append(("enqueue", name))
        return uuid4()

    def claim(self, limit: int) -> list[Job]:
        self.calls.append(("claim", limit))
        batch = self._claimable[:limit]
        self._claimable = self._claimable[limit:]
        return batch

    def complete(self, id: UUID, at: datetime) -> None:
        self.calls.append(("complete", id))

    def fail(self, id: UUID, at: datetime, error: str) -> None:
        self.calls.append(("fail", id, error))


def _claimed(name: str) -> Job:
    """A Job in the state `claim()` hands back: started, not yet finished.

    `started_at` is mandatory here. `JobRunnerService` calls
    `job.finish(...)` on every job it handles, and the domain refuses to
    finish a job that never started (`job.py § finish`), so a stub queue
    returning unstarted jobs would fail every test in this file for a
    reason that has nothing to do with what it is testing.
    """
    now = datetime.now(timezone.utc)
    return Job(
        id=uuid4(),
        name=name,
        enqueued_at=now - timedelta(seconds=1),
        started_at=now,
    )


def _calls(queue: _StubQueue, kind: str) -> list[tuple]:
    return [call for call in queue.calls if call[0] == kind]


def test_run_once_returns_the_number_performed() -> None:
    # Replaces the DB-tier test of the same name, whose `total >= len(ids)`
    # could not be tightened: the live api.worker drains the same table, so
    # the count was neither an upper nor a lower bound on anything. With a
    # stub queue there is no third party, so this asserts `==`.
    queue = _StubQueue([_claimed("heartbeat") for _ in range(3)])
    runner = JobRunnerService(queue=queue, retention=_StubRetention())

    assert runner.run_once() == 3
    assert len(_calls(queue, "complete")) == 3
    assert not _calls(queue, "fail")


def test_prune_pings_dispatches_to_retention() -> None:
    # Replaces `retention.calls >= 1` in the DB-tier
    # `test_enqueued_job_is_claimed_performed_and_completed`. That assertion
    # asserted AGENCY — that *we* performed the job — and the live worker,
    # which has a real working `prune_pings` handler, wins the row often
    # enough that the stub is simply never called.
    retention = _StubRetention()
    runner = JobRunnerService(queue=_StubQueue([_claimed("prune_pings")]), retention=retention)
    assert runner.run_once() == 1
    assert retention.calls == 1

    # `heartbeat` is the runner's own no-op and must not reach retention.
    # The two dispatch entries are what keeps the perform-side table honest.
    unused = _StubRetention()
    runner = JobRunnerService(queue=_StubQueue([_claimed("heartbeat")]), retention=unused)
    assert runner.run_once() == 1
    assert unused.calls == 0


def test_a_failing_handler_records_the_error_and_the_next_job_still_runs() -> None:
    # Replaces the DB-tier test of the same name. There, `poisoned_error is
    # not None` required us to win the poisoned row: the live worker has a
    # WORKING `prune_pings` handler, so a row it claims finishes clean and
    # the assertion fails on a perfectly healthy queue.
    #
    # Order matters and is guaranteed here: claim is oldest-first, so the
    # poisoned job is handled before the healthy one and must not stall it.
    poisoned = _claimed("prune_pings")
    healthy = _claimed("heartbeat")
    queue = _StubQueue([poisoned, healthy])
    runner = JobRunnerService(queue=queue, retention=_StubRetention(raises=True))

    assert runner.run_once() == 1, "the healthy job behind a poisoned one must still be performed"

    failures = _calls(queue, "fail")
    assert [call[1] for call in failures] == [poisoned.id]
    assert "retention exploded" in failures[0][2]

    assert [call[1] for call in _calls(queue, "complete")] == [healthy.id]


def test_a_name_with_no_handler_is_failed_not_raised() -> None:
    # A name with no handler is a data problem in one row. Killing the drain
    # over it would stall every job behind it, so the runner records the
    # failure and continues. The DB tier cannot assert this: the row would
    # have to be won by us, and a job named `no_such_job` is exactly the
    # kind the live worker also fails, indistinguishably.
    orphan = _claimed("no_such_job")
    queue = _StubQueue([orphan])
    runner = JobRunnerService(queue=queue, retention=_StubRetention())

    # Returns rather than raises, and counts nothing as performed.
    assert runner.run_once() == 0, "an unhandled name must not count as performed"

    failures = _calls(queue, "fail")
    assert [call[1] for call in failures] == [orphan.id]
    assert "no handler" in failures[0][2]
    assert not _calls(queue, "complete")


def test_the_clock_defers_and_does_not_work() -> None:
    # The race-free replacement for the deleted DB-tier assertion
    # `_row(job_id)[1] is None` ("not started until something claims it").
    # That assertion was only ever true inside a timing window — the live
    # worker polls the same table and can stamp `started_at` microseconds
    # after the enqueue returns. Stated against the port instead, the
    # property holds STRUCTURALLY: the defer side makes exactly one
    # `enqueue` call and touches nothing else, which is the whole of
    # `clock.md § The clock defers; it does not work`.
    queue = _StubQueue()

    JobService(queue=queue).prune_pings()

    assert queue.calls == [("enqueue", "prune_pings")]

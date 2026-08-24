"""The multi-consumer race against one queue, driven in `test`.

**Why this file exists.** `api.worker` declares `replicas: 2`, and the
replica count is honoured in `prod` alone — clamped to 1 in dev, test and
stage. Left alone, the first time two workers ever claim from one queue is
the production release, and a double-claim discovered there costs a whole
walk. So the race is driven here, in the environment whose suite already
runs against real postgres, using two queue instances instead of two
containers.

**There is a THIRD claimer and it is not interference.** `docex test`
brings the whole stack up before running `test.sh`
(`cicd.md § Build Test Step`), so a live `api.worker` container is polling
this same table throughout. It is observable: it has no handler for the
`conc_<hex>` marker name, so its `JobRunnerService` calls `queue.fail(...)`
and stamps `error = "no handler for job name 'conc_…'"` on every marker row
it wins. Nothing else in this run writes that column, so the error stamp
identifies the worker's claims unambiguously and they can be accounted for
rather than wished away.

That makes this test **stronger than the two-thread form it replaces**,
which asserted `set(all_claimed) == enqueued` and was simply wrong by
construction: a row the worker took was a row we could not return, so the
completeness assertion failed on a healthy queue. Exclusivity is now
asserted across a genuinely separate container on a separate connection
pool — which is what `FOR UPDATE SKIP LOCKED` actually defends against in
production, and closer to it than two threads in one process ever were.

The two in-test consumers spin, while the worker polls at ~1 s with
`batch_size=8`, so in practice the consumers win all 40 and
`worker_claimed` is usually empty. That is fine: no assertion below is
conditioned on it being non-empty.

**What is asserted, and what is not.** The assertion is EXCLUSIVITY: every
job is claimed exactly once, by exactly one of three claimers. That is the
property whose failure breaks the deferral contract, because a job claimed
twice is a job performed twice.

`SKIP LOCKED`'s own contribution is LIVENESS, and this test does not
assert it: without `SKIP LOCKED`, plain `FOR UPDATE` would serialize the
two claimers rather than duplicate rows, so exclusivity still holds and
this test still passes while throughput quietly halves. Do not "simplify"
the lock clause in `QueueJobsPostgres.claim()` on the grounds that the
suite stays green.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg2
import psycopg2.extras


sys.path.insert(0, "/service/dist")

from hex.jobs.adapters.driven.queue_jobs_postgres import QueueJobsPostgres  # noqa: E402
from root import _dsn_from_env  # noqa: E402


# Reading `jobs.id` back as a `uuid.UUID` rather than a `str` is what makes
# the set arithmetic below work against the ids `enqueue()` returned.
# `QueueJobsPostgres.__init__` registers this globally too, but relying on
# that would make this file's correctness depend on construction order.
psycopg2.extras.register_uuid()


_JOB_COUNT = 40
_BATCH = 4

# Bounded settle wait, ~60 s total.
_SETTLE_PASSES = 120
_SETTLE_PAUSE_SECONDS = 0.5


def _marker_rows(marker: str) -> dict[UUID, str | None]:
    """Every row carrying this run's marker name, id → error."""
    with psycopg2.connect(_dsn_from_env()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, error FROM jobs WHERE name = %s", (marker,))
        return {row[0]: row[1] for row in cur.fetchall()}


def test_two_consumers_claim_every_job_exactly_once() -> None:
    # A marker name so a live api.clock's heartbeats, which share this
    # queue, can be told apart from this test's jobs — and so the live
    # api.worker's claims of OUR jobs are identifiable by the error it
    # stamps on them.
    marker = f"conc_{uuid4().hex[:8]}"

    producer = QueueJobsPostgres(dsn=_dsn_from_env())
    enqueued = {producer.enqueue(marker) for _ in range(_JOB_COUNT)}
    assert len(enqueued) == _JOB_COUNT

    # Two INSTANCES, and therefore two independent connections per claim.
    # A single shared connection would prove nothing: two claims on one
    # connection are two statements in one session and cannot race.
    consumers = [
        QueueJobsPostgres(dsn=_dsn_from_env()),
        QueueJobsPostgres(dsn=_dsn_from_env()),
    ]
    claimed: list[list[UUID]] = [[], []]
    strays: list[UUID] = []
    lock = threading.Lock()

    def drain(idx: int) -> None:
        while True:
            batch = consumers[idx].claim(limit=_BATCH)
            if not batch:
                return
            with lock:
                for job in batch:
                    if job.name == marker:
                        claimed[idx].append(job.id)
                    else:
                        strays.append(job.id)

    threads = [
        threading.Thread(target=drain, args=(idx,), name=f"consumer-{idx}")
        for idx in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    for thread in threads:
        assert not thread.is_alive(), "a consumer never drained"

    ours = claimed[0] + claimed[1]
    ours_set = set(ours)

    # -- Settle poll ------------------------------------------------------
    # WHY this is needed: between our drain returning and this read, a row
    # the live worker has CLAIMED but not yet failed is indistinguishable
    # from one of ours — `started_at` set, `finished_at` and `error` both
    # NULL. Wait for every such row to record an outcome. Bounded, because
    # a worker that claims a row and never records anything is a real
    # defect and must fail this test rather than be waited on forever.
    rows: dict[UUID, str | None] = {}
    unaccounted: set[UUID] = set()
    for attempt in range(_SETTLE_PASSES):
        if attempt:
            time.sleep(_SETTLE_PAUSE_SECONDS)
        rows = _marker_rows(marker)
        unaccounted = {
            job_id
            for job_id, error in rows.items()
            if job_id not in ours_set and error is None
        }
        if not unaccounted:
            break
    assert not unaccounted, (
        f"marker rows claimed by neither consumer recorded no outcome in "
        f"{_SETTLE_PASSES * _SETTLE_PAUSE_SECONDS:.0f}s: {sorted(map(str, unaccounted))}"
    )

    # -- Accounting -------------------------------------------------------
    # The live api.worker has no handler for `conc_<hex>`, so it calls
    # `queue.fail(...)` and stamps the error column. Nothing else in this
    # run writes that column: the in-test consumers only `claim`, and only
    # `complete` at cleanup below. THIS READ MUST THEREFORE HAPPEN BEFORE
    # CLEANUP — `complete` sets `error = NULL` and would erase the evidence.
    worker_claimed = {job_id for job_id, error in rows.items() if error is not None}

    assert len(ours) == len(set(ours)), (
        "a job was claimed more than once — FOR UPDATE is not holding"
    )
    assert set(claimed[0]).isdisjoint(claimed[1]), (
        "both in-test consumers claimed the same job — FOR UPDATE is not holding"
    )
    assert ours_set.isdisjoint(worker_claimed), (
        "a job was claimed by both this test and the live api.worker — "
        "exclusivity does not hold ACROSS PROCESSES, which is the case that "
        "matters in prod"
    )
    assert ours_set | worker_claimed == enqueued, (
        "the union of all three claimers is not the whole queue — a job was "
        "enqueued and then claimed by nobody"
    )

    # Leave nothing started-but-unfinished behind, including any heartbeat
    # a live api.clock deferred into the same queue mid-run. Rows the
    # worker claimed are already finished, and `complete`'s
    # `WHERE finished_at IS NULL` makes this a no-op on them — no filter
    # needed here, and adding one would be redundant.
    now = datetime.now(timezone.utc)
    for job_id in ours + strays:
        producer.complete(id=job_id, at=now)

"""The two-consumer race against one queue, driven in `test`.

**Why this file exists.** `api.worker` declares `replicas: 2`, and the
replica count is honoured in `prod` alone — clamped to 1 in dev, test and
stage. Left alone, the first time two workers ever claim from one queue is
the production release, and a double-claim discovered there costs a whole
walk. So the race is driven here, in the environment whose suite already
runs against real postgres, using two queue instances instead of two
containers.

**What is asserted, and what is not.** The assertion is EXCLUSIVITY: every
job is claimed exactly once. That is the property whose failure breaks the
deferral contract, because a job claimed twice is a job performed twice.

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
from datetime import datetime, timezone
from uuid import UUID, uuid4


sys.path.insert(0, "/service/dist")

from hex.jobs.adapters.driven.queue_jobs_postgres import QueueJobsPostgres  # noqa: E402
from root import _dsn_from_env  # noqa: E402


_JOB_COUNT = 40
_BATCH = 4


def test_two_consumers_claim_every_job_exactly_once() -> None:
    # A marker name so a live api.clock's heartbeats, which share this
    # queue, can be told apart from this test's jobs.
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

    all_claimed = claimed[0] + claimed[1]
    assert len(all_claimed) == len(set(all_claimed)), (
        "a job was claimed more than once — FOR UPDATE is not holding"
    )
    assert set(all_claimed) == enqueued, "the union of both consumers is not the whole queue"

    # Leave nothing started-but-unfinished behind, including any heartbeat
    # a live api.clock deferred into the same queue mid-run.
    now = datetime.now(timezone.utc)
    for job_id in all_claimed + strays:
        producer.complete(id=job_id, at=now)

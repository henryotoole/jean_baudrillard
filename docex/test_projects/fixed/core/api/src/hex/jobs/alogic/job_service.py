"""JobService — application logic implementing ContJobs (the DEFER side).

Every method is one line, and that is the whole contract of this side: a
clock's only job is to call a driving port that enqueues, and it performs
no work itself (clock.md § The clock defers; it does not work). If a
method here ever grows a body, the clock has started doing the worker's
job — a singleton with no replicas and no queue-level retry doing work
that has both.
"""

from __future__ import annotations

from uuid import UUID

from hex.jobs.ports.driven.queue_jobs import QueueJobs


class JobService:
    def __init__(self, queue: QueueJobs) -> None:
        self._queue = queue

    def prune_pings(self) -> UUID:
        return self._queue.enqueue("prune_pings")

    def heartbeat(self) -> UUID:
        return self._queue.enqueue("heartbeat")

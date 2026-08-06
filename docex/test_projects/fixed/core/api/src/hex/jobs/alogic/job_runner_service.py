"""JobRunnerService — application logic implementing ContJobRunner
(the PERFORM side).

Claims a batch off the queue and runs each job's handler, driven once per
iteration by `api.worker`'s poll loop.

**There are two dispatch tables in this module and they are NOT
duplication.** `ContJobsCron`'s maps a job name to how the job is
*deferred*; this one maps a job name to how it is *performed*. Collapsing
them is the obvious cleanup and it would couple the clock to the worker's
implementation — the clock would have to know how a job is performed in
order to know how to defer it, at which point nothing stops it performing
the job itself, which is exactly what
`clock.md § The clock defers; it does not work` forbids.

`ContRetention` is a **driving port of another hex module**, which is the
one cross-module import the doctrine allows
(internal_dependency_rules.md § Cross-Module Imports). The composition
root injects `RetentionService` behind it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from hex.jobs.ports.driven.queue_jobs import QueueJobs
from hex.retention.ports.driving.cont_retention import ContRetention


logger = logging.getLogger(__name__)


class JobRunnerService:
    def __init__(
        self,
        queue: QueueJobs,
        retention: ContRetention,
        batch_size: int = 8,
    ) -> None:
        self._queue = queue
        self._retention = retention
        self._batch_size = batch_size
        # The perform-side table. Its keys are job names, matching the
        # defer-side keys in ContJobsCron — the two tables agree on the
        # vocabulary and on nothing else.
        self._handlers: dict[str, Callable[[], int]] = {
            "prune_pings": self._retention.prune,
            "heartbeat": self._heartbeat,
        }

    def _heartbeat(self) -> int:
        """A deliberate no-op. Its purpose is to be observed, not to work."""
        logger.info("jobs: heartbeat performed")
        return 0

    def run_once(self) -> int:
        jobs = self._queue.claim(limit=self._batch_size)
        performed = 0
        for job in jobs:
            now = datetime.now(timezone.utc)
            handler = self._handlers.get(job.name)
            if handler is None:
                # Not a crash. A name with no handler is a data problem in
                # one row, and killing the drain over it would stall every
                # other job behind it.
                job.finish(at=now, error=f"no handler for job name {job.name!r}")
                self._queue.fail(id=job.id, at=now, error=job.error or "")
                logger.error("jobs: no handler for %r (job %s)", job.name, job.id)
                continue
            try:
                result = handler()
            except Exception as exc:
                # WHY: caught per job, then CONTINUE. One poisoned job must
                # not stall the queue behind it — every remaining job in the
                # batch still runs, and the failure is recorded on the row
                # rather than lost to a traceback.
                job.finish(at=now, error=str(exc))
                self._queue.fail(id=job.id, at=now, error=job.error or "")
                logger.exception("jobs: %r failed (job %s)", job.name, job.id)
                continue
            # `finish` before `complete`: the domain refuses to finish a job
            # that never started, so this asserts in-process that `claim`
            # really did hand back a claimed row.
            job.finish(at=now)
            self._queue.complete(id=job.id, at=now)
            logger.info("jobs: %r performed (job %s, result %s)", job.name, job.id, result)
            performed += 1
        return performed

"""ContJobsCli — CLI-mechanism driving adapter for ContJobs.

Fire one job by name from argv. Because it receives a *name* rather than
being invoked at a named entry point, it needs the same map as
`ContJobsCron` — that is the price of a name-shaped mechanism, and it is
why the HTTP adapter (whose mechanism is route-shaped) needs no map at
all.

**Nothing invokes this adapter.** No entrypoint uses it and no core
service's `command` reaches it, yet the composition root constructs it
anyway: the root instantiates every driving mechanism, including ones the
running core service will never use
(internal_dependency_rules.md § Composition Root, item 3). Construction
is free — it captures a port reference and performs no I/O. It is also
the "fire a scheduled job by hand, inside the container" path that the
shared driving port buys.
"""

from __future__ import annotations

import logging
from typing import Callable
from uuid import UUID

from hex.jobs.ports.driving.cont_jobs import ContJobs


logger = logging.getLogger(__name__)


class ContJobsCli:
    def __init__(self, service: ContJobs) -> None:
        self._service = service
        self._dispatch: dict[str, Callable[[], UUID]] = {
            "heartbeat": service.heartbeat,
            "prune_pings": service.prune_pings,
        }

    def fire(self, name: str) -> int:
        """Defer the named job. Returns a process exit code.

        Args:
            name: the job name, as taken from argv.

        Returns:
            0 once the job is enqueued, 2 if `name` is not a known job.
        """
        handler = self._dispatch.get(name)
        if handler is None:
            logger.error(
                "jobs: unknown job %r (known: %s)",
                name, ", ".join(sorted(self._dispatch)),
            )
            return 2
        job_id = handler()
        logger.info("jobs: %r deferred as job %s", name, job_id)
        return 0

"""ContJobs — driving port for deferring a job.

**One method per job**, not one `fire(name)` method. That is what lets the
HTTP adapter expose one route per operation (which is the only shape an
OpenAPI contract can meaningfully describe) and what makes the cron
adapter's table a real *dispatch* rather than a string-keyed side door
into the application.

Shared by every driving mechanism — `ContJobsCron`, `ContJobsHttp`,
`ContJobsCli` — which is the side effect clock.md § Architecture calls out:
every scheduled job is also reachable over HTTP and on the command line, so
firing a scheduled job by hand in `dev` is an ordinary call.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class ContJobs(Protocol):
    def prune_pings(self) -> UUID:
        """Defer a prune of expired processed pings. Returns the job id."""
        ...

    def heartbeat(self) -> UUID:
        """Defer a no-op liveness job. Returns the job id."""
        ...

"""QueueJobs — driven port for the deferred-job queue.

The canonical `Queue` pattern (hex_overview.md § Driven Port / Adapter
Patterns): producer-side access to an asynchronous task queue, plus the
consumer-side claim/complete/fail this project's poll-based worker needs.

Both sides of the queue sit behind ONE port because both are the same
resource. The producer half is what the clock reaches through `ContJobs`;
the consumer half is what `api.worker` reaches through `ContJobRunner`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from hex.jobs.domain.job import Job


class QueueJobs(Protocol):
    def enqueue(self, name: str) -> UUID: ...

    def claim(self, limit: int) -> list[Job]:
        """Atomically claim up to ``limit`` unstarted jobs, oldest first.

        Claimed jobs are stamped `started_at` before this returns, so no
        other consumer can claim them.
        """
        ...

    def complete(self, id: UUID, at: datetime) -> None: ...
    def fail(self, id: UUID, at: datetime, error: str) -> None: ...

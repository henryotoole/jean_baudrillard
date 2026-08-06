"""Job — the deferred unit of work in the `jobs` module.

A job is a *name* plus its lifecycle timestamps. It carries no payload
and no handler: the clock defers a name, the worker looks that name up in
its own perform-side table. Keeping the handler out of the entity is what
lets the two sides stay independent
(clock.md § The clock defers; it does not work).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Job:
    id: UUID
    name: str
    enqueued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("job name must be non-empty")

    def start(self, at: datetime) -> None:
        """Claim transition. Illegal on a job that is already started."""
        if self.started_at is not None:
            raise ValueError(f"job {self.id} already started at {self.started_at}")
        if at < self.enqueued_at:
            raise ValueError("started_at must be at or after enqueued_at")
        self.started_at = at

    def finish(self, at: datetime, error: str | None = None) -> None:
        """Terminal transition. Illegal on a job that was never started.

        A job that finishes without ever having started would mean the
        queue handed out work it never claimed — the invariant whose
        violation is exactly what `FOR UPDATE SKIP LOCKED` exists to
        prevent, so the domain refuses to represent it.
        """
        if self.started_at is None:
            raise ValueError(f"job {self.id} cannot finish before it starts")
        if self.finished_at is not None:
            raise ValueError(f"job {self.id} already finished at {self.finished_at}")
        if at < self.started_at:
            raise ValueError("finished_at must be at or after started_at")
        self.finished_at = at
        self.error = error

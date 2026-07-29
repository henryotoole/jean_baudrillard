"""Ping — the single domain entity in the `pings` module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass
class Ping:
    id: UUID
    payload: str
    created_at: datetime
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("payload must be non-empty")

    @classmethod
    def create(cls, payload: str) -> "Ping":
        return cls(
            id=uuid4(),
            payload=payload,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
        )

    def mark_processed(self, at: datetime) -> None:
        if self.processed_at is not None:
            raise ValueError(f"ping {self.id} already processed at {self.processed_at}")
        if at < self.created_at:
            raise ValueError("processed_at must be at or after created_at")
        self.processed_at = at

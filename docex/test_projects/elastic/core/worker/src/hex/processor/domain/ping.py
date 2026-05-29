"""Ping — domain entity in `worker`'s `processor` module.

Deliberately a separate file from `web`'s `Ping`: per
doctrine/hexagonal_architecture/internal_dependency_rules.md, "code inside
a hexagonal module may never import files and classes in another
hexagonal module" — and that applies across services too. If web and
worker's `Ping` drift, that surfaces a contract drift the test exposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Ping:
    id: UUID
    payload: str
    created_at: datetime
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("payload must be non-empty")

    def mark_processed(self, at: datetime) -> None:
        if self.processed_at is not None:
            raise ValueError(f"ping {self.id} already processed at {self.processed_at}")
        if at < self.created_at:
            raise ValueError("processed_at must be at or after created_at")
        self.processed_at = at

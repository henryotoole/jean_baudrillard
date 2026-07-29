"""RepoPings — driven port for ping persistence (worker side, read+update)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from hex.processor.domain.ping import Ping


class RepoPings(Protocol):
    def claim_unprocessed(self, limit: int) -> list[Ping]: ...
    def mark_processed(self, id: UUID, at: datetime) -> None: ...

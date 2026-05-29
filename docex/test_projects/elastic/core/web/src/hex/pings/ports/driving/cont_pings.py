"""ContPings — driving port for the `pings` module."""

from __future__ import annotations

from typing import Protocol

from hex.pings.domain.ping import Ping


class ContPings(Protocol):
    def create(self, payload: str) -> Ping: ...

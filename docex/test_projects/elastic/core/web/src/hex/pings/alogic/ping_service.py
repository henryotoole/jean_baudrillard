"""PingService — application logic for the `pings` module.

Implements ContPings by tying domain construction to the driven repo.
"""

from __future__ import annotations

from hex.pings.domain.ping import Ping
from hex.pings.ports.driven.repo_pings import RepoPings


class PingService:
    def __init__(self, repo: RepoPings) -> None:
        self._repo = repo

    def create(self, payload: str) -> Ping:
        ping = Ping.create(payload=payload)
        self._repo.save(ping)
        return ping

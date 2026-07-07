"""ReaperService — application logic implementing ContReaper.

Ties the RetentionWindow domain rule to the driven repo: compute the
cutoff from "now", ask the repo to delete everything processed before it.
The clock is injected so the operation stays deterministic in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from hex.reaper.domain.retention_window import RetentionWindow
from hex.reaper.ports.driven.repo_pings import RepoPings
from hex.reaper.ports.driving.cont_reaper import ContReaper


class ReaperService(ContReaper):
    def __init__(
        self,
        repo: RepoPings,
        window: RetentionWindow,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repo = repo
        self._window = window
        self._clock = clock

    def reap(self) -> int:
        cutoff = self._window.cutoff(self._clock())
        return self._repo.delete_processed_before(cutoff)

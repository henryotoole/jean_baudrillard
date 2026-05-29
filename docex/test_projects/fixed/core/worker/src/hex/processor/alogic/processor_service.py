"""ProcessorService — application logic for the `processor` module.

Implements ContProcessor by tying the driven repo to the domain's
mark_processed transition.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hex.processor.ports.driven.repo_pings import RepoPings


class ProcessorService:
    def __init__(self, repo: RepoPings, batch_size: int = 32) -> None:
        self._repo = repo
        self._batch_size = batch_size

    def run_once(self) -> int:
        pings = self._repo.claim_unprocessed(limit=self._batch_size)
        now = datetime.now(timezone.utc)
        for ping in pings:
            # The actual "process" step is a no-op stub. Documented in processor.md.
            ping.mark_processed(at=now)
            self._repo.mark_processed(id=ping.id, at=now)
        return len(pings)

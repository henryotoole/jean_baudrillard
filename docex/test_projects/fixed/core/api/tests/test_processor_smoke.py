"""Smoke tests for the `processor` module of the `api` codebase.

`processor` is the module the `api.worker` core service drives. Verifies
the alogic processes pings correctly against a stub repo. Real postgres
exercise happens implicitly through module integration during the dev/test
compose stack — see plans/core/api/hex/processor.md.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4


sys.path.insert(0, "/service/dist")

from hex.processor.alogic.processor_service import ProcessorService  # noqa: E402
from hex.processor.domain.ping import Ping  # noqa: E402


class _StubRepo:
    def __init__(self, pings: list[Ping]) -> None:
        self._pings = pings
        self.marked: list[tuple] = []

    def claim_unprocessed(self, limit: int) -> list[Ping]:
        return self._pings[:limit]

    def mark_processed(self, id, at) -> None:
        self.marked.append((id, at))


def test_run_once_processes_all_claimed_pings() -> None:
    now = datetime.now(timezone.utc)
    pings = [
        Ping(id=uuid4(), payload="a", created_at=now - timedelta(seconds=2)),
        Ping(id=uuid4(), payload="b", created_at=now - timedelta(seconds=1)),
    ]
    repo = _StubRepo(pings=pings)
    service = ProcessorService(repo=repo)

    processed = service.run_once()

    assert processed == 2
    assert len(repo.marked) == 2

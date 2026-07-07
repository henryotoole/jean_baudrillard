"""Domain + alogic tests for the reaper module.

Pure unit tests — the domain rule (RetentionWindow) needs no I/O, and the
alogic ReaperService is exercised with an in-memory fake repo + a fixed
clock so no database is touched.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hex.reaper.alogic.reaper_service import ReaperService
from hex.reaper.domain.retention_window import RetentionWindow
from hex.reaper.ports.driven.repo_pings import RepoPings


def test_retention_window_rejects_nonpositive():
    with pytest.raises(ValueError):
        RetentionWindow(days=0)
    with pytest.raises(ValueError):
        RetentionWindow(days=-3)


def test_retention_window_cutoff():
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
    cutoff = RetentionWindow(days=30).cutoff(now)
    assert (now - cutoff).days == 30


class _FakeRepo(RepoPings):
    def __init__(self) -> None:
        self.cutoff_seen: datetime | None = None

    def delete_processed_before(self, cutoff: datetime) -> int:
        self.cutoff_seen = cutoff
        return 4


def test_reaper_service_passes_cutoff_and_returns_count():
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
    repo = _FakeRepo()
    service = ReaperService(
        repo=repo, window=RetentionWindow(days=30), clock=lambda: now,
    )
    deleted = service.reap()
    assert deleted == 4
    assert repo.cutoff_seen == RetentionWindow(days=30).cutoff(now)

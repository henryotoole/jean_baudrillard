"""Tests for `Boto3AWSClient.ecs_wait_for_task` consistency behavior.

Mod 027: after `RunTask`, the next `describe_tasks` can briefly return
`tasks: []` (ECS eventual consistency). The wait should tolerate empty
responses for up to ~30 s before raising, then become strict once the
task has been observed at least once.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docex.aws.boto3_client import Boto3AWSClient
from docex.errors import ECSTaskFailed


def _stopped_task(exit_code: int = 0) -> dict:
    return {
        "lastStatus": "STOPPED",
        "containers": [{"exitCode": exit_code, "lastStatus": "STOPPED"}],
    }


def test_ecs_wait_tolerates_brief_consistency_miss(monkeypatch):
    """`describe_tasks` returns empty on the first poll, populated on
    the second. The wait should complete successfully (the migration
    really ran)."""
    client = Boto3AWSClient()
    fake_ecs = MagicMock()
    fake_ecs.describe_tasks.side_effect = [
        {"tasks": []},
        {"tasks": [_stopped_task(0)]},
    ]
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)
    # Patch time.sleep so the test doesn't actually wait poll_interval.
    with patch("docex.aws.boto3_client.time.sleep", lambda _s: None):
        rc = client.ecs_wait_for_task(
            cluster="docex_smoke_elastic_prod",
            task_arn="arn:aws:ecs:us-east-1:1:task/p/abc",
            timeout_s=60,
        )
    assert rc == 0
    assert fake_ecs.describe_tasks.call_count == 2


def test_ecs_wait_raises_after_consistency_window(monkeypatch):
    """`describe_tasks` keeps returning empty past the 30 s consistency
    window — should raise. Use a patched monotonic clock to walk past
    the deadline in two calls."""
    client = Boto3AWSClient()
    fake_ecs = MagicMock()
    fake_ecs.describe_tasks.return_value = {"tasks": []}
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)
    # Patch monotonic to jump past the 30 s window on the second call.
    fake_times = iter([0.0, 0.0, 31.0, 31.0])
    monkeypatch.setattr(
        "docex.aws.boto3_client.time.monotonic", lambda: next(fake_times)
    )
    with patch("docex.aws.boto3_client.time.sleep", lambda _s: None):
        with pytest.raises(ECSTaskFailed, match="describe_tasks returned no record"):
            client.ecs_wait_for_task(
                cluster="cluster",
                task_arn="arn:aws:ecs:us-east-1:1:task/c/abc",
                timeout_s=120,
            )


def test_ecs_wait_raises_immediately_if_task_vanishes_after_seen(monkeypatch):
    """Once the task has been observed at least once, a subsequent
    empty response should NOT be tolerated — that's a real failure
    mode (task vanished), semantically different from initial
    consistency lag."""
    client = Boto3AWSClient()
    fake_ecs = MagicMock()
    fake_ecs.describe_tasks.side_effect = [
        # First call: task visible, still running.
        {"tasks": [{"lastStatus": "PENDING", "containers": []}]},
        # Second call: task vanished.
        {"tasks": []},
    ]
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)
    with patch("docex.aws.boto3_client.time.sleep", lambda _s: None):
        with pytest.raises(ECSTaskFailed, match="describe_tasks returned no record"):
            client.ecs_wait_for_task(
                cluster="c", task_arn="arn:t", timeout_s=120,
            )

"""Unit test for the ``tofu_destroy`` runner's command shape (Mod 052,
Gap F). Mirrors the ``tofu_apply`` argument handling — ``-auto-approve``
and ``-target=<addr>`` — without spawning the real binary.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from docex.opentofu.subprocess_runner import tofu_destroy


def test_tofu_destroy_auto_approve_default(monkeypatch, tmp_path: Path):
    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(
        "docex.opentofu.subprocess_runner.subprocess.run", fake_run
    )
    rc = tofu_destroy(tmp_path)
    assert rc == 0
    cmd = fake_run.call_args[0][0]
    assert cmd[:2] == ["tofu", f"-chdir={tmp_path}"]
    assert "destroy" in cmd
    assert "-input=false" in cmd
    # auto_approve defaults to True (inverse of tofu_apply's default).
    assert "-auto-approve" in cmd


def test_tofu_destroy_targets_and_no_auto_approve(monkeypatch, tmp_path: Path):
    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(
        "docex.opentofu.subprocess_runner.subprocess.run", fake_run
    )
    rc = tofu_destroy(
        tmp_path, auto_approve=False, targets=["aws_ecs_service.api"]
    )
    assert rc == 0
    cmd = fake_run.call_args[0][0]
    assert "-auto-approve" not in cmd
    assert "-target=aws_ecs_service.api" in cmd


def test_tofu_destroy_missing_binary_returns_127(monkeypatch, tmp_path: Path):
    def boom(*_a, **_kw):
        raise FileNotFoundError("tofu not on PATH")

    monkeypatch.setattr(
        "docex.opentofu.subprocess_runner.subprocess.run", boom
    )
    assert tofu_destroy(tmp_path) == 127

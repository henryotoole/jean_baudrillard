"""Unit tests for ``docex down``."""

from __future__ import annotations

import pytest

from docex.errors import EnvNotSupported
from docex.orchestrate.down import run_down


def test_down_rejects_stage(sample_ctx, fake_docker):
    with pytest.raises(EnvNotSupported):
        run_down(sample_ctx, fake_docker, env="stage")


def test_down_calls_compose_down_with_preserve_volumes(sample_ctx, fake_docker):
    rc = run_down(sample_ctx, fake_docker, env="dev")
    assert rc == 0

    down_calls = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(down_calls) == 1
    # (method, compose_file_str, preserve_volumes)
    assert down_calls[0][2] is True

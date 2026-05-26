"""Shared fixtures for integration tests.

Provides a ``running_dev`` fixture that brings up the sample fixture's
dev env via ``docex up dev`` and tears it down after the test. The
fixture is session-scoped to amortize image build cost, but each test
that mutates state should reset by hand.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "sample_project"


def _docker_available() -> bool:
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return False
    return res.returncode == 0


def pytest_collection_modifyitems(config, items):  # noqa: D401
    """Auto-skip integration tests when docker isn't reachable.

    The default addopts skips them entirely. When the user opts in via
    ``-m integration``, we still need a graceful skip if docker is gone.
    """
    if _docker_available():
        return
    skipper = pytest.mark.skip(reason="docker daemon not reachable")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skipper)


@pytest.fixture
def fresh_project(tmp_path: Path) -> Path:
    """Copy the sample fixture into a fresh temp dir.

    Returns the project root path (containing project.yml). Each
    integration test gets its own copy so they don't interfere.
    """
    dest = tmp_path / "smoke_project"
    shutil.copytree(_FIXTURE, dest, dirs_exist_ok=False)
    return dest


@pytest.fixture
def docker_client():
    """Return a SubprocessDockerClient for integration use."""
    from docex.docker import SubprocessDockerClient
    return SubprocessDockerClient()

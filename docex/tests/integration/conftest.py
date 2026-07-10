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


@pytest.fixture(autouse=True)
def _isolate_shared_stacks():
    """Wipe the sample fixture's shared compose stacks + data volumes around
    every integration test.

    WHY: the postgres data volume is named by the compose *project*
    (``sample-dev`` / ``sample-test``), derived from the fixture's
    ``project.yml`` name, NOT the per-test tmp dir — so it is shared across
    integration tests. Under the pre-envmageddon world the postgres password
    was a static committed fixture value, so a carried-over volume was benign.
    It is now a per-env **minted** TTE value (a fresh CSPRNG password per fresh
    project copy), so a volume left by a prior test holds a *stale* password and
    the next ``run_up``'s migrate step auth-fails. Forcing a clean slate before
    and after each test makes postgres re-initialize with the current mint.
    """
    def _clean() -> None:
        if not _docker_available():
            return
        for proj in ("sample-dev", "sample-test"):
            subprocess.run(
                ["docker", "compose", "-p", proj, "down", "-v", "--remove-orphans"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        # Belt-and-suspenders: the data volume name is deterministic
        # (<project>-<env>-appdb_data); remove it directly in case a `down`
        # without a compose file didn't resolve it.
        for vol in ("sample-dev-appdb_data", "sample-test-appdb_data"):
            subprocess.run(
                ["docker", "volume", "rm", "-f", vol],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
    _clean()
    yield
    _clean()


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

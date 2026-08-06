"""Shared fixtures for integration tests.

Provides a ``running_dev`` fixture that brings up the sample fixture's
dev env via ``docex up dev`` and tears it down after the test. The
fixture is session-scoped to amortize image build cost, but each test
that mutates state should reset by hand.
"""

from __future__ import annotations

import os
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


@pytest.fixture(autouse=True)
def _reclaim_root_owned_residue(tmp_path: Path):
    """Return ownership of the test's tmp tree to the host uid at teardown.

    WHY (Mod 119): every integration test leaves root-owned paths behind,
    because containers run as root against bind mounts —
    ``dist/__pycache__`` and ``dist/app.py`` from the dev stack,
    ``.pytest_cache`` and ``infra/stage/tests/__pycache__`` from the
    stagetest container. A root-owned *directory* makes its contents
    unlinkable by the host uid, so pytest's own tmp cleanup (it keeps the
    last 3 ``pytest-N`` roots and ``rm_rf``s the rest) raises
    PermissionError and abandons the whole root — pinning the gigabytes of
    OpenTofu AWS provider binaries the ``tofu validate`` tests download.
    Measured before this mod: 20 tiny root-owned paths holding 5.9 GB
    hostage. It surfaced as unrelated tests failing on
    ``no space left on device``.

    Two of those producers are outside ``dist/`` entirely, which is why the
    fix in ``orchestrate/build.py`` does not make this fixture redundant:
    nothing in ``build.py`` can reach ``.pytest_cache``. Do not delete this
    as duplicative of the product fix.

    ``chown``, not ``rm``: with ``tmp_path_retention_policy = "failed"`` the
    trees that survive are the failing ones, and those are exactly the ones
    someone wants to read.

    Depends on ``tmp_path`` so it finalizes *before* pytest's own
    ``tmp_path`` finalizer, which is what does the deleting.

    Best-effort: reclamation failing must never redden a green test.
    """
    yield
    if not _docker_available():
        return
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{tmp_path}:/work", "alpine:latest",
         "chown", "-R", f"{os.getuid()}:{os.getgid()}", "/work"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


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

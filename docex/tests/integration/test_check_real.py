"""Integration test for ``docex check`` against a real git repo + docker.

Sets up a temp git repo from the sample fixture, makes a feature
branch with a version bump, runs ``docex check``, asserts the
worktree is created + cleaned up, and that the gate-check sequence
runs end-to-end. Then deliberately breaks the contract and confirms
the check fails.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.docker import SubprocessDockerClient
from docex.git import SubprocessGitClient
from docex.pipeline.check import run_check


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "sample_project"


def _init_repo_with_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Materialize the sample fixture as a git repo with an upstream.

    Layout:
        tmp_path/origin.git/   -- bare upstream
        tmp_path/work/         -- the working clone with the fixture
    Returns (work, origin).
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"

    subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    shutil.copytree(_FIXTURE, work, dirs_exist_ok=False)
    # Drop any pre-existing infra/output/ so the fresh repo is clean.
    out = work / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)

    _git(work, "init", "-b", "main")
    _git(work, "remote", "add", "origin", str(origin))
    # Configure a local committer identity so the test machine doesn't
    # need a global git config.
    _git(work, "config", "user.email", "test@docex.test")
    _git(work, "config", "user.name", "docex test")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial: sample fixture")
    _git(work, "push", "-u", "origin", "main")
    return work, origin


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.mark.integration
def test_check_real_happy_path(tmp_path: Path):
    work, _origin = _init_repo_with_fixture(tmp_path)
    # Branch + bump.
    _git(work, "checkout", "-b", "feature/bump")
    pyml = work / "project.yml"
    pyml.write_text(pyml.read_text().replace('"0.1.0"', '"0.1.1"'))
    # Tweak a real source file too so the rebase actually has a delta.
    (work / "core" / "api" / "src" / "marker.py").write_text("# phase 3 marker\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "feat: bump version + marker")

    ctx = load_project_context(work)
    docker = SubprocessDockerClient()
    git = SubprocessGitClient()
    rc = run_check(ctx, docker, git)
    assert rc == 0

    # Worktree must be gone.
    worktrees = work / ".docex" / "worktrees"
    if worktrees.exists():
        assert not list(worktrees.iterdir()), list(worktrees.iterdir())


@pytest.mark.integration
def test_check_real_fails_on_missing_contract_health_path(tmp_path: Path):
    work, _origin = _init_repo_with_fixture(tmp_path)
    _git(work, "checkout", "-b", "feature/break-contract")
    # Remove the declared health_check_path from the contract.
    contract = work / "infra" / "contracts" / "api.web.rest.openapi.yml"
    contract.write_text(
        "openapi: '3.0.3'\n"
        "info: { title: api, version: '0.1.0' }\n"
        "paths:\n"
        "  /something: { get: { responses: { '200': { description: ok } } } }\n"
    )
    pyml = work / "project.yml"
    pyml.write_text(pyml.read_text().replace('"0.1.0"', '"0.1.1"'))
    _git(work, "add", ".")
    _git(work, "commit", "-m", "feat: break contract on purpose")

    ctx = load_project_context(work)
    docker = SubprocessDockerClient()
    git = SubprocessGitClient()
    rc = run_check(ctx, docker, git)
    assert rc == 1

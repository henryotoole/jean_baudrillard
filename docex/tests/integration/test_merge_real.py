"""Integration test for ``docex merge`` against a real git repo."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.docker import SubprocessDockerClient
from docex.git import SubprocessGitClient
from docex.pipeline import merge as merge_mod
from docex.pipeline.merge import run_merge


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "sample_project"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _git_check_ref(cwd: Path, ref: str) -> bool:
    res = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


def _init_repo_with_fixture(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.copytree(_FIXTURE, work, dirs_exist_ok=False)
    out = work / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)

    _git(work, "init", "-b", "main")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "config", "user.email", "test@docex.test")
    _git(work, "config", "user.name", "docex test")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial: sample fixture")
    _git(work, "push", "-u", "origin", "main")
    return work, origin


@pytest.mark.integration
def test_merge_real_fast_forwards_and_tags(tmp_path: Path, monkeypatch):
    work, origin = _init_repo_with_fixture(tmp_path)
    _git(work, "checkout", "-b", "feature/bump")
    pyml = work / "project.yml"
    pyml.write_text(pyml.read_text().replace('"0.1.0"', '"0.1.1"'))
    (work / "core" / "api" / "src" / "marker.py").write_text("# phase 3 merge marker\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "feat: bump + marker")
    _git(work, "push", "-u", "origin", "feature/bump")

    # Stub out the defensive ``run_check`` — it requires docker, which
    # the merge-real test doesn't want to depend on. This keeps the
    # focus on the git state-machine merge-specific behaviour.
    monkeypatch.setattr(merge_mod, "run_check", lambda *a, **kw: 0)

    ctx = load_project_context(work)
    docker = SubprocessDockerClient()
    git = SubprocessGitClient()
    rc = run_merge(ctx, docker, git)
    assert rc == 0, "merge should succeed end-to-end"

    # main now has the feature commit.
    assert _git_check_ref(work, "main")
    # Tag v0.1.1 exists locally.
    assert _git_check_ref(work, "v0.1.1")
    # Upstream has main + tag.
    assert _git_check_ref(origin, "main")
    assert _git_check_ref(origin, "v0.1.1")
    # Feature branch deleted locally + remotely.
    assert not _git_check_ref(work, "feature/bump")
    assert not _git_check_ref(origin, "refs/heads/feature/bump")

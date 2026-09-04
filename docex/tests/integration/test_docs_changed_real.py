"""Integration test for ``SubprocessGitClient.diff_names`` against real git.

Verifies the real git boundary the unit tests can only stub: ``git diff
--name-only <ref>`` against the working tree, restricted to the allowlist
pathspecs, and the empty-tree ref listing all tracked in-scope files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from docex.docs.changed import EMPTY_TREE
from docex.git import SubprocessGitClient


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.mark.integration
def test_diff_names_since_ref_and_empty_tree(tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()

    design = repo / "plans" / "design" / "boundary_conditions.md"
    design.parent.mkdir(parents=True)
    design.write_text("# Intro and Goals\n")
    src = repo / "core" / "api" / "src" / "hex" / "orders" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("x = 1\n")
    outside = repo / "README.md"
    outside.write_text("# proj\n")

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@docex.test")
    _git(repo, "config", "user.name", "docex test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    ref = "HEAD"
    pathspecs = ["plans/design", "core/api/src"]

    # Modify an in-scope design file and an out-of-allowlist file (uncommitted).
    design.write_text("# Intro and Goals\n\nmore\n")
    outside.write_text("# proj\n\nedited\n")

    git = SubprocessGitClient()
    changed = git.diff_names(repo, ref, pathspecs)

    assert "plans/design/boundary_conditions.md" in changed
    # README.md is not under the allowlist pathspecs → excluded by the diff.
    assert "README.md" not in changed

    # Empty-tree ref lists every tracked in-scope file.
    all_in_scope = git.diff_names(repo, EMPTY_TREE, pathspecs)
    assert "plans/design/boundary_conditions.md" in all_in_scope
    assert "core/api/src/hex/orders/service.py" in all_in_scope
    assert "README.md" not in all_in_scope

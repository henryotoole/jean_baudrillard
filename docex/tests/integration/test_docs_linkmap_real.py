"""Integration test for ``docex docs linkmap code_level`` against real git.

Verifies the git-tracked boundary the unit tests can only stub: a real
``git ls-files`` must include tracked source and exclude an untracked /
ignored artifact (``.pyc``). Runs the actual source-enumeration path
(``_resolve_tracked_source`` + ``build_linkmap``) against a temp repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from docex.docs.linkmap import _resolve_tracked_source, build_linkmap
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
def test_code_level_respects_git_tracking(tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()

    # A tracked hex source file + its module doc (for the emergent edge).
    svc = repo / "core" / "api" / "src" / "hex" / "orders" / "service.py"
    svc.parent.mkdir(parents=True)
    svc.write_text("x = 1\n")
    doc = repo / "plans" / "design" / "api" / "module" / "orders.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# Orders\n")

    # An artifact that is present on disk but NOT tracked (gitignored).
    (repo / "core" / "api" / "src" / "generated.pyc").write_text("junk\n")
    (repo / ".gitignore").write_text("*.pyc\n")

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@docex.test")
    _git(repo, "config", "user.name", "docex test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    git = SubprocessGitClient()
    source_files = _resolve_tracked_source(git, repo, ["api"])

    # Tracked source is enumerated; the .pyc is not.
    assert svc.resolve() in source_files
    assert not any(p.name == "generated.pyc" for p in source_files)

    nodes, edges = build_linkmap(
        repo, ["api"], "code_level", [doc], source_files
    )
    by = {n.fpath: n for n in nodes}

    # service.py is a source node; generated.pyc appears nowhere (nothing
    # links to it, so not even a neither stub).
    assert by["core/api/src/hex/orders/service.py"].type == "source"
    assert "core/api/src/generated.pyc" not in by

    # The emergent edge service.py → module doc is present.
    emergent = [
        e
        for e in edges
        if e.link_type == "emergent"
        and e.a == "core/api/src/hex/orders/service.py"
        and e.b == "plans/design/api/module/orders.md"
    ]
    assert len(emergent) == 1

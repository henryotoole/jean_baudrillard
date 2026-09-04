"""Unit tests for ``docex docs changed`` — in-scope changed set (mod 167).

The pure allowlist filter is exercised directly; the ref→changed-set helper is
driven with a ``FakeGitClient`` so no real git is needed.
"""

from __future__ import annotations

import pytest

from docex.docs.changed import (
    EMPTY_TREE,
    changed_fpaths,
    filter_changed,
    in_scope,
    run_docs_changed,
)
from tests.conftest import FakeGitClient


def _write(root, rel, text="x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ---------------------------------------------------------------------------
# in_scope allowlist
# ---------------------------------------------------------------------------


def test_in_scope_keeps_design_and_src():
    assert in_scope("plans/design/x.md", ["api"])
    assert in_scope("core/api/src/hex/orders/service.py", ["api"])


def test_in_scope_drops_out_of_allowlist():
    assert not in_scope("core/api/tests/test_x.py", ["api"])
    assert not in_scope("infra/infra.yml", ["api"])
    assert not in_scope("README.md", ["api"])
    # src for an unknown codebase.
    assert not in_scope("core/other/src/x.py", ["api"])
    # core/<cb>/src bare (no file under it) is not enough — needs >= 4 parts.
    assert not in_scope("core/api/src", ["api"])


# ---------------------------------------------------------------------------
# filter_changed — existence + sort + dedup
# ---------------------------------------------------------------------------


def test_filter_changed_drops_deleted_and_sorts(tmp_path):
    _write(tmp_path, "plans/design/b.md")
    _write(tmp_path, "core/api/src/a.py")
    paths = [
        "plans/design/b.md",
        "core/api/src/a.py",
        "plans/design/gone.md",  # not on disk → dropped
        "infra/infra.yml",       # out of scope → dropped
        "plans/design/b.md",     # dup
    ]
    out = filter_changed(paths, ["api"], tmp_path)
    assert out == ["core/api/src/a.py", "plans/design/b.md"]


# ---------------------------------------------------------------------------
# changed_fpaths — with FakeGitClient
# ---------------------------------------------------------------------------


def test_changed_fpaths_filters_to_in_scope_existing(tmp_path):
    _write(tmp_path, "plans/design/b.md")
    _write(tmp_path, "core/api/src/a.py")
    git = FakeGitClient(
        diff_names_map={
            "REF": [
                "plans/design/b.md",
                "core/api/src/a.py",
                "infra/infra.yml",       # out of scope
                "plans/design/gone.md",  # deleted
            ]
        },
        rev_parse_map={"REF": "sha1"},
    )
    out = changed_fpaths(tmp_path, ["api"], "REF", git=git)
    assert out == ["core/api/src/a.py", "plans/design/b.md"]


def test_changed_fpaths_empty_tree_lists_all(tmp_path):
    _write(tmp_path, "plans/design/b.md")
    git = FakeGitClient(
        diff_names_map={EMPTY_TREE: ["plans/design/b.md"]},
    )
    out = changed_fpaths(tmp_path, ["api"], EMPTY_TREE, git=git)
    assert out == ["plans/design/b.md"]


def test_changed_fpaths_bad_ref_raises(tmp_path):
    # rev_parse returns "" for the ref → unresolvable.
    git = FakeGitClient(rev_parse_map={"BAD": ""})
    with pytest.raises(ValueError):
        changed_fpaths(tmp_path, ["api"], "BAD", git=git)


def test_run_docs_changed_bad_ref_returns_1(capsys, sample_ctx):
    # run_docs_changed builds its own SubprocessGitClient; the sample fixture is
    # a tmp copy (not a git repo), so any ref fails to resolve → ValueError →
    # exit 1 with the ref named on stderr.
    rc = run_docs_changed(sample_ctx, "definitely-not-a-ref")
    assert rc == 1
    assert "definitely-not-a-ref" in capsys.readouterr().err

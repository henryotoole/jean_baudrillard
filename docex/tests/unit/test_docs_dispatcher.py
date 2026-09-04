"""Unit tests for the ``docex docs`` dispatcher wiring (mod 160)."""

from __future__ import annotations

import pytest

from docex.__main__ import (
    _HELP_TEXT,
    _build_handler_table,
    _cmd_docs,
    _format_usage,
)


def test_handler_table_has_docs():
    assert "docs" in _build_handler_table()


def test_help_surface_has_docs():
    assert "docs" in _HELP_TEXT
    assert "Documentation:" in _format_usage()


def test_cmd_docs_scaffold_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    seen = {}

    def fake(ctx):
        seen["scaffold"] = ctx
        return 0

    # The dispatcher imports run_docs_scaffold FROM the docex.docs package,
    # so patch the name on that package.
    monkeypatch.setattr("docex.docs.run_docs_scaffold", fake)

    assert _cmd_docs(["scaffold"]) == 0
    assert "scaffold" in seen


def test_cmd_docs_check_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    seen = {}

    def fake(ctx):
        seen["check"] = ctx
        return 0

    monkeypatch.setattr("docex.docs.run_docs_check", fake)

    assert _cmd_docs(["check"]) == 0
    assert "check" in seen


def test_cmd_docs_requires_a_subcommand():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs([])
    assert excinfo.value.code == 2


def test_cmd_docs_linkmap_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    seen = {}

    def fake(ctx, depth):
        seen["depth"] = depth
        return 0

    monkeypatch.setattr("docex.docs.run_docs_linkmap", fake)

    assert _cmd_docs(["linkmap", "design_docs"]) == 0
    assert seen["depth"] == "design_docs"


def test_cmd_docs_linkmap_rejects_invalid_depth():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["linkmap", "bogus"])
    assert excinfo.value.code == 2


def test_cmd_docs_linkmap_requires_a_depth():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["linkmap"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# Consumer verbs (mod 167)
# ---------------------------------------------------------------------------


def test_cmd_docs_overhead_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    seen = {}

    def fake(ctx, file):
        seen["file"] = file
        return 0

    monkeypatch.setattr("docex.docs.run_docs_overhead", fake)

    assert _cmd_docs(["overhead", "plans/design/x.md"]) == 0
    assert seen["file"] == "plans/design/x.md"


def test_cmd_docs_changed_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    seen = {}

    def fake(ctx, git_ref):
        seen["ref"] = git_ref
        return 0

    monkeypatch.setattr("docex.docs.run_docs_changed", fake)

    assert _cmd_docs(["changed", "HEAD~3"]) == 0
    assert seen["ref"] == "HEAD~3"


def test_cmd_docs_cxt_groups_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    seen = {}

    def fake(ctx, tokens_max, selection):
        seen["tokens_max"] = tokens_max
        seen["selection"] = selection
        return 0

    monkeypatch.setattr("docex.docs.run_docs_cxt_groups", fake)

    assert _cmd_docs(["cxt_groups", "40000", "all"]) == 0
    assert seen["tokens_max"] == 40000
    assert seen["selection"] == "all"


def test_cmd_docs_cxt_groups_rejects_non_int_tokens_max():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["cxt_groups", "lots", "all"])
    assert excinfo.value.code == 2


def test_cmd_docs_overhead_requires_a_file():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["overhead"])
    assert excinfo.value.code == 2


def test_cmd_docs_changed_requires_a_ref():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["changed"])
    assert excinfo.value.code == 2


def test_cmd_docs_cxt_groups_requires_both_args():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["cxt_groups", "40000"])
    assert excinfo.value.code == 2

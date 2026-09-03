"""Unit tests for the single canonical standard-set definition (mod 160)."""

from __future__ import annotations

from docex.docs.standard_set import resolve


_MANDATORY_L1 = {
    "design/boundary_conditions.md",
    "design/concepts_and_decisions.md",
    "design/structures_and_views.md",
    "design/lexicon.md",
    "design/unknowns.md",
    "design/adr_index.md",
    "design/adr_active.md",
    "design/project_diagram.mmd",
    "design/service_diagram.mmd",
    "design/adrs",
    "references",
}


def test_resolve_empty_returns_project_entries_only():
    entries = resolve([])
    rels = {e.rel_path for e in entries}
    # All mandatory L1 entries are present.
    assert _MANDATORY_L1 <= rels
    # No codebase-scoped entry leaks in when there are no codebases.
    assert not any("module_diagram.mmd" in r for r in rels)
    assert not any("/module" in r for r in rels)
    # `product` is optional.
    product = next(e for e in entries if e.rel_path == "product")
    assert product.optional is True
    # The mandatory L1 files/dirs are not optional.
    for e in entries:
        if e.rel_path in _MANDATORY_L1:
            assert e.optional is False, e.rel_path


def test_resolve_expands_codebase_entries_per_codebase():
    entries = resolve(["api", "frontend"])
    rels = {e.rel_path for e in entries}
    for cb in ("api", "frontend"):
        assert f"design/{cb}/module_diagram.mmd" in rels
        assert f"design/{cb}/module" in rels
        assert f"design/{cb}/specifics" in rels
    # Project entries still there.
    assert _MANDATORY_L1 <= rels


def test_resolve_optional_files_marked_optional():
    entries = {e.rel_path: e for e in resolve([])}
    assert entries["design/doctrine_ext.md"].optional is True
    assert entries["design/quality_scenarios.md"].optional is True

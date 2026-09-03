"""Unit tests for ``docex docs check`` — missing-file + reachability (mod 160)."""

from __future__ import annotations

from docex.docs.check import (
    check_docs,
    design_root_exists,
    missing_standard_files,
    unreachable_docs,
)
from docex.docs.scaffold import scaffold_design


def test_missing_standard_file_is_named(tmp_path):
    scaffold_design(tmp_path, ["api"])
    (tmp_path / "plans" / "design" / "unknowns.md").unlink()
    problems = missing_standard_files(tmp_path, ["api"])
    assert any("unknowns.md" in p for p in problems)


def test_missing_codebase_module_diagram_is_named(tmp_path):
    scaffold_design(tmp_path, ["api"])
    (tmp_path / "plans" / "design" / "api" / "module_diagram.mmd").unlink()
    problems = missing_standard_files(tmp_path, ["api"])
    assert any("api/module_diagram.mmd" in p for p in problems)


def test_optional_files_not_required(tmp_path):
    scaffold_design(tmp_path, ["api"])
    # doctrine_ext.md / quality_scenarios.md were never created; still clean.
    assert missing_standard_files(tmp_path, ["api"]) == []


def test_skip_when_design_absent(tmp_path):
    # On a bare tree the guard lives in check_docs / _gate_docs (both consult
    # design_root_exists BEFORE the pure checks), so the SKIP behavior is that
    # check_docs returns 0 and design_root_exists is False. unreachable_docs is
    # self-guarding and returns []. missing_standard_files is a pure enumerator
    # with no self-guard, so it is never called on an absent tree in practice.
    assert design_root_exists(tmp_path) is False
    assert unreachable_docs(tmp_path, []) == []
    assert check_docs(tmp_path, []) == 0


def test_reachability_orphan_is_named(tmp_path):
    scaffold_design(tmp_path, ["api"])
    orphan = tmp_path / "plans" / "design" / "orphan.md"
    orphan.write_text("# Orphan\n\nNothing links to me.\n")
    problems = unreachable_docs(tmp_path, ["api"])
    assert any("plans/design/orphan.md" in p for p in problems)


def test_reachability_via_markdown_link(tmp_path):
    scaffold_design(tmp_path, ["api"])
    extra = tmp_path / "plans" / "design" / "extra.md"
    extra.write_text("# Extra\n")
    root = tmp_path / "plans" / "design" / "structures_and_views.md"
    root.write_text(root.read_text() + "\n[extra](./extra.md)\n")
    assert unreachable_docs(tmp_path, ["api"]) == []


def test_reachability_via_mermaid_click(tmp_path):
    scaffold_design(tmp_path, ["api"])
    module_doc = tmp_path / "plans" / "design" / "api" / "module" / "orders.md"
    module_doc.write_text("# Orders\n")
    diagram = tmp_path / "plans" / "design" / "api" / "module_diagram.mmd"
    diagram.write_text(
        diagram.read_text() + '    click orders "./module/orders.md"\n'
    )
    assert unreachable_docs(tmp_path, ["api"]) == []


def test_check_docs_return_codes(tmp_path):
    scaffold_design(tmp_path, ["api"])
    # Clean tree -> 0.
    assert check_docs(tmp_path, ["api"]) == 0
    # Add an orphan -> 1.
    (tmp_path / "plans" / "design" / "orphan.md").write_text("# Orphan\n")
    assert check_docs(tmp_path, ["api"]) == 1

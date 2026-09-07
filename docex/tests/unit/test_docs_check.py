"""Unit tests for ``docex docs check`` — missing-file + reachability (mod 160)."""

from __future__ import annotations

from docex.docs.check import (
    check_docs,
    design_root_exists,
    missing_standard_files,
    unreachable_docs,
    unresolved_anchors,
)
from docex.docs.scaffold import scaffold_design
from docex.docs.adr import regenerate_adr_indexes


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


def test_orphan_message_format_is_preserved(tmp_path):
    # Mod 165 refactored unreachable_docs onto the linkmap; the exact problem
    # string must stay byte-for-byte identical (the docex check gate + its
    # tests depend on it).
    scaffold_design(tmp_path, ["api"])
    (tmp_path / "plans" / "design" / "orphan.md").write_text("# Orphan\n")
    problems = unreachable_docs(tmp_path, ["api"])
    assert (
        "unreachable doc: plans/design/orphan.md "
        "(not linked from any standard doc or diagram)"
    ) in problems


def test_orphan_message_format_nested_path(tmp_path):
    # A nested orphan formats its path relative to plans/design (not the
    # project root), exactly as the pre-refactor code did.
    scaffold_design(tmp_path, ["api"])
    nested = tmp_path / "plans" / "design" / "api" / "specifics" / "loose.md"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("# Loose\n")
    problems = unreachable_docs(tmp_path, ["api"])
    assert (
        "unreachable doc: plans/design/api/specifics/loose.md "
        "(not linked from any standard doc or diagram)"
    ) in problems


def test_adr_reachable_only_via_generated_index(tmp_path):
    # An ADR linked from NOWHERE but the generated index is still reachable: the
    # linked index carries the edge (mod 170). Before regeneration the stub index
    # is empty, so the ADR is a genuine orphan — proving the link is load-bearing.
    scaffold_design(tmp_path, ["api"])
    adrs = tmp_path / "plans" / "design" / "adrs"
    adrs.mkdir(parents=True, exist_ok=True)
    (adrs / "0001_thing.md").write_text(
        "---\nid: 0001\ntitle: thing\nstatus: accepted\n"
        "date: 2026-01-01\nsupersedes: []\nsuperseded-by: []\ntags: []\n---\n\n"
        "## Context\n...\n"
    )
    # Empty stub index -> the ADR is unreachable.
    before = unreachable_docs(tmp_path, ["api"])
    assert any("adrs/0001_thing.md" in p for p in before)
    # Regenerate: the index now links the ADR -> reachable, whole check green.
    regenerate_adr_indexes(tmp_path)
    assert unreachable_docs(tmp_path, ["api"]) == []
    assert check_docs(tmp_path, ["api"]) == 0


# ---------------------------------------------------------------------------
# Anchor resolution + doc-extension reachability scope (mod 171)
# ---------------------------------------------------------------------------


def test_anchor_cross_file_unresolved_is_named(tmp_path):
    scaffold_design(tmp_path, ["api"])
    target = tmp_path / "plans" / "design" / "target.md"
    target.write_text("# Real Heading\n")
    root = tmp_path / "plans" / "design" / "structures_and_views.md"
    root.write_text(
        root.read_text()
        + "\n[t](./target.md#no-such-heading)\n[t2](./target.md)\n"
    )
    problems = unresolved_anchors(tmp_path, ["api"])
    assert (
        "unresolved anchor: plans/design/structures_and_views.md "
        "-> plans/design/target.md#no-such-heading"
    ) in problems
    assert check_docs(tmp_path, ["api"]) == 1


def test_anchor_same_file_dangling_is_named(tmp_path):
    scaffold_design(tmp_path, ["api"])
    root = tmp_path / "plans" / "design" / "structures_and_views.md"
    root.write_text(root.read_text() + "\n[g](#gone)\n")
    problems = unresolved_anchors(tmp_path, ["api"])
    assert (
        "unresolved anchor: plans/design/structures_and_views.md "
        "-> plans/design/structures_and_views.md#gone"
    ) in problems


def test_anchor_resolves_when_corrected(tmp_path):
    scaffold_design(tmp_path, ["api"])
    target = tmp_path / "plans" / "design" / "target.md"
    target.write_text("# Real Heading\n")
    root = tmp_path / "plans" / "design" / "structures_and_views.md"
    root.write_text(
        root.read_text()
        + "\n[t](./target.md#real-heading)\n[t2](./target.md)\n"
    )
    assert unresolved_anchors(tmp_path, ["api"]) == []
    assert check_docs(tmp_path, ["api"]) == 0


def test_anchor_explicit_id_resolves(tmp_path):
    scaffold_design(tmp_path, ["api"])
    target = tmp_path / "plans" / "design" / "target.md"
    target.write_text("# Heading\n\n<a id=\"pinned\"></a>\n")
    root = tmp_path / "plans" / "design" / "structures_and_views.md"
    root.write_text(
        root.read_text() + "\n[t](./target.md#pinned)\n[t2](./target.md)\n"
    )
    assert unresolved_anchors(tmp_path, ["api"]) == []


def test_anchor_into_unscanned_target_not_failed(tmp_path):
    scaffold_design(tmp_path, ["api"])
    root = tmp_path / "plans" / "design" / "structures_and_views.md"
    # Target is OUTSIDE plans/design; never scanned -> fragment not validated.
    root.write_text(
        root.read_text() + "\n[r](../references/foo.md#whatever)\n"
    )
    assert unresolved_anchors(tmp_path, ["api"]) == []


def test_loose_asset_does_not_fail_reachability(tmp_path):
    scaffold_design(tmp_path, ["api"])
    asset = (
        tmp_path / "plans" / "design" / "api" / "specifics" / "icons" / "logo.svg"
    )
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\x00\x01\x02<svg></svg>")
    assert unreachable_docs(tmp_path, ["api"]) == []
    assert check_docs(tmp_path, ["api"]) == 0


def test_mod170_adr_index_links_survive_anchor_check(tmp_path):
    scaffold_design(tmp_path, ["api"])
    adrs = tmp_path / "plans" / "design" / "adrs"
    adrs.mkdir(parents=True, exist_ok=True)
    (adrs / "0001_thing.md").write_text(
        "---\nid: 0001\ntitle: thing\nstatus: accepted\n"
        "date: 2026-01-01\nsupersedes: []\nsuperseded-by: []\ntags: []\n---\n\n"
        "## Context\n...\n"
    )
    regenerate_adr_indexes(tmp_path)
    assert unresolved_anchors(tmp_path, ["api"]) == []
    assert check_docs(tmp_path, ["api"]) == 0

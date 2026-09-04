"""Unit tests for ``docex docs overhead`` — structural overhead (mod 167).

``compute_overhead`` is pure over an already-built ``(nodes, edges)`` graph, so
these inject file lists directly into ``build_linkmap`` (no git). The
not-a-node error path is covered via ``run_docs_overhead`` with a ``sample_ctx``.
"""

from __future__ import annotations

from docex.docs.linkmap import _enumerate_design_files, build_linkmap
from docex.docs.overhead import (
    compute_overhead,
    outgoing_design_targets,
    run_docs_overhead,
)
from docex.docs.scaffold import scaffold_design


def _write(root, rel, text="# x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _overhead_fpaths(nodes, edges, subject):
    return [n.fpath for n in compute_overhead(nodes, edges, subject)]


# ---------------------------------------------------------------------------
# Rule 1 — L1 roots + standard diagrams
# ---------------------------------------------------------------------------


def test_rule1_l1_roots_always_present(tmp_path):
    scaffold_design(tmp_path, ["api"])
    subject = _write(tmp_path, "plans/design/api/specifics/foo.md")
    design = _enumerate_design_files(tmp_path)
    nodes, edges = build_linkmap(tmp_path, ["api"], "code_level", design, [])

    ov = set(_overhead_fpaths(nodes, edges, "plans/design/api/specifics/foo.md"))
    for root in (
        "plans/design/boundary_conditions.md",
        "plans/design/concepts_and_decisions.md",
        "plans/design/structures_and_views.md",
        "plans/design/project_diagram.mmd",
        "plans/design/service_diagram.mmd",
        "plans/design/api/module_diagram.mmd",
    ):
        assert root in ov
    # The subject itself is never in its own overhead.
    assert "plans/design/api/specifics/foo.md" not in ov


# ---------------------------------------------------------------------------
# Rule 2 — direct links (markdown + mermaid)
# ---------------------------------------------------------------------------


def test_rule2_markdown_link_is_overhead(tmp_path):
    subject = _write(
        tmp_path,
        "plans/design/api/overview.md",
        "# o\n[foo](./specifics/foo.md)\n",
    )
    _write(tmp_path, "plans/design/api/specifics/foo.md")
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [subject, tmp_path / "plans/design/api/specifics/foo.md"], []
    )
    ov = set(_overhead_fpaths(nodes, edges, "plans/design/api/overview.md"))
    assert "plans/design/api/specifics/foo.md" in ov


def test_rule2_mermaid_click_is_overhead(tmp_path):
    diagram = _write(
        tmp_path,
        "plans/design/api/module_diagram.mmd",
        'graph TD\n    click orders "./module/orders.md"\n',
    )
    doc = _write(tmp_path, "plans/design/api/module/orders.md")
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [diagram, doc], []
    )
    ov = set(
        _overhead_fpaths(nodes, edges, "plans/design/api/module_diagram.mmd")
    )
    assert "plans/design/api/module/orders.md" in ov


# ---------------------------------------------------------------------------
# Source subject + module doc (emergent = rule 2 fold-in) + rule 3
# ---------------------------------------------------------------------------


def test_source_subject_pulls_module_doc_and_its_links(tmp_path):
    src = _write(tmp_path, "core/api/src/hex/orders/service.py", "x = 1\n")
    module_doc = _write(
        tmp_path,
        "plans/design/api/module/orders.md",
        "# Orders\n[dep](../specifics/dep.md)\n",
    )
    dep = _write(tmp_path, "plans/design/api/specifics/dep.md")
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [module_doc, dep], [src]
    )
    ov = set(
        _overhead_fpaths(
            nodes, edges, "core/api/src/hex/orders/service.py"
        )
    )
    # Rule 2 (emergent fold-in): the module doc itself.
    assert "plans/design/api/module/orders.md" in ov
    # Rule 3: the doc the module doc links to.
    assert "plans/design/api/specifics/dep.md" in ov


# ---------------------------------------------------------------------------
# Exclusions — overhead is design docs only
# ---------------------------------------------------------------------------


def test_source_and_neither_targets_excluded(tmp_path):
    # A design doc linking to a source file and to an out-of-project target;
    # neither may appear as overhead.
    subject = _write(
        tmp_path,
        "plans/design/api/overview.md",
        "# o\n[s](../../core/api/src/hex/orders/service.py)\n"
        "[out](../../../doctrine/foo.md)\n",
    )
    src = _write(tmp_path, "core/api/src/hex/orders/service.py", "x = 1\n")
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [subject], [src]
    )
    ov = set(_overhead_fpaths(nodes, edges, "plans/design/api/overview.md"))
    assert "core/api/src/hex/orders/service.py" not in ov
    assert not any(fp.startswith("..") for fp in ov)


def test_outgoing_design_targets_only_design(tmp_path):
    subject = _write(
        tmp_path,
        "plans/design/api/overview.md",
        "# o\n[s](../../core/api/src/hex/orders/service.py)\n"
        "[d](./specifics/foo.md)\n",
    )
    src = _write(tmp_path, "core/api/src/hex/orders/service.py", "x = 1\n")
    _write(tmp_path, "plans/design/api/specifics/foo.md")
    nodes, edges = build_linkmap(
        tmp_path,
        ["api"],
        "code_level",
        [subject, tmp_path / "plans/design/api/specifics/foo.md"],
        [src],
    )
    targets = outgoing_design_targets(
        nodes, edges, "plans/design/api/overview.md"
    )
    assert targets == {"plans/design/api/specifics/foo.md"}


# ---------------------------------------------------------------------------
# Ordering — high→low abstraction, ties by fpath
# ---------------------------------------------------------------------------


def test_overhead_ordered_high_to_low(tmp_path):
    scaffold_design(tmp_path, ["api"])
    # Subject links an L2 and an L3 doc; L1 roots come from scaffold.
    subject = _write(
        tmp_path,
        "plans/design/api/overview.md",
        "# o\n[l2](./specifics/foo.md)\n[l3](./module/orders.md)\n",
    )
    _write(tmp_path, "plans/design/api/specifics/foo.md")
    _write(tmp_path, "plans/design/api/module/orders.md")
    design = _enumerate_design_files(tmp_path)
    nodes, edges = build_linkmap(tmp_path, ["api"], "code_level", design, [])
    ov_nodes = compute_overhead(nodes, edges, "plans/design/api/overview.md")
    ranks = {"L1": 0, "L2": 1, "L3": 2}
    seq = [ranks[n.level] for n in ov_nodes]
    assert seq == sorted(seq)  # non-decreasing rank
    # Within-rank ties are by fpath.
    for a, b in zip(ov_nodes, ov_nodes[1:]):
        if a.level == b.level:
            assert a.fpath < b.fpath


# ---------------------------------------------------------------------------
# Dispatcher error path
# ---------------------------------------------------------------------------


def test_run_docs_overhead_not_a_node_returns_1(capsys, sample_ctx):
    rc = run_docs_overhead(sample_ctx, "plans/design/nope.md")
    assert rc == 1
    err = capsys.readouterr().err
    assert "plans/design/nope.md" in err

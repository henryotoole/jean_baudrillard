"""Unit tests for ``docex docs linkmap`` — the doc/code link graph (mod 165).

``build_linkmap`` is pure and git-free, so every test here injects the
``design_files`` / ``source_files`` lists directly; the git-tracked source
enumeration is exercised by the integration test.
"""

from __future__ import annotations

import json

from docex.docs.linkmap import (
    _enumerate_design_files,
    _slug,
    anchors_in,
    build_linkmap,
    fragment_links_in,
    render_linkmap_json,
)
from docex.docs.scaffold import scaffold_design


def _write(root, rel, text="# x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _nodes_by_fpath(nodes):
    return {n.fpath: n for n in nodes}


# ---------------------------------------------------------------------------
# Node metadata
# ---------------------------------------------------------------------------


def test_node_metadata_l1_standard(tmp_path):
    scaffold_design(tmp_path, ["api"])
    p = tmp_path / "plans" / "design" / "boundary_conditions.md"
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/boundary_conditions.md"]
    assert n.type == "design"
    assert n.is_standard is True
    assert n.level == "L1"
    assert n.codebase == "none"
    assert n.module == "none"
    assert isinstance(n.tokens, int) and n.tokens > 0


def test_node_metadata_l2_module_diagram_standard(tmp_path):
    scaffold_design(tmp_path, ["api"])
    p = tmp_path / "plans" / "design" / "api" / "module_diagram.mmd"
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/api/module_diagram.mmd"]
    assert n.level == "L2"
    assert n.is_standard is True
    assert n.codebase == "api"
    assert n.module == "none"


def test_node_metadata_l2_specifics_not_standard(tmp_path):
    p = _write(tmp_path, "plans/design/api/specifics/foo.md")
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/api/specifics/foo.md"]
    assert n.level == "L2"
    assert n.is_standard is False
    assert n.codebase == "api"


def test_node_metadata_l3_module_doc_not_standard(tmp_path):
    p = _write(tmp_path, "plans/design/api/module/orders.md")
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/api/module/orders.md"]
    assert n.level == "L3"
    # A module doc's name varies, so it is NOT a doctrine-standard file.
    assert n.is_standard is False
    assert n.codebase == "api"
    assert n.module == "orders"


def test_node_metadata_adr_dir_is_l1(tmp_path):
    p = _write(tmp_path, "plans/design/adrs/0001_x/decision.md")
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/adrs/0001_x/decision.md"]
    assert n.level == "L1"
    assert n.codebase == "none"
    assert n.module == "none"
    assert n.is_standard is False


def test_node_metadata_adr_index_is_standard_l1(tmp_path):
    scaffold_design(tmp_path, ["api"])
    p = tmp_path / "plans" / "design" / "adr_index.md"
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/adr_index.md"]
    assert n.level == "L1"
    assert n.is_standard is True


def test_source_node_metadata(tmp_path):
    sp = _write(tmp_path, "core/api/src/hex/orders/service.py", "x = 1\n")
    nodes, _ = build_linkmap(tmp_path, ["api"], "code_level", [], [sp])
    n = _nodes_by_fpath(nodes)["core/api/src/hex/orders/service.py"]
    assert n.type == "source"
    assert n.level == "C"
    assert n.is_standard is False
    assert n.codebase == "api"
    assert n.module == "orders"


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


def test_markdown_edge(tmp_path):
    a = _write(tmp_path, "plans/design/a.md", "# a\n[b](./b.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n")
    _, edges = build_linkmap(tmp_path, ["api"], "design_docs", [a, b], [])
    assert len(edges) == 1
    e = edges[0]
    assert e.a == "plans/design/a.md"
    assert e.b == "plans/design/b.md"
    assert e.link_type == "markdown"
    assert e.direction == "a_to_b"


def test_mermaid_click_edge(tmp_path):
    diagram = _write(
        tmp_path,
        "plans/design/api/module_diagram.mmd",
        'graph TD\n    click orders "./module/orders.md"\n',
    )
    doc = _write(tmp_path, "plans/design/api/module/orders.md")
    _, edges = build_linkmap(
        tmp_path, ["api"], "design_docs", [diagram, doc], []
    )
    click_edges = [e for e in edges if e.link_type == "mermaid_click"]
    assert len(click_edges) == 1
    endpoints = {click_edges[0].a, click_edges[0].b}
    assert endpoints == {
        "plans/design/api/module_diagram.mmd",
        "plans/design/api/module/orders.md",
    }


def test_emergent_edge_source_to_module_doc(tmp_path):
    sp = _write(tmp_path, "core/api/src/hex/orders/service.py", "x = 1\n")
    doc = _write(tmp_path, "plans/design/api/module/orders.md")
    _, edges = build_linkmap(tmp_path, ["api"], "code_level", [doc], [sp])
    emergent = [e for e in edges if e.link_type == "emergent"]
    assert len(emergent) == 1
    e = emergent[0]
    # Directed source → doc; source fpath sorts before the doc fpath.
    assert e.a == "core/api/src/hex/orders/service.py"
    assert e.b == "plans/design/api/module/orders.md"
    assert e.direction == "a_to_b"


def test_emergent_edge_absent_when_no_module_doc(tmp_path):
    sp = _write(tmp_path, "core/api/src/hex/orders/service.py", "x = 1\n")
    # No plans/design/api/module/orders.md scanned.
    _, edges = build_linkmap(tmp_path, ["api"], "code_level", [], [sp])
    assert [e for e in edges if e.link_type == "emergent"] == []


# ---------------------------------------------------------------------------
# Direction merge
# ---------------------------------------------------------------------------


def test_reciprocal_same_type_merges_to_both(tmp_path):
    a = _write(tmp_path, "plans/design/a.md", "# a\n[b](./b.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n[a](./a.md)\n")
    _, edges = build_linkmap(tmp_path, ["api"], "design_docs", [a, b], [])
    assert len(edges) == 1
    assert edges[0].direction == "both"


def test_only_higher_to_lower_is_b_to_a(tmp_path):
    x = _write(tmp_path, "plans/design/x.md", "# x\n")
    y = _write(tmp_path, "plans/design/y.md", "# y\n[x](./x.md)\n")
    _, edges = build_linkmap(tmp_path, ["api"], "design_docs", [x, y], [])
    assert len(edges) == 1
    e = edges[0]
    assert (e.a, e.b) == ("plans/design/x.md", "plans/design/y.md")
    assert e.direction == "b_to_a"


def test_different_link_types_stay_distinct_edges(tmp_path):
    # A markdown link AND a mermaid click between the same pair → two edges.
    diagram = _write(
        tmp_path,
        "plans/design/a.mmd",
        'graph TD\n    click b "./b.md"\n',
    )
    b = _write(tmp_path, "plans/design/b.md", "# b\n[a](./a.mmd)\n")
    _, edges = build_linkmap(tmp_path, ["api"], "design_docs", [diagram, b], [])
    link_types = sorted(e.link_type for e in edges)
    assert link_types == ["markdown", "mermaid_click"]


# ---------------------------------------------------------------------------
# neither nodes / depth-relative typing
# ---------------------------------------------------------------------------


def test_link_outside_project_is_neither(tmp_path):
    d = _write(
        tmp_path,
        "plans/design/d.md",
        "# d\n[out](../../../doctrine/foo.md)\n",
    )
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [d], [])
    neither = [n for n in nodes if n.type == "neither"]
    assert len(neither) == 1
    n = neither[0]
    assert n.fpath.startswith("..")  # os.path.relpath ../-style path
    assert n.tokens is None
    assert n.level is None
    assert n.is_standard is False
    assert n.codebase == "none"


def test_depth_relative_source_link(tmp_path):
    d = _write(
        tmp_path,
        "plans/design/d.md",
        "# d\n[s](../../core/api/src/foo.py)\n",
    )
    foo = _write(tmp_path, "core/api/src/foo.py", "x = 1\n")

    # design_docs: source is not scanned → the target is a neither stub.
    nodes_dd, _ = build_linkmap(tmp_path, ["api"], "design_docs", [d], [])
    tgt_dd = _nodes_by_fpath(nodes_dd)["core/api/src/foo.py"]
    assert tgt_dd.type == "neither"
    assert tgt_dd.tokens is None

    # code_level with foo.py tracked → the target is a source node.
    nodes_cl, _ = build_linkmap(tmp_path, ["api"], "code_level", [d], [foo])
    tgt_cl = _nodes_by_fpath(nodes_cl)["core/api/src/foo.py"]
    assert tgt_cl.type == "source"
    assert tgt_cl.level == "C"


def test_untracked_source_under_core_is_neither_at_code_level(tmp_path):
    # C.O.-requested: at code_level, a link to a core/*/src file that is NOT
    # in source_files (i.e. git-untracked) is a `neither` stub — this pins the
    # git-tracked boundary.
    tracked = _write(tmp_path, "core/api/src/hex/orders/service.py", "x = 1\n")
    d = _write(
        tmp_path,
        "plans/design/d.md",
        "# d\n[g](../../core/api/src/generated.py)\n",
    )
    _write(tmp_path, "core/api/src/generated.py", "y = 2\n")  # exists, untracked

    nodes, _ = build_linkmap(
        tmp_path, ["api"], "code_level", [d], [tracked]
    )
    by = _nodes_by_fpath(nodes)
    assert by["core/api/src/generated.py"].type == "neither"
    assert by["core/api/src/hex/orders/service.py"].type == "source"


# ---------------------------------------------------------------------------
# Determinism / rendering / tokens
# ---------------------------------------------------------------------------


def test_render_is_deterministic_and_sorted(tmp_path):
    a = _write(tmp_path, "plans/design/a.md", "# a\n[b](./b.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n[a](./a.md)\n")
    c = _write(tmp_path, "plans/design/c.md", "# c\n")

    n1, e1 = build_linkmap(tmp_path, ["api"], "design_docs", [a, b, c], [])
    n2, e2 = build_linkmap(tmp_path, ["api"], "design_docs", [c, b, a], [])
    out1 = render_linkmap_json("design_docs", n1, e1)
    out2 = render_linkmap_json("design_docs", n2, e2)
    assert out1 == out2

    # nodes sorted by fpath; edges sorted by (a, b, link_type).
    assert [n.fpath for n in n1] == sorted(n.fpath for n in n1)
    assert [(e.a, e.b, e.link_type) for e in e1] == sorted(
        (e.a, e.b, e.link_type) for e in e1
    )

    doc = json.loads(out1)
    assert doc["depth"] == "design_docs"
    assert {n["fpath"] for n in doc["nodes"]} == {
        "plans/design/a.md",
        "plans/design/b.md",
        "plans/design/c.md",
    }


def test_tokens_heuristic(tmp_path):
    # Divisor calibrated to 2.4 chars/token in mod 168 (was 4).
    text = "x" * 48  # 48 chars → round(48/2.4) = 20
    p = _write(tmp_path, "plans/design/z.md", text)
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/z.md"]
    assert n.tokens == max(1, round(len(text) / 2.4))
    assert n.tokens == 20


def test_tokens_floor_is_one(tmp_path):
    p = _write(tmp_path, "plans/design/empty.md", "")
    nodes, _ = build_linkmap(tmp_path, ["api"], "design_docs", [p], [])
    n = _nodes_by_fpath(nodes)["plans/design/empty.md"]
    assert n.tokens == 1


# ---------------------------------------------------------------------------
# Anchor primitives + doc-extension enumeration (mod 171)
# ---------------------------------------------------------------------------


def test_slug_matches_github_no_collapse():
    # Runs of whitespace are NOT collapsed: each whitespace char -> one hyphen.
    assert _slug("Driven Port / Adapter Patterns") == "driven-port--adapter-patterns"
    # Emoji + variation selector stripped, leaving a leading space -> hyphen.
    assert _slug("⚠️ meta is data").startswith("-")
    # Underscore is a \w char, kept.
    assert _slug("Keeps_Underscore") == "keeps_underscore"


def test_anchors_in_headings_and_dedup(tmp_path):
    p = _write(tmp_path, "plans/design/h.md", "# A\n## A\n### B C\n")
    anchors = anchors_in(p)
    assert "a" in anchors
    assert "a-1" in anchors
    assert "b-c" in anchors


def test_anchors_in_skips_fenced_headings(tmp_path):
    text = "# Real\n\n```\n# Not A Heading\n```\n"
    p = _write(tmp_path, "plans/design/f.md", text)
    anchors = anchors_in(p)
    assert "real" in anchors
    assert "not-a-heading" not in anchors


def test_anchors_in_explicit_id(tmp_path):
    p = _write(
        tmp_path,
        "plans/design/e.md",
        '# Title\n\n<a class="x" id="frozen"></a>\n',
    )
    assert "frozen" in anchors_in(p)


def test_fragment_links_in(tmp_path):
    text = (
        "[x](./other.md#sec)\n"
        "[y](#local)\n"
        "[z](./plain.md)\n"
        "[w](https://h/x#f)\n"
    )
    p = _write(tmp_path, "plans/design/src.md", text)
    frags = fragment_links_in(p)
    assert len(frags) == 2
    resolved = {(target, frag) for target, frag in frags}
    assert ((p.parent / "other.md").resolve(), "sec") in resolved
    assert (p.resolve(), "local") in resolved


def test_enumerate_design_files_doc_exts_only(tmp_path):
    _write(tmp_path, "plans/design/a.md")
    _write(tmp_path, "plans/design/x/diagram.mmd")
    _write(tmp_path, "plans/design/notes.txt")
    _write(tmp_path, "plans/design/x/logo.svg", "<svg/>")
    found = {
        p.relative_to(tmp_path).as_posix() for p in _enumerate_design_files(tmp_path)
    }
    assert found == {
        "plans/design/a.md",
        "plans/design/x/diagram.mmd",
        "plans/design/notes.txt",
    }

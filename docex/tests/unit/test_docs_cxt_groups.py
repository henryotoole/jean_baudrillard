"""Unit tests for ``docex docs cxt_groups`` — context grouping (mod 167).

``build_context_groups`` is pure; tests build small graphs with controlled
``tokens`` (recall ``tokens == max(1, round(len(text)/4))``) via ``build_linkmap``.
"""

from __future__ import annotations

from docex.docs.cxt_groups import (
    build_context_groups,
    render_cxt_groups_json,
    run_docs_cxt_groups,
)
from docex.docs.linkmap import build_linkmap


def _write(root, rel, text="x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _big(n):
    # n tokens ≈ 4n chars.
    return "x" * (4 * n)


# ---------------------------------------------------------------------------
# Core properties: full cover, no repeat, budget
# ---------------------------------------------------------------------------


def test_full_cover_no_repeat_and_budget(tmp_path):
    # A,B share overhead X (100t); C has its own Y (100t). A/B/C small (~2t).
    a = _write(tmp_path, "plans/design/a.md", "# a\n[x](./shared.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n[x](./shared.md)\n")
    c = _write(tmp_path, "plans/design/c.md", "# c\n[y](./own.md)\n")
    x = _write(tmp_path, "plans/design/shared.md", _big(100))
    y = _write(tmp_path, "plans/design/own.md", _big(100))
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [a, b, c, x, y], []
    )
    subjects = ["plans/design/a.md", "plans/design/b.md", "plans/design/c.md"]
    groups, oversize = build_context_groups(nodes, edges, subjects, 130)

    assert oversize == []
    # Full cover, no repeat.
    placed = [fp for g in groups for fp in g.subjects]
    assert sorted(placed) == sorted(subjects)
    assert len(placed) == len(set(placed))
    # Budget respected.
    for g in groups:
        assert g.estimated_tokens <= 130


def test_overlap_clusters_shared_pair(tmp_path):
    a = _write(tmp_path, "plans/design/a.md", "# a\n[x](./shared.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n[x](./shared.md)\n")
    c = _write(tmp_path, "plans/design/c.md", "# c\n[y](./own.md)\n")
    x = _write(tmp_path, "plans/design/shared.md", _big(100))
    y = _write(tmp_path, "plans/design/own.md", _big(100))
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [a, b, c, x, y], []
    )
    subjects = ["plans/design/a.md", "plans/design/b.md", "plans/design/c.md"]
    # 130 fits A+B (share X → 110t) but not A+C (210t).
    groups, _ = build_context_groups(nodes, edges, subjects, 130)

    group_of = {fp: i for i, g in enumerate(groups) for fp in g.subjects}
    assert group_of["plans/design/a.md"] == group_of["plans/design/b.md"]
    assert group_of["plans/design/c.md"] != group_of["plans/design/a.md"]


# ---------------------------------------------------------------------------
# Oversize subject
# ---------------------------------------------------------------------------


def test_oversize_subject_singleton_and_exit_0(tmp_path, capsys, sample_ctx, monkeypatch):
    d = _write(tmp_path, "plans/design/d.md", "# d\n[huge](./huge.md)\n")
    huge = _write(tmp_path, "plans/design/huge.md", _big(1000))
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [d, huge], []
    )
    subjects = ["plans/design/d.md"]
    groups, oversize = build_context_groups(nodes, edges, subjects, 50)
    assert oversize == ["plans/design/d.md"]
    assert len(groups) == 1
    assert groups[0].subjects == ("plans/design/d.md",)

    # Wrapper: exit 0 + stderr warning naming the oversize subject.
    monkeypatch.setattr(
        "docex.docs.cxt_groups.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    rc = run_docs_cxt_groups(sample_ctx, 50, "all")
    assert rc == 0
    err = capsys.readouterr().err
    assert "plans/design/d.md" in err


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism(tmp_path):
    a = _write(tmp_path, "plans/design/a.md", "# a\n[x](./shared.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n[x](./shared.md)\n")
    x = _write(tmp_path, "plans/design/shared.md", _big(50))
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [a, b, x], []
    )
    subjects = ["plans/design/a.md", "plans/design/b.md"]
    g1, _ = build_context_groups(nodes, edges, subjects, 1000)
    g2, _ = build_context_groups(nodes, edges, subjects, 1000)
    out1 = render_cxt_groups_json(1000, "all", g1, nodes)
    out2 = render_cxt_groups_json(1000, "all", g2, nodes)
    assert out1 == out2


# ---------------------------------------------------------------------------
# Wrapper validation + selection
# ---------------------------------------------------------------------------


def test_tokens_max_non_positive_returns_1(capsys, sample_ctx):
    assert run_docs_cxt_groups(sample_ctx, 0, "all") == 1
    assert run_docs_cxt_groups(sample_ctx, -5, "all") == 1
    assert "tokens_max" in capsys.readouterr().err


def test_selection_all_runs(sample_ctx):
    # sample fixture has no plans/design + is not a git repo → empty graph,
    # empty groups, exit 0 with well-formed JSON.
    rc = run_docs_cxt_groups(sample_ctx, 1000, "all")
    assert rc == 0


def test_selection_ref_intersects_changed(tmp_path, sample_ctx, monkeypatch):
    a = _write(tmp_path, "plans/design/a.md", "# a\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n")
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [a, b], []
    )
    monkeypatch.setattr(
        "docex.docs.cxt_groups.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    # changed set names a.md (a real node) + a stray not-a-node path; only the
    # real node survives the intersection.
    monkeypatch.setattr(
        "docex.docs.changed.changed_fpaths",
        lambda root, cbs, ref, git=None: [
            "plans/design/a.md",
            "plans/design/ghost.md",
        ],
    )
    import io
    import json
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_docs_cxt_groups(sample_ctx, 1000, "SOMEREF")
    assert rc == 0
    doc = json.loads(buf.getvalue())
    placed = [
        s["fpath"] for g in doc["groups"] for s in g["subjects"]
    ]
    assert placed == ["plans/design/a.md"]

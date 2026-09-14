"""Unit tests for ``docex docs cxt_groups`` — context grouping (mod 167).

``build_context_groups`` is pure; tests build small graphs with controlled
``tokens`` (recall ``tokens == max(1, round(len(text)/2.4))``) via ``build_linkmap``.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from docex.docs.cxt_groups import (
    ContextGroup,
    build_context_groups,
    build_module_integrity_groups,
    render_cxt_groups_json,
    run_docs_cxt_groups,
)
from docex.docs.linkmap import build_linkmap, load_design_docs_graph


def _write(root, rel, text="x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _big(n):
    # n tokens ≈ 2.4n chars (divisor calibrated to 2.4 in mod 168).
    return "x" * round(2.4 * n)


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


# ===========================================================================
# Mod 175a — --depth
# ===========================================================================


def test_design_docs_depth_excludes_source_subjects(
    tmp_path, sample_ctx, monkeypatch
):
    """175a — at design_docs depth, subjects are exclusively design docs."""
    d = _write(tmp_path, "plans/design/d1.md", "# d1\n")
    # A hex source file that would be a subject at code_level depth.
    _write(tmp_path, "core/api/src/hex/m1/f.py", "x = 1\n")

    # The design_docs graph enumerates only plans/design → zero source nodes.
    nodes, edges = load_design_docs_graph(tmp_path, ["api"])
    assert all(n.type != "source" for n in nodes)

    monkeypatch.setattr(
        "docex.docs.cxt_groups.load_design_docs_graph",
        lambda root, cbs: (nodes, edges),
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_docs_cxt_groups(
            sample_ctx, 100000, "all", depth="design_docs"
        )
    assert rc == 0
    doc = json.loads(buf.getvalue())
    placed = [s["fpath"] for g in doc["groups"] for s in g["subjects"]]
    assert placed  # non-empty
    assert all(fp.startswith("plans/design/") for fp in placed)
    assert not any(fp.startswith("core/") for fp in placed)


def test_default_args_byte_identical(tmp_path, sample_ctx, monkeypatch):
    """175a — omitting the new args == spelling out today's defaults."""
    a = _write(tmp_path, "plans/design/a.md", "# a\n[x](./shared.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n[x](./shared.md)\n")
    x = _write(tmp_path, "plans/design/shared.md", _big(50))
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [a, b, x], []
    )
    monkeypatch.setattr(
        "docex.docs.cxt_groups.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )

    buf1 = io.StringIO()
    with redirect_stdout(buf1):
        rc1 = run_docs_cxt_groups(sample_ctx, 1000, "all")
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        rc2 = run_docs_cxt_groups(
            sample_ctx, 1000, "all", depth="code_level", optimize="tokens"
        )
    assert rc1 == rc2 == 0
    assert buf1.getvalue() == buf2.getvalue()


# ===========================================================================
# Mod 175b — --optimize module_integrity
# ===========================================================================


def _mi_valid(groups, nodes):
    """Module-integrity validity oracle (test-side).

    For every top-level unit (design, each codebase) and, recursively, every
    module of a fragmented codebase: a category fragmented across >1 group
    requires each touching group to contain ONLY that category's files.
    """
    by_fpath = {n.fpath: n for n in nodes}
    group_sets = [set(g.subjects) for g in groups]

    def unit_of(fp):
        n = by_fpath[fp]
        return ("design",) if n.type == "design" else ("cb", n.codebase)

    def check(members: set[str], sibling_pred):
        # members: all files of this category across the whole selection.
        touching = [g for g in group_sets if g & members]
        if len(touching) <= 1:
            return True
        # fragmented → every touching group must be pure to `members`
        for g in touching:
            if g - members:
                return False
        return sibling_pred(touching)

    # design category
    design = {fp for fp in by_fpath if by_fpath[fp].type == "design"}
    design = {fp for g in group_sets for fp in g if fp in design}
    if design and not check(design, lambda ts: True):
        return False
    # codebase categories
    cbs = {by_fpath[fp].codebase for g in group_sets for fp in g
           if by_fpath[fp].type == "source"}
    for cb in cbs:
        members = {fp for g in group_sets for fp in g
                   if by_fpath[fp].type == "source"
                   and by_fpath[fp].codebase == cb}

        def modules_ok(touching, cb=cb):
            mods = {by_fpath[fp].module for fp in members}
            for m in mods:
                mm = {fp for fp in members if by_fpath[fp].module == m}
                tt = [g for g in touching if g & mm]
                if len(tt) > 1 and any(g - mm for g in tt):
                    return False
            return True

        if not check(members, modules_ok):
            return False
    return True


def _mi_fixture(tmp_path):
    """C-1 (m1: f1,f2; m2: f), C-2 (m3: f; m4: f), design (d1, d2).

    Every file ~100 tokens; no standard roots / module docs, so a subject's
    overhead is empty and a set's cost is the sum of its members' tokens.
    """
    m1a = _write(tmp_path, "core/c1/src/hex/m1/f1.py", _big(100))
    m1b = _write(tmp_path, "core/c1/src/hex/m1/f2.py", _big(100))
    m2 = _write(tmp_path, "core/c1/src/hex/m2/f.py", _big(100))
    m3 = _write(tmp_path, "core/c2/src/hex/m3/f.py", _big(100))
    m4 = _write(tmp_path, "core/c2/src/hex/m4/f.py", _big(100))
    d1 = _write(tmp_path, "plans/design/d1.md", _big(100))
    d2 = _write(tmp_path, "plans/design/d2.md", _big(100))
    nodes, edges = build_linkmap(
        tmp_path,
        ["c1", "c2"],
        "code_level",
        [d1, d2],
        [m1a, m1b, m2, m3, m4],
    )
    fp = {
        "m1a": "core/c1/src/hex/m1/f1.py",
        "m1b": "core/c1/src/hex/m1/f2.py",
        "m2": "core/c1/src/hex/m2/f.py",
        "m3": "core/c2/src/hex/m3/f.py",
        "m4": "core/c2/src/hex/m4/f.py",
        "d1": "plans/design/d1.md",
        "d2": "plans/design/d2.md",
    }
    return nodes, edges, fp


def _grp(*subjects):
    return ContextGroup(overhead=(), subjects=tuple(subjects), estimated_tokens=0)


def test_mi_prep_table_oracle(tmp_path):
    """175b — the prep's Module Integrity table, row by row."""
    nodes, _edges, fp = _mi_fixture(tmp_path)

    m1 = [fp["m1a"], fp["m1b"]]          # whole module m1 (2 files)
    m2, m3, m4 = fp["m2"], fp["m3"], fp["m4"]
    design = [fp["d1"], fp["d2"]]

    rows = [
        # (arrangement, expected valid)
        ([_grp(*m1), _grp(m2)], True),                       # row 1
        ([_grp(*m1), _grp(m2, m3)], False),                  # row 2
        ([_grp(fp["m1a"]), _grp(fp["m1b"])], True),          # row 3
        ([_grp(*m1, m2, m3, m4), _grp(*design)], True),      # row 4
        ([_grp(fp["m1a"]), _grp(fp["m1b"], m2)], False),     # row 5
        ([_grp(fp["d1"]), _grp(fp["d2"])], True),            # row 6
    ]
    for i, (groups, expected) in enumerate(rows, start=1):
        assert _mi_valid(groups, nodes) is expected, f"row {i}"


def test_mi_algorithm_valid_partition_and_targets(tmp_path):
    """175b — the packer emits a valid partition at every budget + hits targets."""
    nodes, edges, fp = _mi_fixture(tmp_path)
    subjects = sorted(fp.values())

    def placed(groups):
        return [s for g in groups for s in g.subjects]

    # (a) huge budget → one group holding everything.
    huge, _ = build_module_integrity_groups(nodes, edges, subjects, 100000)
    assert sorted(placed(huge)) == subjects
    assert len(placed(huge)) == len(set(placed(huge)))  # no repeat
    assert _mi_valid(huge, nodes)
    assert len(huge) == 1

    # (b) medium budget (250): c1 (300t) fragments on module lines; c2 (200t)
    #     and design (200t) each stay whole.
    med, _ = build_module_integrity_groups(nodes, edges, subjects, 250)
    assert sorted(placed(med)) == subjects
    assert len(placed(med)) == len(set(placed(med)))
    assert _mi_valid(med, nodes)
    group_of = {s: i for i, g in enumerate(med) for s in g.subjects}
    # (c) c2 fits whole → not split.
    assert group_of[fp["m3"]] == group_of[fp["m4"]]
    # (d) whole module m1 shares a group pure to c1.
    assert group_of[fp["m1a"]] == group_of[fp["m1b"]]
    m1_group = next(g for g in med if fp["m1a"] in g.subjects)
    by_fpath = {n.fpath: n for n in nodes}
    assert all(
        by_fpath[s].type == "source" and by_fpath[s].codebase == "c1"
        for s in m1_group.subjects
    )

    # (tiny) budget → single-file groups.
    tiny, _ = build_module_integrity_groups(nodes, edges, subjects, 50)
    assert sorted(placed(tiny)) == subjects
    assert len(placed(tiny)) == len(set(placed(tiny)))
    assert _mi_valid(tiny, nodes)
    assert all(len(g.subjects) == 1 for g in tiny)


def test_mi_oversize_exit_0_and_note(tmp_path, capsys, sample_ctx, monkeypatch):
    """175b — an oversize subject stays exit 0 with a stderr note."""
    d = _write(tmp_path, "plans/design/d.md", "# d\n[huge](./huge.md)\n")
    huge = _write(tmp_path, "plans/design/huge.md", _big(1000))
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [d, huge], []
    )
    groups, oversize = build_module_integrity_groups(
        nodes, edges, ["plans/design/d.md"], 50
    )
    assert oversize == ["plans/design/d.md"]
    assert len(groups) == 1
    assert groups[0].subjects == ("plans/design/d.md",)

    monkeypatch.setattr(
        "docex.docs.cxt_groups.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    rc = run_docs_cxt_groups(
        sample_ctx, 50, "all", optimize="module_integrity"
    )
    assert rc == 0
    assert "plans/design/d.md" in capsys.readouterr().err


def test_mi_composes_with_design_docs_depth(tmp_path, sample_ctx, monkeypatch):
    """175b — --depth design_docs --optimize module_integrity (SC 175b.4)."""
    d1 = _write(tmp_path, "plans/design/d1.md", _big(100))
    d2 = _write(tmp_path, "plans/design/d2.md", _big(100))
    nodes, edges = load_design_docs_graph(tmp_path, ["api"])
    monkeypatch.setattr(
        "docex.docs.cxt_groups.load_design_docs_graph",
        lambda root, cbs: (nodes, edges),
    )

    # Fits → exactly one group, all design docs.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_docs_cxt_groups(
            sample_ctx, 100000, "all",
            depth="design_docs", optimize="module_integrity",
        )
    assert rc == 0
    doc = json.loads(buf.getvalue())
    assert len(doc["groups"]) == 1
    placed = [s["fpath"] for s in doc["groups"][0]["subjects"]]
    assert sorted(placed) == ["plans/design/d1.md", "plans/design/d2.md"]

    # Small budget → multiple groups, each design-only.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_docs_cxt_groups(
            sample_ctx, 150, "all",
            depth="design_docs", optimize="module_integrity",
        )
    assert rc == 0
    doc = json.loads(buf.getvalue())
    assert len(doc["groups"]) > 1
    for g in doc["groups"]:
        for s in g["subjects"]:
            assert s["fpath"].startswith("plans/design/")


def test_optimize_tokens_byte_identical(tmp_path, sample_ctx, monkeypatch):
    """175b — --optimize tokens (default) is byte-identical to today."""
    a = _write(tmp_path, "plans/design/a.md", "# a\n[x](./shared.md)\n")
    b = _write(tmp_path, "plans/design/b.md", "# b\n[x](./shared.md)\n")
    c = _write(tmp_path, "plans/design/c.md", "# c\n[y](./own.md)\n")
    x = _write(tmp_path, "plans/design/shared.md", _big(100))
    y = _write(tmp_path, "plans/design/own.md", _big(100))
    nodes, edges = build_linkmap(
        tmp_path, ["api"], "code_level", [a, b, c, x, y], []
    )
    subjects = sorted(
        n.fpath for n in nodes if n.type in ("design", "source")
    )
    expected = render_cxt_groups_json(
        130, "all", build_context_groups(nodes, edges, subjects, 130)[0], nodes
    )

    monkeypatch.setattr(
        "docex.docs.cxt_groups.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_docs_cxt_groups(sample_ctx, 130, "all", optimize="tokens")
    assert rc == 0
    assert buf.getvalue().rstrip("\n") == expected

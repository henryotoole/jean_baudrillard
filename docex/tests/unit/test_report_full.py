"""Unit tests for docex report docs --format full (mod 177).

The renderer consumes mod 176's ``data`` bucket tree; these tests build that
tree git-free via ``build_linkmap`` (as ``test_report_docs.py`` does), then
exercise the pure layout helpers and the assembled HTML.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout, redirect_stderr

from docex.docs.linkmap import build_linkmap
from docex.report.docs import build_docs_data
from docex.report.full import (
    code_treemap_targets,
    layout_code_treemap,
    layout_comparison,
    layout_doc_treemap,
    render_full_html,
)
from docex.report import run_report


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _corpus(tmp_path):
    """A representative design + source corpus (mirrors test_report_docs)."""
    design = []
    design.append(
        _write(
            tmp_path,
            "plans/design/boundary_conditions.md",
            "Preamble line one.\nPreamble line two.\n"
            "# Intro and Goals\nbody body body body\n"
            "# Constraints\nmore body here\n",
        )
    )
    design.append(
        _write(tmp_path, "plans/design/lexicon.md", "# Project Lexicon\nx\n")
    )
    design.append(_write(tmp_path, "plans/design/adr_index.md", "# idx\n"))
    design.append(_write(tmp_path, "plans/design/adr_active.md", "# active\n"))
    design.append(
        _write(tmp_path, "plans/design/project_diagram.mmd", "graph TD\nA-->B\n")
    )
    design.append(_write(tmp_path, "plans/design/unknowns.md", "# Unknowns\n"))
    design.append(
        _write(tmp_path, "plans/design/quality_scenarios.md", "# Q\n")
    )
    design.append(
        _write(tmp_path, "plans/design/doctrine_ext.md", "# ext (other file)\n")
    )
    design.append(
        _write(tmp_path, "plans/design/specifics/thing.md", "# thing\ndetail\n")
    )
    design.append(_write(tmp_path, "plans/design/adrs/0001_a.md", "# ADR 1\n"))
    design.append(_write(tmp_path, "plans/design/adrs/0002_b.md", "# ADR 2\n"))
    design.append(
        _write(tmp_path, "plans/design/api/module_diagram.mmd", "graph TD\n")
    )
    design.append(
        _write(tmp_path, "plans/design/api/specifics/c1.md", "# c1\ndetail\n")
    )
    design.append(
        _write(tmp_path, "plans/design/api/module/mod1.md", "# mod1\nbody\n")
    )

    source = []
    source.append(
        _write(
            tmp_path,
            "core/api/src/hex/m1/f.py",
            '"""doc referencing core/api/src/hex/m1/f.py"""\n'
            "# inline\nx = 1\n",
        )
    )
    source.append(_write(tmp_path, "core/api/src/app.py", "# root file\ny = 2\n"))
    source.append(
        _write(tmp_path, "core/frontend/src/index.js", "// c\nconst a = 1;\n")
    )
    source.append(_write(tmp_path, "core/api/src/misc.rst", "unlintable prose\n"))

    nodes, edges = build_linkmap(
        tmp_path, ["api", "frontend"], "code_level", design, source
    )
    return nodes, edges


def _doc(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    return build_docs_data(nodes, tmp_path)


# --- assembled-HTML tests ---------------------------------------------------


def test_full_html_has_three_sections(tmp_path):
    html = render_full_html(_doc(tmp_path))
    # Single HTML document.
    assert html.lower().count("<!doctype") == 1
    assert html.lower().count("</html>") == 1
    # Three headings, in order.
    i1 = html.index("Code-Doc Comparison")
    i2 = html.index("Doc Treemap")
    i3 = html.index("Code Treemap")
    assert i1 < i2 < i3
    # Contains inline SVG.
    assert "<svg" in html


def test_full_has_no_external_refs(tmp_path):
    html = render_full_html(_doc(tmp_path))
    low = html.lower()
    assert "http://" not in low
    assert "https://" not in low
    assert "src=" not in low
    assert "<link" not in low
    assert "<img" not in low
    # No xmlns on the inline svg (keeps the no-http self-containment guarantee).
    assert "xmlns" not in low


def test_full_determinism(tmp_path):
    doc = _doc(tmp_path)
    assert render_full_html(doc) == render_full_html(doc)


# --- layout tests -----------------------------------------------------------


def test_comparison_area_traces_to_data(tmp_path):
    doc = _doc(tmp_path)
    rects = layout_comparison(doc, 800, 600)
    assert len(rects) == 2
    design_t = doc["design_docs"]["tokens"]
    source_t = doc["source_code"]["tokens"]
    dw = rects[0].w
    sw = rects[1].w
    # Widths ∝ token weights (equal full height → area ∝ weight).
    assert abs(dw / (dw + sw) - design_t / (design_t + source_t)) < 1e-6
    # Full height, side by side.
    assert rects[0].h == 600 and rects[1].h == 600
    assert abs(rects[1].x - rects[0].w) < 1e-6


def test_doc_treemap_adr_band_and_primaries(tmp_path):
    doc = _doc(tmp_path)
    design = doc["design_docs"]
    W, H = 800, 600
    rects = layout_doc_treemap(design, W, H)

    # (a) exactly one full-width ADR band, beneath the top band.
    adr = [r for r in rects if r.kind == "adr"]
    assert len(adr) == 1
    adr = adr[0]
    assert abs(adr.w - W) < 1e-6
    assert adr.x == 0

    # Primary frames: rects whose label is one of the four primary names.
    prim_names = (
        "L1 Standard Roots",
        "L1 Detail Docs",
        "L2 Architecture Docs",
        "L3 Module Docs",
    )
    frames = [r for r in rects if r.label in prim_names and r.y == 0]
    assert len(frames) == 4
    Ht = frames[0].h
    # The ADR band sits directly beneath the top band.
    assert abs(adr.y - Ht) < 1e-6

    # (b) frame widths ∝ their tokens.
    total_w = sum(f.w for f in frames)
    total_t = sum(f.tokens for f in frames)
    for f in frames:
        assert abs(f.w / total_w - f.tokens / total_t) < 1e-6

    # (c) ADR band height / total ≈ adr_tokens / design_tokens.
    adr_tokens = adr.tokens
    design_tokens = design["tokens"]
    assert abs(adr.h / H - adr_tokens / design_tokens) < 1e-6

    # Canonical L→R order of the frames.
    ordered = sorted(frames, key=lambda r: r.x)
    assert [r.label for r in ordered] == list(prim_names)


def test_code_treemap_per_codebase_and_module(tmp_path):
    doc = _doc(tmp_path)
    targets = code_treemap_targets(doc["source_code"])
    titles = [t for t, _ in targets]
    # One per codebase and one per hex module; no synthetic (root) target.
    assert "api" in titles
    assert "frontend" in titles
    assert "api / m1" in titles
    assert not any("(root)" in t for t in titles)

    # Codebases emitted before modules (deterministic).
    assert titles.index("api") < titles.index("api / m1")
    assert titles.index("frontend") < titles.index("api / m1")

    leaves = dict(targets)["api"]
    S = 300
    rects = layout_code_treemap(leaves, S)
    by_label = {r.label: r for r in rects}

    other = by_label["other / unlintable"]
    code = by_label["code"]
    inline = by_label["inline comments"]
    docstr = by_label["docstrings"]
    refs = by_label["references"]

    # code and other are full-width horizontal bands; other is bottom-most.
    assert abs(code.w - S) < 1e-6
    assert abs(other.w - S) < 1e-6
    assert other.y >= code.y

    # top three slices share the top band's y and their widths ∝ weights.
    assert inline.y == docstr.y == refs.y
    top = [inline, docstr, refs]
    total_w = sum(r.w for r in top)
    total_t = sum(r.tokens for r in top)
    for r in top:
        assert abs(r.w / total_w - r.tokens / total_t) < 1e-6


# --- wrapper tests ----------------------------------------------------------


def test_full_default_renders_via_wrapper(tmp_path, sample_ctx, monkeypatch):
    nodes, edges = _corpus(tmp_path)
    monkeypatch.setattr(
        "docex.report.docs.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = run_report(sample_ctx, "docs", "full")
    assert rc == 0
    html = out.getvalue()
    assert html.lstrip().lower().startswith("<!doctype")
    for heading in ("Code-Doc Comparison", "Doc Treemap", "Code Treemap"):
        assert heading in html
    # The old stub stderr note is gone.
    assert err.getvalue() == ""


def test_full_empty_project_ok(sample_ctx):
    # sample fixture has no plans/design and is not a git repo → empty graph.
    out = io.StringIO()
    with redirect_stdout(out):
        rc = run_report(sample_ctx, "docs", "full")
    assert rc == 0
    html = out.getvalue()
    for heading in ("Code-Doc Comparison", "Doc Treemap", "Code Treemap"):
        assert heading in html

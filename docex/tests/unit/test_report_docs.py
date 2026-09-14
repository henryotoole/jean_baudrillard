"""Unit tests for docex report docs --format data (mod 176).

Fixture corpus built in tmp_path; the graph is built git-free via
``build_linkmap`` (as the cxt_groups tests do), so no repo is needed.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from docex.docs.linkmap import build_linkmap
from docex.report.docs import Bucket, build_docs_data, render_data_json
from docex.report import run_report


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _corpus(tmp_path):
    """A representative design + source corpus.

    ``boundary_conditions.md`` carries a deliberate preamble before its first
    ``#`` heading so its arc42 bucket needs an explicit ``etc`` remainder.
    """
    design = []
    bc = _write(
        tmp_path,
        "plans/design/boundary_conditions.md",
        "Preamble line one.\nPreamble line two.\n"
        "# Intro and Goals\nbody body body body\n"
        "# Constraints\nmore body here\n",
    )
    design.append(bc)
    design.append(_write(tmp_path, "plans/design/lexicon.md", "# Project Lexicon\nx\n"))
    design.append(_write(tmp_path, "plans/design/adr_index.md", "# idx\n"))
    design.append(_write(tmp_path, "plans/design/adr_active.md", "# active\n"))
    design.append(_write(tmp_path, "plans/design/project_diagram.mmd", "graph TD\nA-->B\n"))
    design.append(_write(tmp_path, "plans/design/unknowns.md", "# Unknowns\n"))
    design.append(_write(tmp_path, "plans/design/quality_scenarios.md", "# Q\n"))
    design.append(_write(tmp_path, "plans/design/doctrine_ext.md", "# ext (other file)\n"))
    design.append(_write(tmp_path, "plans/design/specifics/thing.md", "# thing\ndetail\n"))
    design.append(_write(tmp_path, "plans/design/adrs/0001_a.md", "# ADR 1\n"))
    design.append(_write(tmp_path, "plans/design/adrs/0002_b.md", "# ADR 2\n"))
    design.append(_write(tmp_path, "plans/design/api/module_diagram.mmd", "graph TD\n"))
    design.append(_write(tmp_path, "plans/design/api/specifics/c1.md", "# c1\ndetail\n"))
    design.append(_write(tmp_path, "plans/design/api/module/mod1.md", "# mod1\nbody\n"))

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


def _assert_sums(bucket: dict):
    """Recursively: a bucket's children (incl. etc) sum to its own tokens."""
    kids = bucket.get("children")
    if not kids:
        return
    assert sum(k["tokens"] for k in kids) == bucket["tokens"], bucket["name"]
    for k in kids:
        _assert_sums(k)


def _find(bucket: dict, name: str):
    if bucket.get("name") == name:
        return bucket
    for k in bucket.get("children", []):
        hit = _find(k, name)
        if hit is not None:
            return hit
    return None


def test_bucket_sums_hold_everywhere(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    _assert_sums(doc["design_docs"])
    _assert_sums(doc["source_code"])


def test_etc_invariant_on_arc42_preamble(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    bc = _find(doc["design_docs"], "boundary_conditions.md")
    assert bc is not None
    names = [k["name"] for k in bc["children"]]
    # Named arc42 sections present…
    assert "Intro and Goals" in names
    assert "Constraints" in names
    # …plus an explicit etc for the preamble remainder.
    etc = _find(bc, "etc")
    assert etc is not None and etc["tokens"] > 0


def test_design_primary_buckets_present(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    for primary in (
        "L1 Standard Roots",
        "L1 Detail Docs",
        "L2 Architecture Docs",
        "L3 Module Docs",
        "ADRs",
    ):
        assert _find(doc["design_docs"], primary) is not None
    # ADRs is a summed leaf (no children).
    adrs = _find(doc["design_docs"], "ADRs")
    assert "children" not in adrs and adrs["tokens"] > 0
    # doctrine_ext.md lands in L1 Detail Docs → Other Files.
    other = _find(_find(doc["design_docs"], "L1 Detail Docs"), "Other Files")
    assert other is not None
    assert any(k["name"] == "doctrine_ext.md" for k in other["children"])


def test_source_hex_module_tier_and_nonhex_flat(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    api = _find(doc["source_code"], "api")
    # hex module m1 present as a tier; the non-hex app.py under "(root)".
    assert _find(api, "m1") is not None
    assert _find(api, "(root)") is not None
    # frontend is non-hex → files attach directly (no module group).
    frontend = _find(doc["source_code"], "frontend")
    assert any(k["name"] == "index.js" for k in frontend["children"])
    # References were detected in the python module file.
    f = _find(api, "f.py")
    refs = _find(f, "references")
    assert refs is not None and refs["tokens"] > 0
    # The .rst under src is unlintable → its weight is entirely other.
    misc = _find(api, "misc.rst")
    assert misc is not None
    other = _find(misc, "other / unlintable")
    assert other["tokens"] == misc["tokens"] and misc["tokens"] > 0


def test_determinism(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    out1 = render_data_json(build_docs_data(nodes, tmp_path))
    out2 = render_data_json(build_docs_data(nodes, tmp_path))
    assert out1 == out2


def test_run_report_docs_data_via_wrapper(tmp_path, sample_ctx, monkeypatch):
    nodes, edges = _corpus(tmp_path)
    monkeypatch.setattr(
        "docex.report.docs.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_report(sample_ctx, "docs", "data")
    assert rc == 0
    doc = json.loads(buf.getvalue())
    assert doc["report"] == "docs" and doc["format"] == "data"
    _assert_sums(doc["design_docs"])
    _assert_sums(doc["source_code"])


def test_full_stubs_to_data_with_note(tmp_path, sample_ctx, capsys, monkeypatch):
    nodes, edges = _corpus(tmp_path)
    monkeypatch.setattr(
        "docex.report.docs.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    rc = run_report(sample_ctx, "docs", "full")
    assert rc == 0
    captured = capsys.readouterr()
    assert "mod 177" in captured.err            # stub note on stderr
    doc = json.loads(captured.out)              # data JSON on stdout
    assert doc["format"] == "data"


def test_empty_project_ok(sample_ctx):
    # sample fixture has no plans/design and is not a git repo → empty graph.
    rc = run_report(sample_ctx, "docs", "data")
    assert rc == 0

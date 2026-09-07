"""Unit tests for ``docex docs adr`` — ADR index generation + staleness (mod 161)."""

from __future__ import annotations

import pytest

from docex.docs.adr import (
    GENERATED_MARKER,
    adr_index_drift,
    load_adrs,
    parse_adr,
    regenerate_adr_indexes,
    render_active,
    render_index,
)
from docex.docs.scaffold import scaffold_design
from docex.docs.check import check_docs


def _write_adr(
    adrs_dir, fname, *, id, title, status,
    date="2026-01-01", supersedes="[]", superseded_by="[]", tags="[]",
):
    adrs_dir.mkdir(parents=True, exist_ok=True)
    (adrs_dir / fname).write_text(
        "---\n"
        f"id: {id}\n"
        f"title: {title}\n"
        f"status: {status}\n"
        f"date: {date}\n"
        f"supersedes: {supersedes}\n"
        f"superseded-by: {superseded_by}\n"
        f"tags: {tags}\n"
        "---\n\n## Context\n...\n"
    )


def _adrs_dir(tmp_path):
    return tmp_path / "plans" / "design" / "adrs"


def test_parse_preserves_zero_padded_id(tmp_path):
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0004_thing.md", id="0004", title="thing", status="accepted")
    adr = parse_adr(d / "0004_thing.md")
    assert adr.id == "0004"          # not int-coerced to "4"
    assert adr.title == "thing"
    assert adr.status == "accepted"
    assert adr.date == "2026-01-01"
    assert adr.filename == "0004_thing.md"   # real on-disk name (mod 170)


def test_parse_id_list_fields(tmp_path):
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0005_x.md", id="0005", title="x", status="superseded",
               superseded_by="[0006]", supersedes="[0002, 0003]")
    adr = parse_adr(d / "0005_x.md")
    assert adr.supersedes == ("0002", "0003")
    assert adr.superseded_by == ("0006",)


def test_active_excludes_non_accepted_and_superseded(tmp_path):
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0001_a.md", id="0001", title="a", status="accepted")
    _write_adr(d, "0002_b.md", id="0002", title="b", status="proposed")
    _write_adr(d, "0003_c.md", id="0003", title="c", status="rejected")
    _write_adr(d, "0004_d.md", id="0004", title="d", status="deprecated")
    _write_adr(d, "0005_e.md", id="0005", title="e", status="superseded")
    # accepted-but-superseded-by-populated is also excluded.
    _write_adr(d, "0006_f.md", id="0006", title="f", status="accepted",
               superseded_by="[0007]")
    adrs = load_adrs(tmp_path)
    active = render_active(adrs)
    assert "[0001](adrs/0001_a.md)" in active
    for excluded in ("0002", "0003", "0004", "0005", "0006"):
        assert f"[{excluded}]" not in active


def test_index_lists_all_and_renders_supersede_chain(tmp_path):
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0001_old.md", id="0001", title="old", status="superseded",
               superseded_by="[0002]")
    _write_adr(d, "0002_new.md", id="0002", title="new", status="accepted",
               supersedes="[0001]")
    index = render_index(load_adrs(tmp_path))
    assert index.startswith(GENERATED_MARKER)
    assert (
        "| [0001](adrs/0001_old.md) | old | superseded | 2026-01-01 |  | 0002 |"
        in index
    )
    assert (
        "| [0002](adrs/0002_new.md) | new | accepted | 2026-01-01 | 0001 |  |"
        in index
    )


def test_sorted_by_id(tmp_path):
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0010_j.md", id="0010", title="j", status="accepted")
    _write_adr(d, "0002_b.md", id="0002", title="b", status="accepted")
    index = render_index(load_adrs(tmp_path))
    assert index.index("[0002](adrs/0002_b.md)") < index.index(
        "[0010](adrs/0010_j.md)"
    )


def test_empty_adrs_case(tmp_path):
    # No adrs dir at all -> header-only tables, still valid.
    index = render_index(load_adrs(tmp_path))
    active = render_active(load_adrs(tmp_path))
    assert index.startswith(GENERATED_MARKER)
    assert "# ADR Index" in index
    assert active.startswith(GENERATED_MARKER)
    assert "# Active ADRs" in active
    # No data rows.
    assert index.count("\n|") == 2  # header + separator only
    assert active.count("\n|") == 2


def test_regenerate_and_idempotency(tmp_path):
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0001_a.md", id="0001", title="a", status="accepted")
    written = regenerate_adr_indexes(tmp_path)
    assert set(written) == {"plans/design/adr_index.md",
                            "plans/design/adr_active.md"}
    # Second run: byte-identical -> nothing rewritten.
    assert regenerate_adr_indexes(tmp_path) == []
    idx = (tmp_path / "plans" / "design" / "adr_index.md").read_text()
    assert "| [0001](adrs/0001_a.md) | a | accepted |" in idx


def test_drift_detection(tmp_path):
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0001_a.md", id="0001", title="a", status="accepted")
    regenerate_adr_indexes(tmp_path)
    assert adr_index_drift(tmp_path) == []          # freshly generated -> clean
    idx = tmp_path / "plans" / "design" / "adr_index.md"
    idx.write_text(idx.read_text() + "| 9999 | tampered | x | y |  |  |\n")
    problems = adr_index_drift(tmp_path)
    assert any("adr_index.md" in p for p in problems)


def test_drift_silent_when_index_missing(tmp_path):
    # No index files on disk -> drift stays silent (missing_standard_files owns
    # that miss). adrs dir absent -> treated as empty set.
    assert adr_index_drift(tmp_path) == []


def test_fresh_scaffold_passes_staleness(tmp_path):
    scaffold_design(tmp_path, ["api"])
    assert adr_index_drift(tmp_path) == []
    # And the full docs check (which now includes drift) is clean.
    assert check_docs(tmp_path, ["api"]) == 0


def test_check_docs_flags_drift(tmp_path):
    scaffold_design(tmp_path, ["api"])
    idx = tmp_path / "plans" / "design" / "adr_index.md"
    idx.write_text(idx.read_text() + "| 9999 | tamper | x | y |  |  |\n")
    assert check_docs(tmp_path, ["api"]) == 1


def test_cmd_docs_adr_routes(monkeypatch, sample_ctx):
    from docex.__main__ import _cmd_docs

    monkeypatch.chdir(sample_ctx.project_root)
    seen = {}

    def fake(ctx):
        seen["adr"] = ctx
        return 0

    monkeypatch.setattr("docex.docs.run_docs_adr", fake)
    assert _cmd_docs(["adr"]) == 0
    assert "adr" in seen


def test_id_cell_is_linked_to_adr_file(tmp_path):
    # The ADR id cell is a markdown link to the ADR's source file, in BOTH
    # indexes (mod 170 success criterion 1).
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0001_thing.md", id="0001", title="thing", status="accepted")
    adrs = load_adrs(tmp_path)
    link = "[0001](adrs/0001_thing.md)"
    assert link in render_index(adrs)
    assert link in render_active(adrs)


def test_link_target_is_real_filename_not_derived_from_title(tmp_path):
    # The link target is the real on-disk filename, NOT a slug derived from the
    # human title — so it can never drift from the file it points at (mod 170
    # design decision 2). Human title differs from the snake_case filename stem.
    d = _adrs_dir(tmp_path)
    _write_adr(
        d, "0007_use_postgres.md",
        id="0007", title="Use Postgres for storage", status="accepted",
    )
    idx = render_index(load_adrs(tmp_path))
    assert "[0007](adrs/0007_use_postgres.md)" in idx        # real filename
    assert "use-postgres-for-storage" not in idx             # not a title slug
    assert "| Use Postgres for storage |" in idx             # title stays bare

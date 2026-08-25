"""Unit tests for the ``.docex/checks/`` provenance artifact (Mod 150).

The record is a performance cache: every read must degrade safely to ``None`` so
a missing/corrupt record forces ``merge`` to run the full recheck.
"""

from __future__ import annotations

from docex.pipeline import check_record
from docex.pipeline.check_record import (
    CheckRecord,
    checks_dir,
    read_check_record,
    record_path,
    write_check_record,
)


def _sample_record(**overrides) -> CheckRecord:
    base = dict(
        feature_tip="feat0001deadbeef",
        origin_main="trunk0002cafef00d",
        merged_tree_sha="tree0003abc12345",
        checked_at="2026-08-25T00:00:00+00:00",
        docex_version="0.5.0",
    )
    base.update(overrides)
    return CheckRecord(**base)


def test_round_trip(tmp_path):
    rec = _sample_record()
    write_check_record(tmp_path, rec)
    got = read_check_record(tmp_path)
    assert got == rec
    # All five fields survive.
    assert got.feature_tip == rec.feature_tip
    assert got.origin_main == rec.origin_main
    assert got.merged_tree_sha == rec.merged_tree_sha
    assert got.checked_at == rec.checked_at
    assert got.docex_version == rec.docex_version


def test_missing_dir_returns_none(tmp_path):
    # Fresh dir: no .docex/checks/ at all.
    assert read_check_record(tmp_path) is None


def test_missing_file_returns_none(tmp_path):
    checks_dir(tmp_path).mkdir(parents=True)
    # Dir exists but latest.json absent.
    assert read_check_record(tmp_path) is None


def test_corrupt_json_returns_none(tmp_path):
    checks_dir(tmp_path).mkdir(parents=True)
    record_path(tmp_path).write_text("{ not json")
    assert read_check_record(tmp_path) is None


def test_partial_json_returns_none(tmp_path):
    checks_dir(tmp_path).mkdir(parents=True)
    record_path(tmp_path).write_text('{"feature_tip": "x"}')
    assert read_check_record(tmp_path) is None


def test_atomic_overwrite_leaves_no_temp_files(tmp_path):
    a = _sample_record(feature_tip="AAAA")
    b = _sample_record(feature_tip="BBBB")
    write_check_record(tmp_path, a)
    write_check_record(tmp_path, b)
    got = read_check_record(tmp_path)
    assert got is not None and got.feature_tip == "BBBB"
    # No leftover .latest.json.*.tmp files.
    leftovers = [
        p.name
        for p in checks_dir(tmp_path).iterdir()
        if p.name.startswith(".") and p.name.endswith(".tmp")
    ]
    assert leftovers == [], leftovers

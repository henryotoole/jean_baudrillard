"""Unit tests for the on-disk run record (Mod 148)."""

from __future__ import annotations

import time

import pytest

from docex.jobs import record
from docex.jobs.record import Outcome, RunMeta, RunStatus


def _meta(run_id: str, *, vessel="sample-test-runner") -> RunMeta:
    return RunMeta(
        id=run_id,
        kind="test",
        scope="sample/test",
        slot=1,
        vessel_kind="container",
        vessel_name=vessel,
        created_at=record.now_iso(),
        docex_version="0.5.0",
        params={},
    )


# ---------------------------------------------------------------------------
# run ids
# ---------------------------------------------------------------------------


def test_new_run_id_is_unique_and_well_formed():
    ids = [record.new_run_id() for _ in range(50)]
    assert len(set(ids)) == 50, "run ids must be collision-free within a second"
    # Shape: <UTC timestamp>-<6 hex>. The timestamp prefix is what makes them
    # lexicographically sortable by recency (ordering is asserted across a
    # second boundary in test_new_run_id_orders_by_time).
    for rid in ids:
        stamp, sep, suffix = rid.partition("-")
        assert sep == "-"
        assert len(stamp) == len("YYYYMMDDThhmmssZ") and stamp.endswith("Z")
        assert len(suffix) == 6 and int(suffix, 16) >= 0


def test_new_run_id_orders_by_time():
    a = record.new_run_id()
    time.sleep(1.01)  # cross a whole-second boundary
    b = record.new_run_id()
    assert b > a


# ---------------------------------------------------------------------------
# record creation + meta/status round-trips
# ---------------------------------------------------------------------------


def test_create_record_writes_meta_and_launching_status(tmp_path):
    rid = record.new_run_id()
    d = record.create_record(tmp_path, _meta(rid))
    assert d.is_dir()
    meta = record.read_meta(tmp_path, rid)
    assert meta is not None and meta.id == rid and meta.kind == "test"
    status = record.read_status(tmp_path, rid)
    assert status is not None and status.state == "launching"


def test_meta_json_round_trip():
    m = _meta("20260824T000000Z-abcdef")
    assert RunMeta.from_json(m.to_json()) == m


def test_write_and_read_status(tmp_path):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    record.write_status(
        tmp_path, rid,
        RunStatus(state="running", started_at="t0"),
    )
    s = record.read_status(tmp_path, rid)
    assert s.state == "running"
    assert s.started_at == "t0"
    assert s.updated_at is not None  # bumped by write_status


def test_read_meta_and_status_none_when_absent(tmp_path):
    assert record.read_meta(tmp_path, "nope") is None
    assert record.read_status(tmp_path, "nope") is None


def test_read_meta_none_on_unreadable(tmp_path):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    (record.run_dir(tmp_path, rid) / "meta.json").write_text("{ not json")
    assert record.read_meta(tmp_path, rid) is None


# ---------------------------------------------------------------------------
# exit file — atomic write + parse
# ---------------------------------------------------------------------------


def test_write_exit_atomic_round_trip(tmp_path):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    assert record.read_exit(tmp_path, rid) is None
    record.write_exit_atomic(tmp_path, rid, 7)
    assert record.read_exit(tmp_path, rid) == 7


def test_write_exit_atomic_leaves_no_temp_file(tmp_path):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    record.write_exit_atomic(tmp_path, rid, 0)
    leftovers = [
        p.name for p in record.run_dir(tmp_path, rid).iterdir()
        if p.name.startswith(".exit")
    ]
    assert leftovers == [], "the temp file must be renamed onto 'exit', not left"


def test_read_exit_none_on_garbage(tmp_path):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    record.exit_path(tmp_path, rid).write_text("not-a-number")
    assert record.read_exit(tmp_path, rid) is None


# ---------------------------------------------------------------------------
# list_run_ids
# ---------------------------------------------------------------------------


def test_list_run_ids_descending(tmp_path):
    ids = []
    for _ in range(3):
        rid = record.new_run_id()
        record.create_record(tmp_path, _meta(rid))
        ids.append(rid)
        time.sleep(1.01)
    assert record.list_run_ids(tmp_path) == sorted(ids, reverse=True)


def test_list_run_ids_empty_when_no_dir(tmp_path):
    assert record.list_run_ids(tmp_path) == []


# ---------------------------------------------------------------------------
# classify — the shared primitive
# ---------------------------------------------------------------------------


def test_classify_terminal_when_exit_present(tmp_path, fake_docker):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    record.write_exit_atomic(tmp_path, rid, 0)
    # Even if the vessel still reports running, exit wins.
    fake_docker.container_running_results["sample-test-runner"] = True
    assert record.classify(tmp_path, rid, fake_docker) is Outcome.TERMINAL


def test_classify_live_when_vessel_running(tmp_path, fake_docker):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    fake_docker.container_running_results["sample-test-runner"] = True
    assert record.classify(tmp_path, rid, fake_docker) is Outcome.LIVE


def test_classify_orphan_when_vessel_dead(tmp_path, fake_docker):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    fake_docker.container_running_results["sample-test-runner"] = False
    assert record.classify(tmp_path, rid, fake_docker) is Outcome.ORPHAN


def test_classify_orphan_when_vessel_absent(tmp_path, fake_docker):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    # default container_running → None (absent)
    assert record.classify(tmp_path, rid, fake_docker) is Outcome.ORPHAN


def test_classify_orphan_when_meta_unreadable(tmp_path, fake_docker):
    rid = record.new_run_id()
    record.create_record(tmp_path, _meta(rid))
    (record.run_dir(tmp_path, rid) / "meta.json").write_text("garbage{")
    assert record.classify(tmp_path, rid, fake_docker) is Outcome.ORPHAN

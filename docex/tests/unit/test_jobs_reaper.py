"""Unit tests for the single-run self-heal reaper (Mod 148)."""

from __future__ import annotations

import pytest

from docex.jobs import record, reaper


_VESSEL = "sample-test-runner"
_SCOPE = "sample/test"


def _seed_record(ctx, *, with_exit: int | None) -> str:
    rid = record.new_run_id()
    record.create_record(
        ctx.project_root,
        record.RunMeta(
            id=rid, kind="test", scope=_SCOPE, slot=1,
            vessel_kind="container", vessel_name=_VESSEL,
            created_at=record.now_iso(), docex_version="0.5.0", params={},
        ),
    )
    record.write_status(
        ctx.project_root, rid, record.RunStatus(state="running")
    )
    if with_exit is not None:
        record.write_exit_atomic(ctx.project_root, rid, with_exit)
    return rid


def test_running_vessel_refuses_without_touching_it(sample_ctx, fake_docker):
    fake_docker.container_running_results[_VESSEL] = True
    pf = reaper.preflight(
        sample_ctx, fake_docker, scope=_SCOPE, vessel_name=_VESSEL
    )
    assert pf.proceed is False
    assert _SCOPE in pf.reason
    # Never removed, never torn down.
    assert not any(c[0] == "container_rm" for c in fake_docker.calls)
    assert not any(c[0] == "compose_down" for c in fake_docker.calls)


def test_dead_orphan_self_heals(sample_ctx, fake_docker):
    rid = _seed_record(sample_ctx, with_exit=None)
    fake_docker.container_running_results[_VESSEL] = False

    pf = reaper.preflight(
        sample_ctx, fake_docker, scope=_SCOPE, vessel_name=_VESSEL
    )
    assert pf.proceed is True

    # Synthetic authoritative exit == 137 on the orphaned record.
    assert record.read_exit(sample_ctx.project_root, rid) == record.ORPHAN_EXIT_CODE
    status = record.read_status(sample_ctx.project_root, rid)
    assert status.state == "orphaned"
    assert status.exit_code == record.ORPHAN_EXIT_CODE
    assert status.finished_at is not None

    # Exactly one compose_down, preserve_volumes=False (teardown of last resort).
    downs = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(downs) == 1
    assert downs[0][2] is False

    # And the dead vessel is removed to free the name.
    assert ("container_rm", _VESSEL) in fake_docker.calls


def test_dead_terminal_record_rm_only(sample_ctx, fake_docker):
    """A cleanly-completed prior run (exit already present) → rm the dead
    vessel, but no synthetic exit and no teardown."""
    rid = _seed_record(sample_ctx, with_exit=0)
    fake_docker.container_running_results[_VESSEL] = False

    pf = reaper.preflight(
        sample_ctx, fake_docker, scope=_SCOPE, vessel_name=_VESSEL
    )
    assert pf.proceed is True
    # Exit is unchanged (still the real 0, not overwritten with 137).
    assert record.read_exit(sample_ctx.project_root, rid) == 0
    assert not any(c[0] == "compose_down" for c in fake_docker.calls)
    assert ("container_rm", _VESSEL) in fake_docker.calls


def test_absent_vessel_proceeds_without_rm(sample_ctx, fake_docker):
    # default container_running → None (absent)
    pf = reaper.preflight(
        sample_ctx, fake_docker, scope=_SCOPE, vessel_name=_VESSEL
    )
    assert pf.proceed is True
    assert not any(c[0] == "container_rm" for c in fake_docker.calls)
    assert not any(c[0] == "compose_down" for c in fake_docker.calls)

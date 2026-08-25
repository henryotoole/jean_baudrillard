"""Unit tests for the job verbs, the durable ``docex test`` wrapper, and the
in-vessel entrypoint (Mod 148). No real 6-minute suite is ever run."""

from __future__ import annotations

import os

import pytest

from docex.jobs import commands, record
from docex.jobs.commands import (
    run_in_vessel,
    run_job_ls,
    run_job_result,
    run_job_status,
    run_job_wait,
    run_test_job,
)


_VESSEL = "sample-test-runner"
_SCOPE = "sample/test"


def _seed_record(ctx, *, running: bool | None, exit_code: int | None = None,
                 vessel: str = _VESSEL) -> str:
    rid = record.new_run_id()
    record.create_record(
        ctx.project_root,
        record.RunMeta(
            id=rid, kind="test", scope=_SCOPE, slot=1,
            vessel_kind="container", vessel_name=vessel,
            created_at=record.now_iso(), docex_version="0.5.0", params={},
        ),
    )
    record.write_status(
        ctx.project_root, rid,
        record.RunStatus(state="running", started_at=record.now_iso()),
    )
    if exit_code is not None:
        record.write_exit_atomic(ctx.project_root, rid, exit_code)
    return rid


# ---------------------------------------------------------------------------
# --detach: returns fast with a handle, launches once, does not block
# ---------------------------------------------------------------------------


def test_detach_returns_fast_with_a_handle(sample_ctx, fake_docker, capsys):
    rc = run_test_job(sample_ctx, fake_docker, detach=True)
    assert rc == 0
    handle = capsys.readouterr().out.strip()
    assert handle
    # The handle resolves to a real record whose vessel launched exactly once.
    assert record.read_meta(sample_ctx.project_root, handle) is not None
    detached = [c for c in fake_docker.calls if c[0] == "run_detached"]
    assert len(detached) == 1
    # Did not block on the exit file (none present; state is running).
    assert record.read_exit(sample_ctx.project_root, handle) is None
    assert record.read_status(sample_ctx.project_root, handle).state == "running"


# ---------------------------------------------------------------------------
# lock refusal — two arbiters
# ---------------------------------------------------------------------------


def test_preflight_running_lock_refuses_and_launches_nothing(
    sample_ctx, fake_docker, capsys
):
    fake_docker.container_running_results[_VESSEL] = True
    rc = run_test_job(sample_ctx, fake_docker, detach=True)
    assert rc == commands.LOCK_HELD_EXIT
    assert not any(c[0] == "run_detached" for c in fake_docker.calls)
    assert "already in progress" in capsys.readouterr().err


def test_name_conflict_refuses_and_marks_failed(sample_ctx, fake_docker, capsys):
    # preflight proceeds (vessel absent), but the create race is lost.
    fake_docker.run_detached_result = (1, True)
    rc = run_test_job(sample_ctx, fake_docker, detach=True)
    assert rc == commands.LOCK_HELD_EXIT
    err = capsys.readouterr().err
    assert _SCOPE in err
    ids = record.list_run_ids(sample_ctx.project_root)
    assert len(ids) == 1
    assert record.read_status(sample_ctx.project_root, ids[0]).state == "failed"
    # No exit file for a raced launch — nothing ran.
    assert record.read_exit(sample_ctx.project_root, ids[0]) is None


def test_launch_failure_records_exit_and_returns_rc(sample_ctx, fake_docker, capsys):
    fake_docker.run_detached_result = (5, False)
    rc = run_test_job(sample_ctx, fake_docker, detach=True)
    assert rc == 5
    ids = record.list_run_ids(sample_ctx.project_root)
    assert record.read_exit(sample_ctx.project_root, ids[0]) == 5
    assert record.read_status(sample_ctx.project_root, ids[0]).state == "failed"


# ---------------------------------------------------------------------------
# killed-monitor re-attach (no real suite)
# ---------------------------------------------------------------------------


def test_killed_monitor_reattach(sample_ctx, fake_docker, capsys):
    """A record with a running fake vessel and no exit: `ls`/`status` see it
    LIVE; when the vessel finishes after the monitor died, `wait`/`result`
    read the real code off the authoritative exit file."""
    rid = _seed_record(sample_ctx, running=True)
    fake_docker.container_running_results[_VESSEL] = True

    assert run_job_ls(sample_ctx, fake_docker) == 0
    ls_out = capsys.readouterr().out
    assert rid in ls_out and "running" in ls_out

    assert run_job_status(sample_ctx, fake_docker, rid) == 0
    status_out = capsys.readouterr().out
    assert "live" in status_out  # classify outcome == LIVE

    # Vessel finishes after the monitor died: the exit file appears.
    record.write_exit_atomic(sample_ctx.project_root, rid, 0)
    assert run_job_wait(sample_ctx, fake_docker, rid, timeout=None) == 0
    assert run_job_result(sample_ctx, rid) == 0
    assert capsys.readouterr().out.strip() == "0"


def test_killed_monitor_reattach_nonzero(sample_ctx, fake_docker, capsys):
    rid = _seed_record(sample_ctx, running=True)
    fake_docker.container_running_results[_VESSEL] = True
    record.write_exit_atomic(sample_ctx.project_root, rid, 7)
    assert run_job_wait(sample_ctx, fake_docker, rid, timeout=None) == 7
    assert run_job_result(sample_ctx, rid) == 7


def test_wait_times_out_when_still_running(sample_ctx, fake_docker):
    rid = _seed_record(sample_ctx, running=True)
    fake_docker.container_running_results[_VESSEL] = True
    rc = run_job_wait(sample_ctx, fake_docker, rid, timeout=0.0)
    assert rc == commands.WAIT_TIMEOUT_EXIT


def test_result_unfinished_is_distinct_nonzero(sample_ctx, fake_docker):
    rid = _seed_record(sample_ctx, running=True)
    rc = run_job_result(sample_ctx, rid)
    assert rc == commands.RESULT_UNFINISHED_EXIT
    assert rc != 0


def test_resolve_handle_prefix_and_latest(sample_ctx, fake_docker, capsys):
    rid = _seed_record(sample_ctx, running=True, exit_code=0)
    # A unique prefix resolves.
    assert run_job_result(sample_ctx, rid[:10]) == 0
    capsys.readouterr()
    # 'latest' resolves to the newest.
    assert run_job_result(sample_ctx, "latest") == 0
    capsys.readouterr()
    # An unknown handle errors.
    assert run_job_result(sample_ctx, "does-not-exist") == 1
    assert "no run matches" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# orphan reaping end-to-end through run_test_job
# ---------------------------------------------------------------------------


def test_orphan_reaped_on_next_run(sample_ctx, fake_docker):
    old = _seed_record(sample_ctx, running=False)  # no exit → orphan
    fake_docker.container_running_results[_VESSEL] = False

    rc = run_test_job(sample_ctx, fake_docker, detach=True)
    assert rc == 0

    # The OLD record was reaped: authoritative synthetic 137.
    assert record.read_exit(sample_ctx.project_root, old) == record.ORPHAN_EXIT_CODE
    assert record.read_status(sample_ctx.project_root, old).state == "orphaned"
    # The leaked stack was torn down.
    downs = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(downs) == 1 and downs[0][2] is False
    # And a fresh run launched.
    assert any(c[0] == "run_detached" for c in fake_docker.calls)
    assert len(record.list_run_ids(sample_ctx.project_root)) == 2


# ---------------------------------------------------------------------------
# run_in_vessel — terminal status + atomic exit (exit written AFTER status)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rc_expected,state", [(0, "succeeded"), (7, "failed")])
def test_run_in_vessel_records_status_then_exit_and_captures_log(
    sample_ctx, fake_docker, monkeypatch, rc_expected, state
):
    rid = record.new_run_id()
    record.create_record(
        sample_ctx.project_root,
        record.RunMeta(
            id=rid, kind="test", scope=_SCOPE, slot=1,
            vessel_kind="container", vessel_name=_VESSEL,
            created_at=record.now_iso(), docex_version="0.5.0", params={},
        ),
    )

    def fake_body(ctx, docker, params):
        # Written to the OS-level fds, so the vessel's log redirect captures it.
        os.write(1, b"body stdout line\n")
        os.write(2, b"body stderr line\n")
        return rc_expected

    monkeypatch.setitem(commands._JOB_BODIES, "test", fake_body)

    # Prove the exit file is written AFTER the terminal status: capture the
    # recorded state at the moment write_exit_atomic is called.
    seen: dict[str, str | None] = {}
    real_write_exit = record.write_exit_atomic

    def wrapped_write_exit(project_root, run_id, code):
        st = record.read_status(project_root, run_id)
        seen["state_at_exit"] = st.state if st else None
        return real_write_exit(project_root, run_id, code)

    monkeypatch.setattr(record, "write_exit_atomic", wrapped_write_exit)

    # The entrypoint dup2's the log onto fd 1/2; save & restore around it so
    # this test process's own stdout/stderr survive.
    saved1, saved2 = os.dup(1), os.dup(2)
    try:
        rc = run_in_vessel(sample_ctx, fake_docker, rid)
    finally:
        os.dup2(saved1, 1)
        os.dup2(saved2, 2)
        os.close(saved1)
        os.close(saved2)

    assert rc == rc_expected
    assert record.read_exit(sample_ctx.project_root, rid) == rc_expected
    st = record.read_status(sample_ctx.project_root, rid)
    assert st.state == state
    assert st.exit_code == rc_expected
    assert st.finished_at is not None
    # Exit written after the terminal status was recorded.
    assert seen["state_at_exit"] == state
    # The log captured both streams via the fd redirect.
    log = record.log_path(sample_ctx.project_root, rid).read_text()
    assert "body stdout line" in log
    assert "body stderr line" in log


def test_run_in_vessel_missing_meta_writes_failed_exit(sample_ctx, fake_docker):
    # No record created — meta is unreadable.
    rc = run_in_vessel(sample_ctx, fake_docker, "20260101T000000Z-deadbe")
    assert rc == 1
    assert record.read_exit(
        sample_ctx.project_root, "20260101T000000Z-deadbe"
    ) == 1

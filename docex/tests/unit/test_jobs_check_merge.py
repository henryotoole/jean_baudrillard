"""Unit tests for ``docex check`` / ``docex merge`` as durable jobs (Mod 149).

These prove the two commands ride the same substrate ``docex test`` rides:
``--detach`` returns a handle, the per-command lock refuses a second run, a
killed monitor stays re-attachable, the reaper reclaims a hard-killed
check/merge vessel's ephemeral worktree + throwaway stack, the bodies call
``run_check`` / ``run_merge`` with a real git client, and ``merge --detach`` is
refused under brokered git-credential passthrough. No real check suite is run.
"""

from __future__ import annotations

import os

import pytest

from docex.jobs import commands, record
from docex.jobs.commands import (
    run_check_job,
    run_in_vessel,
    run_job_ls,
    run_job_result,
    run_job_wait,
    run_merge_job,
)


_CHECK_VESSEL = "sample-check-runner"
_MERGE_VESSEL = "sample-merge-runner"
_CHECK_SCOPE = "sample/check"
_MERGE_SCOPE = "sample/merge"


def _seed_record(ctx, *, kind, vessel, exit_code=None, params=None) -> str:
    rid = record.new_run_id()
    record.create_record(
        ctx.project_root,
        record.RunMeta(
            id=rid, kind=kind, scope=f"sample/{kind}", slot=1,
            vessel_kind="container", vessel_name=vessel,
            created_at=record.now_iso(), docex_version="0.5.0",
            params=params or {},
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
# --detach: returns a handle, launches exactly once, records kind + params
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "runner,job,kind",
    [
        (_CHECK_VESSEL, run_check_job, "check"),
        (_MERGE_VESSEL, run_merge_job, "merge"),
    ],
)
def test_detach_returns_handle_launches_once(
    sample_ctx, fake_docker, fake_git, capsys, runner, job, kind
):
    rc = job(sample_ctx, fake_docker, fake_git, detach=True)
    assert rc == 0
    handle = capsys.readouterr().out.strip()
    assert handle
    meta = record.read_meta(sample_ctx.project_root, handle)
    assert meta is not None and meta.kind == kind
    # Deterministic teardown identities recorded for the reaper.
    assert meta.params["worktree_slug"] == "check-abc1234"
    assert meta.params["compose_project"] == "sample-check-abc1234"
    assert record.read_status(sample_ctx.project_root, handle).state == "running"
    assert record.read_exit(sample_ctx.project_root, handle) is None
    detached = [c for c in fake_docker.calls if c[0] == "run_detached"]
    assert len(detached) == 1


# ---------------------------------------------------------------------------
# Lock refusal — running vessel and name-conflict race, for check and merge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "runner,job", [(_CHECK_VESSEL, run_check_job), (_MERGE_VESSEL, run_merge_job)]
)
def test_running_lock_refuses(sample_ctx, fake_docker, fake_git, capsys, runner, job):
    fake_docker.container_running_results[runner] = True
    rc = job(sample_ctx, fake_docker, fake_git, detach=True)
    assert rc == commands.LOCK_HELD_EXIT
    assert "already in progress" in capsys.readouterr().err
    assert not any(c[0] == "run_detached" for c in fake_docker.calls)


@pytest.mark.parametrize(
    "scope,job", [(_CHECK_SCOPE, run_check_job), (_MERGE_SCOPE, run_merge_job)]
)
def test_name_conflict_marks_failed(sample_ctx, fake_docker, fake_git, capsys, scope, job):
    fake_docker.run_detached_result = (0, True)
    rc = job(sample_ctx, fake_docker, fake_git, detach=True)
    assert rc == commands.LOCK_HELD_EXIT
    err = capsys.readouterr().err
    assert scope in err
    ids = record.list_run_ids(sample_ctx.project_root)
    assert len(ids) == 1
    assert record.read_status(sample_ctx.project_root, ids[0]).state == "failed"
    assert record.read_exit(sample_ctx.project_root, ids[0]) is None


# ---------------------------------------------------------------------------
# Killed-monitor re-attach for kind=check (headline: no real suite)
# ---------------------------------------------------------------------------


def test_killed_monitor_reattach_check(sample_ctx, fake_docker, capsys):
    rid = _seed_record(sample_ctx, kind="check", vessel=_CHECK_VESSEL)
    fake_docker.container_running_results[_CHECK_VESSEL] = True

    assert run_job_ls(sample_ctx, fake_docker) == 0
    out = capsys.readouterr().out
    assert rid in out and "running" in out and "check" in out
    assert record.classify(sample_ctx.project_root, rid, fake_docker) is record.Outcome.LIVE

    # The vessel finishes after the monitor died: the exit file appears.
    record.write_exit_atomic(sample_ctx.project_root, rid, 0)
    assert run_job_wait(sample_ctx, fake_docker, rid, timeout=None) == 0
    assert run_job_result(sample_ctx, rid) == 0
    assert capsys.readouterr().out.strip() == "0"


# ---------------------------------------------------------------------------
# Generalized reaper — check orphan reclaims worktree + throwaway stack
# ---------------------------------------------------------------------------


def test_reaper_check_orphan_with_params(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    params = {
        "worktree_slug": "check-abc123",
        "compose_project": "sample-check-abc123",
    }
    orphan = _seed_record(
        sample_ctx, kind="check", vessel=_CHECK_VESSEL, params=params
    )
    wt = sample_ctx.project_root / ".docex" / "worktrees" / "check-abc123"
    wt.mkdir(parents=True)
    fake_docker.container_running_results[_CHECK_VESSEL] = False
    # The reaper builds its own SubprocessGitClient lazily; inject the fake so
    # its worktree_remove/prune calls are observable and hit the tmp tree.
    monkeypatch.setattr("docex.git.SubprocessGitClient", lambda: fake_git)

    rc = run_check_job(sample_ctx, fake_docker, fake_git, detach=True)
    assert rc == 0

    # Orphan made authoritative.
    assert record.read_exit(sample_ctx.project_root, orphan) == record.ORPHAN_EXIT_CODE
    assert record.read_status(sample_ctx.project_root, orphan).state == "orphaned"
    # Throwaway stack torn down by its recorded project name.
    assert ("compose_down_project_name", "sample-check-abc123") in fake_docker.calls
    # Worktree dir reclaimed + a fresh run launched.
    assert not wt.exists()
    assert any(c[0] == "worktree_remove" for c in fake_git.calls)
    assert any(c[0] == "run_detached" for c in fake_docker.calls)
    assert len(record.list_run_ids(sample_ctx.project_root)) == 2


def test_reaper_check_orphan_fallback_sweep(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    orphan = _seed_record(sample_ctx, kind="check", vessel=_CHECK_VESSEL, params={})
    wt_root = sample_ctx.project_root / ".docex" / "worktrees"
    (wt_root / "check-aaa").mkdir(parents=True)
    (wt_root / "check-bbb").mkdir(parents=True)
    fake_docker.container_running_results[_CHECK_VESSEL] = False
    monkeypatch.setattr("docex.git.SubprocessGitClient", lambda: fake_git)

    rc = run_check_job(sample_ctx, fake_docker, fake_git, detach=True)
    assert rc == 0

    assert record.read_exit(sample_ctx.project_root, orphan) == record.ORPHAN_EXIT_CODE
    # No compose_project recorded → no throwaway-stack down; the namespace sweep
    # removes every worktree dir and prune is issued.
    assert not (wt_root / "check-aaa").exists()
    assert not (wt_root / "check-bbb").exists()
    assert any(c[0] == "worktree_prune" for c in fake_git.calls)


def test_reaper_test_orphan_unchanged(sample_ctx, fake_docker):
    """The test-kind orphan path is byte-for-byte the old behavior: exactly one
    compose_down of the test stack, no worktree machinery."""
    from docex.jobs.commands import run_test_job

    orphan = _seed_record(sample_ctx, kind="test", vessel="sample-test-runner")
    fake_docker.container_running_results["sample-test-runner"] = False

    rc = run_test_job(sample_ctx, fake_docker, detach=True)
    assert rc == 0
    assert record.read_exit(sample_ctx.project_root, orphan) == record.ORPHAN_EXIT_CODE
    downs = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(downs) == 1 and downs[0][2] is False


# ---------------------------------------------------------------------------
# Body wiring — bodies call run_check / run_merge with a git client
# ---------------------------------------------------------------------------


def test_run_check_body_calls_run_check_with_git(sample_ctx, fake_docker, monkeypatch):
    recorded = {}

    def stub(ctx, docker, git):
        recorded["args"] = (ctx, docker, git)
        return 3

    monkeypatch.setattr("docex.pipeline.check.run_check", stub)
    rc = commands._run_check_body(sample_ctx, fake_docker, {})
    assert rc == 3
    from docex.git import SubprocessGitClient

    ctx_, docker_, git_ = recorded["args"]
    assert ctx_ is sample_ctx and docker_ is fake_docker
    assert isinstance(git_, SubprocessGitClient)


def test_run_merge_body_calls_run_merge_with_git(sample_ctx, fake_docker, monkeypatch):
    recorded = {}

    def stub(ctx, docker, git):
        recorded["args"] = (ctx, docker, git)
        return 5

    monkeypatch.setattr("docex.pipeline.merge.run_merge", stub)
    rc = commands._run_merge_body(sample_ctx, fake_docker, {})
    assert rc == 5
    from docex.git import SubprocessGitClient

    ctx_, docker_, git_ = recorded["args"]
    assert ctx_ is sample_ctx and docker_ is fake_docker
    assert isinstance(git_, SubprocessGitClient)


# ---------------------------------------------------------------------------
# __run-job dispatches check / merge bodies inside the vessel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind,vessel", [("check", _CHECK_VESSEL), ("merge", _MERGE_VESSEL)])
@pytest.mark.parametrize("rc_expected,state", [(0, "succeeded"), (7, "failed")])
def test_run_in_vessel_dispatches_check_merge(
    sample_ctx, fake_docker, monkeypatch, kind, vessel, rc_expected, state
):
    rid = _seed_record(sample_ctx, kind=kind, vessel=vessel)

    def fake_body(ctx, docker, params):
        os.write(1, f"{kind} body ran\n".encode())
        return rc_expected

    monkeypatch.setitem(commands._JOB_BODIES, kind, fake_body)

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
    assert record.read_status(sample_ctx.project_root, rid).state == state
    assert f"{kind} body ran" in record.log_path(sample_ctx.project_root, rid).read_text()


# ---------------------------------------------------------------------------
# merge --detach passthrough guard
# ---------------------------------------------------------------------------


def _clear_passthrough(monkeypatch):
    for k in list(os.environ):
        if k.startswith("GIT_CONFIG_VALUE_"):
            monkeypatch.delenv(k, raising=False)


def test_merge_detach_refused_under_passthrough(
    sample_ctx, fake_docker, fake_git, monkeypatch, capsys
):
    _clear_passthrough(monkeypatch)
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "!python3 /tmp/x/forward.py /tmp/x/sock")
    rc = run_merge_job(sample_ctx, fake_docker, fake_git, detach=True)
    assert rc == commands._MERGE_DETACH_PASSTHROUGH_EXIT
    assert rc == 64
    assert "passthrough" in capsys.readouterr().err.lower()
    assert not any(c[0] == "run_detached" for c in fake_docker.calls)
    # Nothing launched: no record created either.
    assert record.list_run_ids(sample_ctx.project_root) == []


def test_merge_blocking_not_refused_under_passthrough(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    _clear_passthrough(monkeypatch)
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "!python3 /tmp/x/forward.py /tmp/x/sock")
    attached = {}

    def fake_attach(ctx, run_id, **kw):
        attached["run_id"] = run_id
        return 0

    monkeypatch.setattr(commands, "_attach", fake_attach)
    rc = run_merge_job(sample_ctx, fake_docker, fake_git, detach=False)
    assert rc == 0
    # The guard did NOT fire: the vessel launched and we attached.
    assert any(c[0] == "run_detached" for c in fake_docker.calls)
    assert "run_id" in attached


def test_merge_detach_without_passthrough_launches(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    _clear_passthrough(monkeypatch)
    rc = run_merge_job(sample_ctx, fake_docker, fake_git, detach=True)
    assert rc == 0
    assert any(c[0] == "run_detached" for c in fake_docker.calls)

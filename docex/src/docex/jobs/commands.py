"""The ``job`` verbs, the ``docex test`` durable wrapper, and the in-vessel
entrypoint.

``run_test_job`` is the ``docex test`` handler: it preflights the scope's
lock, creates the run record, launches the container vessel, and — unless
``--detach`` — attaches to tail the log and block on the exit file. The
blocking default preserves the exit-code contract CI relies on, but the work
is durable underneath: a killed monitor leaves the run re-attachable via
``docex job wait``.

``run_in_vessel`` is the hidden ``__run-job`` entrypoint that runs *inside*
the vessel: it redirects stdout/stderr to the log, dispatches on
``meta.kind`` to the job body (``run_test`` for kind=test), and records a
terminal status followed by the atomic exit file.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

from docex.jobs import record, reaper
from docex.jobs.vessel import ContainerVessel
from docex.naming import dns_label


# EX_TEMPFAIL — "busy, retry". Used for a lock refusal and a wait timeout.
LOCK_HELD_EXIT = 75
WAIT_TIMEOUT_EXIT = 75
# ``job result`` when the run has not finished — its own status, not a run's
# exit code (a run that genuinely exited 3 prints and returns 3).
RESULT_UNFINISHED_EXIT = 2
# ``merge --detach`` refused because brokered credential passthrough is active —
# a usage error (EX_USAGE), distinct from a lock refusal (see overview § 4).
_MERGE_DETACH_PASSTHROUGH_EXIT = 64


def _run_test_body(ctx, docker, params) -> int:
    # Lazy import: avoids paying orchestrate/test's import cost on every
    # dispatcher load and keeps the module free of an import cycle.
    from docex.orchestrate.test import run_test

    tiers = tuple(params.get("tiers") or ("unit", "integration"))
    selector = params.get("selector")
    slots = int(params.get("slots") or 1)
    return run_test(ctx, docker, tiers=tiers, selector=selector, slots=slots)


def _run_check_body(ctx, docker, params) -> int:  # params unused
    # Lazy imports (same rationale as _run_test_body). The _JOB_BODIES
    # signature is body(ctx, docker, params), so the git client is constructed
    # here rather than threaded through — matching how _require_git builds it.
    from docex.git import SubprocessGitClient
    from docex.pipeline.check import run_check

    return run_check(ctx, docker, SubprocessGitClient())


def _run_merge_body(ctx, docker, params) -> int:  # params unused
    from docex.git import SubprocessGitClient
    from docex.pipeline.merge import run_merge

    return run_merge(ctx, docker, SubprocessGitClient())


# Registry of job bodies keyed by ``meta.kind``. Module-level so tests (and a
# real-docker integration test) can register or replace an entry. The vessel is
# one container kind for every durable job (D2); what varies by kind is the body
# dispatched here and the reaper's orphan teardown.
_JOB_BODIES = {
    "test": _run_test_body,
    "check": _run_check_body,
    "merge": _run_merge_body,
}


# ---------------------------------------------------------------------------
# `docex test` — the durable job with a container vessel.
# ---------------------------------------------------------------------------


def _launch_durable_job(
    ctx, docker, *, kind: str, scope: str, vessel_name: str,
    params: dict, detach: bool,
) -> int:
    """Preflight the scope lock, create the run record, launch the container
    vessel, and (unless ``detach``) attach to block on the exit file.

    Shared by ``run_test_job`` / ``run_check_job`` / ``run_merge_job`` — the
    only per-command variation is ``(kind, scope, vessel_name, params)``. The
    body is dispatched inside the vessel by ``meta.kind`` (``_JOB_BODIES``), so
    it is not a parameter here.
    """
    pf = reaper.preflight(ctx, docker, scope=scope, vessel_name=vessel_name)
    if not pf.proceed:
        print(pf.reason, file=sys.stderr)
        return LOCK_HELD_EXIT

    run_id = record.new_run_id()
    meta = record.RunMeta(
        id=run_id,
        kind=kind,
        scope=scope,
        slot=1,
        vessel_kind="container",
        vessel_name=vessel_name,
        created_at=record.now_iso(),
        docex_version=ctx.project.docex_version,
        params=params,
    )
    record.create_record(ctx.project_root, meta)

    res = ContainerVessel(docker, vessel_name).launch(ctx, run_id)
    if res.name_conflict:
        # A concurrent run won the `docker run --name` create race (D5).
        record.write_status(
            ctx.project_root, run_id,
            record.RunStatus(state="failed", finished_at=record.now_iso()),
        )
        print(
            f"error: another run won the launch race for scope {scope} "
            f"(vessel {vessel_name}); refusing. Wait for it "
            f"(docex job wait <id>) or let it finish.",
            file=sys.stderr,
        )
        return LOCK_HELD_EXIT
    if res.rc != 0:
        record.write_status(
            ctx.project_root, run_id,
            record.RunStatus(
                state="failed", finished_at=record.now_iso(), exit_code=res.rc
            ),
        )
        record.write_exit_atomic(ctx.project_root, run_id, res.rc)
        print(
            f"error: launching the {kind} vessel exited {res.rc}.",
            file=sys.stderr,
        )
        return res.rc

    record.write_status(
        ctx.project_root, run_id,
        record.RunStatus(state="running", started_at=record.now_iso()),
    )

    if detach:
        print(run_id)
        return 0
    return _attach(ctx, run_id)


def run_test_job(
    ctx, docker, *, detach: bool,
    tiers: tuple[str, ...] = ("unit", "integration"),
    selector: str | None = None,
    slots: int = 1,
) -> int:
    """Launch ``docex test`` (or ``docex test integration [subset]``) as a
    durable, container-vessel job.

    Blocks and attaches by default (exit code == the run's); with
    ``detach=True`` prints the handle and returns fast (~seconds). The
    integration lane shares ``test``'s lock scope — both contend over the same
    ``test`` stack, so they refuse each other.
    """
    label = dns_label(ctx.project.name)
    return _launch_durable_job(
        ctx, docker,
        kind="test",
        scope=f"{label}/test",
        vessel_name=f"{label}-test-runner",
        params={"tiers": list(tiers), "selector": selector, "slots": slots},
        detach=detach,
    )


# ---------------------------------------------------------------------------
# `docex check` / `docex merge` — durable jobs on the same substrate.
# ---------------------------------------------------------------------------


def _check_teardown_params(ctx, git, *, slot: int) -> dict:
    """Deterministic identities the reaper reclaims for a hard-killed
    check/merge vessel.

    ``run_check`` recomputes the same project name inside the vessel:
    ``env_compose_project(ctx, "test", slot=slot)`` (the reserved-slot stack,
    Mod 155). The worktree dir is still ``check-<short_sha>`` (run_check names it
    that regardless of which command drove it). Recording these here lets the
    reaper reclaim the leak by label without threading anything through
    ``run_check``'s signature.
    """
    from docex.orchestrate._common import env_compose_project

    short_sha = git.head_sha(ctx.project_root, short=True)
    return {
        "worktree_slug": f"check-{short_sha}",
        "compose_project": env_compose_project(ctx, "test", slot=slot),
        "slot": slot,
    }


def _brokered_passthrough_active() -> bool:
    """True iff the shim staged brokered git-credential passthrough for this
    invocation.

    ``DOCEX_GIT_CREDENTIAL_PASSTHROUGH`` is NOT forwarded into the container;
    the shim instead points in-container git at its ``forward.py`` by injecting
    a ``GIT_CONFIG_VALUE_<n>=!python3 .../forward.py <sock>`` as git's
    ``credential.helper`` (bin/docex). The presence of a ``GIT_CONFIG_VALUE_*``
    naming ``forward.py`` is therefore the in-container signal.
    """
    for key, val in os.environ.items():
        if key.startswith("GIT_CONFIG_VALUE_") and "forward.py" in val:
            return True
    return False


def run_check_job(ctx, docker, git, *, detach: bool) -> int:
    """Launch ``docex check`` as a durable, container-vessel job.

    Blocks by default (exit code == the run's); ``detach=True`` prints the
    handle and returns fast. ``git`` is taken so the foreground can record the
    deterministic teardown identities (``short_sha``) the reaper reclaims on a
    hard-killed vessel.
    """
    from docex.orchestrate._common import CHECK_SLOT

    label = dns_label(ctx.project.name)
    return _launch_durable_job(
        ctx, docker,
        kind="check",
        scope=f"{label}/check",
        vessel_name=f"{label}-check-runner",
        params=_check_teardown_params(ctx, git, slot=CHECK_SLOT),
        detach=detach,
    )


def run_merge_job(ctx, docker, git, *, detach: bool) -> int:
    """Launch ``docex merge`` as a durable, container-vessel job.

    Same shape as ``run_check_job`` (merge's defensive check owns the same
    worktree/stack, so it records the same teardown identities), with one
    fail-fast guard up front.
    """
    label = dns_label(ctx.project.name)
    # Fail-fast guard: brokered git-credential passthrough (shim-staged, tied to
    # the foreground call) does NOT survive a detached merge — the host-side
    # responder dies with the foreground shim invocation, so the vessel's later
    # push cannot re-broker. Refuse up front rather than doing all the work and
    # dying at push. Blocking merge is fine (the responder stays alive), and
    # static credentials (ssh key / gitconfig / file token) are cloned into the
    # vessel and survive. See overview § 4.
    if detach and _brokered_passthrough_active():
        print(
            "error: 'docex merge --detach' is refused while brokered git-"
            "credential passthrough (DOCEX_GIT_CREDENTIAL_PASSTHROUGH) is "
            "active: the host-side credential responder is scoped to the "
            "foreground call and would not survive into the detached vessel, so "
            "the merge's push would fail. Run 'docex merge' attached "
            "(blocking), or use a static credential (SSH key / gitconfig / "
            "file-based token), which is cloned into the vessel and does "
            "survive.",
            file=sys.stderr,
        )
        return _MERGE_DETACH_PASSTHROUGH_EXIT
    from docex.orchestrate._common import MERGE_SLOT

    return _launch_durable_job(
        ctx, docker,
        kind="merge",
        scope=f"{label}/merge",
        vessel_name=f"{label}-merge-runner",
        params=_check_teardown_params(ctx, git, slot=MERGE_SLOT),
        detach=detach,
    )


def _attach(ctx, run_id: str, *, poll_interval: float = 0.5) -> int:
    """Tail the log and block on the exit file — the durable monitor.

    A ``KeyboardInterrupt``/kill here does NOT touch the vessel: the run
    stays re-attachable via ``docex job wait <id>``.
    """
    project_root = ctx.project_root
    lp = record.log_path(project_root, run_id)
    offset = 0
    while True:
        offset = _flush_log(lp, offset)
        code = record.read_exit(project_root, run_id)
        if code is not None:
            _flush_log(lp, offset)
            return code
        time.sleep(poll_interval)


def _flush_log(log: Path, offset: int) -> int:
    """Print any log bytes past ``offset``; return the new offset."""
    try:
        data = log.read_bytes()
    except OSError:
        return offset
    if len(data) <= offset:
        return offset
    try:
        sys.stdout.write(data[offset:].decode("utf-8", errors="replace"))
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 — tailing must never crash the monitor
        pass
    return len(data)


# ---------------------------------------------------------------------------
# `docex job <verb>` — operate on handles.
# ---------------------------------------------------------------------------


def run_job_ls(ctx, docker) -> int:
    """Enumerate every run, reconciling each record against vessel liveness."""
    project_root = ctx.project_root
    ids = record.list_run_ids(project_root)
    if not ids:
        print("no runs recorded (.docex/runs is empty).")
        return 0
    print(
        f"{'ID':<24} {'KIND':<6} {'SCOPE':<18} {'STATE':<10} "
        f"{'STARTED':<26} EXIT"
    )
    for run_id in ids:
        meta = record.read_meta(project_root, run_id)
        status = record.read_status(project_root, run_id)
        outcome = record.classify(project_root, run_id, docker)
        state = _reconciled_state(outcome, status)
        code = record.read_exit(project_root, run_id)
        kind = meta.kind if meta else "?"
        scope = meta.scope if meta else "?"
        started = status.started_at if status and status.started_at else "-"
        print(
            f"{run_id:<24} {kind:<6} {scope:<18} {state:<10} "
            f"{started:<26} {'' if code is None else code}"
        )
    return 0


def _reconciled_state(outcome, status) -> str:
    """Fold a ``classify`` outcome with the recorded status into one label."""
    if outcome is record.Outcome.TERMINAL:
        if status and status.state in ("succeeded", "failed", "orphaned"):
            return status.state
        return "finished"
    if outcome is record.Outcome.LIVE:
        return "running"
    return "orphaned"


def run_job_status(ctx, docker, handle: str) -> int:
    """Print a run's status reconciled against vessel liveness."""
    project_root = ctx.project_root
    run_id = _resolve_handle(project_root, handle)
    if run_id is None:
        _print_unknown_handle(project_root, handle)
        return 1
    meta = record.read_meta(project_root, run_id)
    status = record.read_status(project_root, run_id)
    outcome = record.classify(project_root, run_id, docker)
    code = record.read_exit(project_root, run_id)
    print(f"id:             {run_id}")
    if meta:
        print(f"kind:           {meta.kind}")
        print(f"scope:          {meta.scope}")
        print(f"vessel:         {meta.vessel_name} ({meta.vessel_kind})")
    if status:
        print(f"state:          {status.state}")
        print(f"started:        {status.started_at or '-'}")
        print(f"finished:       {status.finished_at or '-'}")
    print(f"outcome:        {outcome.value}")
    print(f"exit:           {'-' if code is None else code}")
    if meta:
        print(f"vessel_running: {docker.container_running(meta.vessel_name)}")
    return 0


def run_job_wait(ctx, docker, handle: str, *, timeout: float | None) -> int:
    """Block until the exit file appears (or ``timeout``); exit with its code.

    This is the re-attach path: a fresh process, or one whose monitor was
    killed, blocks here on the authoritative exit file.
    """
    project_root = ctx.project_root
    run_id = _resolve_handle(project_root, handle)
    if run_id is None:
        _print_unknown_handle(project_root, handle)
        return 1
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        code = record.read_exit(project_root, run_id)
        if code is not None:
            return code
        if deadline is not None and time.monotonic() >= deadline:
            print(
                f"run {run_id} still running (timed out after {timeout}s).",
                file=sys.stderr,
            )
            return WAIT_TIMEOUT_EXIT
        time.sleep(0.5)


def run_job_logs(ctx, handle: str, *, follow: bool) -> int:
    """Print (or, with ``follow``, tail) a run's log."""
    project_root = ctx.project_root
    run_id = _resolve_handle(project_root, handle)
    if run_id is None:
        _print_unknown_handle(project_root, handle)
        return 1
    lp = record.log_path(project_root, run_id)
    if not lp.is_file():
        print(f"no log recorded for run {run_id} yet.", file=sys.stderr)
        return 1
    if not follow:
        try:
            sys.stdout.write(lp.read_text(errors="replace"))
            sys.stdout.flush()
        except OSError as exc:
            print(f"error reading log for {run_id}: {exc}", file=sys.stderr)
            return 1
        return 0
    offset = 0
    while True:
        offset = _flush_log(lp, offset)
        if record.read_exit(project_root, run_id) is not None:
            _flush_log(lp, offset)
            return 0
        time.sleep(0.5)


def run_job_result(ctx, handle: str) -> int:
    """Print and exit with the run's authoritative ``exit`` code.

    Not finished → a distinct non-zero (its own status), never a run's code.
    """
    project_root = ctx.project_root
    run_id = _resolve_handle(project_root, handle)
    if run_id is None:
        _print_unknown_handle(project_root, handle)
        return 1
    code = record.read_exit(project_root, run_id)
    if code is None:
        print(
            f"run {run_id} has not finished (no exit recorded yet).",
            file=sys.stderr,
        )
        return RESULT_UNFINISHED_EXIT
    print(code)
    return code


def _resolve_handle(project_root, handle: str) -> str | None:
    """Resolve an exact id, a unique prefix, or ``latest`` to a run id."""
    ids = record.list_run_ids(project_root)
    if not ids:
        return None
    if handle == "latest":
        return ids[0]
    if handle in ids:
        return handle
    matches = [i for i in ids if i.startswith(handle)]
    return matches[0] if len(matches) == 1 else None


def _print_unknown_handle(project_root, handle: str) -> None:
    ids = record.list_run_ids(project_root)
    listing = "\n".join(f"  {i}" for i in ids) or "  (none)"
    print(
        f"error: no run matches handle {handle!r}. Known runs:\n{listing}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# `docex __run-job <id>` — runs INSIDE the vessel only (hidden).
# ---------------------------------------------------------------------------


def run_in_vessel(ctx, docker, run_id: str) -> int:
    """Execute the job body inside the vessel and record its outcome.

    Redirects the process's stdout/stderr to the run's ``log`` at the OS level
    (fd 1/2) so child processes — ``docker compose``, migrate, the shims — are
    captured too. Writes a terminal ``status`` and *then* the atomic ``exit``,
    so a reader that sees ``exit`` also sees a consistent status.
    """
    project_root = ctx.project_root
    meta = record.read_meta(project_root, run_id)
    if meta is None:
        record.write_exit_atomic(project_root, run_id, 1)
        return 1

    record.write_status(
        project_root, run_id,
        record.RunStatus(state="running", started_at=record.now_iso()),
    )

    _redirect_stdio_to_log(project_root, run_id)

    body = _JOB_BODIES.get(meta.kind)
    if body is None:
        print(f"error: no job body registered for kind {meta.kind!r}",
              file=sys.stderr)
        rc = 1
    else:
        try:
            rc = body(ctx, docker, meta.params)
        except Exception:  # noqa: BLE001 — any body failure is a failed run
            traceback.print_exc()
            rc = 1

    record.write_status(
        project_root, run_id,
        record.RunStatus(
            state=("succeeded" if rc == 0 else "failed"),
            started_at=record.now_iso(),
            finished_at=record.now_iso(),
            exit_code=rc,
        ),
    )
    # LAST — the exit file is the terminal signal; written after status so a
    # reader that sees `exit` also sees a consistent terminal status.
    record.write_exit_atomic(project_root, run_id, rc)
    return rc


def _redirect_stdio_to_log(project_root, run_id: str) -> None:
    """Point fd 1 and fd 2 at the run's log file (append)."""
    lp = record.log_path(project_root, run_id)
    lp.parent.mkdir(parents=True, exist_ok=True)
    logfd = os.open(lp, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.dup2(logfd, 1)
        os.dup2(logfd, 2)
    finally:
        os.close(logfd)

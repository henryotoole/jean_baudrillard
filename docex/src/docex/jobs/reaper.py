"""Single-run self-heal reaper (F4).

Runs the shared ``classify`` primitive for the one scope about to launch and
decides what to do with a same-named vessel that already exists:

- **running** → the lock is held → REFUSE (never touch a live run).
- **dead + orphaned record** (no ``exit`` file) → self-heal: synthesize the
  authoritative orphan ``exit``, mark the record orphaned, reclaim whatever the
  orphaned run's kind owns (for ``test``, the **fleet** / multi-slot teardown:
  all N deterministic slot stacks the run leaked, N read from the record; or a
  ``check``/``merge`` worktree + its throwaway build/test stack; the vessel's
  ``finally`` never ran), then ``rm`` the dead vessel and proceed.
- **dead + terminal record** (``exit`` already present) → a cleanly-completed
  prior run just holds the name → ``rm`` and proceed. No synth, no teardown.
- **absent** → nothing to reap → proceed.

Because ``ls`` and this reaper both classify via ``record.classify``, they
can never disagree about what an orphan is. A running vessel is never
force-removed, so the reaper cannot harm a legitimate concurrent run.
"""

from __future__ import annotations

from dataclasses import dataclass

from docex.jobs import record
from docex.orchestrate._common import (
    compose_file_for,
    env_compose_project,
    env_file_for,
)


@dataclass
class PreflightResult:
    proceed: bool
    reason: str = ""  # populated on refusal


def _find_record_for_vessel(project_root, vessel_name: str) -> str | None:
    """Newest run id whose ``meta.vessel_name`` matches, or None."""
    for run_id in record.list_run_ids(project_root):
        meta = record.read_meta(project_root, run_id)
        if meta is not None and meta.vessel_name == vessel_name:
            return run_id
    return None


def preflight(ctx, docker, *, scope: str, vessel_name: str) -> PreflightResult:
    """Classify + reap the ``vessel_name`` slot for ``scope``."""
    running = docker.container_running(vessel_name)

    if running is True:
        return PreflightResult(
            False,
            f"a run is already in progress for scope {scope} "
            f"(vessel {vessel_name}); wait for it (docex job wait <id>) or "
            f"let it finish",
        )

    if running is False:
        project_root = ctx.project_root
        run_id = _find_record_for_vessel(project_root, vessel_name)
        if run_id is not None and record.read_exit(project_root, run_id) is None:
            # ORPHAN self-heal: the vessel died before writing its exit. Make
            # the record authoritative, then assume ownership of the stack it
            # leaked (its `finally` teardown never ran).
            record.write_exit_atomic(
                project_root, run_id, record.ORPHAN_EXIT_CODE
            )
            status = record.read_status(project_root, run_id) or record.RunStatus(
                state="orphaned"
            )
            status.state = "orphaned"
            status.finished_at = record.now_iso()
            status.exit_code = record.ORPHAN_EXIT_CODE
            record.write_status(project_root, run_id, status)
            meta = record.read_meta(project_root, run_id)
            _teardown_leaked_resources(ctx, docker, meta)
        # Free the name (completed OR just-reaped-orphan).
        docker.container_rm(vessel_name)
        return PreflightResult(True)

    # running is None → the container is absent → nothing to reap.
    return PreflightResult(True)


def _teardown_leaked_resources(ctx, docker, meta) -> None:
    """Reclaim whatever a hard-killed vessel of this kind leaked, keyed off
    ``meta`` (D2: the vessel is one container kind; the owned resource varies by
    job kind).

    ``test`` -> its compose stack; ``check``/``merge`` -> the ephemeral worktree
    + the throwaway build/test stack the defensive check brought up. An unknown
    kind (or unreadable meta) defaults to the ``test`` teardown, matching the
    pre-mod-149 behavior for a record whose kind cannot be read.
    """
    kind = meta.kind if meta is not None else "test"
    if kind == "test":
        _teardown_test_stack(ctx, docker, meta)
    elif kind in ("check", "merge"):
        _teardown_worktree_job(ctx, docker, meta)
    # An unknown kind leaks nothing we can safely reclaim; do nothing rather
    # than guess (the synthetic exit + rm already freed the name).


def _teardown_test_stack(ctx, docker, meta=None) -> None:
    """Tear down every leaked ``test`` slot stack a hard-killed vessel owned.

    The **fleet** (multi-slot) reaper: the vessel's ``finally`` (which tears
    down each slot) never ran, so slots 1..N leak. N is recorded in
    ``meta.params['slots']`` at launch; default 1 (a pre-slots record, or a
    non-sharded run). Each slot's compose file is at the Mod 152 layout, written
    by the vessel before it brought the slot up.

    ``preserve_volumes=False`` — a ``test`` stack's data is throwaway, and a
    reaped orphan's half-migrated database must not survive into the next run.

    A **failed** slot deliberately left up by a *completed* run is not swept
    here (this path only fires for a hard-killed orphan); it is reclaimed by the
    next run's per-slot pre-up ``compose down``, or persists across a smaller-N
    run until an N≥k run touches slot k — the accepted residual edge
    (overview § 5, ruling Q3).
    """
    from docex.orchestrate._common import slot_compose_file

    params = (meta.params if meta is not None else {}) or {}
    slots = int(params.get("slots") or 1)
    for k in range(1, slots + 1):
        docker.compose_down(
            slot_compose_file(ctx, "test", k),
            preserve_volumes=False,
            env_file=env_file_for(ctx, "test"),
            project_name=env_compose_project(ctx, "test", slot=k),
        )


def _teardown_worktree_job(ctx, docker, meta) -> None:
    """Reclaim a hard-killed check/merge vessel's ephemeral resources.

    1. ``compose down -v`` the throwaway build/test stack by its recorded
       project name (``run_check`` inside the vessel named it
       ``<label>-check-<sha>``).
    2. Remove the ephemeral worktree dir + ``git worktree prune``.

    Never unwinds merge's real git mutations (an interrupted rebase / partial
    ff+tag) — merge's own contract leaves those for the operator to inspect.
    This reclaims only docex-owned ephemeral scratch. Degrades safely: an
    absent/missing ``meta.params`` falls back to a namespace sweep of every
    ``.docex/worktrees/`` entry.

    WHY no temp-branch sweep: the ``GitClient`` protocol has no branch-listing
    method, and the mod's guardrail forbids inventing one. A leaked
    ``docex-check/*`` / ``docex-merge/*`` temp branch is a harmless leftover —
    each is timestamp-suffixed (``_worktree.make_temp_branch``), so the next
    run's branch never collides with a stale one — and ``worktree prune`` clears
    the worktree-list entry that actually matters.
    """
    from docex.git import SubprocessGitClient
    from docex.pipeline._worktree import worktree_path_for

    project_root = ctx.project_root
    params = (meta.params if meta is not None else {}) or {}
    git = SubprocessGitClient()

    # 1. Throwaway compose stack (test env compose file, worktree-unique name).
    compose_project = params.get("compose_project")
    if compose_project:
        docker.compose_down(
            compose_file_for(ctx, "test"),
            preserve_volumes=False,
            project_name=compose_project,
        )

    # 2. Worktree dir(s).
    slug = params.get("worktree_slug")
    if slug:
        _remove_worktree(project_root, worktree_path_for(project_root, slug), git)
    else:
        # Fallback: reclaim every ephemeral worktree under .docex/worktrees/.
        wt_root = project_root / ".docex" / "worktrees"
        if wt_root.is_dir():
            for entry in sorted(wt_root.iterdir()):
                if entry.is_dir():
                    _remove_worktree(project_root, entry, git)
    git.worktree_prune(project_root)


def _remove_worktree(project_root, worktree, git) -> None:
    """Force-remove one worktree, falling back to ``shutil.rmtree``."""
    import shutil

    if not worktree.exists():
        return
    rc = git.worktree_remove(project_root, worktree, force=True)
    if rc != 0 and worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)

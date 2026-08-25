"""Single-run self-heal reaper (F4).

Runs the shared ``classify`` primitive for the one scope about to launch and
decides what to do with a same-named vessel that already exists:

- **running** → the lock is held → REFUSE (never touch a live run).
- **dead + orphaned record** (no ``exit`` file) → self-heal: synthesize the
  authoritative orphan ``exit``, mark the record orphaned, tear down the
  leaked compose stack (the vessel's ``finally`` never ran), then ``rm`` the
  dead vessel and proceed.
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
            _teardown_leaked_stack(ctx, docker)
        # Free the name (completed OR just-reaped-orphan).
        docker.container_rm(vessel_name)
        return PreflightResult(True)

    # running is None → the container is absent → nothing to reap.
    return PreflightResult(True)


def _teardown_leaked_stack(ctx, docker) -> None:
    """Tear down the scope's leaked ``test`` compose stack, best-effort.

    ``preserve_volumes=False`` — a ``test`` stack's data is throwaway, and a
    reaped orphan's half-migrated database must not survive into the next run.
    """
    docker.compose_down(
        compose_file_for(ctx, "test"),
        preserve_volumes=False,
        env_file=env_file_for(ctx, "test"),
        project_name=env_compose_project(ctx, "test"),
    )

"""Worktree helpers shared by pipeline commands (check, rollback).

The ephemeral-worktree machinery — create a worktree at some ref, tear
it down on completion, swallow cleanup errors so they never mask the
real command failure — is identical between ``docex check`` and
``docex rollback``. Only the recipe differs: ``check`` rebases its
worktree onto fresh ``origin/main``; ``rollback`` checks out at
``v<target_version>``. The helpers below are recipe-agnostic.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from docex.git.client import GitClient


def worktree_path_for(project_root: Path, slug: str) -> Path:
    """Return the conventional path for an ephemeral worktree.

    ``slug`` distinguishes the worktree's purpose, e.g. ``check-<sha>``
    or ``rollback-<version>``. Callers compose it so the slug encodes
    the intent of the worktree in the path itself.
    """
    return project_root / ".docex" / "worktrees" / slug


def make_temp_branch(prefix: str, ref_name: str) -> str:
    """Encode the calling command and ref name into a unique branch.

    ``prefix`` is the command name (``check`` / ``rollback``).
    ``ref_name`` is the human-meaningful anchor (feature branch name
    for check, target version for rollback). The timestamp suffix
    prevents collision when the same command runs concurrently against
    the same ref.
    """
    safe = ref_name.replace("/", "-").replace(":", "-")
    return f"docex-{prefix}/{safe}-{int(time.time())}"


def cleanup_worktree(
    project_root: Path,
    worktree: Path,
    temp_branch: str,
    git: GitClient,
) -> None:
    """Best-effort worktree teardown. Never raises.

    Forces removal (worktrees collect untracked build artifacts that
    git's default-mode remove refuses), falls back to ``shutil.rmtree``
    if git still can't remove the directory, prunes the worktree list,
    then deletes the temp branch. Errors are swallowed so cleanup never
    masks the underlying command failure.
    """
    if not worktree.exists():
        return
    rc = git.worktree_remove(project_root, worktree, force=True)
    if rc != 0 and worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
        # WHY: git keeps a stale entry in `worktree list` pointing at a
        # path we just removed under its feet — prune to clear it.
        git.worktree_prune(project_root)
    git.delete_branch(project_root, temp_branch, remote=False)


def parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version into a tuple of ints for comparison.

    Non-numeric segments fall back to 0 — sufficient for ordering
    project.yml versions, not a full PEP 440 parser.
    """
    parts: list[int] = []
    for seg in v.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            digits = "".join(ch for ch in seg if ch.isdigit())
            parts.append(int(digits) if digits else 0)
    return tuple(parts)


def validate_one_minor_back(current: str, target: str) -> str | None:
    """Return None if rolling back ``current`` to ``target`` is allowed
    by the one-minor-back doctrine rule; else return an error string.

    Per cicd.md § Rollback: target must satisfy
    ``target.major == current.major`` and
    ``target.minor >= current.minor - 1``, and ``target < current``.
    """
    cur = parse_version(current)
    tgt = parse_version(target)
    # Pad to 3 components so .minor / .patch are addressable.
    cur = (cur + (0, 0, 0))[:3]
    tgt = (tgt + (0, 0, 0))[:3]

    if tgt >= cur:
        return (
            f"target version {target!r} is not older than current "
            f"version {current!r}; rollback requires a strictly prior version."
        )
    if tgt[0] != cur[0]:
        return (
            f"target version {target!r} crosses a major-version boundary "
            f"(current {current!r}); rollback supports at most one minor "
            f"version back."
        )
    if cur[1] - tgt[1] > 1:
        return (
            f"target version {target!r} is more than one minor version "
            f"behind current {current!r}; rollback supports at most one "
            f"minor version back."
        )
    return None

"""``GitClient`` Protocol.

Every git operation Phase 3's commands need is declared here. Same
discipline as ``DockerClient``: methods return exit codes (where the
underlying ``git`` invocation returns one), never raise on non-zero.
The orchestrate/pipeline layer is responsible for turning failures
into ``DocexError`` subclasses.

Only :mod:`docex.git.subprocess_client` is permitted to ``import
subprocess`` for git.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class GitClient(Protocol):
    """Abstraction over the ``git`` CLI."""

    def is_clean(self, cwd: Path) -> bool:
        """Return True iff the working tree has no uncommitted changes.

        Excludes untracked files that match ``.gitignore``; includes
        untracked files that don't. Mirrors ``git status --porcelain``
        emptiness exactly.
        """
        ...

    def current_branch(self, cwd: Path) -> str:
        """Return the symbolic name of HEAD (e.g. ``feature/x``).

        Returns the empty string on detached-HEAD (no branch). The
        caller decides whether that's an error in context.
        """
        ...

    def head_sha(self, cwd: Path, *, short: bool = False) -> str:
        """Return the HEAD commit SHA. ``short=True`` returns the
        abbreviated form (7-12 chars per git's defaults)."""
        ...

    def fetch(self, cwd: Path, *, remote: str = "origin") -> int:
        """``git fetch <remote>``. Returns exit code."""
        ...

    def merge_base(self, cwd: Path, a: str, b: str) -> str:
        """Return ``git merge-base <a> <b>`` (the common ancestor SHA).
        Returns the empty string if no common ancestor exists."""
        ...

    def rebase(self, cwd: Path, onto: str) -> int:
        """``git rebase <onto>``. Returns exit code.

        On non-zero, the caller is responsible for ``git rebase --abort``
        (call ``rebase_abort`` below) — this method does not auto-abort.
        """
        ...

    def rebase_abort(self, cwd: Path) -> int:
        """``git rebase --abort``. Returns exit code."""
        ...

    def fast_forward(self, cwd: Path, branch: str, to_ref: str) -> int:
        """Fast-forward ``branch`` to ``to_ref``. Returns exit code.

        Implementation strategy: ``git checkout <branch> && git
        merge --ff-only <to_ref>``. The "ff-only" guard makes the
        operation refuse if a non-FF would be required, which is the
        defensive default ``merge`` wants.
        """
        ...

    def tag(self, cwd: Path, name: str, *, ref: str = "HEAD") -> int:
        """``git tag <name> <ref>``. Returns exit code (non-zero if
        the tag already exists or ``ref`` is unknown)."""
        ...

    def tag_exists(self, cwd: Path, name: str) -> bool:
        """Return True iff a tag with this name exists locally."""
        ...

    def push(self, cwd: Path, *, remote: str = "origin", refs: list[str]) -> int:
        """``git push <remote> <refs...>``. Returns exit code."""
        ...

    def delete_branch(self, cwd: Path, name: str, *, remote: bool = False) -> int:
        """Delete a branch. ``remote=False`` ⇒ local (``git branch -D``);
        ``remote=True`` ⇒ remote (``git push origin --delete <name>``).
        Returns exit code."""
        ...

    def worktree_add(
        self,
        cwd: Path,
        path: Path,
        *,
        branch: str | None = None,
        ref: str = "HEAD",
    ) -> int:
        """``git worktree add [-b <branch>] <path> <ref>``. Returns exit code."""
        ...

    def worktree_remove(self, cwd: Path, path: Path, *, force: bool = False) -> int:
        """``git worktree remove [-f] <path>``. Returns exit code."""
        ...

    def list_tags(self, cwd: Path, *, pattern: str | None = None) -> list[str]:
        """Return tags matching ``pattern`` (or all tags if None).

        Sorted in version order so ``v1.2.10`` follows ``v1.2.9``.
        """
        ...

    def checkout(self, cwd: Path, ref: str) -> int:
        """``git checkout <ref>``. Returns exit code."""
        ...

"""Subprocess-backed implementation of ``GitClient``.

Mirrors :mod:`docex.docker.subprocess_client`. This is the *only*
module in docex permitted to ``import subprocess`` for git.

Stdout / stderr inherit from the parent process so the user sees
git's own progress output verbatim (e.g. ``Counting objects: ...``
during a fetch). Reads that need to consume git's stdout
(``current_branch``, ``head_sha``, ``list_tags``) capture and trim it
themselves.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - explicit chokepoint, see module docstring
from pathlib import Path


class SubprocessGitClient:
    """Production ``GitClient`` implementation."""

    def __init__(self, *, git_bin: str = "git") -> None:
        self._git = git_bin

    # ------------------------------------------------------------------
    # Read-only inspections
    # ------------------------------------------------------------------

    def is_clean(self, cwd: Path) -> bool:
        res = self._capture(["status", "--porcelain"], cwd=cwd)
        if res is None:
            return False
        return res.strip() == ""

    def current_branch(self, cwd: Path) -> str:
        res = self._capture(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
        if res is None:
            return ""
        name = res.strip()
        # ``HEAD`` means detached-HEAD.
        return "" if name == "HEAD" else name

    def head_sha(self, cwd: Path, *, short: bool = False) -> str:
        args = ["rev-parse"]
        if short:
            args.append("--short")
        args.append("HEAD")
        res = self._capture(args, cwd=cwd)
        return (res or "").strip()

    def merge_base(self, cwd: Path, a: str, b: str) -> str:
        res = self._capture(["merge-base", a, b], cwd=cwd)
        return (res or "").strip()

    def tag_exists(self, cwd: Path, name: str) -> bool:
        # `git tag -l <name>` prints the name iff it exists. An empty
        # stdout (or non-zero exit) ⇒ no such tag.
        res = self._capture(["tag", "-l", name], cwd=cwd)
        if res is None:
            return False
        return name in res.split()

    def list_tags(self, cwd: Path, *, pattern: str | None = None) -> list[str]:
        args = ["tag", "-l", "--sort=v:refname"]
        if pattern is not None:
            args.append(pattern)
        res = self._capture(args, cwd=cwd)
        if res is None:
            return []
        return [line.strip() for line in res.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------

    def fetch(self, cwd: Path, *, remote: str = "origin") -> int:
        return self._run(["fetch", remote], cwd=cwd)

    def rebase(self, cwd: Path, onto: str) -> int:
        return self._run(["rebase", onto], cwd=cwd)

    def rebase_abort(self, cwd: Path) -> int:
        return self._run(["rebase", "--abort"], cwd=cwd)

    def fast_forward(self, cwd: Path, branch: str, to_ref: str) -> int:
        # checkout then merge --ff-only. If checkout fails, bail.
        rc = self._run(["checkout", branch], cwd=cwd)
        if rc != 0:
            return rc
        return self._run(["merge", "--ff-only", to_ref], cwd=cwd)

    def tag(self, cwd: Path, name: str, *, ref: str = "HEAD") -> int:
        return self._run(["tag", name, ref], cwd=cwd)

    def push(self, cwd: Path, *, remote: str = "origin", refs: list[str]) -> int:
        return self._run(["push", remote, *refs], cwd=cwd)

    def delete_branch(self, cwd: Path, name: str, *, remote: bool = False) -> int:
        if remote:
            return self._run(["push", "origin", "--delete", name], cwd=cwd)
        return self._run(["branch", "-D", name], cwd=cwd)

    def worktree_add(
        self,
        cwd: Path,
        path: Path,
        *,
        branch: str | None = None,
        ref: str = "HEAD",
    ) -> int:
        args = ["worktree", "add"]
        if branch is not None:
            args.extend(["-b", branch])
        args.extend([str(path), ref])
        return self._run(args, cwd=cwd)

    def worktree_remove(self, cwd: Path, path: Path, *, force: bool = False) -> int:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        return self._run(args, cwd=cwd)

    def checkout(self, cwd: Path, ref: str) -> int:
        return self._run(["checkout", ref], cwd=cwd)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run(self, args: list[str], *, cwd: Path) -> int:
        try:
            res = subprocess.run(  # noqa: S603
                [self._git, *args],
                cwd=str(cwd),
                check=False,
            )
        except FileNotFoundError:
            # git not installed; fatal exit-code shape.
            return 127
        return res.returncode

    def _capture(self, args: list[str], *, cwd: Path) -> str | None:
        """Run ``git <args>`` and return stdout. Returns None on failure."""
        try:
            res = subprocess.run(  # noqa: S603
                [self._git, *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return None
        if res.returncode != 0:
            return None
        return res.stdout

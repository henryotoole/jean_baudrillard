"""``docex merge`` — defensive recheck + rebase + ff + tag + push.

Per [docex.md § merge] and [cicd.md § Merge]:

  1. Re-run ``check`` defensively (catches race conditions where main
     moved between ``docex check`` and ``docex merge``).
  2. Fetch origin, then rebase the developer's actual working tree
     (not a worktree).
  3. Fast-forward ``main`` to the rebased tip.
  4. Tag ``v<project.version>``; refuse if the tag already exists.
  5. Push ``main`` and the new tag.
  6. Delete the feature branch locally and on the remote.

If anything past the rebase fails, we leave the local branch in its
rebased state. The operator can inspect ``git log`` and recover by
hand — auto-unwinding is more dangerous than instructive.
"""

from __future__ import annotations

import sys

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import VersionAlreadyReleased
from docex.git.client import GitClient
from docex.pipeline.check import run_check


def run_merge(
    ctx: ProjectContext,
    docker: DockerClient,
    git: GitClient,
) -> int:
    """Run the full merge sequence. Returns process exit code."""
    project_root = ctx.project_root

    # 1. Defensive recheck ---------------------------------------------
    print("merge: running 'docex check' defensively before rebase...")
    rc = run_check(ctx, docker, git)
    if rc != 0:
        print(
            "merge: 'docex check' failed; refusing to merge. "
            "Fix the failing gates and retry.",
            file=sys.stderr,
        )
        return rc

    # 2. Identify feature branch ---------------------------------------
    feature = git.current_branch(project_root)
    if feature == "" or feature == "main":
        print(
            f"error: merge must run from a feature branch (currently {feature!r}).",
            file=sys.stderr,
        )
        return 1

    # 3. Fetch + rebase the developer's tree ---------------------------
    rc = git.fetch(project_root, remote="origin")
    if rc != 0:
        print(f"error: 'git fetch origin' exited {rc}.", file=sys.stderr)
        return rc

    rc = git.rebase(project_root, "origin/main")
    if rc != 0:
        # Abort so we don't leave the working tree mid-rebase.
        git.rebase_abort(project_root)
        print(
            f"error: 'git rebase origin/main' exited {rc}. Resolve the "
            "conflict on your feature branch and retry.",
            file=sys.stderr,
        )
        return rc

    # 4. Fast-forward main to the rebased tip --------------------------
    rc = git.fast_forward(project_root, "main", feature)
    if rc != 0:
        print(
            f"error: fast-forward of 'main' to {feature!r} exited {rc}. "
            "Manual recovery needed.",
            file=sys.stderr,
        )
        return rc

    # We're now on main with HEAD == feature's tip.

    # 5. Tag -----------------------------------------------------------
    tag_name = f"v{ctx.project.version}"
    if git.tag_exists(project_root, tag_name):
        raise VersionAlreadyReleased(
            f"tag {tag_name!r} already exists; bump project.yml's version "
            "and re-run check + merge."
        )
    rc = git.tag(project_root, tag_name, ref="main")
    if rc != 0:
        print(f"error: 'git tag {tag_name}' exited {rc}.", file=sys.stderr)
        return rc

    # 6. Push main + the new tag --------------------------------------
    rc = git.push(project_root, remote="origin", refs=["main", tag_name])
    if rc != 0:
        print(
            f"error: 'git push origin main {tag_name}' exited {rc}.",
            file=sys.stderr,
        )
        return rc

    # 7. Delete feature branch (local then remote) --------------------
    # Local first: branch -D refuses if we're on it, so checkout main
    # is already done by step 4's fast-forward.
    rc = git.delete_branch(project_root, feature, remote=False)
    if rc != 0:
        # Non-fatal: the merge succeeded; surface a warning.
        print(
            f"warning: 'git branch -D {feature}' exited {rc}; "
            "delete the local branch by hand if needed.",
            file=sys.stderr,
        )
    rc_remote = git.delete_branch(project_root, feature, remote=True)
    if rc_remote != 0:
        print(
            f"warning: deleting remote {feature!r} exited {rc_remote}; "
            "may have already been deleted.",
            file=sys.stderr,
        )

    print(f"merge: {feature!r} merged into main and tagged {tag_name}.")
    return 0

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

When the repo has no ``origin`` remote, the fetch (step 2) and push
(step 5) are skipped and the rebase integrates against local ``main``
rather than ``origin/main``. The local merge + tag still happen, so a
remote-less repo (e.g. the test projects) gets a real integration
without a hand-driven ``git merge --ff-only``.

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

    # 0. Remote preflight (fail fast) ----------------------------------
    # Prove origin is reachable + authenticated BEFORE any expensive work
    # (defensive check builds an image and runs the full suite). git
    # ls-remote exercises the identical credential path the later
    # fetch/push need, so a broken-auth environment dies here in seconds
    # instead of after a ~34-min check. On a repo with no origin (e.g. the
    # test projects) there is nothing to prove — skip and take the
    # local-only merge path. Resolving origin here also guarantees check's
    # best-effort fetch succeeds, so the defensive recheck validates
    # against fresh main rather than a stale one.
    has_origin = git.remote_exists(project_root, "origin")
    if has_origin:
        rc = git.ls_remote(project_root, remote="origin")
        if rc != 0:
            print(
                f"error: git remote 'origin' is unreachable or "
                f"unauthenticated ('git ls-remote origin' exited {rc}). "
                "Fix network / git credentials (SSH key or token) and retry. "
                "No image was built and no test was run.",
                file=sys.stderr,
            )
            return rc

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

    # 3. Resolve the trunk ref, fetching only when origin exists ------
    # On a repo with no ``origin`` remote (e.g. the test projects, which
    # deliberately have none) there's nothing to fetch from or push to —
    # we integrate against the *local* ``main`` instead, matching the
    # walker's manual ``git merge --ff-only``.
    if has_origin:
        rc = git.fetch(project_root, remote="origin")
        if rc != 0:
            print(f"error: 'git fetch origin' exited {rc}.", file=sys.stderr)
            return rc
        trunk_ref = "origin/main"
    else:
        print(
            "merge: no 'origin' remote — performing local merge only "
            "(no fetch/push).",
            file=sys.stderr,
        )
        trunk_ref = "main"

    # 4. Rebase onto the trunk, then fast-forward it -------------------
    # Inception establishes an empty ``main`` (pushed to origin), so a
    # doctrine project always has a trunk to rebase onto by first release
    # (see inception.md PART I). If it's absent, fail loudly rather than
    # inventing one: a repo with no ``main`` was not set up via inception,
    # which is outside doctrine. This replaces an older seed-trunk path
    # that tried to create ``main`` here and was itself broken (its
    # ``git checkout main`` could not check out a branch that didn't
    # exist).
    if not git.ref_exists(project_root, trunk_ref):
        print(
            f"error: {trunk_ref} not found. A doctrine project is set up via "
            "inception, which establishes an empty 'main'; see inception.md "
            "PART I. Cannot merge without a trunk.",
            file=sys.stderr,
        )
        return 1

    rc = git.rebase(project_root, trunk_ref)
    if rc != 0:
        # Abort so we don't leave the working tree mid-rebase.
        git.rebase_abort(project_root)
        print(
            f"error: 'git rebase {trunk_ref}' exited {rc}. Resolve the "
            "conflict on your feature branch and retry.",
            file=sys.stderr,
        )
        return rc

    # Fast-forward main to the rebased tip -----------------------------
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
    # Skipped on a no-remote repo; the one-line note at step 3 already
    # told the operator this is a local-only merge.
    if has_origin:
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
    # No remote feature branch to delete when there's no origin at all;
    # skip the remote delete then to avoid a warning operators can't act
    # on.
    if has_origin:
        rc_remote = git.delete_branch(project_root, feature, remote=True)
        if rc_remote != 0:
            print(
                f"warning: deleting remote {feature!r} exited {rc_remote}; "
                "may have already been deleted.",
                file=sys.stderr,
            )

    print(f"merge: {feature!r} merged into main and tagged {tag_name}.")
    return 0

# Redundant Merge Recheck

The gate checks run twice per CI/CD cycle: once in the standalone `docex check`
step, and once again as the defensive recheck at the top of `docex merge`
(`merge.py` calls `run_check` before it rebases). On projects with fast test
suites this is invisible. On a project whose suite takes ~30 minutes, it means a
full hour of testing where one run would usually have done.

## Problem - The Second Full Run Is Usually Wasted

The in-merge recheck exists to guard one specific race: `main` could have moved
between when the operator ran `docex check` and when they ran `docex merge`. If
it did, the earlier green result was validated against a now-stale trunk, and we
must not cut an immutable `v<version>` tag against it. That guard is correct and
worth keeping.

But the doctrine's stated operating model is a solitary developer taking a
feature branch to completion before rebasing back into `main`. Under that model
`main` rarely moves between the two commands — so the recheck almost always
rebuilds a byte-identical worktree, re-runs the full 30-minute suite, and
produces the same green it just produced. We are paying the full premium on
insurance against an event that, by our own assumptions, seldom fires.

## Solution - Skip the Recheck When Nothing Moved

Make the in-merge recheck conditional on `main` having actually moved.

If `origin/main` (or local `main` on a no-remote repo) sits at the same commit
it did when the standalone `check` last passed, and the working tree is still
clean, then the ephemeral feature+main worktree `merge` would build is identical
to the one `check` already validated. The earlier green is still authoritative,
so the recheck can be skipped safely — full correctness preserved, redundant run
eliminated.

The predicate is cheap: a `git rev-parse` on the trunk ref compared against the
trunk commit recorded by the last successful `check`. Only when the trunk has
advanced (or no prior check result is trusted) does `merge` fall back to running
the full recheck as it does today.

### What This Requires

- `check` records, on success, the trunk commit it validated against (and enough
  to identify the tree it checked).
- `merge` reads that record and compares it to the current trunk tip before
  deciding whether to invoke `run_check`.
- Any staleness — trunk moved, working tree dirty, no trusted prior result —
  forces the full recheck. The safe default is always to run.

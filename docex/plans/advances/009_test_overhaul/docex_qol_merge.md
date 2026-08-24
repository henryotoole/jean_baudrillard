# docex `merge` — two QoL quirks to fix

Notes for a QoL pass on the `docex merge` command. Two independent issues,
observed while running `nasmyth` (v0.9.0) down the pipeline. Each section gives the
symptom, the root cause with evidence, and — most importantly — a clear definition
of **what success looks like**, so the fix can be verified rather than guessed at.

Neither issue is a correctness bug in the merge *result*; both are about failing
fast and reading the log. There is also one latent correctness gap noted at the end.

---

## Problem 1 — `merge` wastes the full check/test time before a git auth failure

### Symptom

`docex merge` on a machine whose GitHub SSH auth was broken ran the **entire**
defensive check (build + ~34 min test suite), and only *then* died on:

```
git@github.com: Permission denied (publickey).
fatal: Could not read from remote repository.
error: 'git fetch origin' exited 128.
```

The ~34 minutes were pure waste — the failure was knowable in ~2 seconds at the top
of the command.

### Root cause

A merge run performs **two** remote fetches, handled differently:

1. **Inside `docex check`** — check builds an ephemeral worktree combining the
   feature branch with latest `main`, which needs a `git fetch origin`. Check treats
   this fetch as **best-effort**: on failure it emits
   `warning: 'git fetch origin' exited 128; continuing with potentially stale origin/main`
   and proceeds. This is deliberate — check is meant to be runnable against a
   possibly-stale or offline remote.

2. **In `merge` itself, after check passes** — merge does the *real*
   `git fetch origin` to rebase the feature branch onto latest `main`. This fetch is
   **fatal**. Rebasing-onto-fresh-main and the subsequent push are the whole point of
   merge, so they naturally run *after* the defensive check.

So the auth failure actually surfaces early (as check's tolerated warning), but the
**hard stop** is structurally last. Nothing exercises the remote in a fail-fast way
before the expensive work.

### Evidence (from the failed run's log)

- Early, tolerated: `warning: 'git fetch origin' exited 128; continuing with
  potentially stale origin/main` — emitted during check's worktree setup.
- Late, fatal: `error: 'git fetch origin' exited 128` — emitted after check reported
  `all 9 gate(s) passed` / `check: all gates and tests passed`, at merge's rebase step.

### The failure this guards against

All of merge's remote operations — fetch, push `main`, push tags, delete the remote
feature branch — need the same credential path (SSH agent → GitHub, in this case).
Any of them failing after a 34-min check is the waste to eliminate.

### What success looks like

- A **preflight at the very top of `merge`**, before it spawns `docex check`, that
  proves remote reachability + auth and hard-fails in seconds. `git ls-remote origin`
  exercises the identical SSH path the later fetch/push need and returns 128 on
  exactly this failure.
- Given broken auth, `docex merge` exits **non-zero within a few seconds**, with a
  message naming the actual problem (remote unreachable / auth), and **never builds an
  image or runs a single test**.
- Given working auth, behavior is unchanged (preflight passes silently, or with one
  line, and merge proceeds exactly as today).
- The preflight is scoped to `merge` — do **not** make `check` fatal on fetch
  failure; check's offline tolerance is intentional and used on its own.
- Optional stronger variant: `git push --dry-run origin HEAD:refs/heads/main` also
  verifies *write* permission (branch protection, etc.), not just auth. `ls-remote`
  is sufficient for the auth class of failure actually observed; dry-run push is
  belt-and-suspenders.

---

## Problem 2 — scrambled log ordering (buffering)

### Symptom

In the merge log, docex's own high-level narration appears **out of order** relative
to the subprocess output it brackets. Example ordering *as written to the file*:

1. (lines 1–1462) the whole test suite runs and tears down, ending with
   `Deleted branch docex-check/...`
2. (lines 1463–1468) the fatal `git fetch` error
3. (line 1469) `merge: running 'docex check' defensively before rebase...`
4. (lines 1473–1486) `docex check — gate results` ... `all 9 gate(s) passed`

Line 3 announces the check that already ran in lines 1–1462, and the gate results
(line 4) print after the fatal error (line 2). The file order does not reflect the
true chronology, which makes the log hard to diagnose from.

### Root cause

docex's own stdout (Python `print` / logging) is **block-buffered** because stdout is
a pipe/file, not a TTY — it flushes in ~4–8 KB blocks, largely at process exit. The
subprocesses it launches (git, docker, pytest) inherit the output fd directly and
write to it **live**. Result: subprocess output streams in real time while docex's
narration lands in a clump at the end, interleaved wherever the buffer happened to
flush.

The true chronological sequence for the run above was:
narration "running check defensively" → check's tolerated fetch warning → 34-min
check → "all gates passed" → merge's fatal rebase fetch.

### What success looks like

- docex's own narration interleaves with subprocess output in **true chronological
  order** in both the terminal and a redirected file.
- Fix is a one-liner in the shim / entrypoint: run Python unbuffered — `python -u`,
  or `PYTHONUNBUFFERED=1` in the environment docex runs under. (Line-buffering via
  `sys.stdout.reconfigure(line_buffering=True)` is an alternative but `-u` is
  simplest and covers stderr too.)
- Verify by redirecting a run to a file and confirming a narration line that precedes
  a subprocess block in code also precedes it in the file.

---

## Related latent gap (correctness, not just QoL)

Because `check` tolerates a failed fetch and continues "with potentially stale
origin/main", a `merge` whose fetch is broken currently runs its defensive check
against **stale `main`** — so the check is not actually validating the feature branch
against latest `main`, which is the one thing the defensive re-check exists to do.

The Problem-1 preflight closes this for free: if `merge` guarantees the remote is
reachable *before* running check, then check's fetch succeeds and it validates against
fresh `main`. Worth stating as an explicit success criterion:

- After the preflight lands, a `merge` that reaches the check step is guaranteed to
  have fetched latest `main` first; the defensive check never runs against a stale
  base.

---

## One-line summary

Add a fail-fast `git ls-remote origin` preflight at the top of `docex merge` (saves
~34 min on broken auth *and* guarantees the defensive check sees fresh `main`), and
run docex unbuffered (`python -u` / `PYTHONUNBUFFERED=1`) so logs read in true order.

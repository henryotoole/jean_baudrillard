# Mod 146 — Merge QoL: auth preflight + unbuffered output

**Advance:** 009 Test Overhaul, Wave 1, Mod 1 (feature **F1**).
**Systemic change:** *none* — pure bug-fix/QoL inside docex's existing
synchronous model. No new command, no contract change, no async substrate.
Design intent: [`pre_plan.md` §F1](../../advances/009_test_overhaul/pre_plan.md#f1--merge-qol-auth-preflight--unbuffered-output-small-non-systemic)
and source note [`prep/docex_qol_merge.md`](../../advances/009_test_overhaul/prep/docex_qol_merge.md).

## Goal

Two independent, low-risk changes to how `docex merge` fails and how docex logs
read:

1. **Fail-fast git-auth preflight** at the very top of `docex merge`, so a broken
   git-auth / unreachable-remote environment exits non-zero *in seconds, naming
   the auth problem, without building an image or running any test*. As a free
   side effect this closes the latent correctness gap where `merge`'s defensive
   `check` could run against a **stale `main`** (because `check` tolerates a
   failed fetch and continues).
2. **Run docex unbuffered** so docex's own narration and the live output of the
   subprocesses it launches (git, docker, pytest) interleave in **true
   chronological order** when output is redirected to a file.

## Success criteria (Advance Goal 3, SC1 + SC2)

- **SC1** — `docex merge` with broken git auth exits non-zero in seconds, naming
  the auth/reachability problem, without building an image or running any test.
  The defensive check never runs against stale `main`.
- **SC2** — docex output redirected to a file reads in true chronological order:
  a narration line that precedes a subprocess block *in code* precedes it *in the
  file*.

Explicitly **out of scope** (later mods): the recheck-skip predicate / provenance
record (F2, docex mod ~150), the async `job` substrate (F3), and the stronger
`git push --dry-run` write-permission preflight variant.

---

## Change 1 — the `merge` auth preflight

### Where the two remote fetches live today

A `merge` run touches the remote in two structurally-different ways (verified in
`src/docex/pipeline/`):

- **Inside `docex check`** — `check` builds an ephemeral worktree combining the
  feature branch with latest `main`, needing a `git fetch origin`. `check` treats
  this as **best-effort**: on failure it warns and continues "with potentially
  stale origin/main". This offline tolerance is deliberate and used by `check` on
  its own — it must **not** change.
- **In `merge` itself, after check passes** — the real `git fetch origin`
  (`merge.py` step 3) that rebases onto latest `main`; this one is fatal.

So on broken auth the hard stop is structurally *last*: `check` swallows the
failure as a warning, runs the full build + suite (~34 min observed on
`nasmyth`), and only then does merge's own fetch die at 128. All of merge's remote
ops share one credential path, so proving that path *once* up front is sufficient.

### Design

Add a `git ls-remote origin` preflight as the **first** action in `run_merge`,
before the defensive `run_check`. `git ls-remote` exercises the identical remote
credential path the later fetch/push need and returns non-zero (128) on exactly
the auth/reachability failure class observed.

Sequencing inside `run_merge`:

1. Resolve `has_origin = git.remote_exists(project_root, "origin")` **once, at the
   top** (today this is computed lower down, at step 3 — it is hoisted, and the
   later duplicate call removed).
2. **If `has_origin`:** run the `ls_remote` preflight. On non-zero, print an error
   that names the problem (remote unreachable / auth) and states that no image was
   built and no test was run, then return the exit code — *before* `run_check`.
3. **If not `has_origin`:** skip the preflight entirely (a repo with no `origin`,
   e.g. the test projects, does a local-only merge — unchanged behavior).
4. Proceed to the defensive `run_check`, then the existing rebase / ff / tag /
   push sequence, reusing the already-resolved `has_origin`.

### Why this also closes the stale-`main` gap (for free)

Once the preflight guarantees `origin` is reachable+authenticated *before* `check`
runs, `check`'s best-effort fetch succeeds, so the defensive recheck validates the
feature branch against **fresh** `main` — the one thing that recheck exists to do.
No change to `check`'s tolerance is needed; the guarantee falls out of ordering.

### Touched source

- `src/docex/git/client.py` — add `ls_remote(cwd, *, remote="origin") -> int` to
  the `GitClient` Protocol.
- `src/docex/git/subprocess_client.py` — implement it: `git ls-remote <remote>`
  with **stdout suppressed** (the ref listing is noise) and **stderr inherited**
  (so the real auth error is visible to the operator). Returns the exit code;
  `127` on `FileNotFoundError`, consistent with `_run`.
- `src/docex/pipeline/merge.py` — hoist `has_origin`, add the preflight, keep the
  rest of the state machine intact.
- `tests/conftest.py::FakeGitClient` — add a scriptable `ls_remote` (records the
  call; honors `exit_codes[("ls_remote", remote)]`, default 0).

## Change 2 — unbuffered output

### Root cause

docex's own stdout (Python `print`/logging) is **block-buffered** when stdout is a
pipe/file (not a TTY), flushing in ~4–8 KB blocks largely at process exit, while
the subprocesses it launches inherit the fd and write **live**. Redirected to a
file the narration lands in a clump at the end, scrambled relative to the
subprocess output it brackets.

### Design

Set **`ENV PYTHONUNBUFFERED=1` in `docex/Dockerfile`**. This is the correct single
point:

- Every docex invocation runs through the versioned image, so one line covers the
  terminal path and the redirected-file path, and both stdout and stderr.
- It is **version-pinned** into the image — the deterministic home for an
  image-level behavior — rather than a per-call flag.
- No change to every `print` site; the image entrypoint is the `docex` console
  script (a Python process), which `PYTHONUNBUFFERED` unbuffers wholesale.

This matches F1's named options (`python -u` / `PYTHONUNBUFFERED=1`). Considered
and rejected: (a) `-e PYTHONUNBUFFERED=1` in the version-independent shim — would
retroactively touch *every* docex version and is out of scope for a
single-version mod; (b) in-process `sys.stdout.reconfigure(line_buffering=True)` —
more code, per-site risk, and F1 did not name it.

### Touched source

- `docex/Dockerfile` — add `ENV PYTHONUNBUFFERED=1`.

---

## Testing plan

docex's process (`docex_process.md`): unit tests by default; an integration test
only when behavior crosses a real boundary. Manual-test pause is **waived** for
this mod per the advance (comprehensive manual exercise happens once at
close-out, plan step 13). Automated coverage this mod adds:

**Change 1 (unit, in `tests/unit/test_pipeline_merge.py`):**
- Broken auth ⇒ fast exit: `fake_git.exit_codes[("ls_remote", "origin")] = 128`;
  patch `run_check` to a **spy** and assert it is **never called**, no mutating
  git op ran (`fetch`/`rebase`/`fast_forward`/`tag`/`push`), and `run_merge`
  returns 128. This is the SC1 "no image built, no test run" assertion at the
  seam docex controls (the preflight gates the whole rest of the command).
- Ordering: preflight (`ls_remote`) is recorded in `fake_git.calls` **before**
  the defensive check runs (extend the existing order-tracking test).
- No-origin repo (`has_origin=False`): `ls_remote` is **not** called; the existing
  local-only merge path still passes.
- Working auth (default): `ls_remote` called once, returns 0, merge proceeds
  exactly as today (existing happy-path test stays green).

**Change 2 (unit guard):**
- A cheap alignment-guard test asserting `docex/Dockerfile` declares
  `ENV PYTHONUNBUFFERED=1` (same pattern as docex's existing alignment guards,
  e.g. `test_collection_partition.py`). A full behavioral ordering test would need
  an image build + a redirected subprocess run — disproportionate and flaky for a
  unit suite; the behavior is confirmed inherently by every redirected run and at
  advance close-out. **Design question Q2 below** asks whether sarge wants more
  than the guard here.

Full `python -m pytest tests` must be green in the review step.

---

## Doctrine-text amendments (require operator approval — see Q1)

Per `docex_process.md`, doctrine prose is docex's upstream spec and is changed
*first*, and **only with operator sign-off**. F1's handling rule: land the
doctrine amendment as part of this mod (the way a normal mod updates core-planning
docs — i.e. at the corporal's documentation step, *not* inside `implementation.md`
and *not* by the implementor). The preflight changes documented `merge` behavior,
so it warrants a line in two places. Proposed minimal wording:

- **`doctrine/infrastructure/cicd.md` §Merge → Process** — add a leading step:
  > 1. Preflight the remote with `git ls-remote origin`: fail fast (in seconds) if
  >    `origin` is unreachable or unauthenticated, before building any image or
  >    running any test. Skipped on a repo with no `origin` remote. This also
  >    guarantees the defensive recheck below sees fresh `main`.

  (existing steps 1–5 renumber to 2–6.)

- **`doctrine/infrastructure/docex.md` §`merge`** — append to the description:
  > Before any of this, it preflights the remote with `git ls-remote origin` and
  > exits non-zero in seconds if `origin` is unreachable or auth fails — without
  > building an image or running a test (skipped when the repo has no `origin`).

The unbuffered change is an internal image-diagnostic quality property and does
**not** appear to warrant doctrine-prose text; if it is documented anywhere it is
in docex's own core planning docs (masterplan / Dockerfile notes), handled at the
mod's documentation step. **Q3** confirms.

---

## Design questions

- **Q1 (doctrine approval — required).** Do you approve the two doctrine one-liners
  above (`cicd.md` §Merge Process step, `docex.md` §`merge` sentence)? I will land
  them myself at the documentation step, not delegate them to the implementor. I
  will not touch doctrine prose without your go-ahead.
- **Q2 (unbuffered test depth).** I plan to cover SC2 with a Dockerfile
  alignment-guard unit test (asserts `ENV PYTHONUNBUFFERED=1` present) and rely on
  close-out manual exercise for the behavioral ordering proof. Acceptable, or do
  you want a heavier behavioral/integration ordering test in this mod?
- **Q3 (unbuffered locus).** I recommend `ENV PYTHONUNBUFFERED=1` in the
  `Dockerfile` (version-pinned, single point) over the shim or in-process
  reconfigure. Confirm this is the locus you want.
- **Q4 (preflight strength).** I am using `git ls-remote origin` (covers the
  auth/reachability class actually observed). The stronger
  `git push --dry-run origin HEAD:refs/heads/main` (also verifies *write*
  permission) is deferred as belt-and-suspenders per the source note — confirm
  ls-remote is sufficient for this mod.

Nothing here changes docex's command contract, so I believe all four are within a
mod-cycle corporal's authority *except* Q1, which needs your doctrine sign-off.

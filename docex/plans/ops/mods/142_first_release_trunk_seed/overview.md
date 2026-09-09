# Mod 142 — Establish an empty `main` at inception; remove merge's dead seed-trunk path

## Problem

On a project's very first production release, `docex merge` fails. It tries to
integrate the feature branch against `origin/main`, which does not yet exist,
falls into a "seed-trunk" path (`if trunk_missing:`), and that path is itself
broken: `git.fast_forward(project_root, "main", feature)` does
`git checkout main && git merge --ff-only feature`, and the `checkout main`
fails with `pathspec 'main' did not match` because `main` does not exist to
check out. Merge exits "Manual recovery needed" and leaves the repo untouched.

The root cause is upstream of merge: `inception.md` never establishes `main`.
PART I creates the feature branch `inception_and_first_draft` and lands every
setup/draft commit on it, so the trunk is absent until the first release's
`docex merge` is asked to invent it — the one path that is broken.

Full design record: `docex/plans/advances/008_housekeeping/references/first_release_merge_bug.md`.

## Design

Two parts, both pre-approved by the plan ruling.

### Part 1 — doctrine: establish `main` at inception

Edit `doctrine/practices/inception.md` PART I. Insert a new step **between**
the current step 5 (`cd` into the project) and the current step 6 (create the
`inception_and_first_draft` branch):

> Ensure the initial branch is `main` (the doctrine trunk), make an empty
> initial commit, and push it so `origin/main` exists:
> ```
> git commit --allow-empty -m "Initial commit"
> git push -u origin main
> ```

Then the existing "create and switch to `inception_and_first_draft`" step
follows, now branching off `main`. Every Part I–IV commit still lands on the
feature branch as today; only the empty trunk root is added ahead of it. At
PART V the first `docex merge` takes the normal rebase-onto-`origin/main` path,
and the first-release seeding case never arises.

**Renumbering.** Inserting a step renumbers PART I's steps 6→7, 7→8, 8→9,
9→10. Two cross-references into PART I step numbers shift and must be updated:

- `inception.md` itself, line ~177: "…appended by `docex_install.sh` in
  **PART I step 8**" — install-docex is the old step 8, now step 9 → update to
  "PART I step 9".
- `docex/test_projects/PRE_CUT_CHECKLIST.md` B.1, line ~195: "Per `inception.md`
  **PART I step 7**" (project-root layout) — set-up-basic-structure is the old
  step 7, now step 8 → update to "PART I step 8".

References that do **not** shift, verified:
- `test_projects.md § Inception-flow divergences`: "PART I steps 3–5 skipped"
  (repo create / clone / cd) are all *before* the insertion → stay valid.
  "PART III steps 6–7 skipped" — PART III is untouched → stays valid.
- Historical mod record `_advance_doctrine_shape_and_tiers.md` cites "PART I
  step 8" as a record of a past change — a historical artifact, left as-is.
- `docex.md` and `cicd.md` reference `inception.md` only generically / by PART,
  no PART I step numbers → unaffected.
- The `inception` skill links to `inception.md` with no anchors and no step
  numbers, and no heading changes → not touched, pointers still resolve.

### Part 2 — code: remove `merge.py`'s dead seed-trunk path

In `docex/src/docex/pipeline/merge.py`, the `if trunk_missing:` block (~lines
84–105) that seeds `main` via `fast_forward` is unreachable in the sanctioned
flow once inception guarantees the trunk, and is itself broken. Remove it.

Replace it with an honest **precondition failure**: if `trunk_ref` does not
resolve, print a clear error naming inception as the setup path and return
non-zero, rather than a cryptic downstream rebase/checkout error or a re-added
seed. Then rebase onto `trunk_ref` and fast-forward `main` (the existing normal
path, unchanged).

Two traps handled:
1. **`fast_forward` stays.** It is used twice today: the seed path (removed) and
   the normal rebase path (~line 119, kept). `fast_forward` remains in
   `git/client.py` + `git/subprocess_client.py` — the normal path still needs
   it. Confirmed it has no other callers.
2. **Push-skip simplification.** The remote-delete guard `if has_origin and not
   trunk_missing:` (~line 169) loses its `trunk_missing` term: past the new
   precondition guard the trunk always exists, so the condition simplifies to
   `if has_origin:`. The normal-path push (`if has_origin:`) is unchanged. No
   dangling `trunk_missing` variable remains.

**No-origin repos (the test projects) are unaffected.** They have no `origin`,
so `trunk_ref = "main"` (local), which exists (`git init -b main`); the
precondition passes, merge rebases onto local `main`, tags, skips push, and
deletes only the local branch — exactly as before.

### Drift fixes carried by Part 2 (comments/docstrings only)

Removing the seed path falsifies two comments that describe it. Both are
comment/docstring-only, directly about the behavior being removed, and are
corrected here to keep the code honest (no behavior change):

- `check.py` first-release-mode banner (~line 864) claims "`docex merge` will
  seed `origin/main` from this feature branch." Merge no longer seeds — the
  clause is dropped/reworded. **check's first-release mode itself is kept**: it
  still serves the no-`origin` test projects, where `origin/main` never
  resolves. It does not depend on merge's `trunk_missing`.
- `git/client.py` `ref_exists` docstring says it lets "check and merge switch
  into a … path that seeds main." Reworded to reference only `check`'s
  first-release detection.

### Tests

Update `docex/tests/unit/test_pipeline_merge.py`:
- Remove/repurpose the three seed-path tests: `test_merge_seeds_main_on_empty_origin`,
  `test_merge_skips_remote_feature_delete_on_empty_origin`,
  `test_merge_no_origin_seeds_main_when_local_main_absent`.
- Add a test asserting the new behavior: a missing trunk (`origin/main` absent
  with an origin present; and no local `main` on a no-origin repo) makes merge
  **fail loudly** (non-zero, no rebase, no tag, no push) rather than seed.
- The normal-path tests and the two no-origin-with-local-`main` tests
  (`test_merge_no_origin_skips_fetch_and_push`,
  `test_merge_no_origin_deletes_local_branch_only`) stay green unchanged.

### Six-artifact drift check

1. **Doctrine** — `inception.md` PART I insertion + renumber + self-ref fix.
2. **`plans/core/*.md`** — `test_projects.md § Inception-flow divergences`: add
   that the new empty-`main` step is *adapted* for the test projects — they
   `git init -b main` in place (already noted) but **skip `git push -u origin
   main`** (no origin). masterplan/`release_flow.md`/cicd.md: the `merge`
   descriptions say "rebases onto main, tags, pushes" — normal path only, no
   seeding claim → **no edit needed** (confirmed the code now matches them
   better than before).
3. **src/tests** — `merge.py` + merge tests above; `fast_forward` retained.
4. **`doctrine_excerpts/` + `index.yml`** — no resource maps to inception steps
   or merge seeding → **no change** (confirmed).
5. **Skill pointers** — `inception` skill: generic link, no anchors/step refs,
   no heading change → **not touched, resolves**.
6. Plus the two comment/docstring drift fixes in `check.py` and `git/client.py`.

## Design questions

None blocking. One decision made within authority, flagged for the reviewer:

- **check.py's first-release mode and its comment.** I am *keeping* check's
  empty-`origin/main` first-release mode (it is still needed for the no-`origin`
  test projects) and only correcting its now-false comment about merge seeding.
  Removing check's mode would be a larger change the plan did not sanction and
  would break check on the test projects. If the reviewer wants check's
  first-release mode revisited too, that is a separate follow-up.

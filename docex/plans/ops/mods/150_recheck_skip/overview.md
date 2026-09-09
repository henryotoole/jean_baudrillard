# Mod 150 — Redundant-recheck elimination (F2 / SC4)

**Advance 009 — Test Overhaul, Wave 2, Mod 5.** Completes Advance Goal 3.
Design intent: [pre_plan SC4](../../advances/009_test_overhaul/pre_plan.md#sc4--a-pipeline-green-acquires-provenance--the-gate-becomes-trust-forward),
[advance_plan Wave 2 Mod 5](../../advances/009_test_overhaul/advance_plan.md).

## Problem

`docex check` runs the full gate + build + test (~30 min) and passes. The operator
then runs `docex merge`, whose first real action is a **defensive `run_check`** —
another ~30 min — even when nothing has moved since the standalone check. Under the
doctrine's solitary-developer model `main` rarely moves between the two commands, so
that second run almost always rebuilds a byte-identical worktree and re-derives the
same green. We pay the full premium on insurance against an event our own model says
seldom fires.

The defensive recheck exists to guard one real race: `main` (or the feature branch)
moving between `check` and `merge`, which would validate the earlier green against a
now-stale trunk before an immutable `v<version>` tag is cut. That guard is correct
and stays. This mod makes it **conditional**: `check` records what it validated, and
`merge` *trusts that record forward* — skipping the recheck only when the record
provably still describes reality, and running the full recheck on any doubt.

## Design

Two moving parts: `check` **acquires provenance** (writes a record on success);
`merge` **trusts it forward** (a commit-based skip predicate with a safe default).

### 1. The provenance artifact — `.docex/checks/`

A new machine-local, gitignored artifact joining `.docex/runs/` in the `.docex/`
scratch dir (`.docex/` is already gitignored — no gitignore change needed). It is a
**new module `src/docex/pipeline/check_record.py`**, modelled on `jobs/record.py`.

- **Distinct from the SC3 job record**, deliberately. `.docex/runs/` answers *"did
  this invocation pass"*; `.docex/checks/` answers *"what tree a passing check
  blessed, for `merge` to trust forward."* They are not folded into one another.
- **One file: `.docex/checks/latest.json`.** `merge` only ever trusts the *most
  recent* successful check, so a single latest-wins record is sufficient; a new
  green overwrites it atomically (temp file + `os.replace`). *(Design question 2 —
  flagging the single-file choice for confirmation.)*
- **Schema — exactly the five fields SC4 fixes:**

  ```json
  {
    "feature_tip":     "<full sha of the feature branch tip at check time>",
    "origin_main":     "<full sha of the trunk (origin/main) checked against>",
    "merged_tree_sha": "<git tree SHA of the validated, rebased worktree HEAD>",
    "checked_at":      "<ISO-8601 UTC timestamp>",
    "docex_version":   "<ctx.project.docex_version>"
  }
  ```

- `merged_tree_sha` is the authoritative *"what was tested"* — recorded for audit and
  a possible future stronger comparison. It is **not** part of the v1 skip predicate,
  which is commit-based per SC4 ("identical commit inputs deterministically produce
  identical content").
- **Reads degrade safely**: `read_check_record()` returns `None` on a missing dir,
  missing file, unreadable file, or corrupt/partial JSON — never raises. This is what
  makes "no record / unreadable record → run the check" fall out for free.

Module API (mirrors `jobs/record.py` idioms):
`checks_dir(root)`, `record_path(root)` → `.docex/checks/latest.json`,
`write_check_record(root, rec)` (atomic), `read_check_record(root) -> CheckRecord | None`,
and a `CheckRecord` dataclass with `to_json`/`from_json`.

### 2. `check` writes the record — on success only

At the very end of `run_check` (`pipeline/check.py`), after the full gate + build +
test sequence has passed (immediately before the final `return 0`), gather and write
the record. Written **only** on a fully-green run; a failed check writes nothing (an
early `return`/`raise` never reaches the write).

The four data inputs, and how `check` already has each:

| Field | Source in `run_check` |
| --- | --- |
| `feature_tip` | `git.head_sha(project_root)` — feature-branch tip in the operator's tree (unchanged by the worktree rebase, which runs on a temp branch). |
| `origin_main` | the trunk sha `check` validated against: `git.rev_parse(project_root, "origin/main")` when an `origin` exists; `git.rev_parse(project_root, "main")` on a no-origin repo (local-trunk mode); `""` in empty-origin / first-release mode. |
| `merged_tree_sha` | `git.rev_parse(worktree, "HEAD^{tree}")` — the tree of the rebased worktree that was actually built and tested. |
| `checked_at` / `docex_version` | `now_iso()` / `ctx.project.docex_version`. |

Because `.docex/` is gitignored, writing the record does **not** dirty the working
tree, so it cannot disturb `check`'s own `worktree_clean` gate or `merge`'s
`is_clean` guard. Since mod 149 `check` runs inside a vessel container with the
project bind-mounted at its host path, so `.docex/checks/latest.json` written in the
vessel lands in the real project tree and persists after the vessel exits — exactly
as `.docex/runs/` already does.

### 3. `merge` trusts it forward — the commit-based skip predicate

In `run_merge` (`pipeline/merge.py`), between the `ls-remote` preflight (step 0) and
the defensive recheck (step 1), decide whether to skip.

**How `merge` learns each of the four predicate inputs:**

| Input | Mechanism |
| --- | --- |
| current `origin/main` tip | **Reuse the `ls-remote` preflight.** The preflight is upgraded to learn the trunk tip in the *same* round-trip it already makes: `git ls-remote origin refs/heads/main` both proves reachability/auth (its exit code, exactly as today) **and** yields `origin/main`'s current sha. No extra fetch. On a no-origin repo, the trunk tip is the local `git rev-parse main`. |
| current feature tip | `git.head_sha(project_root)`. |
| working-tree cleanliness | `git.is_clean(project_root)`. |
| docex version | `ctx.project.docex_version` vs the record's `docex_version`. |

**The predicate (skip iff *all* hold):**

```
rec = read_check_record(project_root)              # None ⇒ do not skip
skip = (
    rec is not None
    and rec.docex_version == ctx.project.docex_version
    and rec.feature_tip and rec.feature_tip == head_sha(project_root)
    and rec.origin_main and rec.origin_main == origin_main_now
    and git.is_clean(project_root)
)
```

The `rec.feature_tip and …` / `rec.origin_main and …` truthiness guards forbid a
skip when either recorded value is empty (first-release / empty-origin records
`origin_main=""`), so two empty strings can never compare equal into a spurious skip.

**When `skip` is true**, `merge` prints a one-line note naming the trusted commits and
proceeds straight to the rebase — `run_check` is never called. **When it is false**,
`merge` runs the full defensive `run_check` exactly as today (which, on success,
refreshes `.docex/checks/latest.json`).

### The doctrinal invariant (stated as a rule, not a behavior)

> `merge` trusts a recorded green forward and skips its defensive recheck **only**
> when the trunk and the feature tip are both at the commits the last successful
> `check` recorded, the working tree is clean, and the docex version matches. **Any**
> staleness — trunk moved, feature moved, tree dirty, no record, an unreadable or
> corrupt record, or a docex-version mismatch — forces the full recheck. The recorded
> green is a **performance cache, never a correctness gate**: the safe default is
> always to run.

This mitigation is the point of SC4's "systemic, not just a feature" framing — the
footgun is trusting a stale green, and the guard against it is doctrinal, so it lands
in the doctrine text (below) as a rule.

### Small `GitClient` additions

Two methods on the `GitClient` protocol + `SubprocessGitClient` (both trivial,
`_capture`-backed):

- `rev_parse(cwd, rev) -> str` — `git rev-parse <rev>`, stripped, `""` if
  unresolvable. Used for `origin_main`, local `main`, and `HEAD^{tree}`.
- `ls_remote_sha(cwd, ref, *, remote="origin") -> tuple[int, str]` — `git ls-remote
  <remote> <ref>`, returning `(exit_code, sha)`; `sha == ""` when the ref is absent
  or the command failed. This **replaces the preflight's `git.ls_remote(...)` call**
  in `merge` (still fails fast on a non-zero exit with the identical message), folding
  reachability-proof and tip-learning into one call. The existing `ls_remote` method
  stays on the protocol (unused by merge after this) to avoid gratuitous removal.

## Test plan — both branches + every staleness reason

Per Advance Goal 3 SC3, **both** the skip branch and a forced-recheck case for
**each** staleness reason are covered in the unit suite. (There is no manual-test
phase for docex mods; the advance's close-out step 13 does the live exercise.)

- **`tests/unit/test_check_record.py` (new):** write→read round-trip; `read` returns
  `None` on missing dir, missing file, and corrupt/partial JSON; atomic overwrite.
- **`tests/unit/test_pipeline_check.py`:** after a green `run_check` (reusing the
  existing happy-path harness that stubs compile/build/test), assert
  `read_check_record()` returns a record with the expected `feature_tip` /
  `origin_main` / `docex_version`; assert a **failed** check writes **no** record.
- **`tests/unit/test_pipeline_merge.py`** (the core deliverable) — a `run_check` spy
  asserts called / not-called, plus a crafted `read_check_record`:
  - **skip:** matching record + clean tree + version match → `run_check` **not**
    called, merge still rebases/tags/pushes, rc 0.
  - **forced — no record:** `read_check_record → None` → `run_check` called.
  - **forced — trunk moved:** `origin_main_now != rec.origin_main` → called.
  - **forced — feature moved:** `rec.feature_tip != head` → called.
  - **forced — tree dirty:** `is_clean False` → called.
  - **forced — unreadable/corrupt record:** returns `None` (asserted via a corrupt
    file through the real reader) → called.
  - **forced — version mismatch:** `rec.docex_version != ctx` → called.
- **`FakeGitClient` (`tests/conftest.py`)** gains `rev_parse` (scriptable map,
  default `head`) and `ls_remote_sha` (returns `(rc, remote_main_sha)`), plus a
  `remote_main_sha` attribute. Existing merge preflight tests that assert
  `ls_remote` is invoked are updated to `ls_remote_sha`; `test_jobs_check_merge.py`
  is checked for the same.

## Doctrine amendments (for sign-off before implementation.md)

Per the docex process, doctrine text is amended first and **requires operator
approval**. SC4's named radius is `cicd.md` §Check + §Merge and `docex.md` ### check
+ ### merge. Proposed edits:

**`cicd.md` §Check Step — add a step to `#### Process`:**
> 7. On a fully-green check, record the validated state to `.docex/checks/` — the
>    feature tip, the `origin/main` commit checked against, the merged worktree's
>    tree SHA, a timestamp, and the docex version. This provenance record is what
>    `merge` trusts to skip a redundant defensive recheck (see [§ Merge](#merge)). It
>    is written only on success; a failed check records nothing.

**`cicd.md` §Merge — replace process step 2:**
> 2. Re-run the gate checks defensively — **unless a trusted green makes it provably
>    redundant.** The check step records the state it validated; `merge` skips the
>    recheck **iff** `origin/main` and the feature tip are still at the commits that
>    record names, the working tree is clean, and the docex version matches. **Any**
>    staleness — trunk moved, feature moved, dirty tree, no record, an unreadable
>    record, or a docex-version mismatch — forces the full recheck. This is a rule,
>    not merely an optimization: the recorded green is a **performance cache, never a
>    correctness gate**, so the safe default is always to run. The `git ls-remote
>    origin` preflight (step 1) already learns `origin/main`'s current tip, so the
>    predicate adds no network round-trip.

**`docex.md` ### check — append a sentence:**
> On a fully-green run, `check` records what it validated to `.docex/checks/` (the
> feature tip, the `origin/main` commit, the merged tree SHA, a timestamp, and the
> docex version); `merge` trusts that record to skip a redundant defensive recheck.
> The record is written only on success and is machine-local (gitignored).

**`docex.md` ### merge — append (before the passthrough caveat):**
> `merge` **trusts a recent green forward**: it skips its defensive recheck when
> `origin/main` and the feature tip are at the commits `check` last recorded in
> `.docex/checks/`, the working tree is clean, and the docex version matches —
> reusing the `git ls-remote` preflight to learn the trunk tip rather than fetching
> again. **Any** staleness (trunk or feature moved, dirty tree, a missing or
> unreadable record, a version mismatch) forces the full recheck; the record is a
> performance cache, never a correctness gate, so the safe default is always to run.

*(The masterplan / Filesystem-Surface mention of `.docex/checks/` is a docex core
planning doc — updated in this mod's Documentation step, not in implementation.md,
per the mod process.)*

## Boundaries

- Does **not** weaken "CI/CD is always full." The full check still runs as `check`;
  standalone `docex check` always runs full; `merge` without a trusted record runs
  full. `merge` only trusts a *just-run* green forward instead of repeating it.
- Does **not** touch the test-tier split, the slot axis, or scoped runs (other mods).
- Does **not** change what "green" means in the pipeline — same gates, same build,
  same suite. Only *whether the second, redundant run happens*.

## Design questions for the C.O.

1. **Doctrine wording** — the four amendments above need approval before I write
   `implementation.md` (docex process rule: doctrine is amended first, with operator
   sign-off).
2. **Single `latest.json`** — I chose one latest-wins record over a per-feature/-sha
   keyed store, because `merge` only ever trusts the most recent green. Confirm this
   is the intended shape (it is the cheapest thing that satisfies the predicate).
3. **Folding the preflight** — I learn `origin/main`'s tip by upgrading the existing
   `merge` preflight from `git ls-remote origin` to `git ls-remote origin
   refs/heads/main` (same credential path, same fail-fast). This is the faithful
   reading of SC4's "reuse the preflight rather than add a redundant fetch." Confirm
   acceptable.

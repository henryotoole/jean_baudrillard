# Vendored Dependencies

Pinned third-party code. **Do not hand-edit** — local changes are overwritten on re-sync.
Re-sync deliberately: re-clone the source at a new commit, copy it in, and bump the record
below.

## skill-creator

- **Source:** https://github.com/anthropics/skills — `skills/skill-creator/`
- **Pinned commit:** `57546260929473d4e0d1c1bb75297be2fdfa1949`
- **Vendored:** 2026-06-18
- **License:** see `skill-creator/LICENSE.txt`
- **Provides — the Anthropic skill-eval standard:**
  - `scripts/run_loop.py` — trigger eval / description optimizer (single-skill: eval set of
    `{query, should_trigger}`, 60/40 train/test split, 3 runs/query, proposes a better
    description, selects `best_description` by held-out test score). Shells out to `claude -p`.
  - `scripts/run_eval.py`, `scripts/aggregate_benchmark.py`, `agents/grader.md`,
    `eval-viewer/` — outcome eval (skill-performance) machinery.
  - `references/schemas.md` — the eval JSON schemas (`evals.json`, `grading.json`,
    `benchmark.json`, …).
- **Why pinned:** determinism, per docex's "pin everything" ethos. A behavioral eval must
  produce comparable scores across runs; an upstream change should not silently shift them.

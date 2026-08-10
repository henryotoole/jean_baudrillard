# Evaluating skills

The **single source of truth** for the behavioral evaluation of doctrine skills — it answers two questions: do skill descriptions *trigger* correctly, and do skills *perform* correctly when used? The methodology lives here in full. The executable machinery and data it drives live in `$jb/skill_iter/eval/` — at the repo root, a sibling to `docex/` and to the `skills/` tree that holds this skill, **not** inside this skill (tooling, not doctrine prose). Pointed to under [Tooling](#tooling) and read on demand.

```
skill_iter/eval/
├── run_suite.py            suite-level trigger eval (+ queries.json)
├── run_loop.py             single-skill description optimizer (+ run_eval.py, improve_description.py)
├── aggregate_benchmark.py  rolls per-case outcome gradings into a benchmark
├── schemas.md              evals.json / grading.json / benchmark.json shapes
├── agents/                 grader.md, comparator.md, analyzer.md
└── outcome/<skill>/evals.json   per-skill outcome cases
```

`skill_iter/eval/` is **forked** from Anthropic's `skill-creator` and is now ours to maintain; it is not a pinned upstream.

## The System

The forked standard assumes **self-contained** skills evaluated in isolation. The doctrine skills we evaluate differ in two ways, and those differences are why we adapt rather than adopt:

- **They are router + thread** — thin pointers into a shared doctrine graph — so the with/without-skill delta measures **navigation value** (did the thread route to the right files), **not knowledge**: the doctrine files exist on disk either way. An outcome failure can therefore indict the **underlying doctrine file**, not just the skill, so an outcome eval doubles as a doctrine-content check.
- **They form a competing set** — many descriptions in context at once — so a trigger eval must run with *all* skills installed to see a sibling stealing another's queries. Testing one description in isolation can't.

This methodology is **behavioral** (does the set route and perform). The sibling `cohere` skill covers **static** soundness of the *doctrine* corpus (broken links, skill-reference coverage, Resident-stratum discipline, within-doctrine contradiction). Don't duplicate `cohere`'s checks here.

## Trigger Eval

Does each skill's description fire when it should — and, because the skills compete, *only* when it should?

`queries.json` (in `skill_iter/eval/`) is the single source of truth for the query set. Each entry:

```json
{"query": "a realistic user prompt", "expect": "skill-name" | null, "note": "why / which boundary"}
```

- `expect` — the skill that *should* win, or `null` when no doctrine skill should fire (covered by the Resident stratum, general knowledge, or out of scope).
- Queries must be **substantive** (multi-step, would genuinely benefit from a skill). Trivial one-step prompts don't trigger skills regardless of description quality and make poor tests.
- The valuable entries are the **boundary near-misses**: a query whose `expect` is a *sibling* skill (or `null`) probes whether one description is poaching another's territory — e.g. line-level logging (`null`, not `telemetry-design`); "fix docex's release code" (`docex-edit`) vs. "my release isn't picking up a secret" (`cicd-pipeline`).

Seed the set per activity: each skill's activity → a should-trigger query; each pair of adjacent activities → a near-miss should-not-trigger query that probes the boundary between them. Expand to 8-10 should-trigger per skill before optimizing descriptions for real. **Get the query set human-reviewed before optimizing** — bad queries produce bad descriptions; read `queries.json` directly for review.

Two ways to consume the one query file:

- **Suite-level routing** (`run_suite.py`, our net-new piece) — installs all skills via `--plugin-dir`, runs each query through the model with every description present, records *which* skill it actually loads, and scores per-skill **recall** (expected skill loaded → a miss means doctrine silently skipped), per-skill **precision** (didn't fire when it shouldn't → a false fire wastes context / steals a trigger), and a **confusion matrix** surfacing which pair of descriptions overlaps. The runner **bails at each query's first tool call**, so nested agents never do real work — only the routing decision is measured.

  ```
  python3 run_suite.py --runs-per-query 3 --out last_run.json     # full suite, modal vote over 3 runs
  python3 run_suite.py --limit 3 --runs-per-query 1               # smoke first
  python3 run_suite.py --grep docex --runs-per-query 3            # re-check one skill's boundary after a description change
  ```
  `--grep SUBSTR` keeps only queries whose text or note contains `SUBSTR` (the full competing set stays installed, so poaching is still real) — the fast path for the "re-run on every description change" cadence. `competing_skills` in the queries file is optional; absent it, the runner auto-discovers the installed skills from `<plugin_dir>/skills/*/SKILL.md`, so a focused subset file needn't restate the list.
  Tune `--num-workers` / `--timeout` / `--model`. Output: per-skill recall & precision, overall accuracy, confusion matrix; misroutes to stderr.

- **Per-skill optimization** (`run_loop.py`, single-skill description optimizer) — derive its `[{query, should_trigger}]` set from `queries.json` with `should_trigger = (expect == "X")`; every other query (siblings *and* nulls) becomes a should-not-trigger near-miss for `X`. So the one suite file feeds the optimizer for any skill with only a small adapter. `run_loop.py` runs the eval+improve loop (train/test split, modal vote) and prints the best description it found as JSON.

## Outcome Eval

Does a skill, when used, actually produce a doctrine-correct result — and beat the no-skill baseline? Per-skill, **gated** (run before a doctrine-affecting `docex` cut), built on the `evals.json` case format + the grader/comparator/analyzer agent roles.

A good case targets doctrine that **diverges from a capable model's priors** — an arbitrary choice it couldn't reconstruct. (The `contracts` demonstrator qualifies: the loop-liveness tick with its fixed 10s/30s thresholds, and the rule that only `web`-network core services serve HTTP health at all, are not produced without the doctrine; the inferable parts — contract format, file path — show ≈zero delta. Doctrine where a skill earns its keep is exactly the non-inferable part.) Mark each `expectations` entry as a **delta driver** (doctrine-specific, non-inferable — where the skill must win) or **confirmatory** (inferable, expect ≈zero delta); the delta-driver scores are the skill's measured value.

### The run pattern

Triggering is already proven by the trigger eval, so an outcome run *ensures* the skill is used and compares results (spawned from a context restarted with the on-disk strata active, per Isolation):

1. **with-skill:** a subagent given the prompt plus "read `./skills/<skill>/SKILL.md` and the doctrine it points to".
2. **baseline:** a subagent given the same prompt plus "work only from general knowledge, do not read doctrine files".
3. **Grade** the outputs (below). The **delta on delta-driver expectations is the skill's measured value.**

Case files live at `outcome/<skill>/evals.json` — add one per skill you evaluate; see `schemas.md` for the shape.

### In-tree mutation cases (graded on a diff)

Most skills produce a *fresh artifact* from a prompt, so the prompt + optional static `files` is the whole input and the produced content is what you grade. A few skills instead **mutate an existing project in place** — `project-cohere` reads a project's core planning docs against its code and heals drift. There the input is a whole doctrine project *in a specific drift state* and the graded artifact is the **diff** the run produces — including the *empty* diff, which is the correct result when the project is already coherent.

These get a fixture harness alongside the usual `evals.json`, at `outcome/project-cohere/` (see its `README.md`). The shape:

- **States are `base + overlay`, not full copies** — one coherent `_base` project plus a per-state overlay carrying only the files that differ, so every state is provably `base + exactly one intended drift`. That isolation is the point: one state per finding case.
- **`run_outcome.py` runs the whole loop in one command** — per case and configuration it assembles, runs a headless `claude -p` to cohere the scratch project, captures the diff, grades it with another `claude -p` (the shared `grader.md`), and prints the with-skill vs baseline delta. Grading needs an LLM but not an interactive agent. Under it, **`run_fixture.py` does the deterministic scaffolding** — `assemble` copies base+overlay into a scratch git repo *outside this repo* and records a baseline commit; `capture` emits the diff against the baseline (files changed, insertions/deletions, `is_empty`, unified diff). Drive those two by hand when debugging one stage.
- **Grade on the diff, not an exact expected tree** — "mark unimplemented" and "edit the doc to match code" have free wording, so exact-match is too brittle; hand the diff + the case's `expectations` to `agents/grader.md` as usual.
- **The no-op is a first-class delta driver** — a naive "make the docs consistent" baseline fiddles or deletes; the doctrine-correct behavior is often to change nothing (already coherent) or to *mark, not delete*. That gap is exactly the skill's measured value.

### Grading: two complementary lenses

- **Expectation grading (`agents/grader.md`)** is the objective, gated measure. Grade each output against the case's `expectations` independently, with evidence, emitting a `grading.json` (per `schemas.md`). Prefer deterministic checks. The **delta-driver pass/fail gap between with-skill and baseline is the headline number.** This is what gates a cut.
- **Blind comparison (`agents/comparator.md` → `agents/analyzer.md`)** is the unbiased holistic check, and it specifically guards against *grader bias* — the temptation to score the answer you expected. Hand the comparator the two outputs labeled **A/B with the skill identity stripped**; it picks a winner on a content+structure rubric without knowing which is with-skill. Then the analyzer un-blinds and explains *why* the winner won, yielding concrete improvement suggestions for the skill or the doctrine file behind it. Reach for this when a hand-grade feels subjective, or when you want improvement signal, not just a pass/fail. (The agents are written around comparing two *skills*; in our use, side B is the no-skill baseline — read "loser skill" as "the doctrine the baseline lacked".)

### Aggregating across cases (`aggregate_benchmark.py`)

Once more than one outcome case exists, persist each run's `grading.json` and roll them up with `aggregate_benchmark.py` into a `benchmark.json` (shapes in `schemas.md`). The analyzer's **benchmark mode** then surfaces cross-case patterns the per-case numbers hide — an expectation that passes with *and* without the skill (doesn't differentiate), one that's flaky, or a skill that adds latency without adding pass rate. Run aggregation before a gated cut to read the whole skill set at once rather than case-by-case.

## Tooling

The runners, the data, and the agent roles. **Read on demand** when you actually run an eval. The Python tools need Python 3 and the `claude` CLI (`run_suite.py` / `run_loop.py` shell out to `claude -p`); `quick_validate.py` needs PyYAML.

- [run_suite.py](../../../skill_iter/eval/run_suite.py) + [queries.json](../../../skill_iter/eval/queries.json) — suite-level trigger runner and its labeled query set.
- [run_loop.py](../../../skill_iter/eval/run_loop.py) — single-skill description optimizer (uses `run_eval.py`, `improve_description.py`).
- [schemas.md](../../../skill_iter/eval/schemas.md) — `evals.json`, `grading.json`, `benchmark.json` shapes.
- [agents/grader.md](../../../skill_iter/eval/agents/grader.md), [agents/comparator.md](../../../skill_iter/eval/agents/comparator.md), [agents/analyzer.md](../../../skill_iter/eval/agents/analyzer.md) — the grader, blind-comparator, and post-hoc/benchmark analyzer roles.
- [aggregate_benchmark.py](../../../skill_iter/eval/aggregate_benchmark.py) — cross-case outcome rollup.
- [outcome/contracts/evals.json](../../../skill_iter/eval/outcome/contracts/evals.json) — a worked outcome case to copy.

## Notes

- **Read order.** Skim *The System*, then drop into *Trigger* or *Outcome* depending on what you're running. Pull in the Tooling files only when you actually execute.
- **Cadence.** Trigger evals on every skill or description change. Outcome evals (gated) before a doctrine-affecting `docex` cut.
- **Sibling boundary.** This skill (`skill-iteration`) both authors skills and measures them — the [Author the body](../SKILL.md#author-the-body) and [Evaluate](../SKILL.md#evaluate) phases are two ends of one activity. `cohere` owns *static* soundness of the doctrine corpus. Keep behavioral measurement here and static soundness there.

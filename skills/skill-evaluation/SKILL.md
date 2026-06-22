---
name: skill-evaluation
description: Doctrine for evaluating skills — trigger evals (do skill descriptions fire when they should, without stealing each other's triggers) and outcome evals (does a skill actually produce the doctrine-correct result). Use this whenever you are authoring or changing a skill, editing a skill description, validating a new skill, or before a doctrine-affecting docex cut — anytime you need to measure whether the skills route and perform, not just whether they exist.
---

# skill-evaluation

This skill is the **single source of truth** for the behavioral evaluation of doctrine skills — it answers two questions: do skill descriptions *trigger* correctly, and do skills *perform* correctly when used? The methodology lives here in full; the runners, the query/case data, and the vendored Anthropic standard are pointed to under [Specific Information](#specific-information) and read on demand.

The eval tooling is `$jb/skill_eval`, a top-level sibling to `docex` (tooling, not doctrine prose). Its layout:

```
skill_eval/
├── vendor/skill-creator/   pinned Anthropic skill-eval standard (see vendor/VENDORED.md)
├── trigger/                suite-level trigger eval (run_suite.py + queries.json)
└── outcome/                per-skill outcome cases (<skill>/evals.json)
```

## The System

Two layers, built on the vendored Anthropic `skill-creator` standard. That standard assumes **self-contained** skills; ours are **router + thread** (thin pointers into a shared doctrine graph) and they form a **competing set**. Those two differences are why we adapt rather than adopt:

- **Trigger → run at suite level.** The stock optimizer tests one skill in isolation, which can't see a sibling stealing its queries. We run with *all* doctrine skills installed and score the full confusion matrix, so trigger-stealing is visible.
- **Outcome → reinterpret the baseline.** For a router+thread skill the with/without-skill delta measures **navigation value** (did the thread route to the right files), **not knowledge** — the doctrine files exist on disk either way. An outcome failure can therefore indict the **underlying doctrine file**, not just the skill, so this doubles as a doctrine-content check.

This skill is **behavioral** (does the set route and perform). Its sibling `cohere` is **static** corpus soundness (broken links, skill-reference coverage, Resident-stratum discipline, within-doctrine contradiction). Don't duplicate `cohere`'s checks here.

## Trigger Eval

Does each skill's description fire when it should — and, because the skills compete, *only* when it should?

`queries.json` is the single source of truth for the query set. Each entry:

```json
{"query": "a realistic user prompt", "expect": "skill-name" | null, "note": "why / which boundary"}
```

- `expect` — the skill that *should* win, or `null` when no doctrine skill should fire (covered by the Resident stratum, general knowledge, or out of scope).
- Queries must be **substantive** (multi-step, would genuinely benefit from a skill). Trivial one-step prompts don't trigger skills regardless of description quality and make poor tests.
- The valuable entries are the **boundary near-misses**: a query whose `expect` is a *sibling* skill (or `null`) probes whether one description is poaching another's territory — e.g. line-level logging (`null`, not `telemetry-design`); "fix docex's release code" (`docex-edit`) vs. "my release isn't picking up a secret" (`cicd-pipeline`).

Seed the set from [classification.md](../../docex/plans/campaigns/001_skill_update/classification.md): each activity → a should-trigger query; each cross-activity pair → a near-miss should-not-trigger query. Expand to 8-10 should-trigger per skill before optimizing descriptions for real. **Get the query set human-reviewed before optimizing** — bad queries produce bad descriptions (the vendored `assets/eval_review.html` renders a set for review, or read `queries.json` directly).

Two ways to consume the one query file:

- **Suite-level routing** (our net-new piece, `run_suite.py`) — installs all skills via `--plugin-dir`, runs each query through the model with every description present, records *which* skill it actually loads, and scores per-skill **recall** (expected skill loaded → a miss means doctrine silently skipped), per-skill **precision** (didn't fire when it shouldn't → a false fire wastes context / steals a trigger), and a **confusion matrix** surfacing which pair of descriptions overlaps. The runner **bails at each query's first tool call**, so nested agents never do real work — only the routing decision is measured.

  ```
  python3 run_suite.py --runs-per-query 3 --out last_run.json     # full suite, modal vote over 3 runs
  python3 run_suite.py --limit 3 --runs-per-query 1               # smoke first
  ```
  Tune `--num-workers` / `--timeout` / `--model`. Output: per-skill recall & precision, overall accuracy, confusion matrix; misroutes to stderr.

- **Per-skill optimization** (vendored `run_loop.py`, single-skill description optimizer) — derive its `[{query, should_trigger}]` set from `queries.json` with `should_trigger = (expect == "X")`; every other query (siblings *and* nulls) becomes a should-not-trigger near-miss for `X`. So the one suite file feeds the stock optimizer for any skill with only a small adapter.

## Outcome Eval

Does a skill, when used, actually produce a doctrine-correct result — and beat the no-skill baseline? Per-skill, **gated** (run before a doctrine-affecting `docex` cut), built on the vendored `evals.json` + grader machinery.

A good case targets doctrine that **diverges from a capable model's priors** — an arbitrary choice it couldn't reconstruct. (The `contracts` demonstrator qualifies: the mandated `/health`+`{version}` and `/health/<dependency>` endpoints are not produced without the doctrine; the inferable parts — contract format, file path — show ≈zero delta. Doctrine where a skill earns its keep is exactly the non-inferable part.)

### Isolation (non-negotiable)

The methodology that makes a number trustworthy — ignore it and the numbers lie.

1. **Restart the context with the trimmed Resident strata active before spawning eval subagents.** The failure mode is a stale parent snapshot: a session that loaded the *full* doctrine before the SKILL.md / Resident trim carries it in memory, and any subagent it spawns inherits that snapshot — so the baseline measures nothing. Restarting the session so the parent re-reads the on-disk (trimmed) `CLAUDE.md` makes the parent memory reflect the state under test; subagents then inherit a clean memory. This context restart — not the subprocess mechanism — is the real isolation lever.
2. **Subagents are the right mechanism.** With the parent memory correct, spawn subagents (the Agent tool / the vendored `with_skill` vs `without_skill` pattern). There is no need to shell out to `claude -p` for isolation.
3. **Isolate the baseline by access, not cwd.** The **with-skill** subagent reads the skill and the doctrine files it points to; the **baseline** subagent works from general knowledge only, with no access to the doctrine on disk.

### The run pattern

Triggering is already proven by the trigger eval, so an outcome run *ensures* the skill is used and compares results (spawned from a context restarted with the trim active, per Isolation):

1. **with-skill:** a subagent given the prompt plus "read `./skills/<skill>/SKILL.md` and the doctrine it points to".
2. **baseline:** a subagent given the same prompt plus "work only from general knowledge, do not read doctrine files".
3. Grade each output against the case's `expectations` (objectively verifiable). The **delta on doctrine-specific expectations is the skill's measured value.** Prefer deterministic checks; the vendored `agents/grader.md` covers the grader role.

Case files live at `outcome/<skill>/evals.json` — add one per skill you evaluate. Heavy aggregation (`aggregate_benchmark.py`) and the eval-viewer are deferred until case volume justifies them.

## Specific Information

The runners, the data, and the vendored standard. **Read on demand** when you actually run an eval. The vendored scripts need Python 3 and the `claude` CLI (`run_loop.py` / `run_suite.py` shell out to `claude -p`).

- [trigger/run_suite.py](../../skill_eval/trigger/run_suite.py) and [trigger/queries.json](../../skill_eval/trigger/queries.json) — the suite-level trigger runner and its labeled query set.
- [outcome/contracts/evals.json](../../skill_eval/outcome/contracts/evals.json) — the outcome case-file shape (per-skill `expectations`).
- [skill-creator/SKILL.md](../../skill_eval/vendor/skill-creator/SKILL.md), [references/schemas.md](../../skill_eval/vendor/skill-creator/references/schemas.md), and [agents/grader.md](../../skill_eval/vendor/skill-creator/agents/grader.md) — the vendored standard: the description optimizer (`run_loop.py`), the eval JSON schemas, and the grader role. Pinned; see [vendor/VENDORED.md](../../skill_eval/vendor/VENDORED.md) — do not hand-edit.

## Thread

- **Read order.** Skim *The System*, then drop into *Trigger* or *Outcome* depending on what you're running. Pull in the Specific-Information files only when you actually execute.
- **Cadence.** Trigger evals on every skill or description change. Outcome evals (gated) before a doctrine-affecting `docex` cut.
- **Sibling boundary.** `cohere` owns *static* corpus soundness (links, coverage, Resident discipline, contradiction); this skill owns *behavioral* validation (routing and performance). Keep them separate.

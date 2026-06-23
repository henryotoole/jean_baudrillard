# skill_iter

Tooling for *iterating on skills* — authoring them and improving their quality. A top-level sibling to `docex` (tooling, not doctrine prose). It backs one self-contained skill:

- **`skills/skill-iteration`** — the whole skill loop: authoring a skill (or restructuring an existing one) and measuring whether it triggers and performs (trigger evals + outcome evals). Authoring and evaluation are one activity, so they live in one skill.

That SKILL.md and its `references/` are the **source of truth for methodology**. This directory holds the executable machinery and data they point at — never the methodology prose.

## Layout

```
create/   authoring/packaging tooling
  package_skill.py    bundle a skill directory into a .skill
  quick_validate.py   validate SKILL.md frontmatter

eval/     evaluation tooling + data
  run_suite.py          suite-level trigger eval (all doctrine skills installed; recall/precision/confusion)
  queries.json          labeled trigger query set (the single source of truth for queries)
  run_loop.py           single-skill description optimizer (eval + improve loop, train/test split)
  run_eval.py           single-skill trigger eval (used by run_loop)
  improve_description.py proposes a better description from eval feedback
  aggregate_benchmark.py rolls per-case outcome gradings into a benchmark
  utils.py              shared SKILL.md parsing
  schemas.md            JSON schemas (evals.json, grading.json, benchmark.json)
  agents/
    grader.md           grades one output against a case's expectations
    comparator.md       blind A/B comparison of two outputs (with-skill vs baseline)
    analyzer.md         post-hoc: why the winner won → improvement suggestions
  outcome/<skill>/evals.json   per-skill outcome cases
```

## Provenance

`eval/` and `create/` are **forked** from Anthropic's `skills/skill-creator` (see `LICENSE.txt`). We no longer track upstream; the fork is ours to maintain. The code is organized into `create/` (authoring/packaging) and `eval/` (measurement) folders — an internal split for legibility, not a skill boundary; both halves back the single `skill-iteration` skill. The HTML-presentation surface (eval-viewer, HTML report/review generators) was dropped — results are read as JSON/markdown. Any future re-harvest from upstream is a deliberate, manual merge.

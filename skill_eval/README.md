# skill_eval

Behavioral evaluation tooling for doctrine skills — a top-level sibling to `docex` (tooling, not doctrine prose). Trigger evals (do descriptions route correctly) and outcome evals (do skills perform correctly).

**The methodology and run instructions live in the `skill-evaluation` skill: [`skills/skill-evaluation/SKILL.md`](../skills/skill-evaluation/SKILL.md).** This directory holds only the runners and data it points to:

- `trigger/` — the suite-level trigger runner (`run_suite.py`) and its labeled query set (`queries.json`).
- `outcome/` — per-skill outcome cases (`<skill>/evals.json`).
- `vendor/` — the pinned Anthropic skill-creator standard; do not hand-edit, see `vendor/VENDORED.md`.

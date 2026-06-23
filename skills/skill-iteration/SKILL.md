---
name: skill-iteration
description: Author, restructure, and evaluate skills — capture intent, draft the SKILL.md and its body (thread or self-contained), measure that it triggers and performs, and package it. Use whenever the user wants to build, author, scaffold, restructure, or improve a skill, asks how a skill's body or description should be written, OR wants to measure whether skills trigger correctly (trigger evals) or produce the doctrine-correct result (outcome evals) — anytime the work is on a skill itself.
---

# skill-iteration

Iterating on skills — one activity, one skill. Authoring and evaluation are not separate jobs: you draft a skill, measure whether it triggers and performs, improve it on that signal, and package it, and it almost never makes sense to do one of those without the others. So the whole loop lives here:

**capture intent → author the body → evaluate → improve → package.**

This is a **self-contained** skill, forked from Anthropic's `skill-creator` and reshaped to this doctrine's skill model. Two parts back it, and they sit in **different places**:

- **Methodology prose** — the writing guides and the full evaluation methodology — lives in this skill's own `references/` folder (alongside this `SKILL.md`).
- **Executable machinery** — packaging, validation, and eval runners plus their data — lives in `$jb/skill_iter/`: a tooling directory at the **repo root**, a sibling to `skills/` (and to `docex/`), **not** inside this skill. It is repo-level tooling because its query set and outcome cases span *every* doctrine skill, not just this one (ours to maintain — see `skill_iter/README.md`).

Every bare `skill_iter/...` path in this document is relative to the repo root (`$jb`); run those commands from there.

## Capture intent

Before drafting, pin down four things — extract what you can from the conversation already (if the user said "turn this into a skill," the workflow, tools, step sequence, and corrections are often already in the history) and ask the user only for the gaps:

1. **What should the skill enable** the agent to do?
2. **When should it trigger** — what phrasings and contexts? This becomes the description, the primary triggering mechanism.
3. **What's the output** — format, files, side effects?
4. **Does it need test cases?** Skills with objectively verifiable outputs (file transforms, data extraction, code generation, fixed workflows) benefit; subjective ones (writing style, design) usually don't. Suggest a default, let the user decide.

**Interview and research before writing test prompts.** Proactively ask about edge cases, input/output formats, example files, success criteria, and dependencies. If research would help (similar skills, docs, best practices), do it first — in parallel via subagents when available — so you come to the user with context rather than questions. Settle this before drafting test prompts.

Then write the frontmatter. The **description** carries all the "when to use" information — it is the always-in-context trigger interface. Models tend to *under*-trigger skills, so write the description as a crisp, slightly **pushy** activity trigger: name the concrete phrasings and contexts that should fire it, not just what it does. (e.g. not "Build a dashboard for internal data" but "…use this whenever the user mentions dashboards, data visualization, or wants to display company data, even if they don't say 'dashboard'.")

## Author the body

One decision governs everything downstream — *what kind of skill is this?* — and it forks the body, the structure, and the evaluation path the same way:

- **Self-contained skill** (carries its own corpus of knowledge): read [references/conventional_body.md](references/conventional_body.md).
- **Thread skill** (a thin router into the doctrine corpus — `type: thread`): read [references/thread_body.md](references/thread_body.md).

Read **exactly one**. They are mutually exclusive: a self-contained body duplicates a corpus on purpose, a thread body must never duplicate the doctrine it points at. Choosing the wrong guide produces a structurally wrong skill, so settle the skill's type before opening either file.

## Evaluate

A skill isn't done when it's written — it's done when it's measured. Evaluation answers two questions: does the description *trigger* when it should (and only then), and does the skill *perform* — produce the doctrine-correct result — when used? This skill is the **single source of truth** for that behavioral methodology; its sibling `cohere` owns *static* soundness of the doctrine corpus (broken links, coverage), so don't reach there for behavioral measurement.

Read [references/evaluation.md](references/evaluation.md) when you reach this phase — it carries the full methodology (trigger evals, outcome evals, grading) and routes to the runners and data in `skill_iter/eval/`. **Description optimization** is part of trigger eval, not a separate authoring step: the optimizer (`run_loop.py`) drives a query set — for a doctrine skill the shared `queries.json`, for a standalone skill a set you derive.

Cadence: run trigger evals on every skill or description change; run outcome evals (gated) before a doctrine-affecting `docex` cut.

## Package

Packaging is orthogonal to skill type. The packager validates the SKILL.md frontmatter (via `quick_validate.py`) and bundles the folder into a `.skill` file:

```bash
python3 skill_iter/create/package_skill.py <path/to/skill-folder> [output-dir]
```

Run from the repo root. Direct the user to the resulting `.skill` file. When *improving* an existing skill, preserve its original name and directory — don't mint a `-v2`.

## Reference files

- [references/conventional_body.md](references/conventional_body.md) — how to write a self-contained skill body (anatomy, progressive disclosure, writing patterns and style). Read when [Author the body](#author-the-body) selects self-contained.
- [references/thread_body.md](references/thread_body.md) — how to write a thread-skill body that routes into the doctrine; points at the doctrine's `skills.md` form spec. Read when [Author the body](#author-the-body) selects thread.
- [references/evaluation.md](references/evaluation.md) — the full trigger + outcome evaluation methodology and the `skill_iter/eval/` tooling it drives. Read when you reach [Evaluate](#evaluate).

Read the body guide that matches the skill's type (not both); read `evaluation.md` once you're measuring.

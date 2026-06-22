---
name: skill-creation
description: Create a new skill or improve an existing one — capture intent, draft the SKILL.md and its body, and package it. Use whenever the user wants to build, author, scaffold, restructure, or improve a skill (thread or self-contained), or asks how a skill's body / instructions should be written. For *measuring* whether a skill triggers or performs, this hands off to the `skill-evaluation` skill — this skill is authoring, not evaluation.
---

# skill-creation

Authoring tooling for skills. The loop is **draft → test → improve → package**, and this skill owns the **draft** and **package** ends of it plus the writing of the skill body. It deliberately does *not* own evaluation: measuring whether a skill triggers or performs is a separate activity, and this skill routes that work to `skill-evaluation` (see [Test & evaluate](#test--evaluate)). Keeping authoring and evaluation apart is what lets `skill-evaluation` stay the single source of truth for eval methodology — restating any of it here would just create drift.

This skill is built on Anthropic's vendored `skill-creator` standard (`../../skill_eval/vendor/skill-creator/SKILL.md`). Most of that standard applies unchanged; this body keeps the authoring parts and routes the rest.

## Capture intent

Before drafting, pin down four things — extract what you can from the conversation already and ask the user only for the gaps:

1. **What should the skill enable** the agent to do?
2. **When should it trigger** — what phrasings and contexts? This becomes the description, the primary triggering mechanism.
3. **What's the output** — format, files, side effects?
4. **Does it need test cases?** Skills with objectively verifiable outputs benefit; subjective ones (writing style, design) usually don't. Suggest a default, let the user decide.

Then write the frontmatter. The **description** carries all the "when to use" information — it is the always-in-context trigger interface — and it should be authored as a crisp, slightly *pushy* activity trigger so the skill fires when it should. The interview/research detail in the vendored `## Creating a skill` section is the reference if you need more.

## Author the body

One decision governs everything downstream — *what kind of skill is this?* — and it forks the body, the structure, and (later) the evaluation path the same way:

- **Self-contained skill** (carries its own corpus of knowledge): read [references/conventional_body.md](references/conventional_body.md).
- **Thread skill** (a thin router into the doctrine corpus — `type: thread`): read [references/thread_body.md](references/thread_body.md).

Read **exactly one**. They are mutually exclusive: a self-contained body duplicates a corpus on purpose, a thread body must never duplicate the doctrine it points at. Choosing the wrong guide produces a structurally wrong skill, so settle the skill's type before opening either file.

## Test & evaluate

Evaluation is a distinct activity with its own skill — **do not restate its methodology here**. Route based on the same fork as the body:

- **Thread / doctrine skill** → follow the `skill-evaluation` skill ([../skill-evaluation/SKILL.md](../skill-evaluation/SKILL.md)). It owns suite-level trigger evals (the skills compete, so a skill must be tested with its siblings present) and outcome evals (does the skill route to the doctrine-correct result).
- **Self-contained skill** → the vendored `skill-creator` eval sections apply directly (`../../skill_eval/vendor/skill-creator/SKILL.md`, "Running and evaluating test cases").

**Description optimization** is part of trigger eval, not a separate authoring step — it routes the same way. For doctrine skills, `skill-evaluation` drives the vendored `run_loop.py` optimizer against the shared query set; for self-contained skills, run `run_loop.py` directly per the vendored "Description Optimization" section.

## Package

Packaging is orthogonal to skill type and reused from the vendored standard:

```bash
python -m scripts.package_skill <path/to/skill-folder>
```

Run it from the vendored `skill-creator` directory. Direct the user to the resulting `.skill` file. When *improving* an existing skill, preserve its original name and directory — don't mint a `-v2`.

## Reference files

- [references/conventional_body.md](references/conventional_body.md) — how to write a self-contained skill body (anatomy, progressive disclosure, writing patterns and style). Lifted from the vendored standard.
- [references/thread_body.md](references/thread_body.md) — how to write a thread-skill body that routes into the doctrine. Points at the doctrine's `skills.md` form spec.

Read whichever one [Author the body](#author-the-body) selected — not both.

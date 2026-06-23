# Authoring a thread-skill body

How to write the markdown body of a **thread skill** — a thin *router + thread* into the doctrine corpus, not a self-contained body of knowledge. (For a self-contained skill, use `conventional_body.md` instead — the two are mutually exclusive.)

## The spec lives in the doctrine

The authoritative form for thread skills is **[skills.md](../../../doctrine/skills/skills.md)** — read it now and follow its `## Form` section. This file does not restate that spec (doing so would be the exact duplication thread skills exist to avoid); it only adds the *how-to-apply* while authoring. In brief, `skills.md` requires:

- An `# H1` (the skill name) plus a one-line router intent.
- A mandatory `## General Information` section: a short line stating it holds critical orienting info **with an instruction to read all referenced files now**, then the links.
- An optional `## Specific Information` section for detailed mechanisms: a short line **instructing that its referenced files be read on demand**, then the links.
- An optional `## Thread` section carrying the narrative that binds the references — read-order, how files interact, and the boundary calls to sibling skills.
- Frontmatter marking it a thread skill:
  ```yml
  metadata:
    type: thread
  ```

## How to apply it while authoring

- **Split by activity, not topic.** A thread skill's boundary is an *action* the agent takes (making a release, designing telemetry), not a subject area. If you're tempted to name it after a topic, you're drawing the boundary wrong — that's the signal to re-cut it around what the agent is *doing*.
- **Route, don't restate.** The body's job is (a) to point at specific files or sections, and (b) to supply the thread that ties them together. Never copy doctrine prose into the skill — a copy drifts from its source, and the doctrine files are the single source of truth. If you find yourself explaining *what a doctrine file says*, replace the explanation with a link.
- **Express progressive disclosure through where you point.** `## General Information` is what the agent must read immediately (read-now); `## Specific Information` is detail it reads only if it finds it needs it (read-on-demand). The general→specific axis is carried by *how the body directs attention*, not by inlining content.
- **Use the doctrine link conventions.** References to doctrine files take the form `[file.md](../../doctrine/path/to/file.md)`. References to *sibling skills* are plain code-formatted names (`cicd-pipeline`), not file links.
- **The one ongoing cost is pointer health.** Because the body routes rather than copies, a doctrine edit doesn't require rewriting the skill — it only requires the pointers still resolve. Keep links live (no dangling references, no pointers to moved sections); this is checked mechanically by the `cohere` meta-skill.

## When the body is done

Validate it the way every doctrine skill is validated — through this skill's [Evaluate](../SKILL.md#evaluate) phase: suite-level trigger evals (so a sibling can't steal its triggers) and outcome evals (against doctrine-correct results). Authoring and evaluation are the same activity here; don't treat shipping the body as the finish line.

---
name: inception
description: Doctrine for standing up a brand-new project from nothing — the inception flow that takes a masterplan through repo setup, design, infrastructure smoke test, first draft, and first production release. Use this whenever you are creating a new doctrine project or running any part of inception, even if the word "inception" is never used.
metadata:
  type: thread
---

# inception

Inception is a single ordered procedure whose later parts hand off to other activities; read the flow, then follow the thread into the skill that owns each sub-step rather than working from memory.

## General Information

The inception flow, start to finish. **Read this now.**

[`inception.md`](../../doctrine/practices/inception.md) — PARTs I–V: repo and structure setup, design of the core planning docs, infrastructure smoke test, first-draft mod cycles, and first production release. The procedure of record for a new project.

## Thread

Inception's later parts are entry points into other activities — follow the owning skill rather than reconstructing it here.

- Writing `infra.yml` and the PART III smoke test → `infra-compile`; the preinfra checks within it → `preinfra-setup`.
- PART V (first production release) → `projinfra-setup` for the production project tier, then `cicd-pipeline` for the release pipeline.
- Designing core planning docs (PART II) and the PART IV mod cycles follow the Resident `docs.md` and `modifications.md` practices, already in context.

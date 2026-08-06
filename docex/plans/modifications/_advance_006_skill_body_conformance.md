# Advance Brief: Thread-skill body conformance

**Status: deferred to advance 006; not a 1.7.0 cut blocker.** Raised during
advance 005's `cohere` audit as finding F21 and escalated at mod 121's design
review, where sarge ruled defer. Logged here so the finding is not silently
dropped between advances.

## The defect

[`skills/docex-edit/SKILL.md`](../../../skills/docex-edit/SKILL.md) declares
`metadata: type: thread` in its frontmatter but carries none of the body
structure a thread skill is defined by. Per
[`doctrine/skills/skills.md`](../../../doctrine/skills/skills.md), a thread
skill body is an H1 plus intro, a mandatory `## General Information` section, and
optional `## Specific Information` / `## Thread` sections. `docex-edit` has the
frontmatter declaration and none of the sections.

The skill is **not** broken — it triggers and it works. The declaration is simply
untrue, which makes it an honesty defect rather than a correctness one. That is
the whole reason it is deferrable.

This is **pre-existing**, not advance-005 residue. Nothing in the process-type
solidification work touched this skill's body or its frontmatter.

## Why it was deferred rather than fixed in mod 121

Mod 121 is a fix pass whose governing constraint is *no rule changes* — every
edit repairs prose, repairs an example so it obeys a rule already written, or
routes an existing file. Restructuring a skill body is none of those.

The decisive argument is narrower than scope discipline. **A skill's body and
description are its trigger surface**, and the doctrine already owns a process
for changing a trigger surface: `skill-iteration`, which exists precisely because
trigger surfaces must be *measured* — trigger evals for whether the skill loads
when it should, outcome evals for whether it produces the doctrine-correct
result. Restructuring `docex-edit`'s body inside a fix mod would change a trigger
surface with none of the machinery that exists to verify trigger surfaces. The
fix would be unmeasured, and an unmeasured trigger change is exactly the class of
edit `skill-iteration` was built to prevent.

## Recommendation for advance 006

**Generalize the audit before fixing the instance.** `docex-edit` was found by a
one-off read during a corpus sweep, which is not a reason to believe it is the
only offender. The check is mechanical and cheap:

> For every skill under `$jb/skills/` declaring `metadata: type: thread`, assert
> the body carries an H1, an intro, and a `## General Information` section.

Two directions worth considering when this is taken up:

1. **Ship the check**, alongside `linkcheck.py` and `verify_examples.py` in
   `skills/cohere/executor/`. Advance 005's lesson, stated in mod 121 § 11, is
   that a hand check which passes once is not a check. A conformance rule that is
   only ever verified by reading will drift again.
2. **Resolve each offender the right way round.** For any given skill the fix may
   be *either* restructuring the body to match the declaration *or* correcting
   the declaration to match the body — `type: thread` may simply be the wrong
   label for a skill that was never a router. Decide per skill, and run the
   resulting body through `skill-iteration`'s evals either way.

## Reading

- [`doctrine/skills/skills.md`](../../../doctrine/skills/skills.md) — the thread
  skill body structure this is measured against.
- [`doctrine/doctrine.md § Skills`](../../../doctrine/doctrine.md#skills) — what
  a thread skill is for: router plus thread, not duplicated prose.
- [`skills/skill-iteration/SKILL.md`](../../../skills/skill-iteration/SKILL.md)
  — the process that owns trigger-surface changes, and the evals a body
  restructure must pass.
- [Mod 121 overview § 5](./121_cohere_fix_pass/overview.md) — the finding as
  escalated (F21 / Q5) and the ruling.

---
stratum: resident
---

# Modifications

This documents the standard modification process for designing and implementing changes into the codebase of a project.

A modification or 'mod' is the fundamental unit of change to a codebase; whether it be to add a feature or fix a bug. A fixed process (below) ensures that:
1. A mod's changes can be easily reviewed
2. Project documentation is kept up-to-date with code.

This process is **intentionally agnostic** to broader release cycles, branching, and version control workflow. Formal branching and merging is outside of the scope of a single modification cycle. Git is used within the cycle only for the practical purpose of giving the review step a clean diff to read against. Aside from the two commits specified below, git activity should not occur within a mod cycle.

## Process

The process is performed by you (the agent) as follows:
1. **Initial Plan**: The goal and scope of the mod will be communicated to you within an initial prompt, either in prose form or as a reference to a prompt file.
	1. If you have followup or clarifying questions, ask them now.
2. **Pre-Mod Checks**
	1. Ensure that the current branch is **not** `main`. If it is, end the turn noting that you cannot proceed for this reason.
3. **Design**: Creating `overview.md`.
	1. Create a new [modification folder](./docs.md) in the modification documentation in `$pr/plans/modifications`.
	2. Outline the mod's change at a design level and write the design plan to `overview.md` in the mod folder. Include any "design questions" which shake out during design at the bottom of this file.
	3. End the turn. Report to whoever assigned this mod cycle that you've completed the mod's design overview (note the filepath), request their approval, and direct their attention to any unresolved "design questions".
4. **Implementation**: Creating `implementation.md`.
	1. You create `implementation.md` with implementation steps based on the current codebase. The implementation document should be written such that it can be handed to a fresh context.
		1. *DO NOT* write instructions in the implementation to update core planning docs.
		2. *DO* include instructions to update any core service [contracts](../infrastructure/infrastructure.md#contracts) that will need to change for the mod.
	2. After finishing the file, make a simple git commit with the message `mod ${mod_number} design done, impl. steps written`. This makes it easy to see what has changed after the implementation execution.
5. **Execution**: You kick off a separate, fresh-context sub-agent that executes the mod implementation in the codebase, re-runs tests, etc.
6. **Review**: You review the implementation:
	1. Discover what has changed by checking what new non-committed changes exist. 
	2. Assess whether those changes show drift from the original design intention.
	3. Small drifts can be tolerated or fixed at your discretion. Large drifts or failures should be escalated to whoever assigned this mod cycle for inspection.
	4. Ensure relevant tests are all green.
7. **Manual Test**: By default you pause here for external testing; the initial prompt may explicitly waive this.
	1. End the turn to let whoever assigned this mod cycle perform any manual testing they desire.
8. **Documentation**:
	1. You update the [core planning docs](./docs.md) to reflect the newly modified codebase. Core planning docs should **never** link to modification documents. Relevant design info from the modification docs should be copied over.
	2. Update [changelog](../infrastructure/version_control.md) with a quick description of changes.
9. **Cleanup**:
	1. Commit with the message `mod ${mod_number} complete; designed, implemented, and documented.`
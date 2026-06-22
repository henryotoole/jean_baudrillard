---
stratum: resident
---

# Modifications

This documents the standard modification process for designing and implementing changes into the codebase of a project.

This process is **intentionally agnostic to release cycles, branching, and version control workflow**. Multiple modifications often run consecutively between releases. Git appears in this document only as a tool: a single prescribed commit at the design/implementation boundary (step 3.2) exists so the review step has a clean diff to read against. Any other git activity — further commits within a mod, branching, releases — is orthogonal and out of scope.

## Process

The process is performed by the LLM agent as follows:
1. Ensure that the current branch is **not** `main`.
	1. If the codebase *is* on `main`, alert the operator and do not proceed.
2. Create a new [modification folder](./docs.md) in the modification documentation at $pr/plans/modifications, and add an `overview.md` file outlining the change at a design level.
	1. Iterate on the `overview.md` plan with the operator, working through ramifications and details.
3. Design is complete - time to create implementation steps.
	1. LLM agent creates `implementation.md` with implementation steps based on the current codebase. The implementation document should be written such that it can be handed to a fresh context.
		1. DO NOT write instructions in the implementation to update core planning docs.
		2. DO include instructions to update any core service [contracts](../infrastructure/infrastructure.md#contracts) that will need to change for the mod.
	2. After finishing the file, make a simple git commit with the message "mod ${mod_number} design done, impl. steps written". This makes it easy to see what has changed after the implementation execution.
4. LLM agent kicks off a separate, fresh-context sub-agent to execute the mod implementation in the codebase, re-runs tests, etc.
	1. This sub-agent should always be run in the *foreground* - this process is not parallelized so there's no reason to keep the original thread open.
5. Original "design context" LLM agent reviews the implementation:
	1. Discover what has changed by checking what new non-committed changes exist. 
	2. Assess whether those changes show drift from the original design intention.
	3. Small drifts can be tolerated or fixed at the LLM's discretion. Large drifts or failures should be communicated to the human operator for inspection.
6. Human operator performs any manual tests needed to proof the modification.
7. Original "design context" LLM agent updates the [core planning docs](./docs.md) to reflect the newly modified codebase. Core planning docs should **never** link to modification documents. Relevant design info from the modification docs should be copied over.
8. Update [changelog](../infrastructure/version_control.md) with a quick description of changes.
# Advance Prep

Prep for advance (probably) 014 which will enhance the `docex docs` commands and add a `docex report` command.

The motivation for this advance is to:
1. Get our documentation / code refine and cohere skills in alignment and both working off docex rather than executor code.
2. Create a wholistic and good way to assess the overall state of the codebase over development and refine/cohere iterations.

The solution in broad strokes is to:
1. Refactor `doc-refine`, `doc-refine-orchestrate`, and `project-cohere`.
2. Build the project visualization report which aims to quantify the breakdown of context across different docfiles and code. This will replace the old "line count" part of cohere.

The idea of a report is entirely new. Read about it [here](./docex_report_design.md).

## Refactor of Doc Skills

The purpose of "doc skills" are to keep our docs properly structured and synchronized with the actual code as the project grows. A doc update is naturally part of every mod cycle, but sometimes a doc change for a specific change will have ramifications that weren't detected because other docs and bits of the codebase weren't loaded into the context of the agent making the change.

Much of this doc work is dominated by the need to assess the whole of the design docs and source code without being able to load them all into context at once. This gives rise to the `-orchestrate` command, whose purpose is to create "context groups" of subject files and the shared overhead needed to understand them. This command naturally orchestrates subagents, which can be set to carry out different tasks against each group of docs. Each subagent type does a different sort of task against a different set of context groups.

| Subagent Type | Task | Context Groups |
| ------------- | ---- | -------------- |
| I | Refine | Subtractive / condensing / organizing work aiming to move detail to the correct abstraction level or ADR. | Design docs and code, usually only those changed since a certain git ref. |
| II | Resolve Inconsistencies | Discover, research, and resolve locations where design docs are inconsistent. | Design docs, all time. |
| III | Fix Inaccuracies | Find places where the docs are not accurate relative to the actual code that has been written. | Design docs and code, usually only those changed since a certain git ref. |
| IV | Document Missing | Add documentation for select set of objects (e.g. codebases, hex modules, 1st class hex concepts, db table, etc.) if documentation for that object is totally absent. | TBD, may not be applicable |

We need to break I, II, III, and IV into dedicated skills.

Orchestrate can drive I, II, and III. IV will simply be its own pass.

Orchestrate will need to be re-written to accommodate different skills, not just "refine".

IV I have yet to explore completely, but I suspect it is not well-suited to our context-group-style orchestration and would better be written as its own skill.

## Change to docex docs command

In order to rework `-orchestrate`, we will need to change the docex `cxt_group` command. 

Currently this command simply optimizes for token weight distribution (lowest number of groups within 'target') and does not allow filtering to *just* design docs.

We need to add additional optional args:
`[--depth <depth>]` where `depth` is either `design_docs` or `code_level` (much like the `docex docs linkmap <depth>` arg). This will allow the command to generate design-doc-only groups (`code-level` is current behavior, and the future default.).
`[--optimize <metric>]` where `metric` is either `tokens` or `module_integrity`. Current (and default) behavior is `tokens` - groups are optimized for smallest number of groups that don't exceed the `tokens_max`. The `module_integrity` command would ensure that context groups don't ever split modules, codebases, or design-docs. See below.

### Module Integrity

The idea of module integrity is to present context groups that are guaranteed to collect groups of subject files which belong to the same "categories". These categories are a fixed set: modules, codebases, and design docs. The idea is that we never want to split subject files for one category across two different context groups, unless those two different context groups contain *only* files pertaining to the same category AND the category cannot be further subdivided. Of our categories, only codebases can be subdivided.

Take for example a project with codebases `C-1`, `C-2`. `C-1` contains modules `M-1`, `M-2`. `C-2` contains modules `M-3`, `M-4`.

The following table lists possible combinations, whether they are valid, and why they are not if not.

| CXT Group A Subject Files | CXT Group B Subject Files | Valid | Why |
| ------------------------- | ------------------------- | ----- | --- |
| `M-1` | `M-2` | Yes | Clear split on module lines. |
| `M-1` | `M-2`, `M-3` | No | Splits a codebase, and a codebase can be subdivided into modules. |
| `M-1` | `M-1` | Yes | Split of module subject files across two groups, and only that module. Necessary for large modules. |
| `M-1`, `M-2`, `M-3`, `M-4` | Design docs | Yes | Both codebases entirely contained in one group. |
| `M-1` | `M-2`, `M-1` | No | Splits a module across two groups, but Group B contains another different module. |
| design docs | design docs | Yes | We are splitting one "category" - design docs itself. |

The natural result of this system should frequently give us groups containing several whole modules under one codebase, design docs as one context group, and even entire codebases together. However, it remains resilient to large projects for which one codebase or design docs cannot all fit into one context.
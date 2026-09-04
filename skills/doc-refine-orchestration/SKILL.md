---
name: doc-refine-orchestration
description: This skill describes a process for *managing* the refining documentation prose and content into accordance with doctrine standards. This skill will generally be invoked by prompt rather than by an agent seeking to do work. It covers how to correctly split out the work into different agents in parallel, but not how to actually do the work.
metadata:
  type: conventional
---

# Documentation Refinement Orchestration

| Name | Definition |
| subject file | A doc or source code file which we are planning to make load-bearing edits to. |
| overhead | The docs which must be in-context to make good, meaningful edits to a subject file. |
| docmap | The full mapping of all subject files and related overhead documents. |

Orchestrating any documentation-refining process is tricky. The full sum of code and docs is usually far more than a single context can hold. Fortunately editing a **subject file** (single design doc or file's worth of code-level comments) doesn't require whole-project context. It only requires that certain files be loaded - relevant "adjacent" docs and "higher" docs that link to it.
+ "adjacent" - docs of the same abstraction level, cross linked.
+ "higher" - docs of a higher abstraction level. For code-level comments, all design docs are a higher abstraction level.

We can summarize this in the concept of "overhead" - all the documents that must be in context to make changes to documentation within a subject file (whether source code or design doc).

Now, overhead is tricky. It's hard to deterministically say exactly what composes a subject file's overhead in all cases. However, we can do a decent job in most cases with the following **overhead rules**. A file's *likely overhead* is:
1. All L1 root docs (`boundary_conditions.md`, `concepts_and_decisions.md`, `structures_and_views.md`, and all standard diagrams).
2. Any L2 or L3 doc to which the subject file directly links to.
3. For code-level comments that have a module doc, any L2 or L3 that the *module doc* directly links to.

Now this gives us a deterministic "recommended pool" of overhead for a subject file. It won't be exhaustive, but it lets us do orchestration math. The general procedure is:
1. Identify all subject files that we wish to do work on.
2. Establish the recommended pool of overhead files for each.
3. Denote the "approximate" context usage of loading each file.
4. Clump together groups of subject files which share overhead (*context groups*), aiming for 50% context usage when all subject files and overhead have been loaded.
5. Kick off a sub-agent to use the `docs-refine` skill, giving it a full list of the subject files to assess and the full list of overhead to load into context *before loading any subject file*.
6. For each subject file, the sub-agent will already have the recommended pool of overhead files in context, and can then read the subject file and load any additional files into context intelligently. Then it can make load-bearing edits to the subject file with the best possible information.

This process helps conserve context (we only load overhead files once per full subagent run spanning many subject files).

## Orchestration Process

### Identify Subject Files

It takes considerable LLM usage to scan every line of documentation in a large software project. Therefore, the first step is to choose what documents to actually scan. Only those which have changed since some start point should actually be assessed.

The start point can vary on circumstance:
+ if this is run as part of a mod cycle, the start point is the state before the mod cycle made changes.
+ if this is run as part of an advance, the start point is the start of the advance.
+ if this is specifically run across an *entire* project, the start point is the beginning of git history, and all design docs and source code is in scope.

If the start point has not been indicated to you, you should ask what it is.

Convert that start point to a specific git commit.

### Establish Context Groups

Steps (2) to (4) are handled by `docex` code.

Simply run `docex docs cxt_groups <tokens_max> {<git_ref> | all}` to get the full list of context groups.

### Orchestrate Subagents

Use the results of the `cxt_groups` command to set up one subagent for each context group. Use the below template, and note that loading the overhead files first is by design to take advantage of primacy bias.

*Never parallelize this work* - it's almost impossible to predict what docs will be edited as a result of refinement, and we don't want one agent editing an overhead file actively loaded into context in another agent and being used as reference (or even worse, a collision!).

```md
TEMPLATE TODO
```
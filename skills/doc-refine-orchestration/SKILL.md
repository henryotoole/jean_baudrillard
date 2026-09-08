---
name: doc-refine-orchestration
description: This skill describes a process for *managing* the refining documentation prose and content into accordance with doctrine standards. This skill will generally be invoked by prompt rather than by an agent seeking to do work. It covers how to correctly split out the work into different agents in parallel, but not how to actually do the work.
metadata:
  type: conventional
---

# Documentation Refinement Orchestration

| Name | Definition |
| ---- | ---------- |
| subject file | A doc or source code file which we are planning to make load-bearing edits to. |
| overhead | The docs which must be in-context to make good, meaningful edits to a subject file. |

Orchestrating any documentation-refining process is tricky. The full sum of code and docs is usually far more than a single context can hold. Fortunately editing a **subject file** (single design doc or file's worth of code-level comments) doesn't require whole-project context. It only requires that certain files be loaded - relevant "adjacent" docs and "higher" docs that link to it.
+ "adjacent" - docs of the same abstraction level, cross linked.
+ "higher" - docs of a higher abstraction level. For code-level comments, all design docs are a higher abstraction level.

We can summarize this in the concept of "overhead" - all the documents that must be in context to make changes to documentation within a subject file (whether source code or design doc).

Overhead is inferred structurally. We do not restate the rules here — they live in one place, `docex docs overhead` (see [`docex.md § docs`](../../doctrine/infrastructure/docex.md#docs)), and `docex docs cxt_groups` applies them for us. A pointer can't drift from its source; a restatement did.

This gives us a deterministic "recommended pool" of overhead for a subject file. It won't be exhaustive, but it lets us do orchestration math. The general procedure is:
1. Ask the user what to use for max tokens when when generating context groups.
   + Recommend 400k for 1M context windows, and 100k for 200k windows.
2. Identify all subject files that we wish to do work on.
3. Establish the recommended pool of overhead files for each.
4. Denote the "approximate" context usage of loading each file.
5. Clump together groups of subject files which share overhead (*context groups*), aiming for 50% context usage when all subject files and overhead have been loaded.
6. Kick off a sub-agent to use the `doc-refine` skill, giving it a full list of the subject files to assess and the full list of overhead to load into context *before loading any subject file*.
7. For each subject file, the sub-agent will already have the recommended pool of overhead files in context, and can then read the subject file and load any additional files into context intelligently. Then it can make load-bearing edits to the subject file with the best possible information.

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
You are refining documentation for one context group. Work strictly in this order.

1. FIRST, read these overhead files into context (highest abstraction first) — do
   NOT edit them; they are reference for editing the subjects:
   {{overhead_files, one per line, high→low abstraction}}

2. Invoke the `doc-refine` skill and follow it to make load-bearing edits to each of
   these subject files, one at a time:
   {{subject_files, one per line}}

Do not edit any file outside the subject list except as `doc-refine` directs. Report
which subjects you changed and any overhead file that itself turned out to need work
(flag it; do not edit it — a later group owns it).
```
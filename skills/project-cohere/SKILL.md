---
name: project-cohere
description: This skill describes the process of "cohering" a project to ensure that the documentation is internally consistent and actually matches what the code does. This skill will generally be invoked by the operator rather than by an agent seeking to do work.
---

# Project Cohere

Projects have both documentation that describes code and the code itself. The documentation is a shorthand roadmap which allows the action of a module or code file to be understood without loading a great deal of it into context. It's critical that it be internally consistent and furthermore actually describe the code as-written. No deterministic compile step can ensure this; instead, the documentation must be read over for meaning and the relevant code assessed manually.

## Documentation Tiers

The doctrine-defined documentation levels are:
1. Product docs
2. Architecture / design docs
3. Module docs
4. Code level docs

This cohere skill is primarily concerned with architecture / design, and module docs. It is especially concerned with "core planning docs" - levels 2 and 3 above, found in `$pr/plans/core/`. 

## Source of Truth

The trickiest thing about cohere is that a discrepancy (whether between two sections of docs or a doc section and corresponding code) implies two different possible sources of truth. Choosing which source of truth is the "correct" one is genuinely a judgement call.

The higher the "level" of doc, the more it can be considered a source of truth. `masterplan.md`, as the highest form of architecture doc, should never be changed without asking the operator to make a judgement call on the discrepancy. Lower levels of architecture doc (often direct children in the `$pr/plans/core/${service_name}` folder) carry more weight than module docs. Module docs are often in a `$pr/plans/core/${service_name}/hex` folder.

For lower forms of architecture doc and module docs, what's present in the actual code can indicate that the docs themselves need to change. If there's a discrepancy between two different sections of documentation, the one that matches the code as-written is often the right one.

## Git Conventions

Operate out of whatever branch is currently active (it's the operator's responsibility to set the branch).

## Classes of Problems

There are four classes of problems which can exist in a codebase which this skill aims to fix. They are noted below, alongside some instructions to help when identifying and fixing them.

### 1. Documentation is Inconsistent

In this class, documentation conflicts with other documentation.

When two different bits of documentation disagree or directly conflict, take the following into account:
+ The "level" (e.g. higher or lower architecture, module, etc.) of the opposing documentation bits.
+ What the associated code *actually does*.

These things taken together can help form a clearer picture of the "correct" version. Documentation backed by actual code usually wins in a conflict - often this case is the result of a code update that was not fully documented across all documentation.

### 2. Documentation Does Not Match Code

In this class, code clearly exists to correspond to documentation, but the code's functionality does not match what the documentation indicated.

Usually this means the documentation needs to change. However, keep the [documentation level rules](#source-of-truth) in mind - changing higher forms of doc may require getting the operator's judgement.

### 3. Unimplemented Feature

In this class, no code can be found to correspond to the documentation but the documentation clearly outlines a feature that's seemingly relevant and congruent with the rest of the documentation. This situation implies an *unimplemented* feature. 

In this case, please *mark the relevant documentation as unimplemented* rather than delete it.

### 4. Undocumented Code

In this class, some amount of code is entirely undocumented. It's tricky because, by definition, documentation is a *summary* of the code's behavior, not a perfect 1-to-1 description.

Examples of things that *should be documented*; if found they are probably undocumented code:
+ A core service - deserves dedicated folder and architecture docs.
+ A hex module - this should have its own dedicated document.
+ A first-class hexagonal component like a domain object, port, adapter, or application logic class - these belong in the hex module docs.
+ A database table
+ A hex shared client

Examples of things that *should not be documented*; if found they are details which don't merit mention in core planning docs. Note that these might well *be documented already*, but should not be considered "undocumented code" if they *aren't*:
+ How a function handles weird edge cases
+ Methods of first class hexagonal components
+ Full enumeration of an enum's types
+ What libraries are used for a class

For this skill, lean conservatively with attempting to document truly undocumented code. Furthermore, *always* ask the operator when adding new documentation. The cohere skill will be run many times for a project's codebase. If it added a little bit more detail every time it ran, soon the docs would become bogged down with unnecessary detail.

## Process

The process is broken into:
1. Prep
2. Enumerate Chunks
3. Subagent Sweep
4. Codebase Alteration
5. Consistency Pass
6. Final Summary

### Prep

Run the word-count executor with the `--before` flag. It ships in this skill's own `executor/` directory (alongside this SKILL.md); invoke it by that skill-relative path and point it at the project you're cohering with `--root`:

```
python3 executor/word_count.py --before --root <project-root>
```

If you invoke it from inside the target project you may omit `--root` — the script then locates the project by searching upward from the current directory for `project.yml`. Either way it prints the resolved root. **Confirm that reported root is the project you intend to cohere** before doing any work — on a multi-project machine the wrong current directory would target the wrong project.

You should also certainly read the project's core planning docs - they will help you navigate the rest of the process.

### Enumerate Chunks

In order to perform a proper cohering sweep of the codebase, most of the codebase must be loaded into context. For large codebases, this can *certainly* exceed the context of a single agent. Therefore, for the next step in the process, we split the codebase out into different "chunks" on the basis of size. A chunk might contain the entire codebase source, one or more whole core services packed together, or a subset of a single service's hex modules — never mixing modules across services — depending on the size of the various project pieces.

Fortunately, setting the chunks can be done deterministically with executor code, because the doctrine's filestructure is known. Run the chunker (same skill-relative path and `--root` behavior as the word-count executor):

```
python3 executor/chunk_map.py --root <project-root>
```

It walks `core/*/src`, sizing only real source — the executor uses an allowlist of the doctrine's supported languages, so compiled artifacts (`.pyc`, `.o`, `.dll`, extensionless binaries, `node_modules`, `target/`, …) never inflate the count — by character count (a stable proxy for tokens; it reads no file contents), and prints a JSON chunk map. Each chunk is one of these shapes, chosen by size: the **entire source** (small projects), **one or more whole services** packed together (bounded contexts stay separate — modules from different services are never mixed), or **a subset of a single service's hex modules** (a service too big to fit whole). Tune the per-chunk budget with `--budget <chars>` (default 1400000, ≈ 400k tokens); keep it below a subagent's context so there's headroom for its reasoning and output.

The chunk map is deliberately **code-only** — it does not pair chunks to docs. Doc selection is *your* job as the skill-agent: you read the full set of core planning docs in [Prep](#prep), so you are the right authority to decide which docs are relevant to each chunk's code. This is a deliberate choice — a service's doc layout, especially a non-hex frontend, is irregular and cannot be resolved into a provably-complete file set, so a machine-generated "here are all your docs" list would give the subagent false confidence.

The JSON gives you, per entry in `chunks`:
+ `code_paths` — the source that chunk's subagent should read.
+ `services` — which service(s) the chunk's code belongs to; use it to pull the right planning docs when you curate (below).
+ `code_chars` / `est_tokens` — the chunk's size.
+ `over_budget` — `true` when a single module (or a non-hex service) is larger than the budget and *cannot* be split further. The subagent must still take it; expect it to work near its context limit, and lean on the operator if the result looks incomplete.

And at the top level, two structural signals to inform your doc curation and Class detection:
+ `hints.undocumented_code_units` — code units with no matching module doc (a head-start on [Class 4](#4-undocumented-code)).
+ `hints.unpaired_docs` — docs with no corresponding code: stale/leftover module docs (possible [Class 3](#3-unimplemented-feature)), or `db_schema.md` whose real counterpart lives in `migrations/` (outside chunked source) and must be verified separately.

Each returned chunk should be given a dedicated sub-agent in the next section. Hand each subagent (a) its `code_paths`, and (b) a **curated list of the docs relevant to that code**, which you assemble by hand: the module docs for the modules it holds, the service-level docs for its `services`, and the cross-cutting project docs (`masterplan.md`, plus `conventions.md` if present). When a chunk is a partial slice of a larger service (`granularity: "modules"`), curate only the docs that pertain to the code in that chunk — keep service-wide or cross-module docs for your own later assessment and the [Consistency Pass](#consistency-pass).

### Subagent Sweep

Give each chunk from the previous step its own dedicated sub-agent. Each sub-agent sweeps *only its chunk's code* against the docs you curated for it, and **reports** discrepancies — it does not fix anything (you do that, with full context, in the next step). Fill the placeholders (`{...}`) with the values you assembled per chunk and send this prompt:

```md
# documentation-coherence

You are a documentation-coherence sweep agent for ONE chunk of a larger project.
Operate ONLY on the code and docs listed below — do NOT read the rest of the codebase.

## Your code chunk (read ALL of it):
{code_paths}

## The documentation relevant to this chunk (read ALL of it):
{curated_docs}

## Cross-cutting project docs (read for context):
{project_docs}          # masterplan.md, and conventions.md if present

{classes_of_problem}

## Detection criteria: You are hunting for Classes 2, 3, and 4 only — NOT Class 1.

## Follow This Process:
1. Read the cross-cutting project docs, then the relevant documentation above.
2. Read every file in your code chunk.
3. Compare the code against the docs and report each instance of:
   - Class 2 (docs don't match code): a doc describes code in your chunk, but the
     code's actual behavior differs from what the doc says.
   - Class 3 (unimplemented feature): a doc describes a feature that code in your
     chunk should implement but does not. ONLY report this for functionality that
     would live in the code you were given. If a doc describes a feature whose code
     belongs to a part of the service you were NOT handed, do NOT report it — that
     code lives in a sibling chunk and another agent covers it.
   - Class 4 (undocumented code): code in your chunk that merits documentation (per
     the should/should-not-document lists in the Classes section) but has none.

## Scope rules:
- Assess only documentation that pertains to the code you were given. Ignore — do
  not flag — docs about code outside your chunk.
- Do NOT assess internal inconsistencies between two pieces of documentation.
- Do NOT change any file. Report only.

## Output:
a list of findings, each giving the class (2/3/4), the doc location (file +
section), the code location (file + symbol), and a precise description of the
discrepancy with the evidence you saw. If you found nothing, say so explicitly.
```

Curate `{curated_docs}` per the handoff rules in [Enumerate Chunks](#enumerate-chunks) — and for an `over_budget` chunk, tell the subagent it holds an oversized unit that may strain its context, so it should be thorough and flag anything it could not fully read.

Replace `{classes_of_problem}` with [the classes of problem section](#classes-of-problems) verbatim.

Please use the highest available version of `opus` as the model for the sub-agents.

### Codebase Alteration

Armed with the full list of issues from the subagents, proceed to fix each of these. You'll need to investigate each issue and make sure you agree with the subagent's assessment. Then, you'll need to correct the issue. Remember to consider the [source of truth](#source-of-truth) weights for different levels of documentation.

When a fix will require you to make a change to `masterplan.md`, **always** let the human operator make the ultimate decision on whether to make the change.

### Consistency Pass

Now that the entire codebase has been assessed and broadly corrected, do one final documentation consistency pass to catch [Class 1](#1-documentation-is-inconsistent) issues. This pass will be a little different - instead of reading the docs again yourself, use a subagent to scan for inconsistencies / contradictions within the documentation. Then you can iterate across results the subagent found, and choose for yourself how to apply solutions. Remember to keep [source of truth](#source-of-truth) weights in mind for different levels of documentation and to always let the human operator make the ultimate decision on whether to change `masterplan.md`.

### Final Summary

Provide a general, prose overview of the changes you made.

Run the executor again (same skill-relative path), this time with the `--after` flag, to get:

```
python3 executor/word_count.py --after --root <project-root>
```

+ Total words for the entire core planning documentation set, before and after (and as a percentage change)
+ Total words for the subset of changed files, before and after (and as a percentage change)

And tell the user those results.

After the summary, commit the files which you have changed with a message like "Ran cohere on core planning docs". You don't have to ask for permission to commit, but please do notify the user that you have made a commit.
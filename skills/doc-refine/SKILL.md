---
name: doc-refine
description: This skill describes a process for refining documentation prose and content into accordance with doctrine standards. This skill will generally be invoked by prompt rather than by an agent seeking to do work
metadata:
  type: conventional
---

The doctrine's stance on documentation is relatively focused. Any given piece of documentation has a correct level of abstraction and location in the docs structure or source code. Drift over time is inevitable, but the process defined below can be used to assess the design and code-level docs of a project and correct them.

A note on the language used here. Changes can be:
+ Subtractive - Text has been outright removed, or removed and replaced with a reference to elsewhere.
+ Condensing - Text has been edited to strip detail and provide a more abstract overview. Details may be moved to lower abstraction tiers.
+ Organizing - Text is moved from one location to another, usually to improve conceptual integrity.
+ Additive - Text has been added.

This skill aims to make almost exclusively *subtractive*, *condensing*, or *organizing* changes.

You will be given two lists:
1. "Overhead" files to load into context first. These are files which are generally helpful and provide context for changing the second list of files.
2. "Subject" files to actually edit and change.

# The Process

You will iterate across each *subject file*, one at a time, and apply the following procedure to it. Note that, while the "overhead files" should provide much of the context you need to make edits, you are still allowed and encouraged to load any additional referenced files you feel are necessary to make correct edits. For example, if a *condensing* change will move detail to another doc that hasn't been loaded yet, it should be loaded to make the move.

1. Load subject file into context.
2. Determine what kind of file it is:
  + Source code file (contains source code and "code-level documentation" in the form of inline comments and docstrings)
  + Design doc (in `$pr/plans/design` directory)
3. Determine whether it is an L1 standard arc42 doc
  + One of `boundary_conditions.md`, `concepts_and_decisions.md` or `structures_and_views.md`
4. Apply as many [edit passes](#edit-passes) as match the subject file (most important step!).

After all subject files have been processed, verify and clean up by doing:
1. Run `./bin/docex docs adr` to re-generate the ADR indices.
2. Check that the docs still meet doctrine standards with `./bin/docex docs check`.
  + Fix any issues that have resulted from changes (broken links, etc)
  + Run `./bin/docex docs adr` if any changes made.

# Edit Passes

A) **Apply to only source code files**
  + Are design docs replicated here? (subtractive)
    - Delete prose and replace with a reference.
B) **Apply to only design docs**
  + Is any part of this section purely historic (e.g. mod 101 added X)? (subtractive)
    - Delete it.
  + Does any part of this section try to justify the reasoning behind a decision or state? (subtractive, condensing)
    + Is *the decision or state* already recorded in an ADR?
      - If so, delete the reasoning, even if the reasoning itself was not captured completely.
      - If not:
        - Load `writing-adrs` skill if not yet loaded
        - make a new ADR
        - link to it and delete the reasoning.
C) **Apply to L1 standard arc42 docs**
  + Does X concept really belong in this arc42 section? (organizing)
    - If blatantly in the wrong place, move it.
D) **Apply to all files**
  + Is the description of X concept over-detailed?
    + Can we just get rid of the details? (subtractive)
      - Then do so.
    + Are the details load-bearing? (condensing)
      - Move them to:
        - an L1 specifics document if they are project-wide
        - an L2 specifics document if they are codebase-specific or
        - a module doc if they really describe a module's detailed behavior, rather than a cross cutting concept.
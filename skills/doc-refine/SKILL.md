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

Actual Work
A) Code-inline
  + Are design docs replicated here? (subtractive)
    - Delete prose and replace with a reference.
B) State Pass (ALL DESIGN DOCS)
  + Is any part of this section purely historic (e.g. mod 101 added X)? (subtractive)
    - Delete it.
  + Does any part of this section try to justify the reasoning behind a decision or state? (subtractive, condensing)
    + Is *the decision or state* already recorded in an ADR?
      - If so, delete the reasoning, even if the reasoning itself was not captured completely.
      - If not, make a new ADR, link to it, and delete the reasoning.
C) Categorization Pass (L1 STANDARD DOCS ONLY)
  + Does X concept really belong in this arc42 section? (organizing)
    - If blatantly in the wrong place, move it.
D) Detail Pass (ALL DOCS)
  + Is the description of X concept over-detailed?
    + Can we just get rid of the details? (subtractive)
      - Then do so.
    + Are the details load-bearing? (condensing)
      - Move them to:
        - an L1 specifics document if they are project-wide
        - an L2 specifics document if they are codebase-specific or
        - a module doc if they really describe a module's detailed behavior, rather than a cross cutting concept.
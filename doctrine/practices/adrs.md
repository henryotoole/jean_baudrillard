---
stratum: conditional
---

# Architecture Decision Records

ADR's track the *reasoning* that went into a design decision. They serve a dual role in the doctrine:
1. They allow us to trace decisions into the past and foresee the perils of change.
2. They give LLM's a place to record records that would otherwise clutter up our lightweight, load-bearing state design docs.

The best ADR system is the simplest. The doctrine opts for a simple structure. Each ADR is just a markdown file with some markdown. They are all stored in a folder (`$pr/plans/design/adrs`) where filename is a composite of ID and title e.g. `${id}_${snake_case_title}`.

Two [adr index files](#adr-index) track the full list of ADR's at a high level, making them more easily parsed and located. These files are generated from the ADR files by `docex`. Old ADR's are immutable, so the only action that is ever taken is the addition of new ADR's.

## ADR Format

Below is the schema for an ADR file:

```md
---
id: 0004
title: adr_title	# Title must be long enough that it conveys what the ADR is about, while remaining short enough to be useful as a filename.
status: accepted	# One of an enum, see below for full list.
date: 2026-08-31	# Always ISO form
supersedes: [0003]	# Can be empty
superseded-by: []	# Can be empty
tags: [security, services]
---

## Context
...
## Decision
...
## Consequences
...
```

Valid Statuses
```md
proposed     # written, not yet agreed
accepted     # agreed, currently in force
rejected     # considered and decided against
superseded   # replaced by a later ADR (see superseded-by)
deprecated   # retired, no replacement
```

## ADR Index

We create two index files to act as the "map" of all ADR's:
1. An "active" table, listing approved decisions that have not been superceded.
	+ `| ADR ID | Title | Date | Supersedes |`
2. The "index" table, listing all decisions.
	+ `| ADR ID | Title | Status | Date | Supersedes | Superseded By |`

These are split into two files so that an LLM won't bloat its context by reading the full big table.

## Docex

`docex` provides a deterministic command to synchronize the ADR Indices with the ADR's.

`docex docs adr` regenerates both index files from the ADR sources in `plans/design/adrs/`. Generation is deterministic and idempotent.
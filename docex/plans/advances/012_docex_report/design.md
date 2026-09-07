# Docex Report Command

Informal design document describing the docex report command. 

## Overview

The report command aims to distill, report, and visualize different "views" of a project. The general process is something like:

[All Data] ---(distillation / interpretation)--> [Summarizing Metrics and Data] ---(composing / visualizing)--> [Full Report (including visuals)]

A clear example - the docs for a project (from design all the way down to code-level) can become large for a project and reading all of them can be tricky. `docex report docs` would give the caller a simple, easy-to-read and quick-to-understand view of the full state of the docs.

Full command form:

`docex report <type> [--format data|full]`

## Agent v. Operator Usage

The real *value* of each `report` command is in the distillation / interpretation code that runs. The output can either be the raw metrics and data or the full report with visualizations and descriptive text. The raw data is likely more efficient for LLM consumption and the full report more efficient for operator consumption.

The `--format` optional param lets the command caller choose which occurs. The default should be `full`.

## Report Types

While I envision a variety of report types in the long run, I only have one designed at the time of writing. So `report` will ship with just one report type.

Every report type should distinguish between what the *summarizing metrics and data* look lke compared to the *Full Report*.

### Docs

`./bin/docex report docs`

This report aims to make it easy to assess where the "weight" (measured in tokens) of documentation is falling.

#### Summarizing Metrics and Data

The big metric here is weight (measured in tokens) split into distinct buckets conditional on document type, abstraction level, and location. Primary buckets are named toplevel buckets (see below). Buckets can have sub-groups which themselves are buckets.

When a bucket's sub-buckets don't sum in weight to the equal of the bucket, there should be an "etc" sub-bucket to represent the remainder.

The below ordered list details the design docs bucket structure all the way down.

Primary Buckets (design docs)
+ L1 Standard Roots
	+ `boundary_conditions.md`
		+ All named arc42 sections
	+ `concepts_and_decisions.md`
		+ All named arc42 sections
	+ `structures_and_views.md`
		+ All named arc42 sections
	+ Diagrams (project and service, NOT module)
	+ ADR Indices (both)
	+ `lexicon.md`
+ L1 Detail Docs
	+ L1 `specifics` folder
		+ All `specifics` files.
	+ `quality_scenarios.md`
	+ `unknowns.md`
	+ Other Files (in L1 directory)
		+ Any other files in the L1 directory.
+ L2 Architecture Docs
	+ Each Codebase Folder
		+ Codebase module diagram.
		+ Codebase `specifics` folder.
			+ All codebase `specifics` files.
		+ Other Files (in L2 codebase directory) (excluding `module` folder)
			+ Any other files in the L2 codebase directory.
+ L3 Module Docs
	+ Each Codebase Folder
		+ All files in the codebase `module` folder.

The codebase-level docs also need to be visualized. These are simpler because they haven't nearly the structural complexity of design docs, but harder because they will require linting to distinguish between source code, inline comments, docstrings, and references.

The source code of a project can divided into two nesting groups:
+ codebases
+ modules

Not every codebase will necessarily have modules, but any hexagonally structured one will.

So our bucket tiers go:
Primary Buckets (source code)
+ Each codebase
	+ Each module (if structured into standard hex modules)
		+ Each source code file
			+ Inline comments
			+ Docstrings
			+ References (references in docstrings or inline comments to other files)

We track references to try to get a feel for the slp START HERE
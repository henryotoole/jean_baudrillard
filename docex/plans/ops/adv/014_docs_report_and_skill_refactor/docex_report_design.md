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
	+ Module Diagrams
		+ All codebase module diagrams (name form: `${codebase}/filename`).
	+ `specifics` folders.
		+ All codebase `specifics` files (name form: `${codebase}/filename`).
	+ Other Files (in L2 codebase directory) (excluding `module` folder)
		+ Any other files in the L2 codebase directory.
+ L3 Module Docs
	+ Each Codebase Folder
		+ All files in the codebase `module` folder.
+ ADR's (not split any deeper; the sum of all ADR files except for indices)

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
			+ Code
			+ Other / Unlintable

Unfortunately, this does mean that linting will be required to distinguish comments from code. We'll need to support as many common types as we can (python, go, javascript, etc.) and rely on the "other" category to catch unexpected file types. Naturally we also want to avoid compiled artifacts (like pyc files) - generally such files are git ignored, so ignoring all non-tracked files is likely sufficient.

#### Full Report

The primary way of expressing the above summarizing metrics is in treemap-type diagrams. These are similar to, but not exactly like, conventional treemaps so generating them will probably require some bespoke code rather than a library. Document "weight" is proportional to area.

The full structure of the report shall be:

1. Code-Doc Comparison
2. Doc Treemap
3. Code Treemap

THe resulting report should be rendered into HTML (with all diagrams directly embedded, not separate files)

##### Code-Doc Comparison

This is a simple diagram which aims to give perspective on the weight of the docs vs. the weight of the source code.

This takes the form of a 4:3 (wider than tall) split into two vertical slices: design docs v source code weight.

##### Doc Treemap

The design doc treemap is the most structured and aims to express all those primary buckets. The diagram takes the form of a large rectangle (4:3 ratio, wider than tall) split first into vertical slices and then into horizontal slices. Each vertical slice represents a primary bucket (L1 standard roots, L1 detail docs, etc.) *except for* ADR's, which are handled separately. Then each vertical slice is split into horizontal slices for each sub-bucket of a primary: `boundary_conditions.md`, `concepts_and_decisions.md`, etc. for L1 Standard Roots. Then one last set of horizontal slices *within* a horizontal slice divided by dashed lines for the sub-sub-buckets.

Let's take, for example, the "L2 Architecture Docs" vertical slice for a two-codebase project ("api" and "frontend"). From top to bottom, this slice is broken into three horizontal slice: "Diagrams", "Specifics", and "Other Files". "Diagrams" is broken into two horizontal slices (api/module_diagram.mmd and frontend/module_diagram.mmd), "L2 Specifics" might be broken into several slices (api/concept1.md, api/concept2.md, frontend/concept3.md), and "Other Files" into as many slices as there are other files. 

All slices may have an 'etc' section representing uncategorized token weight.

Each slice has a "weight" in tokens (estimated usage) and, much like a real treemap, should be sized accordingly. The proportions in vertical slices, for example, should indicate the token distribution across all primary buckets. Defined literally, box-area is proportional to weight.

The "ADR's" primary bucket is handled differently. Instead of composing another vertical slice, it forms one large horizontal rectangle that stretches beneath all four primary-bucket vertical slices. This indicates graphically that ADR's span all abstraction levels. Put differently, the *total* graphic is split into two master horizontal slices: the four primary-bucket vertical slices and the ADR slice.

##### Code Treemap

The source code gets displayed differently. Rather than show a breakdown level by level, we show aggregate weight distribution level by level. So we care about how a whole codebase's, or whole module's, weight is distributed across inline comments, docstrings, references, and code.

The form of the code treemap diagram is as follows:

A square, cut into three horizontal slices. The bottom slice always represents "other / unlintable", the middle slice always represents code, and the top one is split into three vertical slices for inline comments, docstrings, and references from left to right.

There should be a diagram for each codebase in the report.

There should also be a diagram for each hex module that exists.
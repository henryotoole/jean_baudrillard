---
stratum: resident
---

# Documentation

This file provides an overview of doctrinal definitions for documentation concepts and structure.

## Classifications

The doctrine recognizes five distinct forms of documentation:

| Name | Purpose |
| ---- | ------- |
| Product Docs | Docs with a frame of reference positioned outside the black box of the project. Installation guides usage instructions for an end user, project requirement documents, etc. These are concerned with *what the project does*, not how it achieves it. |
| Design Docs | Concerned with how the project will achieve its goals. Cut across various levels of abstraction, design docs all sit squarely above implementation. Stored separately and distinctly from the code. Includes "architecture" and "module" docs. |
| Code Level Docs | These are inline comments, function and class docstrings, even file docstrings - any documentation that lives alongside code. Effectively, these are implementation notes. |
| Operational Docs | These document active development workflows in-process. They coordinate active developers and provide a literal historic record of project development. |
| Reference Docs | These document topics *outside* of the project. Could be an API reference that the project will use, a data sample that indicates an interesting edge, a sample of a textbook on helical spur gears, etc. Literally used for reference when designing. |

┌─────────────────┐┌──────────────────────────────────────────┐┌──────────────────┐
│                 ││                                          ││                  │
│  Product Docs   ││               Design Docs                ││ Code-Level Docs  │
│                 ││                                          ││                  │
│                 ││ ┌────────────┬────────────┬────────────┐ ││                  │
│                 ││ │            │            │            │ ││                  │
│                 ││ │   **L1**   │   **L2**   │   **L3**   │ ││                  │
│                 ││ │            │            │            │ ││                  │
│                 ││ │   project  │   codebase │   module   │ ││                  │
│                 ││ │   level    │   level    │   level    │ ││                  │
│                 ││ │            │            │            │ ││                  │
│                 ││ │            │            │            │ ││                  │
│                 ││ ├────────────┴────────────┴────────────┤ ││                  │
│                 ││ │                                      │ ││                  │
│                 ││ │                ADR's                 │ ││                  │
│                 ││ │                                      │ ││                  │
│                 ││ └──────────────────────────────────────┘ ││                  │
└─────────────────┘└──────────────────────────────────────────┘└──────────────────┘
*above chart boxes are on an axis from more abstract ---> less abstract (left to right)

<TODO> Move the above to `diagrams` and link. </TODO>

## Product Documentation

These come from outside the project and are the realm of the operator. Optional.

## Design Documentation

Good design docs are of paramount importance because they provide a "map" of the project - an abbreviated summary which lets the reader understand the source code without *having to read all of it*. Design docs can be loaded cheaply into LLM context; entire codebases cannot. 

### State v Reasoning

Design docs can be cleanly split into two categories - those that capture state, and those that document reasoning.
+ **State-docs** present an accurate snapshot of the project's design. They are broken out across differing levels of abstraction and include what are widely known as "architecture" and "module" docs.
+ **Reasoning-docs** record the reasoning behind the design state - *why* we chose to design some aspect of the project in a certain way. These are ADR's.

### Level of Abstraction

Design docs also naturally land on different levels of *abstraction*. Project-spanning architecture docs, for example, are more broad and less detailed than module docs. The doctrine defines three levels of decreasing abstraction which fit nicely with infrastructure splits into project, codebase, and module.

| Level | Name | Industry Term | Purpose | Diagram |
| ----- | ---- | ------------- | ------- | ------- |
| 1 | Project Level | Architecture Docs | Describes the project as a whole. | Project Diagram |
| 2 | Codebase Level | Architecture Docs | Describes a specific codebase (and core / backing services). | Service Diagram |
| 3 | Module Level | Module Docs | Describe the interiors of individual modules: domain, boundaries, responsibilities, and limitations. | N/A |

### arc42

                                                             DESIGN DOCS                                                            
                                                                                                                                    
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                │                                │                                │                               │
│  **ARC42 Section**             │             **L1**             │             **L2**             │             **L3**            │
│                                │                                │                                │                               │
│                                │             project            │             codebase           │             module            │
│                                │             level              │             level              │             level             │
│                                │                                │                                │                               │
│  Intro & Objectives            │                                │                                │                               │
│                                │                                │                                │                               │
│  Constraints                   │                                │                                │                               │
│                                │                                │                                │                               │
│  Context & Scope               │                                │                                │                               │
│                                │                                │                                │                               │
│  Quality Requirements──────────┼─►quality_scenarios.md          │                                │                               │
│                                │                                │                                │                               │
│  Cross-cutting Concepts──────┬─┼─►specifics (L1 folder)         │                                │                               │
│                              └─┼─►doctrine_ext.md               │                                │                               │
│  Solution Strategy             │                                │                                │                               │
│                                │                                │                                │                               │
│  Risk, Unknowns────────────────┼─►unknowns.md                   │                                │                               │
│  & Tech. Debt                  │                                │                                │                               │
│                                │                                │                                │                               │
│  Building Block View───────────┼─►Project + Service Diagrams┬───┼─►Module Diagrams───────────────┼─►module docs                  │
│                                │                            └───┼─►specifics (L2 folder)         │                               │
│  Runtime View                  │                                │                                │                               │
│                                │                                │                                │                               │
│  Deployment View               │                                │                                │                               │
│                                │                                │                                │                               │
│  Glossary                      │  lexicon.md                    │                                │                               │
│                                │                                │                                │                               │
├────────────────────────────────┴────────────────────────────────┴────────────────────────────────┴───────────────────────────────┤
│                                                                                                                                  │
│                                                                                                                                  │
│  Arch. Decisions                  ADR's                                                                                          │
│                                                                                                                                  │
│                                                                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
*arrows represent routing direction; if A─►B then reading A provides an overview of and links to B.

<TODO> Move the above diagram to diagrams, link from here. </TODO>

The doctrine mandates the use of *arc42* sections to organize design docs. The marriage of *arc42* and the doctrine proves symbiotic and allows us to understand easily what belongs in each *arc42* section. L1 is formally organized into *arc42* sections split across a handful of files. L2 and L3 docs are not *arc42*-structured; they can take more flexible form and represent more detailed sections that L1 docs will reference "downwards" into.

The table below describes each standard section and its non-standard quirks when used under the doctrine:

| *arc42* Name | L1 File | Header | Notes |
| ------------ | ------- | ------ | ----- |
| Introduction & Goals | `boundary_conditions.md` | `# Intro and Goals` | We do not ever have a stakeholder section. |
| Constraints | `boundary_conditions.md` | `# Constraints` | |
| Context & Scope | `boundary_conditions.md` | `# Context and Scope` | Light embellishment on the "Project Diagram", which captures this more completely. |
| Quality Requirements | `boundary_conditions.md` | `# Quality Requirements` | Only include the "overview" - specific scenarios in detail are stored in the `quality_scenarios.md`. |
| Cross-Cutting Concepts | `concepts_and_decisions.md` | `# Cross-Cutting Concepts` | Should *only* contain the overview of each concept, and *only* project-wide concepts. Detailed design goes in `specifics`. This section captures the key ideas and domain in prose. |
| Solution Strategy | `concepts_and_decisions.md` | `# Solution Strategy` | |
| Risk, Unknowns, & Tech Debt | `concepts_and_decisions.md` | `# Risk, Unknowns, and Tech Debt` | Complex, see [below](#risk-unknowns-and-tech-debt) |
| Architecture Decisions | N/A | N/A | These go in the `adr` directory; see [below](#architecture-decision-records) |
| Building-Block View | `structures_and_views.md` | `# Building-Block View` | Complex, see [below](#building-block-view) | 
| Runtime View | `structures_and_views.md` | `# Runtime View` | Critical, project-wide flows that trace the movement of information or action through the project's infrastructure, services, and resources. |
| Deployment View | `structures_and_views.md` | `# Deployment View` | Broadly handled and described by `infra.yml` and doctrine. Contains minimal infra details like which foundation the project uses. |
| Glossary | `lexicon.md` | `# Project Lexicon` | Doctrine uses "lexicon" in the same way *arc42* uses "glossary". |

> The different L1 files here are split both to a) facilitate efficient use of LLM context and b) separate the concerns of what it means for a file to change. Git makes it easy to see when a specific file has changed. A change to `boundary_conditions.md` is far more significant than one to `structures_and_views.md`.

#### Quality Requirements

To prevent LLM context burden when reading `boundary_conditions.md`, we move the actual quality scenarios to a separate file: `quality_scenarios.md`. Each scenario should be a level two heading e.g. `## Scenario B`.

#### Cross-Cutting Concepts

By definition a cross-cutting concept is meaningful across all codebases in a project. Anything truly codebase-specific belongs in that codebase's L2 `specifics` folder. As for cross-cutting concepts, any time a single concept has a lengthy design, the bulk of that detail should be offloaded to the project L1 `specifics` folder as a separate file that is *linked to* from a more general summary in the `concepts_and_decisions.md` cross-cutting concepts section.

Many of the usual cross-cutting concepts we might need to define (like telemetry or hex-module naming conventions) are handled by the doctrine outright. However, sometimes a project requires *bespoke extensions of doctrine concepts*. For example, we might denote a custom [transfer table](TODO TIE INTO CICL.MD) type or a non-official [controller mechanism suffix](TODO TIE INTO HEX_OVERVIEW.MD). Any extension of such a doctrine concept belongs in `doctrine_ext.md` as a level-two section e.g. `## Ramdisk Transfer Table Extension`.

#### Risk, Unknowns, And Tech Debt

1. Risk - A potential danger which only bites once the project is complete and running. 
2. Unknowns - Necessary but missing knowledge.
3. Technical Debt - Discovered but unfinished work that was "island hopped" during development but will bite later.

Risks and technical debts are similar, can be summarized briefly, and belong in the `concepts_and_decisions.md` *arc42* section.

The "unknown" is a non-*arc42* concept which belongs here. An unknown is some detail about reality which we need to complete or implement a design. An unknown could be documentation for an API we expect to use, or an edge-case sample for a datatype the project will work with. Generally when we satisfy an unknown, the result ends up as a file in the `references` folder.

Unknowns are stored in a separate markdown file `unknowns.md` containing a table. We track these alongside design docs because design so that future design work can benefit from past discovery.

| ID | Name | Description | Satisfying Record |
| -- | ---- | ----------- | ----------------- |
| 0 | x_service_api_doc | Docs for X Service REST API. | [x_api_ref.openapi.json](../references/x_api_ref.openapi.json) |
| 1 | data_sample_bad_codec | An MP4 sample with a corrupted codec. | |

ID's are integer and sequential. An empty "satisfying record" column means we don't have it yet.

#### Building-Block View

The building block view carries the heaviest burden of all sections because it acts as the "router" which directs the reader deeper into the relevant more-specific documentation for a task.

Fortunately, doctrine infrastructure lends itself to the creation of the [standard diagrams](#standard-diagrams), which do much of the heavy lifting. These diagrams break the project's structure down into standard *arc42* blackboxes and whiteboxes. 

The prose in the `structures_and_views.md` *arc42* building-block section is ancillary to these diagrams. It should help the reader understand the diagrams (if they are confusing) and **especially** should provide links to any L2 or L3 files which are not linked in the diagrams.

### Standard Diagrams

The doctrine mandates three standard mermaid diagrams for inclusion with state design docs for every project. These form the "ultimate minimap" - a quick way to become oriented with any project's services, their purposes, and overall interaction. These are derived from the "C4 Model" of diagram, but mapped onto doctrine-standard concepts and language. Each is named after the "black box floor", or the lowest level of granularity the diagram shows below which is a "black box".

| Doctrine Name | C4 Equivalent | One Per | Black Box Floor | Details |
| ------------- | ------------- | ------- | --------------- | ------- |
| Project Diagram | System Context | Project | Project | Shows the project as a black box, depicting only interaction with outside services and actors. |
| Service Diagram | Container | Project | Core or Backing Service | Enhanced view in which the project box now contains codebases, core services, and `infra.yml`-defined backing services, and depicting interaction between these. |
| Module Diagram | Component | Core Service | Module | Shows an individual core service, the modules within, and the direct relations reaching into the service. |

Arrows between objects point in the direction of "calling" or "usage", and are labelled with the action taken.

As the project diagram actually shows our infrastructure setup, it should match `infra.yml`. See [TODO](#docex) for more info.

If there's a doc *for* a given box (e.g. a module doc for a module black box, or a contract for a surface), that document *must* be linked in this diagram. The standard diagrams form a critical role providing the "router" that directs reader attention to the correct details.

### LLM Agent Usage

The highest level of state design docs can generally always be loaded into context, with lower levels selectively loaded as needed for the task at hand. ADR's are only loaded when needed to understand a previous design decision or to ratify a new one.

The flow is:
1. Load `lexicon.md`.
2. Load *arc42* docs (`boundary_conditions.md`, `concepts_and_decisions.md`, `structures_and_views.md`).
3. Load all standard diagrams (`project_diagram.mmd`, `service_diagram.mmd`, and `module_diagram.mmd`s).
4. Load relevant L2 docs, usually focused within one codebase.
5. Load relevant L3 docs, which can now be correctly determined.

## Code Level Documentation

Code-level documentation captures implementation-level details. Code level docs should **never** *replicate* design decisions or documentation; but they very much should *reference* design documentation when relevant.

See [comments.md](./comments.md) for details on how and when to write them.

## Standard Documentation Structure

The doctrine standard documentation structure is as follows:

```
plans
├── product  # Optional, for product docs if they exist.
├── design
│   ├── adrs
│   │   ├── 0001_adr_name
│   │   ├── 0002_adr_name
│   │   └── ...
│   ├── ${codebase_name}
│   │   ├── module
│   │   │   └── (module doc files)
│   │   ├── specifics (L2 specific docs)
│   │   └── module_diagram.mmd
│   ├── adr_index.md
│   ├── adr_active.md
│   ├── boundary_conditions.md
│   ├── concepts_and_decisions.md
│   ├── structures_and_views.md
│   ├── lexicon.md
│   ├── unknowns.md
│   ├── doctrine_ext.md  # Optional
│   ├── quality_scenarios.md  # Optional
│   ├── project_diagram.mmd
│   └── service_diagram.mmd
├── ops         # For "operational docs"
│   ├── mods    # See [modifications.md](TODO REF)
│   └── adv     # See [advance.md](TODO REF)
└── references
```

## Docex

TODO *document* how docex interacts with documentation:
+ reachability check stage
+ standard doc missing check stage
+ `infra.yml` matches `service` diagram
+ standard diagrams match each other
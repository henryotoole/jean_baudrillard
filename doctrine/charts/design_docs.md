# Abstraction Axis

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

# ARC42 Inset

                                                             DESIGN DOCS                                                            
                                                                                                                                    
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                │                                │                                │                               │
│  **ARC42 Section**             │             **L1**             │             **L2**             │             **L3**            │
│                                │                                │                                │                               │
│                                │             project            │             codebase           │             module            │
│                                │             level              │             level              │             level             │
│                                │                                │                                │                               │
│  Intro & Goals                 │                                │                                │                               │
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
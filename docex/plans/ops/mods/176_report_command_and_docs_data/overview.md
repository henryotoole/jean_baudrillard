# Mod 176 — `report_command_and_docs_data`

Advance 014, Phase A. Introduce the `docex report <type> [--format data|full]`
command family and its first type, `docs`, at the **`data`** format (the
distillation layer). `full` (HTML treemaps) is Mod 177.

Authoritative spec: advance_plan.md § Phase A → Mod 176, and
`docex_report_design.md` (§ Overview, § Agent v. Operator Usage, § Docs →
Summarizing Metrics and Data). This overview records the design decisions; the
step-by-step is in `implementation.md`.

## What ships

- A new top-level command `docex report <type> [--format data|full]`.
  - `type` currently accepts only `docs`.
  - `--format` defaults to **`full`**. Until Mod 177 lands, `full` **stubs to
    `data`** behind a clear `TODO(mod 177)` (prints a one-line stderr note, then
    emits the `data` JSON). The command MUST accept `--format data` and the
    `report <type>` dispatch MUST be complete and correct.
- `docex report docs --format data` — deterministic JSON on **stdout**,
  diagnostics on **stderr**, sorted/stable, describing token-weight buckets for
  (a) the design-doc corpus and (b) the source code.

## Design decisions

### One graph load, from the shared linkmap builder

The design-doc bucket tree is built from `load_code_level_graph(project_root,
cbs)` (linkmap.py) — **not** a re-walk of `plans/design`. That one call yields
both the `design` nodes (used for the design tree; classification + `tokens`
already computed) and the `source` nodes (used for the source tree's
codebase/module classification and its git-tracked scope). Token estimates are
therefore the **same estimator** linkmap and `cxt_groups` use
(`_estimate_tokens`, `_CHARS_PER_TOKEN = 2.4`) — SC5.

### The bucket model + the `etc` invariant

Every bucket is `{name, tokens, children?}`. A leaf omits `children`. Uniform
rule at every bucket that has children: `remainder = tokens - sum(child.tokens)`;
if `remainder > 0`, append a final child `{name: "etc", tokens: remainder}`.

- **Grouping buckets** (primary design buckets, their named sub-groups, per
  codebase, per module) define `tokens = sum(member-file weights)` and their
  children partition those files exactly ⇒ `etc = 0` (omitted). A stray file
  that matches no named child still lands in an explicit **"Other Files"** child,
  so nothing is silently dropped.
- **arc42 file buckets** (`boundary_conditions.md`,
  `concepts_and_decisions.md`, `structures_and_views.md`) are the one place the
  `etc` invariant does real work: `tokens = max(file-weight, Σ section weights)`;
  children are the file's level-1 (`#`) sections; `etc` = the unsectioned
  remainder (the preamble before the first heading + rounding). Deterministic:
  sections in document order; fence-aware so a `#` inside a code fence is not a
  heading.
- **Source file buckets** partition the file's characters into the five leaf
  categories (below), which sum bottom-up to the file's `tokens` ⇒ `etc = 0`.
  ("Other / Unlintable" is itself the file-level catch-all, so no `etc` is
  needed for source.)

### Design-doc bucket tree (matches `docex_report_design.md` exactly)

Path-based classification of each `design` node (fpath under `plans/design/`,
`<cb>` = a known codebase):

- **L1 Standard Roots**: `boundary_conditions.md`, `concepts_and_decisions.md`,
  `structures_and_views.md` (each split into arc42 `#` sections + `etc`);
  **Diagrams** → `project_diagram.mmd`, `service_diagram.mmd` (NOT module);
  **ADR Indices** → `adr_index.md`, `adr_active.md`; `lexicon.md`.
- **L1 Detail Docs**: **specifics** → every `plans/design/specifics/**` file;
  `quality_scenarios.md`; `unknowns.md`; **Other Files** → any other top-level
  `plans/design/*` doc not named above (e.g. `doctrine_ext.md`).
- **L2 Architecture Docs** (per-codebase files, name form `<cb>/filename`):
  **Module Diagrams** → each `<cb>/module_diagram.mmd`; **specifics** → each
  `<cb>/specifics/**`; **Other Files** → other `<cb>/**` not under `module/`.
- **L3 Module Docs**: per codebase → every file in `plans/design/<cb>/module/**`.
- **ADRs**: a single summed leaf = every `plans/design/adrs/**` file (indices
  excluded — they are separate top-level files, not under `adrs/`). Not split
  deeper.

Only buckets whose members exist are emitted.

### Source-code bucket tree

Per codebase → per module (hex; `module == "none"` files bucket at a codebase
"(root)" tier, and a wholly non-hex codebase has no module tier) → per file →
five leaves: **inline comments**, **docstrings**, **references**, **code**,
**other / unlintable**. Source files come from the code_level graph's `source`
nodes (git-tracked `core/<cb>/src/**` only — compiled artifacts are gitignored).

### Linting (the judgment call I resolved)

Real linting for:
- **Python** (`.py`) — `#` line comments, `"""`/`'''` docstrings, strings/code.
- **C-family** — a single `//` + `/* */` lexer covering **JavaScript/TypeScript**
  (`.js/.jsx/.ts/.tsx`), **Go** (`.go`), **C/C++** (`.c/.h/.cc/.cpp/.hpp/…`),
  **C#** (`.cs`), and **Rust** (`.rs`). This covers Python + JavaScript + Go (the
  required minimum) and, essentially for free, the rest of the doctrine's
  language list (`languages.md`). Docstring detection in C-family:
  JSDoc `/** */`, Rust `///` / `//!` / `/*! */`; other comments are inline. Go
  has no distinct docstring form → all Go comments are inline (noted).
- Everything else → the whole file's weight goes to **other / unlintable**.

**References** are detected *within* comment/docstring text as file-path-like
tokens (a name with a recognized source/doc extension, optionally
slash-qualified — this also catches markdown-link targets). Reference spans are
carved out of the comment/docstring char counts and re-attributed to the
`references` leaf, so the five leaves remain a clean char partition.

## Aligned artifacts (six)

Touched by this mod:
1. `doctrine/infrastructure/docex.md` — a new `report` section + a `report` row
   in the tools table (**pre-authorized** by the plan, SC 176.6).
2. `docex/plans/design/**` — `subcommand_surface.md` gets a `report` row + a
   short subsection; `structures_and_views.md` gets a one-line note and the
   `docs`/`report` package line under Repository Structure. (Done by the
   corporal in the Documentation step, not the implementor.)
3. `src/docex/**` — the new `report/` package + dispatcher wiring.
4. `tests/**` — unit tests over a fixture corpus (bucket sums + `etc`).

Assessed, **no change expected**:
5. `tables/roles/*.yml` — `report` introduces no role/engine.
6. `doctrine_excerpts/index.yml` — `report` introduces no **infrastructural
   resource**, so no entry (confirmed against the "what earns an entry"
   criterion in `docex_process.md`).

## Open design questions

None — the plan and design doc pre-specify this mod; the one judgment call
(linting scope) is resolved above and reported, not escalated.

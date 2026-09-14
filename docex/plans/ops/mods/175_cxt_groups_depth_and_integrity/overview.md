# Mod 175 — `cxt_groups_depth_and_integrity`

Phase A, mod 1 of advance 014. Extends `docex docs cxt_groups <tokens_max>
{<git_ref>|all}` with two optional args that change how subject files are grouped.
Both defaults reproduce today's output byte-for-byte. Pure docex-internal work;
no foundation-specific behavior. Design is fully specified by the advance plan
and prep — this overview records the design decisions and their justification.

## Goal

Deliver two fixed contracts Phase B (the doc-skill refactor) will build on:

1. **`--depth {design_docs | code_level}`** — mirrors `docex docs linkmap
   <depth>`; selects the tracked scope the groups are drawn from. `code_level`
   (today's behavior) stays the default.
2. **`--optimize {tokens | module_integrity}`** — selects the packing objective.
   `tokens` (today's overlap-greedy bin-packing) stays the default;
   `module_integrity` never splits a category (module / codebase / design-docs
   set) across groups except where forced, and then only across pure groups.

## 175a — `--depth`

`cxt_groups` today always builds the `code_level` graph via
`load_code_level_graph`. The `design_docs` graph is the same graph builder
(`build_linkmap`) fed only the design-file enumeration (no tracked-source
enumeration) — identical to how `docex docs linkmap design_docs` differs from
`code_level`. That single scope definition already lives in
`linkmap.py` (`_enumerate_design_files` / `_resolve_tracked_source` /
`build_linkmap`); 175a reuses it, adding **no second allowlist** (SC 175a.3).

### Design decisions

- **New loader `load_design_docs_graph`** added to `linkmap.py` as the sibling of
  the existing `load_code_level_graph`, both delegating to the same enumeration +
  `build_linkmap` primitives. Keeping `load_code_level_graph` as the code_level
  entry point preserves the existing monkeypatch seam that the current
  `cxt_groups` unit tests use, so the default path is provably unchanged.
- **Dispatch in the wrapper**, not inside `build_context_groups`: the wrapper
  picks the graph by depth, then packs. This keeps the pure packing functions
  scope-agnostic.
- **At `design_docs` depth, subjects are exclusively `design` nodes** — the graph
  scans no source files, so no `source` nodes exist and the existing
  `n.type in ("design","source")` subject filter yields design-only (SC 175a.1).
- **Byte-identical default** (SC 175a.2): omitting `--depth` (or `code_level`) runs
  the exact current code path — same graph, same `build_context_groups`, same
  `render_cxt_groups_json`. **The rendered JSON schema is NOT extended** with
  `depth`/`optimize` keys — adding keys would break byte-identical output; the
  caller already knows what it asked for.

## 175b — `--optimize module_integrity`

Implements the prep's Module Integrity table (`adv_014_prep.md § Module
Integrity`) exactly. `tokens` mode is left completely untouched (SC 175b.3
byte-identical) — `module_integrity` is a **separate** packing function
(`build_module_integrity_groups`) that the wrapper dispatches to.

### Category model

Every subject file belongs to exactly one leaf category, classified purely from
its linkmap node metadata:

- `design` node → the **design-docs** category (one category spanning all design
  docs, regardless of the `<cb>` folder an L2/L3 doc sits under — a doc is a doc).
- `source` node with `module != "none"` → the **module** category
  `(codebase, module)`.
- `source` node with `module == "none"` (non-hex codebase, or codebase-level
  source such as `root.py`) → the **codebase** category directly (a codebase-root
  residual with no module tier).

Top-level units are `design` and each `codebase`. A codebase subdivides into its
modules plus a codebase-root residual; design docs and modules are leaves.

### The rule (reverse-engineered from and validated against the prep table)

Never split a top-level unit across groups. When forced (a unit's self+overhead
cost exceeds `tokens_max`):

- **design docs / a non-hex codebase / a module** (a *leaf*) → split only across
  groups that contain **nothing but that leaf's files** (prep rows 3 & 6).
- **a hex codebase** → subdivide into whole modules (+ the codebase-root
  residual) and pack those into groups that contain **only that codebase's
  files**; a group holding a *partial* codebase may not contain any other unit's
  files (prep row 2 is invalid precisely because group B mixes a second
  codebase's module in with a fragment of the first). Whole modules of the same
  fragmented codebase may share a group (prep row 1 generalizes to
  `A={M-1,M-2} | B={M-3,M-4}`); a module that is itself too big splits across
  module-pure groups (prep row 5 invalid: a split module's group holds another
  module).

Whole units that each fit may be freely combined into one group (prep row 4:
both whole codebases in group A, design in B) — combining whole units never
fragments anything.

The prep table maps to these rules:

| A | B | Valid | Rule |
| --- | --- | --- | --- |
| `M-1` | `M-2` | Yes | codebase fragmented on whole-module lines; each group pure-to-C-1 |
| `M-1` | `M-2`,`M-3` | No | group B mixes another codebase's file with a fragment of C-1 |
| `M-1` | `M-1` | Yes | leaf module split; both groups pure-to-M-1 |
| `M-1..M-4` | design | Yes | both codebases whole in A; design whole in B |
| `M-1` | `M-2`,`M-1` | No | split module M-1's group B holds another module |
| design | design | Yes | leaf design split; both groups pure-to-design |

### Algorithm (`build_module_integrity_groups`, pure)

1. Reuse the same overhead/cost machinery as `build_context_groups` (`ov` map,
   `cost(set)` = tokens of subjects∪overhead union).
2. Classify subjects into top-level units.
3. For each unit (sorted): if `cost(unit) <= tokens_max` → a **whole atom**; else
   fragment — a leaf leaf-splits into pure dedicated groups; a hex codebase
   subdivides into module/root children, each of which is a whole atom (packed
   only among this codebase's dedicated groups) or leaf-splits if oversize.
4. Pack all whole atoms (design + whole codebases) into as few groups as possible
   (deterministic first-fit under `tokens_max`); a whole atom is never broken.
5. Emit each group via the shared `_emit_group`; sort groups by subjects.

Graceful degradation (SC 175b.5): an indivisible unit (a single file) whose
self+overhead alone exceeds `tokens_max` becomes its own singleton group and is
reported to the wrapper's oversize list — exit stays 0 with the same stderr note
the tokens mode emits.

### Composition with `--depth` (SC 175b.4)

`--depth design_docs --optimize module_integrity` produces one top-level unit
(`design`): one group if it fits, else design-only leaf-split groups. Falls out
of the algorithm with no special-casing.

## Aligned artifacts touched

- `src/docex/docs/cxt_groups.py` (new packing fn + wrapper args) and
  `src/docex/docs/linkmap.py` (new `load_design_docs_graph`).
- `src/docex/__main__.py` (`--depth` / `--optimize` argparse options + dispatch).
- `tests/unit/test_docs_cxt_groups.py` + `tests/unit/test_docs_dispatcher.py`.
- Doctrine `doctrine/infrastructure/docex.md` `cxt_groups` bullet (pre-authorized
  by the advance plan, SC 175.6).
- Docex design docs: `plans/design/specifics/subcommand_surface.md` and
  `plans/design/structures_and_views.md` (command-family mentions).
- `tables/roles/*.yml` — untouched (no role/engine change).
- `doctrine_excerpts/*.md` + `index.yml` — untouched (introduces no
  infrastructural resource).

## Design questions

None. The design is fully specified by the operator-approved advance plan and
prep; every decision above is derived from them.

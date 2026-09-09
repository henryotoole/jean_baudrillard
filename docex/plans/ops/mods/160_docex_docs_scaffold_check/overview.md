# Mod 160 — `docex docs`: scaffold + structure checks

## Goal

Make the new (Mod 159) documentation structure **mechanically enforceable** by
`docex`. Add a `docs` command group with two subcommands:

- `docex docs scaffold` — lay down the standard design-doc file set under
  `plans/design`, idempotently (never clobber; create only what is missing).
- `docex docs check` — blocking validation with per-problem output and a nonzero
  exit on failure, running **two** checks: *missing-standard-file* and
  *reachability* (orphan detection).

Then wire `docex docs check` as a **blocking gate** of `docex check`.

`docs adr` (ADR index generation) and the diagram comparators are **out of scope**
(Mods 3 and 4 respectively). The `check` command is structured so Mod 4 can add the
comparators as a third check without disturbing these two.

## Design source

- `doctrine/practices/docs.md` § Standard Documentation Structure (the file set +
  `plans/design` layout), § Standard Diagrams, § LLM Agent Usage.
- `docex/plans/advances/010_archdoc_overhaul/research.md` § Reachability Check
  (the orphan-detection algorithm) and § Missing Standard File.
- `docex/plans/advances/010_archdoc_overhaul/adrs.md` (ADR filename/format, for the
  `adrs/` dir + index files scaffold lays down).

## The canonical standard set (single source of truth)

Scaffold and check MUST agree on ONE definition. It lives in a new module
`src/docex/docs/standard_set.py` as a list of typed entries; both subcommands
consume it. An entry carries: a path relative to `plans/`, a `kind`
(`file` | `dir`), an `optional` flag, and a `scope` (`project` | `codebase`).
`codebase`-scoped entries are expanded once per `infra.yml` codebase at resolution
time (`{cb}` placeholder).

### Project-scoped (L1), always present

| Path (under `plans/`) | Kind | Optional |
| --------------------- | ---- | -------- |
| `design/boundary_conditions.md` | file | no |
| `design/concepts_and_decisions.md` | file | no |
| `design/structures_and_views.md` | file | no |
| `design/lexicon.md` | file | no |
| `design/unknowns.md` | file | no |
| `design/adr_index.md` | file | no |
| `design/adr_active.md` | file | no |
| `design/project_diagram.mmd` | file | no |
| `design/service_diagram.mmd` | file | no |
| `design/doctrine_ext.md` | file | **yes** |
| `design/quality_scenarios.md` | file | **yes** |
| `design/adrs` | dir | no |
| `references` | dir | no |
| `product` | dir | **yes** |

### Codebase-scoped (L2), one per `infra.yml` codebase `{cb}`

| Path (under `plans/`) | Kind | Optional |
| --------------------- | ---- | -------- |
| `design/{cb}/module_diagram.mmd` | file | no |
| `design/{cb}/module` | dir | no |
| `design/{cb}/specifics` | dir | no |

This resolves the kickoff's "per-codebase dimension" design authority: the L1 set
is always laid down; the per-codebase set is derived from `infra.yml`'s codebases
(via the existing `orchestrate._common.codebases(ctx)` helper). No doctrine
ambiguity was hit, so no escalation.

**Empty directories** (`adrs/`, `references/`, per-codebase `module/`, `specifics/`)
cannot be tracked by git. Scaffold drops a `.gitkeep` in each so the directory
survives a clone/worktree checkout (which is what the `docex check` gate reads).

## `docex docs scaffold`

For every entry in the resolved standard set:
- `file`: if it does not exist, create parent dirs and write a **template** body.
  Existing files are never touched (idempotent).
- `dir`: `mkdir(parents=True, exist_ok=True)`; if the directory is empty, add a
  `.gitkeep`. Optional dirs (`product`) are created too — cheap, and keeps the
  layout obvious. (Optional *files* are NOT created; creating them would force a
  reachability link obligation for a file the project may not want.)

### Templates and reachability coupling

A freshly-scaffolded tree must pass its own `docs check`. The only mandatory,
non-root file is `unknowns.md`, so `concepts_and_decisions.md`'s template links to
it (in its `# Risk, Unknowns, and Tech Debt` section). All other mandatory files
are reachability **roots** (see below) and need no incoming link. Templates carry
the doctrine-mandated arc42 headers (per docs.md § arc42) so the files are useful
stubs, not empty:
- `boundary_conditions.md`: `# Intro and Goals` / `# Constraints` /
  `# Context and Scope` / `# Quality Requirements`
- `concepts_and_decisions.md`: `# Cross-Cutting Concepts` / `# Solution Strategy` /
  `# Risk, Unknowns, and Tech Debt` (+ link to `unknowns.md`)
- `structures_and_views.md`: `# Building-Block View` / `# Runtime View` /
  `# Deployment View`
- `lexicon.md`: `# Project Lexicon`
- `unknowns.md`: `# Unknowns` + the doctrine's unknowns table header
- `adr_index.md` / `adr_active.md`: heading + the doctrine's index/active table
  headers (Mod 3 will regenerate these)
- `*.mmd`: a minimal valid mermaid stub (`graph TD` + a placeholder node)

## `docex docs check`

Two checks; each yields a list of human-readable problems. The command prints a
per-problem report and exits `1` if any problem exists, else `0`.

### Skip-when-absent

If `plans/design/` does not exist, **both checks pass** with an informational
"no plans/design — skipped" note. Rationale (a deliberate design decision):
- The checks are anti-**drift** guards for an *existing* design corpus, exactly as
  `_gate_contracts` skips when there is no `infra.yml`.
- It keeps the wiring from breaking every fixture / project that predates a design
  tree, and keeps `docex`'s own repo (still on `plans/core`) green under
  `docex check` until Mod 7 dogfoods the migration.
- Inception (Mod 5) runs `docex docs scaffold` at project birth, so real projects
  acquire the tree; from then on the checks enforce it.

### Check 1 — missing-standard-file

Resolve the standard set against the project's codebases; for each **non-optional**
entry, verify it exists with the right kind. Report each missing one as
`missing standard file: plans/<path>` (or `... directory`).

### Check 2 — reachability (orphan detection)

Exactly the research.md algorithm:
1. Enumerate every file under `plans/design`, **excluding** dotfiles and anything
   inside a dot-directory (so `.gitkeep` never counts as a doc).
2. **Roots** = the always-loadable top-level entry set (docs.md § LLM Agent Usage):
   `lexicon.md`, the three arc42 files (`boundary_conditions.md`,
   `concepts_and_decisions.md`, `structures_and_views.md`), the standard diagrams
   (`project_diagram.mmd`, `service_diagram.mmd`, every
   `{cb}/module_diagram.mmd`), and the two ADR entry points (`adr_index.md`,
   `adr_active.md`). Only roots that actually exist seed the graph.
3. Build the link graph: from each visited file, follow links to other files under
   `plans/design`. Parse **markdown links** `[text](target)` and **mermaid click**
   directives (`click NODE "target"` / `click NODE href "target"`). Strip anchors,
   skip URL schemes (`http:`/`https:`/`mailto:`…), resolve relative to the
   containing file, and keep only targets that resolve to an existing file under
   `plans/design`.
4. BFS from the roots. Any enumerated file not reached is an **orphan**.

Report each orphan as `unreachable doc: plans/design/<path> (not linked from any
standard doc or diagram)`.

No per-doc frontmatter is used — reachability is computed from the link graph
itself, per docs.md.

## Wiring into `docex check`

Add `_gate_docs(worktree, worktree_ctx, report)` to `pipeline/check.py`, run
alongside the other gates (against the **worktree**, using
`codebases(worktree_ctx)`). It adds two report rows: `docs_standard_files` and
`docs_reachability`. Both PASS (skipped) when the worktree has no `plans/design`.
Any failure fails the aggregate check (exit 1), same as every other gate.

The check logic is factored so the standalone command and the gate call the **same**
functions (`missing_standard_files(...)`, `unreachable_docs(...)`,
`design_root_exists(...)`) — no second implementation to drift.

## Module layout

```
src/docex/docs/
├── __init__.py        # public API re-exports
├── standard_set.py    # StandardEntry, STANDARD_SET, resolve(codebases)
├── scaffold.py        # templates + run_docs_scaffold(ctx)
└── check.py           # missing_standard_files / unreachable_docs /
                       # design_root_exists / run_docs_check(ctx)
```

Dispatcher: add `_cmd_docs` (a `docs <scaffold|check>` subparser, mirroring
`_cmd_secrets`/`_cmd_config`), register in `_HELP_TEXT`, `_GROUPS` (a new
`Documentation` group), and `_build_handler_table`.

## Six-artifact alignment

- `doctrine/.../*.md`: docex.md/cicd.md rewiring is **Mod 6** (out of scope, per
  advance plan). Noted as intended deferral, not drift.
- `docex/plans/core/*.md`: add a `docs` row to `masterplan.md` § Subcommand Surface
  (in scope — docex's own core doc).
- `tables/roles/*.yml`: untouched (no role/engine change).
- `src/docex/**`, `tests/**`: this mod.
- `doctrine_excerpts/*.md` + `index.yml`: **no entry** — `docs` introduces no
  *infrastructural resource* (it is a command over repo files), and the criterion in
  `docex_process.md` § Additional Artifacts excludes commands.

## Tests (`tests/unit/`, unmarked so the collection-partition guard holds)

- `standard_set` resolution: L1 always; per-codebase entries expand per codebase.
- scaffold: creates the full set; is idempotent (second run is a no-op, existing
  files untouched); a freshly-scaffolded tree passes both checks.
- missing-file: a tree missing a non-optional file fails; missing an optional file
  passes; absent `plans/design` skips.
- reachability: a well-formed tree passes; an orphan file fails and is named; a
  file made reachable by a link (md and mermaid-click) passes.
- gate wiring: `docs_standard_files` + `docs_reachability` appear in the check
  report; a fixture without `plans/design` skips both (guards existing check tests).

No integration test is warranted — scaffold/check cross no real boundary (docker /
AWS / git); it is pure filesystem work.

## Open design questions

None. The per-codebase dimension and the skip-when-absent policy are resolved above
from docs.md + research.md; neither required a doctrine ruling.

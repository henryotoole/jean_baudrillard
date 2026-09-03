# Mod 164 — Document the `docex docs` doc-tooling in doctrine prose

## Goal

Mods 160–161 shipped the `docex docs` command family (`scaffold`, `check`, `adr`)
but the doctrine *prose* was fenced out and left several stubs/TODOs. This mod
fills that prose so the doctrine accurately describes the shipped tooling. No
code changes; documentation only.

Mod 162 (diagram comparators) was **dropped** by operator ruling. The doc-tooling
command set is final and closed: `docex docs {scaffold, check, adr}`. No
comparator is documented or referenced anywhere.

## Ground truth (verified against shipped code)

- `docex/src/docex/docs/{scaffold,check,adr,standard_set}.py` and the `docs`
  dispatcher in `docex/src/docex/__main__.py`.
- `docex docs scaffold` — idempotently lays down the standard design-doc set
  under `plans/design`; never clobbers an existing file, never auto-creates the
  optional entries, `.gitkeep`s empty standard dirs. Reports what it created.
- `docex docs check` — three checks: **missing standard file**, **reachability**
  (orphan doc, from the link graph), **ADR-index freshness**. No-op/pass when the
  project has no `plans/design`. The standalone command and the `docex check`
  gate call the same pure functions.
- `docex docs adr` — regenerates `adr_index.md` + `adr_active.md` from
  `plans/design/adrs/*.md`; deterministic + idempotent; generated files carry a
  "do not edit by hand" marker.
- `docex/src/docex/pipeline/check.py` `_gate_docs` adds three **blocking** rows to
  `docex check` — `docs_standard_files`, `docs_reachability`, `docs_adr_fresh` —
  each skipped (PASS) when the worktree has no `plans/design`.

## Design

Four doctrine-prose targets, all additive:

1. **`doctrine/infrastructure/docex.md`** — add a `docs <op>` row to the command
   reference table (grouped with the other `scaffold`-family commands) and a new
   `### docs` detail subsection covering all three subcommands and stating that
   `docs check` is a blocking sub-gate of `docex check`. Also thread a brief
   "design-doc validation" mention into the existing `### check` prose so the
   gate sequence stays accurate.

2. **`doctrine/infrastructure/cicd.md`** — in the **Check Step** § Process, add a
   blocking "documentation checks" step listing the three sub-checks and noting
   they skip when there is no `plans/design`.

3. **`doctrine/practices/docs.md`** — fill the `## Docex` TODO stub with the
   command overview (`scaffold` / `check` / `adr`) and a `### Reachability Check`
   subsection (prose ported from `research.md`, kept accurate to the shipped
   roots). The two dropped TODO bullets (`infra.yml` matches service diagram /
   standard diagrams match each other) are **removed**, not documented — they were
   the dropped comparator. Only the `## Docex` section is touched; the rest of
   docs.md is finalized.

4. **`doctrine/practices/adrs.md`** — fill the `## Docex` TODO with `docex docs
   adr` (regenerates the two indexes; `docs check` gates their freshness). Only
   that section is touched.

### Reachability roots (accuracy note)

Prose describes the standard roots as they actually are in code
(`_ROOT_NAMES` + per-codebase module diagrams): the L1 arc42 files
(`boundary_conditions.md`, `concepts_and_decisions.md`, `structures_and_views.md`),
`lexicon.md`, the standard diagrams (`project_diagram.mmd`, `service_diagram.mmd`,
and each codebase's `module_diagram.mmd`), and the two ADR indexes
(`adr_index.md`, `adr_active.md`).

## Scope fence

- Doctrine prose only: `docex.md`, `cicd.md`, the `## Docex` sections of `docs.md`
  and `adrs.md`, plus this mod folder.
- No edits to `docex/` source or `docex/plans/` (Mod 7 migrates docex's own tree);
  no edits to `skills/`/`agents/` (mod 163 done); no re-opening finalized sections
  of docs.md/adrs.md.

## Alignment note

`docex.md` is **not** mirrored in `docex/doctrine_excerpts/` (that directory only
mirrors the `docex why <resource>` resource files). No excerpt sync required. The
full six-artifact alignment + cohere run at advance close-out re-verifies.

## Gate

`python3 skills/cohere/executor/linkcheck.py` must be GREEN. Manual-test pause
waived. Two commits per the mod cycle. CHANGELOG `[Unreleased]` entry; no VERSION
bump; no merge.

## Design questions

None. The command set and behavior are fixed by shipped code; the CO's brief
enumerates the exact targets. (One inaccuracy in the brief — the `### Reachability
Check` subsection does not pre-exist in docs.md; it lives in `research.md` and is
ported in here. No decision needed.)

## Residue flagged for later

- `docs.md § Standard Diagrams` still says the service diagram "should match
  `infra.yml`. See [Docex](#docex) for more info." — a promise the dropped
  comparator would have fulfilled. Left untouched (finalized section, outside this
  fence); flagged for the CO/a later mod to soften if desired.
- The existing mod-160 CHANGELOG entry says "the diagram comparators are later
  mods in this advance" — now false since mod 162 was dropped. Left as-is (not
  this mod's entry); flagged.

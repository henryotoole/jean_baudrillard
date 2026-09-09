# Mod 163 — Rewire `skills/` + `agents/` to the new documentation doctrine

## Goal

Mod 159 rewired the `doctrine/` prose to the new documentation model (arc42 state
docs, standard diagrams, ADRs, the `plans/design` + `plans/ops` layout) but was
fenced OUT of `skills/` and `agents/`, which still speak the old vocabulary
(`masterplan.md`, `plans/core`, `plans/modifications`, "core planning docs",
`conventions.md`). This mod brings `skills/` and `agents/` into coherence with the
installed doctrine.

## What must be propagated (from Mod 159)

- **Layout:** `plans/core` → `plans/design`; `plans/modifications` → `plans/ops/mods`;
  `plans/advances` → `plans/ops/adv`; new optional `plans/product`; `references` stays.
- **Model:** `masterplan.md` is retired. Project-level (L1) design is now the arc42
  state docs (`boundary_conditions.md`, `concepts_and_decisions.md`,
  `structures_and_views.md`, `lexicon.md`, `unknowns.md`), the **standard diagrams**
  (Project / Service / Module), per-codebase L2/L3 docs
  (`${codebase}/module/`, `${codebase}/specifics`, `${codebase}/module_diagram.mmd`,
  optional `${codebase}/db_schema.md`), and **ADRs** (`adrs/` + `adr_index.md` /
  `adr_active.md`). `conventions.md` is retired; its role (bespoke doctrine
  extensions) is now `doctrine_ext.md`.
- **Vocabulary:** the lexicon now defines **"Design Docs"** as the primary term with
  "core planning docs" kept as a synonym. Prefer "design docs" in rewritten prose.
- **New tooling:** `docex docs scaffold` (lay down the standard design-doc set),
  `docex docs check` (blocking: missing-file + reachability/orphan + ADR-index
  freshness), `docex docs adr` (regenerate ADR indexes). Verified present in
  `docex/src/docex/__main__.py` / `docex/src/docex/docs/`.

## Critical scoping finding — docex's OWN plans are NOT migrated yet

`docex/plans/` still uses the **old** layout (`core/` with `masterplan.md`,
`modifications/`, `advances/`) because Mod 7 of this advance dogfoods that migration
*later*. Therefore every skill reference that points at **docex's own project docs**
must be LEFT ALONE — rewiring them now would create dangling pointers to files that
don't exist yet. This affects:

- `skills/docex-edit/SKILL.md` (points at `$jb/docex/plans/core/masterplan.md`, etc.)
- `skills/doctrine-update/SKILL.md:60` (points at `$jb/docex/plans/core/masterplan.md`)
- `skills/cohere/SKILL.md:41` and `skills/cohere/executor/` (linkcheck default roots
  include `docex/plans/core`; the doctrine-cohere skill audits the doctrine corpus
  with its own `linkcheck.py`, not `docex docs check`).
- `skills/cohere/executor/tests/test_linkcheck.py` `mirror_*/plans/core` fixtures are
  synthetic temp-dir paths for the duplicate-filename test — not real doc paths.

These are flagged as **deferred residue**: when Mod 7 migrates `docex/plans`, those
references (and `linkcheck.py`'s default roots) must move to the new layout in the
same cycle.

Only references describing a **generic project's** layout (what the doctrine now
prescribes for any downstream project) get rewired here.

## Targets to change

| File | Change |
| ---- | ------ |
| `skills/inception/SKILL.md` | description: "masterplan" → "design brief"; body: "design of the core planning docs" → arc42/design-doc framing; reconcile with updated `inception.md` (design brief seed + `docex docs scaffold`). |
| `skills/project-cohere/SKILL.md` | Rewrite doc-tier model → new five-classification / L1(arc42)+diagrams / L2 / L3 / ADR model; `plans/core`→`plans/design`; retire `masterplan.md` as apex → L1 arc42 state docs; `conventions.md`→`doctrine_ext.md`; subagent-prompt cross-cutting doc list → arc42 L1 set + standard diagrams; add note that mechanical structural checks can be delegated to `./bin/docex docs check`. Preserve all heading anchors. |
| `skills/project-cohere/executor/word_count.py` | `CORE_DOCS_SUBPATH = plans/core` → `plans/design`; docstring/comment vocabulary. |
| `skills/project-cohere/executor/chunk_map.py` | `_hints()`: `plans/core`→`plans/design`; module-doc path `${cb}/hex/${m}.md` → `${cb}/module/${m}.md`; `_mds(.../hex)` → `.../module`; `db_schema` path under `plans/design`. |
| `agents/corporal/mod-developer.md` | description: "core planning docs" → "design docs"; body: "changes to the `masterplan.md`" → "changes to the project's design docs". |
| `skills/skill-iteration/references/evaluation.md:103` | "core planning docs" → "design docs" (vocabulary). |

## No-change (verified clean or out of scope)

- `agents/private/mod-implementor.md`, `agents/sergeant/doctrine-advance.md` — no
  doc-structure references (grep-clean).
- `skills/writing-adrs/` — already authored on the new layout (Mod 159).
- `skills/docex-edit/`, `skills/doctrine-update/`, `skills/cohere/` — see the
  docex-plans finding above; left unchanged, flagged as deferred residue for Mod 7.
- `agents/corporal/mod-developer.md:26` test-discipline wording (`docex test [subset]`)
  is a test-tier concern, not doc-doctrine — out of scope for this mod.

## Gate

`python3 skills/cohere/executor/linkcheck.py` GREEN before COMPLETE.

## Design questions

None. Intent is clear and the change is a deterministic propagation of Mod 159's
decisions. Proceeding per the CO's "drive to COMPLETE" instruction.

# Mod 163 — Implementation Steps

Rewire `skills/` and `agents/` to the new documentation doctrine (arc42 state docs,
standard diagrams, ADRs, `plans/design` + `plans/ops` layout). Repo root is
`/home/ubuntu/.claude/jean_baudrillard`. All paths below are relative to that root.

## Hard constraints

- Edit ONLY files under `skills/` and `agents/`. Do NOT touch `doctrine/`, `docex/src/`,
  or `docex/plans/` (except this mod's own folder, which needs no edits from you).
- Do NOT touch any reference that points at **docex's own project docs**
  (`docex/plans/core`, `docex/plans/core/masterplan.md`, docex's `modifications/` /
  `advances/`). Those stay in the old layout on purpose. Specifically leave
  `skills/docex-edit/SKILL.md`, `skills/doctrine-update/SKILL.md`,
  `skills/cohere/SKILL.md`, and everything under `skills/cohere/executor/` UNCHANGED.
- Preserve every markdown heading and its anchor in `project-cohere/SKILL.md` — other
  sections link to them (`#source-of-truth`, `#classes-of-problems`, `#prep`,
  `#enumerate-chunks`, `#consistency-pass`, `#3-unimplemented-feature`,
  `#4-undocumented-code`, `#1-documentation-is-inconsistent`).

## New-layout reference facts (from the installed `doctrine/practices/docs.md`)

- Design docs live at `$pr/plans/design/`.
- L1 arc42 state docs: `boundary_conditions.md`, `concepts_and_decisions.md`,
  `structures_and_views.md`, `lexicon.md`, `unknowns.md` (+ optional
  `doctrine_ext.md`, `quality_scenarios.md`).
- Standard diagrams: `project_diagram.mmd`, `service_diagram.mmd`, and per-codebase
  `module_diagram.mmd`.
- Per-codebase (L2/L3): `$pr/plans/design/${codebase}/module/` (module docs),
  `$pr/plans/design/${codebase}/specifics/` (L2 specifics),
  `$pr/plans/design/${codebase}/module_diagram.mmd`, optional
  `$pr/plans/design/${codebase}/db_schema.md`.
- ADRs: `$pr/plans/design/adrs/` + `adr_index.md` / `adr_active.md`.
- `masterplan.md` and `conventions.md` are RETIRED. There is no single apex file;
  the most load-bearing L1 doc is `boundary_conditions.md`. Bespoke doctrine
  extensions (old `conventions.md` role) now live in `doctrine_ext.md`.
- New docex commands: `./bin/docex docs scaffold`, `./bin/docex docs check`
  (missing-file + reachability + ADR-index freshness), `./bin/docex docs adr`.

---

## Step 1 — `skills/inception/SKILL.md`

1a. In the frontmatter `description:` (line ~3), change
`"the inception flow that takes a masterplan through repo setup, design, ..."`
to
`"the inception flow that takes a design brief through repo setup, design, ..."`.

1b. In the "General Information" body pointer (line ~16), change
`"design of the core planning docs, infrastructure smoke test, ..."`
to
`"design of the arc42 design-doc corpus, infrastructure smoke test, ..."`.

1c. In the "Thread" list (line ~24), change
`"- Designing core planning docs (PART II) and the PART IV mod cycles follow the Resident `docs.md` and `modifications.md` practices, already in context."`
to name the new tooling and framing, e.g.:
`"- Designing the design docs (PART II) — the arc42 L1 state docs, the standard diagrams (Project / Service / Module), and per-codebase module docs — is driven by the initial design brief and laid down with `./bin/docex docs scaffold`; it plus the PART IV mod cycles follow the Resident `docs.md` and `modifications.md` practices, already in context."`

Keep the sentence a sound activity trigger; the `description` must still read as
"stand up a new project from nothing".

---

## Step 2 — `skills/project-cohere/SKILL.md`

2a. **Documentation Tiers section (lines ~10–18).** Replace the old 4-tier list and
the "core planning docs ... `$pr/plans/core/`" sentence with the new model. The
doctrine now recognizes five documentation classifications (Product, Design,
Code-Level, Operational, Reference); this skill still targets the **design docs**.
State that design docs live at `$pr/plans/design/` and split into:
- L1 project-level state docs, arc42-structured: `boundary_conditions.md`,
  `concepts_and_decisions.md`, `structures_and_views.md`, `lexicon.md`,
  `unknowns.md`, plus the standard diagrams (`project_diagram.mmd`,
  `service_diagram.mmd`);
- L2 codebase-level docs under `$pr/plans/design/${codebase}/` (incl.
  `module_diagram.mmd`, `specifics/`, optional `db_schema.md`);
- L3 module docs under `$pr/plans/design/${codebase}/module/`;
- ADRs (reasoning docs) under `$pr/plans/design/adrs/`.
Note that the skill primarily reconciles the state design docs (L1–L3) against code.
"Core planning docs" may be kept once as the synonym, but prefer "design docs".

2b. **Source of Truth section (lines ~22–26).** `masterplan.md` no longer exists.
Rewrite so the apex is the **L1 arc42 project-level state docs** (the most
load-bearing being `boundary_conditions.md`), which "should never be changed without
asking the operator to make a judgement call on the discrepancy." Then L2
codebase-level docs (direct children of `$pr/plans/design/${codebase}/`), then L3
module docs (under `$pr/plans/design/${codebase}/module/`). Replace the
`$pr/plans/core/...` and `.../hex` paths with the `plans/design` equivalents
(`module/` not `hex/`).

2c. **Class 4 lists (lines ~63–69).** Keep "hex module docs" wording but ensure it
reads coherently ("these belong in the module docs"). Change "core planning docs" at
line ~69 to "design docs".

2d. **Prep section (line ~97).** Change "read the project's core planning docs" to
"read the project's design docs". ADD a short sentence pointing at the mechanical
executor: the deterministic structural checks — missing standard files, doc
reachability/orphans, and ADR-index freshness — can be run with
`./bin/docex docs check` from the project root; this skill focuses on *semantic*
coherence that no compile step can verify. (Place this near the executor invocations
so the reader knows the mechanical/semantic split.)

2e. **Enumerate Chunks (lines ~111, ~120–123).** Change "read the full set of core
planning docs" → "design docs". In the handoff paragraph (line ~123), replace the
cross-cutting doc list `"(masterplan.md, plus conventions.md if present)"` with the
arc42 L1 set + standard diagrams, e.g.
`"(the L1 arc42 state docs — boundary_conditions.md, concepts_and_decisions.md, structures_and_views.md, lexicon.md — plus the standard diagrams, and doctrine_ext.md if present)"`.
Line ~120's "matching module doc" and line ~121's `db_schema.md` note stay valid.

2f. **Subagent prompt (line ~142).** Change the comment
`"{project_docs}          # masterplan.md, and conventions.md if present"`
to
`"{project_docs}          # L1 arc42 state docs + standard diagrams, and doctrine_ext.md if present"`.

2g. **Codebase Alteration + Consistency Pass (lines ~184, ~188).** Replace the two
`"change to masterplan.md"` clauses with "change to an L1 arc42 project-level state
doc" (same meaning: the highest-authority docs require operator judgement). Keep the
"always let the human operator make the ultimate decision" rule.

2h. **Final Summary (lines ~200, ~205).** "core planning documentation set" →
"design-documentation set"; commit-message example "Ran cohere on core planning docs"
→ "Ran cohere on design docs".

Leave the `description:` frontmatter as-is (it is structure-agnostic and still a
sound trigger).

---

## Step 3 — `skills/project-cohere/executor/word_count.py`

3a. Line ~28: `CORE_DOCS_SUBPATH = Path("plans") / "core"` →
`DESIGN_DOCS_SUBPATH = Path("plans") / "design"`. Update the single use in
`count_docs()` (the `core = root / CORE_DOCS_SUBPATH` line and its `core` local —
rename to `design` for clarity, or keep local name but point at the new constant).
Ensure the error message and rglob still work.

3b. Update vocabulary in the module docstring (line ~4 "core planning docs" →
"design docs"; line ~7 `$pr/plans/core` → `$pr/plans/design`) and the
`run_after` print label (line ~91 "All core planning docs" → "All design docs").

3c. This is a behavioral change (the script now measures `plans/design`). There are
no unit tests for this executor, so no test updates are needed — but run it once
against any scaffolded `plans/design` tree or confirm by reading that the path
resolves.

---

## Step 4 — `skills/project-cohere/executor/chunk_map.py`

In `_hints()` (lines ~245–269):

4a. `plans_core = root / "plans" / "core"` → `plans_design = root / "plans" / "design"`
(rename the local throughout the function).

4b. Module-doc existence check (line ~256):
`(plans_core / svc / "hex" / f"{m.name}.md")` →
`(plans_design / svc / "module" / f"{m.name}.md")`.

4c. Stale-module-doc scan (line ~259):
`_mds(plans_core / svc / "hex", recursive=False)` →
`_mds(plans_design / svc / "module", recursive=False)`.

4d. db_schema (line ~263): `plans_core / svc / "db_schema.md"` →
`plans_design / svc / "db_schema.md"`. The note text (code counterpart in
`core/${svc}/migrations`) stays correct.

Do NOT change the source-walking logic (`core/*/src`, `src/hex`) — that walks CODE,
which is unaffected by the doc-layout change.

---

## Step 5 — `agents/corporal/mod-developer.md`

5a. Frontmatter `description:` (line ~3): "updates core planning docs with resultant
changes" → "updates design docs with resultant changes".

5b. Escalation body (line ~22): "changes to the `masterplan.md`" → "changes to the
project's design docs". (This is a corporal deciding when a design decision needs
operator escalation; the new phrasing keeps that meaning.)

Do NOT change line ~26 (test-discipline wording) — out of scope for this mod.

---

## Step 6 — `skills/skill-iteration/references/evaluation.md`

6a. Line ~103: "`project-cohere` reads a project's core planning docs against its
code" → "... reads a project's design docs against its code". Single-word
vocabulary fix; leave the rest of the sentence.

---

## No contract changes

This mod touches no core-service surfaces, so no `$pr/infra/contracts/*` updates are
required.

## Verification (run after all edits)

1. `python3 skills/cohere/executor/linkcheck.py` — must exit GREEN (0 broken links,
   0 bad citations beyond the expected `Declined` block; read the counts, not just
   the exit code).
2. `grep -rn "plans/core\|plans/modifications\|plans/advances\|masterplan\|core planning\|core docs\|core project docs\|conventions.md" skills/ agents/` — the ONLY
   remaining hits allowed are the docex-own-plans references in
   `skills/docex-edit/SKILL.md`, `skills/doctrine-update/SKILL.md`,
   `skills/cohere/SKILL.md`, `skills/cohere/executor/**` (incl. the
   `mirror_*/plans/core` test fixtures). Any other hit is an unresolved target.
3. `python3 -c "import ast; ast.parse(open('skills/project-cohere/executor/word_count.py').read()); ast.parse(open('skills/project-cohere/executor/chunk_map.py').read())"` — both executors still parse.

Report: files touched, linkcheck result (with counts), and the residual grep output.

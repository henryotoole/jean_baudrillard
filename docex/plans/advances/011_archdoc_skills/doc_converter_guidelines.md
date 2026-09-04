# Pre-3.0.0 Design-Doc Conversion

A one-time, per-project procedure for converting a project's pre-3.0.0 `plans/`
(masterplan-centric) into the 3.0.0 documentation structure (arc42 L1 docs, the
standard diagrams, ADRs, and the `plans/{product,design,ops,references}` layout).
Intended to be packaged as a converter skill and/or driven from the `3.0.0`
upgrade guide.

It is heavily LLM-driven — the arc42 split is a judgment task — but the judgment
is **bracketed by deterministic `docex docs` gates** so structural validity is
never a matter of opinion.

## Relationship to `doc-refine`

`doc-refine` refines docs *within* the new structure; it **cannot create that
structure**, which is why it can't do this job alone. This converter builds the
structure, then hands off to a `doc-refine` pass for polish. Where the converter
*refactors* (de-historicize, extract reasoning, push detail down), it **reuses
`doc-refine`'s pass taxonomy** rather than restating it — the definitions live in
the `doc-refine` skill, and this plan only sequences them.

## Guiding Principles

1. **Nothing load-bearing is lost.** The arc42 split is lossy by nature
   (subtractive + reorganizing). The old tree is retained as `_old_plans` and a
   final **reconciliation pass** confirms nothing substantive vanished before it
   is deleted. Structural checks validate *shape*, not *completeness* — this pass
   is the completeness backstop.
2. **References are repo-wide and two-wave.** Files that merely move get their
   references fixed early; design docs that get split/merged get theirs fixed only
   after the refactor settles. Both waves sweep the *whole repo* (source comments,
   `infra.yml`, `CLAUDE.md`, …), not just `plans/` — `linkcheck` sees only
   doctrine-scoped links.
3. **De-historicize, don't blind-delete.** Historical prose ("mod 020 did X")
   often carries a still-true decision; strip the narrative framing but preserve
   the durable fact (present tense, or an ADR).
4. **Bracket with `docex`.** `docex docs scaffold` lays the skeleton up front;
   `docex docs check` (missing-file + reachability + adr-fresh) runs iteratively
   and as the final gate.
5. **Top-down.** Convert high-abstraction first (masterplan → L1) before the docs
   that depend on it.

---

## Translation Reference

### Masterplan Translation

Traditionally masterplans are broken into sections that map closely onto *arc42* —
the change is largely semantic.

| Masterplan Section | L1 Doc | Arc42 Section | Notes |
| ------------------ | ------ | ------------- | ----- |
| Preamble | `boundary_conditions.md` | Intro & Goals | In most masterplans, the text between the first level-one heading and the first level-two heading (usually "## Objectives"). Becomes the project introduction. |
| "## Objectives" | `boundary_conditions.md` | Intro & Goals — Requirements | We used to call these objectives; aligning with industry language and calling them requirements. |
| "## Terms and Concepts" | `concepts_and_decisions.md` | Cross-Cutting Concepts | Judgement required — not everything belongs in Cross-Cutting Concepts. Over-detailed passages should be shunted into an L1 (or L2) `specifics` folder, then summarized and linked down from `concepts_and_decisions.md`. |
| Lexicon | `lexicon.md` | "Glossary" (we don't use that word in `lexicon.md`) | Some masterplans have a Lexicon, some don't. Those that don't may still need one to define critical load-bearing words from "Terms and Concepts". |
| "## Architecture" | multiple | Solution Strategy, Deployment View, Building Block View | The bulk of architecture design lands here. Split across Solution Strategy, Deployment View, and Building Block View. Structure that the **standard diagrams** now capture can simply be deleted (see step 8 — the diagrams are *authored*, not merely inherited). |
| "## Flows" | `structures_and_views.md` | Runtime View | Transfers cleanly — a flow *is* a runtime view. |
| "## Risk / Unknowns / Tech Debt" (if present) | `concepts_and_decisions.md` + `unknowns.md` | Risk, Unknowns & Tech Debt | Risks and tech debt → `concepts_and_decisions.md`; discrete unknowns → the `unknowns.md` table. Projects lacking this section leave `unknowns.md` an empty scaffold. |

**Critical caveat:** in older projects the masterplan often became a catch-all for
LLM additions over many mod cycles. *Much of the material may not belong in an L1
standard doc at all.* The table is a starting point, not truth — in every
movement, let *arc42* guidelines decide.

`quality_scenarios.md` and `unknowns.md` are scaffolded fresh; seed them only if
the old masterplan carried the corresponding content.

### `conventions.md` → `doctrine_ext.md`

The old `doctrine_ext.md` was called `conventions.md`, and in many projects it
became a general-purpose dumping ground. Read it carefully and transfer **only**:
- transfer-table extension notes, and
- hexagonal naming-convention extensions

to `doctrine_ext.md`. Everything else is relocated per its true nature (detail →
`specifics`, reasoning → ADR, or deleted).

### `db_schema.md`

Most projects have a `db_schema.md` in the codebase directory of whichever
codebase owns the database. It belongs in that codebase's new L2 `specifics`
folder.

### Module Docs

Most module docs transfer over more or less intact, into
`plans/design/{codebase}/module/{module}.md`.

---

## Conversion Procedure

### Phase 1 — Mechanical relocation (deterministic, safe)

**0. Inventory / recon.** Enumerate the old tree: `masterplan.md`,
`conventions.md`, `db_schema.md`, module docs, and any bespoke folders (e.g.
`notes/`). Read `infra.yml` for the codebase list (the new per-codebase design
dirs) and the codebase→module mapping. Grep the **whole repo** for references
into `plans/` — this is the target list for the reference waves.

**1. Preserve the old tree.** `git mv plans _old_plans` — a sibling of the new
`plans/`, outside it so nothing (`docs check`, `linkmap`) scans it. Retained as
fallback and reference until the final reconciliation.

**2. Scaffold the new tree.** `docex docs scaffold` (lays down `plans/design`:
arc42 stubs, diagram stubs, `adrs/` + index stubs, per-codebase dirs), and
recreate `plans/product`, `plans/ops/{mods,adv}`, and `plans/references`.

**3. Mechanical relocations (no content change).** Copy the purely-moved files
into place: old `references` → `references`; `modifications` → `ops/mods`;
`advances` → `ops/adv`; bespoke folders (e.g. `notes/`) carried over.

**4. Reference-update — wave 1.** Repo-wide, for the moved-file paths only
(`ops/mods`, `ops/adv`, `references`, bespoke). Watch for the residue a link
checker can't see: prose, ASCII trees, source-comment references.
→ GATE: `docex docs check` (structure present) + a repo-wide grep confirms no
  stale references to the moved paths remain.

### Phase 2 — Design-doc refactor (judgment; reuses `doc-refine` passes)

**5. De-historicize.** Across the old design docs, strip "mod N did X" narrative
framing — preserving any still-true decision it carries (present tense, or route
to an ADR in step 6). (`doc-refine` State pass, subtractive.)

**6. Reasoning → ADRs.** Extract load-bearing reasoning into ADRs, numbered from
`0001`. If a decision's *reasoning* is absent but the decision is load-bearing,
still record the ADR. End the pass with `docex docs adr` so the indexes exist
(else the adr-fresh gate fails). (`doc-refine` State pass, subtractive/condensing.)

**7. Masterplan → L1 nucleus.** Split `masterplan.md` per the Translation
Reference into `boundary_conditions.md` / `concepts_and_decisions.md` /
`structures_and_views.md` / `lexicon.md`, shunting over-detail into an L1
`specifics` file (summarized + linked down). Let *arc42* decide placement over the
table.

**8. Author the standard diagrams (additive).** Old projects have no C4 mermaid
diagrams, but the new structure requires them and they are load-bearing routers.
Author `project_diagram.mmd`, `service_diagram.mmd`, and each codebase's
`module_diagram.mmd` from the old `## Architecture` content + `infra.yml`; wire
mermaid `click` links to the docs/contracts for each box. The service diagram must
be consistent with `infra.yml`.

**9. Remaining docs.** Module docs → `plans/design/{codebase}/module/`
(near-intact); `conventions.md` → `doctrine_ext.md` (selective, per above);
`db_schema.md` → the owning codebase's L2 `specifics`. Apply `doc-refine`'s detail
and categorization passes throughout (over-detail → `specifics`/module doc;
concepts into their correct arc42 section).

**10. Reference-update — wave 2.** Repo-wide, now that design content has landed:
fix every reference into the split/moved design docs.

### Phase 3 — Verify, refine, finalize

**11. Structural verification.** `docex docs check` green (missing-file +
reachability + adr-fresh); repo-wide reference grep clean.

**12. `doc-refine` polish — DESIGN DOCS ONLY.** Run a `doc-refine` pass scoped to
`design_docs` depth (never `code_level` — this conversion never touches source).
Now that the structure exists, this catches residual over-detail, misplacement,
and cross-cutting concerns that the one-shot split missed. Re-run `docs check`
after.

**13. Reconcile and finalize.** The no-loss backstop: compare the final tree
against `_old_plans` and confirm no substantive content was lost that wasn't a
*deliberate* deletion. Then delete `_old_plans` and run `docex docs check` a final
time. Commit.

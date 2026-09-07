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
2. **References are repo-wide and two-wave — but the historical archive is frozen.**
   Files that merely move get their references fixed early; design docs that get
   split/merged get theirs fixed only after the refactor settles. Both waves sweep
   the *whole repo* (source comments, `infra.yml`, `CLAUDE.md`, …), not just
   `plans/` — `linkcheck` sees only doctrine-scoped links. **Exception: never rewrite
   references inside the historical record** — `plans/ops/{mods,adv}` and
   `CHANGELOG.md`. Those are point-in-time snapshots that deliberately keep the
   vocabulary and paths of their era; rewriting hundreds of them is large, wrong, and
   would falsify the record. Their links into the old design tree *will* dangle once
   `_old_plans` is deleted, and that is expected — they are outside `docs check`'s
   scope, so the gate stays green. The reference waves target **live surfaces only**:
   source under `core/`, `infra.yml`, `README`, top-level config, and the new design
   docs.
3. **De-historicize, don't blind-delete.** Historical prose ("mod 020 did X")
   often carries a still-true decision; strip the narrative framing but preserve
   the durable fact (present tense, or an ADR).
4. **Bracket with `docex`.** `docex docs scaffold` lays the skeleton up front;
   `docex docs check` (missing-file + reachability + adr-fresh + anchor-resolution)
   runs iteratively and as the final gate.
5. **Top-down.** Convert high-abstraction first (masterplan → L1) before the docs
   that depend on it.
6. **One old doc rarely maps to one new doc.** A legacy doc is *shredded* across many
   destinations — `conventions.md` alone lands in `doctrine_ext.md`, several
   `specifics/` files, `lexicon.md`, and ADRs; even a single section can split three
   ways. Classify at the **section** level, not the file level, and track where each
   section goes so its inbound references can be repointed (see the protocol below).
7. **A doc may be cited from source by anchor.** Some legacy docs (a testing/guard
   register especially) are referenced from shipped source code by *section anchor*.
   Those anchors are a frozen interface: relocate such a doc **whole**, preserve its
   headings and explicit `<a id>` anchors verbatim, and do not shard or reword its
   cited headings. This is why recon lists every doc's inbound code references *before*
   translation begins.

## The Per-File Translation Protocol

Every legacy design doc is converted by the same four-step protocol. Its first two
steps run in **Phase 1 recon** (they are pure discovery and produce the reference
target-lists the waves consume); its last two run when that doc is translated in
Phase 2.

- **(i) Read to translate.** Read the old file with the intent to transcribe it into
  the new structure — not to summarize it.
- **(ii) List every reference to it (Phase 1).** Grep the **whole repo** (source,
  `infra.yml`, other design docs, `README`, config — but *not* the frozen historical
  archive, per Principle 2) for links and prose citations *into this file*, including
  citations to its individual section **anchors**. This is the per-file target list.
- **(iii) Transcribe, recording where each section lands (Phase 2).** As you
  de-historicize and split the file, keep a section→destination map (which new file,
  which new heading/anchor each section became). Shredding across destinations
  (Principle 6) makes this map the only reliable record of where a reference should now
  point.
- **(iv) Update every reference (Phase 2).** Using the list from (ii) and the map from
  (iii), repoint each inbound reference to the new file **and** the new anchor. A
  heading that was reworded or de-emoji'd (see step 5) has a **new slug**, so a
  reference to its old slug dangles silently — (iii)'s map is what prevents that.

---

## Translation Reference

This is a **section-level** map, not a file-level one. Per Principle 6, expect a legacy
doc to shred across several destinations at once — the rows below say where a given
*kind of content* goes, and one old file will match many rows. Let *arc42* and the true
nature of each section decide; the table is a starting point.

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

### `conventions.md` (the old name for `doctrine_ext.md`)

The old `doctrine_ext.md` was called `conventions.md`, and in many projects it
became a general-purpose dumping ground. It is the canonical shredded file — read it
carefully and route each section to its true home. **Only** these go to
`doctrine_ext.md`:
- transfer-table extension notes,
- hexagonal naming-convention extensions, and
- bespoke hex patterns (project-specific driven/driving port shapes with their own
  abbreviation) and non-standard controller-mechanism suffixes.

Everything else is relocated per its true nature, and in practice this means several
destinations from one file:
- codebase-specific detail → that codebase's L2 `specifics/` (see the row below),
- a project-wide concept → an overview in `concepts_and_decisions.md` + detail in an L1
  `specifics/` file, linked down,
- vocabulary / naming notes → `lexicon.md`,
- load-bearing reasoning → an ADR,
- pure historical chronicle → deleted.

### Codebase-level (L2) docs that are not module docs

Docs that describe one codebase as a whole rather than a single module — an execution
model, an SDK doc, a shared-clients doc, a telemetry doc, and `db_schema.md` (in the
schema-owning codebase) — go to that codebase's L2 folder,
`plans/design/{codebase}/specifics/`. They are not module docs and not project-level.

### Bespoke top-level practice / register docs

A project may carry a durable, project-wide practice doc that is neither arc42, nor a
module doc, nor `conventions.md` — e.g. a testing/guard-discipline **register**. It has
no dedicated arc42 home, so: add a short overview as a Cross-Cutting Concept in
`concepts_and_decisions.md` and put the full register at an L1
`plans/design/specifics/{name}.md`, linked down from that concept (the link satisfies
reachability). If such a doc is cited from source by anchor, relocate it **whole** and
freeze its headings (Principle 7).

### Module Docs

Module docs go to `plans/design/{codebase}/module/{module}.md`. Their *structure*
usually transfers cleanly, but do not expect them to be **near-intact** in content: in
an old project they are typically thick with status narrative and ⚠️/⛔ self-corrections
that the de-historicize pass (step 5) must strip. Conform each to the module-doc shape
(Purpose / Domain / Driving Ports / Driven Ports / Adapters Included / Hard Boundaries).

---

## Conversion Procedure

### Phase 1 — Mechanical relocation (deterministic, safe)

**0. Inventory / recon.** Enumerate the old tree: `masterplan.md`,
`conventions.md`, `db_schema.md`, module docs, codebase-level docs, and any bespoke
folders (e.g. `notes/`). Read `infra.yml` for the codebase list (the new per-codebase
design dirs) and the codebase→module mapping. Then run the Per-File Translation
Protocol's discovery half:
- **(ii) Build a per-file inbound-reference list** for each old design doc — grep the
  whole repo (source, `infra.yml`, other design docs, `README`, config; **not** the
  frozen `plans/ops/**` or `CHANGELOG.md`) for links and prose citations into it,
  *including citations to its section anchors*. These lists are the target list for the
  reference waves.
- **Inventory project-owned doc tooling.** Grep source for the *old doc root as a scope
  constant* (e.g. a `DOC_ROOT = "plans/core"` in a project-owned link-checker or a docs
  test-axis), not just as links. A project may ship its own doc gate coupled to the old
  layout; note it now, because the conversion will break it and disposing of it is
  project follow-up beyond this procedure.

**1. Preserve the old tree.** `git mv plans _old_plans` — a sibling of the new
`plans/`, outside it so nothing (`docs check`, `linkmap`) scans it. Retained as
fallback and reference until the final reconciliation. (Note: after this there is no
`plans/` at all until step 2 scaffolds it.)

**2. Scaffold the new tree.** `docex docs scaffold` lays down `plans/design` (arc42
stubs, diagram stubs, `adrs/` + index stubs, per-codebase dirs) **and**
`plans/product/` and `plans/references/`. The only standard dir it does *not* create is
`plans/ops/{mods,adv}` — make those two by hand.

**3. Mechanical relocations (no content change).** Copy the purely-moved files
into place: old `references` → `references`; `modifications` → `ops/mods`;
`advances` → `ops/adv`; bespoke folders (e.g. `notes/`) carried over. **Non-markdown
assets** (images, SVGs, PDFs) do **not** belong loose under `plans/design` — route them
to `plans/references/` (or leave them in the codebase) and repoint any doc that embeds
them; a binary under `plans/design` cannot be a "reachable design doc."

**4. Reference-update — wave 1.** Repo-wide **live surfaces only** (not the frozen
`plans/ops/**` or `CHANGELOG.md`, per Principle 2), for the moved-file paths only
(`ops/mods`, `ops/adv`, `references`, bespoke). Watch for the residue a link
checker can't see: prose, ASCII trees, source-comment references.
→ GATE: `docex docs check` (structure present) + a repo-wide grep confirms no
  stale references to the moved paths remain in live surfaces.

### Phase 2 — Design-doc refactor (judgment; reuses `doc-refine` passes)

**5. De-historicize.** Across the old design docs, strip "mod N did X" narrative
framing — preserving any still-true decision it carries (present tense, or route
to an ADR in step 6). (`doc-refine` State pass, subtractive.) Two specifics:
- **Headings are in scope, and emojis are stripped.** A `## ⚠️ …` / `## ⛔ …` /
  `## ✅ …` heading is exactly the status chrome this pass removes; emojis do not belong
  in documentation at all. Strip emoji and status markers from **headings** as well as
  prose, consistently across every file.
- **Editing a heading moves its anchor.** De-emoji'ing or rewording a heading changes
  its slug, so every inbound reference to the old slug dangles. This is why the Per-File
  Protocol's step (iii) records the new heading for each moved section and step (iv)
  repoints its references. (Exception: a heading frozen because source cites it by anchor
  — Principle 7 — is left verbatim.)

**6. Reasoning → ADRs.** Extract load-bearing reasoning into ADRs, numbered from
`0001`. If a decision's *reasoning* is absent but the decision is load-bearing,
still record the ADR. End the pass with `docex docs adr`, which regenerates the ADR
indexes **with reference links to each ADR** — so ADRs are reachable through the index
(a standard root) and need no inbound link from a narrative doc. Linking an ADR from the
concept whose decision it records is good practice, not a reachability requirement.
(`doc-refine` State pass, subtractive/condensing.)

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

**9. Remaining docs.** Convert each remaining legacy doc via the Per-File Translation
Protocol: module docs → `plans/design/{codebase}/module/` (structure carries, content
de-historicized to the module-doc shape — *not* near-intact); `conventions.md` shredded
per the Translation Reference (`doctrine_ext.md` for genuine extensions, the rest to
`specifics`/`lexicon`/ADR); codebase-level docs → `{codebase}/specifics/`;
`db_schema.md` → the owning codebase's L2 `specifics`; a bespoke practice register →
`concepts_and_decisions.md` overview + L1 `specifics/`. Apply `doc-refine`'s detail and
categorization passes throughout (over-detail → `specifics`/module doc; concepts into
their correct arc42 section).

**10. Reference-update — wave 2.** Repo-wide **live surfaces only** (never the frozen
`plans/ops/**` or `CHANGELOG.md`), now that design content has landed: using each file's
section→destination map from step (iii), fix every reference into the split/moved design
docs — path **and** anchor.

### Phase 3 — Verify, refine, finalize

**11. Structural verification.** `docex docs check` green (missing-file +
reachability + adr-fresh + **anchor resolution** — every `#fragment` in a design-doc
link resolves to a real heading or explicit anchor); repo-wide reference grep clean over
live surfaces. The anchor check is what catches a reference to a heading that step 5
reworded or de-emoji'd, and cross-file anchor drift when files were converted
independently — a class reachability alone cannot see.

**12. `doc-refine` polish — DESIGN DOCS ONLY.** Run a `doc-refine` pass scoped to
`design_docs` depth (never `code_level` — this conversion never touches source).
Now that the structure exists, this catches residual over-detail, misplacement,
and cross-cutting concerns that the one-shot split missed. Re-run `docs check`
after.

**13. Reconcile and finalize.** The no-loss backstop: compare the final tree
against `_old_plans` and confirm no substantive content was lost that wasn't a
*deliberate* deletion. Then delete `_old_plans` and run `docex docs check` a final
time. Commit.

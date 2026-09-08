---
version: "3.0.0"
severity: major
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 3.0.0

## Summary

3.0.0 is the **archdoc overhaul**: it replaces the old masterplan-centric `plans/`
layout with the arc42-based **design-doc structure** (`plans/{product,design,ops,
references}`), ships the `docex docs` command family that scaffolds and polices it,
and adds the documentation skills (`doc-refine`, `doc-refine-orchestration`,
`writing-adrs`) that author within it.

The **machine** side is automatic (`git pull` + `setup.sh`). The **project** side is
a one-time **design-doc conversion**: your existing `plans/` (a masterplan, a
`conventions.md`, module docs, and so on) is transcribed into the new structure —
arc42 L1 docs, the three standard C4 diagrams, ADRs, and per-codebase design dirs —
bracketed by deterministic `docex docs` gates so structural validity is never a
matter of opinion.

Nothing in your **source, `infra.yml`, or infrastructure changes.** This is a
documentation restructure: no recompile, no redeploy, no CICL bump, no data
implications. `cicl_version` stays `"3"`.

> **⚠ This is a judgment-heavy, LLM-driven conversion, not a mechanical `sed`.** The
> arc42 split is lossy by nature (subtractive + reorganizing). Budget a real pass and
> keep the old tree as a fallback until a final reconciliation confirms nothing
> load-bearing was lost. Read the whole **Project upgrade** section before starting —
> especially the two frozen-interface traps (a heading cited from source by anchor;
> the historical archive) that a naive first pass breaks silently.

See [`practices/docs.md`](../doctrine/practices/docs.md) for the target structure
(the arc42 sections, the three standard diagrams, the reachability rule),
[`infrastructure/docex.md § docs`](../doctrine/infrastructure/docex.md#docs) for the
command family, and the [`CHANGELOG` 3.0.0 entry](../CHANGELOG.md) for the narrative.

## Machine sync

`git pull` + `setup.sh` handle everything machine-side: the resident stratum, the new
`docex docs` commands (via the rebuilt `docex` image), and the new/changed skills
(`doc-refine`, `doc-refine-orchestration`, `writing-adrs`), whose arrival depends on
the plugin-cache version bump this release carries. No manual machine-side step.

## Project upgrade

The conversion runs in three phases. Phase 1 is deterministic and safe; Phase 2 is the
judgment work; Phase 3 verifies and finalizes. Each phase closes on a `docex docs check`
gate, so structure is validated continuously rather than only at the end.

### Guiding constraints (read before you begin)

1. **Nothing load-bearing is lost.** The old tree is retained as `_old_plans` and a
   final **reconciliation** confirms nothing substantive vanished before it is deleted.
   Structural checks validate *shape*, not *completeness* — the reconciliation is the
   completeness backstop.
2. **The historical archive is frozen.** `plans/ops/{mods,adv}` and `CHANGELOG.md` are
   point-in-time snapshots: **never rewrite their references.** Their links into the old
   design tree *will* dangle once `_old_plans` is deleted, and that is expected — they
   are outside `docs check`'s scope, so the gate stays green.
3. **A doc may be cited from source by anchor.** Some legacy docs (a testing/guard
   register especially) are referenced from shipped source code by *section anchor*.
   Those anchors are a frozen interface: relocate such a doc **whole**, preserve its
   headings and explicit `<a id>` anchors verbatim, and do **not** shard or reword its
   cited headings. This is why recon (step 0) lists every doc's inbound *code* references
   before translation begins.
4. **One old doc rarely maps to one new doc.** A legacy doc is *shredded* across many
   destinations (`conventions.md` alone can land in `doctrine_ext.md`, several
   `specifics/` files, `lexicon.md`, and ADRs). Classify at the **section** level, and
   track where each section lands so its inbound references can be repointed.

### Phase 1 — Mechanical relocation (deterministic, safe)

1. **Recon.** Enumerate the old tree (`masterplan.md`, `conventions.md`,
   `db_schema.md`, module docs, codebase-level docs, bespoke folders). Read `infra.yml`
   for the codebase list and codebase→module mapping. For **each** old design doc, build
   an inbound-reference list — grep the **whole repo** (source, `infra.yml`, `README`,
   config, other design docs; **not** the frozen `plans/ops/**` or `CHANGELOG.md`) for
   links and prose citations into it, **including citations to its section anchors**.
   Also grep source for the *old doc root as a scope constant* (e.g. a project-owned
   link-checker or docs test-axis pinned to `plans/core`): a project may ship its own doc
   gate coupled to the old layout — note it now, because the conversion breaks it and
   disposing of it is project follow-up beyond this guide.
2. **Preserve the old tree.** `git mv plans _old_plans` — a sibling of the new `plans/`,
   outside it so nothing (`docs check`, `linkmap`) scans it. (After this there is no
   `plans/` until step 3 scaffolds it.)
3. **Scaffold the new tree.** `./bin/docex docs scaffold` lays down `plans/design` (arc42
   stubs, diagram stubs, `adrs/` + index stubs, per-codebase dirs) **and**
   `plans/product/` and `plans/references/`. The only standard dir it does *not* create is
   `plans/ops/{mods,adv}` — make those two by hand.
4. **Mechanical relocations (no content change).** Move the purely-relocated files:
   old `references` → `references`; `modifications` → `ops/mods`; `advances` → `ops/adv`;
   bespoke folders carried over. **Non-markdown assets (images, SVGs, PDFs) do NOT belong
   loose under `plans/design`** — route them to `plans/references/` (or leave them in the
   codebase) and repoint any doc that embeds them; a binary cannot be a reachable design
   doc (`docs check` now scopes reachability to `.md`/`.mmd`/`.txt`).
5. **Reference wave 1 — moved paths, live surfaces only.** Repo-wide (but **not** the
   frozen `plans/ops/**` or `CHANGELOG.md`), repoint references to the moved-file paths
   (`ops/mods`, `ops/adv`, `references`, bespoke). Watch for residue a link checker can't
   see: prose, ASCII trees, source-comment references.
   → **Gate:** `./bin/docex docs check` (structure present) + a repo-wide grep confirming
   no stale references to the moved paths remain in live surfaces.

### Phase 2 — Design-doc refactor (judgment; reuses `doc-refine` passes)

6. **De-historicize.** Strip "mod N did X" narrative framing across the old design docs,
   preserving any still-true decision it carries (present tense, or route to an ADR in
   step 7). **Headings are in scope** — a `## ⚠️ …` / `## ⛔ …` / `## ✅ …` heading is
   exactly the status chrome to remove; strip emoji and status markers from headings as
   well as prose. **Editing a heading moves its slug**, so every inbound reference to the
   old slug dangles silently — record each moved section's new heading and repoint its
   references (Constraint 4). The one exception: a heading frozen because source cites it
   by anchor (Constraint 3) is left verbatim.
7. **Reasoning → ADRs.** Extract load-bearing reasoning into ADRs, numbered from `0001`
   (record the ADR even where the decision is load-bearing but its reasoning is absent).
   End the pass with `./bin/docex docs adr`, which regenerates the ADR indexes **with a
   reference link to each ADR** — so an ADR is reachable through the index (a standard
   root) and needs no inbound link from a narrative doc. Linking an ADR from the concept
   whose decision it records is good practice, not a reachability requirement. See
   [`practices/writing-adrs`](../doctrine/practices/adrs.md) (the `writing-adrs` skill).
8. **Masterplan → L1 nucleus.** Split `masterplan.md` into `boundary_conditions.md` /
   `concepts_and_decisions.md` / `structures_and_views.md` / `lexicon.md`, shunting
   over-detail into an L1 `specifics/` file (summarized + linked down). Let *arc42*
   decide placement — see the section map in
   [`practices/docs.md § arc42`](../doctrine/practices/docs.md#arc42). `quality_scenarios.md`
   and `unknowns.md` are scaffolded fresh; seed them only if the old masterplan carried
   the corresponding content.
9. **Author the standard diagrams (additive).** Old projects have no C4 mermaid diagrams;
   the new structure requires three and they are load-bearing routers. Author
   `project_diagram.mmd`, `service_diagram.mmd`, and each codebase's `module_diagram.mmd`
   from the old architecture content + `infra.yml`, wiring mermaid `click` links to the
   docs/contracts for each box. **The service diagram must be consistent with `infra.yml`.**
   See [`practices/docs.md § Standard Diagrams`](../doctrine/practices/docs.md#standard-diagrams).
10. **Remaining docs.** Convert each remaining legacy doc by its true nature:
    - **module docs** → `plans/design/{codebase}/module/` — structure carries, but content
      is de-historicized to the module-doc shape (Purpose / Domain / Driving Ports /
      Driven Ports / Adapters Included / Hard Boundaries); do *not* expect them near-intact.
    - **`conventions.md`** (the old `doctrine_ext.md`) is shredded: **only** transfer-table
      extensions, hex naming-convention extensions, and bespoke hex patterns / non-standard
      controller suffixes go to `doctrine_ext.md`; everything else relocates per its nature
      (codebase detail → that codebase's `specifics/`; a project-wide concept → a
      `concepts_and_decisions.md` overview + L1 `specifics/`; vocabulary → `lexicon.md`;
      reasoning → an ADR; pure chronicle → deleted).
    - **codebase-level (L2) docs** that aren't module docs (execution model, SDK, shared,
      telemetry, `db_schema.md`) → `plans/design/{codebase}/specifics/`.
    - **a bespoke practice/register doc** → a Cross-Cutting Concept overview in
      `concepts_and_decisions.md` + the full register at an L1 `plans/design/specifics/`,
      linked down (the link satisfies reachability). Relocate whole if source-cited
      (Constraint 3).

    Use the `doc-refine` / `doc-refine-orchestration` skills for the detail and
    categorization passes throughout.
11. **Reference wave 2 — split/moved design docs, live surfaces only.** Now that design
    content has landed, and again **never** touching the frozen archive, repoint every
    reference into the split/moved design docs — **path and anchor** — using each file's
    section→destination map from step 6/10.

### Phase 3 — Verify, refine, finalize

12. **Structural verification.** `./bin/docex docs check` green — all four checks:
    missing-file, reachability, adr-fresh, and **anchor resolution** (every `#fragment`
    in a design-doc link resolves to a real heading or explicit `<a id>` anchor). The
    anchor check is what catches a reference to a heading step 6 reworded or de-emoji'd,
    and cross-file anchor drift when files were converted independently — a class
    reachability alone cannot see. Plus a repo-wide reference grep clean over live surfaces.
13. **`doc-refine` polish — DESIGN DOCS ONLY.** Run a `doc-refine` pass scoped to
    `design_docs` depth (never `code_level` — this conversion never touches source
    *logic*; source *doc-references* were handled by the reference waves). Re-run
    `docs check` after.
14. **Reconcile and finalize.** Compare the final tree against `_old_plans` and confirm no
    substantive content was lost that wasn't a *deliberate* deletion. Then delete
    `_old_plans` and run `./bin/docex docs check` a final time. Commit.

## Doctrine / behavior notes

- **`docex docs` is a new command family** — `scaffold`, `check`, `adr`, `linkmap`,
  `overhead`, `changed`, `cxt_groups`. `check` is a CI sub-gate (it runs inside
  `docex check`), so once you convert, a broken or unreachable design tree fails the
  pipeline. See [`infrastructure/docex.md § docs`](../doctrine/infrastructure/docex.md#docs).
- **`docs check` has four checks:** Missing Standard File, Reachability (scoped to
  documentation files — `.md`/`.mmd`/`.txt` — so loose assets no longer fail), ADR-index
  Freshness, and **Anchor Resolution**.
- **`docs adr` emits a reference-linked ADR index.** Each ADR row links to its file, so an
  ADR is reachable through the generated index alone — a superseded ADR need not link back
  into the live docs.
- **The design-doc structure is doctrine.** `plans/design` with the arc42 L1 set, the three
  standard diagrams, `adrs/`, and per-codebase `module/` + `specifics/` is now the
  prescribed shape, policed by `docex docs check` and scaffolded by `docex docs scaffold`.
- **New skills:** `doc-refine` and `doc-refine-orchestration` (refine docs *within* the new
  structure) and `writing-adrs` (author an ADR). They arrive via `setup.sh`.
- **Historical records keep the old vocabulary and old paths on purpose** — mod docs, prior
  upgrade guides, and past `CHANGELOG` entries were true when written and are not rewritten;
  their dangling links into `_old_plans` are expected, not a reachability failure.

## Verification

1. `./bin/docex docs check` is **green** — all four checks (missing-file, reachability,
   adr-fresh, anchor resolution) — on the converted tree.
2. `./bin/docex docs adr` run twice is a **no-op** the second time (indexes already
   current), and `adr_index.md` / `adr_active.md` link each ADR to its file.
3. The three standard diagrams exist and are reachable, and `service_diagram.mmd` matches
   `infra.yml` (same codebases, core services, and backing services).
4. A repo-wide grep for the old design paths (e.g. `plans/core`, the old masterplan
   filename) returns hits **only** in the frozen archive (`plans/ops/**`, `CHANGELOG.md`)
   and in `_old_plans` if you have not yet deleted it — never in live source, `infra.yml`,
   `README`, or the new design docs.
5. `_old_plans` is deleted only **after** the reconciliation (step 14) confirms no
   load-bearing content was lost.
6. If your project shipped its own doc gate coupled to the old layout (found in step 1),
   it has been re-scoped, re-baselined, or retired — the project's own test suite is green.

---

*Optional further reading.* The design records behind this release live in advances
[010 (archdoc overhaul)](../docex/plans/advances/010_archdoc_overhaul/) and
[011 (archdoc skills)](../docex/plans/advances/011_archdoc_skills/); the latter's
`doc_converter_guidelines.md` is the full per-file conversion protocol this section
distills. Nothing in this guide requires them.

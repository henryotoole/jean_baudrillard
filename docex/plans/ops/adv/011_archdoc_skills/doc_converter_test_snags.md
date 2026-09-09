# Doc-Converter Guidelines — Test Run Snag Log

Testing `docex/plans/advances/011_archdoc_skills/doc_converter_guidelines.md` (3.0.0 candidate)
against the **real Nasmyth repo** (`~/projects/nasmyth`, `origin/main` @ `b172889`, v0.14.0,
repinned docex 2.0.0 → 3.0.0 candidate). Branch: `test/3.0.0-doc-conversion` (throwaway, not pushed).

Each snag: **what the guideline says**, **what actually happened**, **proposed fix**.
Severity: 🔴 blocks / wrong · 🟡 friction / ambiguity · 🟢 minor / wording.

## Outcome

The conversion **succeeded end-to-end** — the guideline's spine is sound. Final state:
- `docex docs check` **green** on the full converted tree (46 design docs).
- Custom link+anchor validation: **0 broken** design-internal anchors (963 links, 874 anchors checked),
  0 broken file targets (excl. 2 pre-existing `notes/` danglers to a gitignored operator folder).
- Reconciliation: **13,108 → 12,483 md lines (95%)** — consistent with de-historicization, not loss;
  all 29 spot-checked load-bearing concepts survived.
- Module docs follow the canonical hex shape (Purpose/Domain/Driving/Driven/Adapters/Hard Boundaries).
- `_old_plans` **retained** (deletion deferred for operator review; reconciliation that gates it passed).

But the run surfaced **15 guideline gaps**, two of them 🔴 that a naive first-time follower would hit
hard. The headline finding: the guideline says "this conversion never touches source," which is **false
in a real project** — Nasmyth ships a `plans/core`-scoped doc-link gate woven into its test suite, and
the parallel-agent method produces cross-file anchor drift that **no docex gate catches**.

### Priority fixes (do these first)
1. **B / M (🔴):** a real project has source-side doc *gates and citations* the conversion breaks;
   `docs check` validates reachability but **not** anchor resolution, so it can't be the only gate.
   The guideline needs (a) a recon step for project-owned doc tooling, (b) an anchor-resolution check
   as a Phase-3 gate, (c) softening of "never touches source."
2. **F / G / K (🔴/🟡):** the translation model is file→file, but real docs **shred** across many
   destinations, and some are **cited from source by anchor** (frozen). Reframe as section-level, and
   add the "grep source for anchor citations before renaming a heading" rule.
3. **I, J, N, O (🟡):** ADR reachability needs an explicit inbound link; de-historicizing headings moves
   anchors and must be done consistently; loose assets fail `docs check`.

### The 15 snags (detail below)
A(scaffold scope) · **B(source doc-gates 🔴)** · C(historical-archive carve-out) · D(bespoke-doc buckets) ·
E(git mv note) · **F(one-doc→many-dests 🔴)** · **G(source-cited anchors frozen 🔴)** · H(practice-register bucket) ·
I(ADR reachability) · J(heading-slug drift) · K(shred lossy anchors) · L(fan-out token cost) ·
**M(cross-agent anchor drift 🔴)** · N(inconsistent heading de-historicization) · O(loose assets fail gate).

---

## Setup / environment

- **Repo shape (recon):** 2 codebases — `engine` (hex: broker, exchange, feedback, identity,
  indicator, market, session, strategy; + sdk, shared; core services mcp/web/worker_sim/worker_live/feed_*)
  and `frontend` (web). Backing: postgres (`schema_owned_by engine`), valkey.
- **Repo-wide refs into `plans/`: 348 lines**, ~90% in `CHANGELOG.md` (historical), rest are real
  source-comment refs in `.py`/`.ts`/`.svelte` + `README.md`, `infra.yml`, `.gitignore`,
  `infra/transfer_tables/valkey.yml`.
- docex 3.0.0 `docs` surface confirmed present: scaffold, check, adr, linkmap, overhead, changed, cxt_groups.
- Baseline `docs check` on old tree: no-ops ("no plans/design/ — skipped"). Good.

---

### L. 🟡 Operational: converting the largest docs is token-heavy; a parallel fan-out can hit account limits mid-write
- The 5-way fan-out over the module/specifics bulk hit an account **session rate-limit (HTTP 429)**.
  Net effect on disk: ~everything landed except the single largest doc (`market.md`, old 1354 lines),
  which was left partial (126 lines, back half missing). A failed agent's context is unrecoverable, but
  its *file writes* persist — so the recovery unit is "the file that didn't finish," not "the agent."
- **Lesson for the guideline:** the conversion is genuinely large (Nasmyth design corpus ≈ 13k lines).
  Note that (a) the biggest module doc (`market.md` here) may need its own dedicated pass, and (b)
  because agents write files, a crash is recoverable by re-scoping to the missing/partial files rather
  than re-running everything. Checkpoint-commit between phases (as done here) makes this clean.

## Snags

### A. 🟡 Step 2 mis-states what `docs scaffold` covers
- **Guideline says:** step 2 — "`docex docs scaffold` (lays down `plans/design` …), **and recreate
  `plans/product`, `plans/ops/{mods,adv}`, and `plans/references`**." The parenthetical implies
  scaffold does `plans/design` only.
- **Actually:** `docex docs scaffold` (3.0.0) also creates `plans/product/.gitkeep` and
  `plans/references/.gitkeep`. Only `plans/ops/{mods,adv}` is genuinely un-scaffolded. Following the
  guideline literally, you'd "recreate" two dirs scaffold already made.
- **Proposed fix:** reword step 2 → "scaffold lays down `plans/design`, `plans/product`, and
  `plans/references`; **manually create only `plans/ops/{mods,adv}`**, which scaffold does not."

### B. 🔴 The guideline claims "this conversion never touches source" — but a real project carries source-side doc gates the conversion BREAKS
- **Guideline says:** principle 2 sweeps "source comments"; but **step 12 asserts** "this conversion
  never touches source" (scoping `doc-refine` to `design_docs`, "never `code_level`").
- **Actually:** Nasmyth ships a **project-owned doc gate** tightly coupled to the old layout:
  - `core/engine/tests/docs/test_core_doc_links.py` — `DOC_ROOT = "plans/core"`, **~1150 hard-coded
    exact link counts**, a broken-link assertion, and heading-anchor checks. After the split, `plans/core`
    is gone AND every count is invalid. Worse: its docstring says a *missing* docs root **fails** (not
    skips) unless inside the service image — so a full checkout with `plans/core` renamed hard-fails.
  - `core/engine/tests/docs/doc_link_checker.py` + `test_doc_link_checker.py` — the "instrument."
  - `core/engine/tests/test_skip_axes.py` — a `docs` skip axis "resolved from a `plans/core/` path."
  - Plus **prose citations in shipped source**: `session/__init__.py`, `cont_identity_cli.py`,
    `test_web_paths_artifact.py`, `test_identity_sql_shape.py` all cite `plans/core/guards.md § …`.
- **Why it matters:** the conversion cannot leave these alone (CI goes red), but the guideline both
  (a) tells you not to touch source and (b) gives no procedure for a project-owned doc gate that must
  be **re-scoped, re-baselined, or retired**. In 3.0.0 this checker is largely **redundant** with
  `docex docs check` (reachability + link check), so "retire in favor of `docs check`" is likely the
  right call — but that's a source deletion the guideline forbids by its own words.
- **Proposed fix:** add a Phase-1 recon step "**inventory project-owned doc tooling/gates**" (grep
  source for the old doc root as a *scope constant*, not just as links), and a Phase-3 step to
  reconcile them: re-scope to `plans/design`, re-baseline counts, or **retire in favour of
  `docex docs check`**. Soften step 12's absolute "never touches source" to "never touches source
  *logic*; source *doc-references and doc-gates* are in scope for the reference waves + gate reconciliation."
- **Deeper findings on disposition (this is the headline snag):**
  1. **`docs check` does NOT subsume the bespoke checker.** `docex docs check` (3.0.0) validates
     *reachability* but NOT that a link *resolves* — it went green on my L1 tree while that tree
     linked to a dozen not-yet-created files, and it does no heading-anchor validation. The
     project's `test_core_doc_links.py` did exactly those (broken-link + invented-anchor detection,
     which its own history says caught real invented anchors repeatedly). So "retire in favour of
     `docs check`" **loses coverage**; "re-baseline it" means re-deriving ~1150 exact counts by hand.
     Neither is clean — the converter must be told to *choose consciously*.
  2. **The gate is woven into test META-infrastructure.** `test_skip_axes.py` registers a `docs`
     skip-axis naming `tests/docs/test_core_doc_links.py` and **asserts the exact axis set**
     (`{"database","contracts","docs","scid"}`); `test_web_contract_prose.py` cites the checker's
     root-detection. So retiring/re-scoping it is a multi-file source refactor, not a delete — which
     makes the guideline's "never touches source" not merely inaccurate but *dangerously* so.
  3. **Consequence for this run:** I completed the doc-*content* conversion and the reference waves;
     disposing of this project-owned gate is real follow-up the guideline neither warns about nor
     scopes. The project's pytest suite is red until it's done. (The doc-conversion's own gate,
     `docex docs check`, is green — the two gates are different things, which is part of the point.)

### C. 🟡 Reference waves vs. historical records — no carve-out, and the doctrine says keep history frozen
- **Guideline says:** principle 2 — "References are repo-wide … sweep the *whole repo* … not just
  `plans/`." No exception named.
- **Actually:** the moved/renamed paths are referenced from **87 historical op-docs** (`plans/ops/mods`,
  `plans/ops/adv`) and from `CHANGELOG.md`. But the doctrine treats historical records as immutable
  snapshots — the masterplan itself: *"Historical records — mod docs, advance plans, past changelog
  entries — keep the old vocabulary on purpose."* Rewriting hundreds of historical cross-refs (many
  into design docs whose sections were split/merged, so the old anchors no longer exist) is both huge
  churn and arguably wrong.
- **Decision taken (this run):** reference waves target **live surfaces only** — source, `infra.yml`,
  `README`, top-level config, and the new design docs. `plans/ops/{mods,adv}` and `CHANGELOG.md` are
  left frozen (their point-in-time links will dangle after `_old_plans` is deleted, which is what a
  historical snapshot is).
- **Proposed fix:** the guideline must **explicitly carve out the historical archive** from the
  reference waves and state that dangling point-in-time links in `ops/` + `CHANGELOG` are expected,
  not a reachability failure. (They're outside `docex docs check`'s scope anyway, so the gate stays green.)

### D. 🟡 Translation reference has no home for bespoke top-level docs or non-module codebase docs
- **Guideline covers:** masterplan, `conventions.md`→`doctrine_ext.md`, `db_schema.md`, and hex module docs.
- **Actually, Nasmyth has neither-fish-nor-fowl docs:**
  - `plans/core/guards.md` (927 lines) — a bespoke, heavily source-cited "project practices" doc that
    is **not** arc42, not a module doc, not `conventions.md`. Where? (candidates: `doctrine_ext.md`,
    an L1 `specifics/` file, or ADRs — real judgment.)
  - `plans/core/frontend/{architecture,charting,data_access,selection_state,styling}.md` — **L2
    codebase-level** docs that aren't hex-module docs and aren't the project masterplan.
  - `plans/core/engine/{execution_model,sdk,shared,telemetry}.md` — same: engine-level L2 docs, not
    per-hex-module.
- **Proposed fix:** add a translation row for **"codebase-level (L2) docs that aren't module docs"** →
  `plans/design/{codebase}/specifics/`, and a row for **"bespoke top-level practice docs"** with the
  decision procedure (doctrine-extension → `doctrine_ext.md`; project-wide concept detail → L1
  `specifics/`; pure rationale → ADR).

### E. 🟢 `git mv plans _old_plans` removes `plans/`; scaffold must recreate it
- Minor: after step 1 there is no `plans/` until step 2 scaffolds it. A naive `&&`-chained sanity
  check on `plans/` between the two steps aborts. Non-blocking; worth a one-line note in step 1.

### F. 🟡 One legacy doc maps to MANY destinations — the translation table's "one file → one dest" model breaks
- **Guideline says:** the translation reference is a per-file table (masterplan→L1, `conventions.md`→
  `doctrine_ext.md`, `db_schema.md`→L2, module docs→module/). Reads as "each old doc has a home."
- **Actually:** `conventions.md` (485 lines) splits across **five** destinations at once — its pattern
  catalog → `doctrine_ext.md`; storage rules (stream ownership, watermark, jsonb decimals) → engine
  L2 `specifics/`; project-wide concepts (authority/projection, three-state absence, bounded reads) →
  `concepts_and_decisions.md` overview + L1 `specifics/`; engine structural rules → engine
  `specifics/`; and its `## Naming Notes` → **`lexicon.md`**. Even a single *section* (`Src`) splits
  three ways (pattern→doctrine_ext, walk-detail→engine L2, AST-guard prose→guards). The masterplan is
  the same story (see snag below).
- **Proposed fix:** reframe the translation reference as a **section-level** classification pass, not a
  file-level move. Explicitly say a legacy doc is *shredded* across buckets, and that `conventions.md`'s
  non-doctrine-ext content is relocated per its true nature — including a `## Naming Notes`→`lexicon.md`
  path the current text omits.

### G. 🔴 A legacy doc can be CITED FROM SOURCE BY ANCHOR — relocation must preserve headings/anchors, and the guideline never says so
- **Guideline says:** nothing about anchor stability; reference waves fix *link paths*, and step 5
  (de-historicize) freely rewrites design-doc prose.
- **Actually:** `guards.md` is cited from shipped engine source by *section anchor* — e.g.
  `session/__init__.py`, `cont_identity_cli.py`, `test_web_paths_artifact.py`, `test_identity_sql_shape.py`
  all cite `guards.md § How a Tripwire Is Scoped` / `§ Proving A Test Measures Something` /
  `§ A liveness signal is only tested by the run where it is withheld`. So relocating guards.md is
  **constrained**: keep it a single file at a stable path (`specifics/guards.md`), preserve every `##`
  heading and explicit `<a id=…>` anchor verbatim, and do NOT shard it. A de-historicization pass that
  renames a cited heading silently breaks a source citation (and the *source* link-check, not
  `docs check`, is what would catch it).
- **Proposed fix:** add a rule — "before de-historicizing or splitting a doc, grep **source** for
  citations to its section anchors; anchors reachable from code are frozen. Prefer relocating such a
  doc whole." This is the single strongest constraint in the job and the guideline is silent on it.

### I. 🟡 Step 6 (extract ADRs + `docs adr`) is insufficient for the reachability gate
- **Guideline says:** step 6 — "Extract load-bearing reasoning into ADRs… End the pass with
  `docex docs adr` so the indexes exist (else the adr-fresh gate fails)."
- **Actually:** `docex docs adr` generates `adr_index.md`/`adr_active.md` as **plain-text tables
  with no markdown links to the ADR files**. So `docs check`'s reachability test fails on every ADR
  ("unreachable doc: …/adrs/0001_….md — not linked from any standard doc or diagram") unless each ADR
  is **also cited from a narrative standard doc** (normally `concepts_and_decisions.md`, from the
  concept whose decision it records). Extracting an ADR and running `docs adr` is not enough.
- **Proposed fix:** step 6 must add: "link each extracted ADR from the design doc that carries the
  decision it records (usually a `concepts_and_decisions.md` concept) — an ADR reachable only through
  the generated index is *unreachable* and fails `docs check`."
- **Also:** ADR files are flat `adrs/NNNN_snake_title.md` (not `adrs/NNNN_title/adr.md`); worth one
  explicit line in the guideline since the docs.md structure tree renders them ambiguously.

### J. 🟡 De-historicizing changes heading slugs (emoji + reworded headings), silently breaking inbound anchor links
- **Guideline says:** step 5 de-historicizes freely; wave 2 fixes reference *paths*. Nothing about
  the fact that editing a *heading* moves its auto-generated anchor.
- **Actually:** legacy headings are full of emoji and status words (`## ⚠️ meta/ is not only
  reference data…`, `#### ✅ Objective 2 has been tested…`). De-historicizing drops the emoji/status,
  which **changes the GitHub-style slug** (`#-meta-is-not-only-…` → `#meta-is-not-only-…`). Any
  *inbound* link from another file to the old slug now dangles — and since `docs check` doesn't
  validate anchors, it fails silently. This bit the fan-out: one agent's `doctrine_ext.md` links a
  heading another agent de-emoji'd.
- **Proposed fix:** add to step 5/wave-2: "de-historicizing a *heading* moves its anchor — when you
  reword or de-emoji a heading, grep the whole design tree (and source) for links to its old slug and
  update them. Prefer leaving headings that are cited elsewhere unchanged (see snag G)."

### K. 🟡 Shredding the masterplan produces unavoidable lossy anchor remaps
- Confirmed by the fan-out: links like `masterplan.md#engine`, `#non-market-source-data` point into a
  file that was split four ways; agents had to either guess the new anchor or link the destination
  file with **no fragment**. This is inherent to shredding a big doc and the guideline should
  acknowledge it: **when a masterplan section is split, leave a redirect/anchor map** (or accept
  fragment-less links) rather than pretending every inbound anchor survives. Pairs with snag F.

### M. 🔴 Parallel conversion agents produce cross-file ANCHOR drift that no docex gate catches
- **What happened:** splitting the module/specifics bulk across 5 agents, each fixed *its own outbound
  link paths* well (file-resolution: 963 links, 0 real breaks). But **29 cross-file anchor links dangled**
  because agent X cited `../specifics/sdk.md#the-published-authoring-surface` while agent Y (writing
  sdk.md) de-historicized that heading to `## `src/sdk/` — the published authoring surface` (slug
  `srcsdk--…`). Neither agent could see the other's final headings. Same for `db_schema.md#retention`
  → `#retention--three-zones-…`, `session.md#what-admission-refuses-outright-and-why-that-is-not-a-narrowing`
  → `#what-admission-refuses-outright`, etc.
- **Why it's severe:** `docex docs check` validates reachability, **not anchor resolution** — it was
  green while 29 anchors dangled. A plain file-existence link check also misses it (the files exist).
  Only a purpose-built *anchor* checker (heading→slug + explicit `<a id>`, compared against every
  `#fragment`) finds them. I had to build that checker (docex ships none).
- **Proposed fix:** (1) the guideline MUST include/reference an anchor-resolution check as a Phase-3
  gate (docex's reachability check is necessary but not sufficient); (2) when fanning out, either
  freeze headings first (convert L1 + all headings, THEN prose), or run a single anchor-reconciliation
  pass at the end (what I did). Note also that fixing anchors by substring-replacing slugs is
  hazardous — a short slug (`#retention`) is a prefix of the correct one and double-suffixes any
  already-correct link; use exact-fragment matching.

### N. 🟡 De-historicization was applied inconsistently to HEADINGS across agents
- Some agents (engine: indicator, identity, session) stripped `⚠️`/`⛔`/`✅` from headings; one
  (frontend) stripped them from prose but **left 21 in headings** (`## ⛔ The session slug is the id's
  TAIL…`). Since an emoji heading slugs to a *leading-hyphen* anchor, this directly caused a batch of
  the snag-M dangles and is a latent GitHub-render inconsistency.
- **Proposed fix:** the de-historicize instruction must explicitly name **headings** as in scope for
  status-marker removal (an emoji/`✅`/`⛔` in a heading is exactly the chrome to strip), and note the
  anchor consequence. (guards.md is the deliberate exception — its headings are frozen source-cited
  anchors; I left its 2 emoji headings alone.)

### O. 🟡 `docs check` polices EVERY file under `plans/design` for reachability — loose assets fail it
- The frontend legacy tree carried an `icons/` folder of SVG/PNG assets. Relocated naively into
  `frontend/specifics/icons/`, they **failed `docs check`** ("unreachable doc: …/icons/nasmyth.svg") —
  a binary asset can't be a reachable design doc. Fix: assets belong in `plans/references/` (outside the
  reachability gate) or in the codebase, not loose under `plans/design`. (They were duplicates of a real
  source asset `core/frontend/src/ui/assets/` anyway.)
- **Proposed fix:** the guideline's relocation step should say: **non-markdown assets don't go under
  `plans/design`** — route images/binaries to `plans/references/` (or link from source) and repoint.

### H. 🟡 `guards.md`-class docs (durable *practice registers*) have no bucket, and "near-intact module docs" won't be near-intact
- `guards.md` (927 lines) is a durable project-wide testing/guard-discipline register — not arc42, not
  a module doc, not `conventions.md`, not historical (`ops/`). Best home: a Cross-Cutting Concept
  paragraph in `concepts_and_decisions.md` + the whole register at L1 `specifics/guards.md`. The
  guideline's translation reference has no row for "bespoke durable practice doc."
- Separately: step 9 claims module docs "transfer over more or less intact." For Nasmyth they will
  **not** — every module doc is thick with ⚠️/⛔ staleness meta-commentary and status narrative that
  step 5's de-historicization must strip. "Near-intact" undersells the per-module-doc effort. (Will
  confirm when the module docs are converted.)

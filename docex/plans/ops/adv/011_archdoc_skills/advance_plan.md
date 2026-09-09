# Goals

Advance 011 is the second half of the archdoc campaign begun in
[advance 010](../010_archdoc_overhaul/advance_plan.md). Where 010 installed the
new documentation doctrine and the `docex docs {scaffold,check,adr}` tooling,
011 builds the **documentation-refinement tooling** — new `docex docs` verbs
(`linkmap`, `overhead`, `changed`, `cxt_groups`) that the
`doc-refine-orchestration` skill drives — **dogfoods** the new structure onto
`docex`'s own docs, brings the
smoke-test projects onto the new style, and validates the combined 010+011 state
with a fixed-foundation smoke walk. It does **not** cut the release — the `3.0.0`
cut (bundling 010+011) follows this advance (see *Deferred*).

Continues mod numbering from 010: next mod is **165**.

## Goal 1: `docex docs linkmap` — the doc/code link graph

### Success Criteria
1. `docex docs linkmap <depth>` (`design_docs` | `code_level`) emits the full link
   graph as deterministic JSON to **stdout**. `design_docs` covers `plans/design`;
   `code_level` also covers each codebase's `core/*/src` (git-tracked files only,
   so compiled artifacts never appear). Maps **all** in-scope files, including
   those unreachable from the roots.
2. **Nodes** are files, each carrying: `is_standard`, `type` (design / source /
   neither), `fpath` (project-relative), `level` (L1/L2/L3/C, nullable),
   `codebase`, `module`, and `tokens` (estimated context cost — folded into the
   linkmap, so there is no separate token-assessment step). `neither`-type nodes
   exist so edges pointing *outside* the tracked scope are still recorded.
3. **Edges** carry `link_type` (markdown / mermaid-click / structurally-emergent)
   and `direction`. Emergent edges follow doctrine structure — e.g. a hex source
   file `core/{cb}/src/hex/{module}/**` links to its module doc
   `plans/design/{cb}/module/{module}.md` when present.
4. Built on the existing `_links_in` primitive in `docs/check.py`; the current
   **reachability check is refactored to consume this linkmap** (one graph source
   of truth) and stays green. Output discipline like `docex describe --format
   llm`: pure JSON on stdout, diagnostics to stderr, deterministic sort,
   emit-once, nonzero exit on failure.
5. docex unit + integration tests; six-artifact alignment; `docex.md § docs`
   (output format documented) + `masterplan` updated.

## Goal 2: `docex` dogfoods the new doc structure

### Success Criteria

> **Operator ruling (2026-09-04, folded in during 011):** docex is *not* a
> doctrine-standard project — doctrine-based products cannot structurally produce
> a tool like docex, so its docs only need to *resemble* doctrine docs for
> ergonomics, not comply. Expected shape is **L1 arc42 docs + ADRs + an L1
> `specifics/`, and very little else** — **no** forced per-codebase/module L3
> layer (docex has no `infra.yml`, so `codebases()` is empty and none would
> scaffold). **docex itself is NOT obligated to pass `docex docs check`;** do not
> contort its structure to satisfy checks. This relaxes SC1's "per-module L3 docs"
> and SC3 below ("passes live" → best-effort resemblance). Dogfood, not compliance.

1. `docex`'s own project docs migrated `docex/plans/core` → `docex/plans/design`:
   arc42 L1 files, standard diagram(s) as far as they fit (docex has no
   `infra.yml`, so the service diagram is light/optional), an L1 `specifics/` for
   detail that doesn't fit an arc42 section, and any ADRs warranted — laid down via
   `docex docs scaffold`, then populated from the existing
   `masterplan.md`/`docex_process.md`/etc. content. Done **by hand** (docex is the
   executor, not a typical doctrine-authored project — the `doc-refine` skill is
   deliberately *not* exercised on it; see Non-Goals). No per-module L3 layer
   (per the ruling above).
2. `$jb/doctrine/**` is **NOT modified** by this migration. docex's docs may
   *link* to the doctrine freely, but the doctrine is not part of docex's design
   corpus.
3. The migrated corpus should be laid out so `docex docs check` is *satisfiable in
   principle* (standard L1 files present + reachable), but **passing the live check
   is best-effort, not a hard gate** (per the ruling above) — docex is not obliged
   to contort to pass. The hard requirement is the deferral-ledger sweep + green
   `linkcheck` (SC4), not `docex docs check`.
4. The 010 **deferral ledger** is swept to the new `plans/design` paths:
   `credentials.md` masterplan link, `cohere/SKILL.md:41`, `linkcheck.py` default
   roots + `test_linkcheck` `mirror_*` fixtures, `docex-edit`/`doctrine-update`
   references. `linkcheck` green after.

## Goal 3: the orchestration verbs (`overhead`, `changed`, `cxt_groups`) + skill

### Success Criteria
1. `docex docs overhead <file>` lists a subject file's structurally-inferred
   overhead per the overhead rules (all L1 root docs; any L1/L2/L3 doc the subject
   directly links to; for a source file with a module doc, what that module doc
   links to). Best-guess, not exhaustive.
2. `docex docs changed <git_ref>` lists the in-scope files changed since a git-ref
   (git-tracked, location-allowlisted; empty-tree ref = "all").
3. `docex docs cxt_groups <tokens_max> {<git_ref> | all}` returns context groups —
   each a set of subject files with highly-overlapping overhead — where a group's
   total in-context cost (subjects + shared overhead, from the linkmap's `tokens`)
   stays under `<tokens_max>` (an estimate, not exact). Groups fully cover the
   selection with no repeats; shared overhead listed high→low abstraction. The
   grouping is a heuristic (likely clusters on codebase/module lines).
4. All three verbs covered by docex unit + integration tests + six-artifact
   alignment + `docex.md`; and the `doc-refine-orchestration` skill routes to
   `cxt_groups` (SKILL.md already rewritten — finalize its subagent template, drop
   the now-duplicated overhead-rule prose in favor of a pointer to docex, and
   retire the superseded `executor/design.md`).
5. **Empirical calibration:** run `cxt_groups` against docex's migrated corpus
   (Goal 2 — pre-dogfood commit as the ref so migrated docs are subjects) with an
   artificially low `<tokens_max>` to force multiple groups; a subagent loads one
   group and **measures real context usage vs. the `tokens` estimate**, reporting
   accuracy and any tuning.

## Goal 4: smoke-test projects on the new doc style

### Success Criteria
1. Both smoke-test projects' docs updated **by hand** to the new structure (if not
   already), each passing `docex docs check`, so they are valid subjects for the
   walk.

---

# Tactical Plan

Driven by a fresh **sergeant**; mod cycles delegated to **corporal** subagents.
Seams: → DECISION (exceeds corporal authority) · → DEPENDS · → GATE.
**Pre-flight:** the tree must be clean on the advance branch before starting —
commit 010's outstanding manual-pass edits and the `docs`-gate reorder first.

1. **Mod 165: `docex docs linkmap`.** `corporal` (`docex-edit`).
   The rich link graph per Goal 1 — node metadata + `tokens`, typed/directed edges
   incl. structurally-emergent, both depths, all in-scope files (incl.
   unreachable), reachability refactored onto it. Tests; alignment; `docex.md`
   (output format) + `masterplan`.
   → DEPENDS: 010's `docs` group (exists).

2. **Mod 166: dogfood — migrate `docex/plans/core` → `plans/design`.** `corporal`.
   By-hand restructure into the arc42 corpus + diagrams + module docs + ADRs;
   `docex docs check` green live; sweep the 010 deferral ledger; `$jb/doctrine`
   untouched. Heavy — may split; corporal escalates if over budget.
   → DEPENDS: 010 (`scaffold`/`check`).

3. **Mod 167: `docex docs overhead` / `changed` / `cxt_groups` + skill finalize.** `corporal` (`docex-edit`).
   The three consumer verbs per Goal 3 (consuming Mod 165's linkmap); docex tests
   + alignment + `docex.md`. Finalize `doc-refine-orchestration`: fill the subagent
   template, replace its restated overhead rules with a pointer to docex, drop the
   stale `docmap` glossary line, and retire `executor/design.md` (superseded by
   `docex_doc_design.md` / `docex.md`).
   → DEPENDS: Mod 165 (linkmap).

4. **Mod 168: context-grouping calibration.** `corporal`.
   Run `docex docs cxt_groups` against docex's migrated corpus with a low
   `<tokens_max>`; a subagent loads a group and measures real vs. estimated
   context; report accuracy and any `linkmap` token-estimate / `cxt_groups` tuning
   that follows.
   → DEPENDS: Mod 166 (corpus) + Mod 167 (verbs).

5. **Mod 169: smoke-test projects → new doc style (by hand).** `corporal`.
   Update both test projects' docs; each passes `docex docs check`.
   → DEPENDS: 010. Independent of Mods 165–168 (can run any time before close-out).

## Close-out

6. **Fixed-foundation smoke walk** (NOT elastic) per
   [`PRE_CUT_CHECKLIST.md`](../../../test_projects/PRE_CUT_CHECKLIST.md) —
   validates the combined 010+011 state on a real project. Elastic omitted for
   the same reason as 010: all new `docex` code (docs tooling) is
   pre-fixed/elastic-fork. Recorded as a deliberate scoping, not an omission.

## Deferred — to the `3.0.0` cut (bundles advances 010 + 011)

These are campaign-level release gates and steps, run once after 011, per
[`RELEASING.md`](../../../../RELEASING.md):
- **Campaign `cohere` pass** — static audit + `verify_examples.py` + `linkcheck`,
  over the combined 010+011 doctrine/skill changes.
- **Skill evals** — `skill-iteration` trigger evals via `run_suite.py` + outcome
  evals for new/changed skills: new `writing-adrs`, `doc-refine`,
  `doc-refine-orchestration`; changed `inception` (masterplan→design brief),
  `project-cohere`, etc.
- **docex release gates** — full `pytest` (unit then `-m integration` separately,
  from `docex/`) + six-artifact alignment on the combined state.
- **`upgrades/upgrade_3.0.0.md`** (`kind: rebuild`) — its design-doc migration
  section is driven by [`doc_converter_guidelines.md`](./doc_converter_guidelines.md)
  (the pre-3.0.0 converter; this is the materialization of 010's deferred
  "doc-assessor").
- **Version cut `3.0.0`** per `RELEASING.md`: changelog roll; write `VERSION` +
  sync `pyproject.toml`, `__init__.py`, `.claude-plugin/plugin.json`; commit; tag
  `v3.0.0`; `docker build -t docex:3.0.0 ./docex`.

## Open Design Points (resolve at mod time)

From [`docex_doc_design.md`](./docex_doc_design.md), unresolved when the mods start:
- **`link_type` encoding** — string tags (`md`/`mmd`/`emerg`) vs. an int enum
  (design doc NOTE).
- **Other link forms** beyond markdown / mermaid-click / emergent (design doc
  TODO) — decide whether any more are needed.
- **`cxt_groups` algorithm** — a heuristic (set-cover + bin-packing); don't
  over-promise optimality. Expect codebase/module-line clusters.
- **Skill drift to clean up in Mod 167:** `doc-refine-orchestration` SKILL.md
  still restates overhead rules that now differ from the docex spec (SKILL says
  "L2 or L3"; design says "L1/L2/L3") and keeps a now-unused `docmap` glossary
  line — replace with a pointer to docex rather than a restatement.

## Non-Goals / Known Gaps

- **The `doc-refine` and `doc-refine-orchestration` skills are NOT exercised
  end-to-end this campaign.** Only the `cxt_groups` grouping/token math is
  calibrated (Mod 168). docex is not a doctrine-authored project, and the smoke-test-project
  doc updates (Mod 169) are by-hand — so the refinement skills ship *unvalidated
  against a real run*. This is a conscious deferral; the first real exercise will
  be a future refinement on an actual doctrine project. (Flagged for operator
  awareness — see the sergeant's briefing.)

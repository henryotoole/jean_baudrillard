# Goals

Advance 011 is the second half of the archdoc campaign begun in
[advance 010](../010_archdoc_overhaul/advance_plan.md). Where 010 installed the
new documentation doctrine and the `docex docs {scaffold,check,adr}` tooling,
011 builds the **documentation-refinement tooling** (the `docex docs linkmap`
command and the `docmapper` doc-grouping tooling (built into `docex`) behind the `doc-refine-orchestration`
skill), **dogfoods** the new structure onto `docex`'s own docs, brings the
smoke-test projects onto the new style, and validates the combined 010+011 state
with a fixed-foundation smoke walk. It does **not** cut the release — the `3.0.0`
cut (bundling 010+011) follows this advance (see *Deferred*).

Continues mod numbering from 010: next mod is **165**.

## Goal 1: `docex docs linkmap` ships

### Success Criteria
1. `./bin/docex docs linkmap` emits the **complete directed doc-link graph** of
   `plans/design` as JSON to **stdout** (every file → its outbound link targets;
   both outbound and inbound adjacency derivable from it — not just the
   reachable-from-roots set the `docs check` gate computes).
2. Output discipline matching `docex describe --format llm`: pure JSON on stdout,
   diagnostics to stderr, deterministic (`sort_keys`), built once and emitted in a
   single write, nonzero exit on any error (no partial stdout on failure).
3. Built on the existing link-graph code (`_links_in` in `docs/check.py`), not a
   reimplementation.
4. Unit + integration tests green (invocation discipline); six-artifact alignment
   green; `docex.md § docs` and `masterplan.md` updated.

## Goal 2: `docex` dogfoods the new doc structure

### Success Criteria
1. `docex`'s own project docs migrated `docex/plans/core` → `docex/plans/design`:
   arc42 L1 files, the standard diagrams, per-module L3 docs, and any ADRs
   warranted — laid down via `docex docs scaffold`, then populated from the
   existing `masterplan.md`/`docex_process.md`/etc. content. Done **by hand**
   (docex is the executor, not a typical doctrine-authored project — the
   `doc-refine` skill is deliberately *not* exercised on it; see Non-Goals).
2. `$jb/doctrine/**` is **NOT modified** by this migration. docex's docs may
   *link* to the doctrine freely, but the doctrine is not part of docex's design
   corpus.
3. The migrated corpus passes `docex docs check` (reachability + missing-file +
   adr-fresh) **live**.
4. The 010 **deferral ledger** is swept to the new `plans/design` paths:
   `credentials.md` masterplan link, `cohere/SKILL.md:41`, `linkcheck.py` default
   roots + `test_linkcheck` `mirror_*` fixtures, `docex-edit`/`doctrine-update`
   references. `linkcheck` green after.

## Goal 3: `docmapper` implemented and empirically calibrated

### Success Criteria
1. `docmapper` is implemented **as part of `docex`** — a docex command family
   (surface TBD: e.g. `docex docs map <op>` or `docex docmap <op>`, a naming call
   for the mod) providing `init`/`map_overhead`/`assess_tokens`/`group <target>`/
   `print order`/`print group` per [design.md](../../../../skills/doc-refine-orchestration/executor/design.md).
   `init` is deterministic off a git-ref, allowlists by location (`plans/design/**`
   + source roots), considers **git-tracked files only** (gitignored build
   artifacts never appear), treats the **empty-tree SHA** as "all files", and
   **excludes generated-but-committed files** (the two ADR indexes, by their
   do-not-edit marker). Living in docex beside `docs linkmap`, `map_overhead` may
   build the graph in-process; the standalone `docex docs linkmap` still ships.
2. Covered by **docex's unit + integration tests and six-artifact alignment**
   (centralizing in docex is what keeps it maintained and gated — this closes the
   "no owning gate" gap). The `doc-refine-orchestration` skill (SKILL.md + its
   `executor/design.md`) is rewired to **route to the `docex` commands** rather
   than a standalone `docmapper` binary.
3. **Empirical calibration:** run `docmapper` against docex's migrated design
   corpus (Goal 2 output — using the pre-dogfood commit as the git-ref so the
   migrated docs register as subject files), with an artificially low `<target>`
   to force multiple groups. Spawn a subagent to actually **load** one group's
   overhead + subject files and **measure real context usage** against
   `assess_tokens`'s estimate. Report the accuracy.

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
   New `docs` subcommand emitting the full directed link graph as deterministic
   JSON to stdout, per Goal 1. Unit + integration tests; alignment; `docex.md` +
   `masterplan` command surface.
   → DEPENDS: 010's `docs` group (exists).

2. **Mod 166: dogfood — migrate `docex/plans/core` → `plans/design`.** `corporal`.
   By-hand restructure into the arc42 corpus + diagrams + module docs + ADRs;
   `docex docs check` green live; sweep the 010 deferral ledger; `$jb/doctrine`
   untouched. Heavy — may split; corporal escalates if over budget.
   → DEPENDS: 010 (`scaffold`/`check`).

3. **Mod 167: `docmapper` in `docex` + skill rewire.** `corporal` (`docex-edit`).
   Implement docmapper as a docex command family per `design.md` and Goal 3:
   docex unit+integration tests + six-artifact alignment + `docex.md`/`masterplan`
   command surface. Rewire `doc-refine-orchestration` (SKILL.md + `executor/design.md`)
   to route to the new `docex` commands and settle the command-surface name.
   → DEPENDS: Mod 165 (shares the doc link graph); the finalized
     `doc-refine-orchestration` SKILL/design.

4. **Mod 168: `docmapper` empirical calibration.** `corporal`.
   Run `docmapper` against docex's migrated corpus with a low `<target>`; a
   subagent loads a group and measures real vs. estimated context; report
   accuracy and any `assess_tokens`/`group` tuning that follows.
   → DEPENDS: Mod 166 (corpus) + Mod 167 (docmapper).

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
- **`upgrades/upgrade_3.0.0.md`** (`kind: rebuild`).
- **Version cut `3.0.0`** per `RELEASING.md`: changelog roll; write `VERSION` +
  sync `pyproject.toml`, `__init__.py`, `.claude-plugin/plugin.json`; commit; tag
  `v3.0.0`; `docker build -t docex:3.0.0 ./docex`.

## Non-Goals / Known Gaps

- **The `doc-refine` and `doc-refine-orchestration` skills are NOT exercised
  end-to-end this campaign.** Only `docmapper`'s grouping/token math is calibrated
  (Mod 168). docex is not a doctrine-authored project, and the smoke-test-project
  doc updates (Mod 169) are by-hand — so the refinement skills ship *unvalidated
  against a real run*. This is a conscious deferral; the first real exercise will
  be a future refinement on an actual doctrine project. (Flagged for operator
  awareness — see the sergeant's briefing.)

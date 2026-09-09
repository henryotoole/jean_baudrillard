> **STATUS — STOPPED (hard pause after Mod 164).** This advance was halted
> deliberately after Mod 164 plus two sarge fallout commits. **Completed:** Mods
> 159–164 (Mod 162 = comparators *dropped* by operator ruling) and the
> `docs`-gate reorder. **NOT performed:** Mod 7 (docex dogfood) and the entire
> Close-out (steps 8–11 below — cohere, skill evals, docex release gates, fixed
> smoke walk). The deferred work was **carried forward into
> [advance 011 (`archdoc_skills`)](../011_archdoc_skills/advance_plan.md)**, which
> also builds the doc-refinement tooling; the `3.0.0` cut (steps 12–14) follows
> 011 and bundles both advances. See [`report.md`](./report.md) for the full
> resume state.

# Goals

This advance replaces the doctrine's documentation model wholesale: `docs.md` and
`comments.md` are rewritten, ADRs are added as a first-class reasoning-doc, the
design-doc corpus is reorganized onto *arc42* + C4-derived standard diagrams, and
the `plans/` layout changes (`core`→`design`, `modifications`→`ops/mods`,
`advances`→`ops/adv`). `docex` gains tooling to scaffold and police the new
structure. The whole repo then advances as one **MAJOR** version (`2.2.0` → `3.0.0`):
the change invalidates existing projects' doc layout and breaks established
operator workflows, so it ships a `kind: rebuild` upgrade guide.

## Goal 1: New documentation doctrine, coherent across all strata

The new documentation model fully replaces the old across doctrine prose, skills,
and agents, with no dangling references.

### Success Criteria
1. `doctrine/practices/docs.md` and `comments.md` replaced with the drafted versions.
2. ADR spec lives as **conditional**-stratum `adrs.md`, reached by a short
   "writing an ADR" thread skill; `docs.md` carries only a resident pointer to it.
3. Every reference across `doctrine/`, `skills/`, and `agents/` rewired to the new
   file names, `plans/` layout, and vocabulary — verified by `cohere`'s `linkcheck`
   (no dangling links) and a manual residue sweep for prose the linkcheck can't see.
4. `cohere` static audit green and `verify_examples.py` green (the doctrine's own
   worked examples still compile under any changed rule).
5. Resident context budget respected: `adrs.md` is conditional, not resident.

## Goal 2: `docex` supports the new doc structure

### Success Criteria
1. `docex docs scaffold` lays down the standard design-doc file set (the same set
   `inception` uses and the missing-file check enforces).
2. `docex check` blocks on **missing standard file** and on **doc reachability**
   (orphaned-but-load-bearing doc).
3. ADR index generation produces `adr_index.md` + `adr_active.md` from the ADR files.
4. The two diagram comparators (authored diagrams vs. `infra.yml` subgraph; the
   standard diagrams vs. each other) are **either** implemented **or** dropped with
   a written design-out finding explaining the infeasibility.
5. `docex.md` and `cicd.md` updated for the new commands; `docex` unit tests and
   integration tests green (run per the documented invocation discipline); the
   six-artifact alignment check green (incl. a `doctrine_excerpts` re-sync if any
   excerpted prose changed).

## Goal 3: The doctrine dogfoods its own new structure

### Success Criteria
1. `docex/plans/core/` migrated to the new `design/` structure — **or** a written
   exemption recorded in this advance's `report.md`.
2. The migrated docs pass the new `docex check` gates live (reachability +
   missing-file), serving as an end-to-end verification of Goal 2's tooling.

## Goal 4: Release readiness (assessor + guide + cut — operator/next-session)

### Success Criteria
1. A short **doc-assessor** skill exists (conformance-keeping + old→new conversion).
2. `upgrades/upgrade_3.0.0.md` authored, `kind: rebuild`, depending on the assessor.
3. Version cut to `3.0.0` per `RELEASING.md`.

---

# Tactical Plan

Driven by this session as **sergeant**; mod cycles delegated to **corporal**
subagents. Seams marked: → DECISION (exceeds corporal authority, ends the cycle for
a sarge ruling), → GATE (must be green before dependents start), → DEPENDS.

## Tonight (through fixed smoke)

1. **Mod: documentation doctrine swap + cross-corpus rewire.** `corporal`.
   Install new `docs.md` + `comments.md` into `doctrine/practices/`; place `adrs.md`
   as conditional-stratum and author the short "writing an ADR" thread skill; confirm
   `RESIDENT.md` / resident loader wiring (docs + comments stay resident, `adrs.md`
   does **not** join). Then rewire every reference and the `plans/` layout: `lexicon.md`
   ("Core Planning Docs"), `infrastructure.md` (repo-structure tree), `hex_overview.md`
   (module-docs section), `credentials.md`, `inception.md`, `modifications.md`
   (→ `plans/ops/mods`), `advance.md` (→ `plans/ops/adv`). Placement is mechanical, so
   the file moves and the rename sweep are one territory — but budget for residue the
   linkcheck can't catch (prose, ASCII trees). Lands first: it is the source of truth
   everything else coheres to.
   → DECISION: final home of `adrs.md` (`practices/` vs. a design subfolder) and the
     ADR skill's name/description — corporal proposes in design, sarge rules.
   → GATE: `linkcheck` green before skills/agents (Mod 5) rewire against it.

2. **Mod: `docex` scaffold + structure checks.** `corporal` (docex territory; `docex-edit`).
   `docex docs scaffold`; `docex check` missing-standard-file + reachability. Unit +
   integration tests. Precedes inception rewrite and the dogfood migration.
   → DEPENDS: Mod 1 (standard file set defined).

3. **Mod: `docex` ADR index generation.** `corporal`.
   Generate `adr_index.md` + `adr_active.md` from ADR files. Tests.
   → DEPENDS: Mod 1 (ADR format).

4. **Mod: `docex` diagram comparators (AT RISK).** `corporal`.
   → DESIGN-OUT FIRST: both comparators (vs. `infra.yml` subgraph; vs. each other).
   → DECISION: keep-or-drop ruling to sarge based on the design-out. If dropped, the
     written finding satisfies Goal 2 SC4.

5. **Mod: skills + agents rewire.** `corporal` (possibly split — `inception` is heavy).
   `inception` (scaffold the new doc set via `docex docs scaffold`), `cohere`,
   `project-cohere`, `docex-edit`, `doctrine-update`; agents `mod-developer`,
   `mod-implementor`, `doctrine-advance`.
   → DEPENDS: Mod 2 (scaffold exists), Mod 1 (structure + vocabulary settled).

6. **Mod: rewire `docex.md` + `cicd.md`.** `corporal`, small.
   Doctrine docs describing the new `docex` commands and where they sit in the pipeline.
   → DEPENDS: Mods 2–4.

7. **Mod: dogfood — migrate `docex/plans/core` → `design`.** `corporal`.
   Migrate by hand (assessor not built yet) and verify with the new `docex check`
   gates live. If migration proves out-of-budget, record the exemption (Goal 3 SC1).
   → DEPENDS: Mods 2–3.

## Close-out — NOT PERFORMED (carried to advance 011 / the 3.0.0 cut)

8. **`cohere` pass.** `corporal`, run once (token heuristic). Gate: static audit +
   `verify_examples.py` + `linkcheck` all green.
9. **Skill evals.** `skill-iteration` trigger evals via `run_suite.py` + outcome
   evals for materially-changed skills.
10. **`docex` release gates.** Six-artifact alignment; `pytest` unit then
    `-m integration` as separate invocations, from `docex/`.
11. **Fixed-foundation smoke walk** per `PRE_CUT_CHECKLIST.md`.
    **Intentional scoping:** elastic walk omitted — all new `docex` code is
    pre-fixed/elastic-fork, so an elastic walk exercises identical paths. Recorded
    here and in `report.md` as a deliberate decision, not an omission.

## Deferred (operator / next session)

12. **Doc-assessor skill** — operator-authored; prereq for the upgrade guide.
13. **`upgrades/upgrade_3.0.0.md`** (`kind: rebuild`) — depends on the assessor.
14. **Version cut `3.0.0`** per `RELEASING.md`: changelog roll; write `VERSION` and
    sync `pyproject.toml`, `__init__.py`, `.claude-plugin/plugin.json`; commit; tag
    `v3.0.0`; `docker build -t docex:3.0.0 ./docex`.
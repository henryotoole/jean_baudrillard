# Advance 010 — Archdoc Overhaul — IN PROGRESS (paused)

Paused after Mod 164, before the docex dogfood migration and close-out. Branch
`010_archdoc_overhaul`. Target version: **3.0.0** (MAJOR — breaking doc-layout
rule + broken operator workflows; ships a `kind: rebuild` upgrade guide).

## Completed (all committed on `010_archdoc_overhaul`)

| Mod | What | Notes |
| --- | ---- | ----- |
| 159 | Doc-doctrine swap + cross-corpus rewire | New `docs.md`/`comments.md` (resident); `adrs.md` (conditional) + `writing-adrs` skill; `plans/` layout rename across `doctrine/` prose. Residency verified via `gen_resident.sh` (13 resident, `adrs.md` excluded). |
| 160 | `docex docs scaffold` + `docs check` | Checks: missing-standard-file + reachability. Shared canonical standard-set (`standard_set.py`). Blocking sub-gate of `docex check`; skips when no `plans/design`. |
| 161 | `docex docs adr` + freshness gate | Regenerates `adr_index.md`/`adr_active.md`; `docs_adr_fresh` added to the blocking gate. |
| 162 | Diagram comparators | **DROPPED** by operator ruling (abandon). Design-out finding at `docex/plans/modifications/162_.../design_out.md` (commit `b951a98`). Infeasible without a diagram-node↔`infra.yml` identity convention in `docs.md`. |
| 163 | Skills + agents rewire | inception, project-cohere (+executors), mod-developer agent, skill-iteration/evaluation. docex-own-`plans/core` refs deliberately left (see ledger). |
| 164 | Document docex doc-tooling | `docex.md`, `cicd.md`, `docs.md § Docex`, `adrs.md § Docex`. `docex.md` not excerpt-mirrored. |

Plus two sarge fallout commits: `8e8a42e` (docs.md: service, not project, diagram mirrors `infra.yml` — rename residue) and `f36272b` (comparator-drop fallout: docs.md infra-match note + changelog).

Linkcheck green throughout. Each docex mod's pytest (unit + integration, run separately) and six-artifact alignment were green at mod time.

## Remaining

**Mod 7 — dogfood migration (`docex/plans/core` → `plans/design`): DECISION PENDING.**
Sarge recommendation: **defer to the assessor phase** — docex's own arch docs are the ideal first real target for tomorrow's doc-assessor skill, so hand-migrating now risks throwaway work. Goal 3 SC1 pre-authorizes the exemption. Close-out does NOT depend on this, and leaving `plans/core` in place keeps linkcheck/cohere green.

**Close-out (advance_plan.md steps 8–11), none started:**
1. `cohere` pass — static audit + `verify_examples.py` + `linkcheck` green.
2. Skill evals — `skill-iteration` trigger evals via `run_suite.py` (NOT `run_eval.py`) + outcome evals for changed skills. **Flag:** `inception` description changed "masterplan" → "design brief"; `mod-developer` agent desc "core planning docs" → "design docs" — re-verify these trigger.
3. docex release gates — six-artifact alignment + `pytest` unit then `-m integration` as SEPARATE invocations, from `docex/`. Re-run the full suite to confirm the combined state of Mods 160/161/164.
4. Fixed-foundation smoke walk (`PRE_CUT_CHECKLIST.md`). **Elastic walk intentionally omitted** — all new docex code is pre-fixed/elastic-fork, so elastic re-runs identical paths. Deliberate, not an omission.

**Deferred to operator / next session:** doc-assessor skill; `upgrades/upgrade_3.0.0.md` (`kind: rebuild`); version cut `3.0.0` per `RELEASING.md` (changelog roll; `VERSION` + `pyproject.toml` + `__init__.py` + `.claude-plugin/plugin.json`; commit; tag `v3.0.0`; `docker build -t docex:3.0.0 ./docex`).

## Deferral ledger — sweep WHEN `docex/plans/core` migrates (Mod 7 / assessor)

These references point at docex's still-existing `plans/core` layout; valid now, must move with it:
- `doctrine/infrastructure/credentials.md` — `masterplan.md#the-shim` link.
- `skills/cohere/SKILL.md:41` — walks `docex`'s `plans/core/` as a linkcheck root.
- `skills/cohere/executor/linkcheck.py` — default roots include `docex/plans/core`; `tests/.../test_linkcheck.py` `mirror_*` fixtures.
- `skills/docex-edit/SKILL.md`, `skills/doctrine-update/SKILL.md:60` — docex-own-plans references.
- `docex/plans/core/masterplan.md` — the whole tree moves; its content is current.

## Other carried notes
- `inception.md`/`inception` skill use "design brief" as the pre-inception seed (masterplan retired) — accepted by sarge.
- `agents/corporal/mod-developer.md:26` has stale `docex test [subset]` wording on a separate (test-tier) axis — out of this advance's scope.
- `lexicon.md` keeps "core planning docs" as a synonym of the new primary term "Design Docs".

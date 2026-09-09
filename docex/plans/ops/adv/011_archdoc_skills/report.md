# Advance 011 — Archdoc Skills — COMPLETE

The second half of the archdoc campaign begun in
[advance 010](../010_archdoc_overhaul/report.md). Where 010 installed the new
documentation doctrine and the `docex docs {scaffold,check,adr}` tooling, 011
built the documentation-refinement tooling (new `docex docs` verbs), dogfooded
the new structure onto `docex`'s own docs, brought both smoke-test projects onto
the new style, and validated the combined 010+011 state (the **docex 3.0.0
candidate**) with a full fixed-foundation smoke walk.

Branch `011_archdoc_skills`. Mods 165–169. **The 3.0.0 cut is NOT performed by
this advance** — it is deferred and bundles 010+011 (see *Deferred*).

## Goals — all met

| Goal | Outcome |
| ---- | ------- |
| **1. `docex docs linkmap`** | Delivered (mod 165). `linkmap <depth>` (`design_docs`\|`code_level`) emits the doc/code link graph as deterministic JSON to stdout: nodes carry `type`/`level`/`codebase`/`module`/`is_standard`/`tokens`; edges carry `link_type` (markdown/mermaid-click/emergent) + `direction`. The reachability check was refactored onto this one graph (orphan output byte-for-byte unchanged). |
| **2. `docex` dogfoods the new structure** | Delivered (mod 166). `docex/plans/core` → `docex/plans/design` by hand: arc42 L1 + 6 ADRs + L1 `specifics/`. Per operator ruling docex only *resembles* the corpus (no forced module L3 layer, no service diagram, no `project.yml`/`infra.yml`), so `linkcheck` — not `docex docs check` — is the gate. Deferral ledger swept; `$jb/doctrine` untouched but the one `credentials.md` link. |
| **3. Orchestration verbs + skill** | Delivered (mods 167, 168). `overhead`/`changed`/`cxt_groups` built on mod 165's linkmap; `doc-refine-orchestration` finalized (routes to `cxt_groups`, drifted overhead-rule prose replaced with a pointer, `executor/design.md` confirmed already retired). Calibration (mod 168) measured real token density and corrected the estimator (see Findings). |
| **4. Smoke-test projects on the new doc style** | Delivered (mod 169). Both `fixed` and `elastic` migrated by hand to the full arc42 structure (L1 + 4 ADRs each + all three standard diagrams incl. `service_diagram.mmd` + per-codebase `module/`+`specifics/`). `docex docs check` GREEN on **each** — the first real exercise of 010's docs tooling against compliant projects. |

## Mods (all committed on `011_archdoc_skills`)

| Mod | What | Notes |
| --- | ---- | ----- |
| 165 | `docex docs linkmap` + reachability refactor | Unit+integration green; string `link_type`/`direction`; `len/4` token heuristic (no new dep); `ls_files` on `GitClient` + integration test; depth-relative `type`. |
| 166 | docex dogfood migration | linkcheck green; reconciliation confirmed no load-bearing loss; 6 ADRs; `pyproject.toml readme` + docstring pointers swept. |
| 167 | `overhead`/`changed`/`cxt_groups` + skill finalize | overhead folds in the emergent edge; `changed` = ref-vs-working-tree, empty-tree=all; `cxt_groups` overlap-greedy bin-packing, oversize→singleton (exit 0); pure cores root-parameterized (mod-168 guard). |
| 168 | cxt_groups token-estimate calibration | Estimator was materially off — divisor `4 → 2.4`; see Findings. |
| 169 | test projects → 3.0.0 arc42 doc style | Dual-commit (nested repos + outer distribution copy); `docex docs check` green on both; `§ Shape` citations repointed to `docex/plans/design/specifics/test_projects.md`. |

Sarge housekeeping commits: plan-fold (operator Goal-2 ruling); mod-165 changelog backfill.

## Close-out — fixed smoke walk: PASSED

The **docex 3.0.0 candidate** (image `docex:3.0.0`, built from the combined
010+011 source) passed the **full fixed-foundation smoke walk** per
[`PRE_CUT_CHECKLIST.md`](../../../test_projects/PRE_CUT_CHECKLIST.md), Option A
(operator's choice over a scoped alternative):

- **Section A** — fixed repinned to docex 3.0.0; inner-repo resting state per A.2.1; all prereqs green.
- **Section B** — all 17 doctrine-conformance items pass (compile clean; probe census VIOLATIONS 0; 3 contracts; core parity; schedule literal; …).
- **Section C.1–C.9** — preinfra/projinfra; dev sanity (real Let's Encrypt cert, `/health` 200); `docex test` (20); `check` (13 gates incl. the 010 docs sub-gate against real `plans/design`, and contracts_exist=3), `merge`, `containerize` (one `api:0.0.23` repo); `release stage` + `stagetest` (orchestrator gate + 5 probes); `release prod` — **replica unroll** (worker-1/-2 + sidecars + shared alias, the only exercise of the fixed multi-service form), all probes healthy, pings 201/422 + processed, **clock fire→defer→drain** verified to the DB job row.
- **Teardown + Section E** — `teardown.sh` + `verify_clean.sh` both exit 0; standing DNS retained per the E exemption; inner repo restored.

Elastic walk (Section D) omitted deliberately (same rationale as 010: all new
docex code is docs-tooling, pre fixed/elastic-fork). C.10 rollback not walked
(matches the selected Option-A scope; `docex rollback` untouched by 010+011).

**No docex/doctrine/seed bug surfaced.** The fixed half of the pre-cut checklist
is satisfied.

## Findings

1. **Token-estimate materially off → corrected (mod 168).** The `len/4` heuristic
   assumed ~4 chars/token; measured density (paired reader/control, real
   transcript tokens) is ~2.4 for **both** prose (2.43) and Python source (2.34,
   ~4% apart), i.e. the estimate ran ~1.67× low. Fixed with a single divisor
   (`_CHARS_PER_TOKEN = 2.4`, no tokenizer dependency; prose/source agreement
   meant no code-vs-prose split). Verified: the fixed project regrouped 3→5 groups
   at the same `tokens_max`.
2. **`docex docs changed` in a subfolder (mod 168, non-blocking).** `diff_names`
   returns repo-root-relative paths that miss the project-relative allowlist when
   project root ≠ git root (only bites docex-as-subfolder; harmless for real
   projects where the two coincide). Recorded as a limitation; a possible small
   follow-up (`diff_names` cwd-normalization, matching `ls_files`).
3. **PRE_CUT_CHECKLIST C.1 prose drift (walk finding, non-blocking).** C.1 says
   `projinfra up development` brings up "four `-web` networks" and traefik "joins
   all four"; the compiler correctly emits **three external** web networks
   (dev/stage/prod), while `test-web` is env-owned (the `test` compose declares it
   non-external) and created per-run. Fix the C.1 prose at cut close-out.

## Deferred — to the `3.0.0` cut (bundles 010 + 011)

Per [`RELEASING.md`](../../../../RELEASING.md), run once after 011:
- **Campaign `cohere` pass** — static audit + `verify_examples.py` + `linkcheck`.
- **Skill evals** — `skill-iteration` trigger evals via `run_suite.py` + outcome
  evals for new/changed skills (`writing-adrs`, `doc-refine`,
  `doc-refine-orchestration`; changed `inception`, `project-cohere`).
- **docex release gates** — full `pytest` (unit then `-m integration` separately,
  from `docex/`) + six-artifact alignment on the combined state.
- **`upgrades/upgrade_3.0.0.md`** (`kind: rebuild`) — driven by
  [`doc_converter_guidelines.md`](./doc_converter_guidelines.md).
- **Version cut `3.0.0`** — changelog `[Unreleased]`→`[3.0.0]`; write `VERSION` +
  sync `pyproject.toml`/`__init__.py`/`plugin.json`; commit; tag `v3.0.0`;
  `docker build -t docex:3.0.0 ./docex` (candidate already built + validated).
- **Fix the C.1 checklist prose** (Finding 3).

## State notes for the cut / next session

- **Version identifiers are at `2.2.0`** on this branch (reverted post-walk): the
  cut does the atomic bump. The validated **`docex:3.0.0` candidate image**
  remains in the local docker cache.
- **Walk residue:** `docex/test_projects/fixed/project.yml` is repinned to
  `docex_version: 3.0.0` — committed in the fixed **inner** repo (`dfc9066`,
  `v0.0.23` at HEAD) and showing as uncommitted `M` in the outer repo
  (doubly-tracked). The cut reconciles both projects' pins to 3.0.0. `elastic`
  was not repinned (fixed-only walk).
- **Out-of-band operator residue** (untouched, excluded from every advance
  commit): `engineer/coherence.md` (deleted), `engineer/expanded_deployment_capabilities.md`,
  `engineer/nasmyth_doc_sample/`, `engineer/nasmyth_plans.tar.gz`, and a new
  untracked `docex/plans/advances/012_docex_view/`.

## Non-Goal reminder (operator awareness)

The `doc-refine` and `doc-refine-orchestration` skills ship **unvalidated
end-to-end** this campaign — only `cxt_groups`' grouping/token math was calibrated
(mod 168). docex is not a doctrine-authored project, and the smoke-project doc
updates (mod 169) were by-hand, so the refinement skills' first real exercise will
be a future refinement on an actual doctrine project. Conscious deferral.

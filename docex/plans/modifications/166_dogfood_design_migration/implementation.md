# Mod 166 — Implementation

Execution spec for the by-hand `docex/plans/core` → `docex/plans/design` migration.
Per sarge's ruling (single cycle, judgment kept under the corporal's hand): the
mechanical relocation, the masterplan arc42 split, ADR extraction, and the
reconciliation pass are all executed by the mod-developer directly — **not** delegated
to a fresh-context implementor, because anchor preservation and the lossy split are
too nuance-dense to hand off.

Rulings folded in: **omit** `service_diagram.mmd`, `doctrine_ext.md`,
`quality_scenarios.md`; **~6 ADRs** with a preservation bias (DooD + path-mirror merged
into one); **edit** the two docex docstring path-pointers; **frozen-record**
interpretation confirmed (fix LIVE refs; leave historical mod/advance/upgrade/released-
changelog records).

## Ordered steps

### Phase 0 — preserve + scaffold
1. `git mv docex/plans/core docex/plans/_old_core` (sibling of the new tree; nothing scans it).
2. `mkdir -p docex/plans/design/adrs docex/plans/design/specifics`.

### Phase 1 — near-intact `specifics/` relocation + light de-historicize
For each of `compiler.md`, `release_flow.md`, `docex_process.md`, `test_projects.md`:
`git mv docex/plans/_old_core/<f> docex/plans/design/specifics/<f>`, then:
- **Relative-link depth bump (+1).** `specifics/` is one level deeper than the old
  `core/`. Every link to the doctrine (`../../../doctrine/…` → `../../../../doctrine/…`)
  and any other `../`-rooted link must gain one `../`. Grep each moved file for `](../`
  and recompute. Within-`specifics` sibling links stay `./<f>.md`. Links that used to
  point at `masterplan.md` are remapped to the new L1 file / `specifics` file that now
  owns that content (see the masterplan split map in `overview.md`).
- **De-historicize (light).** Strip `(mod NNN)` / "since mod NNN" narrative framing,
  **preserving the durable fact** in present tense. Do NOT rewrite technical substance.
  Where a passage is purely a "history, because it explains how a defect hid" record,
  keep it if it still teaches a live caveat, else condense — logged in the reconciliation
  ledger.
- **Preserve these anchors verbatim** (cited from files I must not or need not touch):
  `docex_process.md § Running the automated tests`; `test_projects.md § Shape`,
  `§ Commit cadence`, `§ Why the test projects are their own git repos`.
- **`test_projects.md` basename is LOCKED** (inner test-project citations resolve it by
  basename; it must remain the sole `test_projects.md` in the repo).

### Phase 2 — masterplan arc42 split (judgment; authored directly)
Split `_old_core/masterplan.md` per the `overview.md` mapping table into the L1 nucleus
+ two specifics + the diagram. New files under `docex/plans/design/`:
- `boundary_conditions.md` — Intro & Goals (preamble + note-on-shape framing + `## Goals`
  → Requirements), Constraints (Implementation language), Context & Scope (Out of Scope),
  Quality Requirements (overview from Goals). Depth = same as old core (`../../../doctrine`).
- `concepts_and_decisions.md` — Cross-Cutting Concepts (Distribution, Shim summary,
  Version Pinning, Bundles-vs-not, Foundation-Aware, Credentials & ambient host state,
  DooD, Ephemeral worktrees, contract/shim-gates summary), Solution Strategy, Risk/
  Unknowns/Tech Debt (Maintenance & Long-Term Risk). Reasoning → ADRs (linked).
- `structures_and_views.md` — Building-Block View (Architecture + Repository Structure +
  Subcommand summary → link to `specifics/subcommand_surface.md`), Runtime View
  (Cross-command orchestration), Deployment View (Filesystem Surface, Foundation-aware
  table, and the **one-line note explaining why there is no `service_diagram.mmd`**).
- `lexicon.md` — project glossary; seed the load-bearing docex terms (shim, DooD,
  foundation, preinfra/projinfra/envinfra, durable job / vessel / reaper, TTE); link to
  the doctrine lexicon rather than restating it.
- `unknowns.md` — empty scaffold (masterplan carries no discrete unknowns).
- `specifics/the_shim.md` — the `### The Shim` detail (incl. host-resolved git creds).
  `credentials.md` repoints here.
- `specifics/subcommand_surface.md` — the Subcommand Surface table (**carry the Mod 165
  `docs …` row that now lists `linkmap`**), `preinfra` fail-vs-decline, durable-job
  substrate detail, and the contract/shim gates detail.
- `project_diagram.mmd` — light C4 system-context: docex (black box) ← operator; docex →
  host docker daemon, operator credentials, registries/AWS/SSH targets, and the project
  repo it operates on; mermaid `click` links to the arc42 docs.

### Phase 3 — ADRs (~6, preservation bias; files `adrs/000N_title.md`)
Format per `doctrine/practices/adrs.md` (frontmatter id/title/status/date/supersedes/
superseded-by/tags + Context/Decision/Consequences). `status: accepted`, `date: 2026-09-04`.
1. `0001_single_bundled_docex_image` — one versioned image bundling all doctrine tooling
   (coherence / lockstep; why not pip/per-tool installs).
2. `0002_patch_only_tags_digest_pinned_base` — determinism of image refs.
3. `0003_docker_outside_of_docker` — DooD over DinD **and** the host-path-mirror
   consequence (merged per ruling).
4. `0004_preinfra_fail_vs_decline` — the two-negative-outcome exit-code split.
5. `0005_durable_job_substrate` — `.docex/runs/` + single container vessel + reaper.
6. `0006_host_brokered_git_credentials` — per-op git credential passthrough (pairs with
   `credentials.md`; the `The Shim` mechanism).
Then hand-write `adr_index.md` (all ADRs) + `adr_active.md` (accepted, not superseded)
per the adrs.md table shapes, each carrying a "generated by `docex docs adr`"-style
marker line noting it was hand-built (docex tooling can't run against docex).

### Phase 4 — ledger sweep + LIVE grep-clean
Exact edits (repoint `plans/core` → the new home; fix anchors):
- `doctrine/infrastructure/credentials.md:40` — link `../../docex/plans/core/masterplan.md#the-shim`
  → `../../docex/plans/design/specifics/the_shim.md#the-shim` (preserve `## The Shim`
  heading in that file). **Only permitted `$jb/doctrine/**` edit.**
- `RELEASING.md:8,:73` — `./docex/plans/core/docex_process.md[#running-the-automated-tests]`
  → `./docex/plans/design/specifics/docex_process.md#running-the-automated-tests`.
- `docex/test_projects/PRE_CUT_CHECKLIST.md:7,38,44,58` — up-links `../plans/core/{test_projects,
  docex_process}.md#…` → `../plans/design/specifics/…`.
- `docex/test_projects/README.md:5` — `../plans/core/test_projects.md`
  → `../plans/design/specifics/test_projects.md`.
- `docex/CHANGELOG.md:11` — live pointer `[`plans/core/docex_process.md`](./plans/core/docex_process.md)`
  → `plans/design/specifics/docex_process.md`.
- `skills/cohere/executor/linkcheck.py` — `DEFAULT_ROOTS` entry + WHY-comment:
  `docex/plans/core` → `docex/plans/design`.
- `skills/cohere/executor/tests/test_linkcheck.py:209–210` — `mirror_*/plans/core/…`
  fixtures → `…/plans/design/…` (assertion is on basenames; re-run to confirm green).
- `skills/cohere/SKILL.md:41` — prose "`plans/core/`" root name → "`plans/design/`".
- `skills/docex-edit/SKILL.md` — `$jb/docex/plans/core` refs → `$jb/docex/plans/design`;
  update the "read all files in plans/core" guidance to name the arc42 entry docs.
- `skills/doctrine-update/SKILL.md:60` — `$jb/docex/plans/core/masterplan.md` → the new home.
- `docex/src/docex/__main__.py:8` — docstring `plans/core/masterplan.md` →
  `plans/design/specifics/subcommand_surface.md` (where the Subcommand Surface now lives).
- `docex/src/docex/naming.py:195` — docstring `plans/core/compiler.md`
  → `plans/design/specifics/compiler.md`.
- **Advance-011 live planning files:** repoint any actual markdown LINK that would break;
  leave descriptive prose that merely *names* the migration (`plans/core → plans/design`)
  as-is. (Verify none of the 011 files carry a breaking live link.)

**Leave untouched (frozen record):** `docex/plans/modifications/**`,
`docex/plans/advances/**` prose, `upgrades/upgrade_*.md`, released `CHANGELOG.md` sections,
and all `docex/test_projects/*/plans/core/**` inner project docs (Mod 169).

### Phase 5 — reconcile, gate, finalize
1. **Reconciliation pass** vs `_old_core`: section-by-section, confirm nothing load-bearing
   vanished that wasn't a deliberate de-historicization. Record every de-historicization /
   condensation / deliberate drop in a ledger for the completion report (sarge requirement 2).
2. `rm -rf docex/plans/_old_core`.
3. **Final gate:** `python3 skills/cohere/executor/linkcheck.py` → exit 0, GREEN.
4. **Grep-clean:** repo-wide grep for LIVE `plans/core` refs → only frozen-record hits remain.
5. `python3 -m pytest skills/cohere/executor/tests/test_linkcheck.py` → green (fixtures moved).
6. Root `CHANGELOG.md` `[Unreleased]`: add/confirm a line for docex's own doc migration.
   **No version bump** — the 3.0.0 cut is deferred post-advance.

## Verification (manual test WAIVED)
- Reconciliation shows no load-bearing loss.
- `linkcheck` exits 0 after `_old_core` deletion.
- `test_linkcheck.py` green.
- Repo-wide grep: no stale LIVE `plans/core` refs.

## Commits
- `mod 166 design done, impl. steps written` (this file + overview).
- `mod 166 complete; designed, implemented, and documented.` (final).

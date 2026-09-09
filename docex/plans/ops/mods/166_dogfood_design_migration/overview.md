# Mod 166 — Dogfood: migrate `docex/plans/core` → `docex/plans/design`

## Goal

Restructure `docex`'s own design docs from the pre-3.0.0 masterplan-centric layout
(`docex/plans/core/`, 5 files) into the 3.0.0 arc42 documentation shape
(`docex/plans/design/`), **by hand**, and sweep the advance-010 deferral ledger so
every reference into the old tree lands on the new one. This is the dogfood step of
advance 011 (Goal 2).

**This is a documentation migration, not a code change.** The only non-doc edits are
reference repointing in the ledger files (one doctrine link, two skill files, the
`linkcheck.py` gate config + its test fixtures, RELEASING.md, and two docstring
path-pointers in docex source).

## Operator ruling that governs this mod

docex is **not** a doctrine-standard project — a doctrine-based product cannot
structurally *produce* a tool like docex. Its docs only need to **resemble** doctrine
docs for ergonomics, not comply:

- Expected shape: **L1 arc42 docs + ADRs + an L1 `specifics/`, and very little else.**
  No forced per-codebase/module L3 layer.
- docex has **no `infra.yml` and no `project.yml`**, so the docex docs CLI
  (`docex docs scaffold`/`check`/`linkmap`) **cannot run against docex itself** (it
  fails at project discovery). We **hand-build** the tree; we do **not** add a
  `project.yml`/`infra.yml` to make tooling run.
- docex is **NOT obligated to pass `docex docs check`.** The real structural gate is
  **`linkcheck`** (`skills/cohere/executor/linkcheck.py`, a standalone tool that needs
  no project discovery).

## The real gate: `linkcheck`

`linkcheck` walks `DEFAULT_ROOTS` = `doctrine/`, `skills/`,
`docex/doctrine_excerpts/`, **`docex/plans/core/`**, `docex/test_projects/`, and the
three repo-root `.md` files. It checks broken links, bad heading anchors, dead `§`
citations, and duplicate doctrine filenames. Two consequences drive this mod:

1. **`docex/plans/core` is literally a root** → after the move, `linkcheck.py`'s
   `DEFAULT_ROOTS` must be repointed to `docex/plans/design`, or `main()` exits 2
   ("root not found").
2. **Any link/citation in a *scanned* file that targets `docex/plans/core/...` breaks
   when the target moves.** Frozen/unscanned files (mod docs, advance docs, upgrade
   guides, source `.py`) are *not* walked, so their stale refs do not fail the gate —
   but see the grep-clean interpretation below.

### What actually breaks the gate (must-fix for GREEN)

| Scanned file (root) | Ref | Fix |
| --- | --- | --- |
| `doctrine/infrastructure/credentials.md:40` | markdown link `../../docex/plans/core/masterplan.md#the-shim` | repoint to new home of "The Shim" content + matching anchor |
| `RELEASING.md:8, :73` | markdown links to `./docex/plans/core/docex_process.md[#running-the-automated-tests]` | repoint to `docex/plans/design/specifics/docex_process.md#…` |
| `docex/test_projects/PRE_CUT_CHECKLIST.md:7,38,44,58` | links up to `../plans/core/{test_projects,docex_process}.md#…` | repoint to `../plans/design/specifics/…` (this is docex's *outer* harness doc, not a test-project-internal doc) |
| `docex/test_projects/README.md:5` | link to `../plans/core/test_projects.md` | repoint to `../plans/design/specifics/test_projects.md` |
| `skills/cohere/executor/linkcheck.py` | `DEFAULT_ROOTS` + WHY-comment | `docex/plans/core` → `docex/plans/design` |

### Anchor/basename invariants that MUST be preserved (or the gate breaks via files I may not touch)

The inner test-project masterplans (`docex/test_projects/{fixed,elastic}/plans/core/masterplan.md`)
carry **live** prose citations `` `docex/plans/core/test_projects.md § Shape` ``. These
files are **out of scope** (Mod 169 / scope fence — I must not edit them). `linkcheck`
resolves that citation by **basename** across the whole repo, then checks the `§ Shape`
heading. Verified: `test_projects.md`, `compiler.md`, `release_flow.md`,
`docex_process.md` are each **unique** in the repo today. Therefore:

- **Keep the basename `test_projects.md`** for the migrated file (destination:
  `plans/design/specifics/test_projects.md`) and **preserve its `## Shape` heading** —
  otherwise those inner citations go `NO CITE FILE` (a hard failure) in files I cannot
  edit.
- Preserve the other cited headings so the repointed links resolve:
  `docex_process.md § Running the automated tests`; `test_projects.md § Commit cadence`
  and `§ Why the test projects are their own git repos`. Because these four docs move
  **near-intact** into `specifics/`, their anchors survive naturally.
- **Sequencing:** run the final green `linkcheck` **after** `_old_core` is deleted.
  While `_old_core` coexists with `design/`, the whole-repo basename index sees two
  copies of each doc → the inner citations become **ambiguous** (declined, non-failing,
  but noisy). Delete first, then gate.

## Target structure (hand-built)

```
docex/plans/design/
├── boundary_conditions.md      # arc42: Intro & Goals, Constraints, Context & Scope, Quality Reqs
├── concepts_and_decisions.md   # arc42: Cross-Cutting Concepts, Solution Strategy, Risk/Unknowns/Tech Debt
├── structures_and_views.md     # arc42: Building-Block View, Runtime View, Deployment View
├── lexicon.md                  # project glossary (seeded from load-bearing docex terms)
├── unknowns.md                 # empty scaffold (masterplan carries no discrete unknowns)
├── project_diagram.mmd         # light: docex black box + operator/host-docker/registries/AWS/the project it operates on
├── adr_index.md
├── adr_active.md
├── adrs/
│   └── 0001_…/ … (see ADR candidates below)
└── specifics/
    ├── compiler.md             # from core/compiler.md, near-intact (light de-historicize)
    ├── release_flow.md         # from core/release_flow.md, near-intact
    ├── docex_process.md        # from core/docex_process.md, near-intact; preserves "Running the automated tests"
    ├── test_projects.md        # from core/test_projects.md, near-intact; preserves "Shape" etc.; basename LOCKED
    ├── subcommand_surface.md   # masterplan's command table (incl. Mod 165 `docs`/linkmap row) + job substrate
    └── the_shim.md             # masterplan "The Shim" detail; credentials.md repoints here
```

**Deliberately omitted** (justified by the operator ruling / docex's non-standard nature;
flagged as design questions Q1–Q2):
- `service_diagram.mmd` — no `infra.yml`, no backing services; a service diagram would be
  a single box. Proposed: omit, with a one-line note in `structures_and_views.md`.
- per-codebase/`module/` L3 docs and `module_diagram.mmd` — docex is not hexagonal; the
  ruling forbids a forced L3 layer.
- `doctrine_ext.md`, `quality_scenarios.md` — docex declares no transfer-table/hex-naming
  extensions of its own and no discrete quality scenarios. Proposed: omit.

## Masterplan → arc42 mapping (the judgment split — review target)

`masterplan.md` is the one doc that is genuinely **split**. The other four core docs move
into `specifics/` near-intact (light de-historicization only). Mapping:

| Masterplan section | Destination | arc42 |
| --- | --- | --- |
| Preamble + "note on shape" (L1–19) | `boundary_conditions.md` § Intro and Goals (intro prose; the note becomes a short framing paragraph) | Intro & Goals |
| `## Goals` (L21) | `boundary_conditions.md` § Intro and Goals → **Requirements** | Requirements |
| `## Architecture` + ASCII diagram (L29) | `structures_and_views.md` § Building-Block + Deployment; diagram authored into `project_diagram.mmd` | Solution Strategy / BBV / Deployment |
| `### Distribution` (L57) | `concepts_and_decisions.md` (cross-cutting); patch-only-tags + digest-pin reasoning → **ADR** | Cross-Cutting + ADR |
| `### The Shim` (L63) | `specifics/the_shim.md` + summary in `concepts_and_decisions.md`; credentials.md repoints here | Cross-Cutting / specifics |
| `### Version Pinning` (L90) | `concepts_and_decisions.md` cross-cutting; one-version-lockstep reasoning → **ADR** | Cross-Cutting + ADR |
| `## Subcommand Surface` (L102) incl. `docs`/linkmap row (Mod 165) | `specifics/subcommand_surface.md` + summarized in BBV | BBV / specifics |
| `### preinfra distinguishes failing from declining` (L132) | `specifics/subcommand_surface.md`; fail-vs-decline exit semantics → **ADR** | specifics + ADR |
| `### Cross-command orchestration` (L159) | `structures_and_views.md` § Runtime View | Runtime |
| `### Durable jobs (job substrate)` (L171) | `specifics/subcommand_surface.md`; `.docex/runs/` design → **ADR** | specifics + ADR |
| `## What docex Bundles vs Doesn't` (L258) | `concepts_and_decisions.md` (orchestrates-vs-language-work principle) | Cross-Cutting |
| `## Filesystem Surface` (L276) | `structures_and_views.md` § Deployment/BBV | Deployment |
| `## Foundation-Aware Behavior` (L304) + liveness gate (L319) | `concepts_and_decisions.md` (foundation parity); gate detail → `specifics/release_flow.md` | Cross-Cutting / specifics |
| `## Credentials & Ambient Host State` (L363) | `concepts_and_decisions.md` cross-cutting | Cross-Cutting |
| `## Docker-outside-of-Docker` (L378) | `concepts_and_decisions.md`; DinD-vs-DooD choice → **ADR** | Cross-Cutting + ADR |
| `## Ephemeral Git Worktrees` (L391) + `### contract and shim gates` (L402) | `concepts_and_decisions.md` summary + `specifics/subcommand_surface.md` detail | Cross-Cutting / specifics |
| `## Repository Structure` (L494) | `structures_and_views.md` § Building-Block View (the `src/` tree) | BBV |
| `### Implementation language` (L545) | `boundary_conditions.md` § Constraints | Constraints |
| `## Maintenance & Long-Term Risk` (L549) incl. edge cases / upstream drift / compatibility matrix | `concepts_and_decisions.md` § Risk, Unknowns, and Tech Debt | Risk |
| `## Out of Scope` (L572) | `boundary_conditions.md` § Context and Scope | Scope |

### ADR candidates (numbered from 0001; extract load-bearing *reasoning*)

Proposed, in rough priority. Final count is design question Q3.
1. `0001` — Single versioned container image bundling all doctrine tooling (coherence /
   lockstep; why not a pip package or per-tool installs).
2. `0002` — Patch-only image tags + digest-pinned base image (determinism).
3. `0003` — Docker-outside-of-Docker over Docker-in-Docker (bind `docker.sock`).
4. `0004` — Project path mirrored at the same in-container path (DooD path agreement).
5. `0005` — `preinfra` fail-vs-decline exit-code distinction.
6. `0006` — Durable job substrate (`.docex/runs/`) design.
7. `0007` — Host-brokered per-operation git credentials (pairs with `credentials.md`; the
   mechanism `masterplan § The Shim` documents).

## Ledger sweep + repo-wide grep-clean

**Explicit ledger (from advance 010 `report.md`, HARD requirement #1):**
- `doctrine/infrastructure/credentials.md` — the `masterplan.md#the-shim` link → new home.
  *(This is the single permitted `$jb/doctrine/**` edit; the doctrine is otherwise untouched.)*
- `skills/cohere/SKILL.md:41` — prose naming `plans/core/` as a linkcheck root → `plans/design/`.
- `skills/cohere/executor/linkcheck.py` — `DEFAULT_ROOTS` + WHY-comment → `plans/design`.
- `skills/cohere/executor/tests/test_linkcheck.py:209–210` — `mirror_*/plans/core/…`
  fixtures → `plans/design` (cosmetic; the test asserts on basenames, path is scaffolding —
  will re-run to confirm still green).
- `skills/docex-edit/SKILL.md:10,12` and `skills/doctrine-update/SKILL.md:60` — the
  docex-own-docs pointers → `plans/design` (and the "read all files in plans/core" line →
  the new arc42 entry docs).

**Beyond the ledger — remaining LIVE refs found by repo-wide grep (also fixed):**
- `RELEASING.md:8,:73` (scanned; breaks the gate).
- `docex/test_projects/PRE_CUT_CHECKLIST.md` + `docex/test_projects/README.md` (scanned;
  outer harness docs, not test-project-internal — repoint the up-links).
- `docex/CHANGELOG.md:11` — a live doc-pointer `[`plans/core/docex_process.md`](…)` →
  repoint (docex/CHANGELOG.md is not a linkcheck root, but it's a live pointer).
- `docex/src/docex/__main__.py:8` (`plans/core/masterplan.md`) and
  `docex/src/docex/naming.py:195` (`plans/core/compiler.md`) — **docstring path-pointers
  only, no logic**. HARD requirement #1 explicitly lists "source comments" as sweep
  targets, so these are in-scope; flagged here for visibility (design question Q4).

**Interpretation of "grep the whole repo … and fix them" (design question Q5):** I read
this as **fix every LIVE reference**, and **leave frozen historical records untouched** —
i.e. `docex/plans/modifications/**`, `docex/plans/advances/**` (except this advance's own
active planning files if they point live), `upgrades/upgrade_*.md`, and RELEASED
`CHANGELOG.md` sections. This matches `linkcheck.py`'s own stated philosophy ("Frozen
records … stay out — their stale links are the record") and the scope fence (don't move
`plans/modifications`/`advances`). Rewriting ~140 historical mod/advance refs would
falsify the record and is not gate-relevant. **Confirm this reading.**

## Method & safety (no content lost)

1. `git mv docex/plans/core docex/plans/_old_core` (sibling of the new tree, outside
   `plans/design`, so nothing scans it).
2. Hand-build `docex/plans/design/` per the structure above — near-intact `specifics/`
   moves first, then the masterplan split, then diagrams + ADRs.
3. Repoint all live refs (ledger + grep-clean).
4. Update `linkcheck.py` roots; run `linkcheck` iteratively while `_old_core` still exists
   (expect ambiguous-but-passing).
5. **Reconciliation pass** against `_old_core`: confirm nothing load-bearing vanished that
   wasn't a *deliberate* de-historicization. De-historicize, don't blind-delete.
6. Delete `_old_core`; run `linkcheck` for the **final GREEN gate**; repo-wide grep confirms
   no stale LIVE `plans/core` refs remain.

## Scope fences respected

- Migrate **`plans/core` → `plans/design` only**. `plans/modifications` and
  `plans/advances` are **not** moved.
- `$jb/doctrine/**` untouched except the one `credentials.md` link.
- `docex/test_projects/*/plans/core/**` (inner project docs) untouched — Mod 169's territory.
- The uncommitted `engineer/` files (`coherence.md`, `expanded_deployment_capabilities.md`)
  left alone and out of all commits.

## Budget & split assessment

Context budget is **not** the binding constraint (1M-context model; the 5 source docs are
~217 KB ≈ 55 K tokens). The binding constraint is **judgment quality on the lossy
masterplan split** — which is exactly why this overview pauses for review. Recommendation:
**single cycle**, executed in two internal phases with linkcheck as the mid-point sanity
gate — Phase 1 = near-intact `specifics/` relocation + full ledger/grep sweep + `linkcheck`
green (this alone satisfies the HARD gate); Phase 2 = the masterplan arc42 split + ADRs +
diagram. If you'd rather split into two mod cycles for tighter review (166a mechanical +
gate; 166b arc42 refactor), that's design question Q6 — I don't think it's necessary but
it's cheap to do.

## Design questions

- **Q1.** Omit `service_diagram.mmd` (no `infra.yml`)? Proposed: yes, with a one-line note.
- **Q2.** Omit `doctrine_ext.md` and `quality_scenarios.md`? Proposed: yes.
- **Q3.** ADR aggressiveness — extract the full ~7 candidates above, or a leaner set (e.g.
  just the 3–4 most load-bearing: single-image, DooD, fail-vs-decline)? docex's docs have
  never carried ADRs, so any number is net-new.
- **Q4.** OK to edit the two docex **source docstring** path-pointers
  (`__main__.py`, `naming.py`) — comment-only, no logic — as HARD requirement #1's "source
  comments" sweep mandates? (Flagging because the escalation rule names "docex source".)
- **Q5.** Confirm the frozen-record interpretation of "grep the whole repo … and fix them"
  (fix live refs; leave historical mod/advance/upgrade/released-changelog records).
- **Q6.** Single cycle (proposed) vs. split 166a/166b?

Awaiting your review of the arc42 mapping before I write `implementation.md` and execute.

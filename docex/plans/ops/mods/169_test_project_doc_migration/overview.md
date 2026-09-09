# Mod 169 — Migrate the two smoke-test projects to the 3.0.0 arc42 doc structure

## Goal

Convert `docex/test_projects/fixed/` and `docex/test_projects/elastic/` from their
pre-3.0.0 masterplan-centric `plans/core/` layout into the **full** 3.0.0 doctrine
documentation structure (arc42 L1 + `lexicon.md`/`unknowns.md` + ADRs + the standard
diagrams **including `service_diagram.mmd`** + per-codebase `plans/design/api/{module,specifics}/`
+ `module_diagram.mmd`), so each project passes `docex docs check`. This is the
real-world validation of advance 010's docs tooling against two *compliant, full*
doctrine projects (docex itself, migrated in Mod 166, is deliberately non-standard).
It is the last mod of advance 011 before close-out.

**This is a documentation migration — no source, infra, or version-artifact change.**
The only non-doc edits are three reference repoints per project (a README link, a
source-comment path pointer, and the live `§ Shape` docex citations in the masterplan).

## Worked precedent

Mod 166 applied this same converter procedure to docex's own docs
(`docex/plans/design/`). Its `overview.md` is the mapping template. Two differences
this mod inherits vs. Mod 166:
- **Full structure, not stripped.** These projects have `project.yml` + `infra.yml` +
  hexagonal `core/api/src`, so they get the per-codebase L3 layer, `service_diagram.mmd`,
  and `module_diagram.mmd` that docex (non-standard, no infra.yml) omitted.
- **The CLI works.** `docex docs scaffold`/`check` run against these projects (they have
  `project.yml`); Mod 166 had to hand-build because docex has none.

---

## 1. Git structure — a correction to the stated premise (design question Q1)

The kickoff states the two projects are nested repos **not tracked by the outer
jean_baudrillard repo** ("tracks only `test_projects/{PRE_CUT_CHECKLIST,README}.md`").
**Recon contradicts this.** Ground truth:

- `fixed/` and `elastic/` **each have their own `.git`** (independent repos, own
  `project.yml`/`CHANGELOG.md`/history) — this part holds.
- **BUT the outer jean_baudrillard repo also tracks every file inside them** as ordinary
  blobs — `git ls-files` counts **141** files under `fixed/` and **133** under
  `elastic/`, and there are **no submodule gitlinks** (no `160000` mode entries). This is
  the classic "embedded repo" situation: the files live in *both* index sets.

**Consequence:** editing `fixed/plans/**` produces uncommitted changes in **two** repos
simultaneously — the nested `fixed` repo *and* the outer `jean_baudrillard` repo. The
proposed "commit only inside the nested repo, outer is oblivious" structure cannot leave
the outer repo clean; it would strand a large uncommitted diff on branch
`011_archdoc_skills`.

**Proposed commit structure (dual-commit — please confirm):**

1. **Inside each nested repo** (`git -C …/fixed`, `git -C …/elastic`): commit the doc
   migration exactly as a real project performing a 3.0.0 doc migration would — that
   project's own `CHANGELOG.md` updated, a commit message in that project's history style
   (e.g. `Migrate design docs to 3.0.0 arc42 structure`). This is the dogfood-realism
   layer the operator wants.
2. **In the outer jean_baudrillard repo** (branch `011_archdoc_skills`): the mod
   bookkeeping commits — this `overview.md` + `implementation.md` (`mod 169 design done,
   impl. steps written`) and the final `mod 169 complete…`. Because the outer repo tracks
   the inner files, the **same migrated file changes ride along in the outer commit**,
   keeping the outer repo consistent (all three repos currently agree byte-for-byte, and
   this preserves that). No separate handling is needed — staging the mod folder plus the
   migrated trees in one `mod 169 complete…` commit is sufficient.

If you'd rather the outer repo *not* carry the inner file churn (e.g. gitignore the inner
trees, or convert them to real submodules), that is a structural change beyond this mod's
scope and I'd want your ruling — flagged as Q1.

## 2. Scope, order, and budget (design question Q2)

**Both projects, fixed first.** Establish the arc42 mapping + green gates on `fixed`,
then replicate to `elastic` (near-identical codebase/modules; differs only in foundation
deltas — ECR/EFS/Service Connect and a two-ECR-repo count — plus one extra masterplan
section, `### Code duplication between fixed and elastic test projects`).

**Budget assessment.** Context budget is **not** the binding constraint (1M-context model;
the two source doc sets are ~680 lines each ≈ comparable to Mod 166's single-cycle load),
and *execution is delegated to fresh-context `mod-implementor` subagents*, not run in my
context. The binding constraint is judgment quality on the lossy masterplan split — which
is why the mapping is fully pre-decided here (§3–§6) so the implementor executes a settled
plan. **Recommendation: single mod cycle (169), executed as two implementor passes** —
pass A does `fixed` end-to-end (mapping established, both gates green, my drift review);
pass B does `elastic` reusing the proven mapping. This bounds each implementor's context
and gives a fixed-project checkpoint. **169b fallback:** only if pass A reveals the split
is heavier than projected do we spin `elastic` into a follow-up mod — I don't expect to
need it. Confirm single-cycle-two-passes (Q2).

---

## 3. Target structure (full doctrine shape, per project)

```
plans/
├── product/                         # empty (no product docs exist)
├── references/                      # empty (none exist)
├── ops/
│   ├── mods/                        # empty (these projects keep no mod docs)
│   └── adv/                         # empty
└── design/
    ├── boundary_conditions.md       # arc42: Intro & Goals, Constraints, Context & Scope, Quality Reqs
    ├── concepts_and_decisions.md    # arc42: Cross-Cutting Concepts, Solution Strategy, Risk/Unknowns/Tech Debt
    ├── structures_and_views.md      # arc42: Building-Block View, Runtime View (the Flows), Deployment View
    ├── lexicon.md                   # from masterplan "## Terms" + load-bearing words
    ├── unknowns.md                  # empty scaffold (no discrete unknowns in the source)
    ├── project_diagram.mmd          # docex-smoke-* black box ↔ operator / Route53 / registry / preinfra
    ├── service_diagram.mmd          # api.{web,worker,clock} + appdb/probe/events backings (from infra.yml)
    ├── adr_index.md
    ├── adr_active.md
    ├── adrs/
    │   └── 0001…/ …                 # see §6
    └── api/                         # per-codebase L2/L3 (codebase = api)
        ├── module_diagram.mmd       # pings/processor/jobs/retention + api.{web,worker,clock} reach-in
        ├── module/
        │   ├── pings.md             # ← plans/core/api/hex/pings.md (near-intact)
        │   ├── processor.md         # ← …/hex/processor.md
        │   ├── jobs.md              # ← …/hex/jobs.md
        │   └── retention.md         # ← …/hex/retention.md
        └── specifics/
            └── db_schema.md         # ← plans/core/api/db_schema.md (near-intact)
```

`docex docs scaffold` (run from each project root via the local source `.venv` — see §8)
lays the arc42 stubs, diagram stubs, ADR index/dir, and the per-codebase `api/` dir; the
`product`/`references`/`ops` dirs are recreated as needed. Then hand-populate.

**Not produced:** `doctrine_ext.md` (neither project declares a transfer-table or
hex-naming *extension of doctrine* — the project-local `sidecar`/`clickhouse` transfer
tables are doctrine's own feature, not an extension), `quality_scenarios.md` (no discrete
scenarios). Both are optional in the standard structure, so their absence passes
`docs check`.

## 4. `masterplan.md` → arc42 mapping (the judgment split)

`masterplan.md` is the one genuinely-split doc. `api/hex/*` and `db_schema.md` move
near-intact (§5). Mapping (identical for both projects; elastic content differs only where
noted):

| Masterplan section | Destination | arc42 |
| --- | --- | --- |
| `## Purpose` (preamble) | `boundary_conditions.md` § Intro and Goals (intro prose) | Intro & Goals |
| `## Objectives` (1–3) | `boundary_conditions.md` § Intro and Goals → **Requirements** | Requirements |
| `## Terms` | `lexicon.md` (seed) + load-bearing terms | Glossary |
| `### Foundation` | `structures_and_views.md` § Deployment View + `concepts_and_decisions.md` (foundation shape); structure the diagrams capture is deleted | Deployment / Cross-Cutting |
| `### Domain` (apex/DNS/TLS/ingress) | `structures_and_views.md` § Deployment View | Deployment |
| `### Backing Services` | `service_diagram.mmd` (authored) + `structures_and_views.md` § Building-Block View prose | BBV |
| `### Core Services` + tables | `service_diagram.mmd` + `structures_and_views.md` § BBV; the deep per-service prose (`api.web`/`api.worker`/`api.clock`) → codebase content routed to `api/` module docs + `api.md`-equivalent BBV summary | BBV |
| `#### Why there is only one codebase` | reasoning → **ADR 0001**; durable fact summarized in `concepts_and_decisions.md` | Cross-Cutting + ADR |
| `### Composition Roots and Entrypoints` | `structures_and_views.md` § BBV (root/entrypoint split) | BBV |
| `### Code duplication…` (**elastic only**) | `concepts_and_decisions.md` § Cross-Cutting Concepts | Cross-Cutting |
| `## Flows` (8 flows) | `structures_and_views.md` § **Runtime View** (a flow *is* a runtime view — transfers cleanly) | Runtime |
| `## Hard Boundaries` | split: scope-shaped → `boundary_conditions.md` § Context and Scope; principle-shaped (no cross-service health; no real broker; one-codebase) → `concepts_and_decisions.md` + the relevant ADRs | Scope / Cross-Cutting |

**De-historicize, don't blind-delete** (converter principle 3): "was two codebases until
CICL v2", "reaper was deleted when role:scheduler retired" carry still-true decisions →
present-tense fact or ADR, narrative framing stripped.

## 5. `api.md`, module docs, `db_schema.md`

- **`api/hex/{pings,processor,jobs,retention}.md`** → `plans/design/api/module/*.md`,
  near-intact (converter step 9). These carry no cross-refs to the masterplan (verified),
  so they move cleanly; only internal relative links need checking (§7).
- **`db_schema.md`** → `plans/design/api/specifics/db_schema.md` (converter §"db_schema.md").
  Its internal link `[hex/jobs.md](./hex/jobs.md#concurrency)` must repoint to
  `../module/jobs.md#concurrency`; its `clock.md § …` citation resolves by basename to
  doctrine, unchanged.
- **`api.md`** (the codebase-L2 architecture doc) has **no single destination** — it is
  a codebase-level architecture doc whose content the 3.0.0 structure distributes:
  - the core-service tables + `domain_default_service` routing → `service_diagram.mmd`
    and `structures_and_views.md` § BBV;
  - the hex-module list + cross-import note → `module_diagram.mmd`;
  - the composition-root / entrypoints / health / contracts prose → `structures_and_views.md`
    § BBV, with over-detail pushed into the module docs where it belongs;
  - the "why one codebase" reasoning → **ADR 0001** (shared with the masterplan's copy —
    de-duplicated).

  It is heavily redundant with the masterplan (both describe the same three core services);
  the reconciliation pass (§9) ensures the merge loses nothing and de-duplicates rather
  than double-writing.

## 6. Standard diagrams + ADRs (additive)

**Diagrams** (authored from `## Architecture` + `infra.yml`; converter step 8):
- `project_diagram.mmd` — `docex-smoke-{fixed,elastic}` as one black box, with the
  operator, Route53/`luxrnd.tech`, the container registry, and preinfra
  (`web_demux`/master-VPC) as externals.
- `service_diagram.mmd` — **authored** (these have `infra.yml`, unlike docex): the `api`
  codebase's three core services (`web`/`worker`/`clock`) and the three backings
  (`appdb`, `probe`, `events`), with `uses`/queue edges; must be consistent with
  `infra.yml`. `click` links wire each surface box to its contract and each core service
  to `api/module_diagram.mmd`.
- `api/module_diagram.mmd` — the four modules + the `api.{web,worker,clock}` reach-in,
  `click`-linked to each `module/*.md`.

**ADR candidates** (numbered from 0001; extract load-bearing *reasoning* — design
question Q3). These projects have never carried ADRs, so any set is net-new:
1. `0001` — **One codebase, three core services.** Why `web`/`worker` merged at CICL v2
   (one artifact, many invocations) and why retired `reaper` folded into `api` as the
   `clock` rather than becoming its own clock (a clock defers onto its own codebase's
   queue; only a schema owner may enqueue). The central shape decision; absorbs the
   masterplan's and `api.md`'s duplicate "why one codebase" prose.
2. `0002` — **Postgres tables as queues.** The doctrine ships no `queue` backing-service
   role, so `pings`/`jobs` are tables owned by the enqueueing codebase. The most visible
   loose end of the CICL-v2 advance; deliberate.
3. `0003` — **Liveness via container tick-file probe, not HTTP.** Health left HTTP;
   `web` keeps `GET /health` only because a load balancer has no other channel; loops
   expose a `/tmp/<svc>.tick` stat'd by `./health.sh`. The 30 s/≤10 s pair.
4. `0004` — **No cross-service health reporting.** The deleted `/health/api/worker`
   fan-out; backing probes live under `/diagnostics`, not `/health`. *(Could fold into
   0003 — Q3.)*

## 7. Reference sweep (repo-wide, per project)

Live references into `plans/core` (verified by grep; frozen CHANGELOG refs left as record):

| File | Ref | Fix |
| --- | --- | --- |
| `{fixed,elastic}/README.md:5` | markdown link `[plans/core/masterplan.md](./plans/core/masterplan.md)` | repoint to `./plans/design/boundary_conditions.md` (the new arc42 entry) |
| `{fixed,elastic}/core/api/tests/test_processor_smoke.py:6` | source comment `see plans/core/api/hex/processor.md.` | repoint to `plans/design/api/module/processor.md` |
| `fixed/plans/core/masterplan.md:93,128` / `elastic/…:98` | live prose citation `` `docex/plans/core/test_projects.md § Shape` `` | **repoint to `docex/plans/design/specifics/test_projects.md § Shape`** (Mod 166 moved that file; `## Shape` heading confirmed present). These lines land in the migrated arc42 docs. |
| `db_schema.md` internal | `[hex/jobs.md](./hex/jobs.md#concurrency)` | → `../module/jobs.md#concurrency` (§5) |

**Left frozen (stay green):** `{fixed,elastic}/CHANGELOG.md` refs to
`docex/plans/core/test_projects.md § Shape` — `linkcheck` resolves `§` citations by
**basename**, and `test_projects.md` still exists (uniquely) at its new home, so these
record-lines resolve without edit. `CHANGELOG` `plans/core/{web,worker}/ → plans/core/api/`
is prose in backticks (a brace-glob, not a link/citation) — not walked. Converter
principle 2: fix live refs, leave the historical record.

## 8. Running the `docs` gate (design note / Q5)

The projects pin `docex_version: 2.2.0`, whose image **predates the `docs` command**
(added in advance 010). So `./bin/docex docs check` would fail. The `docs` command
discovers the project by walking up from CWD to `project.yml`, so the gate is run from the
**current docex source**, CWD = project root:

```
cd docex/test_projects/fixed && /…/docex/.venv/bin/python -m docex docs {scaffold,check,adr}
```

(verified: it discovers `fixed/project.yml` and reports the pre-scaffold state correctly).
This mirrors gate #2's `.venv` invocation of `linkcheck.py` and **avoids repinning** the
projects (a code/infra/version change out of this mod's scope; repinning is the cut's job).
Confirm this invocation is acceptable, i.e. no repin in this mod (Q5).

## 9. Gates + verification (manual test waived)

1. **`docex docs check` GREEN** on each project (missing-file + reachability + adr-fresh),
   run from source per §8. End the ADR pass with `docex docs adr` so the indexes exist.
2. **`linkcheck` GREEN** from the jean_baudrillard root afterward
   (`docex/.venv/bin/python skills/cohere/executor/linkcheck.py`) — its `DEFAULT_ROOTS`
   include `docex/test_projects/`, so it scans the migrated trees. Run the **final** green
   pass **after** `_old` trees are deleted (while `plans/core` and `plans/design` coexist,
   the whole-repo basename index sees two copies → ambiguous-but-passing noise).
3. **Reconciliation** (converter step 13, the no-loss backstop): before deleting the old
   trees, diff the final `plans/design` against the preserved `plans/core` (moved to
   `plans/_old_core` per converter step 1) and confirm nothing load-bearing vanished that
   wasn't a *deliberate* de-historicization. Then delete `_old_core` and re-run both gates.

## 10. Version / CHANGELOG (design question Q4)

**No version bump proposed** — this is a doc-only restructure, not a release. Add an
`[Unreleased]` entry to each project's `CHANGELOG.md` (`### Changed` — design docs migrated
to the 3.0.0 arc42 structure), matching each project's keepachangelog style. The nested
commit (§1.1) carries it. Confirm no-bump (Q4).

## 11. Scope fences respected

- Migrate **`plans/core` → `plans/design`** in each test project only. No source, `infra.yml`,
  `project.yml`, migration, or `bin/` change. No repin/recompile.
- **`$jb/doctrine/**` untouched.** The `§ Shape` repoints are docex-doc citations
  (`docex/plans/design/specifics/test_projects.md`), not doctrine edits — permitted.
- The two uncommitted `engineer/` files in the outer repo are left untouched and out of
  all commits.
- `docex/plans/**` (docex's own docs, incl. the Mod 166 tree) untouched except this mod's
  own folder.

## Design questions

- **Q1 — Git structure.** The outer jean_baudrillard repo **tracks the inner project files**
  (141 fixed / 133 elastic), contradicting the "outer tracks only two .md files" premise.
  Proposed: dual-commit (nested repo for dogfood realism + the same churn riding the outer
  mod commit to keep the outer repo consistent). Confirm — or rule for gitignore/submodule
  conversion (a structural change I'd need your authority for).
- **Q2 — Split.** Single cycle 169, two implementor passes (fixed → elastic); 169b only as
  fallback if pass A over-runs. Confirm.
- **Q3 — ADR set.** The 4 proposed, or fold 0004 into 0003 (→ 3)? Any number is net-new.
- **Q4 — Version/CHANGELOG.** No version bump, `[Unreleased]` entry per project. Confirm.
- **Q5 — `docs` CLI invocation.** Run the gate from the local source `.venv` (CWD = project
  root), not `./bin/docex` (pinned 2.2.0 predates `docs`); no repin in this mod. Confirm.

Awaiting your review of the git structure (Q1 especially) and the arc42 mapping before I
write `implementation.md` and dispatch the implementor.

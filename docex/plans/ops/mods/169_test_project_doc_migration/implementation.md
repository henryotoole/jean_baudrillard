# Mod 169 — Implementation

Execution spec for migrating the two smoke-test projects from the pre-3.0.0
`plans/core/` layout to the **full** 3.0.0 doctrine documentation structure. Written to
be handed to a fresh-context `mod-implementor`. Read `overview.md` (this folder) first —
it carries the approved arc42 mapping, the ADR set, and the git rulings this file executes.

**Two passes, dispatched separately by the corporal:**
- **Part A — `fixed`** (`docex/test_projects/fixed/`). Do this first, end-to-end, both
  gates green. The corporal reviews before Part B.
- **Part B — `elastic`** (`docex/test_projects/elastic/`). Reuses Part A's mapping;
  only the foundation-shaped content differs (§ Part B deltas).

**This is a documentation migration only.** No source, `infra.yml`, `project.yml`,
migration, or `bin/` change. **No repin, no recompile, no version bump.** **Contracts are
unchanged** — no surface (`rest`/`rpc`/`events`) is added, removed, or reshaped, so the
three `infra/contracts/*.yml` files are left exactly as they are.

**Approved rulings folded in:** dual-commit (nested repo + outer repo, § Commits); full
structure incl. `service_diagram.mmd` + per-codebase `api/{module,specifics}` +
`module_diagram.mmd`; **4 separate ADRs** (do NOT fold 0004 into 0003); run the `docs`
gate from the local source `.venv` (NOT `./bin/docex`); leave the `engineer/` files alone.

---

## The `docs` CLI (used throughout — both passes)

The projects pin `docex_version: 2.2.0`, which predates the `docs` command, so **do not
use `./bin/docex`**. Run the current docex source, CWD = the project root:

```
cd docex/test_projects/<project>
/home/ubuntu/.claude/jean_baudrillard/docex/.venv/bin/python -m docex docs <verb>
```

Verbs used: `scaffold`, `check`, `adr`. It walks up from CWD to `project.yml`, so CWD
must be the project root.

---

## Migration recipe (applied identically to each project)

Let `$P` = the project root (`docex/test_projects/fixed` or `.../elastic`). All paths
below are relative to `$P` unless noted.

### Step 1 — preserve the old tree
`git mv plans/core plans/_old_core` (run inside `$P`'s nested repo). `_old_core` is a
sibling of the new `plans/`, outside `plans/design`, so nothing (`docs check`,
`linkcheck`) scans it. It is the reconciliation reference; deleted in Step 9.

### Step 2 — scaffold the new tree
```
cd $P && /…/docex/.venv/bin/python -m docex docs scaffold
```
This lays `plans/design/` (arc42 stubs, `lexicon.md`, `unknowns.md`, diagram stubs,
`adrs/` + `adr_index.md`/`adr_active.md`, and the per-codebase `api/` dir with
`module/`/`specifics/`/`module_diagram.mmd`). Then `mkdir -p plans/product plans/references
plans/ops/mods plans/ops/adv` (kept empty — no product/reference/ops docs exist).

Confirm the scaffold created `plans/design/api/` (codebase `api` from `infra.yml`). If it
did not, create `plans/design/api/{module,specifics}` and the `api/module_diagram.mmd`
stub by hand.

### Step 3 — move the near-intact docs (module docs + db_schema)
`git mv` each, then recompute relative links (see § Link recomputation):
- `plans/_old_core/api/hex/{pings,processor,jobs,retention}.md` →
  `plans/design/api/module/{pings,processor,jobs,retention}.md`
- `plans/_old_core/api/db_schema.md` → `plans/design/api/specifics/db_schema.md`

Apply a **light de-historicize** to each (converter principle 3): strip "was X until mod
N / until CICL v2" narrative framing, **preserving the durable fact** in present tense. Do
NOT rewrite technical substance. Log every such change for the reconciliation ledger.

### Step 4 — split `masterplan.md` → the arc42 L1 nucleus (judgment)
Split `plans/_old_core/masterplan.md` per the `overview.md` §4 mapping table into files
under `plans/design/`. Author each fully (do not leave stubs):

- **`boundary_conditions.md`**
  - `# Intro and Goals` — `## Purpose` preamble as the project introduction; then a
    `## Requirements` subsection from `## Objectives` (1–3), present tense.
  - `# Constraints` — the "hexagonally-architectured … Python" fact and the
    single-host/one-codebase constraints.
  - `# Context and Scope` — the scope-shaped `## Hard Boundaries` items (does NOT solve a
    real problem; no custom transfer tables beyond sidecar/clickhouse; no custom
    observability). Light prose; the project diagram carries the rest.
  - `# Quality Requirements` — a short overview only (the project's quality bar is
    "doctrine-faithful; ambiguities fix doctrine, not this project"). No
    `quality_scenarios.md` (none exist).
- **`concepts_and_decisions.md`**
  - `# Cross-Cutting Concepts` — the durable, project-wide concepts in prose: the
    project-local transfer-table feature (sidecar/clickhouse) and what it exercises; the
    foundation-parity idea; a one-paragraph summary of each ADR's decision **linking down
    to the ADR** (do not restate the reasoning — link it). Principle-shaped
    `## Hard Boundaries` items (no cross-service health; no real broker; one codebase)
    summarized here and linked to their ADRs.
  - `# Solution Strategy` — brief: one codebase / three core services / postgres-mediated
    queues / container-probe liveness, each linking to its ADR.
  - `# Risk, Unknowns, and Tech Debt` — the deliberate loose ends (queue rows accumulate;
    no real broker; the two-codebase shape the walk no longer covers) as tech-debt notes.
    `unknowns.md` stays an empty scaffold (no discrete unknowns).
- **`structures_and_views.md`**
  - `# Building-Block View` — prose supporting `service_diagram.mmd` and
    `api/module_diagram.mmd`: the `api` codebase, its three core services, composition
    root (`root.py`) vs. entrypoints split, and the four hex modules. **Link** to
    `service_diagram.mmd`, `./api/module_diagram.mmd`, and each `./api/module/*.md`. Push
    per-module detail down into the module docs; keep this a router.
  - `# Runtime View` — the `## Flows` section transfers here near-verbatim (8 named flows;
    a flow *is* a runtime view). Keep the flow numbering and names.
  - `# Deployment View` — `### Foundation`, `### Domain` (apex/DNS/TLS/ingress), and the
    core-service→infra mapping. Delete structure the diagrams now capture; keep the
    foundation/domain facts the diagrams don't.
- **`lexicon.md`** — seed from `## Terms` (Ping, Job, Codebase, Core service, Smoke test)
  plus any load-bearing word the split leaves undefined. Link to the doctrine lexicon
  rather than restating shared terms.

### Step 5 — absorb `api.md` (no single destination)
`plans/_old_core/api/api.md` is a codebase-level architecture doc; the 3.0.0 structure
distributes it. It is heavily redundant with the masterplan — **de-duplicate, do not
double-write**:
- core-service tables + `domain_default_service` routing → `service_diagram.mmd` +
  `structures_and_views.md` § BBV;
- hex-module list + the single permitted cross-import (`jobs` runner ← `retention`
  driving port) → `api/module_diagram.mmd` + § BBV;
- composition-root / entrypoints / health / contracts prose → § BBV, with over-detail
  pushed into the relevant `api/module/*.md`;
- "why one codebase and not two" reasoning → **ADR 0001** (merge with the masterplan's
  copy of the same argument).

Then delete `api.md` from `_old_core` is implicit (the whole `_old_core` tree is deleted
in Step 9 after reconciliation).

### Step 6 — author the standard diagrams
Author from `_old_core`'s `## Architecture` + `$P/infra.yml`. Use `<pre class="mermaid">`
-free plain `.mmd`. Arrows point in the direction of calling/usage, labeled with the
action. Wire `click` links (mermaid `click NodeId "relative/path.md"`).

- **`plans/design/project_diagram.mmd`** — `docex-smoke-<foundation>` as one black box;
  externals: the operator, Route53/`luxrnd.tech`, the container registry, and preinfra
  (`web_demux`/master network). `click` the project box to `boundary_conditions.md`.
- **`plans/design/service_diagram.mmd`** — the `api` codebase's three core services
  (`web`/`worker`/`clock`) and the three backings (`appdb`, `probe`, `events`), edges:
  `api.web → api.worker` (drain, `rpc`), `api.{web,clock} → jobs`/`pings` tables via
  `appdb`, `api.web → probe`/`events` (diagnostics). **Must match `infra.yml`.** `click`
  each core service to `./api/module_diagram.mmd`; `click` each surface to its contract
  (`../../infra/contracts/api.web.rest.openapi.yml`, `.../api.worker.rpc.asyncapi.yml`,
  `.../api.worker.events.asyncapi.yml`).
- **`plans/design/api/module_diagram.mmd`** — the four modules + the `api.{web,worker,clock}`
  reach-in; `click` each module to `./module/<m>.md`.

### Step 7 — ADRs (4 separate; `plans/design/adrs/000N_title.md`)
Format per `doctrine/practices/adrs.md` (frontmatter `id`/`title`/`status`/`date`/
`supersedes`/`superseded_by`/`tags`, then Context / Decision / Consequences).
`status: accepted`, `date: 2026-09-04`. Extract the load-bearing *reasoning* (present in
the masterplan/`api.md` prose) — do not merely restate the decision:
1. `0001_one_codebase_three_core_services` — why `web`/`worker` merged at CICL v2 (one
   artifact, many invocations) and why retired `reaper` folded into `api` as the `clock`
   (a clock defers onto its own codebase's queue; only a schema owner may enqueue;
   `reaper` owned no schema/worker/queue). Absorbs the duplicate "why one codebase" prose
   from both masterplan and `api.md`.
2. `0002_postgres_tables_as_queues` — no `queue` backing-service role exists, so
   `pings`/`jobs` are tables owned by the enqueueing codebase. Deliberate loose end of
   CICL-v2; the AsyncAPI channels address tables, not topics.
3. `0003_tick_file_liveness` — liveness left HTTP; `web` keeps `GET /health` only because
   a load balancer has no other channel; loops expose `/tmp/<svc>.tick` stat'd by
   `./health.sh` from a separate process; the 30 s staleness / ≤10 s cadence pair.
4. `0004_no_cross_service_health_fanout` — the deleted `/health/api/worker` fan-out; each
   core service owns its own probe with no aggregation route; backing probes live under
   `/diagnostics`, not `/health`; the defer→drain round trip (flow 4) returns a work
   count, not a liveness verdict. **Distinct from 0003** (topology, not mechanism) — keep
   separate.

Then regenerate the indexes:
```
cd $P && /…/docex/.venv/bin/python -m docex docs adr
```
(the adr-fresh gate requires `adr_index.md`/`adr_active.md` to match `adrs/`).

### Step 8 — reference sweep (repo-wide within `$P`)
Fix LIVE references; leave frozen historical records. Exact edits:

| File | Current | Fix |
| --- | --- | --- |
| `README.md:5` | `[plans/core/masterplan.md](./plans/core/masterplan.md)` | `[plans/design/boundary_conditions.md](./plans/design/boundary_conditions.md)` |
| `core/api/tests/test_processor_smoke.py:6` | comment `see plans/core/api/hex/processor.md.` | `see plans/design/api/module/processor.md.` |
| masterplan `§ Shape` citations (now in the migrated arc42 docs) | `` `docex/plans/core/test_projects.md § Shape` `` | `` `docex/plans/design/specifics/test_projects.md § Shape` `` |

**Leave frozen (do NOT edit):** `CHANGELOG.md` citations to
`docex/plans/core/test_projects.md § Shape` and the `plans/core/{web,worker}/ →
plans/core/api/` prose line — `linkcheck` resolves `§` citations by **basename**, and
`test_projects.md` still exists uniquely at its Mod-166 home, so these record-lines stay
green untouched.

### § Link recomputation (apply during Steps 3–5)
The tree got one level deeper (`api/hex/*` → `api/module/*`; `api/db_schema.md` →
`api/specifics/db_schema.md`). Recompute:
- **Module→module sibling links stay `./<m>.md`** — pings/processor/jobs/retention all
  land together in `api/module/`, so `pings.md`'s `[processor](./processor.md)`,
  `processor.md`'s `[jobs.md](./jobs.md#concurrency)`, etc. are **unchanged**. Verify.
- **`db_schema.md` → `[hex/jobs.md](./hex/jobs.md#concurrency)`** becomes
  `[../module/jobs.md](../module/jobs.md#concurrency)` (specifics/ → module/).
- **Any `api.md`-sourced link that survives into an L1 doc** (e.g. a module link landing
  in `structures_and_views.md` at `plans/design/`) becomes `./api/module/<m>.md`; a
  db_schema link becomes `./api/specifics/db_schema.md`.
- **Doctrine `§` citations and `../doctrine/…` links carry over by basename** — unchanged
  by the move (they were never relative into `plans/`).

### Step 9 — reconcile, gate, finalize (per project)
1. **Reconciliation pass** vs `plans/_old_core`: section-by-section, confirm nothing
   load-bearing vanished that wasn't a deliberate de-historicization or de-duplication.
   **Record every de-historicization / condensation / deliberate drop in a ledger** and
   surface it in the completion report (corporal's no-loss control).
2. `git rm -r plans/_old_core` (inside `$P`).
3. **Gate 1:** `cd $P && /…/docex/.venv/bin/python -m docex docs check` → exit 0, GREEN
   (missing-file + reachability + adr-fresh).
4. **Grep-clean:** `grep -rn "plans/core" $P` → only frozen `CHANGELOG.md` record-lines
   remain.
5. **CHANGELOG:** add an `[Unreleased] → ### Changed` entry to `$P/CHANGELOG.md` in that
   project's keepachangelog style: design docs migrated to the 3.0.0 arc42 structure
   (`plans/core` → `plans/design`; arc42 L1 + ADRs + standard diagrams +
   `plans/design/api/{module,specifics}`). **No version bump.**

### Step 10 — repo-root linkcheck (after BOTH projects, or after each — see dispatch)
```
/home/ubuntu/.claude/jean_baudrillard/docex/.venv/bin/python skills/cohere/executor/linkcheck.py
```
(run from the jean_baudrillard root). Its `DEFAULT_ROOTS` include `docex/test_projects/`,
so it scans the migrated trees. Must exit 0, GREEN. Run the **final** green pass only
**after** every `_old_core` is deleted (coexisting `plans/core` + `plans/design` produce
ambiguous-but-passing basename noise).

---

## Part A — `fixed` (do first)
Apply the full recipe to `docex/test_projects/fixed`. Foundation-specific content for the
`# Deployment View` and diagrams (from the fixed masterplan):
- **Foundation:** `fixed`. All four envs run as docker containers on one host; the
  per-project Traefik distinguishes them by Host header. Inbound 443/80 → host HAProxy
  `web_demux` (preinfra) → per-project Traefik via the `docex-ingress` bridge.
- **Domain:** `docex-smoke-fixed.luxrnd.tech`; TLS via per-project Traefik + Let's Encrypt
  DNS-01 against the `luxrnd.tech` Route53 zone.
- **Backings on fixed:** `appdb` postgres 15 container; `probe` nginx sidecar container;
  `events` clickhouse container mounting a named docker volume.
- **Liveness (fixed):** docker only *reports*; `docex stagetest` reads
  `docker inspect .State.Health.Status` over SSH and gates on it.

## Part B — `elastic` (after Part A review)
Apply the same recipe to `docex/test_projects/elastic`, reusing Part A's arc42 structure,
ADR set, diagram shapes, and link recomputation **verbatim** (the codebase, modules,
core-service topology, contracts, and all module-doc/db_schema cross-links are identical).
Only the following content differs — route it into the same arc42 sections:

- **`# Deployment View` (elastic):** foundation `elastic`; `dev`/`test` local docker,
  `stage`/`prod` on AWS in the shared master VPC (`us-east-1`). Domain
  `docex-smoke-elastic.luxrnd.tech`; Route53 zone provisioned by `docex projinfra up
  production`, NS-delegated from parent `luxrnd.tech`; ACM issues stage+prod certs; ALB
  fronts the web edge.
- **Backings (elastic):** `appdb` → RDS; `probe` → ECS Fargate task; `events` → ECS
  Fargate task + EFS (mount target per private subnet, `transit_encryption: ENABLED`,
  `aws_efs_backup_policy` when `backups: true`). ClickHouse exercises `persistent_storage`.
- **Core services (elastic):** each is `task_definition` + `ecs_service`; `web` adds an
  ALB target group; `worker`/`clock` have none; `clock` is **not** Service-Connect-
  registered and deploys stop-then-start (`minimum_healthy_percent = 0` / `maximum = 100`).
  One ECR repo + one image tag + one `…-migrate` task-def family per codebase (so exactly
  one of each).
- **`service_diagram.mmd` (elastic):** same topology; annotate the elastic infra mapping
  (ALB TG on `web`; ECS services; RDS/EFS backings). Still must match `infra.yml`.
- **`# Cross-Cutting Concepts` — one EXTRA concept:** `### Code duplication between fixed
  and elastic test projects` (the elastic masterplan's extra section). Two separate
  projects, one per foundation; each carries a full `core/api/` copy; doctrine-faithful
  ("core services never share code"); drift is a signal (`diff -r fixed/core
  elastic/core` should be empty). This has no fixed counterpart — add it to elastic's
  `concepts_and_decisions.md` only.
- **`# Runtime View` (elastic):** same 8 flows by name; the flow prose notes RDS, Service
  Connect (peer resolution; the drain flow depends on `api.web → api.worker` resolution),
  EFS-backed ClickHouse, and ECS-orchestrator liveness. The deferral flow is where the
  foundations *converge* (same `DOCEX_SCHEDULES_YAML` literal; enqueue into RDS).
- **ADR 0004 (elastic):** the fan-out deletion note may reference the defer→drain round
  trip depending on Service Connect resolution — keep the topology decision identical to
  fixed; the elastic wording just names ECS/Service Connect where fixed names docker.

The elastic reference sweep (Step 8) is identical: `README.md:5`,
`core/api/tests/test_processor_smoke.py:6`, and the masterplan `§ Shape` citation
(elastic masterplan line ~98) → `docex/plans/design/specifics/test_projects.md § Shape`.

---

## Verification (manual test WAIVED)
Per project: reconciliation shows no load-bearing loss; `docex docs check` (source `.venv`)
exits 0; `grep -rn "plans/core" $P` shows only frozen CHANGELOG record-lines. After both:
repo-root `linkcheck.py` exits 0 GREEN. Report the reconciliation ledger for each project.

## Commits (dual-commit; approved Q1)
**Inside each nested repo** (`git -C docex/test_projects/<project>`), one commit in that
project's history style, e.g.:
`Migrate design docs to 3.0.0 arc42 structure`
staging that project's migrated `plans/` + `README.md` + `CHANGELOG.md` +
`core/api/tests/test_processor_smoke.py`.

**Outer jean_baudrillard repo** (branch `011_archdoc_skills`) — the corporal handles the
bookkeeping commits:
- `mod 169 design done, impl. steps written` (overview + this file). *(already made before
  dispatch.)*
- `mod 169 complete; designed, implemented, and documented.` (final) — stages this mod
  folder **and** the same test-project churn (the outer repo tracks those files, so this
  keeps its distribution copy from drifting; PRE_CUT_CHECKLIST A.2.1 contract).

**Do NOT** touch the `engineer/` files, and do NOT convert the test projects to
submodules or gitignore them.

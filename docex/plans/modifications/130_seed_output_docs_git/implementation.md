# Mod 130 — implementation steps

Scope of this document: **the two seed projects' planning docs and changelogs, and
nothing else.** The compiled output is already correct and committed-pending (mod
129 produced it; mod 130's design verified it byte-for-byte idempotent — do not
re-run `compile` and do not edit anything under `infra/output/`). The git cadence —
inner commits, `git tag -f`, outer catchup commits — is **not yours**; the mod's
C.O. runs it after reviewing your work.

Read [`overview.md`](./overview.md) § 4 first. It is the design record for
everything below and states *why* each edit is required. This file states *where*
and *what*.

## Files in scope — exhaustive

```
test_projects/fixed/plans/core/masterplan.md
test_projects/fixed/plans/core/api/api.md
test_projects/fixed/plans/core/api/hex/jobs.md
test_projects/fixed/CHANGELOG.md
test_projects/elastic/plans/core/masterplan.md
test_projects/elastic/plans/core/api/api.md
test_projects/elastic/plans/core/api/hex/jobs.md
test_projects/elastic/CHANGELOG.md
```

Eight files. **Touch nothing else.** In particular: not `infra/output/**`, not
`infra/infra.yml`, not `infra/contracts/*`, not `core/**`, not
`plans/core/api/db_schema.md`, not `plans/core/api/hex/{pings,processor,retention}.md`
(all four were grepped at design time and carry nothing stale), and nothing under
`docex/plans/core/` or `docex/doctrine_excerpts/` or `docex/test_projects/PRE_CUT_CHECKLIST.md`
(mod 131's).

## Ground truth — read these before writing

The docs must describe the code **as written**, not as any plan forecast it. Read:

| File (in `test_projects/fixed/`) | What you need from it |
| --- | --- |
| `core/api/health.sh` | the three arms, the exit-code contract, the 30 s threshold and its comment |
| `core/api/src/entrypoints/worker.py` | `_POLL_INTERVAL_SECONDS = 1.0`, `_TICK_PATH = Path("/tmp/worker.tick")`, `_RPC_PORT`, the uvicorn daemon thread and *why it survives* |
| `core/api/src/entrypoints/clock.py` | `_TICK_INTERVAL_SECONDS = 5.0`, `_TICK_PATH = Path("/tmp/clock.tick")`, and that uvicorn/fastapi are gone entirely |
| `core/api/src/root.py` | which build functions exist; where each router is mounted; the `/health` and two `/diagnostics/*` routes |
| `core/api/src/hex/jobs/**` (six new files) | exact class names and method signatures |
| `infra/infra.yml` | the `surfaces:` blocks and their comments; `api.clock` has no `port` |
| `infra/contracts/*.yml` | the three filenames and each header's stated purpose |
| `infra/stage/tests/test_smoke.py` | the five test names, incl. `test_defer_and_drain_round_trip` |

`test_projects/elastic/core/` is byte-identical to `test_projects/fixed/core/` by
design — read one tree.

Doctrine files worth having open: `healthchecks.md` (esp. § *What the probe must
actually check*, § *The orchestrator carries the result*, § *`web` services also
serve `GET /health`*), `contracts.md`, `cicl.md § Surfaces`.

## Standard these docs are held to

These are the **projects' own** core planning docs — what a downstream reader opens
when they want to know what good project documentation looks like under this
doctrine. `docs.md § Core Planning Documents` applies in full: the docs must
describe the project accurately enough that it could be rebuilt from them.

Match the existing voice, which is specific and argumentative: it states a choice,
then the reason, then what a reader would otherwise wrongly conclude. Do not
flatten it into a feature list. Where the existing prose already makes the right
argument on the wrong mechanism, **preserve the argument and swap the mechanism** —
do not delete a good paragraph because one noun in it went stale.

---

## Step 1 — repoint three dead doctrine citations

Three prose citations name doctrine headings that **no longer exist**. Post-edit
`contracts.md` has exactly one heading, `## Standards`. Fix wherever they appear in
the eight in-scope files:

| Dead | Replace with |
| --- | --- |
| `contracts.md § Declared by fields` | `cicl.md § Surfaces` — a *surface*, not a field, is what makes a provider |
| `contracts.md § Health Checks` | `healthchecks.md § What the probe must actually check` |
| `contracts.md § Fan-out` | nothing — it was deleted with the fan-out; remove the citation with the claim it supported |

**Do not invent a replacement anchor you have not verified exists.** Before writing
any `<file>.md § <Heading>` citation, `grep -n '^#' doctrine/infrastructure/<file>.md`
and confirm the heading. These citations are prose rather than markdown links, so
nothing mechanically catches a wrong one — which is exactly how these three rotted.

---

## Step 2 — `plans/core/masterplan.md`, both trees

Edit each tree's copy separately; they differ legitimately by foundation and must
stay different. Section names below are the same in both; the elastic copy's
per-service paragraphs carry elastic mechanism and must keep it.

### 2a. Core Services table

- `worker`'s `Port` cell: drop `(health only)`. Fixed → `8081`. Elastic → `8081`,
  and its `On elastic` cell keeps target-group-free wording. The port is now the
  address at which `api.web` reaches the worker's `rpc` surface.
- `clock`'s `Port` cell: **`—`**. It declares no port on either foundation. On
  elastic its `On elastic` cell keeps `task_definition + ecs_service`, **no** target
  group, stop-then-start deployment — and must lose any implication of
  Service-Connect discoverability (see 2d).

### 2b. The `#### api` subsection's Contracts bullet

Three contracts, four-segment paths, keyed on **surface** and not on role:

```
api.web.rest.openapi.yml
api.worker.rpc.asyncapi.yml
api.worker.events.asyncapi.yml
```

State that **declaring a surface is what makes a core service a provider.** The
fixed copy currently says the format follows from `role`; the elastic copy says the
same. Both are wrong now. Delete any statement of the old provider-set formula
`(uses targets) ∪ (web-network services)` wherever it appears — it appears in both
masterplans and both `api.md`s.

### 2c. The `api.worker` paragraph

Rewrite. Required content:

- It carries `port: 8081` because **`api.web` addresses its `rpc` surface** — rule
  32's positive arm — *not* because a `uses` target must be probeable.
- It declares **two surfaces, `rpc` and `events`**, both resolving to `asyncapi`.
  They are two surfaces rather than one because their consumer sets are unrelated:
  `api.web` calls `rpc` synchronously; `events` is produced onto by `api.web` and
  `api.clock` and consumed here.
- It **declares no `health_check_path`** (rule 33 confines that field to
  `web`-network core services) and **serves no `/health`**. Its liveness is a tick
  file at `/tmp/worker.tick`, read by `./health.sh worker` from a separate process.
- `replicas: 2`, honoured in `prod` only — unchanged, keep.
- **Elastic copy only:** its `port` still makes it Service-Connect-discoverable,
  and that is now load-bearing for a *different* reason than the fan-out — it is
  what lets `api.web` resolve it, and what keeps the Service Connect **consumer
  reconcile** exercised at all. Do not restate the reconcile mechanism in detail;
  one sentence and the fact that the worker's registration is what keeps it
  covered.

### 2d. The `#### api.clock` subsection

- Its **"No exemptions"** bullet currently says it serves `/health` off its loop
  tick. Keep the *claim* ("no exemptions") and swap the *mechanism*: it gets a
  container probe like every other core service, via `./health.sh clock`, sourced
  from the loop's tick file. It still gets an OTel sidecar; `replicas` is still
  forbidden.
- Add, plainly: **it binds no application socket.** Mod 129 verified this against
  the container's `/proc/net/tcp` — the only `LISTEN` entry is docker's embedded
  DNS resolver at `127.0.0.11`, which every container has. This is the strongest
  single piece of evidence that health left HTTP, so state it as observed fact.
- Its **Contract** bullet: replace the provider-set formula with "it declares no
  surface, and that is what makes it not a provider."
- **Elastic copy only:** its `health_check_path`-routes-to-container-`healthCheck`
  bullet is now false twice over (the field is gone; the probe is a role default).
  Replace with: the probe arrives as a transfer-table **default** and lands on the
  task definition's container, so a wedged cron loop gets the task killed and
  replaced by the service. Also state that it now joins Service Connect as a
  **client-only** member — `enabled` with a namespace and **no** `service {}` block
  — so it resolves peers and nothing resolves it, which is correct because nothing
  addresses a clock.
- Leave `deployment_minimum_healthy_percent = 0` / `= 100`, the schedules bullets,
  the startup-validation bullet, and the EventBridge "what is gone" bullet
  untouched. They are all still true.

### 2e. Flows — the largest edit

The fixed masterplan has eight numbered flows. The elastic masterplan has a single
`## Flows` paragraph that *enumerates them by name* and then adds elastic specifics;
it must be kept in sync by name.

- **Flow 3 — *Self health*.** Rewrite. `GET /health` survives on `api.web` **only**,
  because a load balancer reads it (`healthchecks.md § web services also serve GET
  /health`). Worker and clock liveness becomes the second half of this flow: the
  loop touches `/tmp/<svc>.tick` at the end of each successful iteration; a
  separate process (`./health.sh <svc>`) stats it and fails if it is absent or more
  than 30 s old. State the number pair **and why it is only meaningful as a pair**:
  the 30 s threshold lives in `health.sh`, the ≤10 s cadence in the entrypoint
  (1 s worker, 5 s clock), and 30 is three times 10 so a healthy loop misses two
  consecutive ticks before it is called stale. State that an **absent** tick file
  fails — a loop that never completed an iteration was never alive.
- **Flow 4 — *Health fan-out* is DELETED**, and the slot is reused for
  ***Deferred-job drain***, keeping the numbering at eight:

  `POST /jobs/drain` on `api.web` → `ContJobDrainHttp` → `JobDrainService` →
  `GwyJobRunnerHttp` (using `WORKER_HOST` / `WORKER_PORT`) → HTTP to `api.worker`'s
  `rpc` surface → `ContJobRunnerHttp` → `ContJobRunner.run_once()` → `{performed: N}`
  travels back out through the edge.

  Say what this flow is *for*: it is the only flow crossing a process boundary
  between two core services, so it is what carries the `uses` edge, the magic refs,
  and rule 32's positive arm. Say that its reply is a **count of work performed** —
  no liveness verdict, no staleness judgment — so it cannot be mistaken for the
  thing this advance deleted.
- **Flow 5** — retarget to `/diagnostics/probe` and `/diagnostics/events`. Substance
  (Service Connect / docker DNS / SG / EFS-mount coverage) unchanged. Add the reason
  for the rename in one clause: they probe *backing* services, and leaving them
  under `/health/*` would invite a reader to conclude the fan-out survived, against
  `healthchecks.md`'s "No service reports on another."
- **Flow 8 — *Clock self health*.** Rewrite as the clock's half of flow 3's tick
  mechanism. Its existing honest point survives and gets stronger: nothing external
  reaches the clock, and the enforcement is now the orchestrator acting on
  `./health.sh clock` — docker reporting `unhealthy` on fixed, ECS killing and
  replacing the task on elastic.
- **Do not add a ninth flow.** Draining is flow 4's subject; job *performance* is
  already flow 7's.

### 2f. Hard Boundaries

- `api.worker.asyncapi.yml` → `api.worker.events.asyncapi.yml` in the "no real
  broker" boundary.
- **Add a boundary: no core service reports on another's health.** This project had
  a fan-out and deliberately does not any more. A copying project needs that told,
  not left to infer from an absence — which is the same reason the one-codebase
  boundary is stated at length.

---

## Step 3 — `plans/core/api/api.md`, both trees

### 3a. Core-service table

As step 2a. `clock`'s `Port` → `—`. The elastic copy's `(health only,
Service-Connect-discoverable)` parentheticals: `worker` keeps
Service-Connect-discoverable and loses "health only"; `clock` loses both.

### 3b. The `api.worker` and `api.clock` paragraphs (currently ≈ L15–17)

Rewrite off the surfaces-and-tick model. **Preserve the clock paragraph's
structure** — it is the document's best passage and its argument ("no exemptions,
and the consequence, that nothing external can reach it, is easy to misread as an
oversight") is still exactly right with `./health.sh clock` substituted for
`/health`. Both paragraphs lose `health_check_path` and the "must be probeable"
reasoning; the worker's gains the `rpc` surface as the reason for its port.

### 3c. Composition root (currently ≈ L44)

- `build_app()`'s inventory: `ContPingsHttp`, `ContJobsHttp` and **`ContJobDrainHttp`**
  routers, plus the standalone `/health`, `/diagnostics/probe`, `/diagnostics/events`
  routes. `/health/api/worker` is gone.
- Add **`build_job_runner_http() -> ContJobRunnerHttp`** to the build-function list,
  and note that the root constructs it even inside `api.web`'s process, where
  nothing mounts it — the same `internal_dependency_rules.md § Composition Root`
  item 3 argument the existing `build_jobs_cli` entry already makes, now with a
  second instance. **Do not** claim a `build_job_drain_http()` exists; it does not.
  `ContJobDrainHttp` is constructed inside `build_app()` alongside the other two
  routers the web app mounts. Verify against `root.py` before writing this
  paragraph.
- Keep `_RETENTION_DAYS = 30` and its reasoning.

### 3d. Entrypoints (currently ≈ L60, L70)

- "the **liveness surface**" is the wrong noun in both entries — it is a file touch,
  not a served route. Replace with "the **liveness tick**" and describe the file.
- `worker.py`: it **keeps a uvicorn daemon thread**, and the doc must say why —
  it serves the `rpc` surface, not health. This is the diff's most misreadable line;
  a reader who skims it will conclude the health server survived under a new name.
  Keep the existing main-thread/daemon-thread signal explanation, which is still the
  reason for the arrangement.
- `clock.py`: state that it loses uvicorn, fastapi, and its listener **outright**,
  and that this is the file which proves the change is real rather than cosmetic —
  everywhere else HTTP survives for a reason, and here, where the only reason was
  health, it is gone completely.
- Both: the tick is withheld on a failing pass, unchanged — keep that reasoning, but
  check the wording. The old phrasing "would answer 200 forever" is stale in a file
  that answers nothing; the source files were corrected to "would keep the probe
  green forever" and the docs should match.

### 3e. Contracts (currently ≈ L76–83)

Three entries, four-segment paths, keyed on surface, each saying which surface
produced it. Required content:

- The two-surfaces-one-format case, explicitly: `rpc` and `events` both resolve to
  `asyncapi`, and they are two surfaces because their consumer sets are unrelated.
  Both channels the worker consumes (`pings`, `jobs`) stay in the **one** `events`
  document, per `cicl.md`'s split table.
- `api.clock` still has no contract — now on the plain ground that it declares no
  surface. Keep the "this is the rule rather than an exemption" framing; drop the
  provider-set formula.
- The spec-version floor: **OpenAPI 3.2 or later, AsyncAPI 3.0 or later**
  (`contracts.md § Standards`). Note that nothing enforces it mechanically —
  `docex check` only YAML-parses the document and reads `paths` — so it is a
  discipline the project holds itself to. The AsyncAPI 3.0 move is also what makes
  `reply` available to describe the `rpc` surface.

### 3f. New section: `## Health`

Insert as its own section (after `## Entrypoints`, before `## Contracts` reads
best). `health.sh` is the codebase's **fourth shim** beside `build.sh` / `test.sh` /
`migrate.sh`, and it is the only one invoked **per core service**. Cover:

- **The exit code is the entire contract.** Nothing reads stdout — docker captures
  probe output and ECS does not, so it can never be a cross-foundation channel. The
  stderr messages are for a human reading `docker inspect` and promise nothing.
- **Three arms.** `web` curls its own `/health` (a request-cycle service is nearly
  self-checking, and this is the one place in the file where curling yourself is
  legitimate). `worker` / `clock` stat their tick file. Unknown argv **exits 2
  loudly**, because falling through to 0 would report every core service healthy
  forever — the one outcome worse than a wrong probe.
- **POSIX `sh`, not bash** — `python:3.12-slim` ships dash and no bash. `stat -c %Y`
  + `date +%s` rather than a python one-liner, so the probe pays no interpreter
  startup inside a 5 s timeout.
- **Where the two numbers live and why they are a pair** — as step 2e's flow 3.
- **`curl` is in the image for the `web` arm** and for nothing else. The doctrine
  withdrew the blanket curl mandate; what an image needs is whatever *its*
  `health.sh` uses.
- **Foundation difference, stated once:** docker only *reports* `unhealthy`; ECS
  *kills and replaces* a task whose essential container fails, which is why
  `startPeriod: 10` exists in the role tables and is elastic-only. Each tree's copy
  should lead with its own foundation.

### 3g. Hard boundaries (currently ≈ L91–99)

- Delete the `/health/api/worker` one-hop bullet.
- Rename the backing-probe bullet to `/diagnostics/*` and add the reason for the
  rename (step 2e, flow 5).
- **Add** a bullet on `POST /jobs/drain`'s concurrency: it is safe against the
  worker's own loop draining simultaneously because `QueueJobsPostgres` opens a
  connection per call and `claim`'s `FOR UPDATE SKIP LOCKED` is the same guarantee
  that makes `replicas: 2` safe. This is the second consumer of a guarantee whose
  first justification is already written down in `hex/jobs.md` — say so and link
  there rather than restating it.
- Keep every other boundary. The "no `api.web` entry in the worker's `uses:`" one is
  still exactly right and is now *more* interesting, because `api.web` → `api.worker`
  is a live HTTP edge and the reverse still is not.

---

## Step 4 — `plans/core/api/hex/jobs.md`

**Write it once, then copy it to the other tree.** The two copies are currently
byte-identical and must stay so:

```
cp test_projects/fixed/plans/core/api/hex/jobs.md \
   test_projects/elastic/plans/core/api/hex/jobs.md
diff test_projects/{fixed,elastic}/plans/core/api/hex/jobs.md   # must be silent
```

This file is **pure addition** — nothing in it is stale. The module grew a
cross-process boundary and the document does not know about it.

### 4a. Driving Ports table

Add `ContJobDrain` — `drain_now() -> int`, driven by `api.web` over HTTP.

### 4b. Driven Ports table

Add `GwyJobRunner` — pattern `Gateway`, `drain_now() -> int`.

### 4c. Adapters Included table

| Adapter | Kind | What it is |
| --- | --- | --- |
| `ContJobRunnerHttp` | driving, `Http` | provider side; `POST /drain` → `{performed: N}`; mounted by `entrypoints/worker.py` |
| `ContJobDrainHttp` | driving, `Http` | consumer side; `POST /jobs/drain` on `api.web`; mounted in `build_app()` |
| `GwyJobRunnerHttp` | driven, `Gateway` | calls the worker's `rpc` surface using the injected `WORKER_HOST` / `WORKER_PORT` |

Verify each class name and signature against the source before writing the table.

### 4d. New section — one module, two processes

This is the section that matters most, and it goes **beside** *"The two dispatch
tables are not duplication"*, because it is the same argument arriving at a third
place. A reader who misreads this shape will conclude the doctrine permits
cross-module imports — so the section must be unambiguous that it does not.

Required content:

- `jobs` now **spans a process boundary**. `api.worker`'s process holds the perform
  half; `api.web`'s process holds a consumer half that reaches it through a
  **driven gateway**. The worker is an *external system* from the consumer's point
  of view — even though both run the same image from the same codebase — which is
  precisely why the port is a `Gwy` and not an import.
- **Why five consumer-side files** (`GwyJobRunner`, `GwyJobRunnerHttp`,
  `ContJobDrain`, `JobDrainService`, `ContJobDrainHttp`) rather than one HTTP call:
  the alternative is application HTTP inside `root.py`, which is exactly what the
  deleted fan-out was. These five are the doctrine's tax for a clean hexagon, and
  they are the seeds' **only** demonstration of a consumer-side gateway onto a
  sibling core service across a declared surface.
- **Why `drain_now()` is not a method on `ContJobs`** — the port the *clock* holds.
  Giving `ContJobs` a drain method hands the clock the ability to trigger
  performance, which is the deferral architecture this document's longest section
  exists to protect. A separate port is the cheaper mistake to avoid.
- **Why it is not a health check**, in one line: the reply is a count of work
  performed; it carries no liveness verdict and no staleness judgment.

### 4e. Concurrency section — extend

`POST /drain` is a **fourth** concurrent claimer against the same queue (beside the
two `prod` worker replicas and the live `test`-env worker the section already
counts), safe by the same `FOR UPDATE SKIP LOCKED`. State the consequence for
testing: this is why the stage test asserts an **integer** `performed` and **not a
count**. The worker drains every second on its own, so a heartbeat queued by the
test may legitimately already be gone and `{performed: 0}` is the honest reply. An
order-dependent count would pass locally and burn a walk. Note that the load-bearing
assertion is the `200` itself, on a route that cannot answer without reaching the
worker across the internal network.

### 4f. Hard Boundaries — add two

- The drain boundary commands **performance**, never deferral. Deferral is the
  clock's, over `ContJobs`.
- The reply's integer is a count of work this call performed; it is **not** a
  promise about which rows moved, and nothing may be built on it as if it were.

---

## Step 5 — `CHANGELOG.md`, both trees

One entry per tree, under the **existing `## [Unreleased]` heading**.

**Hard constraints:**

1. **Do not bump `project.yml`'s version** and do not open a new version heading or
   write a dated release line. The walk's `merge` step bumps; bumping now fails its
   version-not-yet-released gate. `project.yml` is not in scope at all.
2. **Do not revise historical entries.** Several past-version sections describe the
   fan-out, `health_check_path` on the worker, and three-segment contract paths.
   That is what those versions did; keepachangelog history is a record, not a
   description of the present. A grep for the retired spellings **will** hit them
   and that is correct.

Use the sections the file already uses, in its order:

- **Changed** — probe is `./health.sh <service>` on both foundations; worker/clock
  liveness is a tick file, not an HTTP route; `api.web`'s two backing probes renamed
  to `/diagnostics/*`; contract filenames gain a surface segment; spec floors raised
  to OpenAPI 3.2 / AsyncAPI 3.0; `api.clock` drops its `port`; both non-`web` core
  services drop `health_check_path`.
- **Added** — `core/api/health.sh`, the fourth codebase shim; `api.worker`'s `rpc`
  surface (`POST /drain`) and `api.web`'s consumer-side gateway onto it, exposed as
  `POST /jobs/drain`; `infra/contracts/api.worker.rpc.asyncapi.yml`; the stage
  suite's `test_defer_and_drain_round_trip`; three codebase tests in
  `core/api/tests/test_jobs_drain.py`.
- **Removed** — `GET /health/api/worker` and the fan-out; `GET /health` on
  `api.worker` and `api.clock`; the clock's uvicorn/fastapi listener; the stage
  suite's fan-out test.

**The two entries are not the same text.** Each states its own foundation's
consequence, because they differ and shared wording would be false for one:

- **fixed** — the probe is the only enforcement; docker merely *reports*
  `unhealthy`, and nothing acts on it except traefik dropping the container from its
  pool.
- **elastic** — ECS **kills and replaces** a task whose essential container fails a
  probe, which is why `startPeriod: 10` exists and is elastic-only. Also record two
  compiled-output consequences: `api-web`'s task definition **gains** a container
  `healthCheck` it never had (pre-change, `health_check_path` routed only to the ALB
  target group), and `api-clock` **leaves the Service Connect registry**, remaining
  a client-only namespace member.

Write these as the *project's* changelog, not as a `docex` mod note: no mod numbers,
no advance numbers, no reference to `docex`'s branch or its internal planning.

---

## Step 6 — verification

Run from `docex/`. Report each result.

1. **Retired spellings are gone from `plans/`.** Expect **zero** hits:

```sh
grep -rn 'health/api/worker\|fanout\|health_check_path\|/health/probe\|/health/events\|api\.web\.openapi\|api\.worker\.asyncapi\|liveness surface\|health only\|Declared by fields\|contracts\.md § Health Checks\|contracts\.md § Fan-out' \
  test_projects/fixed/plans test_projects/elastic/plans
```

`fan-out` **with the hyphen** is expected to survive in negation ("no core service
reports on another; this project had a fan-out and deliberately does not any more").
That is the prose working, not residue — mod 129 hit the identical false expectation
and the grep was the thing that was wrong. It is therefore deliberately absent from
the pattern above; if you want to check it, check it by reading the hits.

2. **`CHANGELOG.md` hits are historical only.** The same grep over the two
   changelogs will hit past-version sections. Confirm every hit sits under a
   `## [0.0.x]` heading and none under `## [Unreleased]`. Report the count and the
   headings, not a bare number.

3. **`jobs.md` parity** — `diff test_projects/{fixed,elastic}/plans/core/api/hex/jobs.md`
   silent.

4. **Nothing outside scope moved.** `git status --porcelain` from the repo root must
   show, beyond the eight pre-existing `infra/output/**` modifications the design
   left in place, **only** the eight files listed at the top of this document.
   Report the full output.

5. **Every doctrine citation you wrote resolves.** For each `<file>.md § <Heading>`
   you added or changed, `grep -n '^#' doctrine/**/<file>.md` and confirm. Report the
   citations you checked and the headings you found. Nothing mechanical catches these
   yet — mod 132 is building that arm precisely because this advance found two
   instances of them rotting silently.

6. **Do not run `pytest`**, `compile`, `check`, or any git command that writes. The
   C.O. runs the suite and the git cadence after reviewing your work.

## If an instruction here is wrong

Say so and stop, rather than working around it. Three of mod 129's own
implementation steps were wrong — one grep contradicted three other steps in the
same plan, one prescribed an invocation that cannot collect the suite, and one froze
three comments as "verbatim" that the surrounding change had made stale. The
implementor reported all three instead of silently complying, which is the behaviour
this project wants. If a line number in this document does not match the file, trust
the file: the numbers are from a design-time read and the section names are the
durable reference.

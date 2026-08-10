# Mod 131 — Alignment sweep and cut artifacts

The seventh and last documentation mod of [advance 006](../../advances/006_surfaces_and_health/advance_plan.md).
No `src/`, no `tables/` emit behavior, no seed tree. Every file here is something a
**human or a fresh agent reads to learn what shipped** — so the failure mode is not a
red test, it is a reader acting on a sentence that was true two weeks ago.

**Territory.** `docex/plans/core/*`, `docex/doctrine_excerpts/*` + `index.yml`,
`docex/test_projects/PRE_CUT_CHECKLIST.md`, `docex/tables/roles/web.yml` (comments
only), `upgrades/upgrade_1.7.0.md`, root `CHANGELOG.md`.
**Not** the seed trees (mods 129–130, committed), **not** `src/`, **not**
`linkcheck.py` (mod 132), **not** doctrine prose (raised to sarge, never edited).

**Baseline.** Branch `006_surfaces_and_health`, HEAD `bce7b74`, tree clean.
`python -m pytest tests` → 1174 passed, 18 deselected. `python -m pytest tests -m integration`
→ 18 passed, run alone. This mod edits no code, so both counts must be **unchanged**
at the end; a change is a finding, not a success.

---

## 1. What is actually false right now

Collected from mods 126–130's handoffs plus my own read. Ordered by how badly a
reader is misled, not by file.

| # | Site | The false claim | Severity |
| --- | --- | --- | --- |
| 1 | `masterplan.md` § *The contract and health gates* | The whole block: two-armed provider union, format-from-`role`, the openapi fallback, self-health-for-every-openapi-provider, the fan-out, "a core `uses` target must declare both `port` and `health_check_path`", "the curl gate stays". Every sentence. | **Reader builds the wrong mental model of `check` entirely** |
| 2 | `PRE_CUT_CHECKLIST.md` D.11 (l. 426) | A walk box asserts `GET /health/api/worker` returns 200. **That route is deleted.** A walker following it records a failure against correct code. | **Blocks the cut on a phantom** |
| 3 | `PRE_CUT_CHECKLIST.md` C.9 (l. 270) | Same, on the fixed walk, plus "the **only** externally-observable view of `api.worker`'s liveness". | Same |
| 4 | `PRE_CUT_CHECKLIST.md` B.9 / B.10 | The pre-walk audit gates the walk on the retired model — format-from-role, the three-part health model, fan-out routes, `port` **and** `health_check_path` on every core `uses` target. **B is the gate on both walks**, so this is the highest-leverage file in the mod. | Same |
| 5 | `upgrade_1.7.0.md` "what does not move" | *"No container name, hostname, image ref, **contract path**, `Name` tag … changes."* Contract paths change on every provider in the release. | **Downstream project skips a required rename** |
| 6 | `tables/roles/web.yml` × 2 sites | "nothing on fixed acts on it except traefik, which drops the container from its pool" (`defaults`) and "traefik takes target health from the container healthcheck" (`fields`). Both halves wrong per `cicl.md` rule 33 as amended at `bce7b74`. | Table author copies a false rationale |
| 7 | `compiler.md` l. 489, `CHANGELOG.md` × 2 | The same traefik claim, three more times. | Same |
| 8 | `compiler.md` l. 603–604 | "`uses` drives CI (contracts, health fan-out, rule 7)" and "`check.py`'s contract / health gates … read through `core_uses()`". **`check.py` no longer reads `core_uses` at all** — verified by grep, zero hits. | Reader looks for a consumer that does not exist |
| 9 | `compiler.md` l. 594 | Rule 7's one-directional example is *"`api.web` uses `api.worker` for the contract and health fan-out while holding no ref to it."* False twice: no fan-out, and `api.web` now **does** hold refs (`WORKER_HOST`/`WORKER_PORT`). | The example teaches the opposite of the rule |
| 10 | `test_projects.md` l. 17–18, 25 | `api.web` "exposes … the `/health/api/worker` fan-out"; `api.worker` "serves its own `GET /health` off a monotonic loop tick". | Reader of the seed doc looks for deleted code |
| 11 | `doctrine_excerpts/codebase.md` | Lists the codebase's shims as "`build.sh` / `test.sh` / `migrate.sh`". **`health.sh` is the fourth.** See § 3.2 — this is *why* the earlier "no excerpt contradicts" verdict missed it. | `docex why codebase` under-reports |
| 12 | `doctrine_excerpts/service_discovery.md` | Prose citation to `cicl.md § Resilience covers reachability, not resolvability` — an anchor the rewrite deleted. | Dead pointer, invisible to `linkcheck` |
| 13 | `PRE_CUT_CHECKLIST.md` l. 201 | **Markdown** link to `contracts.md#health-checks` — dead anchor. | Dead pointer, visible to `linkcheck` if it could reach the file (mod 132) |
| 14 | `docex_process.md` step 3.1 | *"hit with `pytest -m integration`"* — **the exact invocation that collects nothing** and reports 17 deselected while running zero tests. The process doc tells the next agent to run the trap. | See § 4, design question Q1 |

Items 1–13 are corrected. Item 14 is corrected *and* is the subject of Q1.

## 2. `plans/core/*`

### 2.1 `masterplan.md` — § *The contract and health gates* rewritten whole

Retitled **§ The contract and shim gates**, because the health gates in the plural
no longer exist: one narrowed contract-content assertion survives and the rest of
health left `check` entirely. The new block states, in this order:

1. **Provider set = `surfaces:` alone.** A core service is a provider iff it
   declares a surface. Both arms of the old union are gone, and the second arm was
   **wrong rather than redundant** — a `web`-network core service that declares no
   surface (a frontend serving a browser) was forced to carry a contract for a
   boundary it does not describe.
2. **Format follows `api_styles`, derived not tabulated.** `len(surface.formats()) == 1`
   over `model.py::API_STYLE_FORMATS`. No fallback: an unrecognized style is
   `rule_29_unknown_api_style` at *compile*, so the gate has nothing to guess.
   The retired `_FALLBACK_CONTRACT_FORMAT = "openapi"` is named as retired, because
   "silently the wrong format" is the specific failure the fallback caused.
3. **Four-segment right-anchored paths**, one extension per format. `api.web.rest.openapi.yml`
   resolves; `api.web.openapi.yml` and `api.web.rest.openapi.yaml` do not. The
   **orphan arm** is called out by name: a contract matching no declared surface
   fails the gate, which is the only thing that can see a leftover three-segment
   file sitting *beside* a correct one.
4. **`contract_health_path`, narrowed.** Where a `web`-network core service also
   declares an `openapi` surface, one of its openapi contracts declares a `GET` on
   that service's **declared `health_check_path`** — never a hardcoded `/health`.
   *Any one* openapi surface satisfies it, because requiring it in every surface
   would force a `rest_admin` contract to document a route outside its own
   boundary — a false contract, worse than an omission. Keyed on network
   membership, not role, consistent with rule 33.
5. **`health.sh` is the fourth shim gate**, unconditional; `migrate.sh` stays
   conditional on schema ownership. Roster **10 → 9**.
6. **Two gates deleted.** `_gate_health_endpoints` whole (fan-out, one-hop rule,
   probeability), and `_gate_healthcheck_tooling` — **deleted, not narrowed**,
   because `infrastructure.md § Codebase Containers` withdrew the `curl` mandate.
   A gate enforcing a requirement the rule of record has withdrawn is worse than
   no gate. (The current text says the curl gate *stays*; that is item 1's worst
   single sentence, because it reads as a live requirement.)

**Mod 101's closing paragraph survives as history**, re-marked as history rather
than deleted: `_infer_contract_format` had returned `openapi` unconditionally
since the day it was written, so the async path had never once executed and the
fan-out flaw hid behind it. That is the reason the format was keyed on `role` for
as long as it was, and deleting it would delete the explanation for the defect
this advance fixed.

Two smaller masterplan edits: the Filesystem Surface read-path entry
`infra/contracts/<codebase>.<service>.<fmt>.yml` → four-segment form; and § *The
orchestrator liveness/version gate* is **left alone** (mod 128 wrote it, it is
current, and re-touching it is how a sweep introduces a defect).

### 2.2 `compiler.md` — targeted, not swept

§ Validation (mod 125) and § *The container probe* (mod 127) are current and are
**not** redone. What moves:

- **l. 594** — rule 7's one-directional example is replaced with the live one:
  **`api.clock` uses `api.worker` and holds no ref**, because the edge is the
  `jobs` table rather than the mesh. This is a better example than the one it
  replaces, and it is the same asymmetry rule 32 is edge-scoped for — so the two
  paragraphs now illustrate each other instead of contradicting the tree.
- **l. 603** — "`uses` drives CI (contracts, health fan-out, rule 7)" →
  `uses` drives **validation** (rules 7, 25, 31, 32), the elastic Service Connect
  reconcile, one *view* (`describe`), and one emission (the exec block's readiness
  gate). Contracts are driven by `surfaces:` and no longer by `uses`.
- **l. 604** — the read-site list loses `check.py`. Verified: `core_uses` /
  `backing_uses` return **zero hits** in `pipeline/check.py`. The list keeps rule
  7 and the compiler, and gains rules 31/32 — which is where the "one parser, one
  place to drift" argument now earns its keep.
- **l. 602** — mod 101's cron-role clause stays as history but is tensed as
  history, since "the contract requirement that `uses` drives" is no longer a
  present-tense fact.
- **l. 489** — the traefik claim, replaced with rule 33's own wording: on fixed
  `health_check_path` has **no consumer at all**, the compiler emits no
  health-aware load-balancer labels, and whether traefik passively withholds
  routing is unverified and must not be relied on. The container probe's two
  fixed consumers are Docker (reports; restarts nothing of its own accord) and
  `docex stagetest`.
- `Where to look` — one new row: *how the provider set and contract format are
  derived* → `pipeline/check.py::_gate_contracts` + `model.py::API_STYLE_FORMATS`,
  noting the table lives on the model because two consumers read it.

### 2.3 `release_flow.md` — one line, and I am saying so rather than inventing work

A grep for health/contract/surface/fan-out across the file returns **two** live
hits. l. 142 is mod 128's and is current. l. 269 tells the operator to "confirm
target version is actually older than current via `/health` on the deployed env"
— not false (a `web` edge still returns `{version}`) but no longer the *truthful*
instrument: the doctrine now says the orchestrator wins when it and a self-report
disagree. Repointed at the orchestrator read, with the self-report named as the
weaker of the two.

Nothing else in this file moved. Stated explicitly because a sweep that reports
"swept" without saying what it found is indistinguishable from one that did not run.

### 2.4 `test_projects.md`

- § Shape's three bullets rewritten against what the seeds are now: `api.web` —
  `POST /pings`, `GET /health`, `/diagnostics/{probe,events}`, one `rest` surface;
  `api.worker` — `POST /drain` on a real `rpc` surface plus an `events` surface,
  `replicas: 2`, liveness a **tick file** read by `./health.sh worker`;
  `api.clock` — no `port`, no `health_check_path`, no `surfaces`, and **no
  application socket at all**.
- The 10s/30s sentence gains its split: the **cadence** lives in the entrypoint
  (the only thing that can honour it), the **threshold** in `health.sh` (the only
  thing that judges it), and each number is meaningless without the other.
- The worker's **two surfaces of one format** are called out, because they are the
  only exercise in the repo of "one format, two unrelated consumer sets" and a
  reader will otherwise assume one surface per format.
- Per Q1, a pointer to `docex_process.md`'s suite-invocation rules rather than a
  second copy of them.

## 3. `doctrine_excerpts/` — the aggregate verdict

### 3.1 The verdict

**`surface` earns no `index.yml` entry.** Recorded in `docex_process.md` beside
the `uses` and `clock` precedents, with the reasoning, because on this artifact a
silent no is indistinguishable from an oversight.

The criterion is *infrastructural resources* — the nouns a deployed stack is
physically made of, tracking `shape.md`'s `[resource]` notation. A surface fails
it three ways, and each rules out a different wrong answer:

1. **Nothing is deployed for a surface.** It has no container, no DNS name, no
   ARN, no `shape.md` `[resource]` box. `api.worker`'s two surfaces are two
   *documents in the repo* and one process.
2. **It is a CICL field**, which the stated criterion excludes by name — `cicl.md
   § Service Fields` and `§ Surfaces` specify it, and a third hand-maintained
   restatement buys nothing.
3. **`api_styles`, `health.sh`, and the container probe fail the same test**, so
   the verdict is written to cover the advance rather than one noun — otherwise
   the next mod re-asks it about `probe`.

The mod-126/127/128 halves are folded into the same paragraph: none of the three
introduced a resource, and mod 128's row said so in its own overview expressly so
this mod could aggregate it.

### 3.2 One correction the earlier greps could not have found

**`codebase.md` lists the codebase's shims as "`build.sh` / `test.sh` /
`migrate.sh`".** `health.sh` is the fourth. Corrected.

This is worth more than the one-word fix, because it explains a limit in the
method three mods used: they grepped all 18 excerpts for
**health / contract / surface / curl** and got zero, and concluded nothing
contradicted the new model. That grep is sound for a *changed* claim and blind to
an *omission* — the offending line contains none of those four words, it contains
three filenames. **A grep for the new thing cannot find a list that lacks it.**
The verdict "no excerpt contradicts the new model" was therefore right about
contradiction and wrong about completeness. Recorded in `docex_process.md` with
the verdict, since the same blindness applies to every future sweep of this
artifact.

### 3.3 The other three, decided either way

- **`service_discovery.md`** — the dead prose citation is repointed to
  `infrastructure/reasoning/elastic_release_pattern.md` and
  `infrastructure/specifics/release.md § Service Connect Consumer Reconcile`,
  both live. This is the original instance of the prose-citation drift class;
  mod 130 found a second, and **mod 132 owns the mechanical arm**. No content
  change — the excerpt's deployment-fixes-resolvability prose is correct and is
  in fact *more* load-bearing after this advance, because the reconcile's symptom
  is no longer a fan-out 503 but silence.
- **`core_service.md`** — **gains one clause**: every core service's container
  carries the probe `./health.sh <service>`, emitted by the compiler on both
  foundations, and it is the only liveness enforcement a core service off the
  `web` network gets. Justification for adding rather than abstaining: this is a
  property of the *deployed resource* the file already describes ("always a
  container"), it is exactly what an operator running `docex why core_service`
  after this release needs, and it is one sentence rather than a restatement of
  `healthchecks.md`. No surface content — surfaces are an authoring and CI
  concept and belong in `cicl.md`.
- **`reverse_proxy.md`** — **no probe or surface content earned.** It answers
  "how do requests reach the right container", and the probe answers a different
  question; adding it would make the excerpt a second home for a topic
  `core_service.md` now covers. But see Q2: this file carries a **pre-existing
  falsehood** unrelated to this advance.

## 4. `PRE_CUT_CHECKLIST.md`

This gates both walks, so it is treated as the mod's highest-stakes file. Boxes
moved, boxes deliberately left, and the four hard requirements.

### 4.1 Boxes rewritten

| Box | Change |
| --- | --- |
| **B.3.1** | `surfaces` joins the core-service field list; `health_check_path` noted as network-conditioned rather than role-conditioned. |
| **B.6** | The Dockerfile requirement is that the image **can run `./health.sh <service>`** — whatever that takes is the project's choice. `curl` is no longer doctrine-mandated; the seeds carry it **for one line** of `health.sh`'s `web` arm, and the box says so, because "curl is in the image" must stop reading as conformance. |
| **B.7** | `health.sh` is the **fourth codebase shim**, required unconditionally. Its **per-core-service argv asymmetry** is called out: one file per codebase like the others, but invoked `./health.sh <service>` because a web edge and a worker of one codebase have genuinely different probes — and the compiler supplies the argv so the script never guesses. |
| **B.7.1** | Stays **three** shims, and gains an explicit carve-out naming `health.sh` as the exception. `build.sh`/`test.sh`/`migrate.sh` run in the one-off `-exec` container, whose `environment:` is `codebase_env` — so a core-service-scoped key is absent in them. `health.sh` runs **inside the running core-service container**, so it sees that core service's full env surface. Extending B.7.1's rule to the fourth shim would be wrong, and getting it wrong is silent, which is why the box says it rather than leaving it inferred. |
| **B.9** | Provider set = `surfaces:`; format from `api_styles`; **four**-segment paths; one extension per format; the orphan arm; a `clock` correctly carries no contract because it declares no surface (not because of an exemption); and a `web`-network core service declaring no surface correctly needs **none** — the box that would have been wrong under the old union. |
| **B.10** | Rewritten from the three-part model to: (a) the container probe is `["CMD","./health.sh","<svc>"]` on every core service, **compiler-emitted, not authored**; (b) `health.sh` branches on argv — loop-owners stat a tick file the loop touches *from inside itself*, absent tick **fails**; (c) the 10s cadence / 30s threshold pair, doctrine-fixed, split across entrypoint and shim; (d) `GET /health` survives **only** on `web`-network services, only because a reverse proxy reads it, and where such a service declares an `openapi` surface the route is in that contract; (e) rule 33 both arms; (f) **no fan-out anywhere** — a grep for `/health/<codebase>/<service>` must return zero across the seed tree. The clock paragraph and the § B preamble note both lose "its `/health` is enforced by the container healthcheck" — the clock has no `/health`; it has a probe. |
| **C.8** | `stagetest` now runs the **orchestrator liveness/version gate before the tester image is built** (`docker inspect` over SSH on fixed). The box records which line it prints and that a failure there is *earlier* than a tester failure. The tester's own probes: `/health` on the web edge, `/diagnostics/{probe,events}`, and the defer-then-drain round trip that replaced the deleted liveness fan-out test. |
| **C.9** | The fan-out box is **deleted** and replaced by: `docker inspect --format '{{.State.Health.Status}}'` reporting `healthy` for `api-web`, **both** worker replicas, and `api-clock`; and the defer→drain round trip as the externally-observable proof of worker liveness. The contract-path reference `api.web.openapi.yml` → `api.web.rest.openapi.yml`. The replica-alias rationale is retargeted: a broken network alias now breaks `WORKER_HOST` resolution and therefore `POST /drain`, not a fan-out route. |
| **D.6** | The `/health/api/worker` probe line is replaced by `/diagnostics/{probe,events}` and the two-segment host. The existing `docex build` ordering trap stays and now cross-references the hazard box (§ 4.4). |
| **D.10** | As C.8, with `list_tasks`/`describe_tasks` instead of `docker inspect` over SSH. |
| **D.11** (partial) | **Only** the fan-out box (l. 426) is replaced — with `describe_tasks` container health for `api-web`/`api-worker`/`api-clock` plus the defer→drain round trip. The clock probe box widens to cover `api-worker` too, since "no fan-out and no stage test can reach it" is now true of **every** non-`web` core service rather than the clock alone. |
| **l. 201** | Dead markdown link `contracts.md#health-checks` → `healthchecks.md#what-the-probe-must-actually-check`. |

### 4.2 Boxes deliberately left

- **D.9 and D.11's reconcile boxes, including `N = 2`.** Mod 130 verified the
  count is unchanged: `_reconcile_candidates` keys on whether a consumer's
  *targets* register, both `api.web` and `api.clock` target `api.worker`, and
  `api.worker` keeps its `port` and therefore its Service Connect name. The clock
  going unregistered removes it as a *target*, and **nothing targets a clock.**
  Not touched. A correct number is not a stale number, and "fixing" it would be
  this advance's own recurring defect in reverse.
- **D.9's `api-worker` has a probe and no target group; `api-web` has the target
  group.** True, and *more* meaningful after this advance than before. Kept verbatim.
- **A.4.1's nine standing DNS records, B.14–B.17, C.10/D.12 rollback walks,
  C.11/D.13 teardown, § E.** Nothing in this advance touches them.

### 4.3 The census box — pasted block, not a checked-in script

Mod 130 recorded the probe census verbatim and left the form to me. It lands as a
**pasted Python block inside the B.10 box**, keyed on `VIOLATIONS 0` and exit 0,
with `CONTAINERS` as a corroborating census and **deliberately not a hard number**
— hard-coding `80` is precisely the mistake `N ≠ 2` avoided and goes wrong the
moment a seed gains an env or a replica.

Two notes lifted with it, because both were bought with real time: the HCL arm is
a **line-oriented block walk**, not one regex per name (a first attempt reported
four false `FORBIDDEN`s per `main.tf` by matching the file's first `healthCheck`
for every name — a checker that reports violations where none exist is the mirror
of this advance's recurring defect); and `judge`'s `forbidden` **and** `not core`
arms are both checked, so a probe appearing on something new and unclassified is
caught rather than only the three shapes known today.

**Why a block and not `test_projects/probe_census.py`.** A file is more runnable,
and I considered it. Against: it sits one directory above both seed trees, which
is the edge of my territory; it becomes a **seventh artifact** to keep aligned, on
the one axis (`test_projects/`) that no test reaches; and mod 132 is about to
teach `linkcheck` to walk this directory. A block inside the box it serves cannot
drift away from that box. Raised as Q3 in case sarge wants the file.

### 4.4 The two container-wedging hazards, as instructions

Added as a **numbered how-to-wedge block** in B.10 and cross-referenced from
C.9/D.6 — not as footnotes, because both cost mod 129 real time and both produce
a result that *looks* like an answer:

1. **`kill -STOP 1` inside a container wedges nothing.** PID 1 in a PID namespace
   is immune to `SIGSTOP` from inside it. Mod 129's first attempt was a silent
   no-op and the probe kept reporting green — which would either condemn a correct
   probe or record a pass from a wedge that never happened. **Wedge from the host,
   against `docker inspect --format '{{.State.Pid}}'`**, and `SIGCONT` afterwards.
2. **After any source edit, `./bin/docex build` before probing.** `envinfra up dev`
   leaves the host `dist/` stale, so the stack runs **pre-mod** entrypoints and the
   probe answers "no tick file" — indistinguishable from the absent-tick arm working
   correctly. This is the dev model behaving as designed (source arrives by bind
   mount; `dist/` is refreshed by `build`), which is exactly why it is a trap and
   not a bug. Order: `up` → `build` → restart.

### 4.5 The traefik question, answered empirically on the fixed walk

A **new box in C.9**, and the one place this advance leaves a genuine unknown.
`cicl.md` rule 33 now states that nothing on fixed reroutes traffic away from an
unhealthy container and that traefik's *passive* behavior is **unverified — do not
rely on it**. The fixed walk can settle it for the price of two commands:

1. Wedge `api-web`'s probe per § 4.4 (host-side, against `{{.State.Pid}}`).
2. Poll `docker inspect --format '{{.State.Health.Status}}'` until `unhealthy`
   (three failed 30s intervals — allow ~2 minutes).
3. `curl` the public URL and **record whether traffic still arrives.**
4. `SIGCONT`, confirm the status returns to `healthy`.

**Record the observation either way**, in the walk log, as a fact about the
traefik version in use rather than a doctrine claim. A walk that answers it
converts a doctrinal hedge into evidence; a walk that skips it leaves the hedge
exactly as strong as it is now, which is the honest fallback. The box says
explicitly that **neither outcome is a failure of the cut** — this is data
collection, not a gate — so that a walker under time pressure does not read a
"traffic still arrives" result as a blocker.

### 4.6 Keying on output, not on restated configuration

`test_projects.md`'s own lesson, applied to every box I touched:

- B.9 keys on `docex check`'s `contracts_exist` line and its **named** failure
  message, not on a list of expected filenames.
- B.10's census keys on `VIOLATIONS 0`; the probe boxes key on
  `{{.State.Health.Status}}` / `describe_tasks`' `healthStatus`.
- C.8/D.10 key on the gate's own printed line.
- Where a box does restate configuration (B.7.1's carve-out, the tick paths), it
  is stating a **rule** that only changes when doctrine changes, not a count or a
  pair of names that changes when `infra.yml` moves.

## 5. `upgrades/upgrade_1.7.0.md` — extended, not replaced

1.7.0 is untagged and unreleased, so both advances ship in one guide and one
`cicl_version`. The guide's own conventions are mirrored: the numbered change
table, the "what does not move" list, ordered project steps with the repin first,
the cause→expected-difference table on recompile, and a numbered Verification
section.

### 5.1 Rulings stated outright rather than left inferred

- **`cicl_version` stays `"3"`.** Generation 3 was introduced by advance 005 and
  never released, so `surfaces:` folds into it; a `"4"` bump would manufacture a
  **second rollback-unavailable boundary inside one cut**. Said in the summary, not
  buried — a reader who has to infer this will guess wrong, and guessing `"4"`
  produces a project that does not compile against a released `docex`.
- The **six breaking edits** a project must make, as their own steps: declare
  `surfaces:` on every provider; rename every contract to four segments; write
  `health.sh`; move `health_check_path` — drop it from every non-`web` core service
  and add it to every `web`-network one; drop `port` from core services nothing
  addresses directly; delete every `/health/<codebase>/<service>` route; and remove
  liveness assertions from staging tests.

### 5.2 Structure

Steps **1–6 are untouched.** The new work inserts as steps **7–11** (surfaces,
contract renames, `health.sh`, `health_check_path`/`port`, route + stage-test
deletions), pushing the existing four down to **12–15** (`cicl_version` bump,
recompile-and-diff, redeploy, ⚠ telemetry queries). Two internal anchors
referencing step 8 are repointed. This keeps the guide's load-bearing ordering
intact — **repin first, `cicl_version` last** — which inserting at the end would
have broken.

Three corrections to existing text, all of them things a downstream reader would
act on:

- **"What does not move" loses `contract path`.** Contract paths change on every
  provider. Leaving that word in place is item 5 of § 1 and is the single most
  expensive falsehood in the file.
- "What does not move" **gains** what genuinely does not: `/service`, the `web`
  edge's `GET /health` and its `{version}` body, `health_check_path` on
  `web`-network services, and the ALB target-group probe.
- The § *Doctrine / behavior notes* bullet documenting the fan-out path spelling is
  replaced by its retirement.

### 5.3 Recompile table — new causes

| Cause | Expected difference |
| --- | --- |
| The command probe | Every core-service block's probe becomes `["CMD","./health.sh","<svc>"]` — a compose `healthcheck:` on fixed, a container `healthCheck` on elastic. The `curl -f http://localhost:$PORT$PATH` form **disappears**. `startPeriod: 10` appears on elastic and has **no** fixed counterpart. |
| `health_check_path` off non-`web` | Those services' fixed `healthcheck:` blocks lose their path-derived form (they get the command probe from `defaults` instead). They never had target groups, so nothing ALB-side moves. |
| Contract renames | **Nothing.** Contracts are not compiled output — they live in `infra/contracts/` and never appear in `infra/output/`. Said explicitly, so a reader does not go looking for a diff that cannot exist. |

### 5.4 Verification — the grep that is booked twice

Booked by mod 126 *and* mod 130, so it is stated as a requirement:

> **Grep for surviving three-segment contract filenames.** `ls infra/contracts/`
> and confirm no `<codebase>.<service>.<format>.<ext>` name remains beside its
> four-segment replacement. **An existence-only check is blind to this** — a
> leftover `api.web.openapi.yml` sitting next to a correct
> `api.web.rest.openapi.yml` satisfies every "the contract exists" assertion. The
> thing that catches it is **`_gate_contracts`' orphan arm**, which fails on a
> contract file matching no declared surface; the gate is named here so an
> operator knows what is protecting them and what message to expect.

Plus: zero `health_check_path` on any non-`web` core service; zero
`/health/<codebase>/<service>` routes in source; `docex check` green with
`codebase_scripts` and `contracts_exist` passing; every core service's container
probe reporting healthy on both foundations; and **one loop-owning service
observed failing with a stale tick** — the same red-before-green rule advance 005
made standing, applied to the thing a downstream project is most likely to get
subtly wrong (a tick written by a liveness *thread* rather than by the loop).

## 6. Root `CHANGELOG.md`

Mods 125–130 each appended `[Unreleased]` entries as the mod process requires, so
`### Changed` now interleaves advance 006's four entries with advance 005's four
and a reader cannot tell which release-facing change is which.

**Reorganized by subject, not by advance number.** A reader of the 1.7.0 release
does not know what an advance is; they want to find the change that broke their
`infra.yml`. `#### ` groupings inside `### Changed`:

1. **Vocabulary — codebases and core services**
2. **One relation: `uses`**
3. **`role: clock` replaces `role: scheduler`**
4. **Surfaces replace role-derived contracts**
5. **Health leaves HTTP**
6. **The smoke seeds move onto both models**

The two intro paragraphs already name the advances, so nothing is lost. `### Fixed`
and `### Added` get the same treatment where they carry more than a few entries.
This is a **re-ordering plus headers**, not a rewrite — the entries' prose is what
each mod wrote and stays as written.

Two corrections inside the prose, both instances of the traefik claim: *"on fixed,
traefik takes target health from the container probe"* and *"traefik dropping a
not-yet-ready container from its pool is the behavior you want"*. Replaced with
rule 33's actual reasoning — **ECS kills and replaces; Docker only reports** —
which is the real justification for `startPeriod` being elastic-only and does not
depend on the unverified traefik behavior at all. The mechanism argument survives
intact; only the false corroboration goes.

## 7. Explicitly out of scope

- **Doctrine prose.** Nothing under `doctrine/` is edited. Findings are raised.
- **`linkcheck.py`** — mod 132, which lands after this mod precisely so it
  validates the checklist this mod rewrote.
- **The seeds' trees** — mods 129/130, committed. If this mod finds a defect in
  them it reports rather than fixes.
- **`docex/plans/advances/007_small_edges/*`** — three briefs this advance filed;
  they are future work and are correct as filed.

---

## Rulings at design review

All four questions ruled; recorded here so they are not re-litigated.

1. **Q1 — `docex_process.md` is the authoritative home. Approved**, with the
   reasoning preferred over the brief's original instruction: fix the live wrong
   instruction at step 3.1, state the rules beside it, point from
   `test_projects.md`.
2. **Q2 — both halves approved.** Fix the inverted topology clause in
   `reverse_proxy.md`; the current shape is a **per-project traefik at the project
   tier** plus **dedicated preinfra traefiks** for the registry and the
   observability backend. Book the missing `ec2_traefik` coverage as its own brief
   in `007_small_edges` rather than growing this mod.
3. **Q3 — pasted block in B.10. Approved**, on two standing conditions: keyed on
   what the command **prints** (`VIOLATIONS 0`, exit 0), and the container count is
   **not** a hard number.
4. **Q4 — four segments is correct.** The brief's § 4 list enumerated the *stale
   claims being replaced*; "three-segment paths" was the thing being deleted, not
   the target.
5. **D.11's fan-out box — replace that box only**, as proposed. It fell outside the
   brief's enumerated list because that list was built from recon rather than from
   reading the file. Its reconcile box and `N = 2` stay.
6. **The CHANGELOG's two traefik sites (l. 134, l. 155) are inside
   `[Unreleased]`** — this cut's own entries, written by mods 125–130, not history.
   Corrected. Mod 130's "history is not revised" ruling still stands and simply
   does not reach them; any instance found in a **released** section is left alone
   and noted, because that is what that version shipped. Checked: the only other
   `traefik` hit before `## [1.6.1]` is l. 450, a mod-121 entry about one-segment
   identity in `ec2_traefik.md`, which makes no behavioral claim. Left.

**What the three excerpt findings amount to.** This advance produced **three
independent defects in `doctrine_excerpts/`** — a dead prose anchor
(`service_discovery.md`), a missing shim (`codebase.md`), and an inverted topology
claim (`reverse_proxy.md`) — in the one artifact `docex_process.md` describes as
having no automated consumer. Two of the three are invisible to any grep keyed on
this advance's vocabulary, and the third is unrelated to this advance entirely.
That row has earned itself three times over in a single advance, and the evidence
is recorded with the verdict.

---

## Design questions

### Q1 — where the pytest-invocation hazards live *(I deviated; please confirm)*

**The brief puts them in `test_projects.md`. I put the authoritative statement in
`docex_process.md` and left a pointer in `test_projects.md`.** The reason is that
`docex_process.md` step 3.1 currently reads *"End-to-end integration tests. These
are automated and hit with `pytest -m integration`"* — **that is the trap itself,
written into the doc a fresh agent reads before touching `docex`.** It omits
`python -m`, so the bare binary cannot collect the suite and reports 17 deselected
while running nothing; and it omits that `-m integration` must run **alone**, and
that the default suite is `pytest tests` rather than `pytest tests/unit`, which is
where mod 128 found twelve tests red behind a green report.

Documenting the hazard in `test_projects.md` while leaving the wrong invocation
live in `docex_process.md` would be the exact drift class this mod exists to
close: the correction and the defect in two files, with nothing connecting them.
So `docex_process.md` gets the four-line corrected invocation block and
`test_projects.md` gets a one-line pointer. **If you want them stated in full in
`test_projects.md` as well I will duplicate them, but I would rather not have two
copies of an invocation.**

### Q2 — `doctrine_excerpts/reverse_proxy.md` carries an unrelated falsehood

It says: *"Exactly one traefik instance per host machine — **not** one per
project."* Current doctrine is the opposite — a **per-project** traefik named
`${project_dns_label}-traefik` on the `docex-ingress` network, behind a host-wide
HAProxy `web_demux`. `PRE_CUT_CHECKLIST.md` A.3.1 and `masterplan.md` both
describe the per-project shape, and this mod is writing more boxes that depend on
it. The same excerpt also predates `reverse_proxy: ec2_traefik` and presents the
ALB as elastic's only answer.

Neither is this advance's subject, and it is in my territory. **My inclination:
fix the per-host claim in this mod** — it is verifiable, it is one clause, and it
directly contradicts sentences this same mod is writing — and **raise the
`ec2_traefik` gap for a later mod**, because covering it means writing new prose
about a foundation option rather than sweeping a stale one.

**Ruling requested on both halves.** If you would rather this mod touch nothing
off-subject in that file, I will book both and change nothing there.

### Q3 — the census: block or checked-in script?

§ 4.3 argues for a pasted block in the B.10 box (stays in territory, no seventh
artifact, cannot drift from the box it serves). The alternative,
`test_projects/probe_census.py`, is more runnable and is what a walker under time
pressure would prefer. **I chose the block; say the word and it becomes a file.**

### Q4 — a note, not a question: the brief says "three-segment paths" in § 4

The brief's § 4 describes B.9 as "(provider set, format-from-role, three-segment
paths)" while its § 1 and the design record both say **four**. I have implemented
**four-segment** (`api.web.rest.openapi.yml`), matching `contracts.md`, mod 126's
parser, and both seeds' three shipped contract files. Flagged only so you know I
read it as a slip rather than a ruling.

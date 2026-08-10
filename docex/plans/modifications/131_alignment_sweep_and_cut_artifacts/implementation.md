# Mod 131 — Implementation

Executes the design at [`overview.md`](./overview.md). **Read § 1 of that file
first** — it is the census of what is currently false, and every step below traces
to one of its fourteen rows.

**This mod edits documentation and comments only.** No `src/`, no emit behavior, no
seed tree. Therefore:

> **The test suite is a control, not a signal.** `python -m pytest tests` must
> report **1174 passed, 18 deselected** at the end — *unchanged*. A different count
> means something outside this mod's territory moved and is a **finding to report**,
> not a success. Do not "fix" a test.

**Never invoke bare `pytest`.** It cannot collect this suite and reports 17
deselected while running nothing. Always `python -m pytest`.

All paths are relative to the repo root `/home/ubuntu/.claude/jean_baudrillard`
unless prefixed `docex/`.

**Territory — do not edit anything else.**

| In | Out |
| --- | --- |
| `docex/plans/core/{masterplan,compiler,release_flow,test_projects,docex_process}.md` | anything under `doctrine/` — **raise, never edit** |
| `docex/doctrine_excerpts/*.md` + `index.yml` | `docex/src/**`, `docex/tests/**` |
| `docex/test_projects/PRE_CUT_CHECKLIST.md` | `docex/test_projects/{fixed,elastic}/**` (mods 129–130, committed) |
| `docex/tables/roles/web.yml` — **comments only** | any other file under `docex/tables/` |
| `upgrades/upgrade_1.7.0.md` | `linkcheck.py` (mod 132) |
| `CHANGELOG.md` (root) | released `CHANGELOG.md` sections — see step 40 |
| one new file: `docex/plans/advances/007_small_edges/reverse_proxy_excerpt_elastic_gap.md` | |

**One writing rule that governs every step.** Where a statement can be keyed on
**what a tool prints**, key it there rather than on a restated configuration. A box
or a doc line that restates config rots with no signal; one that compares output
against an expectation announces its own staleness the first time it runs.

---

# Part A — `docex/plans/core/masterplan.md`

## Step 1 — the Filesystem Surface contract path

In the **Read:** list, replace:

```
- `infra/contracts/<codebase>.<service>.<fmt>.yml` — per-provider contracts (validated during `check`)
```

with:

```
- `infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>` — one contract per declared surface (validated during `check`)
```

## Step 2 — rewrite § *The contract and health gates* whole

This is the single largest alignment gap in the repo. The current block runs from
the heading `### The contract and health gates` to the paragraph beginning
`Mod 101 wrote these;` inclusive. **Replace the whole block** with the text below.

Rename the heading to `### The contract and shim gates` — the health gates in the
plural no longer exist.

```md
### The contract and shim gates

Three of those gates read a project's declared boundaries and its codebase layout.
Their criteria are worth stating here because they are easy to get subtly wrong,
and because an earlier generation of them got several things wrong for months. The
rule of record is [`contracts.md`](../../../doctrine/infrastructure/contracts.md)
and [`healthchecks.md`](../../../doctrine/infrastructure/healthchecks.md); this is
how `pipeline/check.py` implements it.

- **Provider set = the core services that declare `surfaces:`.** Nothing else.
  Declaring a surface is what makes a core service a provider, and a `uses` edge
  onto one that declares none is a **compile error** (rule 31) rather than a
  silently-missing contract. The previous two-armed union —
  `(core-targeted uses entries) ∪ (web-network core services)` — is gone, and its
  second arm was **wrong rather than merely redundant**: it forced a contract onto
  every publicly-reachable core service, including a `frontend.web` that serves a
  browser and describes no boundary at all.
- **Format follows the surface's `api_styles`, and the check is derived rather
  than tabulated** — `len(surface.formats()) == 1` over
  `model.py::API_STYLE_FORMATS`. `[rest, stream, webhook]` resolves to one format
  and passes; `[rest, rpc]` fails rule 29 telling the author to split. There is
  **no fallback**: the retired `_FALLBACK_CONTRACT_FORMAT = "openapi"` meant an
  unrecognized role silently received the wrong format, and an unrecognized
  `api_style` is now `rule_29_unknown_api_style` at *compile* time — so by the
  time the gate runs there is nothing left to guess at.
- **Contract paths are parsed right-anchored on four segments** —
  `<codebase>.<service>.<surface>.<format>.<ext>` — and the extension is checked
  against the **resolved format** rather than against a list of accepted suffixes,
  because `contracts.md § Standards` fixes exactly one extension per format. So
  `api.web.rest.openapi.yml` resolves while both `api.web.openapi.yml` (the
  retired three-segment form) and `api.web.rest.openapi.yaml` do not. The path
  stays service-keyed unconditionally: one codebase may run two HTTP core services
  and both are genuine boundaries.
- **The gate has an orphan arm, and it is the arm that earns its keep on an
  upgrade.** A contract file matching no declared surface *fails*, naming the
  four-segment form and saying to rename or delete. This is the only thing that
  can see a leftover `api.web.openapi.yml` sitting **beside** a correct
  `api.web.rest.openapi.yml` — an existence-only check is structurally blind to
  it, because the file it wants is also present.
- **One health assertion survives, narrowed to a contract-content check.** Where a
  `web`-network core service *also* declares an `openapi` surface, one of its
  openapi contracts declares a `GET` on that core service's **declared
  `health_check_path`** — read from the field, never hardcoded to `/health`, so a
  project declaring `/healthz` conforms. *Any one* openapi surface satisfies it:
  requiring the path in **every** surface would force a `rest_admin` contract to
  document a route outside its own boundary, and a contract that describes
  something it does not own is a worse defect than one omitting something
  documented next door. Keyed on `web`-network membership rather than role, for
  rule 33's reason — the field is what a reverse proxy reads, and a `role: web`
  core service off the `web` network has nothing in front of it.
- **`health.sh` is the fourth codebase shim gate**, required unconditionally
  alongside `build.sh` and `test.sh`; `migrate.sh` stays conditional on schema
  ownership. One file per codebase like the others, but invoked **per core
  service** as `./health.sh <service>` — the compiler emits the argv, so the shim
  never guesses which core service it is running in.

**Two gates were deleted rather than repaired, and the distinction matters.**

- `_gate_health_endpoints` went **whole**: the `/health/<codebase>/<service>`
  fan-out, the one-hop recursion rule that existed solely to stop the fan-out
  looping on the legal `web ↔ worker` cycle, and the probeability arm that
  demanded both `port` and `health_check_path` on every core `uses` target — which
  rules 32 and 33 now respectively make conditional and forbid.
- `_gate_healthcheck_tooling` — the `curl`-in-the-image gate — was **deleted, not
  narrowed.** `infrastructure.md § Codebase Containers` no longer mandates `curl`;
  it mandates that the image can run `./health.sh <service>` and leaves the tool
  to the project. A gate enforcing a requirement the rule of record has withdrawn
  is worse than no gate, because it reads as a live constraint.

The roster is therefore **nine** gates, not ten.

**History, because it explains how a real defect hid for months.** Mod 101 wrote
the two-armed union and the fan-out; before it, `_infer_contract_format` had
returned `openapi` **unconditionally since the day it was written** — its asyncapi
branch looked a *codebase* name up in `backing_services`, which `model.py` forbids
from overlapping — so the async-contract path had never once executed, and the
fan-out flaw went unnoticed behind it. That is why format stayed keyed on `role`
for as long as it did: nothing had ever exercised the branch that would have shown
the keying was wrong. Retained as the record of a defect class, not as live
description.
```

## Step 3 — leave § *The orchestrator liveness/version gate* alone

Mod 128 wrote it; it is current. **Do not touch it.** Re-editing a current section
during a sweep is how a sweep introduces a defect.

---

# Part B — `docex/plans/core/compiler.md`

Mod 125 brought § Validation current and mod 127 wrote § *The container probe*.
**Neither is redone.** Only the following move.

## Step 4 — the traefik claim in § *The container probe*

Locate (≈ l. 488):

```
`health_check_path` survives as **one** translation only: `elastic` → `target_group`, the
ALB's own HTTP probe. It has no fixed translation — traefik takes target health from the
container probe — but stays *declared* on the `web` engine so rule 4 accepts it in a fixed
project's `infra.yml`.
```

Replace the em-dashed clause. The new text must state rule 33's actual position and
**must not restate the traefik claim in any form**:

```
`health_check_path` survives as **one** translation only: `elastic` → `target_group`, the
ALB's own HTTP probe. On fixed it has **no consumer at all** — the compiler emits no
health-aware load-balancer labels, only `loadbalancer.server.port`, so the project traefik
does no probing of its own; whether it *passively* withholds routing from a container Docker
has marked unhealthy is a property of that tool which nothing here verifies
([rule 33](../../../doctrine/infrastructure/cicl.md#validation-rules)). The field stays
*declared* on the `web` engine so rule 4 accepts it in a fixed project's `infra.yml`.
On fixed the **container probe** has exactly two consumers and neither reroutes traffic:
Docker, which reports a status and restarts nothing of its own accord, and
`docex stagetest`, which reads that status and fails a release on it.
```

## Step 5 — rule 7's one-directional example

Locate in § Validation (≈ l. 594) the parenthetical:

```
(the walk is over refs, so an edge never obliges a ref — `api.web` uses `api.worker` for the contract and health fan-out while holding no ref to it)
```

**This example is now false twice over**: there is no fan-out, and `api.web` *does*
hold refs to `api.worker` (`WORKER_HOST` / `WORKER_PORT`). Replace with the live
case, and say why this example was chosen:

```
(the walk is over refs, so an edge never obliges a ref — `api.clock` uses `api.worker` and holds **no** ref to it, because the edge is the `jobs` table rather than the mesh, so there is no host to reference. Deliberately the same pair rule 32 is edge-scoped for: `api.worker` has two consumers reaching it two different ways, and the ref-holding one is the one that obliges a `port`. The two rules illustrate each other on one edge pair rather than needing two invented examples)
```

## Step 6 — `uses` no longer drives contracts

Locate (≈ l. 603): `` - `uses` drives CI (contracts, health fan-out, rule 7), the elastic release's Service Connect reconcile, one *view* (`describe`), and **one emission**: ``

Replace the parenthetical list:

```
- `uses` drives **validation** (rules 7, 25, 31, 32), the elastic release's Service Connect reconcile, one *view* (`describe`), and **one emission**: the per-codebase exec block's readiness gate. Contracts are driven by [`surfaces:`](../../../doctrine/infrastructure/cicl.md#surfaces) and no longer by `uses` at all; the health fan-out it once drove is deleted. Nothing else in the compiled output reads it, and …
```

Keep the remainder of that bullet (`and that it *cannot* be read is structural…`)
verbatim.

## Step 7 — the `core_uses()` read-site list

Locate (≈ l. 604): `` Rule 7, `check.py`'s contract / health gates, and the compiler all read through it ``

**`check.py` no longer reads `core_uses` or `backing_uses` at all** — verify with
the grep in step 47 before editing. Replace with:

```
Rules 7, 31 and 32 and the compiler all read through it — "a second parser would be a second place for that rule to drift". `check.py` is **no longer** among the readers: its contract gate derives the provider set from `surfaces:`, so the one-parser argument now earns its keep entirely inside validation.
```

## Step 8 — tense mod 101's cron clause as history

Locate (≈ l. 602): `Mod 101 added a clause forbidding the retired cron role as a
target — it exposed no boundary to use and was exempt from the health fan-out and
contract requirement that `uses` drives — and mod 116 deleted that clause with the
role`.

Change `that `uses` drives` → `that `uses` drove at the time`. One clause; it stops
a historical sentence reading as a live fact.

## Step 9 — one new `Where to look` row

In § *Where to look when changing things*, add after the container-probe row:

```
| How the provider set and a contract's format are derived | `src/docex/pipeline/check.py::_gate_contracts` (provider set = core services declaring `surfaces:`) + `src/docex/cicl/model.py::API_STYLE_FORMATS` (style → format). The table lives on the **model** because two consumers read it — rule 29's validator and this gate — and a literal-equality test pins it against the doctrine table |
```

## Step 10 — sweep for anything mods 128–130 made stale

Run, and repair only genuine falsehoods (do not rewrite current prose):

```sh
cd docex && grep -n "fan.out\|fanout\|/health/\|health_check_path\|_gate_health\|healthcheck_tooling\|_CONTRACT_FORMAT_BY_ROLE\|_FALLBACK_CONTRACT" plans/core/compiler.md
```

Expected after steps 4–9: hits only where the text is explicitly historical or is
describing the current `health_check_path` translation. **Report any hit you leave
in place and why.**

---

# Part C — `docex/plans/core/release_flow.md`

## Step 11 — the version-comparison instrument

In § *Common failure modes*, the `Dry-run on elastic shows an unexpectedly empty
diff` row ends: `confirm target version is actually older than current via
`/health` on the deployed env`.

Not false, but no longer the truthful instrument — the doctrine says the
orchestrator wins when it and a self-report disagree. Replace that cell's fix text:

```
confirm the target version is actually older than what is deployed by reading it from the **orchestrator** (`pipeline/orchestrator_health.py`, the read `stagetest` makes: task-definition revision on elastic, `.Config.Image` on fixed). A `web` edge's `GET /health` still reports a version and is the weaker of the two — a stale container will happily falsify it, which is why [`healthchecks.md § Version`](../../../doctrine/infrastructure/healthchecks.md#version) makes the orchestrator authoritative
```

## Step 12 — confirm nothing else moved, and record that

```sh
cd docex && grep -n "fan.out\|/health\|contract\|surface" plans/core/release_flow.md
```

Two live hits are expected: l. ≈142 (mod 128's, current — **leave**) and the row
just edited. Everything else in the file is about rollback preconditions, worktrees
and AWS adapters and is untouched by this advance. **State in your report that this
file needed one edit** — a sweep that reports "swept" without saying what it found
is indistinguishable from one that did not run.

---

# Part D — `docex/plans/core/test_projects.md`

## Step 13 — § Shape's three core-service bullets

Replace the three bullets (l. ≈17–19) with text true of the seeds as they now
stand. Verify each claim against
`docex/test_projects/fixed/infra/infra.yml` and
`docex/test_projects/fixed/core/api/health.sh` before writing — **read, do not
assume**:

- **`api.web`** (`role: web`) — `POST /pings`, `GET /health`, and
  `/diagnostics/{probe,events}` for the two project-local container backings.
  Declares **one** surface, `rest` (`api_styles: [rest]`), giving
  `api.web.rest.openapi.yml`. `uses: [appdb, probe, events, api.worker]`, and holds
  five-segment magic refs to the worker (`WORKER_HOST`/`WORKER_PORT`) — which is
  what makes that edge *directly addressed* under rule 32's positive arm.
- **`api.worker`** (`role: worker`, `replicas: 2`) — polls the `pings` table, drains
  the `jobs` queue, and serves `POST /drain` so `api.web` can ask it to drain in the
  worker's own process (the perform side of the queue belongs to it). Declares
  **two** surfaces of **one** format — `rpc` and `events`, both `asyncapi` —
  distinguished by unrelated consumer sets. Its liveness is a **tick file** its poll
  loop touches, read by `./health.sh worker`; it runs no HTTP server for health
  purposes.
- **`api.clock`** (`role: clock`) — the long-running singleton owning the cron loop.
  Declares `schedules:` and `uses: [appdb, api.worker]`, holds **no** magic ref, and
  declares **no `port`, no `health_check_path`, and no `surfaces`**: nothing
  addresses it, nothing may `uses` it, and it binds **no application socket at all**.
  Its liveness is `./health.sh clock` over the cron loop's tick file.

Keep the existing `prune_pings` / `heartbeat` sentences and the "together these
exercise the core-service expansion" paragraph.

**Add one sentence** after the worker bullet, because it is the only exercise in the
repo of this shape:

```md
`api.worker`'s two surfaces are the repo's only instance of **one format, two
unrelated consumer sets** — a reader who assumes one surface per format will
misread it. `api.web` calls the `rpc` boundary synchronously and waits for a count;
the queues are produced onto by `api.web` and `api.clock` and consumed here,
asynchronously and with no reply.
```

## Step 14 — the 10s / 30s pair and its split

The paragraph at l. ≈25 says the seeds are the reference implementation "with the
doctrine-fixed 10 s tick / 30 s staleness thresholds". Still true but no longer
where a reader will look. Extend it:

```md
Both numbers are doctrine-fixed and **they now live in two files, deliberately**:
the ≤10 s tick **cadence** in `src/entrypoints/{worker,clock}.py`, because the loop
is the only thing that can honour it, and the 30 s staleness **threshold** in
`core/api/health.sh`, because the probe is the only thing that judges it. Each file
names the other half, since 30 being three times 10 is what the pair *means* — a
healthy loop misses two consecutive ticks before it is called stale — and neither
number shows that alone.
```

## Step 15 — a pointer to the suite-invocation rules

The lesson section **§ A checklist box should assert against what the tool prints**
already exists and stays. Add a short subsection after it:

```md
### How to run this repo's own suite

Not a property of the seeds, but the place a reader of this file next reaches for.
The invocation rules — and the two ways a wrong one reports success while running
nothing — are stated once, authoritatively, in
[`docex_process.md` § Running the automated tests](./docex_process.md#running-the-automated-tests).
Read them there rather than trusting a remembered command; **both** hazards
produced a number close enough to the truth to be believed.
```

## Step 16 — the `verify_clean.sh` and lifecycle sections

Untouched. Confirm with a read; report if you find a health/contract claim in them.

---

# Part E — `docex/plans/core/docex_process.md`

## Step 17 — fix the live wrong invocation at step 3.1

Currently § *Docex Process* step 3 reads:

```
3. **Run expensive tests** - When mod cycles are complete, run the "expensive" tests. These include:
	1. End-to-end integration tests. These are automated and hit with `pytest -m integration`
```

**That instruction is the trap.** Replace sub-item 1 with a pointer:

```
	1. End-to-end integration tests — see [§ Running the automated tests](#running-the-automated-tests) for the invocation, which is **not** the obvious one.
```

## Step 18 — new § *Running the automated tests*

Add as a new `##` section immediately **after** § *Docex Documentation*'s
*Additional Artifacts* subsection and before § *Versioning & Releasing*. Anchor
must be `#running-the-automated-tests` to match steps 15 and 17.

```md
## Running the automated tests

Two invocations, and **three ways to get a number that looks like an answer and is
not.** All three were paid for during advance 006; none of them fails loudly.

```sh
python -m pytest tests                  # the default suite
python -m pytest tests -m integration   # the integration suite — run ALONE
```

1. **`python -m pytest`, never bare `pytest`.** The bare binary cannot collect this
   suite. It reports **17** deselected instead of 18 and runs nothing — a count near
   enough to the truth to be believed.
2. **The default suite is `tests`, not `tests/unit`.** Sixty-plus fast compile tests
   live under `tests/integration/` carrying **no** marker, so the conventional pair
   `pytest tests/unit` + `pytest tests -m integration` has a sixty-test hole between
   them that is invisible from either side. Mod 128 found twelve tests red behind a
   green report that way. The structural cause is filed at
   [`007_small_edges/misfiled_compile_tests.md`](../advances/007_small_edges/misfiled_compile_tests.md).
3. **`-m integration` must run alone.** Run concurrently with anything else it
   produces five convincing false failures in migrate, up/down and build — they
   contend for real docker state.

The common shape is this advance's own recurring defect arriving in the measurement
apparatus rather than the code: *something that could not have detected the failure
reported success.*
```

*(Note for the implementor: the fenced block above contains a nested ``` fence.
Write the section so the inner `sh` fence is a real fence in the output file — the
outer fence here is only quoting.)*

## Step 19 — the `doctrine_excerpts` verdict for advance 006

In § *Additional Artifacts*, after the paragraph beginning `Applying that criterion
at advance 005 (mod 118):` and its closing sentence, append:

```md
Applying it again at advance 006 (mods 125–131): **`surface` gets no entry**, and
the same answer covers `api_styles`, `health.sh`, and the container probe — stated
together so the next mod does not re-ask it one noun at a time. Three reasons, each
ruling out a different wrong answer. **Nothing is deployed for a surface:** it has
no container, no DNS name, no ARN, and no `[resource]` box in `shape.md` —
`api.worker`'s two surfaces are two documents in the repo and one process. **It is
a CICL field**, which this criterion excludes by name; `cicl.md § Surfaces` and
§ Service Fields specify it, and a third hand-maintained restatement would buy
nothing. And **a probe is a property of a resource, not a resource** — the one
sentence it earned went into the existing `core_service.md` entry rather than a new
one. Mods 126, 127 and 128 each concluded independently that they introduced no
resource; mod 128 recorded its row expressly so this verdict could aggregate them.

**How this artifact is swept, and the limit that was found the hard way.** Three
mods of advance 006 grepped all eighteen excerpts for
*health / contract / surface / curl* and got zero hits, and concluded nothing
contradicted the new model. That reasoning is sound for a **changed** claim and
structurally blind to an **omission**: `codebase.md` listed the codebase's shims as
"`build.sh` / `test.sh` / `migrate.sh`" and was wrong by omitting `health.sh` — a
line containing none of the four grep terms, only three filenames. **A grep for the
new thing cannot find a list that lacks it.** So a sweep of this artifact needs a
second pass that reads every entry naming a set — files, stages, roles, fields —
and asks whether the set is still complete. The vocabulary grep cannot answer that
question and will keep returning zero while the omission stands.

**Advance 006 produced three independent defects here, which is what this row is
for.** A dead prose citation in `service_discovery.md` (an anchor the doctrine
rewrite deleted — prose, so `linkcheck` cannot see it); the missing shim in
`codebase.md`; and an **inverted topology claim** in `reverse_proxy.md` ("exactly
one traefik per host machine — not one per project", the opposite of the
project-tier traefik the doctrine now specifies) which was unrelated to the advance
entirely and had simply never been caught. Two of the three are invisible to any
grep keyed on the advance's vocabulary and the third is invisible to a grep keyed on
anything. Three defects in one advance, in the only artifact on this list with no
automated consumer.
```

---

# Part F — `docex/doctrine_excerpts/`

## Step 20 — `service_discovery.md`: repoint the dead prose citation

Replace the closing two lines:

```
Doctrine reference: `infrastructure/shape.md`;
`infrastructure/cicl.md § Resilience covers reachability, not resolvability`.
```

with:

```
Doctrine reference: `infrastructure/shape.md`;
`infrastructure/reasoning/elastic_release_pattern.md` (why application-level
retrying cannot recover from an unresolvable name);
`infrastructure/specifics/release.md § Service Connect Consumer Reconcile` (what a
release does about it).
```

**Verify both targets resolve before writing** — `elastic_release_pattern.md`
exists and carries the reasoning in its preamble; `release.md` carries the literal
heading `### Service Connect Consumer Reconcile`. Change **no other content** in
this file: the deployment-fixes-resolvability prose is correct and is *more*
load-bearing after this advance, because the reconcile's symptom is no longer a
fan-out 503 but silence.

## Step 21 — `codebase.md`: `health.sh` is the fourth shim

Locate: `the `core/<name>/` source folder with `build.sh` / `test.sh` /
`migrate.sh``. Replace with:

```
the `core/<name>/` source folder with `build.sh` / `test.sh` / `health.sh` / `migrate.sh` (`migrate.sh` only where the codebase owns a schema)
```

## Step 22 — `core_service.md`: one clause on the probe

Add as a new paragraph immediately before the closing `Doctrine reference:` line:

```md
Every core service's container carries a health probe the compiler emits on both
foundations — `./health.sh <service>`, a compose `healthcheck:` on fixed and an ECS
container `healthCheck` on elastic. The core service declares nothing for it; the
argv is supplied so one codebase's shim can probe a web edge and a queue consumer
differently. For a core service off the `web` network this probe is its **only**
liveness enforcement: nothing routes to it, so no load balancer and no staging test
can reach it.
```

Do **not** add surface content here — surfaces are an authoring and CI concept and
belong in `cicl.md`.

## Step 23 — `reverse_proxy.md`: the inverted topology claim

Approved at design review. In the **Fixed: Traefik** bullet, replace:

```
Exactly one traefik instance per host machine — *not* one per project.
```

with:

```
One traefik **per project**, at the project tier — brought up by
`docex projinfra up development` and named `${project_dns_label}-traefik` — sitting
behind a single host-wide HAProxy `web_demux` that reads the request domain and
forwards to the right project's traefik over the shared `docex-ingress` network.
(Preinfra services that are not projects — the container registry and the
observability backend — run their own dedicated traefiks.) Per-project rather than
host-wide is what gives blast-radius protection: one project cannot misconfigure
another's routing.
```

Adjust the bullet's trailing sentence if it still argues the host-wide case (the
"one traefik, one cert manager, however many projects" clause) so the paragraph
does not contradict itself. **Do not** add probe or surface content to this file —
it answers "how do requests reach the right container", which the probe does not.

## Step 24 — book the `ec2_traefik` gap rather than writing it

`reverse_proxy.md` also predates `reverse_proxy: ec2_traefik` and presents the ALB
as elastic's only answer. Approved as a **separate brief**, not this mod's work.
Create `docex/plans/advances/007_small_edges/reverse_proxy_excerpt_elastic_gap.md`
(mirroring the shape of its siblings in that folder — read one first, e.g.
`contract_spec_version_ungated.md`):

- **What is wrong:** the excerpt states the ALB as elastic's only reverse proxy;
  CICL's `reverse_proxy:` field accepts `alb` **and** `ec2_traefik`, and `docex`
  implements both (`emit/hcl.py`'s `dockerLabels` block +
  `templates/ec2_traefik_user_data.sh.j2`).
- **Why it was not fixed in mod 131:** covering it means writing *new* prose about
  a foundation option, not sweeping a stale claim; mod 131's territory was an
  alignment sweep and the operator ruled it out of scope at design review.
- **Why it matters:** `docex why reverse_proxy` is what an operator asks when
  choosing, and it currently cannot surface the choice.
- **The standing lesson:** this is the third `doctrine_excerpts/` defect of advance
  006 and the second one no vocabulary grep could find. Cross-reference
  `docex_process.md § Additional Artifacts`.

## Step 25 — `index.yml`: no change, and prove it

`surface` earns **no** entry (step 19). Make **no edit** to `index.yml`. Confirm
with a read that all twenty existing keys still resolve to files that exist:

```sh
cd docex && python -c "
import pathlib, yaml
idx = yaml.safe_load(open('doctrine_excerpts/index.yml'))
missing = [k for k, v in idx.items() if not pathlib.Path('doctrine_excerpts', v).exists()]
extra = sorted(p.name for p in pathlib.Path('doctrine_excerpts').glob('*.md') if p.name not in set(idx.values()))
print('KEYS', len(idx)); print('MISSING', missing); print('UNINDEXED', extra)
"
```

Expect `KEYS 20`, `MISSING []`, `UNINDEXED []`. Any other result is a finding.

## Step 26 — the completeness pass the greps could not do

Per step 19's stated limit, read **every** excerpt and check each entry that names
a **set** (files, stages, roles, fields, foundations) for completeness against
current doctrine. Report findings; **fix only** an omission whose correct value you
can verify from a doctrine file you have read. Anything requiring new prose or a
judgement call is a finding for sarge, not an edit.

---

# Part G — `docex/tables/roles/web.yml` (comments only)

**Change no YAML value, no key, and no structure.** Two comment blocks only. Any
change to the emitted table is out of territory and will show up as churn in the
seeds' compiled output, which this mod must not produce.

## Step 27 — the `startPeriod` justification in `defaults`

Both halves of the current text are wrong. Replace:

```
          # `startPeriod` is elastic-only ON PURPOSE. ECS KILLS a task whose
          # essential container fails its probe and the service replaces it,
          # so a start grace prevents a container being killed before it has
          # written its first tick. Docker only REPORTS `unhealthy` — nothing
          # on fixed acts on it except traefik, which drops the container
          # from its pool, and that is the correct treatment of a container
          # that is not ready yet. A fixed `start_period` would suppress
          # correct behavior rather than prevent a wrong consequence.
```

with:

```
          # `startPeriod` is elastic-only ON PURPOSE, and the reason is a
          # difference between the two orchestrators rather than anything
          # about routing. ECS KILLS a task whose essential container fails
          # its probe and the service replaces it, so a start grace is what
          # prevents a container being killed before it has written its first
          # tick. Docker only REPORTS a status — it restarts nothing of its
          # own accord, and the compiler emits no health-aware traefik labels
          # (only `loadbalancer.server.port`), so on fixed NOTHING reroutes
          # traffic away from an unhealthy container. Per cicl.md rule 33,
          # whether traefik's Docker provider PASSIVELY withholds routing is
          # a property of that tool which this doctrine does not verify: do
          # not rely on it. The fixed probe has exactly two consumers, and
          # neither reroutes: Docker, which reports; and `docex stagetest`,
          # which reads that status and FAILS A RELEASE on it. So there is no
          # wrong consequence for a fixed start grace to prevent — only a
          # `stagetest` gate whose whole job is to notice.
```

## Step 28 — the `fields.health_check_path` comment

It repeats the same false claim ("On fixed, traefik takes target health from the
container healthcheck in `defaults` above"). Replace that clause so the comment
says what rule 33 says — the field has **no fixed consumer at all** — while keeping
the two live reasons it stays declared (rule 4 acceptance, portability) and rule
33's both-foundations requirement. Do not restate the traefik claim.

## Step 29 — confirm the tables are otherwise untouched

```sh
cd docex && git diff --stat tables/
```

Only `tables/roles/web.yml` may appear. Then confirm the emitted output is
unaffected — the strongest available check that these were comments:

```sh
cd docex/test_projects/fixed && git status --porcelain
```

Must be empty (the seeds are committed and this mod does not recompile).

---

# Part H — `docex/test_projects/PRE_CUT_CHECKLIST.md`

**The highest-stakes file in the mod: it gates both walks.** Every box you write
must be keyed on **what a command prints**, not on a restated configuration.

## Step 30 — B.3.1 and the § B preamble

- **B.3.1**: add `surfaces` to the list of fields that live on a core service.
  Where the box lists role-specific fields, note that `health_check_path` is keyed
  on **network membership** (rule 33), not on role — a `role: web` core service off
  the `web` network declares none.
- **§ B preamble note 1** currently says the clock's *"`/health` [is] enforced by
  the container healthcheck"* and that *"no health fan-out and no stage test can
  reach it"*. The clock has **no `/health`**; it has a probe. Rewrite: a clock
  process reading a compiler-delivered `DOCEX_SCHEDULES_YAML`, firing on its own
  cron loop, and having **`./health.sh clock` enforced by the container probe**
  exists only in a walk. Add that being unreachable from outside is now true of
  **every** non-`web` core service, not the clock alone — so the clock is no longer
  a special case, it is the *first* case.

## Step 31 — B.6, Dockerfiles

Append to the box:

```md
Additionally: the image must be able to run **`./health.sh <service>`** for every
core service it hosts — per [`infrastructure.md § Codebase Containers`](../../doctrine/infrastructure/infrastructure.md#codebase-containers),
which states the capability and leaves the tool to the project. **`curl` is no
longer doctrine-mandated.** The seeds carry it for exactly one line — `health.sh`'s
`web` arm curls its own route — and that is a project choice, not conformance. A
box that reads "curl is in the image" as a pass would accept an image that cannot
run its own probe.
```

## Step 32 — B.7, the fourth shim

Extend the box: `health.sh` is the **fourth** codebase shim, required
**unconditionally** (unlike `migrate.sh`, which is conditional on schema
ownership). Then state the asymmetry, because it is the one thing about this shim
that surprises people:

```md
**`health.sh` is the only shim invoked per core service**, as `./health.sh <service>`.
Still one file per codebase like the other three — but a web edge and a queue
consumer of one codebase have genuinely different probes, and argv is cheaper than
four shims. **The compiler emits the argv**, so the script never guesses which core
service it is running in. Confirm the script *branches on `$1`* and that its
fall-through case **fails loudly** — a `*)` arm that exits 0 reports every core
service healthy forever, which is the one outcome worse than a wrong probe.
```

## Step 33 — B.7.1, and the carve-out that must not be got wrong

The box stays **three** shims. Add:

```md
**`health.sh` is the exception, and extending this box to it would be wrong.**
`build.sh` / `test.sh` / `migrate.sh` run in the one-off per-codebase `-exec`
container, whose `environment:` is the **codebase** env surface — which is why a
core-service-scoped key is simply absent in them. `health.sh` runs **inside the
running core-service container**, invoked by the orchestrator's probe, so it sees
that core service's **full** env surface including its core-service-scoped keys.
Stated rather than left inferred because getting it backwards is silent in both
directions: a `health.sh` written to the codebase surface would needlessly avoid
keys it can read, and a `migrate.sh` reading a core-service key gets an empty
string, not an error.
```

## Step 34 — B.9, provider contracts

Replace the box whole:

```md
- [ ] **B.9 Provider contracts present** — **a core service is a provider iff it
  declares `surfaces:`.** Nothing else makes one: the old
  `(core-targeted uses entries) ∪ (web-network core services)` union is gone, and a
  `web`-network core service that declares no surface (a frontend serving a browser)
  correctly needs **no** contract. A `uses` edge onto a core service declaring no
  surface is a **compile error** (rule 31), not a missing contract.

  One contract per surface at
  `infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>` — **four**
  segments, parsed right-anchored. The **format follows the surface's `api_styles`**
  (`rest`/`stream`/`webhook` → `openapi`; `rpc`/`events`/`socket` → `asyncapi`),
  never the provider's `role`, and there is **no fallback**. Exactly one extension
  per format, so `api.web.rest.openapi.yml` resolves while `api.web.openapi.yml` and
  `api.web.rest.openapi.yaml` do not.

  A `clock` carries no contract because it **declares no surface** — not because of
  an exemption. Nothing addresses it and nothing may `uses` it, so it has no
  boundary to describe.

  **Key this box on `docex check`'s own output, not on a filename list.** The
  `contracts_exist` gate reports both directions: a declared surface with no file,
  **and** a file matching no declared surface (the *orphan* arm, whose message names
  the four-segment form and says to rename or delete). The orphan arm is the only
  thing that catches a leftover three-segment contract sitting **beside** its
  correct replacement — an existence check is blind to that, because the file it
  wants is also there. Reaching `check` needs the walk's feature-branch restructure
  ([C.6](#c6-check--containerize) / [D.8](#d8-check--containerize)), so at audit
  time confirm the *shape* here and record the gate's line when you get there.
  Per [`contracts.md`](../../doctrine/infrastructure/contracts.md).
```

## Step 35 — B.10, health

Replace the box whole. Its five parts, the wedging block, and the census block all
live here.

```md
- [ ] **B.10 Health is a command, not an endpoint** — five parts, all per **core
  service**.

  1. **The container probe.** Every core service's container carries
     `["CMD", "./health.sh", "<service>"]` on both foundations — a compose
     `healthcheck:` on fixed, an ECS container `healthCheck` on elastic. It is
     **compiler-emitted from the role tables' `defaults`, not authored**: a queue
     consumer or a cron loop gets a probe while declaring nothing. Cadence is
     doctrine-fixed and uniform; a project-local interval knob is a finding.
     `startPeriod: 10` appears on **elastic only** — ECS kills and replaces a task
     whose essential container fails, Docker only reports.
  2. **`health.sh` exists, branches on argv, and fails loudly on an unknown one.**
     See [B.7](#b7-codebase-scripts).
  3. **A loop-owning core service reports the LOOP's liveness, not the process's.**
     The loop touches a known path each iteration **from inside itself**; the probe
     `stat`s its mtime from a separate process. An **absent** tick file must
     **fail** — a loop that has never completed an iteration has never been alive.
     Checking that the process exists proves nothing (a deadlocked process exists),
     and a separate liveness *thread* proves less than nothing: it answers healthy
     forever while no work moves, converting a loud failure into a silent one.
  4. **The 10 s / 30 s pair, and where each number lives.** ≤10 s tick cadence even
     when idle, 30 s staleness threshold. Both doctrine-fixed — a project-local knob
     for either is a finding. The **cadence** belongs in the entrypoint (the only
     thing that can honour it) and the **threshold** in `health.sh` (the only thing
     that judges it); confirm each file names the other half, because 30 being three
     times 10 is what the pair means. Reference implementation:
     `test_projects/*/core/api/{health.sh,src/entrypoints/{worker,clock}.py}`.
  5. **`GET /health` survives only on the `web` network, and only because a load
     balancer reads it.** It is one role's requirement, not the universal mechanism.
     Rule 33 both arms: **every** `web`-network core service declares
     `health_check_path`, and **no** core service off it does. Where a `web`-network
     core service also declares an `openapi` surface, that contract declares a `GET`
     on its **declared** path (not a hardcoded `/health`) — `docex check`'s
     `contract_health_path` gate, satisfied by *any one* openapi surface.

  **There is no fan-out, and its absence is checked rather than assumed:**

  ```sh
  grep -rn 'health/api/worker\|/health/<codebase>\|_build_health_app' core/ infra/ plans/ | grep -v CHANGELOG
  ```

  Zero hits, except prose that names the deletion in negation. Per
  [`healthchecks.md`](../../doctrine/infrastructure/healthchecks.md).

  ---

  **⚠ How to wedge a probe — read before you try.** Both of these cost mod 129 real
  time, and both produce a result that *looks* like an answer:

  1. **`kill -STOP 1` inside a container wedges nothing.** PID 1 in a PID namespace
     is immune to `SIGSTOP` **from inside that namespace**. The first attempt was a
     silent no-op and the probe kept reporting green — which would either condemn a
     correct probe or record a pass from a wedge that never happened. **Wedge from
     the host, against the real pid:**
     ```bash
     PID=$(docker inspect --format '{{.State.Pid}}' <container>)
     sudo kill -STOP "$PID"      # ... observe ...
     sudo kill -CONT "$PID"      # ALWAYS un-wedge before moving on
     ```
  2. **After any source edit, run `./bin/docex build` before probing.**
     `envinfra up dev` leaves the host `dist/` stale, so the stack runs **pre-mod**
     entrypoints and the probe answers "no tick file" — indistinguishable from the
     absent-tick arm working correctly. This is the dev model behaving as designed
     (source arrives by bind mount; `dist/` is refreshed by `build`), which is
     exactly why it is a trap and not a bug. Order: `up` → `build` → restart.

  ---

  **Probe census over both seeds' compiled artifacts.** Asserts the *negative* half
  of the rule — that the probe lands on exactly the core services and on nothing
  else. **Key this box on what it prints: `VIOLATIONS 0` and exit 0.** The
  `CONTAINERS` line is a corroborating census and is **deliberately not a hard
  number** — hard-coding it is the mistake `N ≠ 2` avoids and goes wrong the moment
  a seed gains an environment or a replica. Run from `docex/`:

  <<<CENSUS_SCRIPT>>>

  Two properties of the script worth preserving if you edit it. The HCL arm is a
  **line-oriented block walk**, not one regex per container name: a first attempt
  used a single regex and reported four false `FORBIDDEN`s per `main.tf`, because
  the pattern matched the file's *first* `healthCheck` for every name — a checker
  that reports violations where none exist is the mirror image of this advance's
  recurring defect and would have condemned a correct emitter. And `judge`'s
  `forbidden` **and** `not core` arms are **both** checked, so a probe appearing on
  something new and unclassified is caught, not only the three shapes known today.
```

**`<<<CENSUS_SCRIPT>>>` placeholder:** substitute the verbatim Python block from
`docex/plans/modifications/130_seed_output_docs_git/overview.md` § *The census
command, verbatim* (l. ≈142–211), indented to sit inside the box as a fenced
` ```python ` block. **Copy it byte-for-byte** — do not retype it and do not
"improve" it.

## Step 36 — line 201's dead markdown link

The old B.10 closed with `Per [`contracts.md § Health Checks`](../../doctrine/infrastructure/contracts.md#health-checks)`
— a dead anchor. Step 35 already repoints it to
`../../doctrine/infrastructure/healthchecks.md`. **Verify no other dead
`contracts.md#` anchor survives in the file:**

```sh
cd docex && grep -n "contracts.md#" test_projects/PRE_CUT_CHECKLIST.md
```

For each hit, confirm the anchor exists in `doctrine/infrastructure/contracts.md`
(`grep -n '^#' `). Repoint any that do not — `healthchecks.md` is the usual target.

## Step 37 — C.8 and D.10, stagetest

Both boxes must record the **new pre-step**, because it fails *earlier* than
anything the box previously described:

- **C.8 (fixed):** `stagetest` now reads every core service's health and version
  from the orchestrator **before it builds the tester image** — `docker inspect`
  **over SSH** to the deployed host, since fixed `stage`/`prod` do not run on the
  operator's machine. A failure here is `DeployedServiceUnhealthy` or
  `OrchestratorStateUnreadable` and happens before any image build; record which.
  Then the tester's own probes: `/health` on the web edge,
  `/diagnostics/{probe,events}` for the project-local backings, the `POST /pings`
  critical path, and the **defer-then-drain round trip** that replaced the deleted
  liveness fan-out test (it asserts **no exact count** — the worker's own poll loop
  legitimately races it).
- **D.10 (elastic):** the same, with ECS `list_tasks` / `describe_tasks` /
  `describe_task_definition` instead of `docker inspect` over SSH.

Note in both: **an empty result set never reads as healthy** — zero core services,
zero RUNNING tasks, and an unreadable container all fail loudly. And **there is no
flag that disables the gate**; if a walk hurts here, the gate is reporting something.

## Step 38 — C.9, fixed release prod

Three edits.

1. **Delete the fan-out box** (currently `https://docex-smoke-fixed.luxrnd.tech/health/api/worker`
   returns 200 …). That route no longer exists; a walker following it records a
   failure against correct code. Replace with:

   ```md
   - [ ] **Every core service's container probe reports healthy.** This is the
     probe's enforcement point and, for the two non-`web` core services, the
     **only** externally-available statement about their liveness:
     ```bash
     for c in api-web api-worker-1 api-worker-2 api-clock; do
       printf '%s\t' "$c"
       docker inspect --format '{{.State.Health.Status}}' "…-prod-$c"
     done
     ```
     All `healthy`. A `starting` that never converges on a worker or the clock means
     the loop has not completed a first iteration — `health.sh` fails an absent tick
     file deliberately. There is no fan-out route to check and no stage test that can
     reach these two; the probe **is** the check.
   - [ ] **The defer → drain round trip is the externally-observable proof of worker
     liveness** — the clock group below already walks it. A wedged worker shows as
     `jobs: 'heartbeat' deferred` with no matching `performed`, plus an `unhealthy`
     probe above.
   ```

2. **Retarget the replica-alias rationale.** The C.9 preamble ends "…sharing one
   network **alias** equal to the unqualified global name (which is what the
   five-segment magic refs resolve to, so a broken alias breaks
   `/health/api/worker` and nothing else would tell you)". Replace the
   parenthetical: a broken alias now breaks `WORKER_HOST` resolution and therefore
   `api.web`'s `POST /drain` call onto the worker's `rpc` surface — an application
   path, which is a *better* canary than the fan-out was because it carries real
   traffic.

3. **Fix the contract path.** The ping box cites
   `infra/contracts/api.web.openapi.yml` → `api.web.rest.openapi.yml`.

## Step 39 — C.9, the new traefik box

Add after the probe box from step 38. This is the one place the advance leaves a
genuine unknown, and the fixed walk can settle it.

```md
> **⚑ Data collection, not a gate.** `cicl.md` rule 33 states that nothing on fixed
> reroutes traffic away from an unhealthy container, and that whether traefik's
> Docker provider **passively** withholds routing is a property of that tool the
> doctrine does not verify. The fixed walk can answer it empirically for the price
> of four commands. **Record the observation either way** — *neither outcome fails
> the cut.* A walk that answers this converts a doctrinal hedge into a fact about
> the traefik version in use; a walk that skips it leaves the hedge exactly as
> strong as it already is, which is the honest fallback.

- [ ] **Does an unhealthy container still receive traffic on fixed?**
  1. Wedge `api-web`'s probe **from the host** per [B.10](#b10-health-is-a-command-not-an-endpoint)'s
     wedging block — `kill -STOP` against `{{.State.Pid}}`. (Inside the container it
     is a no-op.)
  2. Poll until Docker reports it: `docker inspect --format '{{.State.Health.Status}}' …-prod-api-web`
     is `unhealthy`. Three failed 30 s intervals, so allow ~2 minutes.
  3. `curl -sS -o /dev/null -w '%{http_code}\n' https://docex-smoke-fixed.luxrnd.tech/health`
     — **record the code**, and record the traefik image tag from
     `docker inspect --format '{{.Config.Image}}' …-traefik`.
  4. `kill -CONT` the pid; confirm the status returns to `healthy`.

  Write the result into the walk log as an observation about that traefik version,
  **not** as a doctrine claim. If traffic still arrives, rule 33's "do not rely on
  it" is confirmed as necessary. If it does not, the doctrine may later be able to
  state the passive behavior — but only after a second walk reproduces it, since one
  observation of one version is not a doctrine.
```

## Step 40 — D.6, elastic dev sanity

The box currently probes `/health/api/worker` "to isolate a foundation-specific
fan-out failure from an application one". Replace that clause: probe
`https://dev.docex-smoke-elastic.luxrnd.tech/health`, the two-segment
`https://api-web.dev.…/health`, and `/diagnostics/{probe,events}`. Keep the
existing `docex build` ordering warning and add a pointer to B.10's wedging block
(it is the same trap, stated once).

## Step 41 — D.11, the fan-out box only

**Replace only the fan-out box** (`https://docex-smoke-elastic.luxrnd.tech/health/api/worker`
returns 200 …). Its replacement:

```md
- [ ] **Every core service's ECS container health is `HEALTHY`**, and for
  `api-worker` / `api-clock` this is the only externally-available statement about
  their liveness:
  ```bash
  aws ecs list-tasks --cluster docex-smoke-elastic-prod --query 'taskArns[]' --output text \
    | xargs aws ecs describe-tasks --cluster docex-smoke-elastic-prod --tasks \
    --query 'tasks[].{group:group,health:healthStatus,containers:containers[].{n:name,h:healthStatus}}'
  ```
  On elastic the probe is load-bearing in a way it is not on fixed: **ECS kills and
  replaces** a task whose essential container fails, so a wrong probe is a crash
  loop rather than a stale status. `startPeriod: 10` is what keeps a normal start
  from tripping it.
- [ ] **Service Connect still resolves the sibling core service.** The old fan-out
  box proved this incidentally; nothing else does, so assert it directly: `api.web`
  reaching `api.worker`'s `rpc` surface (`POST /drain`) is what the worker's `port`
  makes discoverable. The defer → drain round trip below is the end-to-end proof; a
  resolution failure shows as `api-web` logging a connection error to
  `WORKER_HOST`, **while both services report healthy** — no external signal at all,
  which is why [D.9](#d9-release-stage)'s reconcile box exists.
```

**Do not touch D.11's reconcile box or its `N = 2`**, and do not touch D.9's.
Mod 130 verified the count is still right: `_reconcile_candidates` keys on whether
a consumer's *targets* register; both `api.web` and `api.clock` target
`api.worker`, which keeps its `port` and therefore its Service Connect name. The
clock going unregistered removes it as a *target*, and **nothing targets a clock.**

## Step 42 — D.11, widen the clock probe box

The clock probe box says "**This is the only enforcement a clock gets** — no
fan-out and no stage test can reach it". Still true of the clock, but now true of
**every** non-`web` core service. Widen it to cover `api-worker` as well, and say
that the clock stopped being a special case: it is the *first* case of what is now
the general rule. Do the same for the equivalent box in **C.9**.

## Step 43 — full-file falsehood sweep

```sh
cd docex && grep -n "fan.out\|fanout\|/health/api\|/health/<\|health_check_path\|curl gate\|api.web.openapi\|role.*→.*openapi\|asyncapi" test_projects/PRE_CUT_CHECKLIST.md
```

Every hit must be either (a) rewritten by the steps above, (b) a correct
present-tense statement, or (c) explicitly marked as the deleted model. **Report any
hit you leave and why.**

---

# Part I — `upgrades/upgrade_1.7.0.md`

Extended, not replaced. Mirror the guide's existing conventions exactly: numbered
change table, "what does not move", ordered project steps, cause→expected-difference
table, numbered Verification.

## Step 44 — Summary: two new rows and the `cicl_version` ruling

Add to the change table:

```md
| 5 | **A core service declares its API boundaries as `surfaces:`.** Contract format follows the styles a surface declares, not the provider's `role`; each surface compiles to one contract file, and the filename gains a surface segment. | Every provider's service block; **every contract filename** |
| 6 | **Health leaves HTTP.** The container probe becomes `./health.sh <service>`; `GET /health` survives only where a load balancer reads it; the `/health/<codebase>/<service>` fan-out is deleted; `docex` reads liveness and version from the orchestrator. | Every core service; every codebase's script set; staging tests |
```

Then replace the `cicl_version` sentence with the ruling **stated outright**:

```md
`cicl_version` moves `"2"` → `"3"`. Earlier generations are **rejected, not
shimmed** — a project that has not made these edits does not compile.

> **All six changes ride the same `cicl_version: "3"`.** Changes 5 and 6 are as
> breaking as 1–3, and it would be reasonable to expect a `"4"`. They do not get
> one, on purpose: generation 3 was introduced by this same unreleased cut and has
> never shipped, so folding `surfaces:` into it costs nothing — while a `"4"` would
> manufacture a **second** rollback-unavailable boundary
> ([below](#rollback-is-unavailable-across-the-boundary)) inside one release. Do not
> author `cicl_version: "4"`; it is not a recognized generation and will be
> rejected.
```

Add a third `⚠` callout after the existing scheduler one:

```md
> **⚠ Every contract file is renamed and every codebase gains a `health.sh`.**
> Changes 5 and 6 are not confined to `infra.yml`. Budget: one contract rename per
> provider surface, one new shim script per codebase, and the deletion of every
> fan-out route and every staging-test liveness assertion. Read
> [steps 7–11](#7-declare-surfaces-on-every-provider) before you begin.
```

## Step 45 — "What does not move": the highest-value single correction

The list currently claims: *"**Emitted names.** No container name, hostname, image
ref, **contract path**, `Name` tag, or ECS/task-definition name changes."*

**`contract path` is false and is the most expensive falsehood in the file** — a
project reading it skips a required rename, then hits `_gate_contracts`' orphan arm
with no idea why, or ships a half-renamed contracts directory. Remove the two words
and add a pointer:

```md
- **Emitted *names*.** No container name, hostname, image ref, `Name` tag, or
  ECS/task-definition name changes. (Emitted *output* does change — see
  [step 13](#13-recompile-and-diff-before-deploying) — but nothing is renamed and
  nothing is replaced on that account.) **Contract *paths* are the exception and do
  change** — they gain a surface segment; see [step 8](#8-rename-every-contract-file).
```

Then **add** what genuinely does not move:

```md
- **`/service` and the four Dockerfile stages.** `health.sh` is a new file in an
  existing place, not a new stage or a new working directory.
- **A `web` core service's `GET /health` and its `{version: "x.x.x"}` body.** It
  survives, and staging tests may still assert it against the injected
  `PROJECT_VERSION`. What changed is that it stopped being *universal*.
- **`health_check_path` on `web`-network core services**, and the ALB target-group
  probe it feeds. Same field, same value, same one consumer.
- **Cron expressions, `schedules:`, `schema_owned_by`, `shape_name` tag values.**
  Untouched by changes 5 and 6.
```

## Step 46 — five new steps, inserted as 7–11

Steps **1–6 are untouched.** Insert the five below **after** step 6 and **before**
the `cicl_version` bump, then renumber the existing tail: old 7 → **12**, 8 → **13**,
9 → **14**, 10 → **15**. This preserves the guide's load-bearing ordering — **repin
first, `cicl_version` last** — which appending at the end would have broken.

**Repoint every internal anchor** that referenced the old numbering. Known:
`#8-recompile-and-diff-before-deploying` → `#13-recompile-and-diff-before-deploying`
(appears in the "what does not move" list and in step 45's new text), and any
reference to old step 10 in § *Doctrine / behavior notes*. Grep the file for
`](#` and check each.

### 7. Declare `surfaces:` on every provider

- A core service is a **provider iff it declares `surfaces:`** — a map of named
  boundaries, each with `api_styles:`.
- `api_styles` → format: `rest` / `stream` / `webhook` → **openapi**;
  `rpc` / `events` / `socket` → **asyncapi**. `graphql` and `proto` are **defined
  language that is not implemented** and compile-fail with a named "format not yet
  implemented".
- **One format per surface**, or compile fails (rule 29) telling you to split.
  `[rest, stream, webhook]` is one surface; `[rest, rpc]` is two.
- Name a surface after its primary style unless a core service declares two on the
  same style. Surface names take the codebase/core-service pattern (rule 30) — no
  dots, because a dot would make the four-segment filename parse ambiguous.
- **A `uses` edge onto a core service that declares no surface is a compile error**
  (rule 31). Conversely a core service nothing uses and that describes no boundary
  — a `frontend.web` serving a browser, a `clock` — declares **none**, and needs no
  contract. Include the seeds' worked `infra.yml` fragment: `api.web` with one
  `rest` surface, `api.worker` with `rpc` **and** `events` (two surfaces, one
  format, distinguished by unrelated consumer sets), `api.clock` with none.

### 8. Rename every contract file

`$pr/infra/contracts/<codebase>.<service>.<format>.<ext>` →
`<codebase>.<service>.<surface>.<format>.<ext>`. Worked example:
`api.web.openapi.yml` → `api.web.rest.openapi.yml`.

> **⚠ Move the file; do not copy it.** A leftover three-segment name sitting
> **beside** its four-segment replacement satisfies every "the contract exists"
> check and is caught only by `_gate_contracts`' **orphan** arm. `git mv`, then
> confirm with the grep in [Verification](#verification) item 4.

**Exactly one extension per format** — `openapi`/`asyncapi` → `.yml`. A `.yaml`
that used to be accepted no longer is. And a core service with two surfaces gets
**two** files.

### 9. Write `health.sh`

The **fourth codebase shim**, at `$pr/core/<codebase>/health.sh`, alongside
`build.sh` / `test.sh` / `migrate.sh`. Required for **every** codebase.

- **The exit code is the entire contract.** 0 means this core service is working.
  **Nothing reads stdout** — Docker captures probe output and ECS does not, so it can
  never be a cross-foundation channel.
- **Invoked per core service**, as `./health.sh <service>` — the compiler emits the
  argv. Branch on `$1`, and make the fall-through case **fail loudly**: an arm that
  exits 0 reports every core service healthy forever.
- **A request-cycle service** (`web`) may curl its own route — that is now the
  project's choice inside the shim, not infrastructure the doctrine mandates.
- **A loop-owning service** (`worker`, `clock`) reports the **loop's** liveness: the
  loop touches a tick path each iteration **from inside itself** and the shim `stat`s
  its mtime. An **absent** tick file must **fail**. Do **not** implement this with a
  liveness thread — it answers healthy forever while no work moves.
- Thresholds are doctrine-fixed: ≤**10 s** tick cadence even when idle, **30 s**
  staleness. Cadence in the entrypoint, threshold in the shim.
- Copy the script into the `dev` **and** `prod` Dockerfile stages. Whatever it needs
  (a shell, `curl`, `stat`) is the project's to install — **`curl` is no longer
  doctrine-mandated**, so an image that dropped it must add it back only if its own
  shim uses it.
- Point at the worked implementation: `docex/test_projects/*/core/api/health.sh`.

### 10. Move `health_check_path`; drop decorative `port`s

- **`health_check_path` is keyed on network membership, not role** (rule 33).
  Required on **every** `web`-network core service; **forbidden** on every core
  service off it. Delete it from every `worker` and `clock`. A `role: web` core
  service off the `web` network declares **none**.
- **Rule 28 is retired** and its number tombstoned: it required a `port` beside
  `health_check_path`, and rule 33 now confines that field to `web`-network services
  where rule 15 already requires a port — so the obligation is *redundant*, not
  merely obsolete.
- **Drop `port` from any core service nothing addresses directly** (rule 32). A
  target reached only over a queue or broker needs none. "Directly addressed" means
  **the consumer holds a magic ref to one of the target's provided parts**, and it is
  keyed on the **edge**, not the target — one consumer may call an `rpc` surface
  while another enqueues, and only the first implies a port. `web`-network targets
  are exempt: rule 15 requires a port there regardless.

  > **⚠ On elastic, dropping a `port` also drops a Service Connect name.** A core
  > service registers a resolvable name only where it declares a `port`. That is
  > correct by construction — a target nothing addresses is a target nothing needs
  > to resolve — but if a consumer *does* reach it and you removed the port anyway,
  > the failure is a resolution error **while both services report healthy**. Check
  > your magic refs before deleting a port.

### 11. Delete the fan-out and the staging-test liveness assertions

- **Delete every `GET /health/<codebase>/<service>` route** and the handler behind
  it. The one-hop recursion rule goes with it — it existed solely to stop the
  fan-out looping on the legal `web ↔ worker` cycle.
- **Remove liveness assertions from staging tests.** Staging tests narrow to what
  **requires being outside**: TLS, DNS, reverse-proxy routing, and critical-path
  smoke tests through the real edge. They **may not assert anything about a
  non-`web` core service** — they cannot reach one at all now. A project wanting an
  end-to-end assertion through a worker drives the public edge and observes the
  effect.
- **`docex stagetest` asserts liveness instead, before it builds the tester image**,
  reading the orchestrator (`docker inspect` over SSH on fixed, `describe_tasks` on
  elastic). This is *more* truthful: version comes from the deployment record rather
  than from a self-report a stale container will happily falsify. **When the
  orchestrator and a self-report disagree, the orchestrator wins.**
- If a `web` route was serving *only* the fan-out, delete it. If it also served
  backing-service reachability diagnostics worth keeping, **move them to a path that
  is not `/health/...`** so no reader concludes the fan-out survived under a
  narrower name (the seeds moved theirs to `/diagnostics/{probe,events}`).

## Step 47 — the recompile table, and one thing that will NOT appear

Add to the cause→expected-difference table in what is now step 13:

```md
| The command probe (change 6) | Every core-service block's probe becomes `["CMD", "./health.sh", "<svc>"]` — a compose `healthcheck:` on fixed, a container `healthCheck` on elastic. The `curl -f http://localhost:$PORT$PATH` form **disappears everywhere**. `startPeriod: 10` **appears on elastic only.** The `-exec` block, the elastic `_migrate` task definition, and every `-otelcol` sidecar carry **no** probe — as before. |
| `health_check_path` off non-`web` (change 6) | Those core services lose their path-derived fixed `healthcheck:` and receive the command probe from the role table's `defaults` instead. They never had ALB target groups, so nothing changes ALB-side. `web` services' `target_group` health check is **unchanged**. |
| `surfaces:` (change 5) | **Nothing.** `surfaces:` drives CI and contract-file resolution and reaches **no** emitted artifact. |
```

And add immediately after the table:

```md
> **Contract renames produce no diff in `infra/output/`, and that is expected.**
> Contracts live in `infra/contracts/` and are never compiled into anything. If you
> are looking for the rename in the recompile diff to confirm you did step 8, look
> at `git status` on `infra/contracts/` instead — and at
> [Verification](#verification) item 4, which is the check that actually catches a
> half-done rename.
```

Finally, the guard sentence after the table (`Any change to a container name,
hostname, image ref, contract path, Name tag, or role value is a defect`) —
**remove `contract path` from it** for the same reason as step 45. The guard is
about emitted output, where a contract path never appears; leaving the words in
directly contradicts step 8.

## Step 48 — § *Doctrine / behavior notes*

- **Replace** the bullet documenting the fan-out path spelling (*"The `/health`
  fan-out path is documented as `/health/<codebase>/<service>` …"*) with its
  retirement: the fan-out, the one-hop rule, and the gate that enforced the paths
  are all deleted; `docex` never called the endpoint it mandated, and the only
  runtime consumer was developer-written stage-test code.
- **Add** bullets for: `docex check`'s gate roster going ten → nine (naming the two
  deleted gates, and that the curl gate was **deleted rather than narrowed** because
  `infrastructure.md` withdrew the mandate); the new `contract_health_path` gate and
  its any-one-openapi-surface reading; `codebase_scripts` now requiring `health.sh`;
  and `docex stagetest` failing before the tester build with
  `DeployedServiceUnhealthy` / `OrchestratorStateUnreadable`, with **no flag to
  disable it**.
- **Add** a bullet: the lexicon gains **Surface**; `api_styles` and "probe" get no
  entries, because the lexicon defines concepts rather than CICL fields.

## Step 49 — Verification: renumber and extend

Keep items 1–7 (renumbering their step cross-references per step 46) and add:

```md
8. **No three-segment contract filename survives.** This is the likeliest mistake
   in this upgrade and **an existence-only check cannot see it** — a leftover
   `api.web.openapi.yml` beside a correct `api.web.rest.openapi.yml` satisfies every
   "the contract exists" assertion, because the file the gate wants is also present.
   The thing that catches it is **`_gate_contracts`' orphan arm**, which fails on a
   contract file matching no declared surface and names the four-segment form.
   Confirm by eye first, then let the gate confirm:
   ```sh
   ls infra/contracts/
   # every name must have FOUR dot-separated stem segments before the extension:
   ls infra/contracts/ | awk -F. 'NF!=5 {print "SUSPECT: "$0}'
   ./bin/docex check          # `contracts_exist` must pass
   ```
   `NF != 5` because the extension is the fifth field. A hit is either a leftover
   three-segment file or a surface you failed to declare.
9. **Zero `health_check_path` off the `web` network.** For every core service whose
   `networks:` omits `web`, the field is absent. Rule 33 rejects it, so a miss is a
   loud compile failure rather than a silent one — but check before you compile, so
   you fix them all at once.
10. **Zero fan-out routes.** `grep -rn '/health/' core/` returns only a `web`
    service's own `health_check_path` route. No `<codebase>/<service>` form anywhere.
11. **`docex check` passes `codebase_scripts` and `contracts_exist`**, and the roster
    reports **nine** gates.
12. **Every core service's container probe reports healthy on both foundations you
    run** — `docker inspect --format '{{.State.Health.Status}}'` on fixed, container
    `healthStatus` on elastic.
13. **A loop-owning core service observed FAILING with a stale tick.** Wedge the loop
    and confirm the probe goes unhealthy; then un-wedge and confirm it recovers.
    Green-only is not evidence: the most likely subtle error in step 9 is a tick
    written by a liveness *thread* rather than by the loop, which passes every
    positive test and answers healthy forever while no work moves. **Wedge from the
    host against `docker inspect --format '{{.State.Pid}}'` — `kill -STOP 1` inside
    a container is a no-op**, because PID 1 is immune to `SIGSTOP` in its own
    namespace.
```

---

# Part J — root `CHANGELOG.md`

## Step 50 — group `### Changed` by subject

The `[Unreleased]` section runs from `## [Unreleased]` to `## [1.6.1]`. Its
`### Changed` interleaves advance 006's four entries with advance 005's four, so a
reader cannot tell which release-facing change is which.

**Reorganize by subject, not by advance number** — a reader of the 1.7.0 release
does not know what an advance is; they want the change that broke their `infra.yml`.
Insert `####` headings inside `### Changed` and **move the existing entries under
them, unedited**:

```
#### Vocabulary — codebases and core services
#### One relation: `uses`
#### `role: clock` replaces `role: scheduler`
#### Surfaces replace role-derived contracts
#### Health leaves HTTP
#### The smoke seeds move onto both models
```

Mapping (identify by opening phrase, not by line number — they will shift):

| Heading | Entries to move under it |
| --- | --- |
| Vocabulary | `**A codebase is a `codebase`; a process type is a `core service`.**` |
| One relation | `**`depends_on` and `consumes` merge into one relation, `uses`.**` and `**`docex` implements the `uses` merge.**` |
| `role: clock` | `**`role: scheduler` retires; the clock is an ordinary core service.**` |
| Surfaces | `**A core service declares `surfaces:`; rules 29-33 …**` and `**`docex check`'s contract gate reads `surfaces:` …**` |
| Health leaves HTTP | `**The container probe is a command …**` |
| The smoke seeds | `**Both smoke-test seed projects move onto the new model (mod 129).**` |

**This is a re-ordering plus six headings.** Do **not** rewrite the entries' prose —
each is what its mod wrote and stays as written, except for step 51.

Apply the same treatment to `### Fixed` **only if** it reads better for it; it is
mostly a flat list of unrelated repairs, which is the correct shape for that
section. `### Added` likewise. Use judgement; a heading over a single entry is noise.

## Step 51 — the two traefik claims (both inside `[Unreleased]`)

Confirmed at design review: both are **this cut's own entries**, written by mods
125–130 — not history. Mod 130's "history is not revised" ruling does not reach them.

1. **l. ≈134:** `Its fixed translation — the `curl -f http://localhost:$PORT$PATH`
   probe — is deleted; on fixed, traefik takes target health from the container
   probe.` → replace the clause after the semicolon: on fixed the field has **no
   consumer at all**, because the compiler emits no health-aware traefik labels
   (only `loadbalancer.server.port`) — the field stays declared for portability and
   for rule 4's acceptance.
2. **l. ≈155:** `on fixed there is no consequence to prevent, and traefik dropping a
   not-yet-ready container from its pool is the behavior you want.` → replace the
   `and` clause: on fixed nothing acts on a failing probe at all — Docker reports
   and restarts nothing of its own accord — so there is no wrong consequence for a
   start grace to prevent. **Keep the sentence before it intact**: "ECS kills and
   replaces the task; Docker only reports" is the real mechanism argument and does
   not depend on traefik's behavior in any way.

**Leave released sections alone.** Verify no other in-`[Unreleased]` behavioral
traefik claim survives:

```sh
awk '/^## \[1\.6\.1\]/{exit} /traefik/{print NR": "$0}' CHANGELOG.md
```

Expect only l. ≈450 — a mod-121 entry about one-segment identity in
`ec2_traefik.md`, which makes no behavioral claim. **Leave it.** Any hit in a
released section (below `## [1.6.1]`) is left as-is and **reported**, because that
is what that version shipped.

## Step 52 — one new entry for this mod

Add under `### Fixed`, in this mod's own voice:

```md
- **The docs describing `check`'s contract and health gates described the deleted
  model (mod 131).** `masterplan.md` still narrated the two-armed provider union,
  format-from-`role`, the openapi fallback, self-health for every openapi provider,
  the `/health/<codebase>/<service>` fan-out, and "a core `uses` target must declare
  both `port` and `health_check_path`" — every sentence false after mods 125–127.
  Rewritten against what shipped. Mod 101's account of `_infer_contract_format`
  having returned `openapi` unconditionally **since the day it was written** — so
  the async-contract path never once executed and the fan-out flaw hid behind it —
  is kept as **history**, because it explains how a real defect survived months of
  green runs.

  Three more instances of one drift class were repaired with it. The pre-cut
  checklist told the walker to assert `GET /health/api/worker` returns 200 on
  **both** walks: a route deleted in mod 129, so a walker following the box
  literally would record a failure **against correct code** and stop the cut — the
  most expensive kind of checklist defect, because it burns a walk to teach you
  something false. `upgrade_1.7.0.md` listed **contract path** under "what does not
  move" while every contract in the release is renamed. And a false claim about
  traefik reading container health — true of no shipped configuration, since the
  compiler emits no health-aware traefik labels — had propagated to **five** sites
  (`tables/roles/web.yml` twice, `compiler.md`, and two of this cut's own changelog
  entries) from a single plausible sentence.

  Also: `doctrine_excerpts/` yielded **three independent defects in one advance** —
  a dead prose citation `linkcheck` cannot see, a shim list missing `health.sh`, and
  an **inverted** traefik topology claim unrelated to this advance. Two are
  invisible to any grep keyed on the advance's vocabulary. `docex_process.md` now
  records the verdict (`surface` earns **no** `index.yml` entry, with reasons) and
  the standing limit that produced the misses: **a grep for the new thing cannot
  find a list that lacks it**, so this artifact needs a second pass that reads every
  entry naming a set and asks whether the set is still complete.
```

---

# Part K — verification and commit

## Step 53 — the test suite as a control

```sh
cd docex && python -m pytest tests
```

**Must be 1174 passed, 18 deselected — unchanged.** This mod edits no code, so any
difference is a finding to report, not a success. Do not modify a test.

Integration is not required (nothing in this mod's territory can affect it), but if
run it must be **alone**: `python -m pytest tests -m integration` → 18 passed.

## Step 54 — link and anchor integrity

`linkcheck.py` cannot reach `PRE_CUT_CHECKLIST.md` yet (that is mod 132), so check
the files it *can* reach and hand-check the one it cannot:

```sh
cd /home/ubuntu/.claude/jean_baudrillard && python linkcheck.py doctrine skills
```

Must be green — this mod edits no doctrine, so a new failure means something
unexpected moved.

Then hand-verify **every** anchor this mod wrote or repointed. For each
`](path#anchor)` you introduced, confirm the heading exists in the target:

```sh
grep -n '^#' <target-file>
```

Known targets to confirm: `doctrine/infrastructure/healthchecks.md`
(`#what-the-probe-must-actually-check`, `#version`),
`doctrine/infrastructure/cicl.md` (`#validation-rules`, `#surfaces`),
`doctrine/infrastructure/infrastructure.md` (`#codebase-containers`),
`doctrine/infrastructure/specifics/release.md` (`### Service Connect Consumer
Reconcile`), `docex_process.md#running-the-automated-tests`, and every renumbered
`upgrade_1.7.0.md` self-anchor from step 46.

## Step 55 — the falsehood greps, run once more over everything touched

```sh
cd /home/ubuntu/.claude/jean_baudrillard
grep -rn "fan.out\|fanout\|/health/api/\|/health/<codebase>\|_gate_health_endpoints\|_FALLBACK_CONTRACT\|_CONTRACT_FORMAT_BY_ROLE\|healthcheck_tooling" \
  docex/plans/core/ docex/doctrine_excerpts/ docex/test_projects/PRE_CUT_CHECKLIST.md upgrades/upgrade_1.7.0.md
```

Every surviving hit must be **explicitly historical or explicitly a statement of
deletion**. List each in your report with the reason it survives. A hit that reads
as present-tense fact is a defect this mod was supposed to fix.

```sh
grep -rn "traefik" docex/plans/core/ docex/doctrine_excerpts/ docex/tables/roles/web.yml
```

No hit may claim traefik reads container health or drops unhealthy containers from
a pool. `reverse_proxy.md`'s per-project topology and `compiler.md`'s
"nothing verifies this" statement are the expected hits.

## Step 56 — territory audit

```sh
cd /home/ubuntu/.claude/jean_baudrillard && git status --porcelain
```

The changed set must be **exactly**:

```
docex/plans/core/masterplan.md
docex/plans/core/compiler.md
docex/plans/core/release_flow.md
docex/plans/core/test_projects.md
docex/plans/core/docex_process.md
docex/doctrine_excerpts/service_discovery.md
docex/doctrine_excerpts/codebase.md
docex/doctrine_excerpts/core_service.md
docex/doctrine_excerpts/reverse_proxy.md
docex/test_projects/PRE_CUT_CHECKLIST.md
docex/tables/roles/web.yml
upgrades/upgrade_1.7.0.md
CHANGELOG.md
docex/plans/advances/007_small_edges/reverse_proxy_excerpt_elastic_gap.md   (new)
docex/plans/modifications/131_alignment_sweep_and_cut_artifacts/            (already committed)
```

Plus possibly other `doctrine_excerpts/*.md` if step 26's completeness pass found a
verifiable omission — **name each and why** in your report.

**Anything under `doctrine/`, `docex/src/`, `docex/tests/`, or
`docex/test_projects/{fixed,elastic}/` appearing here is a territory violation.**
Revert it and report.

## Step 57 — report, then stop

**Do not commit.** Report to the corporal:

1. What landed per file, with the specific claim corrected — not "swept
   `compiler.md`" but which sentence and what it now says.
2. Which `PRE_CUT_CHECKLIST.md` boxes moved and which you **deliberately left**
   (D.9/D.11's reconcile boxes and `N = 2` above all).
3. `python -m pytest tests` count, verbatim.
4. Every grep hit from steps 10, 12, 43, 55 that you left in place, with the reason.
5. Anything in the implementation plan that was **wrong** — a line number that had
   moved, a quoted string that did not match, a step that contradicted another.
   Report it rather than working around it silently; that is how the last four mods
   found defects in their own briefs.
6. Any doctrine defect found. **Do not edit `doctrine/`** — raise it.

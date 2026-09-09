# Mod 129 — seed projects: source, contracts, infra

Fifth mod of [advance 006](../../advances/006_surfaces_and_health/advance_plan.md),
and the largest. Brings both seed projects' **source, contracts, and `infra.yml`**
onto the surfaces-and-health model that mods 125–128 built into `docex`.

**Territory.** `test_projects/fixed/**` and `test_projects/elastic/**`, excluding
`infra/output/**`. Nothing in `docex`'s own `src/`, `tables/`, or `tests/`. Not the
recompile, not the projects' `plans/core/*`, not their `CHANGELOG.md`, and no git
state inside the inner repos — all mod 130.

**Rule of record.** The doctrine is committed and authoritative:
[`healthchecks.md`](../../../../doctrine/infrastructure/healthchecks.md),
[`contracts.md`](../../../../doctrine/infrastructure/contracts.md),
[`cicl.md § Surfaces`](../../../../doctrine/infrastructure/cicl.md#surfaces) and
rules 29–33. This mod changes no doctrine file.

**Two real trees.** Verified again at design time: no symlinks under
`test_projects/`, and `diff -rq -x dist fixed/core elastic/core` is clean. Every
`core/` edit is made **twice, identically**. `infra/` differs legitimately by
foundation and is edited per-project.

---

## 1. `infra.yml` (per project)

### `api.web` — unchanged shape, gains a surface

`role: web`, `networks: [web, internal]`, `port: 8080`, and it **keeps**
`health_check_path: /health` (rule 33's positive arm requires it on a
`web`-network service; the ALB target group reads it on elastic).

```yml
        surfaces:
          rest:
            api_styles: [rest]
```

→ `infra/contracts/api.web.rest.openapi.yml`.

`uses: [appdb, probe, events, api.worker]` is unchanged, and `WORKER_HOST` /
`WORKER_PORT` stay — but the comment that justifies them by the fan-out is
rewritten: they now feed a **real application call** into the worker's `rpc`
surface (§ 3). Holding those refs is also what satisfies rule 32's positive arm
for `api.worker`.

### `api.worker` — keeps `port`, loses `health_check_path`, declares two surfaces

`port: 8081` **survives**, and the [SC 2.6 amendment](../../advances/006_surfaces_and_health/advance_plan.md)
is the reason of record: a port-less worker registers no Service Connect name
(`hcl.py:791`), which empties `release.py::_reconcile_candidates`' consumer set
and silently retires the seeds' only coverage of the reconcile. The `port`'s
comment is rewritten from "a port purely for the liveness probe" to what it now
is: the address at which `api.web` reaches the worker's `rpc` boundary.

`health_check_path` is **deleted** — rule 33 forbids it off the `web` network, and
`tables/roles/worker.yml`'s `fields: {}` now rejects it as an undeclared field, so
leaving it in place fails compile.

```yml
        surfaces:
          # Two surfaces, ONE format. Legal, and the reason they are not one
          # surface is the consumers: `api.web` calls the rpc boundary
          # synchronously; the queues are produced onto by `api.web` and
          # `api.clock` and consumed here. cicl.md's split table permits one
          # surface per unrelated consumer set.
          rpc:
            api_styles: [rpc]
          events:
            api_styles: [events]
```

→ `api.worker.rpc.asyncapi.yml` and `api.worker.events.asyncapi.yml`.

Both channels the worker already consumes (`pings`, `jobs`) stay in the **one**
`events` document, per cicl.md's split table: *"A worker consuming two different
queues — one core service, one surface; one AsyncAPI document carries both
channels."*

### `api.clock` — loses `port` and `health_check_path`, declares no surface

Consumer-only and driven by time. Nothing may `uses` it, so it is not a provider
and declares no surface; its probe is the tick file. The long comment justifying
`port: 8082` + `health_check_path` by "the container healthcheck is a clock's only
enforcement" is replaced by a shorter one that says the enforcement is now
`./health.sh clock` and that a clock listens on nothing.

`uses: [appdb, api.worker]` and the "holds no magic ref — the edge is the queue"
comment are unchanged, and that asymmetry is now load-bearing: one target
(`api.worker`), two consumers, reached two different ways — the case that decided
rule 32's edge-scoped detection. The comment says so explicitly rather than
leaving the reader to infer it from rule 32's implementation.

---

## 2. `core/api/health.sh` — the fourth shim

New file per project (byte-identical), `chmod +x`, `case "$1"` over the three core
services. Exit code is the entire contract.

- **`web`** — `curl -fsS -m 3 http://localhost:8080/health`. A request-cycle
  service is nearly self-checking; `healthchecks.md § What the probe must actually
  check` blesses exactly this. `8080` is coupled by convention to `infra.yml`'s
  `port:`, as `entrypoints/web.py` already is.
- **`worker` / `clock`** — stat `/tmp/<service>.tick` and fail if absent or older
  than **30 s**. Absent must fail: a loop that has never ticked has never run one
  iteration.
- **any other argv** — exit non-zero with a message. A typo in the emitted argv
  must be loud, not silently healthy.

**The 30 s threshold lives here and only here.** The entrypoints' `_STALENESS_SECONDS`
is deleted rather than kept: once the probe is a separate process, the entrypoint
no longer judges staleness, and a second copy of the number in a file that no
longer decides anything is a drift surface. The entrypoints keep only their tick
*cadence* (1 s worker, 5 s clock), each comfortably inside the doctrine's 10 s
ceiling, and each comments the relationship.

`stat -c %Y` + `date +%s` rather than a python one-liner: both are guaranteed by
the Debian-based `python:3.12-slim`, and the probe should not pay interpreter
startup on a 5 s timeout.

**The two numbers are only meaningful as a pair, so each file names the other
half.** `health.sh` owns the **threshold** (30 s) and says in a comment that the
loop's cadence lives in the entrypoint; each entrypoint owns the **cadence**
(≤10 s even when idle) and says in a comment that the threshold lives in
`health.sh`. Thirty is three times ten, so a healthy loop misses two consecutive
ticks before it is called stale — a reader who finds one number alone cannot see
that, which is why neither comment is optional.

---

## 3. Source: health leaves HTTP, and the worker gains a real boundary

### 3.1 `entrypoints/worker.py`

Deleted: `_build_health_app`, the `/health` route, `_STALENESS_SECONDS`, and
`_HEALTH_PORT` **as a health port**.

`_Tick` **survives, retargeted to a file** — `Path("/tmp/worker.tick").touch()`
inside the loop, on the same success path that bumped the in-memory float, with
the withheld-tick-on-failure behaviour and its WHY comment intact. Per
`healthchecks.md`, the tick must come from the receive loop itself; a separate
liveness thread "proves less than nothing".

**A uvicorn-on-a-daemon-thread block still exists in this file, and that is
deliberate — flagged here so the diff is not a surprise.** What is deleted is the
health server. What replaces it in the same structural slot is the `rpc` surface's
server (§ 3.2), which exists because a *consumer calls it*, not because anything
needs liveness over HTTP. The WHY comments are rewritten to say so, and the loop's
liveness no longer depends on that thread at all. `api.clock` is the clean
demonstration: it loses uvicorn, fastapi, and its listener entirely.

### 3.2 The `rpc` surface — `POST /drain`

> **This is the mod's escalated design decision. See [Q1](#q1--what-the-workers-rpc-boundary-actually-is).**
> The shape below is my recommendation, not a settled ruling.

`api.web` asks `api.worker` to **drain the deferred-job queue now**, and gets back
the number of jobs performed. The reason this call must cross the process boundary
is doctrinal rather than contrived: the perform side belongs to the worker, and an
edge that drained the queue itself would be the same violation
`clock.md § The clock defers; it does not work` forbids of the clock. Reply is a
count of work performed — it carries no liveness verdict and no staleness
judgment, so it cannot be mistaken for the thing this advance deleted.

**Provider side** (bound only in the worker's entrypoint) — one new file:

| File | Role |
| --- | --- |
| `hex/jobs/adapters/driving/cont_job_runner_http.py` | `ContJobRunnerHttp` — FastAPI router over the **existing** `ContJobRunner` driving port. `POST /drain` → `{performed: N}`. |

`ContJobRunner`, `JobRunnerService`, and `run_once()` are reused unchanged. Safe
against the loop draining concurrently: `QueueJobsPostgres` opens a connection per
call, and `claim`'s `FOR UPDATE SKIP LOCKED` is already what makes `replicas: 2`
safe. That gets a WHY comment; it is the second consumer of a guarantee whose
first justification is already written down.

**Consumer side** (`api.web`) — five files, which is the doctrine's own tax for a
clean hexagon and cannot be paid down without putting an application HTTP call in
`root.py` (which is exactly what the fan-out did, and what is being deleted):

| File | Role |
| --- | --- |
| `hex/jobs/ports/driven/gwy_job_runner.py` | `GwyJobRunner` — Gateway pattern; the worker is an external system from this module's view. |
| `hex/jobs/adapters/driven/gwy_job_runner_http.py` | `GwyJobRunnerHttp` — calls the worker's `rpc` boundary using the injected host/port. |
| `hex/jobs/ports/driving/cont_job_drain.py` | `ContJobDrain` — `drain_now() -> int`. |
| `hex/jobs/alogic/job_drain_service.py` | `JobDrainService` — implements `ContJobDrain` over the gateway. |
| `hex/jobs/adapters/driving/cont_job_drain_http.py` | `ContJobDrainHttp` — `POST /jobs/drain` on `api.web`. |

**Why not put `drain()` on the existing `ContJobs` port** (which would save three
files): `ContJobs` is the port the **clock** holds. Giving it a drain method hands
the clock the ability to trigger performance, which is precisely the deferral
architecture the seed spends paragraphs protecting. The separate port is the
cheaper mistake to avoid.

**The five consumer-side files are the point, not overhead, and are commented as
the tax they are.** The seeds currently demonstrate no consumer-side gateway onto a
sibling core service at all — the sole cross-core call is the raw `urllib` in
`root.py` that this mod deletes. So this is not preserved coverage but *added*
coverage of the canonical shape: a driven gateway port and adapter, injected by the
composition root, calling another core service across a declared surface.

**Two codebase tests** are added (`core/api/tests/`), both stub-backed and
therefore immune to the live `test`-env worker competing for rows:
`JobDrainService` over a stub gateway, and `ContJobRunnerHttp`'s translation
(request in → port call → `{performed: N}` out) over a stub port.

### 3.3 `entrypoints/clock.py`

Deleted: `_build_health_app`, the `/health` route, `_STALENESS_SECONDS`,
`_HEALTH_PORT`, the uvicorn daemon thread, and the `uvicorn` / `fastapi` imports.
`_Tick` retargets to `/tmp/clock.tick`. Everything else — the schedules parse, the
startup binding gate, the forward-only `next_at` seeding, the tick-withheld-on-
total-failure rule — is untouched.

**This is the file a reviewer should read first.** `api.clock` loses uvicorn,
fastapi, and its listener *outright* — it now listens on nothing and declares no
port. That is the mod's strongest single piece of evidence that the change is real
rather than cosmetic: everywhere else HTTP survives for a reason (an ingress edge,
a called surface), and here, where the only reason was health, it is gone
completely.

### 3.4 `root.py`

- **`/health/api/worker` is deleted entirely**, with its docstring citing
  `contracts.md § Fan-out`, and `json` / `urllib` imports pruned to what remains.
- **`GET /health` stays** and keeps returning `{version}` — `api.web` is on `web`,
  the ALB probes it, `_gate_contract_health_path` asserts it appears in the
  `openapi` contract, and the stage tests assert its body against
  `PROJECT_VERSION`.
- **`/health/probe` → `/diagnostics/probe`, `/health/events` → `/diagnostics/events`.**
  Renamed, not deleted. These are `api.web` reachability-probing two *backing*
  services and are the only exercise either seed gives the project-local
  `sidecar` / `clickhouse` engines — and, on elastic, SG reachability to them.
  Deleting them would leave `probe` and `events` unexercised and their `uses`
  edges pointless. Leaving them under `/health/*` would invite a reader to
  conclude the fan-out survived and sits badly against
  `healthchecks.md`'s *"No service reports on another."* A comment states what
  they are and are not. They stay in the `rest` contract.
- Gains `build_job_drain_http()` and `build_job_runner_http()` constructors, and
  passes `WORKER_HOST` / `WORKER_PORT` into the gateway. The root **constructs
  both**, including the one the running core service will never use — per
  `internal_dependency_rules.md § Composition Root` item 3, which the file's own
  `build_jobs_cli` docstring already argues at length.

*Noted, not fixed:* `GET /health` and the two `/diagnostics` routes are defined
inline in `root.py` rather than in a controller. That predates this mod and is
arguably a boundary violation; it is out of territory and left alone.

---

## 4. `Dockerfile` (per project)

- `COPY health.sh` in the **`dev`** and **`prod`** stages, `chmod +x`. Today `dev`
  copies `build.sh migrate.sh test.sh` and `prod` copies only `migrate.sh`, so
  `prod` — the image `stage`/`prod` actually run — has no probe at all.
- `EXPOSE 8080 8081` (8082 dropped). `api.clock` listens on nothing.
- The `curl` comment is rewritten. The doctrine withdrew the curl mandate
  entirely; what an image needs is whatever *its* `health.sh` uses, which here is
  `health.sh`'s `web` arm. The obsolete claims — that the emitted probe is
  `curl -f http://localhost:${port}${path}`, that all three core services need
  curl because all three declare `health_check_path`, and the "doctrine
  improvement TODO: switch to a tool-free probe" — are all now false or done.
- `fastapi` / `uvicorn` keep their lines but the **reason** changes: they serve
  `api.web`'s `rest` surface and `api.worker`'s `rpc` surface. They are no longer
  a liveness dependency, and `api.clock` no longer needs them (it still receives
  them — one image, one dependency set).

---

## 5. Contracts — six files, not four

The advance plan says "the four contract files are renamed". That count is the
**current** one (two per project). The target shape produces **three per project**,
because `api.worker` declares two surfaces:

| Was | Becomes |
| --- | --- |
| `api.web.openapi.yml` | `api.web.rest.openapi.yml` |
| `api.worker.asyncapi.yml` | `api.worker.events.asyncapi.yml` |
| — | `api.worker.rpc.asyncapi.yml` (new) |

`_gate_contracts`' orphan arm fails on any file in `infra/contracts/` that parses
as a contract but matches no surface, so the renames must be exact and nothing may
be left behind.

**Both existing headers narrate the retired model at length and are rewritten, not
patched.** `api.web.openapi.yml` documents the three-segment path scheme and the
fan-out mandate across sixteen lines; `api.worker.asyncapi.yml` justifies its
`/health` absence via `port` + `health_check_path`, and its "why this file exists"
paragraph keys the format on `role`.

**Spec versions are bumped**, per [Q4](#q4--spec-version-minimums):
`openapi: "3.0.3"` → `"3.2.0"`, `asyncapi: "2.6.0"` → `"3.0.0"`. The AsyncAPI bump
is structural — 3.0 lifts `operations` out of `channels` and gives channels an
`address` — which is also what makes `reply` available for the `rpc` surface.

- **`api.web.rest.openapi.yml`** — `GET /health`, `GET /diagnostics/{probe,events}`,
  `POST /pings`, `POST /jobs/{prune_pings,heartbeat}`, `POST /jobs/drain`. Loses
  `GET /health/api/worker`.
- **`api.worker.events.asyncapi.yml`** — the `pings` and `jobs` channels, each with
  an `action: receive` operation. The "AsyncAPI describes a broker and this worker
  has none; the honest address is a table name" note is **kept** — it is still true
  and still the most useful thing in the file.
- **`api.worker.rpc.asyncapi.yml`** — one channel at `/drain`, one operation with
  `action: receive` and a `reply`. Its header states that this is the surface
  `api.web` addresses directly, which is what obliges the worker's `port`.

---

## 6. `infra/stage/tests/test_smoke.py` (per project)

- **`test_health_fanout_reports_worker_liveness` is deleted.**
- The module docstring's first bullet is liveness; the whole docstring is
  rewritten. Staging tests now assert only what requires being outside — TLS/DNS,
  reverse-proxy routing, and critical-path behaviour — and `docex stagetest` reads
  liveness from the orchestrator before the tester image is even built (mod 128).
  `healthchecks.md` states the narrowing outright: staging tests *"do not assert
  liveness, and cannot reach a non-`web` core service at all."*
- The two backing-reachability tests retarget `/diagnostics/probe` and
  `/diagnostics/events` and are renamed to match.
- Kept: the `/health` version assertion against `PROJECT_VERSION`, and the
  `/pings` round trip.
- Added: `test_defer_and_drain_round_trip` — `POST /jobs/heartbeat` (202, a
  `job_id`) then `POST /jobs/drain` (200, `{performed: <int>}`). This is the only
  place from outside that the worker's `rpc` surface — and therefore the `uses`
  edge rule 32 governs — is exercised end to end. It replaces what the fan-out
  test used to prove about that edge (the magic refs resolved, `web` reached a
  non-`web` sibling over the internal network) while asserting nothing about
  liveness, which is now the orchestrator's to report.

  **It must not race the worker's poll loop, and the shape of the test is what
  prevents it.** The worker drains every second on its own, so by the time the
  test calls `/jobs/drain` the heartbeat may legitimately already be gone and the
  honest reply is `{performed: 0}`. **No exact count is asserted** — only that the
  reply is a 200 carrying an integer `performed`. The tautology is deliberate and
  carries a comment saying so: the load-bearing assertion is the `200` itself, on
  a route that *cannot* answer without reaching the worker across the internal
  network. An order-dependent count would pass locally and burn a walk.

  This is also `tests.md`'s own prescribed shape — a scenario that must exercise a
  worker drives the public edge and observes the effect — and `POST /drain`
  satisfies it more strongly than the asynchronous version does: the worker's
  **own reply travels back out through the edge**, so the observation is
  synchronous rather than a side effect that has to be read back later. Which
  matters here, because neither seed has a route that can read a job or a ping
  back; adding one to enable an effect assertion is not in this mod's scope.

---

## 7. Proving the tick probe fails

Success criterion 2.6 requires worker/clock liveness *observed stale-and-failing at
least once*. A probe seen only passing is what advance 005 spent thirteen mods
learning not to trust, and a naive tick reports healthy forever —
`healthchecks.md` calls that "converting a loud failure into a silent one".

Procedure, on the `fixed` seed's `dev` stack:

1. `./bin/docex compile && ./bin/docex build && ./bin/docex envinfra up dev`.
2. `docker compose exec <api-worker> ./health.sh worker` → **exit 0**. Same for
   `clock`. Record the tick file's mtime advancing.
3. **Wedge the loop for real:** `kill -STOP` the worker's python process inside the
   container. The container stays up and the process stays alive — which is
   precisely the failure mode a process-existence probe cannot see. Wait 35 s.
4. `./health.sh worker` → **non-zero**, message naming the staleness. Then
   `docker inspect --format '{{.State.Health.Status}}'` → `unhealthy` once the
   retry count is exhausted, which is the orchestrator half of the same claim.
5. `kill -CONT`; probe returns to 0.
6. Repeat step 3–4 for `clock`.
7. Separately assert the absent-tick arm: `rm /tmp/worker.tick` → non-zero.

Both arms and both services, red before green, recorded in the mod report.

### 7.1 What was actually observed

Run against the `fixed` seed's `dev` stack, then torn down. The probe went red
before it went green, on both loop-owning core services.

**`api.worker`**, wedged with `SIGSTOP` to the poll loop — container up, process
alive, loop frozen:

```
t+2s    probe_rc=0  docker_health=healthy
t+15s   probe_rc=0  docker_health=healthy
t+31s   probe_rc=1  docker_health=healthy    loop tick is 32s stale (threshold 30s)
t+65s   probe_rc=1  docker_health=healthy    loop tick is 66s stale (threshold 30s)
t+95s   probe_rc=1  docker_health=UNHEALTHY  failing_streak=3
```

Docker's own health log, read back from `docker inspect`, carries the three
failures it ran itself: `0 0 1 (40s stale) 1 (70s stale) 1 (100s stale)`. So the
claim is complete end to end — loop wedged → probe red → **orchestrator**
unhealthy — and not merely "a script I ran by hand returned 1". `SIGCONT`
restored `probe_rc=0` within 3 s and `docker_health=healthy` with
`failing_streak=0`. The absent-tick arm was then fired deliberately (`rm
/tmp/worker.tick` → rc=1).

**`api.clock`**, same wedge: `probe_rc=0` at t+10s, `rc=1` at t+33s ("loop tick
is 34s stale"), `docker_health=unhealthy` at streak 3, recovered on `SIGCONT`.

**The clock binds no application socket**, verified rather than asserted — the
only `LISTEN` entry in its `/proc/net/tcp` is `127.0.0.11:*`, docker's embedded
DNS resolver, which every container has. `api.web` shows `0.0.0.0:8080` and
`api.worker` shows `0.0.0.0:8081`; the clock shows nothing.

**The `rpc` edge, live.** `POST /jobs/drain` on `api.web` crossed to the worker
and returned `{"performed": 0}` on the first call and `{"performed": 2}` after
five heartbeats were queued in a burst — the worker's own loop having taken the
other three under `SKIP LOCKED`. That is direct evidence for two design choices
at once: the boundary performs real work, and **the stage test was right not to
assert a count.** `GET /health/api/worker` returns 404.

### 7.2 Two false-green traps found while proving it

Both are the advance's recurring defect — *something that could not have
detected the failure reported success* — and both would have produced a
convincing wrong answer.

1. **`kill -STOP 1` inside the container does not wedge anything.** PID 1 in a
   PID namespace is immune to `SIGSTOP` and `SIGKILL` from inside that namespace
   unless it has installed a handler, so the "wedge" was silently a no-op and the
   probe kept passing — at t+40s it still read `rc=0`. A verifier working from
   that reading concludes either that the probe is broken or, worse, records a
   green from a wedge that never happened. The wedge must be delivered from the
   host: `sudo kill -STOP $(docker inspect -f '{{.State.Pid}}' <container>)`.
2. **`envinfra up dev` left the host `dist/` bind mount stale**, so the
   containers first came up running the *pre-mod* entrypoints. The probe's first
   answer was `no tick file at /tmp/worker.tick` — which is indistinguishable
   from the absent-tick arm working correctly, and is in fact old code that never
   writes a tick at all. `./bin/docex build` refreshed it (and itself refuses to
   run until the stack is up, so the order is `up` → `build` → restart the core
   services). Any future walk that reads a tick-file failure on a first `up`
   should check `dist/` before believing the probe.

---

## 8. Knowingly left stale

Stated so a reader between mods 129 and 130 finds an accounting rather than a gap:

- `infra/output/**` in both projects — mod 130. The `compile` runs this mod's
  signal requires **did** rewrite eight of those artifacts (four per project),
  and they are deliberately **left uncommitted**, so mod 130 reviews the artifact
  diff rather than inheriting it already blessed. That review is the whole reason
  the two mods were split.
- Both projects' `plans/core/masterplan.md` and `plans/core/api/api.md`, which
  still describe the fan-out and the three-segment contract paths — mod 130.
- Both `CHANGELOG.md`s and the inner-repo commit / tag cadence — mod 130.
- `PRE_CUT_CHECKLIST.md` § B.7 (which still tells the walker that every core
  `uses` target declares `port` **and** `health_check_path`, and that the curl gate
  has no network filter), C.7, C.9, D.9, D.11 — mod 131.

## 8.1 Errors in this mod's own implementation plan

Recorded because the implementor reported them rather than working around them,
which is the behaviour worth reinforcing.

1. **Step 12(d)'s grep contradicted steps 3.4, 10.1 and 11.2.** It expected zero
   hits for `fan-out` while three other steps *commissioned* prose using the word
   in negation ("these are **not** a health fan-out — there is no fan-out"). Ten
   hits, all negations, five per tree. The prose is right and the grep was wrong:
   a change this size needs the deletion stated, not silently absent. The grep's
   other seven spellings — `health/api/worker`, `fanout`, `_build_health_app`,
   `_HEALTH_PORT`, `_STALENESS_SECONDS`, `health/probe`, `health/events` — are
   clean, and those are the structural ones. **Verified** at review.
2. **Step 12(f)'s literal `pytest tests -q` cannot collect the suite.** Three
   files do `from tests.conftest import ...`, and plain `pytest` does not put the
   repo root on `sys.path`; it errors on collection and reports *17* deselected
   rather than 18, because one deselected test lives in an erroring file. A
   count that is nearly right while nothing ran is the worst possible signature.
   The working invocation is `.venv/bin/python -m pytest tests -q`. Pre-existing
   and unrelated to this mod, but the plan should not have written the broken
   form.
3. **Three comments the plan froze had gone stale.** Steps 4 and 5 said "keep
   verbatim" / "unchanged" for three WHY comments phrased as "would answer 200
   forever" — reasoning that is still exactly right inside files that now serve
   nothing. The implementor honoured the freeze and flagged it; fixed at review to
   "would keep the probe green forever". A `verbatim` instruction is a liability
   when the surrounding substrate is what the mod is changing.

Accepted without change: `build_processor` / `build_clock` docstrings also said
the entrypoint owns "the liveness surface" and were corrected (an addition the
plan did not enumerate, in territory and required for truthfulness); step 7's two
tests became three, splitting the 503 case out for clearer failure attribution.

## 9. Provenance of the local `docex:1.7.0` image

Recorded because an undocumented local tag is how a work-in-progress image is
later mistaken for a released one.

**The `docex:1.7.0` image on this machine was rebuilt mid-advance**, at branch
`006_surfaces_and_health` HEAD `7804c88` — after mods 125–128 and before this one.
The image it replaced was built 2026-08-06 and predated the whole advance, so
`./bin/docex compile` through the shim would have run a `docex` with no `surfaces:`
support and rejected correctly-authored input.

1.7.0 is **untagged and unreleased**, so the tag promises nobody anything and there
is no released artifact to corrupt. `RELEASING.md` step 7 rebuilds it at cut time
and both smoke walks rebuild it regardless, so this is early rather than extra.

The seeds are exercised **through the real shim** rather than through `docex`'s
venv on purpose: the shim path — mounts, DooD, in-container paths — is how a
project actually runs `docex`, and it is the artifact whose behaviour this advance
validates. A venv invocation would test the code while skipping the delivery
mechanism. (The three-gate harness in Q2 is the one venv-side exception, because
`check` cannot be reached through the shim at all from this mod's territory.)

---

## Design questions

### Q1 — what the worker's `rpc` boundary actually is

**The mod brief nominates job status. I recommend against it, and the reason is a
property of this seed specifically.**

`api.web` and `api.worker` are one codebase, share one composition root, share the
`hex/jobs` module, and share one postgres database. Web's `JobService` already
holds a `QueueJobs` adapter pointed at the same `jobs` table. So a `getJobStatus`
RPC has web make an HTTP call to a sibling process in order to read a row it can
read directly, one method away. That is a contrivance a reviewer will flag, and
the seeds are the reference implementation downstream projects copy — they inherit
whatever the seeds fail to justify.

Three candidates, all of which satisfy "a real `rpc` surface with a real consumer":

| | Boundary | Verdict |
| --- | --- | --- |
| **A** | `getJobStatus(id)` — nominated in the brief | Contrived here: web shares the DB and the module, so the call buys nothing an in-process read does not. |
| **B** | `POST /drain` — "drain the queue now", reply `{performed: N}` | **Recommended.** |
| **C** | worker runtime/drain statistics | Smallest, and genuinely in-process-only data — but it reads adjacent to health and invites exactly the misreading the `/health/probe` rename exists to prevent. |

**Why B.** (1) It cannot be mistaken for a health check: it is a command with a
side effect whose reply is a count of work performed. (2) Its cross-process
necessity is doctrine-grounded — the perform side belongs to the worker, and an
edge that drained the queue itself would commit the violation
`clock.md § The clock defers; it does not work` forbids of the clock. (3) It
reuses `ContJobRunner` / `JobRunnerService` / `run_once()` wholesale, so the
provider side is one new adapter. (4) AsyncAPI 3.0 `reply` describes it exactly,
which is what the style table cites `rpc` for. (5) It gives the seeds a
demonstration of a **consumer-side gateway onto a sibling core service** — the
shape rule 32's positive arm exists to govern, and a shape currently demonstrated
only by raw `urllib` inside `root.py`, which is being deleted.

**Honest cost of B:** five new consumer-side files (§ 3.2). Approximately 180 new
lines of source per tree, doubled across the two trees. A had roughly the same
cost plus a `QueueJobs.get` read; C would be about half.

**Fall-back if you rule for A or C:** either is implementable within the same
plan; only § 3.2, the `rpc` contract, and one stage-test assertion change.

### Q2 — my completion signal does not exist as specified

The mod brief sets `./bin/docex check` green as a per-project signal. **That
cannot be reached from inside this mod's territory**, and I would rather say so
now than report a fabricated green:

1. `check` **refuses to run** on `main` or with a dirty tree (`check.py` docstring
   step 1). Both inner repos are on `main`, and my edits necessarily dirty them.
2. Its gates run against an **ephemeral worktree of committed state** rebased onto
   `origin/main` — so even if it ran, it would evaluate the *old* files and tell
   me nothing about uncommitted work.
3. Inner-repo commits, branches, and tags are explicitly mod 130's.

**Proposed substitute, per project:**

- `./bin/docex compile` succeeds. (Today it *fails* on both seeds — rule 33's
  negative arm and `tables/roles/worker.yml`'s `fields: {}` both reject the
  worker's `health_check_path` — so this is a genuine red→green transition, not a
  no-op check.)
- The three `check` gates this mod's territory can affect — `contracts_exist`,
  `contract_health_path`, `codebase_scripts` — invoked **directly** against each
  seed tree via a throwaway harness in scratch (`load_project_context` +
  `_gate_*`, all importable from `docex/.venv`). Verified working at design time.
  Reported gate-by-gate.
- Full `docex check` deferred to mod 130 (which owns the inner-repo commit) or to
  the walk's C.7 / D.7 box.

**And one request.** The local `docex:1.7.0` image is from **2026-08-06**, four
days before HEAD — it predates mods 125–128, so `./bin/docex compile` run through
the shim today would exercise a `docex` with no `surfaces:` support and reject a
correctly-authored file. I intend to rebuild it in place:
`docker build -t docex:1.7.0 ./docex` from the repo root, which is step 7 of
`RELEASING.md` and what the walk does anyway. No tracked artifact changes. Say the
word if you would rather that wait.

### Q3 — six contract files, not four

Not a question; a correction to the plan's count, recorded in § 5 so a B-audit
does not read it as scope creep. `api.worker`'s second surface is the operator's
own instruction and is deliberate coverage of two-surfaces-one-format, which
nothing else in the repo exercises.

### Q4 — spec version minimums

`contracts.md § Standards` now fixes **OpenAPI 3.2 or later** and **AsyncAPI 3.0
or later**. Both existing seed contracts predate that text and violate it
(`3.0.3`, `2.6.0`). Nothing enforces it mechanically — `docex check` only
YAML-parses the document and reads `paths` — so this would sit as silent drift
past a green walk. I intend to bump both to conform, which makes the AsyncAPI
rewrite structural rather than cosmetic. Flagging rather than assuming, because it
enlarges the contract diff.

### Q5 — the worker keeps a uvicorn daemon thread

Not a question, but the diff's most misreadable line and I want it on the record
before you read it. The block is not the health server surviving under a new
name: liveness moves entirely to the tick file, and the server exists only because
`api.web` calls the `rpc` surface. Delete the surface and the worker listens on
nothing. `api.clock` — which has no surface — is the file that proves the point,
losing uvicorn, fastapi, and its listener outright.

### Q6 — `_STALENESS_SECONDS` is deleted from the entrypoints

The brief notes that `_STALENESS_SECONDS = 30.0` already encodes the doctrine
threshold. It does — but once the probe is a separate process, the entrypoint no
longer judges staleness, and keeping the constant leaves the number written in two
files of which only one decides. I am moving it to `health.sh` and deleting it
from both entrypoints, leaving each entrypoint only its tick cadence and a comment
naming the 10 s ceiling that cadence satisfies. Reversible if you disagree.

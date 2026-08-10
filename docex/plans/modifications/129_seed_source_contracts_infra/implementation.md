# Mod 129 — implementation steps

Design: [`overview.md`](./overview.md). Read it first; it carries the *why* for
every step below and the rulings that closed three design questions.

**Territory.** `docex/test_projects/fixed/**` and `docex/test_projects/elastic/**`,
excluding `infra/output/**`. Nothing in `docex`'s own `src/`, `tables/`, `tests/`,
`plans/`, or `doctrine_excerpts/`. Do **not** touch either project's
`plans/core/*`, `CHANGELOG.md`, `README.md`, or any git state inside the inner
repos (no `git add`, `commit`, `tag`, or `checkout` under `test_projects/`). Those
belong to mod 130.

Paths below are relative to `docex/test_projects/` unless stated. `$FIXED` =
`fixed`, `$ELASTIC` = `elastic`.

**The `core/` trees must stay byte-identical.** They are two real trees, not
symlinks. The order of work below exists to guarantee that mechanically: do every
`core/` edit in `$FIXED` **only**, then copy the changed files across in step 8,
then verify with `diff`. Do not hand-edit the same file twice.

**Do not run `docex check`.** It refuses a dirty tree and refuses `main`, and it
grades committed state — it cannot see this work. The completion signal is step 9.

---

## 1. `fixed/core/api/health.sh` — new file

Create with exactly this content, then `chmod +x`.

```sh
#!/bin/sh
# health.sh — the `api` codebase's container health probe.
#
# The fourth codebase shim, beside build.sh / test.sh / migrate.sh, and the only
# one invoked PER CORE SERVICE: the compiler emits
# `["CMD", "./health.sh", "<service>"]` as the container probe on both
# foundations, so this script never has to guess where it is running
# (healthchecks.md § The probe). `./health.sh` resolves against WORKDIR /service.
#
# THE EXIT CODE IS THE ENTIRE CONTRACT. 0 means this core service is working;
# anything else means it is not. Nothing reads stdout — docker captures probe
# output and ECS does not, so it can never be a cross-foundation channel
# (healthchecks.md § Version). The messages below go to stderr for a human
# reading `docker inspect` and promise nothing.
#
# POSIX sh, not bash: python:3.12-slim ships dash as /bin/sh and no bash.

set -eu

svc="${1:-}"
if [ -z "$svc" ]; then
    echo "health.sh: usage: ./health.sh <core-service>" >&2
    exit 2
fi

# The staleness THRESHOLD is doctrine-fixed at 30s and lives here, because this
# script is the only thing that judges it. The loop CADENCE — at least one tick
# every 10s even when idle — is doctrine-fixed too and lives in
# src/entrypoints/{worker,clock}.py, because the loop is the only thing that can
# honour it. THE TWO NUMBERS ARE MEANINGLESS APART: 30 is three times 10, so a
# healthy loop misses two consecutive ticks before it is called stale — enough
# slack for scheduling jitter and one slow iteration without flapping, while
# still failing a wedged loop inside the window the orchestrator acts on. There
# is no per-project knob for either
# (healthchecks.md § What the probe must actually check).
STALENESS_SECONDS=30

# Must match infra.yml's `port:` on api.web. Nothing injects it, so the two are
# coupled by convention — exactly as src/entrypoints/web.py's default is.
WEB_PORT=8080

check_tick() {
    # A loop-owning core service's liveness is sourced FROM THE LOOP: the loop
    # touches this file at the end of each iteration and this stats it from a
    # separate process. Checking that the process exists would prove nothing (a
    # deadlocked process exists), and checking a separate liveness thread would
    # prove less than nothing — it answers healthy forever while no work moves,
    # converting a loud failure into a silent one
    # (healthchecks.md § What the probe must actually check).
    tick="/tmp/$1.tick"

    # An ABSENT tick file FAILS. A loop that has never completed an iteration
    # has never been alive, and reporting healthy until the first tick would
    # hide a loop that never started — the exact failure this probe exists for.
    # On elastic the role tables' `startPeriod: 10` is what keeps this from
    # killing a task during normal startup; on fixed docker only reports, so
    # nothing acts on it early.
    if [ ! -f "$tick" ]; then
        echo "health.sh: $1: no tick file at $tick — the loop has not completed an iteration" >&2
        exit 1
    fi

    age=$(( $(date +%s) - $(stat -c %Y "$tick") ))
    if [ "$age" -gt "$STALENESS_SECONDS" ]; then
        echo "health.sh: $1: loop tick is ${age}s stale (threshold ${STALENESS_SECONDS}s)" >&2
        exit 1
    fi
}

case "$svc" in
    web)
        # A service driven by a REQUEST CYCLE is nearly self-checking: if it
        # accepts a connection and routes a trivial request, it is serving.
        # Curling its own route is legitimate here and nowhere else in this file
        # (healthchecks.md § What the probe must actually check). `curl` is in
        # the image FOR THIS LINE — see the Dockerfile.
        curl -fsS -m 3 "http://localhost:${WEB_PORT}/health" >/dev/null
        ;;
    worker|clock)
        # Both own a loop. A clock is not exempt from anything: it wakes, checks
        # its schedule, and sleeps, which is a loop in exactly this sense.
        check_tick "$svc"
        ;;
    *)
        # A typo in the emitted argv must be LOUD. Falling through to exit 0
        # would report every core service healthy forever, which is the one
        # outcome worse than a wrong probe.
        echo "health.sh: unknown core service '$svc' (expected web, worker or clock)" >&2
        exit 2
        ;;
esac
```

Sanity-check it locally before moving on:
`sh -n fixed/core/api/health.sh` (parses), and
`FIXED=fixed; sh $FIXED/core/api/health.sh nonesuch; echo $?` → `2`.

---

## 2. `fixed/core/api/src/hex/jobs` — the `rpc` surface and its consumer

Six new files. Every one of them gets a real module docstring in the register the
rest of this codebase uses — these files are the doctrine's worked example of a
consumer-side gateway onto a sibling core service, and that shape appears nowhere
else in either seed.

### 2.1 `adapters/driving/cont_job_runner_http.py` — provider side (new)

`ContJobRunnerHttp`, a second *mechanism* on the **existing** `ContJobRunner`
driving port. `APIRouter` with one route: `POST /drain`, `status_code=200`,
`response_model=_DrainResult(performed: int)`. Handler calls
`self._service.run_once()`; wraps `except Exception` into
`HTTPException(503, f"could not drain: {exc}")`, mirroring
`cont_jobs_http.py::_defer`'s existing idiom.

Docstring must carry, in this order:

1. This is `api.worker`'s `rpc` surface — `surfaces: {rpc: {api_styles: [rpc]}}`
   in `infra.yml`, contract `api.worker.rpc.asyncapi.yml`.
2. **Why the boundary crosses a process edge at all**: the perform side of the
   queue belongs to `api.worker`. An HTTP edge that drained the queue in its own
   process, with its own sizing and its own lifetime, would commit the violation
   `clock.md § The clock defers; it does not work` forbids of the clock one core
   service over. `api.web` asks; it does not perform.
3. `Http` is the *mechanism* suffix and `rpc` is the *api_style* — different axes,
   and the doctrine keys the contract format on the second
   (`cicl.md § Surfaces`). This is the case MCP made, which this adapter shares.
4. **Concurrency, and why no lock**: the router is served from a daemon thread
   while the poll loop drains on its own interval. `QueueJobsPostgres` opens a
   connection per call and `claim` uses `FOR UPDATE SKIP LOCKED` — the guarantee
   that already makes `replicas: 2` safe against itself. A second in-process
   caller is the same race with a shorter name. **Do not add a lock.**

Handler docstring must state that **`performed: 0` is a success, not an error** —
the worker's own loop drains on its interval, so an empty queue is the ordinary
outcome of asking at the wrong moment, and a caller treating 0 as failure is
asserting on scheduling. And that 503 means the batch could not be claimed at all.

### 2.2 `ports/driven/gwy_job_runner.py` — consumer side (new)

`GwyJobRunner(Protocol)` with one method: `drain_now(self) -> int`, docstringed
"Ask `api.worker` to drain the queue now; return the number of jobs performed."

Docstring: the canonical **Gateway** pattern
(`hex_overview.md § Driven Port / Adapter Patterns`). `api.worker` shares this
module's source, but it is a different process reached over the network, and from
`api.web`'s side that is precisely what a gateway is for.

### 2.3 `adapters/driven/gwy_job_runner_http.py` — consumer side (new)

`GwyJobRunnerHttp(GwyJobRunner)`. `__init__(self, host: str | None, port: str | int | None)`.
`drain_now()` POSTs an empty body to `http://{host}:{port}/drain` with
`urllib.request` and a 5-second timeout, then returns
`json.loads(resp.read())["performed"]`.

- Use **stdlib `urllib`**, not `httpx`: `httpx` is installed only in the
  Dockerfile's `test` stage, and `root.py` already reaches for `urllib` for the
  same reason.
- If `host` or `port` is falsy, raise `RuntimeError("WORKER_HOST/WORKER_PORT not set")`.
- Let failures raise. The driving adapter translates any exception to 503, which
  is `cont_jobs_http.py`'s existing pattern; do **not** invent a bespoke exception
  type for one call site.
- The address is **injected**, never read from `os.environ` here — only the
  composition root reads the environment.

Docstring must state that `WORKER_HOST` / `WORKER_PORT` are resolved by the
compiler from the five-segment magic refs
`${codebases.api.core_services.worker.{host,port}}` declared on `api.web` (docker
network DNS on fixed, ECS Service Connect on elastic, one env var name either
way), and that **holding those refs is what obliges the `api.worker` entry in
`api.web`'s `uses:`** (rule 7) *and* what makes the worker "directly addressed",
which is what obliges the worker's `port` (rule 32's positive arm). This adapter
is the reason those three declarations are true rather than decorative.

### 2.4 `ports/driving/cont_job_drain.py` — consumer side (new)

`ContJobDrain(Protocol)` with `drain_now(self) -> int`.

Docstring must carry the **reason this is a separate port** rather than a method
on `ContJobs`, because that is the reader's first question and the answer is
load-bearing: `ContJobs` is the port **`api.clock` holds**. A `drain()` on it
would hand the clock the ability to trigger performance, which is exactly what
`clock.md § The clock defers; it does not work` forbids. Three extra files are the
cheaper mistake to avoid.

### 2.5 `alogic/job_drain_service.py` — consumer side (new)

`JobDrainService` implementing `ContJobDrain`, holding a `GwyJobRunner` injected
by constructor. `drain_now()` returns `self._gateway.drain_now()`.

Docstring must **own the thinness honestly**: this is a one-line delegation and
that is correct. The alogic layer is where the operation is *named* and where the
driving port is implemented; inventing logic to justify the file would be adding
behaviour the project does not have. The port/adapter pair on either side is
carrying the design, and this is the seam that keeps `api.web`'s controller from
knowing that a sibling process exists.

### 2.6 `adapters/driving/cont_job_drain_http.py` — consumer side (new)

`ContJobDrainHttp`, `APIRouter`, one route `POST /jobs/drain`, `status_code=200`,
`response_model=_DrainResult(performed: int)`. Handler calls
`self._service.drain_now()` and wraps `except Exception` into
`HTTPException(503, f"worker unreachable: {exc}")`.

Handler docstring: purpose, no request body, `{"performed": N}` at 200,
`performed: 0` is a success (same wording as 2.1), 503 means the worker could not
be reached and **nothing was drained** — the caller may retry, and the worker's
own poll loop will drain the queue regardless.

---

## 3. `fixed/core/api/src/root.py`

1. **Delete** the `/health/api/worker` handler entirely, including its docstring
   and the `# Health fan-out.` comment block above it.
2. **Prune imports** to what remains: `json` becomes unused → delete;
   `urllib.error` / `urllib.request` are still used by `/diagnostics/probe` →
   keep; `socket` still used by `/diagnostics/events` → keep.
3. **Rewrite the `WORKER_HOST` / `WORKER_PORT` comment.** It currently says the
   refs are "used by the /health/api/worker fan-out". They now address
   `api.worker`'s `rpc` surface for an application reason. Keep the sentence about
   rule 7 obliging the `uses:` entry; add that direct addressing is what obliges
   the worker's `port` under rule 32's positive arm.
4. **Rename the two diagnostics routes**, keeping their bodies unchanged:
   - `@app.get("/health/probe")` → `@app.get("/diagnostics/probe")`
   - `@app.get("/health/events")` → `@app.get("/diagnostics/events")`
   - rename the functions `health_probe` → `diagnostics_probe`,
     `health_events` → `diagnostics_events`.
   - **Rewrite the comment above them** to say what they are and are not: these
     are `api.web` probing the reachability of two **backing** services
     (`probe`/`sidecar`, `events`/`clickhouse`) — the only exercise either seed
     gives those project-local engines, and on elastic the only exercise of SG
     reachability to them. They are **not** the health fan-out and not a report on
     another core service; `healthchecks.md` forbids that and it is deleted. They
     were moved out of `/health/*` precisely so no future reader concludes
     otherwise.
5. **Leave `GET /health` exactly as it is**, but replace its comment. It is no
   longer "doctrine-mandated for every long-running core service"; it survives
   because `api.web` is on the `web` network, the reverse proxy probes it there
   (`health_check_path: /health`), and the project's own stage tests assert its
   body against `PROJECT_VERSION`. Cite `healthchecks.md § web services also serve
   GET /health`.
6. **Factor the job-runner wiring** so it exists once. Add a private
   `_job_runner_service() -> JobRunnerService` holding what `build_job_runner`
   currently builds (queue, retention repo, `RetentionWindow`, `JobRunnerService`),
   and have `build_job_runner()` return `ContJobRunnerCli(service=_job_runner_service())`.
   Comment the helper: two copies of this wiring is the drift the composition root
   exists to prevent, which is the same argument rule 3 of
   `internal_dependency_rules.md § Entrypoints` makes against splitting the root.
7. **Add `build_job_runner_http() -> ContJobRunnerHttp`**, returning
   `ContJobRunnerHttp(service=_job_runner_service())`. Docstring: constructs
   `api.worker`'s `rpc` surface adapter; `entrypoints/worker.py` binds it to
   uvicorn, because the runtime host is not an adapter.
8. **In `build_app()`**, after the existing `cont_jobs` router include, construct
   and mount the drain controller:
   `GwyJobRunnerHttp(host=WORKER_HOST, port=WORKER_PORT)` →
   `JobDrainService(gateway=...)` → `ContJobDrainHttp(service=...)` →
   `app.include_router(...)`. Comment that the gateway is constructed even when
   `WORKER_HOST` is unset (construction performs no I/O — it fails only when
   called), which is what keeps `build_app()` usable from
   `tests/test_smoke.py` in the `test` container.
9. Add the six new imports.

---

## 4. `fixed/core/api/src/entrypoints/worker.py`

**Delete:** `_build_health_app`, its `/health` route, `_STALENESS_SECONDS`,
`_HEALTH_PORT`, and the `HTTPException` import.

**Keep and retarget `_Tick`** to a file:

```py
# The tick is a FILE, not an in-memory float: the probe is `./health.sh worker`,
# which docker and ECS run as a SEPARATE PROCESS, so the tick has to live
# somewhere that process can stat (healthchecks.md § What the probe must
# actually check). `/tmp` is tmpfs-backed wherever the core service declares
# `disk:`, so this is a memory write rather than a disk write once a second.
_TICK_PATH = Path("/tmp/worker.tick")


class _Tick:
    """The loop's liveness signal, observable from another process."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def bump(self) -> None:
        # `touch` both creates the file and re-stamps its mtime, which is the
        # whole of the signal — the CONTENT is never read.
        self._path.touch()
```

- `_tick = _Tick(_TICK_PATH)` at module scope.
- **The file is deliberately not created at startup.** The old `_Tick.__init__`
  pre-seeded liveness with `time.monotonic()`; the file version must not, because
  `health.sh`'s absent-file arm is what catches a loop that never started. Say
  this in a comment.
- The bump site is unchanged: still on the `else:` branch of the loop's `try`, so
  a failing iteration still withholds the tick. **Keep that WHY comment verbatim.**

**Replace the health server with the `rpc` surface's server.** Constants:

```py
# `api.worker`'s `rpc` surface. Must match infra.yml's `port: 8081` on this core
# service — nothing injects it, so the two are coupled by convention, as in
# web.py.
_RPC_PORT = 8081
```

`main()` still starts uvicorn on a daemon thread, and the WHY comment must be
rewritten so the diff is not misread:

- This thread is **not** the health server under a new name. Liveness is the tick
  file and does not involve this thread at all — kill the server and the probe
  still tells the truth.
- It exists because `api.web` **calls** this boundary (`POST /drain`), which is an
  application call, not a probe.
- The loop stays in the **main** thread and the server in the daemon thread, for
  the reason already written: signals are delivered to the main thread and it is
  the loop that must hear SIGTERM; a daemon thread also needs no join.

Build the app in the entrypoint, not the root — the runtime host belongs here:

```py
runner_http = build_job_runner_http()
rpc_app = FastAPI(title="api-worker-rpc", version=VERSION)
rpc_app.include_router(runner_http.router)
```

**Module docstring rewrite.** It currently says the file owns "the liveness
surface that proves it is still turning" and cites `contracts.md § Health Checks`
for a 10s/30s pair. New text must say: the file owns the poll loop, the signal
handling that stops it, the **monotonic tick file** that the container probe
stats, and the runtime host for the core service's `rpc` surface. State that the
**cadence** (a tick at least every 10s even when idle — which `_POLL_INTERVAL_SECONDS`
satisfies with room to spare) lives here and the **threshold** (30s) lives in
`health.sh`, that both are doctrine-fixed with no per-project knob, and that the
two numbers only mean something as a pair. Cite
`healthchecks.md § What the probe must actually check`.

Also update the loop's `logger.info("processor: starting loop (interval=%.2fs, health on :%d)…")`
line — it advertises a health port that no longer exists. Report the tick path and
the rpc port instead.

---

## 5. `fixed/core/api/src/entrypoints/clock.py`

The clean case, and the file a reviewer should be pointed at first: **the clock
ends this mod listening on nothing.**

**Delete:** `_build_health_app` and its route, `_STALENESS_SECONDS`,
`_HEALTH_PORT`, the `uvicorn.Server(...)` + `threading.Thread(...)` block in
`main()`, and the `uvicorn` and `fastapi` imports outright.

**Retarget `_Tick`** exactly as in step 4, with `_TICK_PATH = Path("/tmp/clock.tick")`.

**Unchanged:** `_load_schedules`, the `cron.unbound(schedules)` startup gate and
all three of its WHY comments, the forward-only `next_at` seeding, the
`if not due or failures < len(due): _tick.bump()` rule and its comment,
`_stop.wait(_TICK_INTERVAL_SECONDS)`.

`_TICK_INTERVAL_SECONDS = 5.0` keeps its comment, edited: it still explains that
the bounded wait is the whole of the liveness mechanism, but the mechanism is now
a touched file rather than a served route, and the threshold it must stay inside
lives in `health.sh`. Cite `healthchecks.md` rather than `contracts.md § Health
Checks`.

**Module docstring:** replace "the liveness surface that proves it is still
turning" with the tick file, and add one sentence stating that a clock runs **no
HTTP server at all** — it takes no ingress, nothing addresses it, and it declares
no `port` and no surface, so its probe is `./health.sh clock` reading the tick and
nothing else. Update the `"clock: starting loop (tick=%.1fs, health on :%d)"` log
line the same way as step 4.

---

## 6. `fixed/core/api/Dockerfile`

1. **Header comment** — "`api.worker` (poll loop + liveness server) and
   `api.clock` (cron loop + liveness server)" is now wrong twice. `api.worker` is
   a poll loop plus an `rpc` surface; `api.clock` is a cron loop and nothing else.
2. **The `curl` comment block (lines ~11–25) is replaced.** Every claim in it is
   now false: the emitted probe is `["CMD", "./health.sh", "<service>"]`, not
   `curl -f http://localhost:${port}${path}`; `health_check_path` no longer exists
   on `worker`/`clock`; the `docex check` curl gate is gone; and the "Doctrine
   improvement TODO: switch the emit to a tool-free probe" has happened. New
   comment: `curl` is here because **`health.sh`'s `web` arm uses it** — an image
   needs whatever its own probe needs and nothing more
   (`healthchecks.md § The probe`). Keep the still-true fact that
   `python:3.12-slim` ships no curl.
3. **The `fastapi` / `uvicorn` comment** keeps the packages and changes the
   *reason*: they serve `api.web`'s `rest` surface and `api.worker`'s `rpc`
   surface. They are no longer a liveness dependency anywhere, and `api.clock`
   needs neither — it receives them only because one image carries one dependency
   set.
4. **`dev` stage:** `COPY build.sh migrate.sh test.sh health.sh /service/`. The
   existing `RUN chmod +x /service/*.sh` already covers it.
5. **`prod` stage:** `COPY migrate.sh health.sh /service/` and
   `RUN chmod +x /service/migrate.sh /service/health.sh`. This is the load-bearing
   half — `prod` is the image `stage` and `prod` actually run, and it currently
   ships no probe at all. (`test` derives `FROM prod` and inherits it.)
6. **`EXPOSE 8080 8081`** in both `dev` and `prod`; drop `8082`. Update the
   trailing comment: 8080 for `api.web`'s rest surface, 8081 for `api.worker`'s
   rpc surface, and `api.clock` listens on nothing.

---

## 7. `fixed/core/api/tests/` — two new tests

Add to a new `test_jobs_drain.py`. Both are stub-backed on purpose: the `test`
env runs a live `api.worker` and `api.clock` competing for the same rows, so an
agency-shaped assertion against the real DB is wrong by construction
(`test_projects.md § The test env has no sole actor`). Follow
`test_jobs_alogic.py`'s existing stub idiom.

1. **`JobDrainService` over a stub gateway** — `drain_now()` returns the
   gateway's count and calls it exactly once.
2. **`ContJobRunnerHttp` translation** — with a stub `ContJobRunner` whose
   `run_once()` returns 3, `POST /drain` via `fastapi.testclient.TestClient`
   returns 200 and `{"performed": 3}`; with a stub that raises, it returns 503.
   This is a driving-adapter test in the doctrine's sense: it verifies
   *translation*, not downstream behaviour (`hex_overview.md § Tests`).

Do not add a `test_smoke.py` case for `/jobs/drain`: `build_app()` in the `test`
container has no reachable worker, and the stage test (step 10) covers the live
edge.

---

## 8. Mirror `core/` into `elastic` and prove byte-identity

```
cd docex/test_projects
cp fixed/core/api/health.sh                      elastic/core/api/health.sh
cp fixed/core/api/Dockerfile                     elastic/core/api/Dockerfile
cp fixed/core/api/src/root.py                    elastic/core/api/src/root.py
cp fixed/core/api/src/entrypoints/worker.py      elastic/core/api/src/entrypoints/worker.py
cp fixed/core/api/src/entrypoints/clock.py       elastic/core/api/src/entrypoints/clock.py
cp fixed/core/api/tests/test_jobs_drain.py       elastic/core/api/tests/test_jobs_drain.py
mkdir -p elastic/core/api/src/hex/jobs/{ports/{driving,driven},adapters/{driving,driven},alogic}
for f in ports/driving/cont_job_drain.py ports/driven/gwy_job_runner.py \
         adapters/driving/cont_job_runner_http.py adapters/driving/cont_job_drain_http.py \
         adapters/driven/gwy_job_runner_http.py alogic/job_drain_service.py; do
  cp "fixed/core/api/src/hex/jobs/$f" "elastic/core/api/src/hex/jobs/$f"
done
chmod +x elastic/core/api/health.sh
```

Then **verify** — this is audit box B.14's own check and it must be clean:

```
diff -rq -x dist fixed/core elastic/core   # expect NO output, rc 0
```

If it reports anything, fix by re-copying from `fixed`, never by editing
`elastic`.

---

## 9. `infra.yml` — edit each project separately

The two files differ legitimately by foundation. Make the same *structural*
changes in each and preserve each file's own foundation-specific prose.

### `api.web`

- Add, indented under the core service beside `uses:`:
  ```yml
        surfaces:
          rest:
            api_styles: [rest]
  ```
  with a comment: one surface, one contract file
  (`api.web.rest.openapi.yml`); declaring a surface is what makes a core service
  a provider (`cicl.md § Surfaces`).
- Keep `port: 8080`, keep `health_check_path: /health`, and rewrite that field's
  comment: rule 33 **requires** it on a `web`-network core service, because it is
  what the reverse proxy reads (the ALB target group on elastic, the project
  traefik on fixed). Keep each project's existing foundation-specific sentence.
- Rewrite the `uses:` comment: drop "`api.web` proxies the worker's liveness at
  /health/api/worker and therefore speaks to that boundary". Replace with: the
  dotted entry names a core service, and `api.web` speaks to `api.worker`'s `rpc`
  surface (`POST /drain`) for an application reason. Keep the one-direction
  justification.
- Rewrite the `SIDECAR_*` / `CLICKHOUSE_*` comment's "only the web edge exposes
  /health/{probe,events}" → `/diagnostics/{probe,events}`. The rule-7 reasoning
  after it is unchanged and stays.
- Rewrite the `WORKER_HOST` / `WORKER_PORT` comment: the refs address the worker's
  `rpc` surface, not a fan-out. Holding them obliges the `api.worker` entry in
  `uses:` (rule 7) **and** makes the worker directly addressed, which is what
  obliges its `port` (rule 32's positive arm).

### `api.worker`

- **Keep `port: 8081`** and rewrite its comment. It is no longer "a port purely
  for the liveness probe". It is the address at which `api.web` reaches the `rpc`
  surface — rule 32's positive arm — and on elastic it is also what registers the
  Service Connect name, without which `release`'s consumer reconcile has nothing
  to compare against. Keep the "a worker is never routed / rule 15 doesn't apply"
  clause, which is still true.
- **Delete `health_check_path: /health`.** Rule 33 forbids it off the `web`
  network, and `tables/roles/worker.yml` now declares `fields: {}`, so it also
  trips `tt_rule_4_undeclared_field`.
- Add:
  ```yml
        surfaces:
          rpc:
            api_styles: [rpc]
          events:
            api_styles: [events]
  ```
  with a comment covering three things: (a) **two surfaces, one format** — legal,
  and what makes them two rather than one is the *consumers*: `api.web` calls the
  rpc boundary synchronously, while the queues are produced onto by `api.web` and
  `api.clock` and consumed here; (b) both queues (`pings`, `jobs`) live in the
  **one** `events` document, per `cicl.md § Surfaces`'s split table — *"a worker
  consuming two different queues: one core service, one surface"*; (c) the two
  contract files this produces.
- `replicas: 2` and its comment are unchanged.

### `api.clock`

- **Delete `port: 8082` and `health_check_path: /health`.**
- Replace the long comment that justified them. New text: a clock takes no ingress
  (rule 27 forbids `web` in its networks), nothing `uses` it, and nothing
  addresses it — so it declares **no port, no `health_check_path`, and no
  surface**. Its liveness is `./health.sh clock` reading the loop's tick file,
  which the orchestrator runs and acts on (docker `healthcheck:` on fixed / ECS
  container health on elastic — keep each project's own wording). Keep the point
  that this enforcement is real but local: staging tests cannot reach it
  (`clock.md § Caveats`).
- Rewrite the `uses: [appdb, api.worker]` comment so the **asymmetry is explicit**
  rather than left to be inferred: `api.worker` has **two** consumers reaching it
  **two different ways** — `api.web` holds magic refs and calls it directly, while
  this clock holds **no ref** and reaches it through the `jobs` table. That is the
  case rule 32 is edge-scoped for: the same target is "directly addressed" on one
  edge and not on the other, and a per-target rule could not express it. Keep "a
  ref implies an edge, never the reverse".
- `schedules:` and `resources:` unchanged.

### Verify

```
cd docex/test_projects/fixed   && ./bin/docex compile   # expect rc 0
cd ../elastic                  && ./bin/docex compile   # expect rc 0
```

Both currently fail with **6 validation errors each** (rule 31 ×2, rule 33 ×2,
`tt_rule_4_undeclared_field` ×2). Record the before and after in the mod report.

`compile` will rewrite files under `infra/output/`. **Leave them.** Mod 130 owns
that diff; do not revert it and do not review it.

---

## 10. Contracts

Work in each project's `infra/contracts/`. Use `git mv` **only in the outer repo**
— i.e. plain `mv`/`cp` is fine; do not run git commands inside `test_projects/`.
Three files must exist per project when you are done, and **nothing else**:
`_gate_contracts`' orphan arm fails on any leftover file that parses as a contract
name.

| Was | Becomes |
| --- | --- |
| `api.web.openapi.yml` | `api.web.rest.openapi.yml` |
| `api.worker.asyncapi.yml` | `api.worker.events.asyncapi.yml` |
| — | `api.worker.rpc.asyncapi.yml` |

The only differences between the two projects' contracts are `info.title`
(`docex_smoke_fixed` / `docex_smoke_elastic`) and the `servers:` URLs
(`docex-smoke-fixed` / `docex-smoke-elastic`). Write `fixed`'s, copy, then
substitute those two strings.

### 10.1 `api.web.rest.openapi.yml`

- **Bump `openapi: "3.0.3"` → `"3.2.0"`.** `contracts.md § Standards` fixes
  OpenAPI 3.2 or later as the minimum. Nothing enforces this mechanically — that
  gap is written up at
  [`007_small_edges/contract_spec_version_ungated.md`](../../advances/007_small_edges/contract_spec_version_ungated.md)
  and is not this mod's to close.
- **Replace the entire header comment** (currently sixteen lines documenting the
  three-segment path scheme and the fan-out mandate, and adjudicating which of
  three `/health` sub-paths are doctrine-required). New header states: the path is
  `<codebase>.<service>.<surface>.<format>.<ext>` and this file is the `rest`
  surface of `api.web`; `GET /health` belongs here because `api.web` is on the
  `web` network **and** declares an `openapi` surface, which is the one case
  `healthchecks.md § web services also serve GET /health` describes and
  `docex check`'s `contract_health_path` gate asserts; the `/diagnostics/*` paths
  are backing-service reachability probes and are **not** a health fan-out —
  there is no fan-out, `healthchecks.md § What this doctrine does not do` forbids
  one, and these were moved out of `/health/*` so nobody reads them as its
  remnant.
- **Update `info.description`**: `/health/{probe,events}` →
  `/diagnostics/{probe,events}`; delete "…`/health/api/worker` is the
  doctrine-required liveness fan-out onto the worker" and replace with the drain
  route's one-line purpose.
- **Delete the whole `/health/api/worker` path item** and the two-line comment
  above it.
- **Rename** `/health/probe` → `/diagnostics/probe` (`operationId: healthProbe` →
  `diagnosticsProbe`) and `/health/events` → `/diagnostics/events`
  (`healthEvents` → `diagnosticsEvents`). Bodies unchanged. Update each
  `summary:` to say "backing-service reachability" rather than anything with
  "health" in it.
- **`GET /health`, `POST /pings`, and the two `/jobs/*` deferral routes are
  unchanged**, including the long comments justifying one-route-per-job and 202.
- **Add `POST /jobs/drain`:** 200 → `{performed: integer}` (required), 503 →
  "the worker could not be reached; nothing was drained". `operationId: drainJobs`.
  Its `description` must say what the route is *for* — `api.web` asks
  `api.worker` to drain the deferred-job queue now, because the perform side of
  the queue belongs to the worker and an edge that drained it itself would be
  performing rather than deferring — and that **`performed: 0` is a success**.

### 10.2 `api.worker.events.asyncapi.yml`

Structural rewrite. **`asyncapi: "2.6.0"` → `"3.0.0"`** per `contracts.md`, which
means channels carry an `address` and `messages`, and operations move to a
top-level `operations:` block with `action: receive`:

```yml
channels:
  pings:
    address: pings
    messages:
      ping: { ... }
  jobs:
    address: jobs
    messages:
      job: { ... }

operations:
  consumePing:
    action: receive
    channel: { $ref: '#/channels/pings' }
  performJob:
    action: receive
    channel: { $ref: '#/channels/jobs' }
```

- **Every payload schema, every property, and every property description carries
  over verbatim.** The 2.6 → 3.0 move is a restructure, not a re-specification;
  do not drop or reword field documentation while moving it.
- **Keep the "known loose end" block** — AsyncAPI naturally describes a broker,
  this worker has none, its queues are postgres tables, and the honest channel
  address is a table name. It is still true and still the most useful paragraph in
  the file. Edit only its dated framing ("1.6.0 ships a first-class `worker` role
  with no first-class thing for it to consume" / "provably unreachable before mod
  101").
- **Delete the "what is deliberately ABSENT" block** at the end of the header. Its
  three claims are all retired: it justifies the missing `/health` via `port` +
  `health_check_path`, cites `contracts.md § Declared by fields` (deleted), and
  points at `/health/api/worker` in the consumer's OpenAPI (deleted). Replace with
  one sentence: this surface describes the queues this core service **consumes**;
  its request/reply boundary is a **separate surface** in
  `api.worker.rpc.asyncapi.yml`, and its liveness is a container probe that no
  contract describes.
- Header "why this file exists" must stop keying the format on `role`. The format
  follows from the surface's `api_styles: [events]`, and the file exists because
  the surface is declared.

### 10.3 `api.worker.rpc.asyncapi.yml` — new

`asyncapi: "3.0.0"`. One channel, one operation with a `reply` — which is the
`rpc` style's whole reason for resolving to `asyncapi`
(`cicl.md § Surfaces`, and it is why 3.0 is the floor):

```yml
channels:
  drain:
    address: /drain
    messages:
      drainRequest: { ... }   # empty object body
      drainResult:  { ... }   # { performed: integer }

operations:
  drainQueue:
    action: receive
    channel: { $ref: '#/channels/drain' }
    reply:
      channel: { $ref: '#/channels/drain' }
      messages:
        - $ref: '#/channels/drain/messages/drainResult'
```

- `servers:` — one entry, the internal address, `protocol: http`. Comment that
  HTTP is the *transport* and `rpc` is the *api_style*: different axes, and the
  contract format keys on the second. This is MCP's case.
- Header must state: this is the surface `api.web` **addresses directly**, which
  is what obliges this core service's `port` under rule 32's positive arm — and
  that the same core service's *other* consumer, `api.clock`, reaches it through
  the `jobs` queue instead and holds no address at all. One target, two consumers,
  two kinds of edge.
- Document that `performed: 0` is a success and why (the worker's own loop drains
  on its interval).

---

## 11. `infra/stage/tests/test_smoke.py` — edit each project separately

The two files differ: `fixed` uses a module-level `_client = httpx.Client(...)`,
`elastic` calls `httpx.get(..., timeout=10)` inline. **Preserve each file's own
idiom** — that divergence is pre-existing and unifying it is not this mod's work.

1. **Delete `test_health_fanout_reports_worker_liveness` entirely**, including its
   docstring.
2. **Rewrite the module docstring.** Its first bullet is liveness. New text:
   staging tests assert only what requires being **outside** — TLS/DNS
   reachability, reverse-proxy routing, and critical-path smoke tests — and they
   assert **nothing** about liveness, because `docex stagetest` reads every core
   service's health and version from the orchestrator before the tester image is
   even built. They also cannot reach a non-`web` core service at all. Cite
   `healthchecks.md § What this doctrine does not do` and `tests.md § Staging
   Tests`. Drop the `api.clock` paragraph's claim that it "serves /health like any
   core service" — it serves nothing; keep the point that nothing out here can
   reach it. Replace the `/health/{probe,events}` paragraph's paths.
3. **Retarget and rename the two backing-reachability tests:**
   `test_health_probe_reaches_sidecar` → `test_diagnostics_probe_reaches_sidecar`
   at `/diagnostics/probe`; `test_health_events_reaches_clickhouse` →
   `test_diagnostics_events_reaches_clickhouse` at `/diagnostics/events` (keep its
   longer timeout). Their docstrings' claims about what they prove are unchanged
   and still true.
4. **Unchanged:** `test_health_endpoint` (the `PROJECT_VERSION` assertion) and
   `test_create_ping_round_trip`.
5. **Add `test_defer_and_drain_round_trip`:**

   ```py
   def test_defer_and_drain_round_trip() -> None:
       """Drive the public edge and observe a worker doing work.

       tests.md's prescribed shape for a scenario that must exercise a
       non-`web` core service: drive the real ingress and observe the effect.
       `POST /jobs/drain` satisfies it synchronously — the worker's OWN reply
       travels back out through the edge — so nothing has to be read back
       later, which matters because neither seed has a route that can read a
       job back.

       A 200 here means the five-segment magic refs resolved to a reachable
       address and `api.web` reached a non-`web` sibling core service across
       its declared `rpc` surface: docker network DNS on fixed, ECS Service
       Connect on elastic. It means nothing about liveness — that is the
       orchestrator's to report, and `docex stagetest` has already read it.
       """
       deferred = <post to /jobs/heartbeat>
       assert deferred.status_code == 202, deferred.text
       assert "job_id" in deferred.json()

       drained = <post to /jobs/drain, timeout 15>
       assert drained.status_code == 200, drained.text
       # NO EXACT COUNT, deliberately. `api.worker` drains on its own poll
       # interval, so by the time this call lands the heartbeat above may
       # legitimately already be gone and `performed: 0` is the honest answer.
       # The load-bearing assertion is the 200 itself, on a route that cannot
       # answer without reaching the worker. An order-dependent count would
       # pass on a dev machine and fail on the walk, which is the worst
       # signature a smoke test can have.
       performed = drained.json()["performed"]
       assert isinstance(performed, int) and performed >= 0
   ```

   Write it in each file's own httpx idiom.

---

## 12. Final verification

Run and record all of it in the mod report.

```
# a. compile, both projects — the mod's primary signal
cd docex/test_projects/fixed  && ./bin/docex compile ; echo "fixed rc=$?"
cd ../elastic                 && ./bin/docex compile ; echo "elastic rc=$?"

# b. the two core trees are still byte-identical (audit box B.14)
cd docex/test_projects && diff -rq -x dist fixed/core elastic/core ; echo "rc=$?"

# c. exactly three contracts per project, correctly named
ls fixed/infra/contracts elastic/infra/contracts

# d. every retired spelling is gone from both seeds
grep -rn "health/api/worker\|fan-out\|fanout\|_build_health_app\|_HEALTH_PORT\|_STALENESS_SECONDS\|health/probe\|health/events" \
  fixed elastic 2>/dev/null | grep -v 'infra/output/\|/dist/\|__pycache__\|\.git/\|\.pytest_cache\|plans/core/\|CHANGELOG'
# expect NO hits. plans/core and CHANGELOG are excluded because they are mod 130's.

# e. health.sh is executable in both trees and rejects a bad argv
for p in fixed elastic; do
  test -x $p/core/api/health.sh && echo "$p health.sh executable"
  sh $p/core/api/health.sh nonesuch; echo "$p bad-argv rc=$?"   # expect 2
done

# f. docex's own suite is untouched by this mod — run it ALONE
cd docex && pytest tests -q        # expect 1174 passed, 18 deselected
```

**(f) must be unchanged at 1174.** Nothing in `docex/tests/`, `src/`,
`pyproject.toml`, or the Makefile references `test_projects/`, so a moved count
means something reached outside this mod's territory. If it moves, stop and report
rather than adjusting a test.

Do **not** run `pytest -m integration` concurrently with (f); concurrent pytest
processes in this repo manufacture convincing false failures.

## 13. Out of scope — do not do these

- Any `git` command inside `test_projects/` (commit, tag, branch, checkout).
- Reverting or reviewing `infra/output/**`, which step 9's `compile` will churn.
- Either project's `plans/core/*`, `CHANGELOG.md`, or `README.md`.
- `PRE_CUT_CHECKLIST.md`, `docex/plans/core/*`, `doctrine_excerpts/` — mod 131.
- Any file under `doctrine/`.
- Building the contract spec-version gate. It is written up as a future brief;
  mod 126 owned `check.py`'s contract gate and is closed.
- Bringing up a dev stack or exercising the probe live. The mod's owner does that
  in the review step, deliberately, because the criterion is *observed failing*.

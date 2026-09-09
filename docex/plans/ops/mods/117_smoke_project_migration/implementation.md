# Mod 117 — Implementation Steps

Migrate both smoke-test projects off the deleted `role: scheduler` and onto
`role: clock`. Design rationale is in [`overview.md`](./overview.md); this file
is the executable plan and assumes no prior context.

## Ground rules

- **Absolute paths only.** The two project roots are:
  - `FIXED   = /home/ubuntu/.claude/jean_baudrillard/docex/test_projects/fixed`
  - `ELASTIC = /home/ubuntu/.claude/jean_baudrillard/docex/test_projects/elastic`
- **`$FIXED/core` and `$ELASTIC/core` must stay byte-identical.** Write every
  source file **once** under `$FIXED/core/api/src`, then copy the whole tree
  across. Never hand-edit the same file twice. `infra.yml`, `verify_clean.sh`,
  `CHANGELOG.md`, `project.yml` and `plans/` legitimately differ; **nothing
  under `core/` may.**
- **Do not touch** `PRE_CUT_CHECKLIST.md`, `docex/plans/core/test_projects.md`,
  `upgrades/upgrade_2.0.0.md`, or the root `CHANGELOG.md`. Those are Mod 120.
- **Do not touch** either project's `plans/core/**` or `CHANGELOG.md`. The
  mod-developer writes those in the documentation step.
- **Do not commit.** The mod-developer owns the inner/outer commit cadence.
- **No `docex` source changes in this mod.** The binding-coverage `check` gate is
  escalated and held — see `overview.md § The binding-coverage seam`.

### Compiling without rebuilding the docex image

The projects pin `docex_version: "1.6.0"`, but the compiler under development is
the working tree. Run it from source, from inside a project root:

```sh
cd $FIXED && PYTHONPATH=/home/ubuntu/.claude/jean_baudrillard/docex/src \
  python3 -m docex compile
```

The `project pins docex_version '1.6.0', but this is docex 1.6.1` warning is
expected and harmless. Right now this command fails with
`codebases.reaper.core_services.prune: core service 'reaper.prune' uses unknown
role 'scheduler'` — that is the starting state this mod removes.

---

## Step 1 — Delete `reaper`

In **both** projects:

1. `rm -rf <root>/core/reaper` (the whole tree: `src/`, `dist/`, `tests/`,
   `Dockerfile`, `build.sh`, `test.sh`).
2. Delete the entire `reaper:` codebase block from `<root>/infra/infra.yml`
   (fixed `:94-120`, elastic `:107-134` — the leading comment block goes too).
3. `<root>/teardown.sh` and `<root>/verify_clean.sh`: `for service in api reaper`
   → `for service in api`. Update the adjacent comment that says "exactly as
   `reaper` did before mod 107" — it now names a codebase that does not exist;
   rewrite it to say the loop covers every codebase and there is currently one.
4. `$ELASTIC/verify_clean.sh` — **delete** the `aws scheduler list-schedules`
   leak check (currently `:206-209`, the `schedules=` assignment plus its
   `if`). EventBridge Scheduler is no longer an emit target on any foundation,
   so this is one fewer AWS resource type that can leak.
5. `$ELASTIC/infra/infra.yml` — the `container_registry` comment says "`api` and
   `reaper` get one each regardless of core-service count". Rewrite for one
   codebase; keep the point that the repo is keyed on the **codebase**, not the
   core-service count, since that is what the sentence exists to say.

Do **not** delete the historical `reaper` mentions in either `CHANGELOG.md` —
past entries were true when written. (The mod-developer will remove only the
entries that describe *current* state.)

---

## Step 2 — `hex/retention` (the reaper's module, transplanted)

New module at `$FIXED/core/api/src/hex/retention/`, mirroring the deleted
`reaper` module. Standard layout with `__init__.py` in every directory.

| File | Contents |
| --- | --- |
| `domain/retention_window.py` | `RetentionWindow` — copy verbatim from the deleted `reaper/src/hex/reaper/domain/retention_window.py` (frozen dataclass, positive-days invariant, `cutoff(now)`) |
| `ports/driven/repo_pings.py` | `RepoPings` Protocol — `delete_processed_before(cutoff: datetime) -> int` |
| `adapters/driven/repo_pings_postgres.py` | `RepoPingsPostgres` — copy from the deleted reaper adapter. Keep its docstring's point that this is a *parallel* implementation to `pings`'/`processor`'s repos, since hex modules never share code |
| `ports/driving/cont_retention.py` | `ContRetention` Protocol — `prune() -> int` (returns rows deleted) |
| `alogic/retention_service.py` | `RetentionService(repo, window, clock=…)` implementing `ContRetention.prune()` — the deleted `ReaperService.reap()` renamed. Keep the injected clock callable; it is what keeps the operation deterministic in tests |

The 30-day retention constant stays a **composition-root** wiring decision (it
was `_RETENTION_DAYS` in the deleted `reaper/src/root.py`); move it to
`$FIXED/core/api/src/root.py`, not into the module.

---

## Step 3 — `hex/jobs` (the queue, both halves)

New module at `$FIXED/core/api/src/hex/jobs/`.

### 3.1 Domain

`domain/job.py` — `Job` entity:

```py
@dataclass
class Job:
    id: UUID
    name: str
    enqueued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
```

Give it the two state transitions rather than letting callers mutate fields:
`start(at)` (illegal if already started) and `finish(at, error=None)` (illegal if
not started). These are the module's invariants and they belong in the domain,
not in alogic.

### 3.2 Driven port + adapter — the canonical `Queue` pattern

`ports/driven/queue_jobs.py` — `QueueJobs` Protocol:

```py
def enqueue(self, name: str) -> UUID: ...
def claim(self, limit: int) -> list[Job]: ...
def complete(self, id: UUID, at: datetime) -> None: ...
def fail(self, id: UUID, at: datetime, error: str) -> None: ...
```

`adapters/driven/queue_jobs_postgres.py` — `QueueJobsPostgres(dsn)`, psycopg2,
same connection style as the existing repos.

**`claim()` is the load-bearing one.** One transaction:

```sql
SELECT id, name, enqueued_at FROM jobs
 WHERE started_at IS NULL
 ORDER BY enqueued_at ASC
 LIMIT %s
   FOR UPDATE SKIP LOCKED
```

then `UPDATE jobs SET started_at = %s WHERE id = ANY(%s)`, then commit. Both
statements **must** be in the same transaction and on the same connection — a
`SELECT … FOR UPDATE` whose transaction ends before the `UPDATE` holds no lock
and the whole guarantee evaporates.

Write a `WHY:` comment on the lock clause covering both halves:
`FOR UPDATE` gives **exclusivity** (no job claimed twice — `api.worker` runs
`replicas: 2` in prod, so this is a genuine two-consumer race), and
`SKIP LOCKED` gives **liveness** (without it the second worker blocks behind the
first's batch instead of taking different rows). Say explicitly that
`test_jobs_concurrency.py` asserts the first and not the second, so nobody
"simplifies" the clause on the grounds that tests still pass.

### 3.3 Driving ports

`ports/driving/cont_jobs.py` — `ContJobs` Protocol, **one method per job**:

```py
def prune_pings(self) -> UUID: ...
def heartbeat(self) -> UUID: ...
```

Each returns the enqueued job's id. One method per job is what lets the HTTP
adapter expose one route per operation and what makes the cron adapter's table a
*dispatch* rather than a string-keyed side door.

`ports/driving/cont_job_runner.py` — `ContJobRunner` Protocol:
`run_once() -> int` (jobs performed this pass).

### 3.4 Alogic

`alogic/job_service.py` — `JobService(queue: QueueJobs)` implementing `ContJobs`.
Each method is one line: `return self._queue.enqueue("<job_name>")`. **It does no
work**; per `clock.md § The clock defers; it does not work` that is the whole
contract of this side.

`alogic/job_runner_service.py` — `JobRunnerService(queue, retention: ContRetention, batch_size=8)`
implementing `ContJobRunner`:

- `claim(batch_size)`, then for each job look its name up in the
  **perform-side** handler map and call it.
- `complete(id, now)` on success; `fail(id, now, str(exc))` on exception, and
  **continue to the next job** — one poisoned job must not stall the queue.
- A name with no handler is a `fail(...)` with a clear message, not a crash.
- Return the count performed.

Handler map: `prune_pings` → `self._retention.prune()`, `heartbeat` → a logged
no-op returning 0.

`retention: ContRetention` is a **driving port of another module**, which is the
one cross-module import the doctrine allows
(`internal_dependency_rules.md § Cross-Module Imports`). The composition root
injects `RetentionService`.

### 3.5 Driving adapters

`adapters/driving/cont_jobs_cron.py` — **`ContJobsCron`**. The defer-side
dispatch table:

```py
class ContJobsCron:
    JOB_NAMES: tuple[str, ...] = ("heartbeat", "prune_pings")

    @classmethod
    def job_names(cls) -> tuple[str, ...]: ...

    def __init__(self, service: ContJobs) -> None: ...
    def fire(self, name: str) -> UUID: ...
```

Requirements, each load-bearing:

- `JOB_NAMES` is **class-level** and `job_names()` is a **classmethod**, so the
  names are readable with **no service instance, no database, and no
  `DATABASE_*` in the environment**. This is the seam that keeps all three
  binding-coverage outcomes cheap (`overview.md § The binding-coverage seam`);
  do not make it an instance property.
- The instance dispatch map is built in `__init__` from `service`'s bound
  methods and its keys **must** equal `JOB_NAMES`. Assert that in `__init__`.
- `fire(name)` performs the fired / succeeded / failed **translation**: log
  `job fired`, call the port method, log `job deferred` with the returned id, or
  log the failure and re-raise. This translation is why `ContJobsCron` is a real
  adapter rather than ceremony — it is what keeps the entrypoint thin enough to
  satisfy the standing "an entrypoint needing its own test is doing too much"
  rule.

Docstring **must** carry the two-tables paragraph (see Step 8).

`adapters/driving/cont_jobs_http.py` — **`ContJobsHttp`**, a FastAPI router,
**one route per job**:

- `POST /jobs/prune_pings` → `service.prune_pings()`
- `POST /jobs/heartbeat` → `service.heartbeat()`
- Both return `202` with `{"job_id": "<uuid>"}`.

**No dispatch table here, deliberately.** A route is not a name lookup, and one
route per operation is what an OpenAPI contract can actually describe; a single
`POST /jobs/{name}` would make the contract meaningless. Say so in the docstring.
Doctrine requires a full docstring on every externally-accessible controller
function (purpose, args, error states, return shape).

`adapters/driving/cont_jobs_cli.py` — **`ContJobsCli`**, `fire(name)` from argv.
It receives a *name*, so it needs the same map as the cron adapter — the price
of a name-shaped mechanism. Nothing invokes it; the composition root constructs
it anyway because the root instantiates every driving mechanism, including ones
the running core service never uses
(`internal_dependency_rules.md § Composition Root`, item 3). It is also the
"fire a scheduled job by hand" path that the shared driving port buys.

`adapters/driving/cont_job_runner_cli.py` — **`ContJobRunnerCli`**, `run_once()`,
translation only. Model it exactly on the existing `ContProcessorCli`, including
its `WHY:` about not swallowing exceptions: the entrypoint's loop must be able
to tell a failed pass from a zero-work pass, because it may only bump the
liveness tick on a genuine pass.

---

## Step 4 — Migration

New file `$FIXED/core/api/migrations/20260806000000_create_jobs.sql`. Additive
and forward-only; backward compatible with the previous application version
(nothing existing reads or writes this table).

```sql
-- migrate:up
CREATE TABLE IF NOT EXISTS jobs (
    id          uuid        PRIMARY KEY,
    name        text        NOT NULL,
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    started_at  timestamptz NULL,
    finished_at timestamptz NULL,
    error       text        NULL
);

CREATE INDEX IF NOT EXISTS jobs_pending_idx
    ON jobs (enqueued_at)
    WHERE started_at IS NULL;

-- migrate:down
DROP INDEX IF EXISTS jobs_pending_idx;
DROP TABLE IF EXISTS jobs;
```

Both sections are mandatory (checklist B.12).

---

## Step 5 — Composition root

Edit `$FIXED/core/api/src/root.py`. It stays the **only** file that constructs
concrete adapters, and it still constructs without activating — no server, no
socket, no loop.

1. Move `_RETENTION_DAYS = 30` here from the deleted reaper root, with its
   comment explaining it is a wiring decision rather than a doctrine part.
2. `build_app()` — additionally construct `QueueJobsPostgres`, `JobService`, and
   `ContJobsHttp`, and `app.include_router(cont_jobs.router)`.
3. New `build_clock() -> ContJobsCron` — queue → `JobService` → `ContJobsCron`,
   returned un-run.
4. New `build_job_runner() -> ContJobRunnerCli` — queue + `RepoPingsPostgres`
   (retention) + `RetentionWindow(days=_RETENTION_DAYS)` + `RetentionService` →
   `JobRunnerService` → `ContJobRunnerCli`, returned un-run.
5. New `build_jobs_cli() -> ContJobsCli`, constructed for completeness per the
   "every mechanism" rule. Add a short comment saying it is deliberately
   unused by any entrypoint and why that is correct.

Update the module docstring's "one module per core service (`web`, `worker`)"
to name `clock` as well.

---

## Step 6 — `entrypoints/clock.py`

New file `$FIXED/core/api/src/entrypoints/clock.py`. **This is the doctrine's
reference implementation of a clock runtime host** — downstream projects copy
it, so comment it to that standard. Model it on the existing
`entrypoints/worker.py`, which is already the liveness reference.

Shape:

```py
_STALENESS_SECONDS = 30.0   # doctrine-fixed (contracts.md § Health Checks)
_TICK_INTERVAL_SECONDS = 5.0  # bounded, comfortably inside the 10 s ceiling
_HEALTH_PORT = 8082         # must match infra.yml's `port:` on api.clock
```

1. Read **`DOCEX_SCHEDULES_YAML`** from the environment and `yaml.safe_load` it.
   The value is the **literal rendered YAML**, identical on both foundations —
   *not* a path to a file. Do not add a file fallback and do not branch on
   foundation; a comment should say that the single-variable, literal-value
   design is the point (`clock.md § How the schedule reaches the container`).
   Absent or empty ⇒ log and exit non-zero: a clock with no schedule is
   misconfigured, and validation forbids it upstream.
2. Build `next_at` per job with `croniter(expr, start_time=now)` — **from
   process start**, so a clock that was down does not stampede on boot.
   Forward-only, no backfill, per `clock.md § Caveats`.
3. Health server on `_HEALTH_PORT` in a **daemon thread**; the cron loop on the
   **main** thread. Copy `worker.py`'s `WHY:` verbatim in substance: signals are
   delivered only to the main thread and it is the loop that must hear SIGTERM.
4. The loop:
   - for each job whose `next_at <= now`: `cron.fire(name)`, then recompute
     `next_at` from `now`;
   - **bump the monotonic tick every iteration**, fired or not;
   - `_stop.wait(_TICK_INTERVAL_SECONDS)`.
   Comment that the doctrine's 10 s tick / 30 s staleness rule is satisfied *by
   the loop's shape* — a bounded wait — rather than by a separate keepalive, and
   that this is why `clock.md` says a bounded ≤10 s wait is the natural way to
   write one.
5. `/health` reads the **loop's** tick, never the health thread's own aliveness;
   503 once `age > _STALENESS_SECONDS`. Same `WHY:` as `worker.py`: a wedged
   clock must fail its own probe.
6. A firing failure is logged and swallowed so one bad job does not kill the
   loop — **but do not bump the tick on a pass where every fire raised**, for
   the same reason `worker.py` does not.
7. **Seam note.** A short comment: binding coverage (every scheduled name having
   a dispatch entry) is asserted nowhere yet, pending an operator ruling —
   `ContJobsCron.job_names()` is exposed and instance-free precisely so the
   assertion can be added cheaply either in the entrypoint or in `docex check`.
   Frame it as a recorded decision, not a TODO.

---

## Step 7 — Existing files

### 7.1 `$FIXED/core/api/src/entrypoints/worker.py`

Inside the loop, after `cli.run_once()`, call `job_runner.run_once()`. Both go
in the same `try`, and the tick is bumped **once**, in the existing `else` — so a
failure in either half correctly withholds the tick. Build the runner via
`build_job_runner()` alongside `build_processor()`. Extend the startup log line
to mention the queue drain. Do not add a second tick or a second interval.

### 7.2 `$FIXED/core/api/Dockerfile`

- Add `pyyaml==6.0.2` and `croniter==5.0.1` to the `pip install`, with a comment
  that the clock entrypoint parses `DOCEX_SCHEDULES_YAML` and evaluates plain
  5-field UTC cron — **no dialect translation anywhere**, since the clock is
  project code rather than a cloud primitive.
- `EXPOSE 8080 8081` → `EXPOSE 8080 8081 8082` in both the `dev` and `prod`
  stages.
- Update the header and the curl comment: **one image, THREE core services**
  (`api.web`, `api.worker`, `api.clock`). `api.clock` also declares
  `health_check_path`, so it too obliges curl.

### 7.3 `$FIXED/infra/contracts/api.web.openapi.yml`

Add the two operations with full descriptions, `202` responses returning
`{job_id}`, and a note that they are the **same driving port** the clock fires —
so firing a scheduled job by hand in `dev` is an ordinary call, not a special
path. Keep the existing `/health*` paths untouched.

### 7.4 `$FIXED/infra/contracts/api.worker.asyncapi.yml`

- Add a channel for the `jobs` queue table: the worker *receives* deferred jobs.
  Describe the message as a `jobs` row (`id`, `name`, `enqueued_at`) and state
  that the transport is the postgres table, claimed with
  `FOR UPDATE SKIP LOCKED`, not a broker.
- Line ~81: the `processed_at` description calls it "the retention key the
  `reaper.prune` …" — re-point at `api.clock`'s `prune_pings` job, performed by
  `api.worker`.

### 7.5 `$FIXED/core/api/tests/`

Three new files; `test.sh` already globs `/service/tests` and needs no change.

- `test_clock_smoke.py` — imports `ContJobsCron` **without** a database and
  asserts `job_names()` is non-empty and matches the dispatch keys of a
  `ContJobsCron` built over a stub `ContJobs`. This is the test that keeps the
  instance-free accessor from silently regressing.
- `test_jobs_smoke.py` — against the live test-env postgres: enqueue via
  `JobService`, drain via `JobRunnerService`, assert the row is `started_at` +
  `finished_at` set with `error IS NULL`; and a failing-handler case asserting
  `error` is populated and the *next* job still runs.
- `test_jobs_concurrency.py` — the race. Enqueue 40 jobs; two
  `QueueJobsPostgres` instances on **separate connections**, each claiming
  batches of 4 from its own thread until the queue drains; assert **every job
  was claimed exactly once and the union is all 40**. Comment that this asserts
  *exclusivity* and that `SKIP LOCKED`'s own contribution is *liveness*, so the
  lock clause must not be "simplified" because the test still passes. This
  exists so the two-consumer race is exercised in `test` rather than first
  occurring at the prod release, where `replicas: 2` first takes effect.

---

## Step 8 — The two-dispatch-tables explanation

Write this paragraph, in substance, into **both** `cont_jobs_cron.py`'s and
`job_runner_service.py`'s class docstrings:

> There are two dispatch tables in this module and they are **not** duplication.
> This one maps a job name to how the job is **deferred**; the other maps a job
> name to how it is **performed**. Collapsing them is the obvious cleanup and it
> would couple the clock to the worker's implementation — the clock would have
> to know how a job is performed in order to know how to defer it, at which
> point nothing stops it performing the job itself, which is exactly what
> `clock.md § The clock defers; it does not work` forbids.

(The module doc `plans/core/api/hex/jobs.md` carries the same point; the
mod-developer writes it in the documentation step.)

---

## Step 9 — `infra.yml`: add `api.clock`

Add a third core service under `codebases.api.core_services` in **both**
projects, after `worker`:

```yml
      clock:
        role: clock
        command: ["python", "/service/dist/entrypoints/clock.py"]
        port: 8082
        health_check_path: /health
        networks: [internal]
        uses: [appdb, api.worker]
        schedules:
          prune_pings: "0 3 * * *"
          heartbeat:   "* * * * *"
        resources:
          cpu: 0.25
          memory: 512MB
```

`$ELASTIC` additionally gets `disk: 25GB` under `resources`, matching its
siblings (Fargate's ephemeral-storage minimum).

Comment the block — these projects are read as worked examples, so the comments
carry as much weight as the YAML:

- `uses: [api.worker]` **holds no magic ref**. The clock reaches the worker
  through the queue table, not the mesh, so there is no host to reference; the
  edge exists to declare the interface. Cite `cicl.md § Three clarifications`
  ("a ref implies an edge, never the reverse").
- `port` + `health_check_path` with **nothing routed to it**. A clock takes no
  ingress (rule 27 forbids `web`), nothing `uses` it, so no fan-out reaches it —
  its `/health` is enforced by the **container healthcheck alone** (docker
  `healthcheck:` on fixed, ECS container health on elastic). That is
  `clock.md § Caveats`, and it is real enforcement: a wedged clock gets
  restarted.
- **No `replicas`** — forbidden on a clock (rule 26); it is a singleton, and on
  elastic it deploys stop-then-start so a rolling deploy cannot double-fire.
- **Two jobs.** `prune_pings` is the retired `reaper.prune`'s work on its
  original `0 3 * * *`. `heartbeat` is minutely **so the walk can observe** the
  clock fire → defer → drain path inside a realistic window; without it that
  path is unobservable and the cron loop is never seen firing anything.

---

## Step 10 — Propagate and verify

1. **Rebuild `dist/`** in both projects: `sh $FIXED/core/api/build.sh` and the
   same for `$ELASTIC`. (`build.sh` clears `dist/` and re-copies `src/`, so
   stale `reaper` and pre-clock artifacts go.)
2. **Copy the code tree**: make `$ELASTIC/core` identical to `$FIXED/core`.
3. **Parity gate — must be empty:**
   ```sh
   diff -r -x '__pycache__' -x 'dist' \
     /home/ubuntu/.claude/jean_baudrillard/docex/test_projects/fixed/core \
     /home/ubuntu/.claude/jean_baudrillard/docex/test_projects/elastic/core
   ```
   Code identity across foundations is a doctrine property (checklist B.14) and
   the clock is the newest thing that could break it.
4. **Compile both projects**, from source, per the Ground rules recipe. Each
   must succeed and write `infra/output/{dev,test,stage,prod}/`.
5. **Read the emitted output** and confirm, on **fixed**:
   - a compose service for the clock with the codebase's image and the clock's
     `command`;
   - a paired otelcol sidecar (no exemptions);
   - a docker `healthcheck:` probing `:8082/health` with curl;
   - **`DOCEX_SCHEDULES_YAML` present in the clock's `environment:`**, its value
     the literal rendered YAML carrying both jobs;
   - **no** `depends_on:` on any core-service block (the `uses` merge removed
     it), while the per-codebase exec block still carries
     `condition: service_healthy`;
   - no Ofelia container and no scheduler INI anywhere.
6. Same read on **elastic**:
   - `aws_ecs_task_definition` + `aws_ecs_service` for the clock, and **no**
     target group;
   - `deployment_minimum_healthy_percent = 0` and
     `deployment_maximum_percent = 100` on the clock's service and **not** on
     `api.web`/`api.worker`;
   - `DOCEX_SCHEDULES_YAML` as a literal task-definition env entry;
   - **no** `aws_scheduler_schedule` and no scheduler-invocation IAM role
     anywhere in the tree.
7. Confirm `infra/output/<env>/schedules.yml` renders in both projects, keyed
   `api.clock`, for all four envs.
8. **Suites**, from `/home/ubuntu/.claude/jean_baudrillard/docex`:
   `pytest tests/unit` (≥ 988 passing) and `pytest -m integration`
   (20 passed / 0 failed). This mod changes no `docex` source, so any regression
   here is a real finding, not an expected churn.

## Report back

- The `diff -r` result (expected: empty).
- The compile result for each project and each env.
- The emitted-output confirmations from steps 5–7, quoting the actual
  `DOCEX_SCHEDULES_YAML` value and the two `deployment_*` lines.
- Unit and integration counts.
- Anything where `clock.md` was silent and you had to choose — flag it rather
  than absorbing it.

# Mod 117 — Migrate both smoke projects onto the clock

Delete the `reaper` codebase from both smoke-test projects, fold its work into
`api` as `api.clock` + a deferred queue job, and write that tree as the
doctrine's **reference implementation** of the clock architecture.

Both projects currently fail `docex compile` with `rule_2_unknown_role` on
`reaper.prune` — the state Mod 116 deliberately left. This mod is what makes
the tree compilable again.

> **Scope — this mod is the CODE half. Split approved.** The three large
> documents (`PRE_CUT_CHECKLIST.md`, `test_projects.md`,
> `upgrades/upgrade_1.7.0.md`) plus the root `CHANGELOG.md` are **Mod 120**.
> Their brief is built from
> [Deferred to Mod 120](#deferred-to-mod-120) below, so anything missing from
> that section is something Mod 120 has to rediscover — it is maintained as a
> handoff, not as a footnote.

---

## Why `reaper` cannot simply become a clock

Recorded here because the deletion looks heavier than the alternative and a
future reader will ask.

A clock **defers onto its own codebase's queue**, and only the codebase that
owns a schema may write to it
([`clock.md § The clock defers; it does not work`](../../../../doctrine/infrastructure/specifics/clock.md#the-clock-defers-it-does-not-work)).
`reaper` owns no schema — it reaches into `api`'s `pings` table through its own
repo adapter — and it has no worker and no queue. `reaper.clock` would therefore
have had to *do* the prune inside the singleton, which is exactly what the rule
forbids. `api` owns the schema, owns a polling worker, and can own a queue. So
the clock folds into `api` and `reaper` is deleted.

The two-codebase coverage this costs is accepted knowingly; recording it is a
[document-mod deliverable](#deferred-to-the-document-mod).

---

## Target shape

One codebase, **four** core services.

| Core service | Role | Port | `uses` | Notes |
| --- | --- | --- | --- | --- |
| `api.web` | `web` | 8080 | `[appdb, probe, events, api.worker]` | unchanged, plus the new job routes |
| `api.worker` | `worker` | 8081 | `[appdb]` | unchanged loop, plus a second drain call |
| `api.clock` | `clock` | 8082 | `[appdb, api.worker]` | **new** |
| — | | | | `reaper.prune` **deleted** |

### `infra.yml` — the new block

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
          # elastic only, matching its siblings:
          # disk: 25GB
```

Three deliberate choices in that block:

- **`uses: [api.worker]` with no magic ref.** The clock reaches the worker
  through the queue table, not the mesh. `cicl.md § Three clarifications` states
  the rule this exercises directly — *a ref implies an edge, never the reverse* —
  and `clock.md` calls for exactly this edge on a producer that reaches its
  consumer through a broker. It also means the clock is *not* a provider (nothing
  `uses` it, and it is not on `web`), so it correctly carries no contract.
- **`port` + `health_check_path` with no route.** A clock takes no ingress and
  nothing fans out to it, so its `/health` is enforced only by the container
  healthcheck (docker `healthcheck:` / ECS container health). That is
  `clock.md § Caveats` verbatim, and it is what the walk must be told to look at
  (`docker inspect` / ECS health, not a URL).
- **Two jobs, one of them minutely.** `prune_pings` is the retired reaper's
  work on its original schedule. `heartbeat` exists so the clock → queue →
  worker path is **observable inside a walk window**; a `0 3 * * *` job alone
  would make Goal 3 SC6 ("the walks show a running clock that fires a job,
  defers it, and sees `api.worker` pick it up") unverifiable in practice. It
  also gives the dispatch table more than one entry, which is what makes the new
  `check` gate meaningful.

---

## The reference implementation

Downstream projects copy this tree, so it is built to the architecture
`clock.md § Architecture` prescribes, element for element:

```
entrypoints/clock.py        runtime host — the cron loop
  → ContJobsCron            driving adapter: job name → port method
    → ContJobs              driving port (shared with ContJobsHttp, ContJobsCli)
      → alogic
        → QueueJobs         driven port — canonical `Queue` pattern
          → QueueJobsPostgres
```

### Two new hex modules in `api`

**`hex/jobs`** — the queue. Both halves of it: the producer side the clock
drives, and the consumer side the worker drives.

```
hex/jobs
├── domain/job.py                        Job entity: id, name, enqueued_at,
│                                        started_at, finished_at, error
├── ports
│   ├── driving/cont_jobs.py             ContJobs — ONE METHOD PER JOB:
│   │                                      prune_pings() / heartbeat()
│   ├── driving/cont_job_runner.py       ContJobRunner — run_once() -> int
│   └── driven/queue_jobs.py             QueueJobs — enqueue / claim /
│                                        complete / fail
├── alogic
│   ├── job_service.py                   implements ContJobs; enqueues
│   └── job_runner_service.py            implements ContJobRunner; claims a
│                                        batch and dispatches by name
└── adapters
    ├── driving/cont_jobs_cron.py        ContJobsCron — the dispatch table
    ├── driving/cont_jobs_http.py        ContJobsHttp — one route per job
    ├── driving/cont_jobs_cli.py         ContJobsCli — fire one job by name
    └── driven/queue_jobs_postgres.py    QueueJobsPostgres
```

**`hex/retention`** — the reaper's module, transplanted and renamed for what it
is. `domain/retention_window.py` (`RetentionWindow`, unchanged), driven port
`RepoPings.delete_processed_before`, its postgres adapter, driving port
`ContRetention.prune()`, alogic `RetentionService`. `jobs`' runner imports
`ContRetention` — a **driving port**, which is the one legal cross-module
import.

### Where each dispatch table lives, and why there are two

This is the part a copying project will get wrong, so it is decided here rather
than discovered.

- **`ContJobsCron`** holds *job name → port method*. It is the only component
  that receives a job **name** from outside, and it owns the fired / succeeded /
  failed translation. This keeps the entrypoint thin enough to satisfy the
  standing "an entrypoint needing its own test is doing too much" rule.
- **`ContJobsHttp` holds no table.** It exposes **one route per job**
  (`POST /jobs/prune_pings`, `POST /jobs/heartbeat`) calling the matching port
  method directly. A route is not a name lookup, and one route per operation is
  what an OpenAPI contract can actually describe.
- **`ContJobsCli`** takes a name on argv and therefore needs the same map as the
  cron adapter — it is the small price of a name-shaped mechanism.
- **`JobRunnerService`** (alogic, worker side) holds *job name → handler*.
  `prune_pings` → `ContRetention.prune()`; `heartbeat` → a logged no-op. This is
  a second, genuinely different table: the first says how to **defer** a job,
  this one says how to **perform** it. Only one of them runs in the clock.

> **The two tables are not duplication, and this must be said where downstream
> readers will look.** A defer-side table in `ContJobsCron` and a perform-side
> table in `JobRunnerService` read as redundant at a glance, and collapsing them
> is the obvious cleanup. It would couple the clock to the worker's
> implementation and destroy the deferral architecture: the clock would have to
> know how a job is *performed* in order to know how to *defer* it, at which
> point nothing stops it performing the job itself. This tree is the reference
> implementation, and a copying project inherits whatever it fails to explain —
> so this goes in **`plans/core/api/hex/jobs.md`** (the module doc) and in the
> two adapters' docstrings, not only in this overview. A mod overview is not
> what downstream projects read.

`ContJobsCron` exposes its names as a **class-level** tuple with a
`job_names()` accessor, constructible without a service instance. That is not
cosmetic — see [the binding-coverage seam](#the-binding-coverage-seam-held).

### `entrypoints/clock.py`

Modelled directly on `entrypoints/worker.py`, which is already the doctrine's
liveness reference:

- Reads **`DOCEX_SCHEDULES_YAML`** — the *literal rendered YAML*, identical on
  both foundations, never a path. Parsed with `yaml.safe_load`.
- Computes each job's `next_at` with `croniter` **from process start** —
  forward-only, no backfill, per `clock.md § Caveats`.
- Loop waits on a `threading.Event` with a **bounded ≤10 s** timeout, bumping a
  monotonic tick every iteration whether or not anything fired. The doctrine's
  10 s tick / 30 s staleness rule then falls out of the loop shape rather than
  being bolted on; the comment in the file says exactly that.
- Health server on `:8082` in a daemon thread, poll loop on the main thread —
  same signal-handling rationale as `worker.py`, copied deliberately.
- No `--list-jobs` flag and no startup binding check — see
  [the binding-coverage seam](#the-binding-coverage-seam-held). The entrypoint
  carries a short comment naming the seam so a copying project does not read the
  absence as an oversight.

### Queue table — one new migration

`migrations/20260806000000_create_jobs.sql`, additive and forward-only:

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id          uuid        PRIMARY KEY,
    name        text        NOT NULL,
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    started_at  timestamptz NULL,
    finished_at timestamptz NULL,
    error       text        NULL
);
CREATE INDEX IF NOT EXISTS jobs_pending_idx
    ON jobs (enqueued_at) WHERE started_at IS NULL;
```

`QueueJobsPostgres.claim()` uses `FOR UPDATE SKIP LOCKED`. This is load-bearing
rather than decorative: `api.worker` runs `replicas: 2` in prod, so the prod
release is a real two-consumer race against one queue.

### The race must be exercised before prod

Left alone, that two-consumer race **first occurs at C.9 / D.11** — the same
prod-only `replicas` clamp the checklist already warns is where a core service
that cannot tolerate a sibling first fails. Discovering a double-claim there
costs a walk.

So `tests/test_jobs_concurrency.py` drives it in the `test` env, where the
codebase suite already runs against real postgres: enqueue 40 jobs, run two
`QueueJobsPostgres` instances (**separate connections** — one shared connection
proves nothing) claiming in batches of 4 from two threads until drained, then
assert **every job was claimed exactly once and the union is the whole set**.

The assertion is exclusivity, which is the property whose failure breaks the
deferral contract — a job performed twice. `SKIP LOCKED`'s own contribution is
*liveness*: without it `FOR UPDATE` would serialize rather than duplicate, so
one worker would block behind the other's batch. The test says both in a comment
so a future reader does not "simplify" the lock clause on the grounds that the
test still passes.

### Existing files that change

| File | Change |
| --- | --- |
| `src/root.py` | `build_app()` mounts `ContJobsHttp`'s router; new `build_clock()` → `ContJobsCron`; new `build_job_runner()` → `ContJobRunnerCli`; `ContJobsCli` constructed and returned unused, per the "construct every mechanism" rule |
| `src/entrypoints/worker.py` | the loop calls `job_runner.run_once()` alongside `processor.run_once()`; one tick per iteration, still not bumped on failure |
| `Dockerfile` | `pyyaml` + `croniter` pinned; `EXPOSE` gains 8082; the CMD/curl comments extended to name the third core service |
| `tests/` | new `test_jobs_smoke.py`, `test_clock_smoke.py`, and `test_jobs_concurrency.py` (below); `test.sh` unchanged — it already globs |
| `infra/contracts/api.web.openapi.yml` | the two `POST /jobs/*` operations |
| `infra/contracts/api.worker.asyncapi.yml` | a `jobs` channel; the `reaper.prune` retention note at :81 re-pointed at `api.clock` |
| `teardown.sh`, `verify_clean.sh` (both) | `for service in api reaper` → `for service in api` |
| `elastic/verify_clean.sh:206` | the `aws scheduler list-schedules` leak check **deleted** — one fewer AWS resource type able to leak |

### Deleted outright

`core/reaper/` in both projects (45 files each, `src/` + `dist/` + Dockerfile +
scripts + tests), the `reaper:` block in both `infra.yml`s, and the
`container_registry` comment in `elastic/infra.yml` that says "`api` and
`reaper` get one each".

---

## The binding-coverage seam (HELD)

Mod 115 deferred "assert every declared job name has a binding" to this mod on
the grounds that it needs a project with a real dispatch table to read. **It is
now escalated to the operator and not built here** — the same way Mod 115 held
the delivery contract until it was ruled on. Three outcomes are live:

| Outcome | What it costs | `clock.md` edit? |
| --- | --- | --- |
| (a) `docex check` gate reading `<command...> --list-jobs` | a flag on `clock.py`; a gate on the `_gate_healthcheck_tooling` pattern (`check.py:544-640`); a new obligation on every downstream clock | yes — plus `cicd.md § Check Step` |
| (b) clock-side startup validation | `clock.py` raises when a scheduled name has no binding; no `docex` change; catches it a deploy later than (a) | yes |
| (c) drop it | nothing | yes — soften the "can assert" sentence |

**This mod is structured so any of the three is a small change**, and the whole
of that structure is one thing: `ContJobsCron` exposes its dispatch keys as a
**class-level tuple** behind `job_names()`, readable **without a service
instance, without a database, and without `DATABASE_*` in the environment**.
(a) then needs only an argv branch in `clock.py`; (b) needs only a comparison
against the parsed schedule map; (c) needs nothing. Building `job_names()` is
not a bet on any outcome — it is what the perform-side/defer-side split needs
anyway, so it is free.

**Two of the three require a `clock.md` edit, which is Mod 120's** — it owns the
documents. Whichever way the ruling goes, the doctrine sentence lands there, and
outcome (a) additionally needs a mod to build the gate.

`clock.py` and `cont_jobs_cron.py` each carry a one-paragraph note that binding
coverage is unasserted pending that ruling, so the absence reads as a decision
rather than an omission.

---

## Verification

1. `./bin/docex compile` clean in **both** projects, all four envs.
2. `diff -r test_projects/fixed/core test_projects/elastic/core` empty
   (excluding `__pycache__`/`dist`, per B.14). Code identity across foundations
   is a doctrine property and the clock is the newest thing that could break it.
3. `pytest tests/unit` ≥ 988 and `pytest -m integration` 20 passed / 0 failed.
   **No `docex` source changes in this mod** — the binding-coverage gate is
   held — so these are a no-regression check, not a new-coverage one.
4. **Read the emitted output by hand** on both foundations and confirm: the
   clock is a compose service / `task_definition` + `ecs_service`; it carries a
   paired otelcol sidecar; `DOCEX_SCHEDULES_YAML` reaches the container with the
   literal YAML on both; elastic carries
   `deployment_minimum_healthy_percent = 0` / `maximum = 100`; no
   `aws_scheduler_schedule` or scheduler IAM role survives anywhere;
   `infra/output/<env>/schedules.yml` renders.

## Commits

Per `test_projects.md § Commit cadence`, and getting this wrong leaves the
release pipeline blind to the change:

1. **Inner repo first**, one per project, project-shaped message. Each inner
   repo is dirty with the *whole advance's* seed delta — mods 110–116 were never
   committed inward — so this single commit lands the codebase/core-service
   rename, the `uses` merge, `cicl_version: "3"`, and the clock together. **The
   message must enumerate all four.** A future reader diffing one inner commit
   that contains four unrelated changes will otherwise assume something was
   squashed by accident and go looking for history that does not exist.
2. Bump `project.yml` (`fixed` 0.0.16 → 0.0.17, `elastic` 0.0.18 → 0.0.19), add
   the `CHANGELOG.md` entry, and **force-move `v<version>`** to the new HEAD.
3. **Outer catchup commit**, path-scoped, on `005_process_type_solidification`.

`docex_version` stays `1.6.0` — repinning is the cut's job (checklist A.2). The
walk's feature-branch restructure (C.6) is **not** this mod's work.

---

## Deferred to Mod 120

**This section is Mod 120's brief.** It is maintained as a handoff — anything
absent here is something Mod 120 must rediscover.

- **`PRE_CUT_CHECKLIST.md`** — `cicl_version: "3"` in B.3; `uses` replacing the
  `depends_on`/`consumes` items in B.3.1/B.3.2; the scheduler exemptions
  throughout B.9/B.10 inverted into the clock's **non**-exemption (and the note
  that a clock's health is container-enforced, not stage-tested); the "two
  things only this walk covers" note rewritten (the scheduler arm is gone; the
  clock arm is a coverage *gain*); C.5's per-codebase test fan-out → one run;
  C.6's two registry repos → one; D.8's ECR count two → one; **D.9's "came up as
  a scheduled task, not a service" check inverts** and its `list-services` count
  goes four → five; new walk steps proving the clock fires, defers, and is
  drained; and **D.6's `sudo find … -exec rm -rf` workaround deleted** — Mod 119
  fixed the defect it was treating.
- **`test_projects.md`** — § Shape becomes one codebase; line 17's "the only
  end-to-end coverage of the scheduler path anywhere" is now false and must be
  replaced by a written record of the coverage consciously given up (one image
  per codebase, the two-repo counts, the per-codebase `migrate.sh`/`test.sh`
  fan-out), so a future reader finds a reason rather than a discrepancy and does
  not "restore" the second codebase.
- **`upgrades/upgrade_1.7.0.md`** — work its own "Before this ships" checklist:
  fold the `uses` migration in interleaved with the rename's step 2 (rename
  first), **rewrite step 6's "expect exactly four differences" table** (the
  byte-identical guarantee was the rename's property alone; `uses` breaks it),
  add the `scheduler` → `clock` migration, resolve the 6 dangling anchors,
  restate the `cicl_version` rollback trap, then delete the fragment banner and
  the `status:` frontmatter.
- Root `CHANGELOG.md`.
- **The `clock.md` sentence for whichever binding-coverage outcome the operator
  rules** — see [the seam](#the-binding-coverage-seam-held). Two of the three
  outcomes need it; the third needs the "can assert" sentence softened. Mod 120
  owns the documents, so it owns that edit either way. Outcome (a)
  additionally needs a mod to build the `docex` gate; that is not Mod 120's.

---

## Rulings

Recorded here because the code below reads as over- or under-built without
them.

1. **Split approved.** Mod 117 is the code; Mod 120 is the documents. The split
   line: documents describe the finished state, so they cannot be written
   accurately before the code exists, and the document mod carries no test
   surface to interleave.
2. **Binding coverage escalated to the operator and held.** Not built here.
   Structured so all three outcomes are small; see
   [the seam](#the-binding-coverage-seam-held).
3. **`heartbeat` approved.** A smoke project exists to be observed. Firing by
   hand over HTTP would exercise the driving port while leaving **the cron loop
   itself never observed firing anything** — the one component this advance
   replaced a whole subsystem to obtain.

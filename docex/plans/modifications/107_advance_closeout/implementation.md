# Mod 107 — Implementation

Executes the design in [`overview.md`](./overview.md). Written for a fresh
context: everything needed is either stated here or reachable from the file
paths given. All paths absolute from the repo root
`/home/ubuntu/.claude/jean_baudrillard` (referred to below as `$jb`).

Five stages, each independently reviewable. **Do them in order** — Stage A's
migration is what Stage B documents and Stage C explains.

## Hard stops — do NOT do these

Per the operator's autonomy ruling:

- **Do not** create the `v1.6.0` git tag.
- **Do not** build the `docex:1.6.0` image.
- **Do not** run the two-foundation smoke walk against real infrastructure.
- **Do not** run `pytest -m integration` (needs docker/AWS).
- **Do not** touch anything under `$jb/doctrine/`, `$jb/agents/`,
  `$jb/engineer/`, `$jb/skill_iter/`, or `$jb/skills/`. All of it is the
  operator's in-progress work and much of it is already dirty. This mod's
  doctrine dependencies were satisfied by Mods 094 and 106.
- **Do not** edit anything under `$jb/docex/plans/core/`. Those are core
  planning docs, updated in the mod cycle's documentation step by the
  supervising agent, not here.
- **Do not** rename the fixture scheduler process types
  (`nightly_cleanup.nightly_cleanup`). Resolved Q6 — deliberately left.

## Expected test results

Baseline, measured before this mod: **`pytest tests/unit` = 982 passed**;
**`pytest tests/` = 1046 passed, 17 deselected**.

The only `src/` changes in this mod are a docstring and (conditionally, Stage E)
one validator relocation. So:

- If Stage E's Q5 fix is **not** taken: both numbers must be **unchanged**.
- If it **is** taken: both numbers go up by exactly **+1** (the one new test).

Any other movement means something unintended happened — stop and report.

Run from `$jb/docex` with `/home/ubuntu/.local/bin/pytest` (the repo `.venv`
has no pytest installed).

---

# Stage A — Migrate both smoke projects to `cicl_version: "2"`

Both projects live at `$jb/docex/test_projects/{fixed,elastic}/`.

**The binding constraint, checked at the end of this stage:** everything under
`core/` must stay **byte-identical between the two projects**. Checklist item
B.14 enforces it (`diff -r fixed/core elastic/core` must be empty, ignoring
`__pycache__`/`dist`), and it currently passes. Write each source file once and
copy it to the other project. Only `infra/infra.yml`, `infra/output/`, and the
inner `CHANGELOG.md`/`plans/` legitimately differ.

**Use `git mv` for every rename** so history follows. Note both projects are
*nested git repos* as well as being tracked by the outer repo; run `git mv` from
the **outer** repo (`$jb`) so the outer index records the rename. Do not commit
inside the inner repos — the supervising agent handles commit cadence.

## A.1 — Restructure `core/`: merge `worker` into `web`, rename to `api`

The end state, per project:

```
core/
├── api/                     (was web/, absorbing worker/)
│   ├── Dockerfile
│   ├── build.sh
│   ├── migrate.sh           (unchanged — api owns the schema)
│   ├── migrations/          (unchanged)
│   ├── test.sh
│   ├── src/
│   │   ├── root.py          (construct only — no activation)
│   │   ├── entrypoints/
│   │   │   ├── __init__.py
│   │   │   ├── web.py       (uvicorn host)
│   │   │   └── worker.py    (poll loop + tick + health server)
│   │   └── hex/
│   │       ├── pings/       (from web)
│   │       └── processor/   (from worker)
│   └── tests/               (union of web's and worker's)
└── reaper/                  (name UNCHANGED — resolved Q2)
    ├── Dockerfile
    ├── build.sh
    ├── test.sh
    ├── src/
    │   ├── root.py          (construct only)
    │   ├── entrypoints/
    │   │   ├── __init__.py
    │   │   └── prune.py
    │   └── hex/reaper/
    └── tests/
```

Steps:

1. `git mv core/web core/api`.
2. `git mv core/worker/src/hex/processor core/api/src/hex/processor`.
3. `git mv core/worker/tests/test_smoke.py core/api/tests/test_processor_smoke.py`
   (`api/tests/test_smoke.py` already exists — do not clobber it).
4. Delete the remainder of `core/worker/` (`Dockerfile`, `build.sh`, `test.sh`,
   `src/root.py`, `src/__init__.py`, `src/hex/__init__.py`, `dist/`,
   `tests/__init__.py`). `git rm` the tracked ones.
5. Create `core/api/src/entrypoints/__init__.py` and
   `core/reaper/src/entrypoints/__init__.py` (empty).

## A.2 — Split the composition roots: construct, don't activate

Doctrine rule (`$jb/doctrine/hexagonal_architecture/internal_dependency_rules.md`
§ Entrypoints): *"The composition root **constructs**; it does not **activate**.
It builds no server, opens no socket, and consumes no queue."* And: *"The
runtime host is not an adapter... a broker's consume loop is not one either.
Both belong to the entrypoint."*

That second sentence means the poll loop currently inside
`ContProcessorCli.run_forever()` **moves to the entrypoint**. This is the
doctrinally-correct shape and the reason this seed becomes the reference
implementation — follow it exactly.

### `core/api/src/root.py`

- Keep `build_app()` and `_dsn_from_env()` essentially as they are.
- **Delete `main()` and the `if __name__` block** — activation moves to
  `entrypoints/web.py`. Drop the now-unused `uvicorn` and `sys` imports.
- Add a `build_processor()` function that constructs the worker's graph
  (`RepoPingsPostgres` → `ProcessorService` → `ContProcessorCli`) and returns
  the driving adapter. It is the same file because there is **one composition
  root per codebase**, not per process type.
- `FastAPI(title=...)` becomes `"api"`.
- Add the `/health/api/worker` fan-out endpoint inside `build_app()` —
  see A.4.

### `core/api/src/hex/processor/adapters/driving/cont_processor_cli.py`

Reduce to translation only:

- Keep `run_once()` — it invokes the driving port and returns the count.
- **Remove** `run_forever()`, the `signal` handlers, `_stop`, `time.sleep`, and
  the `poll_interval_seconds` constructor arg. Those are runtime-host concerns
  and move to the entrypoint. Keep the per-iteration `try/except` **in the
  entrypoint's loop**, not here (a translation adapter should not swallow
  errors).
- Update the module docstring: it currently describes itself as "the container's
  main process", which is no longer true.

### `core/reaper/src/root.py`

Same treatment: keep `_dsn_from_env()`; replace `main()` with a
`build_reaper()` that returns the constructed `ContReaperCli`. Delete the
`if __name__` block.

## A.3 — Write the entrypoints

### `core/api/src/entrypoints/web.py`

Thin: import `build_app` from `root`, run uvicorn.

```python
"""Entrypoint for the `web` process type of the `api` codebase."""
# WHY: the default must match infra.yml's `port: 8080` for this process type —
# nothing injects PORT, so the two are coupled by convention.
port = int(os.environ.get("PORT", "8080"))
uvicorn.run(build_app(), host="0.0.0.0", port=port, log_level="info")
```

### `core/api/src/entrypoints/worker.py`

This is the only genuinely new logic in the mod. It owns the loop, the
monotonic tick, and the liveness surface. The thresholds are
**doctrine-fixed** (`$jb/doctrine/infrastructure/contracts.md` § Health Checks)
— do not parameterize them, do not make them env-configurable:

- The loop bumps a **monotonic** tick each iteration (`time.monotonic()`).
- The loop ticks **at least every 10 s even when idle** — the poll interval is
  1.0 s, comfortably inside that, and the receive must stay bounded.
- The `/health` handler returns **503** when the tick is older than **30 s**,
  otherwise `{"version": VERSION}` with 200.

Structure:

1. A tiny module-level tick holder (a mutable box or a small class with a
   `float` and a `bump()`), written by the loop thread and read by the server.
   A plain float assignment is atomic under the GIL — no lock needed; say so in
   a `# WHY:` comment so a reader does not add one.
2. A FastAPI app with one route, `GET /health`, reading the tick.
3. Run **uvicorn in a daemon thread** and the **poll loop in the main thread**,
   so SIGTERM reaches the loop. Add a `# WHY:` comment recording the doctrinal
   point that liveness is sourced *from the loop's tick*, not from the health
   thread's own aliveness — a separate liveness thread that reported health
   independently is exactly what the doctrine forbids.
4. Signal handling (SIGTERM/SIGINT) sets a stop flag; the loop exits after the
   current iteration. Moved here from `ContProcessorCli`.
5. Per-iteration `try/except` logging the exception and continuing — a transient
   DB error must not kill the worker. **Do not bump the tick in the exception
   path**: a loop that fails every iteration is not alive, and bumping there
   would defeat the probe. This is a subtle point — comment it.
6. `logging.basicConfig` per `$jb/doctrine/practices/logging.md`.

### `core/reaper/src/entrypoints/prune.py`

Import `build_reaper` from `root`, call `run_once()`, `sys.exit()` the result.
Run-to-completion; no tick, no server (`scheduler` process types are
**exempt** from the health model).

## A.4 — The `/health/api/worker` fan-out endpoint

Added to `build_app()` in `core/api/src/root.py`. Required by
`contracts.md § Fan-out`: each `web`-network process type exposes the health of
everything it `consumes` that is not itself on the `web` network.

- Path: `GET /health/api/worker` — note the **two** segments
  (`/health/<service>/<process>`), not the old one-segment form.
- Reads `WORKER_HOST` / `WORKER_PORT` from env (injected by the four-segment
  magic refs added in A.5).
- Proxies the worker's **own** `/health` with a **short hard timeout** (3 s, as
  the existing `/health/probe` uses).
- **One hop only** — never call the target's fan-out endpoints. Add a `# WHY:`
  comment: without this rule the legal `consumes` cycle recurses.
- 503 on unreachable or on a non-200 from the worker; pass the worker's
  `version` through on success.

Model it on the existing `/health/probe` handler, which is right next to it.

## A.5 — `infra/infra.yml`

Rewrite both. **Preserve every existing explanatory comment** that is still
true — these files are heavily commented on purpose and the comments are the
seed's teaching value. Update the ones the migration falsifies (e.g. the
`worker` block's "No port — `worker` isn't on the web network, so no
reverse-proxy exposure" is obsolete: it now has a port, for health).

Top level, both projects:

- `cicl_version: "1"` → `"2"`.
- `domain_default_service: web` → `domain_default_process: api.web`.
- Everything else at top level unchanged (`foundation`, `apex_domain`,
  `container_registry`/`reverse_proxy`, `repo_url`,
  `observability_backend_url`).

`core_services:` becomes two codebases, `api` and `reaper`:

```yml
core_services:
  api:
    # Codebase-scoped: both process types run the same artifact and both
    # need a database, so these live once at the service level and merge
    # into every process type. (cicl.md § Field scoping.)
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
      DATABASE_SSLMODE: ${backing_services.appdb.sslmode}
    processes:
      web:
        role: web
        command: ["python", "/service/dist/entrypoints/web.py"]
        port: 8080
        networks: [web, internal]
        health_check_path: /health
        depends_on: [appdb, probe, events]
        consumes: [api.worker]
        env:
          # Process-scoped: only the web edge exposes /health/{probe,events},
          # so only it declares these refs — which is what keeps `probe` and
          # `events` out of the worker's depends_on (rule 7: a SERVICE-level
          # ref would oblige every process type).
          SIDECAR_HOST: ${backing_services.probe.host}
          SIDECAR_PORT: ${backing_services.probe.port}
          CLICKHOUSE_HOST: ${backing_services.events.host}
          CLICKHOUSE_PORT: ${backing_services.events.port}
          # Four-segment core magic refs — the worker's Service-Connect /
          # docker-DNS address, used by the /health/api/worker fan-out.
          # Holding these refs is what obliges `consumes: [api.worker]`.
          WORKER_HOST: ${core_services.api.worker.host}
          WORKER_PORT: ${core_services.api.worker.port}
        resources:
          cpu: 0.25
          memory: 512MB
          # elastic only: disk: 25GB
      worker:
        role: worker
        command: ["python", "/service/dist/entrypoints/worker.py"]
        # A port purely for the liveness probe: a worker is never routed, but
        # `consumes` targets must be probeable, and on elastic the port is
        # also what makes it Service-Connect-discoverable.
        port: 8081
        health_check_path: /health
        networks: [internal]
        depends_on: [appdb]
        replicas: 2
        resources:
          cpu: 0.25
          memory: 512MB
          # elastic only: disk: 25GB

  reaper:
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
      DATABASE_SSLMODE: ${backing_services.appdb.sslmode}
    processes:
      # Named after the job, not the role — a scheduler codebase commonly
      # carries several jobs. (cicl.md § Naming convention.)
      prune:
        role: scheduler
        schedule: "0 3 * * *"
        command: ["python", "/service/dist/entrypoints/prune.py"]
        networks: [internal]
        depends_on: [appdb]
        resources:
          cpu: 0.25
          memory: 512MB
```

`backing_services:` — one change only: `appdb.schema_owned_by: web` → `api`
(it names a **codebase**, never a process type).

**Note the single-direction `consumes`.** The design overview floated a mutual
`api.web ↔ api.worker` cycle to exercise cycle acceptance. Do **not** add
`consumes: [api.web]` to the worker: this worker polls a table and never calls
the web edge, so the reverse edge would be a false declaration in the file that
downstream projects copy. Cycle acceptance is already covered by Mod 098's unit
tests. Honesty in the reference implementation wins.

Keep the two projects' differences exactly as they are today: `disk: 25GB` on
the elastic `api` process types only (Fargate's 21 GiB floor), no `disk` on the
scheduler, and the foundation-specific comment wording.

## A.6 — Contracts

1. `git mv infra/contracts/web.openapi.yml infra/contracts/api.web.openapi.yml`.
   **This file is already dirty in the baseline** (a `campaign` → `advance`
   prose fix in a comment) — carry that content forward; do not revert it.
2. In it, add the `/health/api/worker` path (the fan-out endpoint from A.4).
   The existing `/health/probe` and `/health/events` paths stay. Update the
   header comment, which explains why probe/events are present — it should now
   also note that `/health/api/worker` **is** doctrine-required (it is a
   `consumes` target's fan-out), unlike probe/events which are not.
3. **New:** `infra/contracts/api.worker.asyncapi.yml`. Required because
   `api.worker` is a `consumes` target and therefore a provider, and the format
   is role-derived (`worker` → asyncapi). Keep it minimal and honest: one
   channel describing the `pings` work queue with the message schema.

   Add a header comment recording the awkwardness rather than hiding it: this
   worker's "queue" is the `pings` **table**, because the doctrine ships no
   `queue` role, so the broker shape an AsyncAPI contract naturally describes is
   approximated by a polled table. This is the advance's known loose end
   (flagged item #4) and the seed should make it visible.

   Per `contracts.md § Declared by fields`, this contract describes **only the
   message boundary** — no `/health` path belongs in it; the worker's
   probeability is declared by its `port` + `health_check_path` fields.

## A.7 — Dockerfiles

`core/api/Dockerfile` (was `web`'s):

- Title comment `web` → `api`; note it now serves **two** process types.
- The `curl` justification comment stays and gains a second reason: the worker
  process type also declares `health_check_path`, so the gate requires `curl`
  for it too.
- `COPY src/`, `tests/` etc. already cover the new `entrypoints/` and the
  absorbed `hex/processor/` — verify, don't assume.
- The `dev`, `prod`, and `test` stages' `CMD ["python", "/service/dist/root.py"]`
  is now **wrong** (`root.py` no longer activates). Per
  `cicl.md § Process Types`, `command` is required on every process type and
  **supersedes the Dockerfile `CMD`**, which is deliberately irrelevant for core
  services. Replace the `dev`/`prod` `CMD` with the web entrypoint as a sane
  interactive default and add a `# WHY:` noting the compiler overrides it. Leave
  `test`'s `CMD ["sleep", "infinity"]` alone.
- `EXPOSE 8080` — add `8081` for the worker's health port.
- Worker deps: `worker`'s image installed only `psycopg2-binary`; the merged
  image needs `fastapi`/`uvicorn` for the worker's health server, which
  `web`'s base already installs. Verify nothing is missing.

`core/reaper/Dockerfile`:

- **Retire the mod-074 header.** The comment currently says the `prod` stage is
  self-contained because the trigger launches the job with no bind mounts and
  "`docex up dev` builds this `prod` stage locally (mod 074) so Ofelia can
  launch it in dev". **Mod 103 retired that** — the Ofelia job now keys off the
  codebase image, and dev jobs run the `dev` stage. Rewrite the paragraph to
  describe current behavior, and keep the (still true) point that the image must
  carry its own `/service/dist` because the trigger supplies no mounts. Flag in
  the report if the surrounding stage structure also needs a change; do not
  restructure the stages on your own initiative.
- Update the `CMD` to the `prune` entrypoint, same reasoning as above.

## A.8 — Scripts and the inner project files

1. `fixed/teardown.sh:75` and `fixed/verify_clean.sh:45` — both read
   `for service in web worker`. Change to `for service in api reaper`.
   **This fixes a pre-existing leak**: `reaper` was in neither list, so its
   registry repo survived teardown and `verify_clean` could not see it. Add a
   brief comment naming the codebases so the next process-type addition does not
   silently reintroduce the gap. Check `elastic/teardown.sh` and
   `elastic/verify_clean.sh` for any equivalent list (a first grep found only
   comments — confirm).
2. `infra/stage/tests/test_smoke.py` (both projects; **already dirty** — carry
   it forward). Update the module docstring's stale service naming and add a
   probe of `/health/api/worker`, which is the only place the stage tests can
   observe the new worker liveness surface end to end.
3. `project.yml` (both) — `docex_version: "1.5.0"` → `"1.6.0"`. Required, not
   deferred to walk time: a `cicl_version: "2"` project cannot compile under a
   1.5.0 image, so leaving the pin ships a seed broken at its own pin. Leave
   `version:` (the project's own version) alone.
4. Inner `plans/core/**` (both projects): `plans/core/web/` → `plans/core/api/`
   (`git mv`), fold `plans/core/worker/hex/processor.md` into it, and update
   `masterplan.md` to describe two codebases with three process types. These are
   the *seed's* docs — part of the artifact being migrated, and B.11-adjacent —
   so they are in scope here, unlike `$jb/docex/plans/core/`.
5. Inner `CHANGELOG.md` (both; **already dirty** — carry forward). Add an
   `[Unreleased]` entry describing the process-type migration, in the projects'
   existing voice.

## A.9 — Compile both projects and read the output

`compile` is pure Python — no docker — so this runs from source:

```sh
cd $jb/docex/test_projects/fixed   # then again for elastic/
PYTHONPATH=$jb/docex/src python3 -m docex compile
```

Both must exit 0. Then **read the emitted output** and confirm each item below.
This is the closest thing to an end-to-end test of the advance available without
docker, so do not just check the exit code.

Fixed (`infra/output/{dev,test,stage,prod}/docker-compose.yml`):

- Compose services `…-api-web`, `…-api-worker`, and the `reaper-prune` Ofelia
  trigger — and **no** `api-api`, `web-web`, or `worker-worker`.
- **One** `…-api-exec` service, `profiles: [exec]`, carrying **service-level
  `env:` only** (the six `DATABASE_*`) — and specifically **not** `SIDECAR_HOST`
  or `WORKER_HOST`, which are process-scoped. This is Mod 099's central rule.
- **Two** `-otelcol` sidecars for the `api` codebase (one per non-scheduler
  process type), none for `reaper`.
- `OTEL_SERVICE_NAME=api-web` and `api-worker` respectively, plus
  `docex.core_service=api` / `docex.process_type=<proc>` in
  `OTEL_RESOURCE_ATTRIBUTES`; and on the **exec** service the de-qualified
  `OTEL_SERVICE_NAME=api` with `docex.process_type` **absent**.
- `WORKER_HOST` on `api-web` resolved to the worker's global name (not left as
  literal `${core_services.api.worker.host}` — that literal-passthrough was one
  of the bugs Mod 097 fixed).
- Traefik router/service labels only on `api-web`, keyed on its unqualified
  global name.
- In `dev`/`test`/`stage`: **exactly one** worker service — `replicas` clamps to
  1 outside `prod`. In **`prod`**: the unroll — two services suffixed `-1`/`-2`,
  each with its own `container_name` and its own sidecar, sharing one network
  **alias** equal to the unqualified global name, and traefik labels (if any)
  still on the unqualified name.
- No host port published for `api-worker` (resolved flagged item #2).

Elastic (`infra/output/{stage,prod}/main.tf`):

- Task definitions and ECS services for `api-web` and `api-worker`; a
  scheduled task for `reaper-prune` with **no** `ecs_service`.
- `api-worker` has a container-level `healthCheck` and **no** target group;
  `api-web` has a target group.
- **`desired_count = 2`** on the prod `api-worker` ECS service, `1` in stage.
- **One** `…-migrate` task definition family per codebase (not per process
  type), resource address `api_migrate`.
- **One** ECR repo per codebase — `api` and `reaper` — not one per process type.
- Service Connect entries for both `api` process types.
- Env-tier tags carry the new `process` tag.

Then confirm the identity rules hold:

```sh
cd $jb/docex/test_projects
diff -r fixed/core elastic/core            # must be empty (ignore __pycache__/dist)
grep -rn 'domain_default_service\|cicl_version: "1"' fixed elastic   # must be empty
```

Report anything that does not match. **Do not "fix" docex to make the output
match** — a mismatch here is a genuine finding about the advance and belongs in
the report, not in a patch.

---

# Stage B — `PRE_CUT_CHECKLIST.md`

`$jb/docex/test_projects/PRE_CUT_CHECKLIST.md`. The walk it describes is now a
gate on two things nothing else covers, so it must not misroute the operator.

1. **B.9** — contract path `infra/contracts/<svc>.<format>.yml` →
   `<svc>.<proc>.<format>.yml`, and the provider set is now (`consumes` targets)
   ∪ (web-network process types), so a `worker` provider gets **asyncapi**.
2. **B.10** — health endpoints are per process type: `GET /health` on every
   long-running process type, and `GET /health/<svc>/<proc>` (two segments) for
   each `consumes` target not on the `web` network. Note the `scheduler`
   exemption and the monotonic-tick requirement for loop-owning process types.
3. **B.11** — add `src/entrypoints/` with one module per process type, and the
   composition-root-constructs-but-does-not-activate rule. This is a **new**
   audit item; without it the checklist cannot catch a project whose `root.py`
   still starts a server.
4. **B.3** — `infra.yml` shape now includes `cicl_version: "2"`, a mandatory
   non-empty `processes:` block on every core service, and
   `domain_default_process` (dotted); old `domain_default_service` absent.
5. **B.7** — scripts are per **codebase**, not per process type; `migrate.sh`
   runs once per codebase. Add that `migrate.sh`/`test.sh`/`build.sh` may read
   **service-level `env:` only**.
6. **C.6 / D.8** — image names are per codebase: `…/api:<v>` and
   `…/reaper:<v>`. The old `…/web` and `…/worker` are gone.
7. **C.9 / D.11** — hostnames become `api-web.prod.…`; the bare-env and
   bare-project routes now resolve via **`domain_default_process`**. Add a
   `/health/api/worker` probe alongside the existing ones.
8. **D.9** — the ECS service list `web`/`worker`/`probe`/`events` becomes
   `api-web`/`api-worker`/`probe`/`events`, plus the `reaper-prune` scheduled
   task.
9. **A.4.1** — the existing `*.dev.…`-style wildcards already cover the new
   `api-web` hostname, so no new records are needed **for the smoke projects**.
   State that explicitly, because the upgrade guide tells downstream projects
   the opposite (they need a record per new web hostname), and a reader
   comparing the two documents will otherwise think one is wrong.
10. **The Q4 note — add it prominently**, in as many words: *the `prod` release
    (C.9) is the only thing in existence that exercises the fixed replica
    unroll, because `replicas` clamps to 1 in `dev`, `test`, and `stage` and
    every integration test runs against `dev`. Skipping C.9 means shipping that
    code untested.* Put it where an operator deciding to stop after stagetest
    will see it — at the top of C.9 and in § E.
11. Also state that **no integration test covers a scheduler**
    (`tests/integration/conftest.py` points them all at `sample_project`), so
    `reaper-prune` on the fixed walk is the only end-to-end scheduler coverage
    that exists.
12. **Fix the dangling link at `:104`** — `release_mechanism.md § Fixed
    Foundation: Ansible` → `release.md`; verify the `#fixed-foundation-ansible`
    anchor still resolves in the new file and adjust if not.

---

# Stage C — `upgrades/upgrade_1.6.0.md`

New file. Match `$jb/upgrades/upgrade_1.5.0.md` for shape and voice — read it
first. Schema per `$jb/upgrades/README.md`:

```yaml
---
version: "1.6.0"
severity: minor
kind: incremental
scope: [machine, project]
---
```

`incremental`, not `rebuild`: no infrastructure is torn down. But be explicit
that resources **are renamed**, so the first apply replaces containers, ECS
services, task definitions, log groups, and (on `alb`) target groups.

Sections, in `README.md`'s prescribed order:

**Summary** — a core service is now a codebase declaring N process types; every
emitted identity gains a second segment. Link the 1.6.0 changelog entry rather
than restating it.

**Machine sync** — `doctrine-update` lands the `docex:1.6.0` image and the
refreshed skill set. Note `.claude-plugin/plugin.json`'s bump is what
invalidates the plugin cache so new/changed skills actually land.

**Project upgrade** — the ordered heavy section. Spine: the design record's
[not-process-qualified table](../docex/plans/advances/004_next/service_processes_refactor.md#what-is-not-process-qualified)
(the inventory of what does **not** move — image, ECR repo, `schema_owned_by`,
source folder, migrations, `secrets:`/`config:`) plus the nine numbered
migration steps. Then, each of these explicitly:

1. **The error you will actually see.** Before anything else, set expectations:
   a v1 `infra.yml` under 1.6.0 fails with **per-service field-scoping errors**
   naming the moved fields, plus `extra_forbidden` on `domain_default_service` —
   **not** a single "unsupported `cicl_version`" message. (If Stage E's Q5 fix
   lands, describe the version message instead, and say the field errors follow
   once the version is corrected. Write this section **after** Stage E so it
   matches reality.) Quote a real excerpt captured from a real run.
2. **Nest every core service under `processes:`.** Show a before/after. Cover:
   hoisting `secrets:`/`config:`/shared `env:` to the service level; `command:`
   required on **every** process type including `web`; the service level
   accepting only `{processes, secrets, config, env}`.
3. **`src/entrypoints/`** — one module per process type, composition root
   constructs without activating, and the **liveness tick** obligation for
   loop-owning process types (monotonic, ≤10 s even when idle, 30 s staleness,
   503 when stale — doctrine-fixed, no knob). Point at
   `docex/test_projects/*/core/api` as the reference implementation.
4. **`domain_default_service` → `domain_default_process`**, now dotted and
   fully qualified.
5. **Contract file renames** → `<svc>.<proc>.<format>.yml`; new AsyncAPI
   contracts for `worker` providers; `/health/<svc>/<proc>` fan-out endpoints
   in consumers' OpenAPI.
6. **`depends_on` is backing-services-only; core→core moves to `consumes:`**,
   dotted and fully qualified, bare names illegal. Include the one-directional
   / same-codebase / service-level-`env:`-obliges-every-process clarifications,
   since all three surprise people.
7. **Four-segment core magic refs** — `${core_services.<svc>.<proc>.<part>}`;
   bare core refs now illegal.
8. **`migrate.sh` / `test.sh` / `build.sh` may read service-level `env:` only.**
   Call this out hard — it is the break most likely to bite silently, because a
   migration reading a process-scoped var simply gets nothing.
9. **On fixed: add public DNS records for every new web hostname**
   (`api-web.dev.…`) **before** `envinfra up dev`. Otherwise traefik's HTTP-01
   authorizations fail and Let's Encrypt's failed-authorization rate limit
   trips — which is time-based, so it costs an hour, not a retry.
   `docex preinfra development` surfaces the gap first.

**Doctrine / behavior notes:**

- **Rollback is unavailable across the boundary.** For exactly one release
  cycle, prod has no rollback path: `docex rollback` refuses at cheap pre-flight
  (before any worktree or apply) because step 3 recompiles the target version's
  `infra.yml` with the *current* docex. Quote the refusal message **verbatim**
  from `_boundary_message` in `$jb/docex/src/docex/pipeline/rollback.py`,
  including its two-step fix-forward instructions and its closing note that
  rollback works normally once a second `cicl_version: "2"` release exists. Say
  plainly that the mitigation is to keep the window short.
- **`${a-b}` now errors, and there is no escape.** `_COMPILE_RE` was widened to
  admit `-`, so a `${a-b}` that previously passed through as literal text is now
  an undefined-compile-time-variable error. The grammar is exactly `${var}`,
  `$[var]`, `@expr` with **no escape form** — the `$$` doubling in the tree is
  applied by emitters *after* substitution and never reaches the resolver, so it
  is not a workaround. The fix is to rename the variable. Say this plainly
  rather than implying an escape exists.
- **New emitted names for every core service** — containers, ECS services, task
  definitions, log groups, sidecars, traefik routers, hostnames. Enumerate them
  so nobody is surprised mid-apply.
- **`alb` target-group names gain hash suffixes; `iam` can now hard-fail.** Word
  this carefully: **neither policy changed in this advance.** The only
  `naming_policies.yml` edit is `http_host` (`max_len: 63, overflow: error`).
  `alb`'s 32-char `hash_truncate` and `iam`'s 64-char cap both predate it; the
  **fourth name segment** is what makes them bite. Consequences: `alb` target
  groups whose names previously fit are **destroyed and recreated** on first
  apply (the descriptive name survives in the `Name` tag); and an `iam`
  scheduler-role name can now exceed 64 and **hard-fail the compile**, so a
  project that compiles today may not. An operator sent looking for a policy
  diff will not find one — do not send them.
- **Scheduler-only naming.** Name the **codebase** after the codebase and the
  **process** after the job. A codebase named after its job compiles to
  `nightly_cleanup-nightly_cleanup` — correct, but ugly, and it is what a
  mandatory `processes:` block produces. Cite
  `docex/test_projects/*/core/reaper` (codebase `reaper`, process `prune` →
  `reaper-prune`) as the worked example.
- `replicas` is honoured in **`prod` only** (clamped to 1 elsewhere), so a
  process type that does not tolerate siblings first surfaces in production.
  Flag it as a known limitation.

**Verification** — `compile` succeeds with `cicl_version: "2"`; emitted names
carry two segments; one image and one ECR repo per codebase; `OTEL_SERVICE_NAME`
distinct per process type; `/health/<svc>/<proc>` reachable; `docex check`
passes the new `consumes`-target `port` + `health_check_path` assertion.

---

# Stage D — `CHANGELOG.md`

`$jb/CHANGELOG.md`. One `## [1.6.0] - 2026-07-29` entry covering mods 094-106,
Keep a Changelog format, in the voice of the existing `[1.5.0]` / `[1.4.0]`
entries — **read those two first** and match their bullet density and technical
level.

A drafted entry will be supplied by the supervising agent. If it is not
available, build it by reading all thirteen `overview.md` files under
`$jb/docex/plans/modifications/09*_*/` and `10*_*/` (094-106) — **not** the
diff. Mod 096 alone is 58 files and its intent is not recoverable from the diff.

Requirements:
- Organize by user-visible change, not mod by mod.
- Lead `Changed` with the headline (codebase + N process types → `<svc>-<proc>`).
- Mark breaking changes explicitly, following whatever convention the existing
  entries use.
- `Fixed` must carry the latent/silent-failure bugs with enough detail that a
  reader understands what was broken — among them the ansible `schema_owned_by`
  comparison that would have emitted **no migrate tasks while reporting
  success**, the `curl` gate being a no-op, `_infer_contract_format`'s
  provably-unreachable asyncapi branch, hyphenated four-segment magic refs
  emitted as literal text, and `docex build dev` broken for scheduler-only
  codebases.
- Note `replicas` was declared, range-checked, documented, and **read by
  nothing** until this release (`desired_count` hardcoded to 1).
- Reference `upgrades/upgrade_1.6.0.md` where existing entries reference theirs.
- Roll `[Unreleased]` per `RELEASING.md` step 3, leaving an empty
  `[Unreleased]` heading above the new entry if that is the file's convention.

---

# Stage E — Version artifacts, the docstring, and the Q5 attempt

## E.1 — Bump to 1.6.0

The four artifacts `RELEASING.md` tracks (all currently `1.5.0`, all in sync):

| File | Field |
| ---- | ----- |
| `$jb/VERSION` | the whole file |
| `$jb/docex/pyproject.toml` | `version` |
| `$jb/docex/src/docex/__init__.py` | `__version__` |
| `$jb/.claude-plugin/plugin.json` | `version` — **load-bearing**, the plugin cache key |

Plus two the table omits:

- `$jb/docex/uv.lock` — carries docex's own version (~line 62). Bump it (or
  re-lock) or it silently goes stale.
- `$jb/docex/test_projects/{fixed,elastic}/project.yml` — `docex_version`,
  already handled in A.8.3.

**Do not** touch `skill_iter/**` fixtures, which also pin 1.5.0 but are the
operator's untracked work.

Verify with a repo-wide grep for `1\.5\.0` afterwards and confirm every
remaining hit is a legitimate historical reference (changelog entries, prior
upgrade guides, mod docs) rather than a live declaration.

## E.2 — `compose_exec` docstring

`$jb/docex/src/docex/docker/client.py`, the `compose_exec` docstring (~:112-127).
It claims to be "the primary mechanism used by `docex build`, `docex migrate`,
and the build-test step of `docex test`". All three moved to
`compose_run_one_off` in Mod 099 (`migrate.py:116`, `build.py:146`,
`test.py:103,127`).

Rewrite the docstring to say what is true: a general-purpose exec against an
**already-running** container, with **no current production call sites**, kept
as part of the docker protocol surface. **Do not delete the method** — deletion
touches the protocol, the implementation, the fake, and four tests asserting its
absence from call lists, and this is the wrong mod for that. A protocol method
with no caller is unremarkable; a docstring naming three callers it no longer
has is actively misleading.

## E.3 — Q5: the unreachable `cicl_version` message (attempt, with bail-out)

**Problem.** `$jb/docex/src/docex/cicl/model.py:298-317` validates
`cicl_version` in a `@model_validator(mode="after")` on `CICLDocument`, which
runs only after nested field validation succeeds. A real v1 `infra.yml` fails
inside `CoreService` first, so the operator never sees the bespoke message
naming `upgrades/upgrade_1.6.0.md` — the single most-read error the release
produces, hit by every downstream project exactly once, while upgrading.
Reproduce it first (Stage A.9's command against an un-migrated `infra.yml`) so
you have the real output.

**Attempt.** Move the version check to a `@model_validator(mode="before")` on
`CICLDocument` reading the raw dict, so it fires *before* nested models are
built. Keep the existing message text and the unknown-version fallback. Add
**one** unit test asserting a v1 document with flat core services surfaces the
`cicl_version` message (not field-scoping errors).

**Bail-out — take it without hesitation.** If this costs more than that one
validator relocation plus one test — e.g. it perturbs other tests' expected
error text, breaks `mode="before"` assumptions about raw-vs-parsed input, or
requires reordering unrelated validators — **stop, revert, and document
instead.** The field-scoping errors are good and do name the guide, so the
fallback is genuinely acceptable.

**Report which path you took.** It changes both Stage C's step 1 (which error
the guide documents) and the expected suite numbers (+1 if taken, unchanged if
not).

---

# Final checks and report

1. `pytest tests/unit` and `pytest tests/` from `$jb/docex` with
   `/home/ubuntu/.local/bin/pytest`. Report **both** numbers against the
   baseline **982 / 1046**, and state whether Q5 was taken (+1 each if so).
2. Both smoke projects compile, with the Stage A.9 output assertions confirmed
   item by item.
3. `diff -r fixed/core elastic/core` empty.
4. `git status --porcelain` — confirm nothing under `doctrine/`, `agents/`,
   `engineer/`, `skill_iter/`, or `skills/` changed beyond the 118 baseline
   entries. Compare against
   `/tmp/claude-1000/-home-ubuntu--claude-jean-baudrillard/26086b69-c94f-4900-95fc-b375cba7aaec/scratchpad/baseline_dirty.txt`.
5. **Do not commit.** The supervising agent handles commits with explicit
   pathspecs (the index holds staged renames from prior mods, so a bare
   `git commit -a` would sweep in unrelated work).

In the report, call out separately: anything where the compiled output did not
match Stage A.9's expectations; any place the doctrine and the emitted reality
disagreed; and any inherited claim in this document that proved wrong.

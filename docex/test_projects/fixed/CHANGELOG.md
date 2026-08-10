# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Health left HTTP. Every core service now supplies a **container probe**,
`./health.sh <service>`, and the orchestrator is the only thing that reads it.
On this foundation docker only *reports*: a failing container is marked
`unhealthy` and nothing in the compiled stack restarts it or reroutes around it.
The consequence is a release gate rather than a restart — `docex stagetest`
reads `docker inspect`'s `.State.Health.Status` over SSH and fails on anything
that is not `healthy`. (On the elastic companion, ECS kills and replaces the
task instead.)

### Changed

- **The container probe is `./health.sh <service>` on both foundations.** It is
  emitted by the role transfer tables as a `defaults` entry rather than derived
  from any authored field, so a core service gets a probe by being a core
  service. `interval: 30s`, `timeout: 5s`, `retries: 3` are unchanged.
- **`api.worker` and `api.clock` liveness is a tick file, not an HTTP route.**
  The loop touches `/tmp/<service>.tick` at the end of each successful
  iteration and `./health.sh` stats it from a separate process, failing when the
  file is absent or more than 30 s old. An absent file fails deliberately: a loop
  that never completed an iteration was never alive. The 30 s threshold lives in
  `health.sh` and the ≤10 s tick cadence in the entrypoints, and the two only
  mean anything as a pair — 30 is three times 10, so a healthy loop misses two
  consecutive ticks before it is called stale.
- **`api.web`'s two backing probes moved to `/diagnostics/*`.**
  `GET /health/probe` → `GET /diagnostics/probe` and `GET /health/events` →
  `GET /diagnostics/events`. They probe *backing* services; under `/health/*` a
  reader would reasonably conclude the deleted fan-out survived under a narrower
  name.
- **Contract filenames gained a surface segment.** The path is now
  `<codebase>.<service>.<surface>.<format>.<ext>`, so `api.web.openapi.yml` →
  `api.web.rest.openapi.yml` and `api.worker.asyncapi.yml` →
  `api.worker.events.asyncapi.yml`. The format follows from the surface's
  `api_styles`, never from the core service's `role`.
- **Contract spec floors raised** to OpenAPI 3.2 and AsyncAPI 3.0.
- **`api.clock` dropped its `port`.** It declares no port, no surface, and binds
  no application socket; its entrypoint imports neither uvicorn nor fastapi.
- **`api.worker` and `api.clock` dropped `health_check_path`.** That field is
  confined to `web`-network core services, where it is what the reverse proxy
  reads. `api.web` keeps it.

### Added

- **`core/api/health.sh`** — the codebase's fourth shim, beside `build.sh`,
  `test.sh`, and `migrate.sh`, and the only one invoked *per core service*. Its
  exit code is its entire contract; nothing reads its stdout. Three arms: `web`
  curls its own `/health`, `worker` and `clock` stat their tick file, and an
  unrecognised argument exits 2 loudly rather than falling through to 0.
- **An `rpc` surface on `api.worker`** — `POST /drain`, returning
  `{"performed": N}` — and **`api.web`'s consumer side of it**, exposed as
  `POST /jobs/drain`. The perform side of the deferred-job queue belongs to the
  worker, so the edge asks rather than performs. This is the codebase's only
  cross-core-service call and the reason `api.worker` carries a `port` at all.
- **`infra/contracts/api.worker.rpc.asyncapi.yml`** — the worker now declares two
  surfaces, `rpc` and `events`, both resolving to `asyncapi`. Two rather than one
  because their consumer sets are unrelated.
- **`test_defer_and_drain_round_trip`** in the stage suite — defers a heartbeat
  through the public edge, then drains it and asserts a `200` with an integer
  `performed`. Deliberately not a count: the worker drains on its own interval,
  so `{"performed": 0}` is an honest reply.
- **Three codebase tests** in `core/api/tests/test_jobs_drain.py` covering the
  drain service's delegation and the provider adapter's success and failure
  translations.

### Removed

- **`GET /health/api/worker` and the health fan-out.** No core service reports on
  another's health any more, and none may: liveness is read from the orchestrator
  rather than proxied through a peer.
- **`GET /health` on `api.worker` and `api.clock`.** The route survives on
  `api.web` alone, because a reverse proxy reads it and has no other way to ask.
- **The clock's uvicorn/fastapi listener**, entirely. `entrypoints/clock.py` now
  runs a cron loop and nothing else.
- **The stage suite's fan-out test**, with the endpoint it exercised.

## [0.0.20] - 2026-08-10

Documentation corrections found by the advance-006 coherence pass (docex mod
134b). No code, config, or behavior change — every edit here makes a document
say what the seed actually does.

### Fixed

- **`db_schema.md` claimed `pings.id` was a `uuid7`** generated "for
  time-ordered insertion". The domain calls `uuid4()`, which is random, so both
  the function and the stated property were wrong. The table's ordering comes
  from `created_at`.
- **`db_schema.md` stated the doctrine requires migrations to be "reversible".**
  `databases.md` requires them to be idempotent and **forward-only** — the
  doctrine never reverses a schema, even on rollback, and `docex rollback` runs
  no migration at all. The `-- migrate:down` half of each file is dbmate's file
  format, not a path the pipeline takes.
- **`processor.md` said multi-worker coordination was "out of scope for this
  seed".** `FOR UPDATE SKIP LOCKED` ships in the `jobs` module and four other
  seed docs treat it as load-bearing. The boundary is real but belongs to
  `processor` alone, whose work is a no-op and so has nothing to contend over.
- **`test.sh`'s comment enumerated five of seven test files**, omitting
  `test_jobs_alogic.py` and `test_jobs_drain.py`. The script globs the whole
  folder, so only the comment was short; it now says the glob is the authority.
- **Four dead section citations repointed** — `infra.yml`'s
  `cicl.md § Field scoping` (the heading is `cicl_reasoning.md § Field Scoping`)
  and `cicl.md § Three clarifications` (prose inside rule 7, not a heading), and
  `transfer_tables.md § naming` in **both** `verify_clean.sh` and `teardown.sh`
  (the heading is `§ Naming Policies`). The two shell scripts carry the same
  comment, so fixing one would have left the pair disagreeing about which
  spelling is current. None was a markdown link, so nothing mechanical could
  resolve any of them.

## [0.0.19] - 2026-08-06

Repairs found by the `1.7.0` pre-cut fixed-foundation smoke walk. No feature
change; every edit here makes an existing check or test able to do its job.

### Fixed

- **The `jobs` tests no longer assume they are the only actor.** `docex test`
  brings the whole `test` env up, so a live `api.worker` drains the same queue
  the suite writes to. `test_jobs_concurrency.py` now accounts for the worker as
  a **third claimer** — identifiable because it stamps a "no handler" error on
  the test's marker rows — and asserts exclusivity across all three, which is
  strictly stronger than the two-thread form it replaces. Assertions that
  required sole agency moved to a new stub-queue alogic file,
  `tests/test_jobs_alogic.py`.
- **`verify_clean.sh` can now fail.** It reported `OK: registry images` while
  thirty tags remained: the registry query was unauthenticated and 401'd, the
  reply was swallowed, and empty was read as clean. It now authenticates,
  enumerates `/v2/_catalog` (so repos retired by a rename are visible),
  matches image names in every form they take, and **fails whenever a check
  cannot be answered** rather than reporting zero.
- **`teardown.sh` actually deletes.** Same auth and catalog fixes, plus the OCI
  index media type in `Accept` — buildx pushes an index, so the old
  `manifest.v2+json` request resolved no digest and the delete never ran.

### Added

- **The clock validates its schedule at startup.** A scheduled job name with no
  binding in the clock's dispatch table now fails the deploy, before the cron
  loop is entered, naming both the offending job and the implemented set. A
  bound job with *no* schedule remains legitimate and is deliberately not
  reported — the driving port is shared, so a job reachable only over HTTP or
  CLI is a valid design.

## [0.0.17] - 2026-08-06

This entry covers **four doctrine changes at once**, because the seed was carried
through the whole `1.7.0` advance before being committed. They landed in the
doctrine as separate mods; they reach this project together.

### Changed

- **Vocabulary rename (`cicl_version` 2 → 3).** What was a *core service* is now a
  **codebase**; what was a *process type* is now a **core service**. In
  `infra.yml`: top-level `core_services:` → `codebases:`, nested `processes:` →
  `core_services:`. Core magic refs gain the collection segment and are now five
  segments — `${codebases.api.core_services.worker.host}`.
- **`depends_on:` and `consumes:` merged into one `uses:` field.** A bare entry
  names a backing service, a dotted one names a core service. Backing services
  declare no outbound edges at all — they are graph sinks. No core-service block
  carries a compose `depends_on:` any more; the per-codebase `-exec` block is the
  only surviving ordering emission, and it still gates `migrate.sh` on a cold
  database.
- **`cicl_version` is `"3"`.** Generation `"2"` is rejected, not shimmed.
- `api.worker`'s AsyncAPI contract now declares two consumed boundaries: unclaimed
  `pings` rows and deferred `jobs` rows.

### Added

- **`api.clock` — a `clock` core service, the third invocation of the `api`
  image.** A long-running singleton cron loop that reads its schedule from
  `DOCEX_SCHEDULES_YAML` (the *literal* rendered YAML, identical on both
  foundations — not a path) and **defers** each fired job onto the `jobs` table.
  Emits a compose service with a docker `healthcheck:` on `:8082/health` and a paired otelcol sidecar. Two jobs: `prune_pings` at `0 3 * * *`, and `heartbeat`
  every minute so the fire → defer → drain path is observable inside a smoke walk.
- **`jobs` hex module** — the deferred-work queue, holding both halves of the
  deferral contract. `QueueJobsPostgres.claim()` uses `FOR UPDATE SKIP LOCKED`:
  exclusivity against `api.worker`'s two prod replicas, plus liveness so the
  second replica does not block behind the first's batch.
- **`retention` hex module** — the retired `reaper` codebase's rule, unchanged,
  now reached only as the `prune_pings` job's handler.
- `jobs` table migration; `POST /jobs/prune_pings` and `POST /jobs/heartbeat` on
  `api.web` (the same driving port the clock fires, so firing a scheduled job by
  hand is no longer a special path); `tests/test_jobs_concurrency.py`, which
  drives the two-consumer race in `test` rather than leaving it to first occur in
  the prod release.

### Removed

- **The `reaper` codebase, entirely** — tree, `infra.yml` block, scripts,
  Dockerfile, tests, and the Ofelia trigger container and its generated INI.

  It could not simply become a clock. A clock defers onto its **own** codebase's
  queue, only the codebase that owns a schema may enqueue, and `reaper` owned no
  schema (it reached into `api`'s `pings` table), no worker, and no queue. `api`
  owns all three.

  Before this change the emitted set was compose services `…-api-web` / `…-api-worker`, plus the `reaper-prune` Ofelia trigger. **This project now has one
  codebase on purpose.** What that costs the smoke walk is recorded in
  `docex/plans/core/test_projects.md § Shape` — a future reader who finds one
  codebase where two are expected should read that before assuming drift.
- `role: scheduler` no longer exists anywhere in the doctrine.

## [0.0.16] - 2026-07-29

### Changed

- Version bump only, to give the 1.6.0 pre-cut rollback walk (C.10) a prior
  version to roll back from. No functional change.

## [0.0.15] - 2026-07-29

### Changed

- **Migrated to `cicl_version: "2"`** — process types. The two core services
  `web` and `worker` collapse into **one codebase `api`** declaring two process
  types, `api.web` and `api.worker`; they always shared a database, a table, and
  six identical `DATABASE_*` refs, and were only ever split because pre-v2 CICL
  had no way to say "one artifact, two invocations". The `reaper` codebase keeps
  its name and gains one process type named after the job, `reaper.prune`.
  Emitted identities are now two-segment: compose services `…-api-web` and `…-api-worker`, plus the `reaper-prune` Ofelia trigger.
- `worker` moves from `role: web` (a pre-1.6.0 workaround — the role did not
  exist) to the first-class **`role: worker`**, which is also what makes its
  contract AsyncAPI.
- `domain_default_service: web` → `domain_default_process: api.web`, dotted and
  fully qualified. `schema_owned_by: web` → `api` — it names a codebase, never
  a process type.
- `env:` is deliberately **split across both levels**: the six `DATABASE_*` refs
  sit at the `api` service level (both process types need a database), while the
  `SIDECAR_*`/`CLICKHOUSE_*` refs stay on `api.web`. Hoisting the latter would
  oblige *every* process type to declare the edge (rule 7), forcing the worker
  to `depends_on` backings it never touches.
- `core/web/` → `core/api/`, absorbing `core/worker/src/hex/processor/`;
  `core/worker/` is gone. Contract `web.openapi.yml` → `api.web.openapi.yml`.
  Inner docs `plans/core/{web,worker}/` → `plans/core/api/`.
- Both Dockerfiles' `CMD` now points at an entrypoint rather than `root.py`, and
  carries a note that `command` supersedes it for core services. The `reaper`
  Dockerfile's mod-074 header is retired: the job runs the **codebase's** image
  tag (mod 103), so `dev` launches the `dev` stage, not a separate self-contained
  job image.
- `teardown.sh` / `verify_clean.sh` iterate codebases (`api reaper`) rather than
  `web worker`. **Fixes a pre-existing leak:** `reaper` was in neither list, so
  its registry repo survived teardown and `verify_clean` could not see it.
- Repinned `docex_version` to `1.6.0`. A `cicl_version: "2"` project cannot
  compile under a 1.5.0 image.

### Added

- **`src/entrypoints/`** in both codebases, one module per process type, per
  `internal_dependency_rules.md § Entrypoints`. `root.py` now **constructs but
  does not activate** — it opens no socket, starts no server, and runs no loop.
  `api` exposes `build_app()` and `build_processor()`; `reaper` exposes
  `build_reaper()`.
- **A liveness tick in `api.worker`.** `entrypoints/worker.py` owns the poll
  loop (1 s), the SIGTERM handling, and a `GET /health` on port 8081 that 503s
  once the loop's monotonic tick is 30 s stale. Thresholds are doctrine-fixed
  (`contracts.md § Health Checks`) — tick at least every 10 s even when idle, 30 s
  staleness, no knob. The tick is **not** bumped in the exception path: a loop
  failing every iteration is not alive. uvicorn runs in a daemon thread and the
  loop in the main thread so SIGTERM reaches the loop.
- **`GET /health/api/worker`** on the web edge — the doctrine-required `consumes`
  fan-out (`contracts.md § Fan-out`), one hop only with a hard 3 s timeout, never
  calling the target's own fan-out endpoints. Declared in
  `api.web.openapi.yml` and probed by the stage smoke tests, which is the only
  place the worker's liveness is observable end to end.
- **`infra/contracts/api.worker.asyncapi.yml`** — required because `api.worker`
  is a `consumes` target and therefore a provider, with the format following
  from its role. Its header records the advance's known loose end rather than
  hiding it: the doctrine ships no `queue` role, so this worker's "queue" is the
  `pings` **table** and the AsyncAPI channel addresses a table, not a topic.
- `api.worker` declares `port: 8081` + `health_check_path`. A worker is never
  routed, but a `consumes` target must be probeable — and on the elastic companion the port is also what makes it Service-Connect-discoverable.
- `replicas: 2` on `api.worker`. Honoured in `prod` only (clamped to 1 in dev/test/stage), which makes the prod release the **only** thing that exercises the compose replica unroll — two services suffixed `-1`/`-2` sharing one network alias.

## [0.0.14] - 2026-07-11

### Changed

- Rollback-walk bump (second version so the pre-cut walk can roll prod back to 0.0.13).

## [0.0.13] - 2026-07-11

### Changed

- Pre-cut smoke walk under the docex 1.5.0 release candidate (release + rollback
  paths on the fixed foundation).

## [0.0.11] - 2026-07-07

### Added

- New `reaper` **scheduler** core service — a cron job (`0 3 * * *`) that prunes
  processed `pings` older than a 30-day retention window. Adds smoke coverage for
  the doctrine `scheduler` role end-to-end (Ofelia container on fixed) and for the
  `test`-env trigger suppression. Own hex module: `RetentionWindow` domain value,
  `ReaperService` alogic, a minimal `RepoPingsPostgres` (`delete_processed_before`),
  and a `ContReaperCli` driving adapter. Source is identical to the elastic
  companion's `reaper`. The job runs from the self-contained `prod` image stage
  (the scheduler trigger launches it with no bind-mounts). Exercising it in a
  smoke walk requires a docex version carrying the fixed-scheduler emit fixes
  (mods 073–075), so the `docex_version` pin advances when that version ships.

## [0.0.5] - 2026-06-09

### Changed

- Repinned to docex 1.0.3 (mod 048 — elastic-side bug bundle). No
  fixed-side changes were needed in this cut (mod 048 covers elastic
  bugs the fixed walk doesn't surface), but the repin keeps the two
  test projects in lockstep on the current docex version.

## [0.0.4] - 2026-06-09

### Changed

- Repinned to docex 1.0.2 (mod 047) after the fixed-foundation smoke
  walk surfaced four bugs in 1.0.1. The fix bundle is in docex
  1.0.2's CHANGELOG; for this project the practical effects are:
  per-project traefik now uses v3.6 (working docker provider),
  emits `traefik.docker.network` so multi-network web services route
  correctly, and the `docex check` health-endpoints gate no longer
  demands `/health/<backing>` entries. Recompiled output reflects all
  three. Inner-repo state is `main` at v0.0.4, walked clean through
  C.1–C.11 against docex 1.0.2 (the 0.0.3 walk produced the bug
  reports that drove 1.0.2).

## [0.0.3] - 2026-06-09

### Fixed

- Stage tests use `httpx.Client(verify=False)` until docex emits AWS
  creds for the project traefik (needed for ACME DNS-01 via Route53).
  Until then, traefik serves its self-signed default cert and httpx
  rejects with CERTIFICATE_VERIFY_FAILED. Tracked as a docex gap in mod
  047.

## [0.0.2] - 2026-06-09

### Fixed

- `core/web/Dockerfile` now installs `curl`. The doctrine-emitted docker
  healthcheck for the `web` core service (from the `health_check_path`
  field translation in transfer table `web/container`) runs
  `CMD curl -f http://localhost:8080/health`. `python:3.12-slim` doesn't
  carry curl, so the container stayed perpetually `unhealthy` and
  traefik 3.x's docker provider filtered it out of its router config —
  rendering the service unreachable. Adding curl is project-side; the
  long-term doctrine fix (likely switching to traefik HTTP healthcheck
  via service labels) is tracked in docex mod 047 / 1.0.2.

## [0.0.1] - 2026-06-09

### Added

- Project re-incepted against doctrine docex 1.0.0 (post shape-and-tier
  advance) and then immediately repinned to docex 1.0.1 (mod 046, the
  naming-policy leak patch). The inner git history starts fresh at this
  version; the compiled output reflects the 1.0.1 fix (data-plane names
  hyphenate the project segment everywhere doctrine prescribes). See
  `../PRE_CUT_CHECKLIST.md` for the walk.
- `infra.yml` declares `apex_domain: luxrnd.tech` (mod 031's bare-apex
  rule); project subdomain derives to `docex-smoke-fixed.luxrnd.tech`.
- Project-local transfer tables `infra/transfer_tables/{sidecar,clickhouse}.yml`
  preserved from the prior seed; they keep the project-local
  transfer-table feature exercised on every cut.

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Health left HTTP. Every core service now supplies a **container probe**,
`./health.sh <service>`, and the orchestrator is the only thing that reads it.
On this foundation that has teeth: ECS **kills and replaces** a task whose
essential container fails its probe, which is why the role tables also emit
`startPeriod: 10` — elastic-only, and there to give a loop time to complete its
first iteration before an absent tick file can kill the task.

### Changed

- **The container probe is `./health.sh <service>` on both foundations.** It is
  emitted by the role transfer tables as a `defaults` entry rather than derived
  from any authored field, so a core service gets a probe by being a core
  service. `interval: 30s`, `timeout: 5s`, `retries: 3`, `startPeriod: 10`.
- **`api-web`'s task definition gains a container `healthCheck` it never had.**
  Before this change the `web` role routed `health_check_path` to the ALB target
  group *only*, so the task definition carried no `healthCheck` at all and a
  wedged web process was visible only to the load balancer. It is now visible to
  ECS as well.
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
  `GET /diagnostics/events`. They probe *backing* services — the nginx sidecar
  and the EFS-backed ClickHouse task — and remain the project's only exercise of
  Service Connect resolution and security-group reachability to them. Under
  `/health/*` a reader would reasonably conclude the deleted fan-out survived
  under a narrower name.
- **Contract filenames gained a surface segment.** The path is now
  `<codebase>.<service>.<surface>.<format>.<ext>`, so `api.web.openapi.yml` →
  `api.web.rest.openapi.yml` and `api.worker.asyncapi.yml` →
  `api.worker.events.asyncapi.yml`. The format follows from the surface's
  `api_styles`, never from the core service's `role`.
- **Contract spec floors raised** to OpenAPI 3.2 and AsyncAPI 3.0.
- **`api.clock` dropped its `port`, and with it leaves the Service Connect
  registry.** Its `service_connect_configuration` keeps `enabled` and the
  namespace but no longer emits a `service {}` block, so it is now a **client-only**
  member: it resolves its peers and nothing can resolve it. That is correct —
  nothing addresses a clock. Its `portMappings` block is gone too. It binds no
  application socket at all; its entrypoint imports neither uvicorn nor fastapi.
- **`api.worker` and `api.clock` dropped `health_check_path`.** That field is
  confined to `web`-network core services, where it compiles to the ALB target
  group's health check. `api.web` keeps it, and it remains the one consumer the
  field has.

### Added

- **`core/api/health.sh`** — the codebase's fourth shim, beside `build.sh`,
  `test.sh`, and `migrate.sh`, and the only one invoked *per core service*. Its
  exit code is its entire contract; nothing reads its stdout, and ECS does not
  even capture it. Three arms: `web` curls its own `/health`, `worker` and
  `clock` stat their tick file, and an unrecognised argument exits 2 loudly
  rather than falling through to 0.
- **An `rpc` surface on `api.worker`** — `POST /drain`, returning
  `{"performed": N}` — and **`api.web`'s consumer side of it**, exposed as
  `POST /jobs/drain`. The perform side of the deferred-job queue belongs to the
  worker, so the edge asks rather than performs. This is the codebase's only
  cross-core-service call, the reason `api.worker` carries a `port` at all, and
  now the reason its Service Connect registration is load-bearing.
- **`infra/contracts/api.worker.rpc.asyncapi.yml`** — the worker now declares two
  surfaces, `rpc` and `events`, both resolving to `asyncapi`. Two rather than one
  because their consumer sets are unrelated.
- **`test_defer_and_drain_round_trip`** in the stage suite — defers a heartbeat
  through the public edge, then drains it and asserts a `200` with an integer
  `performed`. The `200` is the load-bearing part: it cannot be answered without
  `api.web` resolving `api.worker` over Service Connect and reaching it through
  the `internal` security group. Deliberately not a count — the worker drains on
  its own interval, so `{"performed": 0}` is an honest reply.
- **Three codebase tests** in `core/api/tests/test_jobs_drain.py` covering the
  drain service's delegation and the provider adapter's success and failure
  translations.

### Removed

- **`GET /health/api/worker` and the health fan-out.** No core service reports on
  another's health any more, and none may: liveness is read from the ECS API
  rather than proxied through a peer or fetched through the ALB.
- **`GET /health` on `api.worker` and `api.clock`.** The route survives on
  `api.web` alone, because the ALB target group reads it over the network and has
  no way to run a command inside a container.
- **The clock's uvicorn/fastapi listener**, entirely. `entrypoints/clock.py` now
  runs a cron loop and nothing else.
- **The stage suite's fan-out test**, with the endpoint it exercised.

## [0.0.24] - 2026-08-10

Documentation corrections found by the advance-006 coherence pass (docex mod
134b). No code, config, or behavior change — every edit here makes a document
say what the seed actually does.

### Fixed

- **`masterplan.md`'s per-env hostnames were missing the codebase segment.**
  They read `<service>.<env>.docex-smoke-elastic.luxrnd.tech`; compiled output
  is `api-web.<env>.…`. Aligned to the canonical form the fixed companion
  already states — `<codebase>-<service>`, two segments in one DNS label,
  hyphen-joined.
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
- **Three dead section citations repointed** in `infra.yml`:
  `cicl.md § Field scoping` (the heading is
  `cicl_reasoning.md § Field Scoping`), `cicl.md § Three clarifications` (prose
  inside rule 7, not a heading), and `cicl.md § Container Registry` (the heading
  is `§ Container Registry and Service Images`). None was a markdown link, so
  nothing mechanical could resolve them.

## [0.0.20] - 2026-08-06

Repairs found by the `1.7.0` pre-cut **fixed**-foundation smoke walk, applied
here because the `core/` trees are byte-identical across seeds — and because
this seed's `verify_clean.sh` turned out to carry a larger version of the same
defect. No feature change.

### Fixed

- **The `jobs` tests no longer assume they are the only actor.** `docex test`
  brings the whole `test` env up, so a live `api.worker` drains the same queue
  the suite writes to. `test_jobs_concurrency.py` now accounts for the worker as
  a **third claimer** and asserts exclusivity across all three, which is
  stronger than the two-thread form it replaces. Assertions needing sole agency
  moved to a new stub-queue alogic file, `tests/test_jobs_alogic.py`.
- **`verify_clean.sh` can now fail.** It had **21** query sites that swallowed
  errors and **no credential preflight**, so expired credentials, a wrong
  region, or one missing IAM permission made all ~20 AWS checks report `OK` and
  the script exit 0 — on the gate that certifies this account has stopped
  costing money. Every query now fails loudly when it cannot be answered, a
  preflight aborts early and **echoes the account id and region** (a clean run
  against the wrong account is its own false green), and the two presence checks
  now distinguish *resource absent* from *call failed*.
- **Local docker images are checked and torn down.** Neither script touched them
  before; the first repaired run found **14** leftovers, including images from
  the retired `reaper` codebase.

### Added

- **The clock validates its schedule at startup.** A scheduled job name with no
  binding now fails the deploy before the cron loop is entered, naming both the
  offending job and the implemented set. A bound job with *no* schedule stays
  legitimate and is deliberately not reported.

## [0.0.19] - 2026-08-06

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
  Emits a `task_definition` + `ecs_service` with a container-level ECS health check, no target group, and `deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100` so a rolling deploy cannot double-fire. Two jobs: `prune_pings` at `0 3 * * *`, and `heartbeat`
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
  Dockerfile, tests, and the `aws_scheduler_schedule`, the EventBridge Scheduler target, and the per-service scheduler-invocation IAM role — one fewer AWS resource type `verify_clean.sh` must check for leaks.

  It could not simply become a clock. A clock defers onto its **own** codebase's
  queue, only the codebase that owns a schema may enqueue, and `reaper` owned no
  schema (it reached into `api`'s `pings` table), no worker, and no queue. `api`
  owns all three.

  Before this change the emitted set was ECS services `api-web` / `api-worker`, plus a `reaper-prune` scheduled task. **This project now has one
  codebase on purpose.** What that costs the smoke walk is recorded in
  `docex/plans/core/test_projects.md § Shape` — a future reader who finds one
  codebase where two are expected should read that before assuming drift.
- `role: scheduler` no longer exists anywhere in the doctrine.

## [0.0.18] - 2026-07-30

### Changed

- Rollback-walk bump for the confirmatory 1.6.0 pre-cut elastic walk
  (`PRE_CUT_CHECKLIST § D.12`). Two versions must coexist in ECR for
  `docex rollback prod 0.0.17` to have a prior release to converge on. No
  application or infrastructure change.

## [0.0.17] - 2026-07-30

### Changed

- Version bump for the **confirmatory** 1.6.0 pre-cut elastic walk. The first
  walk found two docex defects (mods 108 and 109) and was therefore an
  assembled pass — D.1-D.8 ran on one image, D.9+ on another. This walk runs
  D.1-D.13 end to end against the final candidate so the cut does not rest on
  a spliced result. No application or infrastructure change.

## [0.0.16] - 2026-07-29

### Changed

- Rollback-walk version bump for the 1.6.0 pre-cut elastic smoke walk
  (`PRE_CUT_CHECKLIST § D.12`). Two versions must coexist in ECR for
  `docex rollback prod 0.0.15` to have a prior release to converge on. No
  application or infrastructure change.

## [0.0.15] - 2026-07-29

### Changed

- **Migrated to `cicl_version: "2"`** — process types. The two core services
  `web` and `worker` collapse into **one codebase `api`** declaring two process
  types, `api.web` and `api.worker`; they always shared a database, a table, and
  six identical `DATABASE_*` refs, and were only ever split because pre-v2 CICL
  had no way to say "one artifact, two invocations". The `reaper` codebase keeps
  its name and gains one process type named after the job, `reaper.prune`.
  Emitted identities are now two-segment: ECS services and task definitions `api-web` and `api-worker`, plus a `reaper-prune` scheduled task with no `ecs_service`; one ECR repo and one `…-migrate` task-definition family per **codebase**.
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
  routed, but a `consumes` target must be probeable — and on elastic the port is also exactly what makes it Service-Connect-discoverable, which is what lets the sibling `api.web` task reach its `/health` one hop away.
- `replicas: 2` on `api.worker`. Honoured in `prod` only (clamped to 1 in dev/test/stage), so prod's `api-worker` ECS service carries `desired_count = 2` and stage carries 1.

## [0.0.14] - 2026-07-11

### Changed

- Rollback-walk bump (second version so the pre-cut walk can roll prod back to 0.0.13).

## [0.0.13] - 2026-07-11

### Changed

- Pre-cut smoke walk under the docex 1.5.0 release candidate (release + rollback
  paths on the elastic foundation).

## [0.0.11] - 2026-07-07

### Added

- New `reaper` **scheduler** core service — a cron job (`0 3 * * *`) that prunes
  processed `pings` older than a 30-day retention window. Adds smoke coverage for
  the doctrine `scheduler` role on elastic (EventBridge Scheduler → ECS `RunTask`,
  no `ecs_service`, per-service scheduler-invocation IAM role) and for the
  `test`-env trigger suppression. Own hex module: `RetentionWindow` domain value,
  `ReaperService` alogic, a minimal `RepoPingsPostgres` (`delete_processed_before`),
  and a `ContReaperCli` driving adapter. Source is identical to the fixed
  companion's `reaper`. Elastic secret delivery reuses the task-def `secrets[]`/SSM
  path, so no fixed-side ofelia plumbing applies.

## [0.0.5] - 2026-06-09

### Fixed

- `teardown.sh` walks the post-mod-035 project-tier path
  (`infra/output/project/production/main.tf`) explicitly. The previous
  loop checked `infra/output/$layer/main.tf` and silently skipped the
  project tier (mod 035 had split the layout into per-side
  subdirectories). Without this fix, the project-tier `tofu destroy`
  is skipped, the state bucket is destroyed in step 6 anyway, and
  project-tier resources (ALB, ACM, Route53 zone) are left orphaned —
  `verify_clean.sh` fails. Now uses an explicit layer→path map.

### Changed

- Repinned to docex 1.0.3 (mod 048). Mod 048's three docex fixes
  (`projinfra up development` not a stub anymore, `migrate.py` master-
  VPC + hyphenated SG lookups, bare-project A-record on prod env-tier
  ALB emit) all apply to this project's release path.

## [0.0.4] - 2026-06-09

### Changed

- Version-only bump to exercise the rollback walk (D.12). No code or
  config changes; smoke walk needs two versions in ECR for the
  rollback path to flow.

## [0.0.3] - 2026-06-09

### Fixed

- `core/web/Dockerfile` installs curl. Doctrine-emitted docker
  healthcheck (`CMD curl -f`) needs it; without curl the container is
  marked unhealthy and traefik 3.x's docker provider filters it out.
  Same fix as the fixed companion at v0.0.2 — propagated here to
  preserve core-tree parity per `test_projects.md`.

## [0.0.2] - 2026-06-09

### Changed

- Repinned to docex 1.0.2 (mod 047) so this project picks up the bug
  fixes from the fixed-foundation walk. Specifically: per-project
  traefik on dev-side uses v3.6, emits
  `traefik.docker.network`, and `docex check` no longer requires
  `/health/<backing>` entries. None of these directly affect elastic
  production-side resources (which use the ALB, not per-project
  traefik), but they all matter for the dev-side compose stack.
  Walk against 1.0.2 is gated on operator-side master-VPC stand-up
  (currently blocked by us-east-1 VPC quota cap).

## [0.0.1] - 2026-06-09

### Added

- Project re-incepted against doctrine docex 1.0.0 (post shape-and-tier
  advance) and then immediately repinned to docex 1.0.1 (mod 046,
  the naming-policy leak patch). The inner git history starts fresh at
  this version; the compiled output reflects the 1.0.1 fix — Route53
  zone, ACM cert SANs, Service Connect namespace, docker network names,
  OTel sidecar names, and project traefik all hyphenate the project
  segment (`docex-smoke-elastic`) rather than carrying the underscored
  `docex_smoke_elastic` form that AWS rejects in DNS contexts. See
  `../PRE_CUT_CHECKLIST.md` for the walk.
- `infra.yml` declares `apex_domain: luxrnd.tech` (mod 031's bare-apex
  rule); project subdomain derives to
  `docex-smoke-elastic.luxrnd.tech`. NS-delegated from the parent
  `luxrnd.tech` zone in Route53 during the two-phase
  `projinfra up production` apply.
- `infra.yml` declares `reverse_proxy: alb` (mod 044's default). The
  EC2-traefik variants exist but are not exercised by this smoke
  project per operator decision; ALB is the doctrine default and
  what's covered here.
- Project-local transfer tables `infra/transfer_tables/{sidecar,clickhouse}.yml`
  preserved from the prior seed; they keep the project-local
  transfer-table feature exercised (and on elastic, the EFS
  persistent-storage machinery for `events`).

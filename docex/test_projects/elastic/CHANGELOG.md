# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

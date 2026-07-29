# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

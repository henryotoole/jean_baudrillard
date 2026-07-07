# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  campaign) and then immediately repinned to docex 1.0.1 (mod 046, the
  naming-policy leak patch). The inner git history starts fresh at this
  version; the compiled output reflects the 1.0.1 fix (data-plane names
  hyphenate the project segment everywhere doctrine prescribes). See
  `../PRE_CUT_CHECKLIST.md` for the walk.
- `infra.yml` declares `apex_domain: luxrnd.tech` (mod 031's bare-apex
  rule); project subdomain derives to `docex-smoke-fixed.luxrnd.tech`.
- Project-local transfer tables `infra/transfer_tables/{sidecar,clickhouse}.yml`
  preserved from the prior seed; they keep the project-local
  transfer-table feature exercised on every cut.

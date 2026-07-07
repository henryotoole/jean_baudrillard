# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  campaign) and then immediately repinned to docex 1.0.1 (mod 046,
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

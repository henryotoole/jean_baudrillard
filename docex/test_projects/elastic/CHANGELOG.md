# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

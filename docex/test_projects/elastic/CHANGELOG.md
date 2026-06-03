# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.6] - 2026-06-03

### Added

- Declare `observability_backend_url: "https://hyperdx.luxrnd.tech"` in
  `infra/infra.yml`. Required as of docex 0.11.0 (added by mod 017).
  Sidecars in stage/prod export telemetry to this backend; the API key
  goes in `infra/secrets/{stage,prod}.env` as `TELEMETRY_API_KEY=`.

## [0.0.4] - 2026-06-02

### Added

- `health_check_path: /health` on the `web` core service in
  `infra.yml`. Exercises mod 010's `target: target_group` routing
  end-to-end: the elastic compile now lands a
  `health_check { path = "/health" ... }` block on the ALB target
  group, and ECS tasks pass the load-balancer health check (without
  this the ALB fell back to `/`, which the backend doesn't serve,
  and the rolling deploy cycled tasks indefinitely on 404s).

### Fixed

- `teardown.sh` now polls until `DeletionProtection=false` lands in
  AWS API before running `tofu destroy`. The previous version called
  `modify-db-instance --apply-immediately` (async — flag flip takes
  5-30s) then immediately ran `tofu destroy`, racing with the API
  state. When tofu lost the race it skipped RDS deletion silently
  (the `|| echo warning` swallowed the exit), the project-tier
  destroy then tripped on still-attached RDS ENIs, and the state
  bucket was deleted anyway leaving orphaned RDS + VPC behind.

## [0.0.3] - 2026-06-02

### Changed

- Repinned to docex 0.9.0. Recompiled infra/output/* against the new
  candidate version (mod 010's emits/target routing affects the
  compiler internals but produces no project-side `infra.yml` change
  here; mods 009 + 011 were already adopted at 0.0.2).

## [0.0.2] - 2026-06-01

### Fixed

- `core/web/migrate.sh` no longer hard-codes `sslmode=disable` in the
  DATABASE_URL. RDS rejects non-TLS postgres connections by default;
  the fixed-foundation postgres-in-docker doesn't run TLS, so the
  libpq default of `prefer` (try TLS first, fall back to plaintext)
  is the cross-foundation correct choice.

## [0.0.1] - 2026-05-29

### Added

- Project incepted.

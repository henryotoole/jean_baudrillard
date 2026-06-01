# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

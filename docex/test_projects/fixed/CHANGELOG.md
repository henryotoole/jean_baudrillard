# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.2] - 2026-06-02

### Changed

- Repinned to docex 0.9.0; adopted doctrine-injected PROJECT_VERSION
  (mod 011) and DATABASE_SSLMODE part on postgres (mod 009).
- Renamed backing service `db` → `appdb` to avoid postgres engine's
  reserved-DBName list (mod 006), matching the elastic smoke
  project's convention.
- `teardown.sh` walks both underscore and hyphen forms of the project
  name to clean up resources whose names came through the naming
  policy translation (mod 005).

### Added

- Project incepted.

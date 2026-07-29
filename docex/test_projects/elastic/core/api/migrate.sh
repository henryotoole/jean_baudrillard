#!/bin/sh
# migrate.sh — apply database migrations via dbmate.
# Doctrine: databases.md mandates dbmate for SQL migrations.
#
# Runs once per CODEBASE (`schema_owned_by: api`), never per process type.
# It may therefore only read SERVICE-level `env:` — the six DATABASE_*
# parts below are declared at the `api` service level for exactly this
# reason. A process-scoped var (SIDECAR_HOST, WORKER_HOST) would simply be
# absent here, silently.
set -eu

cd "$(dirname "$0")"

: "${DATABASE_HOST:?DATABASE_HOST must be set}"
: "${DATABASE_PORT:?DATABASE_PORT must be set}"
: "${DATABASE_NAME:?DATABASE_NAME must be set}"
: "${DATABASE_USER:?DATABASE_USER must be set}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set}"
: "${DATABASE_SSLMODE:?DATABASE_SSLMODE must be set}"

# Compose the DSN from the parts-only env vars (cicl.md § Provided Fields).
# sslmode is a doctrine-provided part — `disable` on fixed, `require` on
# elastic — so this script is foundation-agnostic.
export DATABASE_URL="postgres://${DATABASE_USER}:${DATABASE_PASSWORD}@${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}?sslmode=${DATABASE_SSLMODE}"

exec dbmate --no-dump-schema --migrations-dir /service/migrations up

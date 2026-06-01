#!/bin/sh
# migrate.sh — apply database migrations via dbmate.
# Doctrine: databases.md mandates dbmate for SQL migrations.
set -eu

cd "$(dirname "$0")"

: "${DATABASE_HOST:?DATABASE_HOST must be set}"
: "${DATABASE_PORT:?DATABASE_PORT must be set}"
: "${DATABASE_NAME:?DATABASE_NAME must be set}"
: "${DATABASE_USER:?DATABASE_USER must be set}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set}"

# Compose the DSN from the parts-only env vars (cicl.md § Provided Fields).
# sslmode unset → libpq default `prefer`: TLS where supported (RDS),
# plaintext fallback where it isn't (postgres-in-docker dev/test).
# Works on both foundations.
export DATABASE_URL="postgres://${DATABASE_USER}:${DATABASE_PASSWORD}@${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}"

exec dbmate --no-dump-schema --migrations-dir /service/migrations up

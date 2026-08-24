# sample_project — Phase 2 fixture

This fixture exercises Phase 2's `up`, `down`, `build`, `test`, and
`migrate` commands against a minimal real core service (`api`) backed
by a postgres database.

## Layout

```
project.yml              # name=sample, version=0.1.0
infra/
  infra.yml              # one core service, one backing service
  secrets/
    dev.env              # placeholder POSTGRES_* values (see warning below)
    test.env             # ditto for test env
core/
  api/
    Dockerfile           # build / dev / prod / test stages
    build.sh             # canonical build entry point
    test_unit.sh         # no-infra test tier (globs tests/unit)
    test_integration.sh  # stack-backed test tier (globs tests/integration)
    migrate.sh           # idempotent migration shim (python+psycopg2)
    src/app.py           # trivial http.server returning /health
    tests/unit/          # one passing unit-tier smoke test
    tests/integration/   # one passing integration-tier smoke test
    migrations/*.sql     # CREATE TABLE IF NOT EXISTS health (...)
```

## Important: env files

**Real projects must gitignore `infra/secrets/<env>.env`.** They contain
runtime secrets. The values committed here are deliberate fixtures —
they exist so docker compose has substitutions to plug in when this
project is used to test docex itself.

Secret keys are derived on demand from committed sources (`infra.yml`
`secrets:` blocks + backing `kind: secret` vars + doctrine-injected keys)
and reconciled into the gitignored per-env files via `docex secrets
scaffold <env>`.

## Bumping docex version

The fixture pins `docex_version: "0.2.0"`. When docex's image surface
changes, the smoke test (`phase_2.md` Step 14) re-pins this value to
match the rebuilt image tag.

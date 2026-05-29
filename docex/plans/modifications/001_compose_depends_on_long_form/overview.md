# Mod 001 — Compose `depends_on` must wait for `service_healthy`

## Problem

`docex up <env>` (dev/test) and `docex test` both invoke `compose exec ./migrate.sh` immediately after `compose up --detach` returns. The fixed test project (`test_projects/fixed`) and elastic test project (`test_projects/elastic`) both fail the same way on a clean run:

```
 Container docex-smoke-fixed-dev-db Started
 Container docex-smoke-fixed-dev-web Started
Error: dial tcp 172.20.0.2:5432: connect: connection refused
error: migrate.sh for service 'web' exited 2; stack is up but migrations failed.
```

The db container has a `pg_isready` healthcheck (from the postgres engine's transfer-table entry) and becomes healthy ~10 s after `Started`. The `web` container starts as soon as the db container *starts*, not when it's *healthy*. By the time `web` is up enough for `compose exec`, postgres is still initializing, so the migration's TCP connect is refused.

### Root cause

`src/docex/emit/compose.py:179–182` writes `depends_on` in compose's short-form (a flat list of service names):

```yaml
depends_on:
- docex-smoke-fixed-dev-db
```

Compose's short-form only waits for the dependency to *start*. The long-form `depends_on` with `condition: service_healthy` is what makes compose wait for the healthcheck to pass before starting the dependent.

## Design

Change the compose emitter so that, for each entry in a service's `depends_on`, it emits **long-form** with an appropriate condition:

```yaml
depends_on:
  docex-smoke-fixed-dev-db:
    condition: service_healthy
```

Condition selection rule:

| Target service has a `healthcheck:` block | Emitted condition |
| ----------------------------------------- | ----------------- |
| Yes                                       | `service_healthy` |
| No                                        | `service_started` |

`service_started` matches the current short-form semantics — i.e. it's a safe default when the target has no way to declare readiness. The compiler can detect "has a healthcheck" by inspecting the target service's compose block after the transfer-table merge.

### Why fix it at the emitter

Two other places one might think of fixing this:

1. **`orchestrate/up.py`** — poll for db readiness before running `migrate.sh`. Rejected: it only fixes the migration symptom. Any other dependent service (e.g. `worker → db`) would still race postgres on startup. The doctrine's promise is that the *compose file itself* reflects intent.
2. **Per-engine in transfer tables** — declare each engine's "wait condition." Rejected: condition selection is purely a function of whether the engine declares a healthcheck, which is already in the transfer table. No new per-engine knowledge needed.

The emitter is the single point of translation from CICL's flat `depends_on` to compose's long-form, and is the right home.

### Scope

- **Fixed only.** Elastic uses ECS / RDS with their own readiness mechanisms; `depends_on` is HCL-pop'd at `src/docex/emit/hcl.py:206`. No change there.
- **All envs that compile to compose.** `dev`, `test`, and (on fixed-foundation projects) `stage`/`prod`. The `release` path on fixed runs Ansible against the compiled compose, so this fix flows into stage/prod releases as a free side effect.
- **All `depends_on` edges, not just backing services.** A core service depending on another core service with a healthcheck (e.g. `web` depends on `worker` where `worker` declares a health_check_path) should also wait for `service_healthy`.

## Five-artifact alignment

Per [`docex_process.md § Additional Artifacts`](../../core/docex_process.md#additional-artifacts):

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | One-sentence addition — likely in [`transfer_tables.md § Foundation Invariants`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#foundation-invariants) — stating that `depends_on` is emitted long-form and waits for `service_healthy` when the target declares a healthcheck. The rule belongs there since it's a uniform per-compose-file invariant, not engine-specific. |
| `docex/plans/core/*.md` | No change. The compose emitter isn't surfaced in `masterplan.md` at this resolution. |
| `tables/roles/*.yml` | No change. Postgres already declares its healthcheck; other engines either do or don't — the emitter just reads what's there. |
| `src/docex/**` | `src/docex/emit/compose.py` — rewrite the `depends_on` translation block to produce a long-form map keyed by global name, with `condition` chosen per the rule above. |
| `tests/**` | Unit test in `tests/unit/test_compose_emitter.py` covering both branches (healthcheck present → `service_healthy`; absent → `service_started`). **Also fix the stale fixture assertions** in `tests/integration/test_up_down_real.py` and `tests/integration/test_migrate_real.py` which still look for backing-service name `"database"` but the fixture renamed it to `"db"`. Small enough to bundle here; both fixes need the same `pytest -m integration` pass for validation. |

## Validation

- Unit test passes for both branches of the condition rule.
- Run `./bin/docex up dev` in `test_projects/fixed` — `migrate.sh` succeeds on a clean stack-up.
- Run `./bin/docex test` in `test_projects/fixed` — exits 0.
- Same in `test_projects/elastic` for the local-only dev/test envs.

## Decisions

1. **Bundling.** Test-fixture rename (`database` → `db`) is bundled into this mod — small enough that splitting would create churn for no review benefit.
2. **Doctrine home.** The new invariant lives in `transfer_tables.md § Foundation Invariants` — it's a specific compile-time emission rule, not general CICL prose.
3. **`service_completed_successfully`.** Acknowledged out-of-scope; will revisit if/when one-off migration containers replace `compose exec`.

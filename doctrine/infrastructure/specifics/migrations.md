---
stratum: conditional
---

# Migrations

This file describes how database schema migrations — changes applied to a codebase's owned database — are invoked by `docex` at well-defined points in the lifecycle. The mechanism is foundation-aware in implementation but identical in contract: every codebase that owns a database schema provides a `migrate.sh` shim that `docex` runs against the right database at the right time.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context. The shorter doctrine-prose summary is in [cicd.md § Migrate Step](../cicd.md#migrate-step).

## Source of Truth

Each backing service whose role uses `schema_owned_by` in `infra.yml` names a codebase in that field — the **schema owner**. The named codebase provides:

```
core/<codebase>/
  migrate.sh          # the shim, invoked by docex — once per codebase
  migrations/         # the actual migration files (project tool's format)
```

The migration tool is the project's choice — `dbmate`, `alembic`, `flyway`, `goose`, etc. `migrate.sh` is a small shim that invokes the chosen tool against the database identified by the same environment variables the service itself uses at runtime — i.e. the connection parts the service binds from the backing service's `provides:` block (in the doctrine's examples, `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_SSLMODE`). Because those env-var names are identical across foundations (see [transfer_tables.md § provides](./transfer_tables.md)), the same `migrate.sh` works unchanged on fixed and elastic — including `DATABASE_SSLMODE`, which is load-bearing on elastic where RDS rejects non-SSL connections under its default `pg_hba.conf`. `migrate.sh` must build its connection string from the parts rather than hardcoding `sslmode=disable` or `sslmode=require`. The shim's contract is exit-code only: `0` on success, non-zero on any failure.

Migration is a **per-codebase** operation. `schema_owned_by` names a codebase and `migrate.sh` runs once for that codebase however many [core services](../cicl.md#core-services) it declares. There is no per-core-service migration.

Only one codebase may own a given database. This is enforced via the `schema_owned_by` field in CICL — by this mechanism, a backing service can only have one codebase that controls its schema. This invariant exists specifically to avoid race conditions where two codebases concurrently run migrations against the same schema.

## Invocation Timing

Migrations are run by [`./bin/docex migrate <env>`](../docex.md#migrate), which the operator can invoke directly. The command is also invoked implicitly by three lifecycle operations:

- **`./bin/docex envinfra up dev`**: after the compose stack is up, before the developer interacts with the env.
- **`./bin/docex test`**: after the `test` env's compose stack is up, before any codebase's `test.sh` runs. Tests always see a fully-migrated schema.
- **`./bin/docex release <env>`** (`stage`, `prod`): after the database is reachable but before the new application code is fully rolled out. Per-env-category mechanism below.

In every case, migration runs as a separate process invocation against the codebase's image — never on the host, never woven into the application's startup sequence. The exact invocation mechanism varies by env category — `dev`/`test` use the same mechanism on both foundations (since dev/test are always fixed-style per [shape.md § Shape and Environment](../shape.md#shape-and-environment)); `stage`/`prod` mechanism varies by foundation.

## Dev and Test Mechanism

For `dev` and `test` envs, on both foundations, `./bin/docex migrate <env>` runs `migrate.sh` as a one-off container of each schema-owning **codebase's** [exec service](./exec_service.md):

```bash
docker compose -f infra/output/<env>/docker-compose.yml \
    run --rm <project>-<env>-<codebase>-exec ./migrate.sh
```

(`./migrate.sh` is relative because the image's working directory is the fixed `/service` root — see [Codebase Containers](../infrastructure.md#codebase-containers). `--build` is added in `test` only, [for the reason given there](./exec_service.md#invocation).)

Two of that block's properties are why migration runs there. It needs nothing running — it is profile-gated and waits on its backing services' healthchecks, so the one-off gates on the database rather than assuming the stack is up. And it carries codebase-level `env:` only, so a migration cannot read a core service's overlay.

If `migrate.sh` exits non-zero, the env stays up and `./bin/docex migrate <env>` returns the non-zero code. The schema may be in a partial state; the operator fixes the migration and re-invokes the command. Since the env is unchanged otherwise, retry is just another one-off run — no env teardown or rebuild required.

## Stage and Prod on Fixed Foundation

For `stage`/`prod` on fixed projects, migration is a step in the Ansible playbook, placed between "render configs" and "start the new stack":

```yaml
# Pseudo-playbook step
- name: Run migrations for {{ svc.codebase }}
  ansible.builtin.command:
    cmd: >-
      docker compose -p {{ compose_project_name }}
      run --rm {{ svc.exec_service }} /service/migrate.sh
  loop: "{{ codebases_with_schema }}"
```

For each schema-owning codebase, `compose run` starts a one-off container of that codebase's [exec service](./exec_service.md) using the new image — the *same* block `dev` and `test` use, which is why that block is emitted in all four fixed-compiled envs and not just the two. The container inherits its networks and readiness gates, reads its env vars from the rendered `.env`, and exits with a status code. The old service containers are still running and serving traffic against the (about-to-be-migrated) database — see [Backward Compatibility](#backward-compatibility-requirement) below.

Note the path is absolute here (`/service/migrate.sh`) while `dev`/`test` use the relative `./migrate.sh`. Both resolve to the same script; the absolute form is used where the command is rendered into a playbook rather than issued against a known working directory.

If any migration fails, the playbook aborts before `docker compose up -d` runs the new stack. Old containers continue serving, the release fails loudly with a clear error, and the operator can fix and re-run.

> **⚠ Known divergence — the emitted playbook does not currently do this.** The task that pulls images uses a compose module argument that also *starts* the stack, so the real fixed ordering is **up → migrate**, and the abort guarantee above does not hold: a failed migration leaves the new code up against an unmigrated schema. Found by advance 006's fixed smoke walk; longstanding rather than new. This paragraph states the **intended** contract and is left standing as the target, because the fix belongs with a walk that can verify it — see [`fixed_release_migrates_after_up.md`](../../../docex/plans/advances/008_housekeeping/references/fixed_release_migrates_after_up.md). Until then, treat a fixed `stage`/`prod` release as **not** protected against a failing migration.

## Stage and Prod on Elastic Foundation

For `stage`/`prod` on elastic projects, the compiler emits one "migration" ECS task definition per schema-owning **codebase** — family `${project}-${env}-${codebase}-migrate`, not one per core service, since `migrate.sh` runs once per codebase. Its sizing is the per-dimension **maximum** across the codebase's core services, which is order-independent (so the migration cannot be resized by renaming or adding an unrelated core service) and never under-provisions. Its environment is the codebase-scoped surface only, matching the fixed path. The migration and the application task definitions reference the same image — the difference is the command:

- Main task definition: runs the application's normal entrypoint.
- Migration task definition: runs `/service/migrate.sh` and exits.

`./bin/docex release <env>` sequences:

1. **Aggregate to SSM** (the aggregation step from [`config_and_secrets.md`](./config_and_secrets.md) — TTE, secrets, and config pushed to the `/<project>/<env>/` prefix; TTE put-if-absent).
2. **Update the migration task definition image tag** to the new version via the AWS API (`RegisterTaskDefinition`). This does not affect any running services.
3. **`RunTask`** the migration task definition for each codebase with a schema. Each task starts, pulls the new image, runs `migrate.sh` against the existing RDS, and exits. The task runs in the master VPC's primary-AZ private subnet with the project's `${project}-${env}-internal` security group so it can reach RDS.
4. **Poll for completion** via `DescribeTasks`. If any task's container exits non-zero, abort the release immediately — the application's main task definition is unchanged, so the existing service continues serving against (now-migrated) RDS.
5. **`tofu apply`** to update the application's main task definition, triggering the ECS rolling deploy of the new application code.

This ordering ensures migrations are fully complete and verified before any new application tasks attempt to use the new schema. The application rollout that follows is a standard rolling deploy with no migration-related race conditions.

### First-Time Release of an Env

The first time an elastic env is released, the env's ECS services, RDS, and migration task definition referenced in steps 2-4 above don't exist yet — they're created by step 5's `tofu apply`. (The ECS cluster itself is project-tier and always present — see [shape.md § ecs_cluster](../shape.md#elastic-foundation).) `./bin/docex release` detects a first release via an ECS-service-existence probe (the env's ECS service is not yet in its cluster) and swaps the order to `1 → 5 → 2-4`: push secrets, run `tofu apply` (creating the RDS, task definitions, and the ECS service with the new image), then `RunTask` the migration against the now-live RDS.

The transient consequence: on a first release, the application's ECS service comes up before the migration runs. Until the migration completes, the application tasks may crash-loop or 500 against the not-yet-created schema. This is acceptable because there are no users on a first deploy and the window is bounded by migration runtime. Subsequent releases find the env's ECS service present and follow the steady-state order, preserving the zero-downtime properties documented below. A [`clock`](./clock.md) core service is the one guaranteed to exercise this window, because it fires on its own schedule rather than in response to a request: a job due inside it will fire, fail against the missing schema, and log a stack trace before the migration lands. That is expected and self-healing — see [`clock.md § Caveats`](./clock.md#caveats).

## Backward-Compatibility Requirement

Both foundations execute migrations against a live database that old application code is also using. During the rolling-deploy window:

- **Fixed:** the migration runs before `docker compose up -d`, but the old containers are technically still running until compose replaces them. There's a brief window where old code interacts with the new schema.
- **Elastic:** the old ECS tasks continue serving traffic during the migration and during the subsequent rolling deploy. The window is longer than fixed.

**To achieve zero-downtime releases, migrations must be backward-compatible with the previous application version.** A migration that drops a column the old code still reads will break old tasks during the rolling window. Patterns that satisfy this:

- Add columns rather than rename them; deprecate old columns over multiple releases.
- Make new columns nullable initially; backfill data; tighten constraints in a later release.
- Split breaking schema changes into multi-release sequences (deploy 1 adds; deploy 2 removes).

Projects that can tolerate downtime can ignore this — they'll experience errors during the rolling window but recover once the deploy completes. The doctrine documents the requirement; it does not enforce it.

The same requirement underlies the [rollback](../cicd.md#rollback) mechanism's "schema not reversed" stance: a backward-compatible migration is rollback-friendly almost by definition, because the schema-after-migration is also valid for the schema-before-migration's code.

## Caveats

- **Schema ownership is enforced at compile time.** Each database backing service's `schema_owned_by` field names exactly one codebase and the field is a single scalar, not a list, so a database with two competing schema owners is structurally unrepresentable. No escape hatch for "two codebases migrate the same schema" — that's an architectural smell the doctrine refuses to accept.
- **Migration tool is project-local.** The doctrine does not prescribe `dbmate` or any other tool; only the shim's exit-code contract.
- **No automatic rollback.** A failed migration leaves the database in whatever partial state the tool produced. The doctrine assumes migrations are idempotent and forward-only; fixing a partially-applied migration is the operator's responsibility.
- **Migration runs use the new image.** This means the new code's migration files run against the existing schema — which is correct, but means a project's `migrate.sh` and migration files must work *standalone* (not depend on the application being running, not require any one-off bootstrap state).

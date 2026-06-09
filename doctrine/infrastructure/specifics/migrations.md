# Migrations

This file describes how database schema migrations — changes applied to a service's owned database — are invoked by `docex` at well-defined points in the lifecycle. The mechanism is foundation-aware in implementation but identical in contract: every core service that owns a database schema provides a `migrate.sh` shim that `docex` runs against the right database at the right time.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context. The shorter doctrine-prose summary is in [cicd.md § Migrate Step](../cicd.md#migrate-step).

## Source of Truth

Each backing service whose role uses `schema_owned_by` in `infra.yml` names a core service in that field — the **schema owner**. The named core service provides:

```
core/<service>/
  migrate.sh          # the shim, invoked by docex
  migrations/         # the actual migration files (project tool's format)
```

The migration tool is the project's choice — `dbmate`, `alembic`, `flyway`, `goose`, etc. `migrate.sh` is a small shim that invokes the chosen tool against the database identified by the same environment variables the service itself uses at runtime — i.e. the connection parts the service binds from the backing service's `provides:` block (in the doctrine's examples, `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_SSLMODE`). Because those env-var names are identical across foundations (see [transfer_tables.md § provides](./transfer_tables.md)), the same `migrate.sh` works unchanged on fixed and elastic — including `DATABASE_SSLMODE`, which is load-bearing on elastic where RDS rejects non-SSL connections under its default `pg_hba.conf`. `migrate.sh` must build its connection string from the parts rather than hardcoding `sslmode=disable` or `sslmode=require`. The shim's contract is exit-code only: `0` on success, non-zero on any failure.

Only one core service may own a given database. This is enforced via the `schema_owned_by` field in CICL — by this mechanism, a backing service can only have one core service that controls its schema. This invariant exists specifically to avoid race conditions where two services concurrently run migrations against the same schema.

## Invocation Timing

Migrations are run by [`./bin/docex migrate <env>`](../docex.md#migrate), which the operator can invoke directly. The command is also invoked implicitly by three lifecycle operations:

- **`./bin/docex envinfra up dev`**: after the compose stack is up, before the developer interacts with the env.
- **`./bin/docex test`**: after the `test` env's compose stack is up, before any service's `test.sh` runs. Tests always see a fully-migrated schema.
- **`./bin/docex release <env>`** (`stage`, `prod`): after the database is reachable but before the new application code is fully rolled out. Per-env-category mechanism below.

In every case, migration runs as a separate process invocation against the service's image — never on the host, never woven into the application's startup sequence. The exact invocation mechanism varies by env category — `dev`/`test` use the same mechanism on both foundations (since dev/test are always fixed-style per [shape2.md § Shape and Environment](../shape2.md#shape-and-environment)); `stage`/`prod` mechanism varies by foundation.

## Dev and Test Mechanism

For `dev` and `test` envs, on both foundations, `./bin/docex migrate <env>` runs `migrate.sh` inside each schema-owning core service's already-running container via `docker compose exec`:

```bash
docker compose -f infra/output/<env>/docker-compose.yml \
    exec <service> /service/migrate.sh
```

The service's container is already up (it was brought up by `./bin/docex envinfra up <env>` or `./bin/docex test`), already on the env's internal network, and already carries the runtime env vars the shim needs to reach the database. `docker compose exec` reuses all of that — no separate container, no separate network attachment, no env-var rendering.

The exec runs in the service's `dev`-stage (or `test`-stage) container, which carries the build tools and any migration-tool dependencies the project's `Dockerfile` declares for development. The application process itself keeps running while the exec is in flight; `migrate.sh` is invoked as an independent process inside the same container.

If `migrate.sh` exits non-zero, the env stays up and `./bin/docex migrate <env>` returns the non-zero code. The schema may be in a partial state; the operator fixes the migration and re-invokes the command. Since the env is unchanged otherwise, retry is just another exec — no env teardown or rebuild required.

## Stage and Prod on Fixed Foundation

For `stage`/`prod` on fixed projects, migration is a step in the Ansible playbook, placed between "render configs" and "start the new stack":

```yaml
# Pseudo-playbook step
- name: Run migrations
  community.docker.docker_container:
    name: "{{ project }}-{{ env }}-{{ service }}-migrate"
    image: "{{ registry }}/{{ project }}/{{ service }}:{{ version }}"
    command: /service/migrate.sh
    networks:
      - name: "{{ project }}-{{ env }}-internal"
    env_file: /opt/{{ project }}/{{ env }}/.env
    detach: false
    auto_remove: true
  loop: "{{ services_with_schema }}"
```

For each schema-owning core service, a one-off container runs `migrate.sh` using the new image. The container joins the project's existing internal network to reach the database, reads its env vars from the rendered `.env`, and exits with a status code. The old service containers are still running and serving traffic against the (about-to-be-migrated) database — see [Backward Compatibility](#backward-compatibility-requirement) below.

If any migration fails, the playbook aborts before `docker compose up -d` runs the new stack. Old containers continue serving, the release fails loudly with a clear error, and the operator can fix and re-run.

## Stage and Prod on Elastic Foundation

For `stage`/`prod` on elastic projects, the compiler emits a separate "migration" ECS task definition for each schema-owning core service. Both the migration task definition and the main service task definition reference the same image — the difference is the command:

- Main task definition: runs the application's normal entrypoint.
- Migration task definition: runs `/service/migrate.sh` and exits.

`./bin/docex release <env>` sequences:

1. **Push secrets to SSM** (the secrets step from [`secrets.md`](./secrets.md)).
2. **Update the migration task definition image tag** to the new version via the AWS API (`RegisterTaskDefinition`). This does not affect any running services.
3. **`RunTask`** the migration task definition for each service with a schema. Each task starts, pulls the new image, runs `migrate.sh` against the existing RDS, and exits. The task runs in the master VPC's primary-AZ private subnet with the project's `${project}-${env}-internal` security group so it can reach RDS.
4. **Poll for completion** via `DescribeTasks`. If any task's container exits non-zero, abort the release immediately — the application's main task definition is unchanged, so the existing service continues serving against (now-migrated) RDS.
5. **`tofu apply`** to update the application's main task definition, triggering the ECS rolling deploy of the new application code.

This ordering ensures migrations are fully complete and verified before any new application tasks attempt to use the new schema. The application rollout that follows is a standard rolling deploy with no migration-related race conditions.

### First-Time Release of an Env

The first time an elastic env is released, the cluster, RDS, and migration task definition referenced in steps 2-4 above don't exist yet — they're created by step 5's `tofu apply`. `./bin/docex release` detects this case via an `ecs_cluster_exists` probe and swaps the order to `1 → 5 → 2-4`: push secrets, run `tofu apply` (creating the cluster, RDS, task definitions, and the ECS service with the new image), then `RunTask` the migration against the now-live RDS.

The transient consequence: on a first release, the application's ECS service comes up before the migration runs. Until the migration completes, the application tasks may crash-loop or 500 against the not-yet-created schema. This is acceptable because there are no users on a first deploy and the window is bounded by migration runtime. Subsequent releases find the cluster present and follow the steady-state order, preserving the zero-downtime properties documented below.

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

- **Schema ownership is enforced at compile time.** Each database backing service's `schema_owned_by` field names exactly one core service — the field is a single scalar, not a list, so a database with two competing schema owners is structurally unrepresentable. No escape hatch for "two services migrate the same schema" — that's an architectural smell the doctrine refuses to accept.
- **Migration tool is project-local.** The doctrine does not prescribe `dbmate` or any other tool; only the shim's exit-code contract.
- **No automatic rollback.** A failed migration leaves the database in whatever partial state the tool produced. The doctrine assumes migrations are idempotent and forward-only; fixing a partially-applied migration is the operator's responsibility.
- **Migration runs use the new image.** This means the new code's migration files run against the existing schema — which is correct, but means a project's `migrate.sh` and migration files must work *standalone* (not depend on the application being running, not require any one-off bootstrap state).

# Release Mechanism

This file describes how `docex release <env>` pushes a built release out to its target environment. As with other specifics, this is documentation for the compiler implementer and the curious developer; it is not meant to be loaded as general doctrine context.

## General Flow

A release combines three orthogonal inputs into a running stack:
- A `build_image` pulled from the project's `container_registry`
- The `environment_config` emitted by `docex compile` for the target environment
- The environment's `secrets` (typically `.env`-style files)

The operation is **push-initiated** and **idempotent**. A control node (the developer's machine, a CI runner, or `docex` running in its own container on either) initiates the deploy; the target converges to the declared desired state; re-running the same release against an already-converged target is a no-op. This holds for both foundations.

The control node needs **credentials** for the target. The exact form differs by foundation, but the rule is the same: credentials come from the operator's environment (CI secret store, local keychain, OS env vars) and `docex` consumes them from well-known locations. `docex` does not manage credential storage itself.

## Secrets

Secrets — environment-specific runtime values like database passwords, API keys, and other config that shouldn't be committed — use a unified `.env`-as-source-of-truth model across both foundations.

### Source of truth

The project keeps per-environment `.env` files under `infra/secrets/`:

```
infra/secrets/
  .gitignore        # auto-created by project bootstrap; ignores *.env
  README.md         # auto-created by project bootstrap; explains usage
  example.env       # auto-emitted by `docex compile`; committed
  dev.env           # operator-maintained, gitignored
  test.env          # operator-maintained, gitignored
  stage.env         # operator-maintained, gitignored
  prod.env          # operator-maintained, gitignored
```

`example.env` is emitted by the compiler from the `env:` blocks of the project's backing services in the [transfer tables](./transfer_tables.md) — every env var any backing service requires shows up there with an empty placeholder value, grouped by the service that introduced it. The developer copies it to `<env>.env` and fills in real values per environment.

### Materialization at release

The `.env` is the canonical source; the deployment target is overwritten *from* it on every release.

- **Fixed (Ansible):** the playbook reads `infra/secrets/<env>.env` from the control node and renders it onto the host as `/opt/<project>/<env>/.env`. Docker Compose reads this file when starting containers.
- **Elastic (OpenTofu):** before `tofu apply` runs, `docex release` reads `infra/secrets/<env>.env` and pushes each `KEY=value` pair to SSM Parameter Store at `/<project>/<env>/KEY` as a `SecureString` (encrypted with the default `aws/ssm` KMS key). The emitted HCL then provisions ECS task definitions whose `secrets` blocks reference those SSM paths; ECS resolves the values when starting tasks.

In both cases, the `.env` wins on every release. Manual edits to the host `.env` (fixed) or SSM parameters (elastic) are overwritten on the next deploy. This is by design: it preserves the deterministic doctrine, but means the operator must use the `.env` for everything, including hot-fixes.

### Caveats

- **No externally-rotated secrets.** Phase 1 assumes all secrets are project-controlled. AWS-managed RDS rotation, third-party-issued tokens, or anything else that updates outside the `.env` would be clobbered on each release. Projects that need this will require a future doctrine extension (likely a way to mark certain secret names as externally-managed).
- **Trust model.** Real production secret values sit on every operator's laptop. The doctrine assumes the operator's machine is trusted; compliance-driven environments that mandate "secrets only live in the vault" should not adopt this pattern as-is.

## Migrations

Database migrations — schema changes applied to a service's owned database — use a per-service `migrate.sh` shim invoked by `docex` at well-defined points in the release flow. The mechanism is foundation-aware in implementation but identical in contract.

### Source of truth

Each core service that declares `schema_owned_by` for a database in `infra.yml` provides:

```
core/<service>/
  migrate.sh          # the shim, invoked by docex
  migrations/         # the actual migration files (project tool's format)
```

The migration tool is the project's choice — `dbmate`, `alembic`, `flyway`, `goose`, etc. `migrate.sh` is a small shim that invokes the chosen tool against the database identified by the same environment variables the service itself uses at runtime (`POSTGRES_HOST`, `POSTGRES_USER`, etc.). The shim's contract is exit-code only: `0` on success, non-zero on any failure.

Only one core service may own a given database. This is enforced via the `schema_owned_by` field in CICL — by this mechanism, a backing service can only have one core service that controls its schema. This invariant exists specifically to avoid race conditions where two services concurrently run migrations against the same schema.

### Invocation timing

Migrations run at three points, all orchestrated implicitly by `docex`:

- **`docex up <env>`** (`dev`): after the compose stack is up, before the developer interacts with the env.
- **`docex test`**: after the `test` env's compose stack is up, before any service's `test.sh` runs. Tests always see a fully-migrated schema.
- **`docex release <env>`** (`stage`, `prod`): after the database is reachable but before the new application code is fully rolled out. Foundation-specific mechanism below.

In every case, migration runs inside a container based on the service's image — never on the host, never inside the application's runtime container.

### Fixed-foundation mechanism

For fixed projects, migration is a step in the Ansible playbook, placed between "render configs" and "start the new stack":

```yaml
# Pseudo-playbook step
- name: Run migrations
  community.docker.docker_container:
    name: "{{ project }}_{{ env }}_{{ service }}_migrate"
    image: "{{ registry }}/{{ project }}/{{ service }}:{{ version }}"
    command: /service/migrate.sh
    networks:
      - name: "{{ project }}_{{ env }}_internal"
    env_file: /opt/{{ project }}/{{ env }}/.env
    detach: false
    auto_remove: true
  loop: "{{ services_with_schema }}"
```

For each core service with a `schema_owned_by` declaration, a one-off container runs `migrate.sh` using the new image. The container joins the project's existing internal network to reach the database, reads its env vars from the rendered `.env`, and exits with a status code. The old service containers are still running and serving traffic against the (about-to-be-migrated) database — see [Backward compatibility](#backward-compatibility-requirement) below.

If any migration fails, the playbook aborts before `docker compose up -d` runs the new stack. Old containers continue serving, the release fails loudly with a clear error, and the operator can fix and re-run.

### Elastic-foundation mechanism

For elastic projects, the compiler emits a separate "migration" ECS task definition for each core service that has `schema_owned_by`. Both the migration task definition and the main service task definition reference the same image — the difference is the command:

- Main task definition: runs the application's normal entrypoint.
- Migration task definition: runs `/service/migrate.sh` and exits.

`docex release <env>` sequences:

1. **Push secrets to SSM** (existing step).
2. **Update the migration task definition image tag** to the new version via the AWS API (`RegisterTaskDefinition`). This does not affect any running services.
3. **`RunTask`** the migration task definition for each service with a schema. Each task starts, pulls the new image, runs `migrate.sh` against the existing RDS, and exits. The task runs in the env's private subnets with the `internal` security group so it can reach RDS.
4. **Poll for completion** via `DescribeTasks`. If any task's container exits non-zero, abort the release immediately — the application's main task definition is unchanged, so the existing service continues serving against (now-migrated) RDS.
5. **`tofu apply`** to update the application's main task definition, triggering the ECS rolling deploy of the new application code.

This ordering ensures migrations are fully complete and verified before any new application tasks attempt to use the new schema. The application rollout that follows is a standard rolling deploy with no migration-related race conditions.

### Backward-compatibility requirement

Both foundations execute migrations against a live database that old application code is also using. During the rolling-deploy window:

- **Fixed:** the migration runs before `docker compose up -d`, but the old containers are technically still running until compose replaces them. There's a brief window where old code interacts with the new schema.
- **Elastic:** the old ECS tasks continue serving traffic during the migration and during the subsequent rolling deploy. The window is longer than fixed.

**To achieve zero-downtime releases, migrations must be backward-compatible with the previous application version.** A migration that drops a column the old code still reads will break old tasks during the rolling window. Patterns that satisfy this:

- Add columns rather than rename them; deprecate old columns over multiple releases.
- Make new columns nullable initially; backfill data; tighten constraints in a later release.
- Split breaking schema changes into multi-release sequences (deploy 1 adds; deploy 2 removes).

Projects that can tolerate downtime can ignore this — they'll experience errors during the rolling window but recover once the deploy completes. The doctrine documents the requirement; it does not enforce it.

### Caveats

- **Schema ownership is enforced at compile time.** Two services declaring `schema_owned_by` for the same database is a compile error. No escape hatch for "two services migrate the same schema" — that's an architectural smell the doctrine refuses to accept.
- **Migration tool is project-local.** The doctrine does not prescribe `dbmate` or any other tool; only the shim's exit-code contract.
- **No automatic rollback.** A failed migration leaves the database in whatever partial state the tool produced. The doctrine assumes migrations are idempotent and forward-only; fixing a partially-applied migration is the operator's responsibility.
- **Migration runs use the new image.** This means the new code's migration files run against the existing schema — which is correct, but means a project's `migrate.sh` and migration files must work *standalone* (not depend on the application being running, not require any one-off bootstrap state).

## Fixed Foundation: Ansible

For fixed-foundation projects, `docex release <env>` invokes `ansible-playbook` (from inside the `docex` container) against an inventory of stage/prod hosts. The playbook itself is emitted by `docex compile` alongside the compose files for that environment.

The playbook's tasks, in order:
1. `docker pull` the project's `build_image` at the tagged version. Uses the registry credentials already present in the target host's `~/.docker/config.json` — see [Registry Credentials](#registry-credentials) below.
2. Render the env's compose file and `.env` from the compiled templates onto the host at `/opt/<project>/<env>/`.
3. Run `docker compose up -d` from that directory; Docker reconciles running containers to declared state.

Each task uses an idempotent Ansible module (`community.docker.docker_image`, `template`, `community.docker.docker_compose_v2`, etc.). Re-running the playbook against an unchanged target produces zero changes.

**SSH Credentials.** An SSH private key authorized on each target host for a dedicated `deploy` user (member of the `docker` group). The keypair is provisioned to the host during fixed-foundation prerequisite setup. The doctrine prescribes one keypair per `(project, env)` — generated once, never shared across projects.

The private key is placed by the operator at `infra/deploy_creds/<env>` (e.g., `infra/deploy_creds/prod`); `docex release <env>` reads from this fixed path. The `deploy_creds/` directory is created by the project bootstrap pre-populated with a `.gitignore` (so its contents can never be committed) and a `README.md` explaining what belongs there.

This `deploy_creds/` folder is the doctrine's single prescribed home for *file-based* deploy-time credentials introduced by the doctrine itself. Cloud credentials with established conventions (AWS via `~/.aws/credentials`, the docker registry via `~/.docker/config.json`) continue to live in their conventional locations — see [credentials.md § Fixed](../credentials.md#fixed).

**Registry Credentials.** The playbook does not `docker login` during release. The target host's `~/.docker/config.json` is populated out of band as part of `host_machine` prerequisite setup, and `docker pull` succeeds against the project's `container_registry` using whatever creds are already there. The operator's side (`docex containerize` / `docker push`) follows the same convention on the development machine — login once, conventional location, no doctrine machinery in between. See [credentials.md § Container Registry](../credentials.md#fixed-container-registry) for the full layout.

If the host's creds are missing or stale, `docker pull` fails loudly and the release aborts before any compose changes. The fix is to re-run `docker login` on the host as the deploy user; the doctrine does not attempt to manage this from the operator's side.

**Inventory.** Generated by the compiler from the project's `domain` field. The stage host resolves to `stage.<domain>`; the prod host resolves to `www.<domain>`. There is no override mechanism: DNS resolution and deployment reachability share the same path, so if a host can't be reached by its domain name, the right fix is to repair DNS, not to introduce a workaround in `infra.yml`. When multi-machine fixed-foundation support is added (currently deferred), this section will grow a list-shaped form to accommodate it.

## Elastic Foundation: OpenTofu

For elastic-foundation projects, `docex release <env>` performs two operations in sequence: it first pushes secrets to SSM Parameter Store (per [Secrets](#secrets) above), then invokes `tofu apply` against the HCL emitted by `docex compile` for the target environment. If the SSM push fails, `tofu apply` does not run — the release fails cleanly with no infrastructure changes attempted.

OpenTofu reads the emitted HCL, diffs against the current AWS state, and applies. For a typical release where only the image tag has changed, this updates each core service's ECS task definition, causing ECS to roll the service: pull the new image from ECR, drain old tasks, start new tasks, run health checks. For initial provisioning or for releases that include infrastructure changes, the same apply additionally creates or modifies VPC, subnet, ALB, RDS, etc. resources.

**Credentials.** An AWS access key or assumed role with permission to manage the project's resources. Sourced by `tofu` from standard AWS environment variables (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, or OIDC tokens supplied by CI). The doctrine prescribes a dedicated IAM role per project, with least-privilege permissions.

**State.** OpenTofu requires a state file to track the mapping between HCL resources and real-world AWS resources. This state is stored in an S3 bucket with DynamoDB locking, both provisioned as project infrastructure once per project. Their creation is a separate one-shot operation (`docex bootstrap`) run when the project first adopts the elastic foundation — see [elastic_bootstrap.md](./elastic_bootstrap.md) for the full description of what it creates and how. Subsequent `docex release <env>` runs assume the state backend exists and use it transparently.

## Why Symmetric Push

Both foundations use push-initiated releases. This is intentional: `docex release <env>` has the same shape regardless of foundation — compile, decide, run from a place with credentials, watch convergence, re-run any time to reconcile.
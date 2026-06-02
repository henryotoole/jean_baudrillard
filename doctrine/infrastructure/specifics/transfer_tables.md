# Transfer Tables

The compiler's job is to turn `infra.yml` — written in foundation-agnostic terms — into concrete provider-ready output. To do this it relies on a body of doctrinal knowledge encoded in **transfer tables**: YAML files that define what each abstract role means, how each engine is configured per foundation, what variables get substituted where, and which invariants apply universally to every emitted resource.

This file specifies the format of these tables. It is documentation for the compiler implementer and for anyone authoring or extending a transfer table; it is not meant to be loaded as general doctrine context.

## Where Transfer Tables Live

- **Doctrine-shipped tables** are bundled inside `docex` and define the canonical translations for every supported role/engine combination. They are the source of truth for any project that does not extend them.
- **Project-local tables** may optionally live at `infra/transfer_tables/` and are deep-merged with the doctrine-shipped tables at compile time. This allows individual projects to define new engines for existing roles, override defaults, or introduce entirely new roles — at the cost of departing from "one canonical method." Most projects should not need this; see [cicl.md § CICL Transfer Tables](../cicl.md#cicl-transfer-tables) for the project-extension semantics.

## Substitution Grammar

Transfer tables make use of three distinct kinds of substitution, each resolved at a different layer of the deployment chain. Distinguishing them is essential for reading and writing the tables correctly.

| Syntax | Resolved by | When | Example |
| ------ | ----------- | ---- | ------- |
| `${var}` | docex compiler | at `./bin/docex compile` | `${global_service_name}` → `myproject-prod-database` |
| `$[var]` | docker-compose or ECS | at container start (runtime) | `$[POSTGRES_USER]` → value of `POSTGRES_USER` env var |
| `@<expr>` | OpenTofu | at `tofu apply` (elastic only) | `@aws_db_instance.database.endpoint` → the live RDS endpoint |

### `${var}` — compile-time substitution

The compiler replaces `${var}` with a value at the moment the table is rendered. The value comes from the context of the service being compiled (its name, env, port, etc.) or from refs to other services in `infra.yml`.

### `$[var]` — runtime substitution (pass-through)

`$[var]` is a literal runtime variable that should appear in the final output file as a variable reference. In a compose file it becomes `${var}` (which docker-compose substitutes at runtime from `.env`); in an ECS task definition it becomes a `secrets[]` entry pointing at the corresponding SSM parameter. The compiler does **not** resolve these — it emits them verbatim, translated to the target language's mechanism.

### `@<expr>` — HCL pass-through (elastic only)

`@<expr>` is a literal HCL expression that the compiler emits as-is into the elastic output, allowing OpenTofu to resolve it at `tofu apply` time. The compiler strips the `@` prefix (and resolves any `${var}` compile-time variables embedded inside the expression), then writes the rest verbatim into the HCL.

This is how transfer tables reference provider-allocated values — RDS endpoints, ElastiCache addresses, S3 bucket ARNs — that AWS only assigns when resources are created.

For example, `@aws_db_instance.${name}.endpoint` for a service named `database` becomes the HCL literal:

```hcl
aws_db_instance.database.endpoint
```

Tofu's dependency graph then ensures the RDS instance is created first, after which the endpoint value is known and substituted everywhere it's referenced. `@<expr>` is meaningless in compose output, so it appears only in elastic-side templates.

### Available compile-time variables

The following variables are always available inside a transfer table entry:

| Variable | Refers to |
| -------- | --------- |
| `${name}` | The simple service name from `infra.yml` (e.g., `database`). |
| `${global_service_name}` | The globally-unique form of the service name (see [Naming Conventions](#naming-conventions)). |
| `${port}` | The service's `port` field from `infra.yml`. |
| `${networks}` | The list of networks the service belongs to. |
| `${project_name}` | From `project.yml`. |
| `${env_name}` | The environment being compiled (`dev`, `test`, `stage`, `prod`). |
| `${role_name}` | The service's `role` field from `infra.yml` (e.g., `web`, `relational_db`). |
| `${env_subdomain}` | The full hostname for the env: `dev.<domain>` / `test.<domain>` / `stage.<domain>` / `www.<domain>` for prod. |
| `${field_value}` | Inside a `fields:` entry, the value the project supplied for that role-specific field. |

### Magic refs

When `infra.yml` references another service via a magic ref like `${backing_services.database.host}`, the compiler resolves it by looking up the named service's engine and rendering the matching part from its `provides:` block — in this case, the postgres engine's `host` part. Magic refs are a CICL feature; transfer tables provide the resolution targets.

## Naming Policies

Most resources in compiled output need a globally-unique name to avoid collisions across projects and environments. The doctrine prescribes the *internal* form:

```
${project_name}_${env_name}_${service_name}
```

That internal form then passes through a **naming policy** appropriate to the target AWS resource type (or to docker, on fixed) before reaching the emitted artifact. Different downstream systems have different constraints:

- **Docker container/network names** accept both underscores and hyphens.
- **AWS resource identifiers** vary by service: RDS allows hyphens but not underscores; S3 bucket names must be lowercase with hyphens and globally unique across all of AWS; SGs are more permissive; etc.

Policies live as a top-level `naming_policies:` block in the transfer tables, named by resource type. Engines reference one by name (`naming: rds`); structural emitters in `docex` code (state backend, project ECR/IAM, SSM path prefix) hardcode the policy name they need.

### Schema

```yml
naming_policies:
	<policy_name>:
		separator: underscore | hyphen
		case: any | lower
		max_len: <int>   # optional
```

- **`separator`** — chooses what `_` in the internal form becomes in the rendered name. `hyphen` translates each `_` to `-`; `underscore` preserves the underscore form (and translates stray `-` back to `_` for symmetry).
- **`case`** — `any` preserves case; `lower` lowercases the rendered name.
- **`max_len`** — if set, a rendered name exceeding this length fails compile with a clear error rather than being silently truncated.

### Doctrine-shipped policies

| Policy | Resource(s) | Separator | Case | Max len |
| ------ | ----------- | --------- | ---- | ------- |
| `s3` | S3 bucket | hyphen | lower | 63 |
| `rds` | RDS instance identifier, DB subnet group, ElastiCache cluster | hyphen | lower | 63 |
| `ddb` | DynamoDB table | underscore | any | 255 |
| `alb` | ALB and target-group name | hyphen | any | 32 |
| `ecs` | ECS cluster, service, task-definition family | underscore | any | 255 |
| `ecr_repo` | ECR repository | underscore | lower | 256 |
| `iam` | IAM role / policy | underscore | any | 64 |
| `ssm_path` | SSM parameter path segment | underscore | any | 1024 |
| `docker` | Docker network / container / volume | underscore | any | (none) |
| `http_host` | DNS label (hostname) | hyphen | lower | (none) |

Default rule, expressed once: **where AWS allows both underscore and hyphen, the doctrine prefers underscore** (matching the project-name form). Hyphen-translation happens only where AWS requires it (S3, RDS, ALB).

### How engines reference a policy

Inside `roles.<role>.<engine>`, the `naming:` field is a string reference into `naming_policies:`:

```yml
roles:
  relational_db:
    postgres:
      ...
      naming: rds          # resolves to the `rds` policy
```

### How structural emitters reference a policy

Resources `docex` emits that are not associated with any `infra.yml` service — the OpenTofu state-backend bucket and DDB table, the project-tier ECR repos, the project task-execution IAM role, the SSM path prefix — pick a policy by hardcoded name in `docex` code. The body of the policy still comes from `naming_policies:` (so it remains reloadable / overridable from a project-local table); only the *choice* of policy is doctrine knowledge embedded in `docex` itself.

## Anatomy of a Role Definition

A role is defined under the top-level `roles:` block. Each role contains one or more named engines that implement it. The schema:

```yml
roles:
	<role_name>:
		description: "<one-line role summary>"   # optional; surfaced by `./bin/docex roles`
		<engine_name>:
			foundation: fixed | elastic | both
			default_port: <int>   # optional
			emits:
				fixed: [<target_name>, ...]     # first entry = default target
				elastic: [<target_name>, ...]   # first entry = default target
			defaults:
				fixed: { ... }
				elastic: { ... }
			fields:
				<role_specific_field>:
					fixed:
						target: <target_name>   # optional; defaults to first emits.fixed entry
						<translation body>
					elastic:
						target: <target_name>   # optional; defaults to first emits.elastic entry
						<translation body>
			provides:
				<part_name>:
					fixed: "..."
					elastic: "..."
			env:
				<ENV_VAR_NAME>: "human-readable description"
			naming: <policy_name>   # reference into top-level naming_policies:
```

### Walking example: `relational_db` / `postgres`

```yml
roles:
	relational_db:
		postgres:
			foundation: both
			emits:
				fixed: [compose_service]
				elastic: [rds_instance]
			defaults:
				fixed:
					volumes:
						- postgres-data:/var/lib/postgresql
					healthcheck:
						test: ["CMD-SHELL", "pg_isready -U $[POSTGRES_USER] -d ${name}"]
						interval: 10s
						timeout: 5s
						retries: 5
					environment:
						POSTGRES_USER: $[POSTGRES_USER]
						POSTGRES_PASSWORD: $[POSTGRES_PASSWORD]
						POSTGRES_DB: ${name}
				elastic:
					engine: "postgres"
					instance_class: "db.t3.medium"
					allocated_storage: 20
					storage_encrypted: false
					publicly_accessible: false
					backup_retention_period: 7
					deletion_protection: true
					storage_type: "gp3"
			fields:
				version:
					fixed:
						image: postgres:${field_value}
					elastic:
						engine_version: ${field_value}
			provides:
				host:
					fixed: "${global_service_name}"
					elastic: "@aws_db_instance.${name}.endpoint"
				port:
					fixed: "${port}"
					elastic: "${port}"
				db:
					fixed: "${name}"
					elastic: "${name}"
				user:
					fixed: "$[POSTGRES_USER]"
					elastic: "$[POSTGRES_USER]"
				password:
					fixed: "$[POSTGRES_PASSWORD]"
					elastic: "$[POSTGRES_PASSWORD]"
				sslmode:
					fixed: "disable"
					elastic: "require"
			env:
				POSTGRES_USER: "The username of the postgres user"
				POSTGRES_PASSWORD: "The password of the postgres user"
			naming: rds   # RDS identifier (hyphen + lower + 63); applied on both foundations for consistency
```

The `sslmode` part exists specifically to bridge a real fixed↔elastic difference that the doctrine would otherwise force projects to encode by hand: local postgres containers accept plain TCP, while AWS RDS rejects non-SSL connections under its default `pg_hba.conf`. Without a `provides:` part, every project's `migrate.sh` (and any other code that builds a connection string) would grow if/else-on-hostname logic — the exact coupling `provides:` exists to eliminate. Surfacing `sslmode` as a part keeps the parts-only model load-bearing on both foundations.

### Field reference

- **`foundation`** (required) — one of `fixed`, `elastic`, or `both`. Declares which foundations this engine supports. The compiler uses this to validate that `infra.yml`'s declared engines are compatible with the foundation being compiled. For roles where the same engine works on both foundations (postgres-in-docker for fixed, postgres-on-RDS for elastic), `both` is used. For roles where the project picks per foundation (e.g., `engine: [minio, s3]` in `infra.yml`), each engine declares its own `foundation` and the compiler picks the matching one for the env being compiled.

- **`default_port`** (optional) — the port this engine listens on by default. When a service using the engine omits the `port:` field in `infra.yml`, the compiler uses this value for the `${port}` substitution variable (and hence the `port` provided-part). Omit it for engines with no canonical port; a magic ref to a port that is neither declared nor defaulted resolves to empty, which is a compile error.

- **`emits`** (required) — per-foundation list of named destinations this engine's translations can land on. The first entry in each list is the *default target* — where `defaults:` lands and where any `fields.<f>.<foundation>` entry without an explicit `target:` lands. Subsequent entries are alternative destinations selectable via `target:`. Each destination name corresponds to a concrete emit site the compiler knows how to render (e.g., `compose_service` → the docker-compose service block; `rds_instance` → the `aws_db_instance` HCL resource; `target_group` → the `aws_lb_target_group` HCL resource). Some destinations are conditional on other state — `target_group`, for instance, only exists when the service is on the `web` network — and routing to an inapplicable destination is a compile error. The set of destination names the compiler recognizes is closed and lives in doctrine knowledge inside docex; a transfer table cannot invent new ones. **The engine's `emits` list is the dispatcher key**: the compiler chooses the per-destination renderer by destination name, not by engine name and not by whether the service is core or backing.

- **`defaults`** (required) — per-foundation blocks of YAML that get merged into the default target's emitted resource for every service using this engine. For fixed this is typically the docker-compose service skeleton (volumes, healthcheck, environment); for elastic it is the engine's primary Tofu resource block (instance class, storage settings, etc.). `defaults:` cannot route to a non-default target — that's what `fields:` translations with `target:` are for.

- **`fields`** (optional) — declares the role-specific fields the project may set on this service in `infra.yml` (e.g., `version: "15"` for relational_db, `versioning: true` for object_store), and how each translates per foundation. The compile-time variable `${field_value}` refers to the value the project supplied. Each per-foundation translation may declare an optional `target:` naming the destination from the engine's `emits:` list; when omitted, the translation lands on the default target. This is what lets a single field on a single service contribute to *more than one* emitted resource — e.g., `health_check_path` on a `web/container` service routes to `target_group` on elastic (the ALB target group's health check) while still landing on `compose_service` (the container's docker healthcheck) on fixed.

- **`provides`** (optional) — declares the discrete connection **parts** of this engine that consumers may reference via magic refs (e.g., `${backing_services.database.host}`). Each part is foundation-aware: a separate template per foundation. Templates may use any of the three [substitution syntaxes](#substitution-grammar) — `${var}` for compile-time values, `$[var]` for runtime app refs, or `@<expr>` for HCL pass-through (elastic only, used for provider-allocated values like RDS endpoints). Common part names are short and consistent across engines of the same role: `host`, `port`, `db`, `user`, `password` for relational_db; `bucket_name`, `region`, `endpoint`, `access_key`, `secret_key` for object_store; etc. Engines may expose any additional parts they need. **An engine never exposes a pre-composed connection string — there is no `url` part** (see the rule below).

	Exposing parts rather than composed strings is a **hard rule**, not a stylistic preference. A composed value (e.g. a `DATABASE_URL`) would have to inline secrets like the database password — but elastic's secret injection (ECS `secrets[]` sourced from SSM) can only deliver each secret as a whole standalone env var; it cannot embed one inside a larger value without materializing that value as plaintext in the task definition and Tofu state. Parts-only is therefore the single model that keeps `provides:` identical across foundations, which is exactly what preserves fixed↔elastic portability. As a consequence, secrets like `$[POSTGRES_USER]` and `$[POSTGRES_PASSWORD]` never appear as inline values in compiled artifacts — they flow through compose's runtime substitution (fixed) or the ECS `secrets[]` block (elastic), staying out of any persisted task definition or compose snapshot. A consumer that needs a composed handle (e.g., `DATABASE_URL`) builds it from the parts at startup — the standard cloud-native pattern, and now the only one.

- **`env`** (optional) — declares the runtime environment variables this engine requires. Each entry is `KEY: "human-readable description"`. The compiler uses this list for two purposes:
	1. **`example.env` generation:** every backing service's `env` entries become rows in `infra/secrets/example.env`, grouped by service.
	2. **Secret wiring:** when a core service binds one of this engine's `provides:` parts whose template includes a `$[...]` runtime ref (e.g. `DATABASE_USER: ${backing_services.database.user}`, where `user` resolves to `$[POSTGRES_USER]`), the compiler wires the secret into the consumer's container under the consumer's **own** key (`DATABASE_USER`) — emitted as a compose `environment:` line `DATABASE_USER: ${POSTGRES_USER}` (fixed) or an ECS `secrets[]` entry `{ name = "DATABASE_USER", valueFrom = <SSM path of POSTGRES_USER> }` (elastic). The container's env-var surface is therefore identical across foundations; only the delivery mechanism differs. The underlying secret's name (`POSTGRES_USER`) is what identifies it in `.env`/SSM — it is not what the application reads. Because a secret part resolves to exactly one bare `$[REF]` (never a composed string), this binding is always 1:1; embedding a secret inside a larger value is a compile error.

- **`naming`** (required) — name of a policy declared in the top-level `naming_policies:` block. The compiler applies the policy's separator/case/max_len when forming `${global_service_name}` for this engine's resources, so per-engine identifier rules live in one declarative table rather than scattered through emit code. See [Naming Policies](#naming-policies) for the canonical set and the doctrine-wide separator preference.

### Walking example: `web` / `container`

```yml
roles:
	web:
		container:
			foundation: both
			emits:
				fixed: [compose_service]
				elastic: [task_definition, ecs_service, target_group]
			defaults:
				fixed:
					# Port, env, and depends_on come from the project's infra.yml.
					# Image is derived from `container_registry` + project + service + version
					# (see cicl.md § Container Registry). cpu/memory limits and tmpfs sizing
					# come from the service's `resources:` block (see § Resources Translation).
					# Routing is NOT carried here. The compiler emits it
					# network-driven for any `web`-network service — Traefik
					# discovery labels (fixed) / an ALB target group + listener
					# rule (elastic), with per-service subdomains. See
					# networks.md and cicl.md § Domain.
				elastic:
					# Port, env, and depends_on come from infra.yml. Image is derived (see fixed
					# block above). cpu/memory/ephemeral_storage come from the service's
					# `resources:` block (see § Resources Translation). Doctrine adds Fargate
					# task settings; the ALB target group + listener rule are emitted alongside
					# the ECS service when this service is on the `web` network.
					launch_type: FARGATE
					network_mode: awsvpc
			fields:
				health_check_path:
					fixed:
						# target omitted → defaults to compose_service
						healthcheck:
							test: ["CMD", "curl", "-f", "http://localhost:${port}${field_value}"]
							interval: 30s
							timeout: 5s
							retries: 3
					elastic:
						target: target_group
						health_check:
							path: ${field_value}
							healthy_threshold: 2
							unhealthy_threshold: 3
							interval: 30
							timeout: 5
			provides:
				host:
					fixed: "${global_service_name}"
					elastic: "${global_service_name}"   # Resolved via ECS Service Connect within the env's namespace
				port:
					fixed: "${port}"
					elastic: "${port}"
			env: {}
			naming: ecs   # ECS cluster/service/task family (underscore, case-preserving, 255)
```

This entry shows what differs from a backing service like postgres:

- **No project-side `engine:` declaration.** Core service roles have a single canonical engine (`container`); the project does not pick one in `infra.yml`. The transfer table's engine layer is filled by the `container` placeholder for schema uniformity.
- **`env: {}` is empty.** Core services do not introduce engine-required env vars the way postgres does (POSTGRES_USER, etc.). The project's own env vars are declared directly in its `core_services.<name>.env` block in `infra.yml`.
- **`provides:` is symmetric across foundations.** Apps reach a core service by the same name on both foundations: `myproject_prod_api` resolves via the shared docker network in fixed, and via ECS Service Connect within the env's namespace in elastic. Same connection string; different resolution mechanism underneath.
- **`health_check_path` is a role-specific field that crosses emit targets.** The project supplies the value (e.g., `/health`) in its `infra.yml`. On fixed, the translation lands on the default `compose_service` target as a docker healthcheck block. On elastic, the translation routes via `target: target_group` to the ALB target group's `health_check` block — *not* to the ECS task definition (the default elastic target). Without the `target:` redirect, the field would silently land on the wrong resource and the ALB would fall back to checking `/`. This is the canonical example of why `emits:` and `target:` exist; before this mechanism the field was structurally undeliverable.

## Failure-mode contract

Errors raised while loading transfer tables — bundled or project-local — are strict and self-describing. The compiler will not silently drop unknown shapes; every malformed entry must be surfaced at load time with enough information to fix it.

1. **Source attribution.** Every error names the YAML file from which the offending value was read (relative to the project root for project-local tables, relative to the docex source for bundled tables). A developer should be able to copy the path from the error and open the file immediately.

2. **Position attribution.** Where the position within the file is recoverable — top-level key, role name, engine name, policy name — the message names it explicitly.

3. **Suggestions on plausible typos.** Unknown keys within a short edit distance of a known key produce a "did you mean X?" hint. Where no close match exists, the full allowed-key list is included instead.

4. **No silent drop.** Unknown top-level keys, unknown engine sub-keys, unknown naming-policy sub-keys, and unknown emit destinations are hard errors at load time. The transfer-table surface is strict — anything outside the schema is rejected at load time, not at use time and not silently.

5. **Identical strictness across both layers.** The same rules apply to doctrine-bundled tables and project-local tables. A bug in a bundled table should fail the same way a bug in a project-local table does.

The full set of allowed keys at each layer is defined in `src/docex/cicl/transfer.py` (`_ALLOWED_*` constants) and in `src/docex/naming.py` (policy keys); they are the source of truth.

## Container-backing services on elastic

A backing service whose engine declares `emits.elastic: [task_definition, ecs_service]` is rendered as an ECS Fargate task on elastic — identical to how a core service is rendered there. The compiler dispatches by the engine's declared destinations, not by whether the service is core or backing.

This is what makes containerized backing services (sidecars, OTel collectors, ClickHouse, anything that runs as a container but isn't bespoke project code) first-class on elastic. The engine declares its image and per-foundation defaults in the transfer table; the compiler routes to the same `task_definition` + `ecs_service` resources the core path uses.

Container-backing engines must bake `cpu` and `memory` (Fargate units; `cpu` as an integer string of vCPU/1024, `memory` as MiB) directly into `defaults.elastic`. Backing services don't carry a `resources:` block in `infra.yml` — the engine controls sizing. Projects that need to tune sizing override the engine's defaults via a project-local transfer table entry.

Stateful container-backing services (ClickHouse, persistent Redis, anything with a data directory that must survive restarts) additionally need persistent storage. EFS attachment on Fargate is covered separately — see [§ Persistent storage on Fargate](#) (added in a follow-on mod).

## Foundation Invariants

In addition to engine-specific config, the compiler applies a small set of foundation-wide invariants to every emitted resource. These are not engine-specific — they apply uniformly across every service in a compiled output.

### Per-container (fixed)

Every compose service receives:

```yml
container_name: ${global_service_name}
logging: *default-logging
restart: unless-stopped
networks: ${networks}
```

Additionally, services on the `web` network receive these Traefik discovery labels:

```yml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.${global_service_name}.rule=${host_rule}"
  - "traefik.http.routers.${global_service_name}.entrypoints=websecure"
  - "traefik.http.routers.${global_service_name}.tls=true"
  - "traefik.http.routers.${global_service_name}.tls.certresolver=doctrine"
  - "traefik.http.services.${global_service_name}.loadbalancer.server.port=${port}"
```

`${host_rule}` is the per-service [host rule](../cicl.md#per-service-subdomains). The literal resolver name `doctrine` is the prescribed handle for the single machine-wide cert resolver — the operator configures Traefik with a resolver of that exact name, and docex emits labels referencing it. Decoupling the *name* (a doctrine handshake) from the *implementation* (currently Let's Encrypt + DNS-01) lets the doctrine evolve the underlying mechanism without changing the handle.

### Per-core-service env (both foundations)

Every core service — regardless of foundation — additionally receives one doctrine-injected env var:

| Variable | Value | Source |
| -------- | ----- | ------ |
| `PROJECT_VERSION` | The project's current version | `project.yml` `version:` field |

The variable is doctrine-injected, not project-declared — a project's `infra.yml` need not list it under `env:`, and listing it explicitly is redundant. The compiler emits it on every core service's environment block (compose `environment:` on fixed; ECS `environment[]` entry on elastic — not an SSM secret, since the version is not sensitive).

The name matches the env var [`./bin/docex stagetest` injects](../cicd.md#staging-tests) into the stage tester container. A service introspecting its own version (e.g. a `/health` endpoint that returns `{"version": "..."}`) reads from the same canonical handle a stage test compares against — so the assertion `body["version"] == os.environ["PROJECT_VERSION"]` is deterministic across the release boundary, not a manual sync.

Backing services do not receive this env var. They run third-party software with no application-side code that would consume it; emitting it on them would be inert.

### Per-compose-file (fixed)

Every emitted `docker-compose.yml` is prepended with the YAML anchor referenced above:

```yml
x-logging: &default-logging
	driver: json-file
	options:
		max-size: "10m"
		max-file: "3"
```

### Depends-on emission (fixed)

Compose `depends_on` is always emitted in long-form (a map), never short-form. For each dependency, `condition` is `service_healthy` when the target service's emitted compose block contains a `healthcheck:`, otherwise `service_started`. Short-form only waits for the target container to start; backing services like postgres take measurable time to become reachable after starting, and a dependent service (or `compose exec` from `./bin/docex up`) that connects too early hits a refused TCP socket. The healthcheck is already declared by the engine, so using it as the wait condition is the deterministic translation.

```yml
depends_on:
	${global_service_name_of_target}:
		condition: service_healthy   # or service_started
```

### Per-resource (elastic)

Every Tofu resource emitted for a service receives:

```hcl
identifier = "${global_service_name}"
tags = {
	project    = "${project_name}"
	env        = "${env_name}"
	service    = "${name}"
	role       = "${role_name}"
	managed_by = "doctrine"
}
```

(The `identifier` field shown above is doctrinal shorthand — different AWS resource types use different names for the field that holds the resource's primary name, e.g. RDS uses `identifier`, ECS uses `name`, S3 uses `bucket`. The compiler maps `${global_service_name}` to the appropriate field per resource type.)

## Resources Translation

The project's per-service [`resources:` block](../cicl.md#resources) is translated by the compiler into per-foundation resource fields. The translation is uniform across all core services regardless of role or engine — it does not appear in any individual engine's transfer-table entry, and engines do not declare cpu/memory defaults themselves.

### Fixed (docker-compose)

For each core service, the compiler emits:

```yml
deploy:
	resources:
		limits:
			cpus: "${resources.cpu}"
			memory: ${resources.memory}
```

If `resources.disk` is set, the compiler additionally emits a sized tmpfs at `/tmp`:

```yml
tmpfs:
	- /tmp:size=${resources.disk}
```

If `resources.gpu` is set, the compiler additionally emits NVIDIA device reservations:

```yml
deploy:
	resources:
		reservations:
			devices:
				- driver: nvidia
				  count: ${resources.gpu.count}
				  capabilities: [gpu]
```

### Elastic (ECS Fargate task definition)

For each core service, the compiler emits the corresponding HCL fields on the Fargate task definition:

```hcl
cpu              = "${resources.cpu * 1024}"   # Fargate vCPU units: 1024 = 1 vCPU
memory           = "${resources.memory in MiB}"
ephemeral_storage {
	size_in_gib = ${resources.disk}            # only when resources.disk is set
}
```

`resources.gpu` is rejected at validation time on elastic compiles — Fargate does not support GPU workloads. See [cicl.md § Resources](../cicl.md#resources) and [infrastructure.md § Deferred](../infrastructure.md#deferred).

### Defaults

`resources.cpu` and `resources.memory` have no defaults — they are required by CICL on every core service. `resources.disk` is optional with these foundation-specific behaviors when omitted:

- **Fixed:** no tmpfs is emitted; the container shares the host disk. The overlay layer remains unbounded regardless of whether `disk` is set (an overlay2 storage driver limitation).
- **Elastic:** `ephemeral_storage` is omitted from the task definition, accepting Fargate's 21 GiB default.

## Validation

When loading transfer tables (doctrine and project-local merged) and compiling against `infra.yml`, the compiler enforces:

1. Every role used by `infra.yml` has at least one engine entry in the merged tables.
2. Every engine declared in `infra.yml` is defined in some transfer table.
3. Every engine's `foundation` field permits the foundation it is being compiled for. (E.g., `engine: minio` in an elastic-foundation env is an error because minio declares `foundation: fixed`.)
4. Every role-specific field used in `infra.yml` for a given service is declared in that engine's `fields:` block.
5. Every compile-time variable reference (`${...}`) in any rendered template resolves to a known variable in its context.
6. Every runtime ref (`$[...]`) appearing in any `provides:` part template is also declared in the engine's `env:` block — so dependency propagation can wire it up correctly when a consumer references that part.
7. Every magic ref in `infra.yml` (e.g., `${backing_services.database.host}`) names a part the referenced engine's `provides:` block exposes.
8. `@<expr>` refs appear only in elastic-side templates (`provides.<part>.elastic`, `defaults.elastic`, etc.) and never in fixed-side templates, where HCL syntax is meaningless.
9. The `naming` policy resolved for each engine is satisfied by the `${global_service_name}` the compiler generates; impossible cases (e.g., a project name + env name + service name combination that exceeds the policy's `max_len`) fail compile cleanly with a descriptive error.
10. Every engine's `naming:` value is the name of a policy declared in `naming_policies:` (bundled or project-local). An unknown policy ref fails compile at load time.
11. Every engine declares a non-empty `emits.fixed` and `emits.elastic` list (the latter only required if the engine supports the elastic foundation). Every destination name in those lists is one the compiler recognizes; unknown destination names fail compile at load time.
12. Every `fields.<f>.<foundation>.target:` value (if set) names a destination in the engine's `emits.<foundation>` list. If the named destination is conditional (e.g., `target_group` requires the service to be on the `web` network) and the condition does not hold for the service being compiled, that is also a compile error — surfaced with a hint pointing at the missing condition.

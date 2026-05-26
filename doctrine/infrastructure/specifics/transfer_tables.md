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
| `${var}` | docex compiler | at `docex compile` | `${global_service_name}` → `myproject-prod-database` |
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

When `infra.yml` references another service via a magic ref like `${backing_services.database.url}`, the compiler resolves it by looking up the named service's transfer-table-defined field — in this case, the postgres engine's `url:` template. Magic refs are a CICL feature; transfer tables provide the resolution targets.

## Naming Conventions

Most resources in compiled output need a globally-unique name to avoid collisions across projects and environments. The doctrine prescribes the format:

```
${project_name}_${env_name}_${service_name}
```

Different downstream systems have different naming constraints:

- **Docker container/network names** accept both underscores and hyphens.
- **AWS resource identifiers** vary by service: RDS allows hyphens but not underscores; S3 bucket names must be lowercase with hyphens and globally unique across all of AWS; SGs are more permissive; etc.

The compiler resolves this with a per-engine convention: use underscores as the separator by default, falling back to hyphens (and other transformations like lowercasing) where required. Each engine's transfer table entry should declare its naming constraints explicitly so the compiler can enforce them consistently. URL formats are similarly engine-specific and are defined in each engine's `url:` field.

## Anatomy of a Role Definition

A role is defined under the top-level `roles:` block. Each role contains one or more named engines that implement it. The schema:

```yml
roles:
	<role_name>:
		<engine_name>:
			foundation: fixed | elastic | both
			defaults:
				fixed: { ... }
				elastic: { ... }
			fields:
				<role_specific_field>:
					fixed: { ... }
					elastic: { ... }
			provides:
				<part_name>:
					fixed: "..."
					elastic: "..."
			env:
				<ENV_VAR_NAME>: "human-readable description"
			naming:
				separator: underscore | hyphen
				case: any | lower
				max_len: <int>
```

### Walking example: `relational_db` / `postgres`

```yml
roles:
	relational_db:
		postgres:
			foundation: both
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
			env:
				POSTGRES_USER: "The username of the postgres user"
				POSTGRES_PASSWORD: "The password of the postgres user"
			naming:
				separator: hyphen   # for elastic (RDS identifier); fixed permits underscore but we use hyphen consistently
				case: lower
				max_len: 63
```

### Field reference

- **`foundation`** (required) — one of `fixed`, `elastic`, or `both`. Declares which foundations this engine supports. The compiler uses this to validate that `infra.yml`'s declared engines are compatible with the foundation being compiled. For roles where the same engine works on both foundations (postgres-in-docker for fixed, postgres-on-RDS for elastic), `both` is used. For roles where the project picks per foundation (e.g., `engine: [minio, s3]` in `infra.yml`), each engine declares its own `foundation` and the compiler picks the matching one for the env being compiled.

- **`defaults`** (required) — per-foundation blocks of YAML that get merged into the emitted resource definition for every service using this engine. For fixed this is the docker-compose service skeleton (volumes, healthcheck, environment); for elastic it is the Tofu resource block (instance class, storage settings, etc.).

- **`fields`** (optional) — declares the role-specific fields the project may set on this service in `infra.yml` (e.g., `version: "15"` for relational_db, `versioning: true` for object_store), and how each translates per foundation. The compile-time variable `${field_value}` refers to the value the project supplied.

- **`provides`** (optional) — declares the parts of this engine that consumers may reference via magic refs (e.g., `${backing_services.database.host}`). Each part is foundation-aware: a separate template per foundation. Templates may use any of the three [substitution syntaxes](#substitution-grammar) — `${var}` for compile-time values, `$[var]` for runtime app refs, or `@<expr>` for HCL pass-through (elastic only, used for provider-allocated values like RDS endpoints). Common part names are short and consistent across engines of the same role: `host`, `port`, `db`, `user`, `password` for relational_db; `bucket_name`, `region`, `endpoint`, `access_key`, `secret_key` for object_store; etc. Engines may expose any additional parts they need.

	Because `provides:` exposes parts rather than composed strings, secrets like `$[POSTGRES_USER]` and `$[POSTGRES_PASSWORD]` never appear as inline values in compiled artifacts — they only flow through compose's runtime substitution (fixed) or ECS's `secrets[]` block (elastic), keeping them out of any persisted task definition or compose snapshot. Apps that need a composed URL (e.g., `DATABASE_URL`) construct it themselves from the parts at startup, which is the standard cloud-native pattern.

- **`env`** (optional) — declares the runtime environment variables this engine requires. Each entry is `KEY: "human-readable description"`. The compiler uses this list for two purposes:
	1. **`example.env` generation:** every backing service's `env` entries become rows in `infra/secrets/example.env`, grouped by service.
	2. **Dependency propagation:** when a core service references one of this engine's `provides:` parts whose template includes a `$[...]` runtime ref (e.g., `${backing_services.database.user}` resolves to `$[POSTGRES_USER]`), the compiler ensures that same env var also reaches the consumer's container — emitted as a compose `environment:` line (fixed) or as an ECS `secrets[]` entry (elastic).

- **`naming`** (optional, but engine-specific constraints must be declared somewhere) — machine-readable form of the engine's identifier constraints. Lets the compiler pick the right separator, case, and length when forming `${global_service_name}` for this engine's resources without hardcoding per-engine rules in the compiler itself.

### Walking example: `web` / `container`

```yml
roles:
	web:
		container:
			foundation: both
			defaults:
				fixed:
					# Port, env, and depends_on come from the project's infra.yml.
					# Image is derived from `container_registry` + project + service + version
					# (see cicl.md § Container Registry). cpu/memory limits and tmpfs sizing
					# come from the service's `resources:` block (see § Resources Translation).
					# Doctrine adds Traefik discovery labels so the machine-wide reverse_proxy
					# routes the env's subdomain to this container.
					labels:
						- "traefik.enable=true"
						- "traefik.http.routers.${global_service_name}.rule=Host(`${env_subdomain}`)"
						- "traefik.http.routers.${global_service_name}.entrypoints=websecure"
						- "traefik.http.routers.${global_service_name}.tls=true"
						- "traefik.http.services.${global_service_name}.loadbalancer.server.port=${port}"
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
						healthcheck:
							test: ["CMD", "curl", "-f", "http://localhost:${port}${field_value}"]
							interval: 30s
							timeout: 5s
							retries: 3
					elastic:
						target_group_health_check:
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
			naming:
				separator: hyphen
				case: lower
				max_len: 63
```

This entry shows what differs from a backing service like postgres:

- **No project-side `engine:` declaration.** Core service roles have a single canonical engine (`container`); the project does not pick one in `infra.yml`. The transfer table's engine layer is filled by the `container` placeholder for schema uniformity.
- **`env: {}` is empty.** Core services do not introduce engine-required env vars the way postgres does (POSTGRES_USER, etc.). The project's own env vars are declared directly in its `core_services.<name>.env` block in `infra.yml`.
- **`provides:` is symmetric across foundations.** Apps reach a core service by the same name on both foundations: `myproject-prod-api` resolves via the shared docker network in fixed, and via ECS Service Connect within the env's namespace in elastic. Same connection string; different resolution mechanism underneath.
- **`health_check_path` is a role-specific field.** The project supplies the value (e.g., `/health`) in its `infra.yml`, and the transfer table translates it into a docker healthcheck block for fixed or an ALB target-group health check for elastic.

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

### Per-compose-file (fixed)

Every emitted `docker-compose.yml` is prepended with the YAML anchor referenced above:

```yml
x-logging: &default-logging
	driver: json-file
	options:
		max-size: "10m"
		max-file: "3"
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
9. The `naming` constraints declared by each engine are satisfied by the `${global_service_name}` the compiler generates; impossible cases (e.g., a project name + env name + service name combination that exceeds an engine's `max_len`) fail compile cleanly with a descriptive error.

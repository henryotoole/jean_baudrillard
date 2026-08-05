---
stratum: conditional
---

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

A `$[VAR]`'s resolution depends on the **`kind`** of the engine `env:` entry it names (see [§ Anatomy of a Role Definition](#anatomy-of-a-role-definition)): a `secret` or `minted` var is emitted as the pass-through runtime reference described above; a `fixed` var is instead resolved to its literal `value:` at compile time and inlined, so it never reaches the runtime layer.

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
| `${name}` | The service's identity as the compiler keys it: the simple `infra.yml` name for a backing service (e.g. `database`), and the two-segment compiled identity for a [core service](../cicl.md#core-services) (e.g. `api-web`). |
| `${global_service_name}` | The globally-unique form of the service name (see [Naming Policies](#naming-policies)). |
| `${port}` | The service's `port` field from `infra.yml`. |
| `${networks}` | The list of networks the service belongs to. |
| `${project_name}` | From `project.yml`. |
| `${env_name}` | The environment being compiled (`dev`, `test`, `stage`, `prod`). |
| `${role_name}` | The service's `role` field from `infra.yml` (e.g., `web`, `relational_db`). |
| `${env_subdomain}` | The full bare-env hostname per [cicl.md § Domain](../cicl.md#domain): `${env_name}.${project_name}.${apex_domain}` (e.g., `dev.myproject.example.com`, `prod.myproject.example.com`). The bare-project ergonomic shortcut `${project_name}.${apex_domain}` is also available as `${bare_project_subdomain}` for prod-routing rules. |
| `${apex_domain}` | The apex domain from `infra.yml`'s `apex_domain:` field. |
| `${field_value}` | Inside a `fields:` entry, the value the project supplied for that role-specific field. |

### Magic refs

When `infra.yml` references another service via a magic ref like `${backing_services.database.host}`, the compiler resolves it by looking up the named service's engine and rendering the matching part from its `provides:` block — in this case, the postgres engine's `host` part. Magic refs are a CICL feature; transfer tables provide the resolution targets.

## Naming Policies

Most resources in compiled output need a globally-unique name to avoid collisions across projects and environments. The doctrine prescribes the *internal* form:

```
${project_name}_${env_name}_${service_name}
```

`${service_name}` here is the service's compiled identity as `${name}` gives it (see [§ Available compile-time variables](#available-compile-time-variables)): the two-segment `<codebase>-<service>` for a [core service](../cicl.md#core-services), the bare `infra.yml` key for a backing service. The compiler's **codebase-keyed** artifacts — the per-codebase exec container and migration task definition — put the codebase name in that slot instead, which is what makes them de-qualified by construction (see [§ Per-core-service env](#per-core-service-env-both-foundations)). The ECR repo is neither: it is a two-segment path emitted structurally, with no policy applied at all.

That internal form then passes through a **naming policy** appropriate to the target AWS resource type (or to docker, on fixed) before reaching the emitted artifact. Different downstream systems have different constraints:

- **Docker container, network, and volume names** always use hyphens — the `docker` policy is hyphen-only and applies wherever a Docker resource is rendered, regardless of which engine emitted it.
- **AWS resource identifiers** vary by service: RDS requires hyphens; S3 bucket names must be lowercase with hyphens and globally unique across all of AWS; ECS clusters/services/task-defs and Service Connect names also use hyphens (so a service's compiled name is identical on fixed Docker and elastic ECS); IAM roles, SSM path segments, and DynamoDB tables preserve underscores. ECR repo names are a special case (a two-segment path joined by `/`) handled by a structural emitter rather than a naming policy — see [§ How structural emitters reference a policy](#how-structural-emitters-reference-a-policy).

Policies live as a top-level `naming_policies:` block in the transfer tables, named by resource type. Engines reference one by name (`naming: rds`); structural emitters in `docex` code (state backend, project IAM, SSM path prefix, ECR repo path) hardcode either the policy name they need or — when the policy machinery cannot express the desired shape — the rendering itself.

### Schema

```yml
naming_policies:
	<policy_name>:
		separator: underscore | hyphen
		case: any | lower
		max_len: <int>              # optional
		overflow: error | hash_truncate   # optional; default error
```

- **`separator`** — chooses what `_` in the internal form becomes in the rendered name. `hyphen` translates each `_` to `-`; `underscore` preserves the underscore form (and translates stray `-` back to `_` for symmetry).
- **`case`** — `any` preserves case; `lower` lowercases the rendered name.
- **`max_len`** — if set, a rendered name exceeding this length is handled per `overflow`.
- **`overflow`** *(optional; default `error`)* — what to do when the rendered name exceeds `max_len`. `error` fails compile with a clear message rather than silently truncating — the correct default, because most identifiers double as human-facing names and a silent truncation would be surprising. `hash_truncate` keeps a readable prefix and appends `-<h>`, where `<h>` is the first 6 hex characters of the SHA-256 of the full internal name — guaranteeing the result fits `max_len` while staying collision-resistant across distinct inputs that share a truncated prefix. Use `hash_truncate` only for AWS **identifier** fields that are *not* the human-facing `Name` tag; the descriptive full name is preserved in the resource's `Name` tag (see [cicl.md § Naming and Tagging](../cicl.md#naming-and-tagging)). The `alb` policy uses it because the ALB and target-group `name` fields hard-cap at 32 characters, which a `${project}_${env}_${service}` combination overruns for all but the shortest project names.

### Doctrine-shipped policies

| Policy | Resource(s) | Separator | Case | Max len | Overflow |
| ------ | ----------- | --------- | ---- | ------- | -------- |
| `s3` | S3 bucket | hyphen | lower | 63 | error |
| `rds` | RDS instance identifier, DB subnet group, ElastiCache cluster | hyphen | lower | 63 | error |
| `ddb` | DynamoDB table | underscore | any | 255 | error |
| `alb` | ALB and target-group name | hyphen | any | 32 | hash_truncate |
| `ecs` | ECS cluster, service, task-definition family, Service Connect discoverable name | hyphen | any | 255 | error |
| `iam` | IAM role / policy | underscore | any | 64 | error |
| `ssm_path` | SSM parameter path segment | underscore | any | 1024 | error |
| `docker` | Docker network / container / volume | hyphen | any | (none) | error |
| `http_host` | DNS label (hostname) | hyphen | lower | (none) | error |

Default rule, expressed once: **anything name-resolvable on the data plane** — Docker containers/networks/volumes, ECS cluster/service/task-def identifiers, ECS Service Connect names, ALB/target-group names, S3 buckets, RDS identifiers, hostnames — **uses hyphens**, so a service's compiled name is identical on fixed Docker and elastic ECS. **Underscores are preserved only for inert identifiers** that AWS uses as record keys but applications never name in DNS or compose: IAM roles, SSM path segments, and DynamoDB tables.

**ECR repo names are a separate case.** The image-reference form `${container_registry}/${project_name}/${codebase_name}:${version}` declared in [cicl.md § Container Registry and Service Images](../cicl.md#container-registry-and-service-images) requires a literal `/` between the project segment and the codebase segment, with each segment's own underscores preserved. The single-separator naming-policy machinery cannot express "join with `/`, preserve `_` inside each segment" — `separator: hyphen` mangles intra-segment underscores; `separator: underscore` produces the wrong joiner. ECR repo naming is therefore not handled by a policy entry; it is emitted directly by the structural emitter — see [§ How structural emitters reference a policy](#how-structural-emitters-reference-a-policy).

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

Resources `docex` emits that are not associated with any `infra.yml` service — the OpenTofu state-backend bucket and DDB table, the project task-execution IAM role, the SSM path prefix — pick a policy by hardcoded name in `docex` code. The body of the policy still comes from `naming_policies:` (so it remains reloadable / overridable from a project-local table); only the *choice* of policy is doctrine knowledge embedded in `docex` itself.

Some structural emitters render a shape the single-separator policy machinery cannot express, and in those cases the emitter hardcodes the rendering directly rather than referencing a policy. The current case is **ECR repos**: the emitter renders `${project_name}/${codebase_name}` literally — each segment verbatim, slash as joiner. No policy applies. The SSM path prefix `/${project}/${env}/` is a milder version of the same pattern: the `ssm_path` policy controls per-segment rendering, but the `/` joiners between `project`, `env`, and the parameter key are emitted directly by docex code, not by the policy. The principle is the same — joiners with shape that can't be reduced to a single global separator live in the emitter; the policy governs only what happens within a segment.

## Generation Policies

A `kind: minted` env var (see [§ Anatomy of a Role Definition](#anatomy-of-a-role-definition)) is generated by `docex`, not supplied by the operator. **Generation policies** describe how to mint such a value. They are a deliberate sibling to — not part of — [naming policies](#naming-policies): a naming policy is consumed by a *formatter* that reshapes an existing identifier (separator/case/length); a generation policy is consumed by a *generator* that produces a fresh random value (length + alphabet). Conflating them would muddy both the formatter/generator surfaces and the load-time allowlists.

Policies live in a top-level `generation_policies:` block and are referenced by name from a minted env var's `policy:` field.

### Schema

```yml
generation_policies:
	<policy_name>:
		length: <int>
		alphabet: url_safe | alnum   # named character set
```

### Doctrine-shipped policies

| Policy | Length | Alphabet |
| ------ | ------ | -------- |
| `password` | 32 | `url_safe` |

One general `password` policy covers every foreseeable minted credential across engines. **`url_safe` is load-bearing, not incidental.** Under the [parts-only rule](#anatomy-of-a-role-definition) the *application* composes its own connection string from parts at startup, so a password containing `@ : / # ? % & +` breaks a naive `scheme://user:pass@host/db` build; independently, AWS RDS forbids `/ @ "` and spaces in the master password. `url_safe` (`[A-Za-z0-9]` plus `-` and `_`) is the intersection safe for both, and 32 characters of it is ~190 bits — ample for a credential that sits well below the top of defense-in-depth. Generation uses a CSPRNG.

Generation policies deep-merge across the bundled and project-local layers exactly like naming policies — a project may override `password.length` or define a new policy and reference it from a project-local engine's minted env var.

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
				# Scalar shorthand — KEY: "desc" == {kind: secret, desc: "desc"}:
				<ENV_VAR_NAME>: "human-readable description"
				# Full form declares the variable's kind:
				<ENV_VAR_NAME>:
					kind: secret | minted | fixed   # default: secret
					desc: "human-readable description"
					value: "<literal>"              # kind: fixed only
					policy: <generation_policy>     # kind: minted only
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
						- ${global_service_name}_data:/var/lib/postgresql/data
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
					# .address (hostname only), NOT .endpoint (host:port) — port is its
					# own part, and .endpoint would compose to a malformed host:port:port.
					elastic: "@aws_db_instance.${name}.address"
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
				POSTGRES_USER:
					kind: fixed
					value: appuser
					desc: "Postgres role name — doctrine-fixed, not a secret."
				POSTGRES_PASSWORD:
					kind: minted
					policy: password
					desc: "Postgres role password — generated once per env."
			naming: rds   # RDS identifier (hyphen + lower + 63); applied on both foundations for consistency
```

Every `$[POSTGRES_USER]` reference in `defaults`, the `healthcheck`, and `provides.user` is left unchanged — because `POSTGRES_USER` is `kind: fixed`, the compiler inlines `appuser` at each site, so the username leaves the store entirely and only `POSTGRES_PASSWORD` is minted. `appuser` clears RDS master-username rules and this engine's own `reserved_names`.

The `sslmode` part exists specifically to bridge a real fixed↔elastic difference that the doctrine would otherwise force projects to encode by hand: local postgres containers accept plain TCP, while AWS RDS rejects non-SSL connections under its default `pg_hba.conf`. Without a `provides:` part, every project's `migrate.sh` (and any other code that builds a connection string) would grow if/else-on-hostname logic — the exact coupling `provides:` exists to eliminate. Surfacing `sslmode` as a part keeps the parts-only model load-bearing on both foundations.

### Field reference

- **`foundation`** (required) — one of `fixed`, `elastic`, or `both`. Declares which foundations this engine supports. The compiler uses this to validate that `infra.yml`'s declared engines are compatible with the foundation being compiled. For roles where the same engine works on both foundations (postgres-in-docker for fixed, postgres-on-RDS for elastic), `both` is used. For roles where the project picks per foundation (e.g., `engine: [minio, s3]` in `infra.yml`), each engine declares its own `foundation` and the compiler picks the matching one for the env being compiled.

- **`default_port`** (optional) — the port this engine listens on by default. When a service using the engine omits the `port:` field in `infra.yml`, the compiler uses this value for the `${port}` substitution variable (and hence the `port` provided-part). Omit it for engines with no canonical port; a magic ref to a port that is neither declared nor defaulted resolves to empty, which is a compile error.

- **`emits`** (required) — per-foundation list of named destinations this engine's translations can land on. The first entry in each list is the *default target* — where `defaults:` lands and where any `fields.<f>.<foundation>` entry without an explicit `target:` lands. Subsequent entries are alternative destinations selectable via `target:`. Each destination name corresponds to a concrete emit site the compiler knows how to render (e.g., `compose_service` → the docker-compose service block; `rds_instance` → the `aws_db_instance` HCL resource; `target_group` → the `aws_lb_target_group` HCL resource; `container_definition` → **not a resource at all but a merge target**: its renderer emits nothing, and a field routed to it is merged into the ECS *container* definition the `task_definition` destination already builds. This is how a `worker` gets a container-level `healthCheck`, since it has no target group to hang one on). Some destinations are conditional on other state — `target_group`, for instance, only exists when the service is on the `web` network — and routing to an inapplicable destination is a compile error. The set of destination names the compiler recognizes is closed and lives in doctrine knowledge inside docex; a transfer table cannot invent new ones. **The engine's `emits` list is the dispatcher key**: the compiler chooses the per-destination renderer by destination name, not by engine name and not by whether the service is core or backing.

- **`defaults`** (required) — per-foundation blocks of YAML that get merged into the default target's emitted resource for every service using this engine. For fixed this is typically the docker-compose service skeleton (volumes, healthcheck, environment); for elastic it is the engine's primary Tofu resource block (instance class, storage settings, etc.). `defaults:` cannot route to a non-default target — that's what `fields:` translations with `target:` are for.

- **`fields`** (optional) — declares the role-specific fields the project may set on this service in `infra.yml` (e.g., `version: "15"` for relational_db, `versioning: true` for object_store), and how each translates per foundation. The compile-time variable `${field_value}` refers to the value the project supplied. Each per-foundation translation may declare an optional `target:` naming the destination from the engine's `emits:` list; when omitted, the translation lands on the default target. This is what lets a single field on a single service contribute to *more than one* emitted resource — e.g., `health_check_path` on a `web/container` service routes to `target_group` on elastic (the ALB target group's health check) while still landing on `compose_service` (the container's docker healthcheck) on fixed.

- **`provides`** (optional) — declares the discrete connection **parts** of this engine that consumers may reference via magic refs (e.g., `${backing_services.database.host}`). Each part is foundation-aware: a separate template per foundation. Templates may use any of the three [substitution syntaxes](#substitution-grammar) — `${var}` for compile-time values, `$[var]` for runtime app refs, or `@<expr>` for HCL pass-through (elastic only, used for provider-allocated values like RDS endpoints). Common part names are short and consistent across engines of the same role: `host`, `port`, `db`, `user`, `password` for relational_db; `bucket_name`, `region`, `endpoint`, `access_key`, `secret_key` for object_store; etc. Engines may expose any additional parts they need. **An engine never exposes a pre-composed connection string — there is no `url` part** (see the rule below).

	Exposing parts rather than composed strings is a **hard rule**, not a stylistic preference. A composed value (e.g. a `DATABASE_URL`) would have to inline secrets like the database password — but elastic's secret injection (ECS `secrets[]` sourced from SSM) can only deliver each secret as a whole standalone env var; it cannot embed one inside a larger value without materializing that value as plaintext in the task definition and Tofu state. Parts-only is therefore the single model that keeps `provides:` identical across foundations, which is exactly what preserves fixed↔elastic portability. As a consequence, a secret like `$[POSTGRES_PASSWORD]` never appears as an inline value in compiled artifacts — it flows through compose's runtime substitution (fixed) or the ECS `secrets[]` block (elastic), staying out of any persisted task definition or compose snapshot. (A `kind: fixed` var such as `POSTGRES_USER` is the opposite case: it is inlined to its literal `appuser` at compile and *does* appear inline — safe precisely because it is not a secret.) A consumer that needs a composed handle (e.g., `DATABASE_URL`) builds it from the parts at startup — the standard cloud-native pattern, and now the only one.

- **`env`** (optional) — declares the runtime environment variables this engine requires. Each entry carries a **`kind`** (default `secret`) that determines how the compiler resolves the variable's `$[...]` references and where, if anywhere, its value is stored:
	- **`secret`** — an operator-supplied secret with no in-project source. Its key surfaces in the project's secrets surface (`infra/secrets/<env>.env`, reconciled by `docex secrets scaffold`); its `$[...]` refs are emitted as runtime references (compose `${VAR}` / ECS `secrets[]`) exactly as before.
	- **`minted`** — a value `docex` generates per its `policy:` (see [§ Generation Policies](#generation-policies)) the first time an env needs it, recorded in that env's **TTE store** (never the secrets file, never git). Its `$[...]` refs are emitted as runtime references like a secret; only the *source* differs. Generation is impure and never runs at `compile`.
	- **`fixed`** — a doctrine-fixed literal (`value:`), not a secret and not stored. Every `$[VAR]` reference to it is **inlined at compile time**; the variable appears in no store and no secrets file.

	Because a secret or minted part resolves to exactly one bare `$[REF]` (never a composed string), the container-edge binding stays 1:1 — a consumer's `DATABASE_PASSWORD: ${backing_services.database.password}` is delivered as a compose `environment:` line `DATABASE_PASSWORD: ${POSTGRES_PASSWORD}` (fixed) or an ECS `secrets[]` entry `{ name = "DATABASE_PASSWORD", valueFrom = <SSM path of POSTGRES_PASSWORD> }` (elastic). The container's env-var surface is identical across foundations; only the delivery mechanism differs, and the underlying key (`POSTGRES_PASSWORD`) identifies the value in the store, not what the app reads. Embedding a secret inside a larger value is a compile error. (The full source→container flow is in [config_and_secrets.md](./config_and_secrets.md).)

- **`naming`** (required) — name of a policy declared in the top-level `naming_policies:` block. The compiler applies the policy's separator/case/max_len when forming `${global_service_name}` for this engine's resources, so per-engine identifier rules live in one declarative table rather than scattered through emit code. See [Naming Policies](#naming-policies) for the canonical set and the doctrine-wide separator preference.

- **`persistent_storage`** (optional) — declares this engine needs a durable data directory mounted into the container. Single field: `mount_path` (the container-side path). Required for stateful container-backing services on elastic, where the doctrine emits an EFS filesystem and mounts it at `mount_path`. Engines that declare `persistent_storage` MUST also include `efs_file_system` in `emits.elastic` (bidirectional validation, enforced at load). On fixed, the field is informational — engines manage their own docker named volume via `defaults.fixed.volumes`. See [Persistent storage on Fargate](#persistent-storage-on-fargate).

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
					# Port, env, and uses come from the project's infra.yml.
					# Image is derived from `container_registry` + project + service + version
					# (see cicl.md § Container Registry). cpu/memory limits and tmpfs sizing
					# come from the service's `resources:` block (see § Resources Translation).
					# Routing is NOT carried here. The compiler emits it
					# network-driven for any `web`-network service — Traefik
					# discovery labels picked up by the project's own traefik
					# (fixed) / an ALB target group + listener rule attached
					# to the project ALB (elastic), with per-service domains.
					# See networks.md and cicl.md § Domain.
				elastic:
					# Port, env, and uses come from infra.yml. Image is derived (see fixed
					# block above). cpu/memory/ephemeral_storage come from the service's
					# `resources:` block (see § Resources Translation). Doctrine adds Fargate
					# task settings; the ALB target group + listener rule are emitted alongside
					# the ECS service when this service is on the `web` network, attaching to
					# the project's project-tier ALB by ARN (looked up via the project tofu
					# remote state).
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
					elastic: "${global_service_name}"   # Service Connect discoveryName. Resolvable by ECS tasks inside the namespace (via Envoy sidecar). Mesh-internal only — not resolvable from outside the mesh via DNS. See shape.md § Elastic-Foundation.
				port:
					fixed: "${port}"
					elastic: "${port}"
			env: {}
			naming: ecs   # ECS cluster/service/task family + Service Connect name (hyphen, case-preserving, 255)
```

This entry shows what differs from a backing service like postgres:

- **No project-side `engine:` declaration.** Core service roles have a single canonical engine (`container`); the project does not pick one in `infra.yml`. The transfer table's engine layer is filled by the `container` placeholder for schema uniformity.
- **`env: {}` is empty.** Core services do not introduce engine-required env vars the way postgres does (POSTGRES_USER, etc.). The project's own env vars are declared directly in its `codebases.<cb>.core_services.<svc>.env` block in `infra.yml` (or codebase-wide in `codebases.<cb>.env`).
- **`provides:` is symmetric across foundations.** Apps reach a core service by the same name on both foundations: `myproject-prod-api-web` resolves via the shared docker network in fixed, and via ECS Service Connect within the env's namespace in elastic. Same connection string; different resolution mechanism underneath.
- **`health_check_path` is a role-specific field that crosses emit targets.** The project supplies the value (e.g., `/health`) in its `infra.yml`. On fixed, the translation lands on the default `compose_service` target as a docker healthcheck block. On elastic, the translation routes via `target: target_group` to the ALB target group's `health_check` block — *not* to the ECS task definition (the default elastic target). Without the `target:` redirect, the field would silently land on the wrong resource and the ALB would fall back to checking `/`. This is the canonical example of why `emits:` and `target:` exist; before this mechanism the field was structurally undeliverable.

## Failure-mode contract

Errors raised while loading transfer tables — bundled or project-local — are strict and self-describing. The compiler will not silently drop unknown shapes; every malformed entry must be surfaced at load time with enough information to fix it.

1. **Source attribution.** Every error names the YAML file from which the offending value was read (relative to the project root for project-local tables, relative to the docex source for bundled tables). A developer should be able to copy the path from the error and open the file immediately.

2. **Position attribution.** Where the position within the file is recoverable — top-level key, role name, engine name, policy name — the message names it explicitly.

3. **Suggestions on plausible typos.** Unknown keys within a short edit distance of a known key produce a "did you mean X?" hint. Where no close match exists, the full allowed-key list is included instead.

4. **No silent drop.** Unknown top-level keys, unknown engine sub-keys, unknown naming-policy sub-keys, unknown generation-policy sub-keys, and unknown emit destinations are hard errors at load time. The transfer-table surface is strict — anything outside the schema is rejected at load time, not at use time and not silently.

5. **Identical strictness across both layers.** The same rules apply to doctrine-bundled tables and project-local tables. A bug in a bundled table should fail the same way a bug in a project-local table does.

The full set of allowed keys at each layer is defined in `src/docex/cicl/transfer.py` (`_ALLOWED_*` constants) and in `src/docex/naming.py` (policy keys); they are the source of truth.

## Container-backing services on elastic

A backing service whose engine declares `emits.elastic: [task_definition, ecs_service]` is rendered as an ECS Fargate task on elastic — identical to how a core service is rendered there. The compiler dispatches by the engine's declared destinations, not by whether the service is core or backing.

This is what makes containerized backing services (sidecars, OTel collectors, ClickHouse, anything that runs as a container but isn't bespoke project code) first-class on elastic. The engine declares its image and per-foundation defaults in the transfer table; the compiler routes to the same `task_definition` + `ecs_service` resources the core path uses.

Container-backing engines must bake `cpu` and `memory` (Fargate units; `cpu` as an integer string of vCPU/1024, `memory` as MiB) directly into `defaults.elastic`. Backing services don't carry a `resources:` block in `infra.yml` — the engine controls sizing. Projects that need to tune sizing override the engine's defaults via a project-local transfer table entry.

Stateful container-backing services (ClickHouse, persistent Redis, anything with a data directory that must survive restarts) additionally need persistent storage. See [§ Persistent storage on Fargate](#persistent-storage-on-fargate) below.

## Persistent storage on Fargate

A container-backing service whose engine declares `persistent_storage` gets a per-service EFS filesystem mounted into the task at the declared `mount_path`. This is the doctrine's mechanism for stateful container backings on elastic — ClickHouse, persistent Redis, anything that needs a durable data directory.

```yml
roles:
  analytics_db:
    clickhouse:
      emits:
        elastic: [task_definition, ecs_service, efs_file_system]
      persistent_storage:
        mount_path: /var/lib/clickhouse
      fields:
        backups:
          elastic:
            target: efs_file_system
            enabled: ${field_value}
      ...
```

The compiler emits, per such service:

- `aws_efs_file_system` — encrypted at rest using the AWS-managed KMS key.
- `aws_efs_mount_target` per private subnet — so tasks in any AZ can mount the filesystem. Mount targets attach to the service's non-`web` security groups, leveraging the existing `internal` SG's self-ingress for NFS port 2049 — no new SG rule needed.
- A `volume` block on the `aws_ecs_task_definition` referencing the EFS by ID, with `transit_encryption = "ENABLED"`.
- A `mountPoints` entry on the container definition linking the volume to the declared `mount_path`. The volume name inside the task definition is the doctrine-fixed handle `"data"` (one EFS per stateful service, mounted at one path).

**Backups are project-opt-in.** Engines that emit `efs_file_system` may declare a `backups` field with `target: efs_file_system` (the field-routing mechanism described in [§ Anatomy of a Role Definition](#anatomy-of-a-role-definition)); the project sets `backups: true` on the backing service in `infra.yml` to enable. When enabled, the compiler emits an `aws_efs_backup_policy` resource tying the filesystem to the AWS Backup default plan. Default disabled — only the project knows whether the data is replaceable cache or irreplaceable user state.

**Bidirectional validation.** An engine declaring `persistent_storage` must also declare `efs_file_system` in `emits.elastic`, and vice-versa. Either alone is a compile-time error at load — they go together.

**EFS access points and lifecycle policies are out of scope.** Engines that need them can extend via project-local transfer tables. Default behavior: mount the EFS root, keep all files in Standard storage.

**On fixed**, `persistent_storage` is informational only. Engine authors declare their docker named volume in `defaults.fixed.volumes` themselves (the existing pattern, as postgres demonstrates). The fixed and elastic sides agree on `mount_path` because the engine declares both — small duplication, large clarity.

## Authoring Project-Local Transfer Tables

The doctrine ships canonical engines for the common roles — `relational_db/postgres`, `cache/redis`, `object_store/{minio,s3}`, `web/container`, `worker/container` (long-running non-HTTP core services — queue consumers, stream processors), `clock/container` (the scheduled-work singleton — see [clock.md](./clock.md)). When a project needs a role or engine the doctrine doesn't bundle (ClickHouse, OpenTelemetry collector, RabbitMQ, etc.), it adds a project-local transfer table. The doctrine's machinery does the rest: schema validation, foundation translation, magic-ref resolution, ECS dispatch, EFS plumbing if stateful.

This section is the authoring perspective. The schema and rules live earlier in this document — this section is "how to actually write one."

### File layout and discovery

Project-local tables live at `<project_root>/infra/transfer_tables/`. The loader (`load_transfer_tables` in `src/docex/cicl/transfer.py`) discovers them by recursive `*.yml` / `*.yaml` glob, so either layout works:

```
infra/transfer_tables/
├── sidecar.yml              # flat — one engine per file
└── clickhouse.yml
```

or

```
infra/transfer_tables/
└── roles/
    ├── telemetry.yml
    └── analytics.yml        # nested — match the doctrine's tables/roles/ layout
```

Bundled tables live inside the docex image at `tables/`. The loader reads bundled tables first, then project-local — project values override bundled at every leaf. See [§ Deep-merge semantics](#deep-merge-semantics) below for the exact merge rules.

Every error from the loader names the source file (`tables/roles/<file>.yml` for bundled, `infra/transfer_tables/<file>.yml` for project-local) per [§ Failure-mode contract](#failure-mode-contract). Authors should expect strict, source-attributed failures — typos and schema violations fail at load time, not silently or downstream.

### Deep-merge semantics

The two layers — bundled and project-local — are deep-merged at compile time. The rules:

- **Dicts merge key-by-key.** A project-local table can override individual leaf values without restating the whole engine entry.
- **Scalars (strings, numbers, bools) are replaced wholesale.** Project value wins.
- **Lists are replaced wholesale.** No append, no merge-by-element. If a project wants to "extend" a bundled list, it must restate the full list.
- **`None` does NOT remove a key.** To zero out a leaf, supply an empty dict / string / list — don't omit it.

A mini-example: the doctrine-bundled postgres engine declares `defaults.elastic.instance_class: db.t3.medium`. A project that needs a larger instance writes only the override:

```yml
# infra/transfer_tables/postgres_override.yml
roles:
  relational_db:
    postgres:
      defaults:
        elastic:
          instance_class: db.t3.large
```

After merge, the postgres engine has `instance_class: db.t3.large` and all other bundled fields (foundation, naming, emits, the rest of defaults, fields, provides, env) unchanged. The project did not restate them and does not need to.

The same model applies to **naming policies**. The top-level `naming_policies:` block deep-merges across layers. A project can:

- **Override an existing policy's parameters.** E.g., tighten `s3`'s `max_len` from 63 to 32. The project writes only the changed leaf; other policy parameters (separator, case) stay as bundled.
- **Define a new policy.** E.g., a `kafka_topic` policy for a project-specific naming convention. The project declares the policy under `naming_policies:` and references it from an engine's `naming:` field.

```yml
# infra/transfer_tables/naming_overrides.yml
naming_policies:
  # Override an existing policy.
  s3:
    max_len: 32

  # Define a new policy.
  kafka_topic:
    separator: hyphen
    case: lower
    max_len: 249
```

Both bundled-engine `naming: s3` references and project-engine `naming: kafka_topic` references resolve against the merged policy table.

### Adding a new engine to an existing role

When the project needs a different concrete implementation of a role the doctrine already models, declare the new engine under the role:

```yml
# infra/transfer_tables/redis_extra.yml
roles:
  cache:
    valkey:
      foundation: fixed
      naming: docker
      emits:
        fixed: [compose_service]
      defaults:
        fixed:
          image: valkey/valkey:8
      # ... other fields
```

The bundled `cache/redis` engine remains available; the project's `cache/valkey` is now also available. The project's `infra.yml` chooses one by name:

```yml
backing_services:
  appcache:
    role: cache
    engine: valkey  # or redis (bundled)
    version: "8"
```

### Adding a wholly new role

When the project needs a kind of service the doctrine doesn't model, declare both the role and at least one engine for it:

```yml
# infra/transfer_tables/telemetry.yml
roles:
  telemetry_collector:
    description: "OpenTelemetry-style sidecar collecting traces and metrics from peer services."
    otel:
      foundation: both
      naming: ecs
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service]
      defaults:
        fixed:
          image: otel/opentelemetry-collector-contrib:0.115.0
        elastic:
          image: otel/opentelemetry-collector-contrib:0.115.0
          cpu: "256"
          memory: "512"
      # ... full engine declaration
```

Engine declarations look identical regardless of whether the role is bundled or project-defined. The schema is the same; only the registration site differs.

### Worked example: stateless container backing

Goal: a `sidecar` role with an `nginx` engine, used by the project's `web` service to expose a downstream health endpoint. Two files: the transfer table, and the `infra.yml` snippet that consumes it.

**`infra/transfer_tables/sidecar.yml`:**

```yml
roles:
  sidecar:
    description: "Stateless auxiliary container — sidecar, health-probe, lightweight proxy."
    nginx:
      foundation: both
      default_port: 80
      naming: ecs
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service]
      defaults:
        fixed:
          image: nginx:1.27-alpine
        elastic:
          image: nginx:1.27-alpine
          cpu: "256"
          memory: "512"
      provides:
        host:
          fixed: "${global_service_name}"
          elastic: "${global_service_name}"
        port:
          fixed: "${port}"
          elastic: "${port}"
      env: {}
```

**Consumer in `infra.yml`:**

```yml
backing_services:
  probe:
    role: sidecar
    engine: nginx
    networks: [internal]

codebases:
  api:
    core_services:
      web:
        role: web
        port: 8080
        networks: [web, internal]
        uses: [probe, appdb]
        env:
          SIDECAR_HOST: ${backing_services.probe.host}
          SIDECAR_PORT: ${backing_services.probe.port}
          # ... other env
```

At runtime, `api.web` reads `SIDECAR_HOST=<project>-<env>-probe` and `SIDECAR_PORT=80`. On fixed, docker network DNS resolves the host. On elastic, ECS Service Connect resolves it through the env's namespace. No application code change crosses foundations.

### Worked example: stateful container backing

Goal: an `analytics_db` role with a `clickhouse` engine. Stateful — needs durable storage. Project opts into backups for the production data.

**`infra/transfer_tables/clickhouse.yml`:**

```yml
roles:
  analytics_db:
    description: "OLAP analytics database. Stateful — data directory persists across task restarts via EFS on elastic, named volume on fixed."
    clickhouse:
      foundation: both
      default_port: 9000
      naming: ecs
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service, efs_file_system]
      defaults:
        fixed:
          image: clickhouse/clickhouse-server:24.10
          volumes:
            - ${global_service_name}-data:/var/lib/clickhouse
        elastic:
          image: clickhouse/clickhouse-server:24.10
          cpu: "1024"
          memory: "4096"
      persistent_storage:
        mount_path: /var/lib/clickhouse
      fields:
        # Project opt-in for AWS Backup. Default disabled — only the
        # project knows whether the data is replaceable cache or
        # irreplaceable user state.
        backups:
          elastic:
            target: efs_file_system
            enabled: ${field_value}
      provides:
        host:
          fixed: "${global_service_name}"
          elastic: "${global_service_name}"
        port:
          fixed: "${port}"
          elastic: "${port}"
      env: {}
```

**Consumer in `infra.yml`:**

```yml
backing_services:
  events:
    role: analytics_db
    engine: clickhouse
    networks: [internal]
    backups: true   # opt in — this data is irreplaceable

codebases:
  api:
    core_services:
      web:
        role: web
        port: 8080
        networks: [web, internal]
        uses: [events, appdb]
        env:
          CLICKHOUSE_HOST: ${backing_services.events.host}
          CLICKHOUSE_PORT: ${backing_services.events.port}
          # ... other env
```

What the compiler emits on elastic for `events`:

- `aws_efs_file_system.events` (encrypted at rest).
- `aws_efs_backup_policy.events` (because `backups: true`).
- `aws_efs_mount_target.events` with `count = length(private_subnet_ids)`, attached to the `internal` SG.
- `aws_ecs_task_definition.events` with a `volume { name = "data" efs_volume_configuration { ... } }` block and a container `mountPoints` entry linking `"data"` → `/var/lib/clickhouse`.
- `aws_ecs_service.events` with `service_connect_configuration` registering the service as discoverable at `<project>-<env>-events`.

On fixed, the `defaults.fixed.volumes` entry creates a docker named volume mounted at `/var/lib/clickhouse`; ClickHouse's data survives `./bin/docex envinfra down dev` / `envinfra up dev` cycles. The compose stack runs ClickHouse as a regular container on the internal network.

Same `infra.yml`, same magic-ref values flowing into `api.web`'s env block, same application code on both foundations. The foundation-specific machinery — EFS on elastic, docker volumes on fixed — is doctrine-internal; the project just declares "stateful at /var/lib/clickhouse" and gets the right thing.

If the engine declares `persistent_storage` but the project forgets `backups`, the data is durable but not backed up; if the engine omits `efs_file_system` from `emits.elastic`, the loader fails at compile time with a clear bidirectional-validation error per [§ Failure-mode contract](#failure-mode-contract).

## Foundation Invariants

In addition to engine-specific config, the compiler applies a small set of foundation-wide invariants to every emitted resource. These are not engine-specific — they apply uniformly across every service in a compiled output.

### Per-container (fixed)

Every compose service receives — for a core service, once per [core service](../cicl.md#core-services):

```yml
container_name: ${global_service_name}
logging: *default-logging
restart: unless-stopped
networks: ${networks}
labels:
  - "docex.project=${project_name}"
```

The `docex.project` label is emitted on **every** container the compiler produces — core services, backing services, and OTel sidecars alike, not just `web` services. It scopes the per-project traefik's docker provider (which carries a matching `--providers.docker.constraints=Label(\`docex.project\`,…)`) to this project's own containers, so a project's traefik ignores other projects' containers sharing the host-wide `docex-ingress` bridge. See [projinfra/fixed_reverse_proxy.md § How Env-Tier Services Get Routed](./projinfra/fixed_reverse_proxy.md#how-env-tier-services-get-routed).

**Under a replica unroll the shape shifts, and only then.** When a core service
declares `replicas: N` and the count is in effect (`prod` only), the compiler
emits N services keyed `${global_service_name}-<i>`, each with its own
`container_name`, and rewrites `networks:` from compose's short-form list into
map form to carry a **shared alias** equal to the unqualified
`${global_service_name}` on every network. Docker DNS round-robins that alias
across the N containers, which is what keeps `provides.host` meaning the same
thing whether a core service has one replica or four. Outside that case there is
no `aliases` handling and the short-form list is emitted unchanged.

Additionally, services on the `web` network receive these Traefik discovery labels (appended to the `docex.project` label above):

```yml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.${global_service_name}.rule=${host_rule}"
  - "traefik.http.routers.${global_service_name}.entrypoints=websecure"
  - "traefik.http.routers.${global_service_name}.tls=true"
  - "traefik.http.routers.${global_service_name}.tls.certresolver=doctrine"
  - "traefik.http.services.${global_service_name}.loadbalancer.server.port=${port}"
```

**The traefik labels are keyed on the unqualified `${global_service_name}`, and
must stay that way.** Under a replica unroll, N containers therefore declare the
*same* router and the *same* service, and traefik's docker provider loads them as
N servers behind one router — which is how the reverse proxy load-balances a
`web` core service's replicas. Qualifying the labels per replica would instead
produce N routers fighting over one `Host()` rule.

`${host_rule}` is the per-core-service host rule derived from [cicl.md § Domain](../cicl.md#domain) — `Host(\`${codebase}-${service}.${env}.${project}.${apex_domain}\`)`, with the additional bare-env / bare-project rules for the `domain_default_service` in prod.

The literal resolver name `doctrine` is the prescribed handle for the project's traefik cert resolver — the per-project traefik (one per project, part of the project's compose stack) is configured with a resolver of that exact name, and docex emits labels referencing it. Decoupling the *name* (a doctrine handshake) from the *implementation* (currently Let's Encrypt + HTTP-01) lets the doctrine evolve the underlying mechanism without changing the handle. See [networks.md § networks: [web]](./networks.md#networks-web) for how the per-project traefik connects to the host-wide `docex-ingress` network and is reached by the HAProxy web demux.

### Per-core-service env (both foundations)

Every core service — regardless of foundation — additionally receives a set of doctrine-injected env vars:

| Variable | Value | Source |
| -------- | ----- | ------ |
| `PROJECT_VERSION` | The project's current version | `project.yml` `version:` field |
| `OTEL_SERVICE_NAME` | The core service's compiled identity, `<codebase>-<service>` | `infra.yml` `codebases.<cb>.core_services.<svc>` keys, hyphen-joined |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Doctrine-fixed. The paired OTel sidecar shares the core service's network namespace, so loopback addressing resolves to the sidecar identically on both foundations — see [telemetry_infra.md § Service Discovery (Fixed)](./telemetry_infra.md#service-discovery) and [§ Service Discovery (Elastic)](./telemetry_infra.md#service-discovery-1). |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Doctrine-fixed; matches the `otlp` receiver shape baked into the sidecar config — see [telemetry_infra.md § Pipeline Shape](./telemetry_infra.md#pipeline-shape). |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.namespace=${project_name},service.version=${project_version},deployment.environment.name=${env_name},docex.codebase=${codebase},docex.service=${service}` | Composed by the compiler from `project.yml` and `infra.yml`; drives backend-side filtering in the observability backend. The two `docex.*` attributes are the codebase / core-service axes made independently queryable — `service.name` fuses them with a hyphen and cannot be decomposed, since either segment may itself contain `-`. |

These variables are doctrine-injected, not project-declared — a project's `infra.yml` need not list them under `env:`, and listing them explicitly is redundant. The compiler emits each on every core service's environment block (compose `environment:` on fixed; ECS `environment[]` entry on elastic — not SSM secrets, since none of these values are sensitive).

`PROJECT_VERSION`'s name matches the env var [`./bin/docex stagetest` injects](../cicd.md#staging-tests) into the stage tester container. A service introspecting its own version (e.g. a `/health` endpoint that returns `{"version": "..."}`) reads from the same canonical handle a stage test compares against — so the assertion `body["version"] == os.environ["PROJECT_VERSION"]` is deterministic across the release boundary, not a manual sync.

The four `OTEL_*` variables are the OTel SDK's standard auto-discovery surface: any conformant SDK reads them from the environment at startup, so application code doesn't have to wire telemetry config explicitly. The full picture of how the sidecar, exporter, and backend fit together lives in [telemetry_infra.md](./telemetry_infra.md); this table is the canonical list of what the compiler emits onto the core service container itself.

**There are two identity forms, not one.** The table above describes the surface
a **core service**'s container receives. The compiler also emits two artifacts
that belong to the **codebase** rather than to any core service — the per-codebase
exec container and the elastic migration task definition — and those carry a
*de-qualified* identity:

| Key | core-service surface | per-codebase surface |
| --- | -------------------- | -------------------- |
| `OTEL_SERVICE_NAME` | `api-web` — the compiled identity | `api` — the **authoring** codebase name |
| `docex.codebase` | `api` | `api` |
| `docex.service` | `web` | *absent* |

The per-codebase value is the authoring name (`api`), deliberately **not** the
global name (`myproject-prod-api`): it matches the migrate container's `name` and
the CloudWatch log group, both codebase-keyed, exactly as the core-service surface
carries the compiled two-segment name rather than the global one.

**`docex.service`'s presence is the signal.** It is set if and only if the
emitter is a declared core service, so its absence identifies a per-codebase
artifact rather than a value someone forgot to fill in. Stamping the identity
before the surfaces split would give a migration the name of whichever core
service happened to sort first — an identity that moves when an unrelated core
service is renamed.

Backing services do not receive these env vars. They run third-party software with no application-side code that would consume `PROJECT_VERSION`, and the OTel SDK auto-instrumentation lives in core services' application code, not in backing-service images. Emitting any of these on a backing service would be inert.

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

Compose `depends_on` is emitted on **one block only** — the per-codebase exec service, whose gate is the union of the codebase's backing-targeted `uses` edges (see [migrations.md](./migrations.md#dev-and-test-mechanism)). No core-service block carries it. Where it is emitted it is always long-form (a map), never short-form. For each dependency, `condition` is `service_healthy` when the target service's emitted compose block contains a `healthcheck:`, otherwise `service_started`. Short-form only waits for the target container to start; backing services like postgres take measurable time to become reachable after starting, and a dependent service (or a `compose run` one-off from `./bin/docex envinfra up`) that connects too early hits a refused TCP socket. The healthcheck is already declared by the engine, so using it as the wait condition is the deterministic translation.

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
	managed_by = "doctrine"
	infra_tier = "environment"
	shape_name = "${shape_name}"   # core_service | backing_service
	descriptor = "${descriptor}"   # e.g. RDS, S3, ecs-svc, task-def
	project    = "${project_name}"
	env        = "${env_name}"
	codebase   = "${codebase_name}"
	service    = "${core_service_name}"  # core services only; key OMITTED otherwise
	role       = "${role_name}"
	Name       = "${project_name}_${env_name}_${codebase_name}_${core_service_name}"
}
```

This is the **envinfra** tag block. It is one of three tag blocks (preinfra, projinfra, envinfra) that together form the doctrine-wide tagging standard — see [`cicl.md § Naming and Tagging`](../cicl.md#naming-and-tagging) for the full standard and the pre-/projinfra blocks. `shape_name` is `core_service` or `backing_service` per the service's tier; `descriptor` differentiates the per-service resources (RDS/S3/ecs-svc/task-def/logs/EFS/…).

The `service` tag is present only on resources belonging to a core service. For a
backing service — and for the per-codebase migration resources — the key is
**omitted entirely** rather than emitted empty, so a reader can tell a
codebase-scoped resource from a core-service-scoped one by the key's presence rather
than by inspecting its value; `Name` then falls back to
`${project}_${env}_${codebase}`. Note the joiner here is `_`, not `-`: this is a
tag value, not a data-plane name.

(The `identifier` field shown above is doctrinal shorthand — different AWS resource types use different names for the field that holds the resource's primary name, e.g. RDS uses `identifier`, ECS uses `name`, S3 uses `bucket`. The compiler maps `${global_service_name}` to the appropriate field per resource type.)

## Resources Translation

The project's per-core-service [`resources:` block](../cicl.md#resources) is translated by the compiler into per-foundation resource fields. The translation is uniform across all core services regardless of role or engine — it does not appear in any individual engine's transfer-table entry, and engines do not declare cpu/memory defaults themselves.

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

For each core service, the compiler computes the Fargate task definition's `cpu` and `memory` in two steps:

1. **Compute the desired `(cpu, memory)`** by summing the service's `resources:` block and any doctrine-fixed sidecar overhead (currently the OTel sidecar's 0.1 vCPU / 128 MB allowance — see [telemetry_infra.md § Task-Level Resource Allocation](./telemetry_infra.md#task-level-resource-allocation)). The intermediate values are `cpu_desired = resources.cpu * 1024 + sidecar_cpu_units` and `memory_desired = resources.memory_mib + sidecar_memory_mib`.

2. **Round up to the smallest Fargate-supported tier** that meets or exceeds both dimensions. Fargate only supports a discrete table of `(vCPU, memory)` combinations (e.g., `0.25 vCPU` pairs with `0.5 / 1 / 2 GB`; `1 vCPU` pairs with `2 / 3 / 4 / 5 / 6 / 7 / 8 GB`; `2 vCPU` pairs with `4 / 5 / ... / 16 GB`; and so on). The compiler ships a hardcoded table of these combinations and looks up the next-up tier deterministically.

The emitted HCL is then:

```hcl
cpu              = "${tier.cpu}"               # Fargate vCPU units: 1024 = 1 vCPU
memory           = "${tier.memory}"            # MiB
ephemeral_storage {
	size_in_gib = ${resources.disk}            # only when resources.disk is set
}
```

**Tier rounding is uniform across all core services**, not just those where a sidecar pushes a boundary. A project declaring `cpu: 1.5, memory: 3GB` produces a `(cpu_desired = 1536, memory_desired = 3072)` that Fargate doesn't support, so the compiler rounds up to the next valid tier (e.g., `(2048, 4096)`). Sidecar overhead is one trigger; non-tier-aligned project values are another; both produce the same behavior.

The overhead is paid once **per task definition**, i.e. once per core service, so a codebase with three core services pays it three times and each rounds to its own tier independently.

**The compiler surfaces the rounding in compile output** so the cost implication is visible to the operator before apply. Projects sensitive to over-allocation can request slightly under a Fargate tier boundary so the sidecar (or other) overhead absorbs within the same tier.

Values that exceed the largest Fargate tier (currently 16 vCPU / 120 GB) fail compile with a descriptive error rather than silently capping to the max.

`resources.gpu` is rejected at validation time on elastic compiles — Fargate does not support GPU workloads. See [cicl.md § Resources](../cicl.md#resources) and [infrastructure.md § Deferred](../infrastructure.md#deferred).

### Defaults

`resources.cpu` and `resources.memory` have no defaults — they are required by CICL on every core service. `resources.disk` is optional with these foundation-specific behaviors when omitted:

- **Fixed:** no tmpfs is emitted; the container shares the host disk. The overlay layer remains unbounded regardless of whether `disk` is set (an overlay2 storage driver limitation).
- **Elastic:** `ephemeral_storage` is omitted from the task definition, accepting Fargate's default allotment (20 GiB; the explicitly-settable range starts at 21 GiB).

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
9. The `naming` policy resolved for each engine is satisfied by the `${global_service_name}` the compiler generates. A rendered name that exceeds the policy's `max_len` fails compile cleanly with a descriptive error, *unless* the policy sets `overflow: hash_truncate`, in which case the name is truncated with a deterministic hash suffix to fit (see [§ Naming Policies](#naming-policies)).
10. Every engine's `naming:` value is the name of a policy declared in `naming_policies:` (bundled or project-local). An unknown policy ref fails compile at load time.
11. Every engine declares a non-empty `emits.fixed` and `emits.elastic` list (the latter only required if the engine supports the elastic foundation). Every destination name in those lists is one the compiler recognizes; unknown destination names fail compile at load time.
12. Every `fields.<f>.<foundation>.target:` value (if set) names a destination in the engine's `emits.<foundation>` list. If the named destination is conditional (e.g., `target_group` requires the service to be on the `web` network) and the condition does not hold for the service being compiled, that is also a compile error — surfaced with a hint pointing at the missing condition.
13. Every `kind: minted` env var's `policy:` names a policy declared in `generation_policies:` (bundled or project-local); an unknown ref fails at load.
14. Every `kind: fixed` env var declares a `value:` (and no `policy:`); every `kind: minted` env var declares a `policy:` (and no `value:`).

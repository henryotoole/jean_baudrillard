---
stratum: conditional
---

# CICL

Overview of the *Clausewitzian Infrastructure Configuration Language* format and compiler.

Every project has an `infra.yml` file which describes the project's infrastructure resources in provider-agnostic language.

## The CICL Format

The CICL format defines the backing and core services that compose the [environment infrastructure](./infrastructure.md#infrastructure-tiers) on which the project code runs. It is really just YAML with a bunch of special keywords and a string interpolation feature. Every project gets one, and only one, CICL file: `infra.yml`. The file is broken into `codebases`, `backing_services`, and some toplevel config. `codebases` has one field per codebase, each of which declares its `core_services`; `backing_services` has one field per backing service. Then, every service has its own fields which define the service parameters.

CICL language defines infrastructure in *general, provider-agnostic* terms. For example, when describing an object storage service we will call it an `object_store` instead of `S3`. When describing an `object_store`'s configuration, we would say `versioning: true` instead of bothering with `aws_s3_bucket_versioning` resources. These represent the fundamental properties of the *role* of the service.

A deterministic compiler is responsible for translating these *general* terms into specific, provider-ready configuration as docker-compose config or OpenTofu HCL files. This compiler is [provided by the doctrine](#the-cicl-compiler). Naturally, such an abstract description of infrastructure is bound to leave out details. This is the whole point; infrastructure *design* should be as simple as possible with the details "filled in" deterministically.

To make these decisions, the compiler relies on CICL transfer tables and some doctrine-defined rules. More on these below.

The below yaml snippet is a non-exhaustive example of a CICL `infra.yml` file.
```yml

cicl_version: "2"
foundation: fixed # or "elastic". [More info](./infrastructure.md#foundation).
apex_domain: "example.com"
domain_default_service: api.web  # the web core service mapped to the bare <env>.<project>.<apex_domain>
container_registry: "registry.example.com"  # required for fixed; optional for elastic (defaults to project ECR)
repo_url: "https://github.com/owner_account/project_name"
observability_backend_url: "https://hyperdx.example.com"
# Defines reverse proxy choice. Elastic foundations only.
# reverse_proxy: alb # or ec2_traefik_eip or ec2_traefik_pip

codebases:

	# One codebase, one image, three core services.
	api:
		# Codebase-scoped fields sit at the codebase level.
		secrets:
			DISCORD_API_KEY: "Key to the discord bot used by the API."
		env:
			BUCKET_NAME:  ${backing_services.bucket.bucket_name}
			DATABASE_HOST: ${backing_services.database.host}
			DATABASE_PORT: ${backing_services.database.port}
			DATABASE_NAME: ${backing_services.database.db}
			DATABASE_USER: ${backing_services.database.user}
			DATABASE_PASSWORD: ${backing_services.database.password}
			DATABASE_SSLMODE: ${backing_services.database.sslmode}
		core_services:
			web:
				role: web
				command: ["python", "-m", "entrypoints.http"]
				port: 8080
				networks: [web, internal]
				health_check_path: /health
				resources:
					cpu: 1.0
					memory: 2GB
					disk: 20GB
				depends_on: [database, cache, bucket]
				consumes: [api.worker]
			worker:
				role: worker
				command: ["python", "-m", "entrypoints.worker"]
				port: 8080
				networks: [internal]
				health_check_path: /health
				replicas: 4
				resources:
					cpu: 2.0
					memory: 4GB
				depends_on: [cache, database]
				consumes: [api.web]
			nightly_cleanup:
				role: scheduler
				schedule: "0 3 * * *"
				command: ["python", "-m", "jobs.cleanup"]
				networks: [internal]
				resources:
					cpu: 0.25
					memory: 512MB
				depends_on: [database]

backing_services:

	database:
		role: relational_db
		engine: postgres
		version: "15"
		networks: [internal]
		schema_owned_by: api

	cache:
		role: cache
		engine: redis
		version: "7"
		networks: [internal]

	bucket:
		role: object_store
		port: 9000	# on the web network, so a routing port is required
		engine: [minio, s3]
		versioning: true	# A role-specific field.
		networks: [web, internal]
```

### Core Services

A **codebase** is a source tree and the single *build artifact* compiled from it. A **core service** is a named way of invoking that artifact: its own role, command, resources, networks, and port. One codebase, one image, N core services — a web edge, a queue consumer, and a nightly job can all be the same image started three different ways.

The codebase is the unit of *code*; the core service is the unit of *deployment*. Everything that is true of the source belongs to the codebase (e.g. the Dockerfile, `build.sh`, `migrate.sh`, the image, "never share code"). Everything that is true of a running container belongs to a core service (e.g. a port, a replica count, a health check, a routable address).

```yml
codebases:
	api:
		secrets: { ... }        # codebase-scoped
		config:  { ... }        # codebase-scoped
		env:     { ... }        # codebase-scoped, merged into every core service
		core_services:
			web:                # a core service
				role: web
				command: [...]
			worker:
				role: worker
				command: [...]
```

> **Naming**: A core service is generally named after its role, unless a codebase declares two on the same role. `role: web` → `web`; `role: worker` → `worker`; `role: scheduler` → the job's name (`nightly_cleanup`), since a codebase commonly has several jobs.

### Service Fields

The table below lists all standard fields for codebases and/or core services.

| Field Name | Required | Scope | Description |
| ---------- | -------- | ----- | ----------- |
| core_services | yes | codebase | The codebase's [core services](#core-services). Must be present and non-empty. |
| secrets | no | codebase | Bespoke, project-supplied secret env vars with no in-project source. Surfaced in the project's secrets file (`<env>.env`). See [configurable.md](./configurable.md#secrets). |
| config | no | codebase | Declared, non-secret, per-env config values (e.g. a URL that differs by environment). Keys are declared here; values live in the non-tracked, LLM-readable `infra/config/<env>.env`. See [configurable.md](./configurable.md#config). |
| env | no | codebase + core service | Contains fields which define infrastructure-driven environment variables for the container. Valid at the codebase level and on a core service; a core service's own block merges over the codebase's. |
| role | yes | core service, backing | What this core service or backing service *does* for the project e.g. 'web', 'worker', 'relational_db', 'cache'. |
| command | yes | core service | The command that launches this core service. Required on every core service; supersedes the Dockerfile `CMD`. |
| networks | yes | core service, backing | Lists the networks this core service or backing service will belong to. |
| resources | yes | core service | Computing resources the core service requires at runtime. See [Resources](#resources). |
| port | no | core service, backing | The port that the core service or backing service should be available on. |
| depends_on | no | core service, backing | Readiness gate. Names **backing services only**. See [Depends-On Relationships](#depends-on-relationships). |
| consumes | no | core service | Interface edges to other core services, dotted and fully qualified. See [Consumes Relationships](#consumes-relationships). |
| replicas | no | core service | The number of parallel containers to launch in production. Ignored in `dev`, `test`, and `stage`. Defaults to 1. Not permitted on a `scheduler` core service. |
| engine | yes | backing | The underlying software package the service will use e.g. 'postgres', 'redis', etc. Can define two options if `fixed` and `elastic` foundations require different engines. |
| version | yes | backing | The version of the engine to use. Format depends on engine. |
| schema_owned_by | sometimes | backing | Required for database roles (e.g. `relational_db`) to denote which codebase owns the database schema and drives migrations. Names a **codebase**, never a core service — `migrate.sh` runs once per codebase. |

Note that codebases do **not** declare an `image` field. Image references are derived deterministically by the compiler from the top-level [`container_registry`](#container-registry-and-service-images), the project name and version (from `project.yml`), and the codebase name. The image is keyed on the **codebase**, so every core service of a codebase runs the same image. See [Container Registry](#container-registry-and-service-images) for the full format.

The values for these fields can have "magic refs" like ${backing_services.object_store.bucket_name} which reference service [provided fields](#provided-fields) and are filled with the correct interpolated values when `infra.yml` is converted to docker-compose or OpenTofu config files.

Some services will have additional fields. These are role specific, and will be translated with the [transfer tables](#cicl-transfer-tables) during compilation.

`./bin/docex compile` will always fail loudly when a field is placed in the wrong scope, or if a required field is absent.

### Provided Fields

Every role may declare fields which are "provided" to other services. These tend to represent fundamental properties like `port` or `host`. They are defined per role in the `docex` transfer tables so that `docex` is careful and consistent when compiling `infra.yml`.

Restrictions with infra providers (particularly AWS SSM) mean that provided fields must be *values*, and can not be strings which are interpolated later. A role never exposes a pre-composed connection string. A consumer that needs a composed handle (e.g. a database url) builds it from the parts at startup. In the example above, `api` would need a database url to connect to the `database` backing service. We provide `DATABASE_HOST`, `DATABASE_PORT`, etc. as environmental variables so that the code within `api` can construct a database url at runtime. This produces an identical landscape across all four environments.

The provided fields for each role live in the `docex` transfer tables, not in this doctrine. To discover them, run `./bin/docex role <role>` — it lists the role's engines and their provided fields (which are secrets, the required env vars, and the role-specific fields). `./bin/docex roles` lists every available role. See [docex.md](./docex.md#role).

### Magic Refs

A magic ref reads a [provided field](#provided-fields) off another service. A core ref is a **literal path** into the document — every segment names a key the reader can walk in `infra.yml`, including the intermediate `core_services` collection. A backing ref has no such collection to traverse:

```
${codebases.<codebase>.core_services.<service>.<part>}   # five segments — api.web.host
${backing_services.<service>.<part>}                     # three segments — database.host
```

Refs are always **dotted**. Emitted names are hyphenated; see [Domain](#domain).

### Environmental Variables

Three fields define a container's environment variables, distinguished by *where the value comes from* and *how it is handled*:

- **`env:`** — values the compiler resolves at compile time: literals and magic refs to other services' provided parts.
- **`secrets:`** — bespoke secrets the operator supplies, never committed. Each declared key is delivered to the container as an env var of the same name, defined in `infra/secrets/<env>.env`.
- **`config:`** — non-secret, deployment-specific, per-env values (e.g. a third-party URL that differs by environment). Each declared key is delivered to the container the same way a secret is, differing only in that the value is non-secret. Defined in the non-tracked, LLM-readable `infra/config/<env>.env`. Config is the doctrine's escape valve for per-environment values that are neither compile-resolvable nor secret.

A given key may appear in **at most one** of `env:`, `secrets:`, and `config:` on a service. Across the whole project the three value *categories* are disjoint by key — an overlap is a compile error. See [configurable.md](./configurable.md) for the full model.

### Rules

We define some arbitrary but hard rules for these infra files in order to reduce complexity.

1. Service names are interpolated into a globally unique name when used as variables.
	+ For example, a core service needs a bucket name. This name will be interpolated from the object store backing service name, the environment name, and the project name.
2. Services communicate over URLs, and those URLs are built from provided fields (host, port, etc.) at startup.

### Naming and Tagging

Consistent naming and tagging conventions are employed wherever possible to ensure infrastructure is easy to identify.

#### Fixed Foundation

For `fixed`-foundation infrastructure resources, there are no tags. Naming standards are:
1. Docker networks: `${project_name}-${env_name}-${network_definition_name}`
2. Docker containers `${project}-${env}-${codebase}-${service}`

#### Elastic Foundation

In the elastic foundation, tags can be used and the naming / tagging convention is a little more developed:

preinfra_tags:
+ `managed_by`: "doctrine-operator"
+ `infra_tier`: "prerequisite"
+ `shape_name`: "${shape_name}"
+ `descriptor`: "*"
+ `Name`: "${shape_name}_${descriptor}"

projinfra_tags:
+ `managed_by`: "doctrine"
+ `infra_tier`: "project"
+ `shape_name`: "${shape_name}"
+ `descriptor`: "*"
+ `project`: "${project_name}"
+ `Name`: "${project}_${shape_name}_${descriptor}"

envinfra_tags:
+ `managed_by`: "doctrine"
+ `infra_tier`: "environment"
+ `shape_name`: "${shape_name}"
+ `descriptor`: "*"
+ `project`: "${project_name}"
+ `env`: "${env_name}"
+ `codebase`: "${codebase_name}"
+ `service`: "${core_service_name}"
+ `role`: "${role_name}"
+ `Name`: "${project}_${env}_${codebase}_${service}"

Notes on certain tags:
+ `shape_name` - The name from the [shape table](./shape.md#elastic-foundation) for elastic resources. If no shape name applies, set to `etc`.
+ `descriptor` - A looser descriptor for this resource. Use AWS abbreviations when possible e.g. ALB, IGW, etc. Not required, but useful for differentiating especially pre- and projinfra resources that belong to the same "shape name" from each other.
+ `codebase` - The codebase name. On a backing service this carries the backing service's own name, since a backing service has no codebase.
+ `service` - The core service name. Present on env-tier resources that belong to a specific core service; omitted for backing services, which have none.
+ `Name` - Redundant; present only for AWS console ergonomics.

These tags are not exclusive - some specific resources define their own tags which are load-bearing and used by `docex` machinery.

### Domain

The anatomy of a project's domain is rigidly defined and critical to the "just works" nature of CICL machinery. A full domain describes a specific core service uniquely across all projects. The form is:

`<codebase>-<service>.<env>.<project_name>.<apex_domain>` e.g. `api-web.dev.myproject.example.com`

Simply by assessing the domain of a request, any machinery with no further context can determine the destination project name, environment, and service. The `infra.yml` config `apex_domain` field sets the project's bare apex domain e.g. `example.com` or `example.co.uk`. Projects may or may not share apex domains with other projects.

Keep in mind, the domain structure is not the exclusive means of inter-service communication. Only `web`-network services are reachable from the outside; a domain pointing at a non-`web` service would not be routed there. There's also some variation by foundation - `elastic` backing services like S3 have their own endpoints provided by AWS whereas `fixed` backing services like `minio` require routing with the domain mechanism.

Unfortunately, combining the codebase and service into one label does mean that a domain can not be string-interpolated back out into the codebase and core service name. However, because the two are joined into one container of the same name, in practice we can always route requests to the right container by domain.

#### Bare Subdomains

There are a few "bare" subdomains possible with the above anatomy, listed in the table below. They require extra routing, as they do nothing by default.

| "Bare" Subdomain | Schema | Route |
| ---------------- | ------ | --- |
| Bare Env | `<env>.<project_name>.<apex_domain>` | Route to env's `domain_default_service`. |
| Bare Project | `<project_name>.<apex_domain>` | Route to prod's "bare env". |
| Bare Apex | `<apex_domain>` | Does nothing. |

The "bare project" domain is useful for user URL ergonomics - `<project_name>.<apex_domain>` simply reads as a clean way to access a project in a browser. Similarly, the "bare env" is nice for developers who wish to view the `dev` environment, perhaps via web interface, at `dev.<project_name>.<apex_domain>`. Note that these are routing choices, not redirects. A redirect would ruin the ergonomics.

#### TLS Implications

This complex and subdomain-heavy structure does have implications for SSL certificates.

TLS is only maintained for the `dev`, `stage`, and `prod` env-domains. The `test` env is not accessed via SSL in practice.

##### Elastic TLS

On `elastic` foundations, we use DNS-01. Wildcard certificates are available and the load is not too bad. The following covers all possible domains for a given project when DNS-01 is used. Note that we only include `stage` and `prod`, as `dev`/`test` are always fixed.

1. Stage Cert - Covers all domains for the `stage` environment.
	+ `*.stage.<project_name>.<apex_domain>`
	+ `stage.<project_name>.<apex_domain>`
2. Production Cert - Covers all domains needed for `prod`. Distinct cert from `stage` to keep production safely airgapped from development operations.
	+ `*.prod.<project_name>.<apex_domain>`
	+ `prod.<project_name>.<apex_domain>`
	+ `<project_name>.<apex_domain>`

##### Fixed TLS

On `fixed` foundations, DNS-01 is not available and HTTP-01 is used instead. We let traefik issue Let's Encrypt certs naturally per-host for each `web`-network service. This mechanism is far less cert-efficient (using one cert per `web`-network service per env), but works *simply* and *automatically*.

### Container Registry and Service Images

The `container_registry` top-level config option declares where codebase [build images](./shape.md) are pushed and pulled from. The compiler derives every image reference deterministically on the basis of environment:
- **`dev` / `test`** build each codebase's image **locally** from its Dockerfile (the compiled compose file carries a `build:` block) and never pull from a registry. The image is therefore a **registry-less local tag**:
	`${project_name}/${codebase_name}:${version}`.
- **`stage` / `prod`** reference an image that is pushed to and pulled from a registry, so the ref carries the full registry host:
	`${container_registry}/${project_name}/${codebase_name}:${version}`

with `project_name` and `version` from `project.yml` and `codebase_name` from the CICL key under `codebases`. Each codebase gets its own image; all images for a project share the project-wide version.

The image is keyed on the **codebase**, not the core service. A codebase declaring three [core services](#core-services) produces one image, which all three run with different [`command`](#core-services) values.

- **Fixed foundation:** `container_registry` is **required**. The doctrine does not provision a registry for fixed projects — it is [prerequisite infrastructure](./shape.md#fixed-foundation). Typical values are a self-hosted Docker Registry V2 URL or a public registry (Docker Hub, ghcr.io, etc.).
- **Elastic foundation:** `container_registry` is **optional**. When omitted, `stage`/`prod` images resolve to the project's auto-provisioned registry (ECR). The registry domain is deterministically interpolated by OpenTofu using provider (AWS) account ID, the `doctrine`-pinned region, and standard AWS form. When provided, `container_registry` explicitly overrides the ECR default such that an external registry can be used instead.

### Git Repo URL

The `repo_url` top-level field formally declares the project git repository's URL. The github repository name should be the same as the project name.

This field currently only serves a documentary role. The git host and repo are prerequisite infrastructure and not managed by the `docex` compiler.

### CICL Version

The top-level `cicl_version` field declares which generation of the CICL format `infra.yml` is written in. The current version is **`"2"`**.

Previous versions are **rejected**, not shimmed. A compatibility parser accepting both forms would reintroduce the flat, one-service-per-codebase shape that predates nesting core services under a codebase, as a permanent second code path, in exchange for serving a migration that every project performs exactly once. The compiler fails with a message naming the relevant project-upgrade guide.

### Observability Backend

The `observability_backend_url` top-level field declares the URL at which the project's observability backend is reachable. This is the destination that the OTel collector sidecars (paired with each core service) forward signals to in `stage` and `prod`. See [telemetry.md](./telemetry.md) for the full telemetry model. The URL propagates directly into each sidecar's environment as `OBSERVABILITY_BACKEND_URL`.

The URL must be HTTPS-scheme and well-formed. The compiler rejects `http://` and unparseable values at compile time. The compiler does not probe the URL for reachability; that is verified in the [check step](./cicd.md#check-step) e.g. `./bin/docex check`.

### Networks

The purpose of a network is to scope windows of access by service. Networks are interpreted from `infra.yml` on the basis of the `networks` field. Each service may belong to multiple networks. Every service must belong to at least one network. For example, a service declaring `networks: [web, internal]` is on both networks: reachable from the internet *and* from the internal service network.

Some networks will get special properties if they have a certain name. The full list is:
1. `web` - A network named web will be open to the broader internet via HTTP. Services on `web` can be accessed from the internet.

The default is for networks to be internal and closed, such that only services on the network get access to each other.

Network names are defined in `infra.yml` with simple names e.g. `web`, `internal`, etc. for developer convenience. However, in practice the compiler will create networks scoped by "simple name", project, and environment. A REST API service on the `web` network will be placed on a Docker network with a name something like `${project_name}-${env_name}-${network_definition_name}` (or a similar SG in `elastic`).

Network names in practice **always** use hyphens. If an input (like a project name) has an underscore it will be converted when the network name is formed.

Details on networks, how they are evaluated, and how they compile out can be found [here](./specifics/networks.md).

### Resources

The `resources:` field declares the computing resources a [core service](#core-services) requires at runtime. It is **required** on every core service — sizing is invocation-determined, so a web edge and a queue consumer of the same codebase size independently. Resources are described in provider-agnostic units; the compiler translates them per foundation. The full translation rules live in [transfer_tables.md § Resources Translation](./specifics/transfer_tables.md#resources-translation).

```yml
resources:
	cpu: 1.0          # required; vCPUs, fractional allowed (e.g., 0.5, 2)
	memory: 2GB       # required; RAM. Decimal units (MB, GB) only.
	disk: 20GB        # optional; ephemeral storage for temp files. Foundation-dependent default if omitted.
	gpu:              # optional; omit when no GPU is required
		count: 1      # number of GPUs to request
```

| Field | Fixed (compose) | Elastic (ECS Fargate) |
| ----- | --------------- | --------------------- |
| `cpu` | `deploy.resources.limits.cpus` | `cpu` in Fargate vCPU units (value × 1024) |
| `memory` | `deploy.resources.limits.memory` | `memory` in MiB |
| `disk` | tmpfs at `/tmp` sized to the requested value | `ephemeral_storage.size_in_gib` |
| `gpu.count` | `deploy.resources.reservations.devices` (NVIDIA) | **unsupported** — compile error |

**Notes:**
- Memory and disk accept `MB` and `GB` (decimal). Units are an authoring convenience, not an exactness contract.
- GPU support is v1-minimal: `count` only. Architecture or VRAM hints are deferred.
- **Elastic + GPU is not supported.** The doctrine commits to Fargate for elastic, and Fargate does not run GPU workloads. Listed under [infrastructure.md § Deferred](./infrastructure.md#deferred).
- The `disk` translation is asymmetric: on elastic, `ephemeral_storage` bounds the whole writable layer; on fixed, the compiler sizes a tmpfs at `/tmp` and the container's overlay layer remains unbounded (a limitation of the overlay2 storage driver). Apps that respect the [12-factor app](https://12factor.net/) ephemeral-storage principle write temp files to `/tmp` and are unaffected.
- Backing services do not take a `resources:` block in v1. Their sizing comes from the engine's defaults in the transfer table; projects needing different sizes use project-local transfer tables.
- **Fargate tier rounding (elastic only).** AWS Fargate supports only a discrete set of `(vCPU, memory)` combinations. The compiler rounds the requested `(cpu, memory)` (plus any doctrine-fixed sidecar overhead) up to the smallest supported Fargate tier that meets or exceeds both dimensions, and surfaces the rounding in compile output. Values that exceed the largest Fargate tier fail compile cleanly. The `resources:` block stays foundation-agnostic — the project author writes the sizing that makes sense; the compiler does the tier translation. See [transfer_tables.md § Resources Translation](./specifics/transfer_tables.md#resources-translation).
- Compile errors on this block name the full path, e.g. `codebases.api.core_services.worker.resources.disk`.

### Depends-On Relationships

`depends_on` is a **readiness gate**, and it names **backing services only**. It provides the DAG the compiler needs to bring infrastructure online in the right order: a core service that declares `depends_on: [database]` is not started until the database is healthy.

A core service may **not** appear in a `depends_on` list. Interface coupling between core services is a different relation with different rules, and lives in [`consumes`](#consumes-relationships).

Furthermore, if a core service references a backing service's information via [magic ref](#magic-refs), it depends on that backing service. If the relationship doesn't show up in the core service's `depends_on` field, the compiler will trip an error.

**`depends_on` is a convenience, never a correctness guarantee.** It is honoured on `fixed` foundations, where the compiler emits it as a compose `condition:`. On `elastic` it is discarded, because it *cannot* be honoured: ECS has no cross-service ordering primitive, and even a deploy-time emulation would hold exactly once and then be silently violated forever after, as ECS independently replaces tasks for scaling, AZ rebalance, failed health checks, and platform updates.

> **Startup ordering is not a substitute for connection resilience.**

Every service must tolerate its dependencies being absent at any moment — not only at startup — because on elastic they will be. Reconnect, back off, and fail requests cleanly; do not assume a dependency that was reachable a second ago still is.

#### Resilience covers reachability, not resolvability

The rule above answers *reachability*: a dependency that is down, restarting, or briefly unroutable. It does **not** answer a second failure mode that elastic adds, and which no amount of application-level retrying can escape.

ECS Service Connect fixes a client task's set of **resolvable endpoint names at task start**. An endpoint registered in the namespace *after* a client task started is not merely unreachable from that task — it is unresolvable, for the entire remaining life of the task. The name does not exist. Backing off and retrying never converges, because there is nothing to converge on.

So a core service created alongside a [`consumes`](#consumes-relationships) target it has never seen registered can be permanently unable to reach it, with both sides healthy. The externally visible symptom is a `503` on the [health fan-out](./contracts.md#fan-out); the invisible one is that every real call across that edge fails too.

**`docex` closes this at release time**, by redeploying any consumer whose `consumes` target registered during that release. Note carefully that this is *not* the deploy-time ordering emulation rejected above, and the distinction is what makes it sound: an endpoint **registration is durable state**, owned by the service rather than by task liveness, and it survives every task replacement. Holding once is therefore permanently sufficient — after the first registration, every later task (scaling, AZ rebalance, failed health check, platform update) starts into a namespace that already contains the name. A readiness gate decays because liveness changes; a registration does not.

Ordering could not have solved it in any case: a `consumes` graph may legally [contain cycles](#the-graph-may-contain-cycles), and in a cycle some member must be created first.

### Consumes Relationships

`consumes` is an **interface** edge between core services. Where `depends_on` says *"do not start me until this is up"*, `consumes` says *"I speak to this boundary"*.

```yml
codebases:
	api:
		core_services:
			web:
				consumes: [api.worker]
```

Targets are **dotted and fully qualified**. A bare codebase name is illegal, not shorthand for "all its core services": an interface edge points at a specific boundary, and a codebase does not have one contract.

`consumes` **emits nothing** — no compose key, no HCL resource. It is read by CI, by validation, and by the elastic release, where it does four jobs:

1. It declares the [provider / consumer](./infrastructure.md#contracts) relationships that determine which core services must carry a contract, and in which format.
2. It drives the health-check fan-out — see [contracts.md § Health Checks](./contracts.md#health-checks).
3. It satisfies [validation rule 7](#validation-rules) for magic refs whose target is a core service.
4. On elastic, it identifies which consumers must be redeployed after a release that registers a new Service Connect endpoint — see [§ Resilience covers reachability, not resolvability](#resilience-covers-reachability-not-resolvability).

Job 4 is a *release-time orchestration* read, not an emit: nothing derived from `consumes` reaches the compiled output. "Emits nothing" and "is read only by CI" are separate claims, and only the first is a rule — the emit-free property is worth pinning by test, whereas the set of readers may grow.

| | `depends_on` | `consumes` |
| --- | --- | --- |
| Names | backing services only | core services only |
| Job | readiness gate | contracts, health fan-out, rule 7, elastic consumer reconcile |
| Cycles | fatal | **legal** |
| Emitted | compose `condition:` on fixed; nothing on elastic | **nothing, on either foundation** |

#### The graph may contain cycles

This is why the two relations cannot merge. `api.web` enqueues a job; `api.worker` posts the result back to `api.web`'s internal API. So `web consumes api.worker` *and* `worker consumes api.web`. That is a cycle, it is the most common web/worker topology in existence, and it is entirely fine — interfaces may be mutually referential. A cycle in `depends_on`, by contrast, is a startup deadlock that compose refuses to start. There is one DAG (`depends_on`) and one cyclic digraph (`consumes`); no single field could carry a cycle rule that is simultaneously fatal and fine.

#### Three clarifications

- **One-directional: a ref implies an edge, never the reverse.** A magic ref to a core service obliges a matching `consumes` entry. A `consumes` entry does *not* oblige a magic ref — in the cycle above, `api.web` declares `consumes: [api.worker]` for the contract and the health fan-out but holds no ref to the worker, because it reaches it through the broker.
- **Same-codebase is not exempt.** `api.worker` referencing `${codebases.api.core_services.web.host}` still declares `consumes: [api.web]`. Sharing source does not make it not a boundary.
- **A codebase-level `env:` ref obliges every core service** to declare the edge, consistent with how `depends_on` is treated. If every core service receives `WEB_HOST`, every core service talks to `api.web`.

### Reverse Proxy

Elastic foundations have two options for the reverse proxy resource - ALB for projects which require robust availability and ingress and an EC2 traefik instance for those which don't. ALBs cost substantially more than an EC2 instance doing the equivalent task. The EC2 instance can be backed with a regular Public IP or an Elastic IP. Public IPs will inevitably lead to some downtime if they change, but an infinite number of them are available, so both options are available.


This selection is defined with the `reverse_proxy` field. It can be:
1. `alb` - An ALB will be used.
2. `ec2_traefik_eip` - The EC2 instance with traefik will be used and backed with an Elastic IP.
3. `ec2_traefik_pip` - Same as `ec2_traefik_eip`, except a Public IP is used instead.

## The CICL Compiler

The compiler translates `infra.yml` into docker-compose config or OpenTofu HCL.

The compiler is bundled into `docex` as a command e.g. `./bin/docex compile`.

### Simplifications

In order to simplify down the massive complexities of infrastructure, we make some simplifications:
1. `elastic` foundations only use AWS as a provider and only use one region: "us-east-1".
2. `elastic` foundations use "us-east-1a" as the primary AZ. We sometimes include a second AZ if required by AWS (e.g. for ALBs), but we avoid placing service containers in it [in practice](./reasoning/ingress_and_egress.md#elastic-azs).

### Shape Assumption and Declaration

The [shape](./shape.md) of the infrastructure surrounding a project covers all three [tiers](./infrastructure.md#infrastructure-tiers) of infrastructure. The compiler treats each a little differently:

| Tier | Described by `infra.yml` | Described by compiler output |
| ---- | ------------------------ | ---------------------------- |
| Prerequisite | No | No |
| Project | Partially | Yes |
| Environment | Yes | Yes |

Limiting prerequisite and project infrastructure exposure in `infra.yml` succeeds in the doctrine's goal of reducing as much as possible to "one canonical method" - it keeps infrastructure design simple. However, those results should still be *discoverable* by the developer both for understanding and debugging. For this reason, `docex` provides the [describe](./docex.md#describe) command.

Furthermore, the compiler documents all its derived infrastructure configuration in the output files to this end.

### CICL Transfer Tables

In order to translate provider-agnostic CICL definitions into the specifics needed to actually construct or provision infrastructure, the compiler requires 'transfer tables'. These concretely define how we will actually implement different infrastructure roles.

For example, many software projects need object storage. The transfer tables will define `object_store` as a role and list the engines that are available for each foundation e.g. 'minio' for `fixed` and 'S3' for `elastic`. Each engine-foundation combination will contain detailed instructions on how to configure that combination with the relevant tools. These instructions are what allow automatic translation from something like `versioning: true` to `aws_s3_bucket_versioning` resource configuration.

These tables are formatted in plain YAML. The `doctrine` maintains transfer tables which ought to cover most cases. To provide flexibility, projects can also provide their own project-specific transfer tables in the `infra/transfer_tables` folder. These will be deep merged with the `doctrine` ones when the compiler runs. However, **care should be taken** when choosing design that calls upon this additional complexity. Most projects won't need it.

When adding project-specific transfer tables, always load the `infra-compile` skill.

### Compiler Output

All compiler output lives under `infra/output/`. Output is git-tracked: diffs on output files show what an `infra.yml` change actually produces, and reviewers can see the full infrastructure impact of a change in a PR. The output is organized first by tier (project vs. env) and then by side (for project tier) or env name (for env tier).

**Env-tier output** (one subdirectory per environment).

For **fixed envs** (`dev`, `test`, and `stage`/`prod` when foundation is fixed):

```
infra/output/<env>/
	docker-compose.yml        # always
	playbook.yml              # stage/prod only
	inventory.yml             # stage/prod only (derived from `apex_domain`)
	ansible.cfg               # stage/prod only
```

For `dev` and `test`, just the compose file — those envs run locally and don't need an Ansible playbook. `./bin/docex envinfra up dev` and `./bin/docex envinfra up test` invoke `docker compose -f infra/output/<env>/docker-compose.yml up` under the hood.

For **elastic envs** (`stage` and `prod` when foundation is elastic):

```
infra/output/<env>/
	main.tf
```

A single env `main.tf` contains the env-tier resources: provider config, state backend reference, networks (security groups), ECS, backing services, env-specific DNS records, and the reverse-proxy routing wiring — ALB listener rules + target groups on the `alb` path, or `traefik.*` `dockerLabels` on each `web`-service's task definition on the `ec2_traefik_*` path (discovered by the instance's traefik ECS provider). OpenTofu does not require splitting, and a single file is simpler to read and review. Each env reads project-tier outputs (zone, certs, ALB/EC2-traefik ARNs, ECR repos, task-execution role) via `data "terraform_remote_state" "project"`.

**Project-tier output** (one subdirectory per side). Project-tier resources are sided per [`projinfra/projinfra.md`](./specifics/projinfra/projinfra.md), so output is split too:

```
infra/output/project/
	development/
		docker-compose.yml    # 4 -web networks + project traefik; always emitted
	production/
		docker-compose.yml    # fixed-foundation only: 4 -web networks + project traefik
		playbook.yml          # fixed-foundation only when prod side is a remote host
		inventory.yml         # fixed-foundation only when prod side is a remote host
		ansible.cfg           # fixed-foundation only when prod side is a remote host
		main.tf               # elastic-foundation only: Route53 zone, ACM certs, ALB or EC2-traefik, ECR repos, task-execution role
```

The development side is always fixed-style (docker-compose) regardless of project foundation, because `dev`/`test` always run as docker stacks. The production side mirrors that for fixed projects; for elastic projects it switches to HCL. Both sides are applied via `./bin/docex projinfra <direction> <side>`.

The project-tier elastic HCL uses a distinct state key (`key = "project/terraform.tfstate"`) in the project's S3 state backend. See [`projinfra/elastic_state_backend.md`](./specifics/projinfra/elastic_state_backend.md).

### Validation Rules
The following rules apply to whether or not an `infra.yml` file is valid.

1. All required fields must be present on relevant services.
2. All roles must either be defined in the standard transfer tables or the project-local ones.
3. All "magic refs" must resolve.
4. Engines must be known and engines must match foundation (e.g. minio for `fixed` foundation, S3 for `elastic`).
5. The rendered data-plane identity of every emitted service must be unique after naming-policy normalization. The set spans core services, backing services, **and the derivatives the compiler appends to them** — `-otelcol` (the paired collector sidecar), `-scheduler` (the Ofelia trigger), `-exec` (the per-codebase operations container), `-migrate` (the migration task definition), and `-1`…`-N` (the replica index, on a core service declaring `replicas: N`) — since all of them render into the same namespace. So a core service named `exec` on codebase `api` is an error: it renders `api-exec`, which is byte-identical to the exec container the compiler emits for the `api` codebase, and the two would silently share one compose key. Likewise a codebase `api` declaring core services `web` with `replicas: 3` and `web-1` is an error: replica 1 of `web` renders `api-web-1`, byte-identical to the `web-1` core service's own compiled identity. The rule is keyed on **collision, not on a list of forbidden names**, which is what makes it cover every suffix the compiler learns in future without a further edit, and what keeps a name that collides with nothing from being forbidden for its own sake.
6. Cyclic dependency chains with `depends_on` are not allowed. (Cycles in `consumes` **are** allowed — see [Consumes Relationships](#consumes-relationships).)
7. Magic refs which imply a dependency must be matched by a corresponding edge, of the kind the target calls for: a ref to a **backing service** must be matched by a `depends_on` entry on the referencing core service; a ref to a **core service** must be matched by a `consumes` entry. This rule governs **core-service referencers**, since a core service is the only thing that can hold either edge. A backing service that embeds a core service's part — an `object_store` holding `${codebases.api.core_services.web.host}` as a CORS origin, say — cannot satisfy it at all: backing services have no `consumes:`, and rule 24 forbids them a `depends_on` to a core service. That is rule 7 correctly **not applying** rather than a gap, because a backing service embedding a core hostname is not *calling* it, so there is no readiness or interface implication for either relation to express. See [Consumes Relationships](#consumes-relationships) for the one-directional, same-codebase, and codebase-level-`env:` clarifications.
8. Database roles (e.g. `relational_db`) all specify a valid `schema_owned_by` codebase.
9. `container_registry` is set when `foundation: fixed`. Omission is permitted under elastic, where it defaults to the project's auto-provisioned ECR.
10. Every core service has a `resources:` block declaring at least `cpu` and `memory`.
11. `resources.gpu` is not declared when `foundation: elastic` — GPU workloads are not supported on Fargate.
12. `domain_default_service`, if set, names a core service that is on the `web` network.
13. `apex_domain` must be a bare apex domain without subdomains.
14. Neither codebase names nor core service names can be one of the following: [`dev`, `test`, `stage`, `prod`, `www`], because it makes domain parsing challenging and because a core service named `prod` renders `api-prod.dev.myproject.example.com`, which reads as a production host in a dev environment.
15. Every `web`-network **core service** declares a `port`.
16. A core service's *effective* `env:` (codebase-level merged under core-service-level) does not declare a key that also appears in the codebase's `secrets:` or `config:`.
17. Every engine's `naming:` value in a transfer table is the name of a policy declared in `naming_policies:` (see [transfer_tables.md § Naming Policies](./specifics/transfer_tables.md#naming-policies)).
18. `reverse_proxy` can only appear on `foundation: elastic` projects.
19. Every key a core service consumes from `config:` is declared in its codebase's `config:` block; config values live in the non-tracked `infra/config/<env>.env`. See [config_and_secrets.md](./specifics/config_and_secrets.md).
20. The three env-value categories — engine-minted (transfer-table `kind: minted`), secret (codebase `secrets:` + doctrine-injected), and config (codebase `config:`) — are disjoint across the whole project by source key. A key claimed by more than one category is a compile error, and doctrine-injected keys (e.g. `TELEMETRY_API_KEY`) are reserved and may not be redeclared in any category.
21. `cicl_version` is `"2"`. Earlier generations of the format are rejected, not translated.
22. Every codebase declares a non-empty `core_services:` block, and declares nothing at the codebase level outside `{core_services, secrets, config, env}`.
23. Every core service declares a `command`.
24. `depends_on` names only backing services. A core service in a `depends_on` list is an error.
25. `consumes` names only core services, fully qualified as `<codebase>.<service>`. A bare codebase name is an error, and a core service may not consume itself. A `scheduler` core service may not be a `consumes` target: cron invokes it and nobody else does, so it exposes no boundary to consume and is exempt from the health fan-out that `consumes` drives.
26. `replicas` is not declared on a `scheduler` core service.
27. `worker` and `scheduler` core services do not declare `web` in `networks`.
28. Every core service that declares `health_check_path` also declares a `port`. The path is only meaningful against a port — the probe is issued at `http://localhost:<port><path>` — and no role fixes a default health port, deliberately: an implicit one would silently oblige the application to bind it. Without this rule the omission emits a malformed probe and surfaces as a container that never becomes healthy, rather than as a compile error.
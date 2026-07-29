---
stratum: conditional
---

# CICL

Overview of the *Clausewitzian Infrastructure Configuration Language* format and compiler.

Every project has an `infra.yml` file which describes the project's infrastructure resources in provider-agnostic language.

## The CICL Format

The CICL format defines the backing and core services that compose the [environment infrastructure](./infrastructure.md#infrastructure-tiers) on which the project code runs. It is really just YAML with a bunch of special keywords and a string interpolation feature. Every project gets one, and only one, CICL file: `infra.yml`. The file is broken into `core_services`, `backing_services`, and some toplevel config. Each of those has one field per service, the name of which is the name of the service. Then, every service has its own fields which define the service parameters.

CICL language defines infrastructure in *general, provider-agnostic* terms. For example, when describing an object storage service we will call it an `object_store` instead of `S3`. When describing an `object_store`'s configuration, we would say `versioning: true` instead of bothering with `aws_s3_bucket_versioning` resources. These represent the fundamental properties of the *role* of the service.

A deterministic compiler is responsible for translating these *general* terms into specific, provider-ready configuration as docker-compose config or OpenTofu HCL files. This compiler is [provided by the doctrine](#the-cicl-compiler). Naturally, such an abstract description of infrastructure is bound to leave out details. This is the whole point; infrastructure *design* should be as simple as possible with the details "filled in" deterministically.

To make these decisions, the compiler relies on CICL transfer tables and some doctrine-defined rules. More on these below.

The below yaml snippet is a non-exhaustive example of a CICL `infra.yml` file.
```yml

cicl_version: "2"
foundation: fixed # or "elastic". [More info](./infrastructure.md#foundation).
apex_domain: "example.com"
domain_default_process: api.web  # the web process type mapped to the bare <env>.<project>.<apex_domain>
container_registry: "registry.example.com"  # required for fixed; optional for elastic (defaults to project ECR)
repo_url: "https://github.com/owner_account/project_name"
observability_backend_url: "https://hyperdx.example.com"
# Defines reverse proxy choice. Elastic foundations only.
# reverse_proxy: alb # or ec2_traefik_eip or ec2_traefik_pip

core_services:

	# One codebase, one image, three process types.
	api:
		# Codebase-scoped fields sit at the service level.
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
		processes:
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

Two things in that example are worth naming. `api.web` and `api.worker` each `consumes` the other — a legal cycle, and the most common web/worker topology there is; see [Consumes Relationships](#consumes-relationships). And the `worker` process type's broker is the `cache` backing service: the doctrine ships no dedicated `queue` role, so a redis broker is declared under the `cache` role. `depends_on` names only backing services, which is why the worker's dependency on `api.web` appears under `consumes` and not there.

### Process Types

A core service is a *codebase* and the single *build artifact* compiled from it. A **process type** is a named way of invoking that artifact: its own role, command, resources, networks, and port. One codebase, one image, N process types — a web edge, a queue consumer, and a nightly job can all be the same image started three different ways.

The `processes:` block is **required** on every core service and must be non-empty. There is no flat form and no single-process shorthand. That costs a few lines on a service that really does have one process type, and buys a great deal: every emitted identity is unconditionally two-segment, so the collapse logic that a shorthand would demand — at the emitted name, the hostname, the contract path, the health path, `OTEL_SERVICE_NAME`, and every tag — lives in zero places rather than in all of them.

```yml
core_services:
	api:
		secrets: { ... }        # codebase-scoped
		config:  { ... }        # codebase-scoped
		env:     { ... }        # codebase-scoped, merged into every process type
		processes:
			web:                # a process type
				role: web
				command: [...]
			worker:
				role: worker
				command: [...]
```

#### Field scoping

One principle generates the whole split, including for fields not yet invented:

> A field belongs to the **codebase** iff its value is determined by the source code. It belongs to the **process type** iff its value is determined by the invocation.

| Codebase-scoped (on the core service) | Process-type-scoped |
| ------------------------------------- | ------------------- |
| `processes:` | `role`, `command` |
| `secrets:`, `config:` | `resources`, `replicas` |
| migration ownership (`migrate.sh` runs once per codebase) | `networks`, `port` |
| `env:` (shared) | `depends_on`, `consumes` |
| | `env:` (merges over service-level) |
| | every role-specific field (`health_check_path`, `schedule`, …) |

Applying it: the *code* is what reads `STRIPE_API_KEY`, so `secrets:` is codebase-scoped. `migrations/` lives in the source tree, so migration ownership is too. **Role-specific fields follow `role`**, which is invocation-determined, so they are process-scoped by derivation — the table never needs revisiting when a role gains a field.

`env:` is the one field that straddles the principle, because some variables are code-determined (`DATABASE_HOST` — the code needs a database) and some are invocation-determined (a worker's concurrency knob). It is therefore valid at **both** levels, and a process type's effective environment is the service-level block merged under its own, process-level winning on a key collision. It is the only such exception, and it exists because the principle genuinely lands on both sides rather than as an oddity.

**The service level accepts only `{processes, secrets, config, env}`.** Anything else is a hard error. A stray `resources:` at the service level is almost always a mis-nested process-type field, and failing loudly beats silently doing nothing.

**`command` is required on every process type, including `web`.** With several process types sharing one image, at most one could inherit the Dockerfile `CMD`, and "which one" is an ambiguity worth deleting rather than answering. Requiring it universally is self-documenting and makes the Dockerfile `CMD` irrelevant for core services.

#### Naming convention

Not a hard rule, but a documented convention — unspecified naming drifts across projects (`api.web` / `api.api` / `api.main` / `api.server`) and cross-project familiarity is a stated goal of this doctrine.

> **A process type is named after its role**, unless a codebase declares two process types on the same role. `role: web` → `web`; `role: worker` → `worker`; `role: scheduler` → the job's name (`nightly_cleanup`), since a codebase commonly has several jobs.

A project that genuinely needs two HTTP boundaries names them by boundary — `api.public`, `api.admin` — and deviates deliberately.

### Service Fields

The table below lists all standard fields for services.

| Field Name | Required | Scope | Description |
| ---------- | -------- | ----- | ----------- |
| processes | yes | core (service) | The core service's [process types](#process-types). Must be present and non-empty. |
| secrets | no | core (service) | Bespoke, project-supplied secret env vars with no in-project source. Surfaced in the project's secrets file (`<env>.env`). See [configurable.md](./configurable.md#secrets). |
| config | no | core (service) | Declared, non-secret, per-env config values (e.g. a URL that differs by environment). Keys are declared here; values live in the non-tracked, LLM-readable `infra/config/<env>.env`. See [configurable.md](./configurable.md#config). |
| env | no | core (both levels) | Contains fields which define infrastructure-driven environment variables for the container. Valid at the service level and on a process type; a process type's own block merges over the service's. |
| role | yes | core (process type), backing | What this process type or backing service *does* for the project e.g. 'web', 'worker', 'relational_db', 'cache'. |
| command | yes | core (process type) | The command that launches this process type. Required on every process type; supersedes the Dockerfile `CMD`. |
| networks | yes | core (process type), backing | Lists the networks this process type or backing service will belong to. |
| resources | yes | core (process type) | Computing resources the process type requires at runtime. See [Resources](#resources). |
| port | no | core (process type), backing | The port that the process type or backing service should be available on. |
| depends_on | no | core (process type), backing | Readiness gate. Names **backing services only**. See [Depends-On Relationships](#depends-on-relationships). |
| consumes | no | core (process type) | Interface edges to other core process types, dotted and fully qualified. See [Consumes Relationships](#consumes-relationships). |
| replicas | no | core (process type) | The number of parallel containers to launch in production. Ignored in `dev`, `test`, and `stage`. Defaults to 1. Not permitted on a `scheduler` process type. |
| engine | yes | backing | The underlying software package the service will use e.g. 'postgres', 'redis', etc. Can define two options if `fixed` and `elastic` foundations require different engines. |
| version | yes | backing | The version of the engine to use. Format depends on engine. |
| schema_owned_by | sometimes | backing | Required for database roles (e.g. `relational_db`) to denote which core service owns the database schema and drives migrations. Names a **core service** (a codebase), never a process type — `migrate.sh` runs once per codebase. |

Note that core services do **not** declare an `image` field. Image references are derived deterministically by the compiler from the top-level [`container_registry`](#container-registry-and-service-images), the project name and version (from `project.yml`), and the core service name. The image is keyed on the **codebase**, so every process type of a core service runs the same image. See [Container Registry](#container-registry-and-service-images) for the full format.

The values for these fields can have "magic refs" like ${backing_services.object_store.bucket_name} which reference service [provided fields](#provided-fields) and are filled with the correct interpolated values when `infra.yml` is converted to docker-compose or OpenTofu config files.

Some services will have additional fields. These are role specific, and will be translated with the [transfer tables](#cicl-transfer-tables) during compilation.

### Provided Fields

Every role may declare fields which are "provided" to other services. These tend to represent fundamental properties like `port` or `host`. They are defined per role in the `docex` transfer tables so that `docex` is careful and consistent when compiling `infra.yml`.

Restrictions with infra providers (particularly AWS SSM) mean that provided fields must be *values*, and can not be strings which are interpolated later. A role never exposes a pre-composed connection string. A consumer that needs a composed handle (e.g. a database url) builds it from the parts at startup. In the example above, `api` would need a database url to connect to the `database` backing service. We provide `DATABASE_HOST`, `DATABASE_PORT`, etc. as environmental variables so that the code within `api` can construct a database url at runtime. This produces an identical landscape across all four environments.

The provided fields for each role live in the `docex` transfer tables, not in this doctrine. To discover them, run `./bin/docex role <role>` — it lists the role's engines and their provided fields (which are secrets, the required env vars, and the role-specific fields). `./bin/docex roles` lists every available role. See [docex.md](./docex.md#role).

### Magic Refs

A magic ref reads a [provided field](#provided-fields) off another service. Refs to core services carry the process dimension; refs to backing services do not:

```
${core_services.<service>.<process>.<part>}     # four segments — api.web.host
${backing_services.<service>.<part>}            # three segments — database.host
```

The asymmetry is honest rather than accidental: a backing service has no process types, so there is nothing to qualify. A **bare** core service name is illegal rather than shorthand — a codebase has no single boundary, so `${core_services.api.host}` has no answer.

Refs are always **dotted**. Emitted names are hyphenated; see [Domain](#domain).

A process type may not reference **itself**. Beyond being degenerate, `provides.host` is the *internal* discovery name, so the one plausible motive — building an absolute URL to oneself — would not return what the author expects. Use `localhost`.

A magic ref implies a declared edge, and which edge depends on the target's kind — see [validation rule 7](#validation-rules).

### Environmental Variables

Three fields define a core service's container environment variables, distinguished by *where the value comes from* and *how it is handled*:

- **`env:`** — values the compiler resolves at compile time: literals and magic refs to other services' provided parts.
- **`secrets:`** — bespoke secrets the operator supplies, never committed. Each declared key is delivered to the container as an env var of the same name, defined in `infra/secrets/<env>.env`.
- **`config:`** — non-secret, deployment-specific, per-env values (e.g. a third-party URL that differs by environment). Each declared key is delivered to the container the same way a secret is, differing only in that the value is non-secret. Defined in the non-tracked, LLM-readable `infra/config/<env>.env`. Config is the doctrine's escape valve for per-environment values that are neither compile-resolvable nor secret.

A given key may appear in **at most one** of `env:`, `secrets:`, and `config:` on a service. Across the whole project the three value *categories* are disjoint by key — an overlap is a compile error. See [configurable.md](./configurable.md) for the full model.

Of the three, only `env:` is valid at both the core service and the process type level; `secrets:` and `config:` are codebase-scoped and declared once on the service. A process type's effective environment is the service-level `env:` merged under its own, and the disjointness rule above is evaluated against that effective set. See [Process Types § Field scoping](#field-scoping).

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
2. Docker containers `${project}-${env}-${service}-${process}`

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
+ `service`: "${core_service_name}"
+ `process`: "${process_name}"
+ `role`: "${role_name}"
+ `Name`: "${project}_${env}_${service}_${process}"

Notes on certain tags:
+ `shape_name` - The name from the [shape table](./shape.md#elastic-foundation) for elastic resources. If no shape name applies, set to `etc`.
+ `descriptor` - A looser descriptor for this resource. Use AWS abbreviations when possible e.g. ALB, IGW, etc. Not required, but useful for differentiating especially pre- and projinfra resources that belong to the same "shape name" from each other.
+ `process` - The process type name. Present on env-tier resources that belong to a specific core service process type; omitted for backing services, which have none.
+ `Name` - Redundant; present only for AWS console ergonomics.

These tags are not exclusive - some specific resources define their own tags which are load-bearing and used by `docex` machinery.

### Domain

The anatomy of a project's domain is rigidly defined and critical to the "just works" nature of CICL machinery. A full domain describes a specific process type uniquely across all projects. The form is:

`<service>-<process>.<env>.<project_name>.<apex_domain>` e.g. `api-web.dev.myproject.example.com`

Simply by assessing the domain of a request, any machinery with no further context can determine the destination project name, environment, and service. The `infra.yml` config `apex_domain` field sets the project's bare apex domain e.g. `example.com` or `example.co.uk`. Projects may or may not share apex domains with other projects.

Keep in mind, the domain structure is not the exclusive means of inter-service communication. Only `web`-network services are reachable from the outside; a domain pointing at a non-`web` service would not be routed there. There's also some variation by foundation - `elastic` backing services like S3 have their own endpoints provided by AWS whereas `fixed` backing services like `minio` require routing with the domain mechanism.

#### The service label is single and hyphen-joined

The process type occupies the *same* label as the core service, joined by a hyphen — `api-web.dev.…`, never `web.api.dev.…`. Three independent reasons, any one of which is decisive:

1. **TLS wildcards cover exactly one label.** The elastic certs are `*.stage.<project>.<apex>`; a `web.api.stage.…` host sits two labels deep and is uncovered, and multi-level wildcards are not valid in TLS, so no cert could cover it.
2. **The domain parse is positional.** The promise above — that machinery with no further context can determine project and environment — holds because the anatomy has a fixed number of parts.
3. The [bare-env and bare-project routes](#bare-subdomains) are defined relative to that four-part form.

**Nothing ever reverse-parses the label back into `(service, process)`.** This is worth stating, because `api-web` looks ambiguous — it could be service `api` + process `web`, or a service literally named `api-web`. Nothing cares. The master network's demux parses the domain *right-anchored* (public suffix, then apex, then the project label immediately left of it) and has no opinion about how many labels sit further left; traefik and the ALB match whole host strings that the compiler generated. The label is a rendered output, never an input to be decomposed. What the ambiguity *does* require is that rendered identities be unique — see [validation rule 5](#validation-rules).

#### Dots for reference, hyphens for emission

One rule covers the whole system. Authoring and reference forms are **dotted**: `consumes:` targets, `domain_default_process`, [magic refs](#magic-refs), and `describe` node ids. Emitted data-plane names are **hyphenated**: container names, security groups, hostnames, log streams, and traefik router keys.

#### Bare Subdomains

There are a few "bare" subdomains possible with the above anatomy, listed in the table below. They require extra routing, as they do nothing by default.

| "Bare" Subdomain | Schema | Route |
| ---------------- | ------ | --- |
| Bare Env | `<env>.<project_name>.<apex_domain>` | Route to env's `domain_default_process`. |
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

The `container_registry` top-level config option declares where core service [build images](./shape.md) are pushed and pulled from. The compiler derives every image reference deterministically on the basis of environment:
- **`dev` / `test`** build each core service's image **locally** from its Dockerfile (the compiled compose file carries a `build:` block) and never pull from a registry. The image is therefore a **registry-less local tag**:
	`${project_name}/${service_name}:${version}`.
- **`stage` / `prod`** reference an image that is pushed to and pulled from a registry, so the ref carries the full registry host:
	`${container_registry}/${project_name}/${service_name}:${version}`

with `name` and `version` from `project.yml` and `service_name` from the CICL key under `core_services`. Each core service gets its own image; all images for a project share the project-wide version.

The image is keyed on the **codebase**, not the process type. A core service declaring three [process types](#process-types) produces one image, which all three run with different [`command`](#process-types) values. This is the joint the doctrine holds at 1:1 — one codebase, one build artifact — while the artifact-to-process-type joint is 1:N.

- **Fixed foundation:** `container_registry` is **required**. The doctrine does not provision a registry for fixed projects — it is [prerequisite infrastructure](./shape.md#fixed-foundation). Typical values are a self-hosted Docker Registry V2 URL or a public registry (Docker Hub, ghcr.io, etc.).
- **Elastic foundation:** `container_registry` is **optional**. When omitted, `stage`/`prod` images resolve to the project's auto-provisioned registry (ECR). The registry domain is deterministically interpolated by OpenTofu using provider (AWS) account ID, the `doctrine`-pinned region, and standard AWS form. When provided, `container_registry` explicitly overrides the ECR default such that an external registry can be used instead.

### Git Repo URL

The `repo_url` top-level field formally declares the project git repository's URL. The github repository name should be the same as the project name.

This field currently only serves a documentary role. The git host and repo are prerequisite infrastructure and not managed by the `docex` compiler.

### CICL Version

The top-level `cicl_version` field declares which generation of the CICL format `infra.yml` is written in. The current version is **`"2"`**, which introduced the mandatory [`processes:`](#process-types) block, the [`consumes`](#consumes-relationships) relation, and four-segment [core magic refs](#magic-refs).

`cicl_version: "1"` is **rejected**, not shimmed. A compatibility parser accepting both forms would reintroduce the flat pre-`processes:` shape as a permanent second code path, in exchange for serving a migration that every project performs exactly once. The compiler fails with a message naming the relevant project-upgrade guide.

One consequence is worth knowing before it is needed: a [rollback](./cicd.md#rollback) recompiles the target version's `infra.yml` with the *current* compiler, so rollback across the v1 → v2 boundary is not possible. It aborts at pre-flight, before anything is applied, with a fix-forward message.

### Observability Backend

The `observability_backend_url` top-level field declares the URL at which the project's observability backend is reachable. This is the destination that the OTel collector sidecars (paired with each core service) forward signals to in `stage` and `prod`. See [telemetry.md](./telemetry.md) for the full telemetry model. The URL propagates directly into each sidecar's environment as `OBSERVABILITY_BACKEND_URL`.

The URL must be HTTPS-scheme and well-formed. The compiler rejects `http://` and unparseable values at compile time. The compiler does not probe the URL for reachability; that is verified in the [check step](./cicd.md#check-step) e.g. `./bin/docex check`.

### Networks

The purpose of a network is to scope windows of access by service. Networks are interpreted from `infra.yml` on the basis of the `networks` field. Each service may belong to multiple networks. Every service must belong to at least one network. For example, a service declaring `networks: [web, internal]` is on both networks: reachable from the internet *and* from the internal service network.

Some networks will get special properties if they have a certain name. The full list is:
1. `web` - A network named web will be open to the broader internet via HTTP. Services on `web` can be accessed from the internet.

`web` membership is restricted on core services: a `worker` or `scheduler` process type may not declare it (see [validation rule 27](#validation-rules)). The principle behind the rule is that a process type wanting public ingress *is* a web process type, and should say so with `role: web`. Network membership is declared per **process type**, not per core service — the web edge and the queue consumer of one codebase routinely sit on different networks.

The default is for networks to be internal and closed, such that only services on the network get access to each other.

Network names are defined in `infra.yml` with simple names e.g. `web`, `internal`, etc. for developer convenience. However, in practice the compiler will create networks scoped by "simple name", project, and environment. A REST API service on the `web` network will be placed on a Docker network with a name something like `${project_name}-${env_name}-${network_definition_name}` (or a similar SG in `elastic`).

Network names in practice **always** use hyphens. If an input (like a project name) has an underscore it will be converted when the network name is formed.

Details on networks, how they are evaluated, and how they compile out can be found [here](./specifics/networks.md).

### Resources

The `resources:` field declares the computing resources a [process type](#process-types) requires at runtime. It is **required** on every process type — sizing is invocation-determined, so a web edge and a queue consumer of the same codebase size independently. It is not valid at the core service level. Resources are described in provider-agnostic units; the compiler translates them per foundation. The full translation rules live in [transfer_tables.md § Resources Translation](./specifics/transfer_tables.md#resources-translation).

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
- Compile errors on this block name the full path, e.g. `core_services.api.processes.worker.resources.disk`.

### Depends-On Relationships

`depends_on` is a **readiness gate**, and it names **backing services only**. It provides the DAG the compiler needs to bring infrastructure online in the right order: a process type that declares `depends_on: [database]` is not started until the database is healthy.

A core process type may **not** appear in a `depends_on` list. Interface coupling between core process types is a different relation with different rules, and lives in [`consumes`](#consumes-relationships).

Furthermore, if a process type references a backing service's information via [magic ref](#magic-refs), it depends on that backing service. If the relationship doesn't show up in the process type's `depends_on` field, the compiler will trip an error.

**`depends_on` is a convenience, never a correctness guarantee.** It is honoured on `fixed` foundations, where the compiler emits it as a compose `condition:`. On `elastic` it is discarded, because it *cannot* be honoured: ECS has no cross-service ordering primitive, and even a deploy-time emulation would hold exactly once and then be silently violated forever after, as ECS independently replaces tasks for scaling, AZ rebalance, failed health checks, and platform updates.

> **Startup ordering is not a substitute for connection resilience.**

Every service must tolerate its dependencies being absent at any moment — not only at startup — because on elastic they will be. Reconnect, back off, and fail requests cleanly; do not assume a dependency that was reachable a second ago still is.

### Consumes Relationships

`consumes` is an **interface** edge between core process types. Where `depends_on` says *"do not start me until this is up"*, `consumes` says *"I speak to this boundary"*.

```yml
processes:
	web:
		consumes: [api.worker]
```

Targets are **dotted and fully qualified**. A bare core service name is illegal, not shorthand for "all its process types": an interface edge points at a specific boundary, and a codebase does not have one contract.

`consumes` emits nothing. It is consumed entirely by CI and validation, where it does three jobs:

1. It declares the [provider / consumer](./infrastructure.md#contracts) relationships that determine which process types must carry a contract, and in which format.
2. It drives the health-check fan-out — see [contracts.md § Health Checks](./contracts.md#health-checks).
3. It satisfies [validation rule 7](#validation-rules) for magic refs whose target is a core process type.

| | `depends_on` | `consumes` |
| --- | --- | --- |
| Names | backing services only | core process types only |
| Job | readiness gate | contracts, health fan-out, rule 7 |
| Cycles | fatal | **legal** |
| Emitted | compose `condition:` on fixed; nothing on elastic | nothing — CI only |

#### The graph may contain cycles

This is why the two relations cannot merge. `api.web` enqueues a job; `api.worker` posts the result back to `api.web`'s internal API. So `web consumes api.worker` *and* `worker consumes api.web`. That is a cycle, it is the most common web/worker topology in existence, and it is entirely fine — interfaces may be mutually referential. A cycle in `depends_on`, by contrast, is a startup deadlock that compose refuses to start. There is one DAG (`depends_on`) and one cyclic digraph (`consumes`); no single field could carry a cycle rule that is simultaneously fatal and fine.

#### Three clarifications

- **One-directional: a ref implies an edge, never the reverse.** A magic ref to a core process type obliges a matching `consumes` entry. A `consumes` entry does *not* oblige a magic ref — in the cycle above, `api.web` declares `consumes: [api.worker]` for the contract and the health fan-out but holds no ref to the worker, because it reaches it through the broker.
- **Same-codebase is not exempt.** `api.worker` referencing `${core_services.api.web.host}` still declares `consumes: [api.web]`. Sharing source does not make it not a boundary.
- **A service-level `env:` ref obliges every process type** to declare the edge, consistent with how `depends_on` is treated. If every process receives `WEB_HOST`, every process talks to `api.web`.

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
5. The rendered data-plane identity of every emitted service must be unique after naming-policy normalization. The set spans core process types, backing services, **and the derivatives the compiler appends to them** — `-otelcol` (the paired collector sidecar), `-scheduler` (the Ofelia trigger), `-exec` (the per-codebase operations container), and `-migrate` (the migration task definition) — since all of them render into the same namespace. So a process type named `exec` on core service `api` is an error: it renders `api-exec`, which is byte-identical to the exec container the compiler emits for the `api` codebase, and the two would silently share one compose key. The rule is keyed on **collision, not on a list of forbidden names**, which is what makes it cover every suffix the compiler learns in future without a further edit, and what keeps a name that collides with nothing from being forbidden for its own sake.
6. Cyclic dependency chains with `depends_on` are not allowed. (Cycles in `consumes` **are** allowed — see [Consumes Relationships](#consumes-relationships).)
7. Magic refs which imply a dependency must be matched by a corresponding edge, of the kind the target calls for: a ref to a **backing service** must be matched by a `depends_on` entry on the referencing process type; a ref to a **core process type** must be matched by a `consumes` entry. See [Consumes Relationships](#consumes-relationships) for the one-directional, same-codebase, and service-level-`env:` clarifications.
8. Database roles (e.g. `relational_db`) all specify a valid `schema_owned_by` core service.
9. `container_registry` is set when `foundation: fixed`. Omission is permitted under elastic, where it defaults to the project's auto-provisioned ECR.
10. Every core service **process type** has a `resources:` block declaring at least `cpu` and `memory`.
11. `resources.gpu` is not declared when `foundation: elastic` — GPU workloads are not supported on Fargate.
12. `domain_default_process`, if set, names a process type that is on the `web` network.
13. `apex_domain` must be a bare apex domain without subdomains.
14. Neither core service names nor process type names can be one of the following: [`dev`, `test`, `stage`, `prod`, `www`], because it makes domain parsing challenging and because a process named `prod` renders `api-prod.dev.myproject.example.com`, which reads as a production host in a dev environment.
15. Every `web`-network **process type** declares a `port`.
16. A process type's *effective* `env:` (service-level merged under process-level) does not declare a key that also appears in the core service's `secrets:` or `config:`.
17. Every engine's `naming:` value in a transfer table is the name of a policy declared in `naming_policies:` (see [transfer_tables.md § Naming Policies](./specifics/transfer_tables.md#naming-policies)).
18. `reverse_proxy` can only appear on `foundation: elastic` projects.
19. Every key a core service consumes from `config:` is declared in that service's `config:` block; config values live in the non-tracked `infra/config/<env>.env`. See [config_and_secrets.md](./specifics/config_and_secrets.md).
20. The three env-value categories — engine-minted (transfer-table `kind: minted`), secret (core `secrets:` + doctrine-injected), and config (core `config:`) — are disjoint across the whole project by source key. A key claimed by more than one category is a compile error, and doctrine-injected keys (e.g. `TELEMETRY_API_KEY`) are reserved and may not be redeclared in any category.
21. `cicl_version` is `"2"`. Earlier generations of the format are rejected, not translated.
22. Every core service declares a non-empty `processes:` block, and declares nothing at the service level outside `{processes, secrets, config, env}`.
23. Every process type declares a `command`.
24. `depends_on` names only backing services. A core process type in a `depends_on` list is an error.
25. `consumes` names only core process types, fully qualified as `<service>.<process>`. A bare core service name is an error, and a process type may not consume itself.
26. `replicas` is not declared on a `scheduler` process type.
27. `worker` and `scheduler` process types do not declare `web` in `networks`.
28. Every process type that declares `health_check_path` also declares a `port`. The path is only meaningful against a port — the probe is issued at `http://localhost:<port><path>` — and no role fixes a default health port, deliberately: an implicit one would silently oblige the application to bind it. Without this rule the omission emits a malformed probe and surfaces as a container that never becomes healthy, rather than as a compile error.
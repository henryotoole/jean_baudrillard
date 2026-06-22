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

cicl_version: "1"
foundation: fixed # or "elastic". [More info](./infrastructure.md#foundation).
apex_domain: "example.com"
domain_default_service: api  # the web service mapped to the bare <env>.<project>.<apex_domain>
container_registry: "registry.example.com"  # required for fixed; optional for elastic (defaults to project ECR)
repo_url: "https://github.com/owner_account/project_name"
observability_backend_url: "https://hyperdx.example.com"
# Defines reverse proxy choice. Elastic foundations only.
# reverse_proxy: alb # or ec2_traefik_eip or ec2_traefik_pip

core_services:

	api:
		role: web
		port: 8080
		env:
			BUCKET_NAME:  ${backing_services.bucket.bucket_name}
			DATABASE_HOST: ${backing_services.database.host}
			DATABASE_PORT: ${backing_services.database.port}
			DATABASE_NAME: ${backing_services.database.db}
			DATABASE_USER: ${backing_services.database.user}
			DATABASE_PASSWORD: ${backing_services.database.password}
			DATABASE_SSLMODE: ${backing_services.database.sslmode}
		secrets:
			DISCORD_API_KEY: "Key to the discord bot used by the API."
		resources:
			cpu: 1.0
			memory: 2GB
			disk: 20GB
		networks: [web, internal]
		depends_on: [database, cache, bucket]
	
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

### Service Fields

The table below lists all standard fields for services.

| Field Name | Required | Core or Backing Service | Description |
| ---------- | -------- | ----------------------- | ----------- |
| role | yes | both | What this service *does* for the project e.g. 'relational_db', 'cache', etc. |
| networks | yes | both | Lists the networks this service will belong to. |
| resources | yes | core | Computing resources the service requires at runtime. See [Resources](#resources). |
| depends_on | no | both | List of services that must be running before this one starts. |
| port | no | both | The port that the service should be available on. |
| env | no | core | Contains fields which define infrastructure-driven environment variables for the container. |
| replicas | no | core | The number of parallel containers to launch in production. Ignored in `dev`, `test`, and `stage`. Defaults to 1. |
| command | no | core | The command to run to launch the core service. |
| secrets | no | core | Bespoke, project-supplied secret env vars with no in-project source. Used to construct `example.env` later. |
| engine | yes | backing | The underlying software package the service will use e.g. 'postgres', 'redis', etc. Can define two options if `fixed` and `elastic` foundations require different engines. |
| version | yes | backing | The version of the engine to use. Format depends on engine. |
| schema_owned_by | sometimes | backing | Required for database roles (e.g. `relational_db`) to denote which core service owns the database schema and drives migrations. |

Note that core services do **not** declare an `image` field. Image references are derived deterministically by the compiler from the top-level [`container_registry`](#container-registry-and-service-images), the project name and version (from `project.yml`), and the service name. See [Container Registry](#container-registry-and-service-images) for the full format.

The values for these fields can have "magic refs" like ${backing_services.object_store.bucket_name} which reference service [provided fields](#provided-fields) and are filled with the correct interpolated values when `infra.yml` is converted to docker-compose or OpenTofu config files.

Some services will have additional fields. These are role specific, and will be translated with the [transfer tables](#cicl-transfer-tables) during compilation.

### Provided Fields

Every role may declare fields which are "provided" to other services. These tend to represent fundamental properties like `port` or even secrets like `password`. They are defined per role in the `docex` transfer tables so that `docex` is careful and consistent when compiling `infra.yml` - especially with secrets, which must be carefully handled in compiled output.

Restrictions with infra providers (particularly AWS SSM) mean that provided fields must be *values*, and can not be strings which are interpolated later. A role never exposes a pre-composed connection string. A consumer that needs a composed handle (e.g. a database url) builds it from the parts at startup. In the example above, `api` would need a database url to connect to the `database` backing service. We provide `DATABASE_HOST`, `DATABASE_PORT`, etc. as environmental variables so that the code within `api` can construct a database url at runtime. This produces an identical landscape across all four environments.

The provided fields for each role live in the `docex` transfer tables, not in this doctrine. To discover them, run `./bin/docex role <role>` — it lists the role's engines and their provided fields (which are secrets, the required env vars, and the role-specific fields). `./bin/docex roles` lists every available role. See [docex.md](./docex.md#role).

### Secret and Env Fields

Two fields define a core service's container environmental variables. `env:` holds values the compiler resolves - literals and magic refs to provided parts. `secrets:` holds bespoke secrets the operator supplies via `<env>.env` (and SSM on elastic), never committed. A given key may appear in at most one of them.

### Rules

We define some arbitrary but hard rules for these infra files in order to reduce complexity.

1. Service names are interpolated into a globally unique name when used as variables.
	+ For example, a core service needs a bucket name. This name will be interpolated from the object store backing service name, the environment name, and the project name.
2. Services communicate over URLs, and those URLs are built from provided fields (host, port, etc.) at startup.

### Naming and Tagging

Consistent naming and tagging conventions are employed wherever possible to ensure infrastructure is easy to find and identify.

#### Fixed Foundation

For `fixed`-foundation infrastructure resources, there are no tags. Naming standards to:
1. Docker networks: `${project_name}-${env_name}-${network_definition_name}`
2. Docker containers `${project}-${env}-${service}`

#### Elastic Foundation

In the elastic foundation, tags can be used and the naming / tagging convention is a little more rigorous.

### Domain

The anatomy of a project's domain is rigidly defined and critical to the "just works" nature of CICL machinery. A full domain describes a specific service container uniquely across all projects. The form is:

`<service>.<env>.<project_name>.<apex_domain>` e.g. `api.dev.myproject.example.com`

Simply by assessing the domain of a request, any machinery with no further context can determine the destination project name, environment, and service container. The `infra.yml` config `apex_domain` field sets the project's bare apex domain e.g. `example.com` or `example.co.uk`. Projects may or may not share apex domains with other projects.

Keep in mind, the domain structure is not the exclusive means of inter-service communication. Only `web`-network services are reachable from the outside; a domain pointing at a non-`web` service would not be routed there. There's also some variation by foundation - `elastic` backing services like S3 have their own endpoints provided by AWS whereas `fixed` backing services like `minio` require routing with the domain mechanism.

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

The `container_registry` top-level config option declares where core service [build images](./shape.md) are pushed and pulled from. The compiler derives every image reference deterministically on the basis of environment:
- **`dev` / `test`** build each core service's image **locally** from its Dockerfile (the compiled compose file carries a `build:` block) and never pull from a registry. The image is therefore a **registry-less local tag**:
	`${project_name}/${service_name}:${version}`.
- **`stage` / `prod`** reference an image that is pushed to and pulled from a registry, so the ref carries the full registry host:
	`${container_registry}/${project_name}/${service_name}:${version}`

with `name` and `version` from `project.yml` and `service_name` from the CICL key under `core_services`. Each core service gets its own image; all images for a project share the project-wide version.

- **Fixed foundation:** `container_registry` is **required**. The doctrine does not provision a registry for fixed projects — it is [prerequisite infrastructure](./shape.md#fixed-foundation). Typical values are a self-hosted Docker Registry V2 URL or a public registry (Docker Hub, ghcr.io, etc.).
- **Elastic foundation:** `container_registry` is **optional**. When omitted, `stage`/`prod` images resolve to the project's auto-provisioned registry (ECR). The registry domain is deterministically interpolated by OpenTofu using provider (AWS) account ID, the `doctrine`-pinned region, and standard AWS form. When provided, `container_registry` explicitly overrides the ECR default such that an external registry can be used instead.

### Git Repo URL

The `repo_url` top-level field formally declares the project git repository's URL. The github repository name should be the same as the project name.

This field currently only serves a documentary role. The git host and repo are prerequisite infrastructure and not managed by the `docex` compiler.

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

The `resources:` field on a core service declares the computing resources the service requires at runtime. It is **required** on every core service. Resources are described in provider-agnostic units; the compiler translates them per foundation. The full translation rules live in [transfer_tables.md § Resources Translation](./specifics/transfer_tables.md#resources-translation).

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

### Depends-On Relationships

The relationships between services defined by the `depends_on` block serve several roles:
1. It provides the DAG needed for the compiler to produce infrastructure config which brings infrastructure online in the right order.
2. It describes the [provider / consumer](./infrastructure.md#contracts) relationship between core services. This allows the compiler to ensure these relationships are defined properly; [CI/CD](./cicd.md) `docex` checks rely on this relationship.
3. It defines a dependency chain which lets us check which services are "downstream" in the chain from others.

Furthermore, if Service A references Service B's information via magic ref, then A depends on B. If that relationship doesn't actually show up in A's `depends_on` field, the compiler will trip an error.

### Reverse Proxy

Elastic foundations have two options for the reverse proxy resource - ALB for projects which require robust availability and ingress and an EC2 traefik instance for those which don't. ALB's cost substantially more than an EC2 instance doing the equivalent task. The EC2 instance can be backed with a regular Public IP or an Elastic IP. Public IP's will inevitably lead to some downtime if they change, but an infinite number of them are available, so both options are available.


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
2. `elastic` foundations use "us-east-1a" as the primary AZ. We sometimes include a second AZ if required by AWS (e.g. for ALB's), but we avoid placing service containers in it [in practice](./reasoning/ingress_and_egress.md#elastic-azs).

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

For example, many software projects need a relational database. The transfer tables will define `object_store` as a role and list the engines that are available for each foundation e.g. 'minio' for `fixed` and 'S3' for `elastic`. Each engine-foundation combination will contain detailed instructions on how to configure that combination with the relevant tools. These instructions are what allow automatic translation from something like `versioning: true` to `aws_s3_bucket_versioning` resource configuration.

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

A single env `main.tf` contains the env-tier resources: provider config, state backend reference, networks (security groups), ECS, backing services, env-specific DNS records, ALB listener rules / EC2-traefik SSM config updates. OpenTofu does not require splitting, and a single file is simpler to read and review. Each env reads project-tier outputs (zone, certs, ALB/EC2-traefik ARNs, ECR repos, task-execution role) via `data "terraform_remote_state" "project"`.

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

**Secret declarations** (both foundations):

Alongside the env-specific output, the compiler emits `infra/secrets/example.env` documenting every runtime secret the project's services require. This is derived from the `env:` blocks of [transfer table](./specifics/transfer_tables.md) entries for each backing service and `secrets` blocks for core services in `infra.yml`. The developer never writes secret names into the project by hand — the surface stays in sync with doctrine knowledge automatically. See [secrets.md](./specifics/secrets.md) for the full layout of `infra/secrets/` and how the operator's `<env>.env` files are consumed at release time.

### Validation Rules
The following rules apply to whether or not an `infra.yml` file is valid.

1. All required fields must be present on relevant services.
2. All roles must either be defined in the standard transfer tables or the project-local ones.
3. All "magic refs" must resolve.
4. Engines must be known and engines must match foundation (e.g. minio for `fixed` foundation, S3 for `elastic`).
5. Names must be unique across services.
6. Cyclic dependency chains with `depends_on` are not allowed.
7. Magic refs which imply dependency between services must be matched by a corresponding `depends_on` block between services.
8. Database roles (e.g. `relational_db`) all specify a valid `schema_owned_by` core service.
9. `container_registry` is set when `foundation: fixed`. Omission is permitted under elastic, where it defaults to the project's auto-provisioned ECR.
10. Every core service has a `resources:` block declaring at least `cpu` and `memory`.
11. `resources.gpu` is not declared when `foundation: elastic` — GPU workloads are not supported on Fargate.
12. `domain_default_service`, if set, names a service that is on the `web` network.
13. `apex_domain` must be a bare apex domain without subdomains.
14. Service names can not be one of the following: [`dev`, `test`, `stage`, `prod`, `www`], because it makes domain parsing challenging.
15. Every `web`-network service declares a `port`.
16. A core service's `env:` and `secrets:` do not declare the same key.
17. Every engine's `naming:` value in a transfer table is the name of a policy declared in `naming_policies:` (see [transfer_tables.md § Naming Policies](./specifics/transfer_tables.md#naming-policies)).
18. `reverse_proxy` can only appear on `foundation: elastic` projects.
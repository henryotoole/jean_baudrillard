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
domain: "example.com"
container_registry: "registry.example.com"  # required for fixed; optional for elastic (defaults to project ECR)
repo_url: "https://github.com/owner_account/project_name"

core_services:

	api:
		role: web
		port: 8080
		env:
			BUCKET_NAME:  ${backing_services.bucket.name}
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
		depends_on: [reverse_proxy]
		networks: [internal]
		schema_owned_by: api

	cache:
		role: cache
		engine: redis
		version: "7"
		depends_on: [reverse_proxy]
		networks: [internal]

	bucket:
		role: object_store
		engine: [minio, s3]
		versioning: true	# A role-specific field.
		depends_on: [reverse_proxy]
		networks: [web, internal]

	reverse_proxy:
		role: reverse_proxy
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
| env | no | core | Contains fields which define environment variables for the container. |
| replicas | no | core | The number of parallel containers to launch in production. Ignored in `dev`, `test`, and `stage`. Defaults to 1. |
| command | no | core | The command to run to launch the core service. |
| engine | yes | backing | The underlying software package the service will use e.g. 'postgres', 'redis', etc. Can define two options if `fixed` and `elastic` foundations require different engines. |
| version | yes | backing | The version of the engine to use. Format depends on engine. |
| schema_owned_by | sometimes | backing | Required for database roles (e.g. `relational_db`) to denote which core service owns the database schema and drives migrations. |

Note that core services do **not** declare an `image` field. Image references are derived deterministically by the compiler from the top-level [`container_registry`](#container-registry), the project name and version (from `project.yml`), and the service name. See [Container Registry](#container-registry) for the full format.

The values for these fields can have "magic refs" like ${backing_services.object_store.name} which are filled with the correct interpolated values when `infra.yml` is converted to docker-compose or OpenTofu config files.

Some services will have additional fields. These are role specific, and will be translated with the [transfer tables](#cicl-transfer-tables) during compilation.

### Rules

We define some arbitrary but hard rules for these infra files in order to reduce complexity.

1. Service names are interpolated into a globally unique name when used as variables.
	+ For example, a core service needs a bucket name. This name will interpolated from the object store backing service name, the environment name, and the project name.
2. Services communicate over URLs, and those URLs are deterministically interpolated.

### Domain

The `domain` toplevel config option is the project's apex domain — bare, with no `www` or other prefix. All environments are served at single-label subdomains derived from it:

| Environment | Subdomain |
| ----------- | --------- |
| `dev` | `dev.<domain>` |
| `test` | `test.<domain>` |
| `stage` | `stage.<domain>` |
| `prod` | `www.<domain>` |

So `domain: "example.com"` yields `dev.example.com`, `test.example.com`, `stage.example.com`, and `www.example.com`. The apex itself (`example.com`) is not served by the doctrine; operators who want apex-to-`www` redirection handle it at the DNS or registrar level.

There's also a slight difference in intent depending on project foundation. For a project with a `fixed` foundation, DNS configuration is out of scope for infra management and we assume each subdomain has already been routed to the correct machine. For `elastic` foundation projects, the subdomains are configured to route to the correct ALB by OpenTofu.

### Container Registry

The `container_registry` top-level config option declares where core service [build images](./shape2.md) are pushed and pulled from. Projects never write image strings by hand — the compiler derives every image reference deterministically as:

```
${container_registry}/${project_name}/${service_name}:${version}
```

with `name` and `version` from `project.yml` and `service_name` from the CICL key under `core_services`. Each core service gets its own image; all images for a project share the project-wide version.

- **Fixed foundation:** `container_registry` is **required**. The doctrine does not provision a registry for fixed projects — it is [prerequisite infrastructure](./shape2.md#fixed-foundation). Typical values are a self-hosted Docker Registry V2 URL or a public registry (Docker Hub, ghcr.io, etc.).
- **Elastic foundation:** `container_registry` is **optional**. Defaults to the project's auto-provisioned ECR: `<account>.dkr.ecr.us-east-1.amazonaws.com`. Setting it explicitly overrides the default — useful when a project wants to push to an external registry instead.

### Git Repo URL

The `repo_url` top-level field formally declares the project git repository's URL. The github repository name should be the same as the project name.

This field currently only serves a documentary role. The git host and repo are prerequisite infrastructure and not managed by the `docex` compiler.

### Networks

The purpose of a network is to scope windows of access by service. Networks are interpreted from `infra.yml` on the basis of the `networks` field. Each service may belong to multiple networks. Every service must belong to at least one network. For example, a service declaring `networks: [web, internal]` is on both networks: reachable from the internet *and* from the internal service network.

Some networks will get special properties if they have a certain name. The full list is:
1. `web` - A network named web will be open to the broader internet via HTTP.

The default is for networks to be internal and closed, such that only services on the network get access to each other.

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
- Memory and disk accept `MB` and `GB` (decimal). Binary units (`MiB`/`GiB`) are not supported in v1 — units are an authoring convenience, not an exactness contract.
- GPU support is v1-minimal: `count` only. Architecture or VRAM hints are deferred.
- **Elastic + GPU is not supported.** The doctrine commits to Fargate for elastic, and Fargate does not run GPU workloads. Listed under [infrastructure.md § Deferred](./infrastructure.md#deferred).
- The `disk` translation is asymmetric: on elastic, `ephemeral_storage` bounds the whole writable layer; on fixed, the compiler sizes a tmpfs at `/tmp` and the container's overlay layer remains unbounded (a limitation of the overlay2 storage driver). Apps that respect the [12-factor app](https://12factor.net/) ephemeral-storage principle write temp files to `/tmp` and are unaffected.
- Backing services do not take a `resources:` block in v1. Their sizing comes from the engine's defaults in the transfer table; projects needing different sizes use project-local transfer tables.

### Depends-On Relationships

The relationships between services defined by the `depends_on` block serve several roles:
1. It provides the DAG needed for the compiler to produce infrastructure config which brings infrastructure online in the right order.
2. It describes the [provider / consumer](./infrastructure.md#contracts) relationship between core services. This allows the compiler to ensure these relationships are defined properly; [CI/CD](./cicd.md) `docex` checks rely on this relationship.
3. It defines a dependency chain which let's us check which services are "downstream" in the chain from others.

Furthermore, if Service A reference's Service B's information via magic ref, then A depends on B. If that relationship doesn't actually show up in A's `depends_on` field, the compiler will trip an error.

## The CICL Compiler

The compiler translates `infra.yml` into docker-compose config or OpenTofu HCL.

The compiler is bundled into `docex` as a command e.g. `docex compile`.

### Simplifications

In order to simplify down the massive complexities of infrastructure, we make some simplifications:
1. `elastic` foundations only use AWS as a provider and only use one region: "us-east-1".

### Shape Assumption and Declaration

The [shape](./shape2.md) of the infrastructure surrounding a project covers all three [tiers](./infrastructure.md#infrastructure-tiers) of infrastructure. The compiler treats each a little differently:

| Tier | Described by `infra.yml` | Described by compiler output |
| ---- | ------------------------ | ---------------------------- |
| Prerequisite | No | No |
| Project | No | Yes |
| Environment | Yes | Yes |

Keeping prerequisite and project infrastructure out of `infra.yml` succeeds in the doctrine's goal of reducing as much as possible to "one canonical method" - it keeps infrastructure design simple. However, those results should still be *discoverable* by the developer both for understanding and debugging. For this reason, `docex` provides the [describe](./docex.md#describe) command.

Furthermore, the compiler documents all its derived infrastructure configuration in the output files to this end.

### CICL Transfer Tables

In order to translate provider-agnostic CICL definitions into the specifics needed to actually construct or provision infrastructure, the compiler requires 'transfer tables'. These concretely define how we will actually implement different infrastructure roles.

For example, many software projects need a relational database. The transfer tables will define `object_store` as a role and list the engines that are available for each foundation e.g. 'minio' for `fixed` and 'S3' for `elastic`. Each engine-foundation combination will contain detailed instructions on how to configure that combination with the relevant tools. These instructions are what allow automatic translation from something like `versioning: true` to `aws_s3_bucket_versioning` resource configuration.

These tables are formatted in plain YAML. The `doctrine` maintains transfer tables which ought to cover most cases. To provide flexibility, projects can also provide their own project-specific transfer tables which will be deep merged with the `doctrine` ones when the compiler runs. However, **care should be taken** when choosing design that calls upon this additional complexity. Most projects won't need it.

### Compiler Output

All compiler output lives under `infra/output/<env>/`, one subdirectory per environment. Output is git-tracked: diffs on output files show what an `infra.yml` change actually produces, and reviewers can see the full infrastructure impact of a change in a PR. The exact contents depend on the env's foundation.

**Fixed envs** (`dev`, `test`, and `stage`/`prod` when foundation is fixed):

```
infra/output/<env>/
	docker-compose.yml        # always
	playbook.yml              # stage/prod only
	inventory.yml             # stage/prod only (derived from `domain`)
	ansible.cfg               # stage/prod only
```

For `dev` and `test`, just the compose file — those envs run locally and don't need an Ansible playbook. `docex up` and `docex up test` invoke `docker compose -f infra/output/<env>/docker-compose.yml up` under the hood.

**Elastic envs** (`stage` and `prod` when foundation is elastic):

```
infra/output/<env>/
	main.tf
```

A single `main.tf` per env contains everything: provider config, state backend reference, networks, ALB, ECS, backing services, DNS. OpenTofu does not require splitting, and a single file is simpler to read and review.

**Secret declarations** (both foundations):

Alongside the env-specific output, the compiler emits `infra/secrets/example.env` documenting every runtime secret the project's services require, derived from the `env:` blocks of [transfer table](./specifics/transfer_tables.md) entries for each backing service. The developer never writes secret names into the project by hand — the surface stays in sync with doctrine knowledge automatically. See [release_mechanism.md § Secrets](./specifics/release_mechanism.md#secrets) for the full layout of `infra/secrets/` and how the operator's `<env>.env` files are consumed at release time.

### Validation Rules
The following rules apply to whether or not an `infra.yml` file is valid.

1. All required fields must be present on relevant services.
2. All roles must either be defined in the standard transfer tables or the project-local ones.
3. All "magic refs" must resolve.
4. Engines must be known and engines must match foundation (e.g. minio for `elastic` foundation.)
5. Names must be unique across services.
6. Cyclic dependency chains with `depends_on` are not allowed.
7. Magic refs which imply dependency between services must be matched by a corresponding `depends_on` block between services.
8. Database roles (e.g. `relational_db`) all specify a valid `schema_owned_by` core service.
9. `container_registry` is set when `foundation: fixed`. Omission is permitted under elastic, where it defaults to the project's auto-provisioned ECR.
10. Every core service has a `resources:` block declaring at least `cpu` and `memory`.
11. `resources.gpu` is not declared when `foundation: elastic` — GPU workloads are not supported on Fargate.
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

cicl_version: "3"
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
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
      DATABASE_SSLMODE: ${backing_services.appdb.sslmode}
    core_services:
      web:
        role: web
        command: ["python", "-m", "entrypoints.http"]
        port: 8080
        networks: [web, internal]
        health_check_path: /health   # web only — this is the load balancer's probe
        resources:
          cpu: 1.0
          memory: 2GB
          disk: 20GB
        env:
          # Core-service-scoped: only `web` touches the bucket, so the ref
          # belongs here rather than on the codebase.
          BUCKET_NAME: ${backing_services.bucket.bucket_name}
        uses: [appdb, cache, bucket, api.worker]
        surfaces:
          rest:
            api_styles: [rest, webhook]   # one OpenAPI contract
      worker:
        role: worker
        command: ["python", "-m", "entrypoints.worker"]
        networks: [internal]
        replicas: 4
        resources:
          cpu: 2.0
          memory: 4GB
        uses: [cache, appdb, api.web]
        surfaces:
          events:
            api_styles: [events]          # one AsyncAPI contract
      clock:
        role: clock
        command: ["python", "-m", "entrypoints.clock"]
        networks: [internal]
        resources:
          cpu: 0.25
          memory: 512MB
        uses: [appdb, api.worker]
        # No `surfaces:` — a clock is driven by time, not from outside. It is
        # a consumer only, so nothing may `uses` it.
        schedules:
          nightly_cleanup: "0 3 * * *"
          hourly_rollup: "0 * * * *"

backing_services:

  appdb:
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
    port: 9000 # on the web network, so a routing port is required
    engine: [minio, s3]
    version: "RELEASE.2024-01-16T16-07-38Z" # pins the minio image tag (fixed); s3 (elastic) has no image, so version is exempt there
    versioning: true # A role-specific field.
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
      web:                  # a core service
        role: web
        command: [...]
        surfaces: { ... }   # core-service-scoped
      worker:
        role: worker
        command: [...]
        surfaces: { ... }
```

> **Naming**: A core service is generally named after its role, unless a codebase declares two on the same role. `role: web` → `web`; `role: worker` → `worker`; `role: clock` → `clock`.

### Service Fields

The table below lists all standard fields for codebases and/or core services.

| Field Name | Required | Scope | Description |
| ---------- | -------- | ----- | ----------- |
| core_services | yes | codebase | The codebase's [core services](#core-services). Must be present and non-empty. |
| secrets | no | codebase | Bespoke, project-supplied secret env vars with no in-project source. Surfaced in the project's secrets file (`<env>.env`). See [configurable.md](./configurable.md#secrets). |
| config | no | codebase | Declared, non-secret, per-env config values (e.g. a URL that differs by environment). Keys are declared here; values live in the non-tracked, LLM-readable `infra/config/<env>.env`. See [configurable.md](./configurable.md#config). |
| env | no | codebase + core service | Contains fields which define infrastructure-driven environment variables for the container. Valid at the codebase level and on a core service; a core service's own block merges over the codebase's. |
| role | yes | core service, backing | What this core service or backing service *does* for the project e.g. 'web', 'worker', 'relational_db', 'cache'. |
| surfaces | no | core service | The API [surfaces](#surfaces) which this core service exposes. |
| command | yes | core service | The command that launches this core service. Required on every core service; supersedes the Dockerfile `CMD`. |
| networks | yes | core service, backing | Lists the networks this core service or backing service will belong to. |
| resources | yes | core service | Computing resources the core service requires at runtime. See [Resources](#resources). |
| port | no | core service, backing | The port that the core service or backing service should be available on. |
| uses | no | core service | What this core service talks to. Names a **backing service** (bare) or a **core service** (dotted and fully qualified). See [Uses Relationships](#uses-relationships). |
| replicas | no | core service | The number of parallel containers to launch in production. Ignored in `dev`, `test`, and `stage`. Defaults to 1. Not permitted on a `clock` core service. |
| schedules | sometimes | core service | Map of job name → bare 5-field UTC cron string. Required on a `clock` core service and rejected on every other role. See [clock.md](./specifics/clock.md). |
| engine | yes | backing | The underlying software package the service will use e.g. 'postgres', 'redis', etc. Can define two options if `fixed` and `elastic` foundations require different engines. |
| version | yes | backing | The version of the engine to use. Format depends on engine. |
| schema_owned_by | sometimes | backing | Required for database roles (e.g. `relational_db`) to denote which codebase owns the database schema and drives migrations. Names a **codebase**, never a core service — `migrate.sh` runs once per codebase. |

Note that codebases do **not** declare an `image` field. Image references are derived deterministically by the compiler from the top-level [`container_registry`](#container-registry-and-service-images), the project name and version (from `project.yml`), and the codebase name. The image is keyed on the **codebase**, so every core service of a codebase runs the same image. See [Container Registry](#container-registry-and-service-images) for the full format.

The values for these fields can have "magic refs" like ${backing_services.object_store.bucket_name} which reference service [provided fields](#provided-fields) and are filled with the correct interpolated values when `infra.yml` is converted to docker-compose or OpenTofu config files.

Some services will have additional fields. These are role specific, and will be translated with the [transfer tables](#cicl-transfer-tables) during compilation.

`./bin/docex compile` will always fail loudly when a field is placed in the wrong scope, or if a required field is absent.

### Provided Fields

Every role may declare fields which are "provided" to other services. These tend to represent fundamental properties like `port` or `host`. They are defined per role in the `docex` transfer tables so that `docex` is careful and consistent when compiling `infra.yml`.

Restrictions with infra providers (particularly AWS SSM) mean that provided fields must be *values*, and can not be strings which are interpolated later. A role never exposes a pre-composed connection string. A consumer that needs a composed handle (e.g. a database url) builds it from the parts at startup. In the example above, `api` would need a database url to connect to the `appdb` backing service. We provide `DATABASE_HOST`, `DATABASE_PORT`, etc. as environmental variables so that the code within `api` can construct a database url at runtime. This produces an identical landscape across all four environments.

The provided fields for each role live in the `docex` transfer tables, not in this doctrine. To discover them, run `./bin/docex role <role>` — it lists the role's engines and their provided fields (which are secrets, the required env vars, and the role-specific fields). `./bin/docex roles` lists every available role. See [docex.md](./docex.md#role).

### Magic Refs

A magic ref reads a [provided field](#provided-fields) off another service. A core ref is a **literal path** into the document — every segment names a key the reader can walk in `infra.yml`, including the intermediate `core_services` collection. A backing ref has no such collection to traverse:

```
${codebases.<codebase>.core_services.<service>.<part>}   # five segments — api.web.host
${backing_services.<service>.<part>}                     # three segments — appdb.host
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
2. When services communicate over URLS, those URLs are built from provided fields (host, port, etc.) at startup.

### Naming and Tagging

Consistent naming and tagging conventions are employed wherever possible to ensure infrastructure is easy to identify.

#### Fixed Foundation

For `fixed`-foundation infrastructure resources, there are no tags. Naming standards are:
1. Docker networks: `${project_name}-${env_name}-${network_definition_name}`
2. Docker containers: `${project}-${env}-${codebase}-${service}`

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

The top-level `cicl_version` field declares which generation of the CICL format `infra.yml` is written in. The current version is **`"3"`**.

Previous generations are **rejected**, not shimmed. A compatibility parser accepting an older form would keep that generation's shape alive as a permanent second code path — the flat, one-service-per-codebase layout that predates nesting core services under a codebase, or the split `depends_on` / `consumes` relation that predates `uses` — in exchange for serving a migration that every project performs exactly once. The compiler fails with a message naming the relevant project-upgrade guide.

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
    count: 1        # number of GPUs to request
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

### Uses Relationships

`uses` is the single relation between services. In the example below, service `api.web` *uses* service `api.worker` across a surface. Between core services, a consumer / provider relationship is implied. Below, `api.web` is the *consumer* and `api.worker` is the *provider* in the relationship.

```yml
codebases:
  api:
    core_services:
      web:
        uses: [appdb, cache, bucket, api.worker]
```

A `uses` entry names either a **backing service** (e.g. `appdb`) or a **core service** (dotted and fully qualified, e.g. `api.worker`). A bare codebase name is invalid.

**Only core services declare `uses`.** A backing service has no outbound edges at all. Where an engine genuinely needs another container beneath it, that requirement is an *engine* concern and belongs in its transfer table. This decision is load bearing as it makes backing services a *sink* in the infrastructure relational graph.

The `uses` field serves four purposes:
1. It declares the [provider / consumer](./infrastructure.md#contracts) relationships between services.
2. It satisfies [validation rule 7](#validation-rules) for magic refs.
3. It determines which backing services must be running to use the per-codebase exec service [exec_service.md](./specifics/exec_service.md).
4. On elastic, it names the endpoints each consumer must be able to resolve.

While `uses` relationships do allow the infrastructure graph to be constructed, they are *not* used by `docex` to implement start ordering between core and backing services. Doctrine-compliant **core services must tolerate the momentary absence of dependencies**. Network outages, deployments, startup sequences, and other factors can all lead to temporary downtime of any service. Graceful handling of these sometimes unavoidable absences is necessary. Use:
+ Sensible timeouts to produce clean errors when a service is down unreachable.
+ Retries with exponential backoff and jitter to reduce hammering when the absent service returns.

The `uses` relationship does allow for cycles. Service A can use Service B while Service B uses Service A.

Naturally, a consumer-service cannot "use" a provider-service if the provider does not have any declared surfaces. Such a state is invalid and will trip a `docex` compile error.

### Surfaces

The *surface* is the doctrine name for the API which allows interaction with a core service from the "outside". A good example is a `web`-role core service's REST-based API. Other project infra (like a frontend) or 3rd party access would both interact with the core service through this REST surface.

Every surface has a contract which defines its behavior (see [contracts.md](./contracts.md)). Surfaces also have one or more "API styles" e.g. REST, RPC, webhooks, MCP etc. Only certain combinations of API styles can be used together in one surface. Each style has a doctrine-defined standard format of contract which can effectively express it (see [contracts.md](./contracts.md#standards)). All styles in a surface must map to the same contract format. Invalid style combinations will trip a `docex` compile error. 

| API Style | Format | Covers |
| --- | --- | --- |
| `rest` | `openapi` | resource-oriented HTTP |
| `stream` | `openapi` | SSE, JSON Lines, `application/json-seq` (OpenAPI 3.2 `itemSchema`) |
| `webhook` | `openapi` | provider-initiated callbacks (OpenAPI 3.1 top-level `webhooks`) |
| `rpc` | `asyncapi` | JSON-RPC, MCP, request/reply (AsyncAPI 3.0 `reply`) |
| `events` | `asyncapi` | queue / broker / pub-sub |
| `socket` | `asyncapi` | WebSocket, bidirectional |
| `graphql` | `graphql` | GraphQL SDL |
| `grpc` | `proto` | gRPC / protobuf IDL |

> **NOTE**: `graphql` and `proto` are not yet implemented.

Surfaces are defined in `infra.yml` under the relevant core service.

```yml
codebases:
  api:
    core_services:
      web:
        role: web
        networks: [web, internal]
        port: 8080
        health_check_path: /health
        surfaces:
          rest:
            api_styles: [rest, stream, webhook]   # all openapi — one contract
          events:
            api_styles: [events]                  # different format — its own surface
      mcp:
        role: web
        networks: [web, internal]
        port: 8081
        health_check_path: /health
        surfaces:
          mcp:
            api_styles: [rpc]                     # asyncapi
```

Both declare `networks` and `health_check_path` because both are publicly routed,
and [rule 33](#validation-rules) ties that field to `web`-network membership rather
than to the `web` *role* — routing is network-driven.

The second surface above is `events` rather than `graphql` for a mechanical
reason worth stating: a `graphql` surface **compiles to an error** today, so an
example using one would be a worked example that does not work. `events` makes the
same point — one process, two boundaries, two formats, therefore two surfaces —
against a format the compiler can actually carry.

Each surface compiles to exactly one contract file, named for the surface that produced it. See [contracts.md](./contracts.md) for the path format.

> **Naming**: A surface is generally named after its main API style, unless a core service declares two surfaces on the same style. `api_styles: [rest]` → `rest`; `api_styles: [rest, webhook]` → `rest`; two REST surfaces → `rest_public` and `rest_admin`.

A core service can have multiple surfaces. These can even be of the same type - for example, it's fine to have two surfaces named `rest_public` and `rest_admin` for two REST API's with differing purpose and authentication. However, this leads to the interesting design question of whether to split surfaces within one core service or across two different ones. The answer comes down to similarity and process suitability:

> Two boundaries belong to one core service iff every core-service-distinguishing
> field — `role`, `command`, `resources`, `networks`, `port`, `replicas` — would
> take the same value for both. If any would differ, they are two core services.

Splitting is cheap — two core services share one codebase, one image, and one composition root, and cost only a second thin entrypoint. Bundling is the move that cannot be undone without changing deployed topology, routing, and contract paths. **When in doubt, split.**

| Circumstance | Correct Split | Why |
| ------------ | ------------- | --- |
| A classic `api` with `web` and `worker` | Two core services, one surface each | Queue-based worker has a fundamentally different entrypoint and `command`; must be different core services. |
| A REST API that also emits webhooks and streams SSE | **One** core service, **one** surface | All three styles are `openapi`, and one process serves them on one port with one sizing. `api_styles: [rest, stream, webhook]`. |
| A REST API that also serves GraphQL from the same server | **One** core service, **two** surfaces | Same process, same sizing — but the formats differ, so they cannot share a contract. |
| A public REST API and an internal admin REST API in one process | **One** core service, **two** surfaces | Same format, but genuinely different consumers and auth. `rest_public` and `rest_admin`. |
| …where the admin API must be off the `web` network | **Two** core services | `networks` differs, so the split test fails. Boundary shape did not decide this; deployment did. |
| A REST edge and an MCP session server | **Two** core services | Session holding sizes on concurrent sessions and needs long drain windows; `resources` and `command` both differ. |
| A REST API and a gRPC API | **Two** core services | Each needs its own listening `port`, and a core service declares one. (Per-surface `port` is deliberately deferred.) |
| A worker consuming two different queues | **One** core service, **one** surface | Both are `events`; one AsyncAPI document carries both channels. Two surfaces only if the consumers are genuinely unrelated. |
| A `clock` | **One** core service, **no** surfaces | Driven by time, not from outside. Declaring no surface is what makes it a non-provider. |

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

Rule numbers are **stable identities**. They are cited from other doctrine files, from `docex`'s validation issue ids, and from the pre-cut checklist, so a retired rule keeps its number and is marked below rather than removed — the rules that follow it are never renumbered.

1. All required fields must be present on relevant services.
2. All roles must either be defined in the standard transfer tables or the project-local ones.
3. All "magic refs" must resolve.
4. Engines must be known and engines must match foundation (e.g. minio for `fixed` foundation, S3 for `elastic`).
5. The rendered data-plane identity of every emitted service must be unique after naming-policy normalization. The set spans core services, backing services, **and the derivatives the compiler appends to them** — `-otelcol` (the paired collector sidecar), `-exec` (the per-codebase operations container), `-migrate` (the migration task definition), and `-1`…`-N` (the replica index, on a core service declaring `replicas: N`) — since all of them render into the same namespace. So a core service named `exec` on codebase `api` is an error: it renders `api-exec`, which is byte-identical to the exec container the compiler emits for the `api` codebase, and the two would silently share one compose key. Likewise a codebase `api` declaring core services `web` with `replicas: 3` and `web-1` is an error: replica 1 of `web` renders `api-web-1`, byte-identical to the `web-1` core service's own compiled identity. The rule is keyed on **collision, not on a list of forbidden names**, which is what makes it cover every suffix the compiler learns in future without a further edit, and what keeps a name that collides with nothing from being forbidden for its own sake.
6. *(Retired in 2.0.0.)* Formerly forbade cycles in `depends_on`. With one relation, and backing services declaring no outbound edges, a backing service is a graph **sink** — acyclicity across backing-targeted edges is a property of the graph's shape rather than a rule enforced against it.
7. Magic refs which imply a dependency must be matched by a corresponding `uses` entry on the referencing core service. This rule governs **core-service referencers**, since a core service is the only thing that can hold a `uses` edge. A backing service that embeds a core service's part — an `object_store` holding `${codebases.api.core_services.web.host}` as a CORS origin, say — cannot satisfy it at all, because backing services declare no edges. That is rule 7 correctly **not applying** rather than a gap: a backing service embedding a core hostname is not *calling* it, so there is no interface implication for the relation to express. Three clarifications: the implication is **one-directional** — a ref obliges an edge, an edge obliges no ref; sharing a codebase is **not** an exemption, since two core services of one codebase still meet at a boundary; and a ref in a codebase-level `env:` obliges the edge on **every** core service that receives it.
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
21. `cicl_version` is `"3"`. Earlier generations of the format are rejected, not translated.
22. Every codebase declares a non-empty `core_services:` block, and declares nothing at the codebase level outside `{core_services, secrets, config, env}`.
23. Every core service declares a `command`.
24. *(Retired in 2.0.0.)* Formerly restricted `depends_on` to backing services. There is one relation now, and its shape rule is rule 25.
25. `uses` names either a backing service, bare, or a core service, fully qualified as `<codebase>.<service>`. A bare codebase name is an error, and a core service may not use itself.
26. `replicas` is not declared on a `clock` core service.
27. `worker` and `clock` core services do not declare `web` in `networks`.
28. *(Retired in 2.0.0.)* Formerly required a `port` alongside `health_check_path`. Rule 33 confines `health_check_path` to `web`-network core services and rule 15 already requires a `port` on those, so the obligation is redundant rather than merely obsolete.
29. Every [surface](#surfaces)'s `api_styles` resolve to exactly one contract format. A surface mixing styles of differing formats is an error, not a merge — split it into two surfaces. The rule is *derived* from the style table rather than tabulated against it, so it cannot drift as styles are added.
30. Surface names match the same pattern as codebase and core service names. A surface name is one segment of its contract's filename, which is parsed right-anchored into four fields, so a dot in a surface name makes the path ambiguous.
31. Every core-service `uses` target declares at least one surface. Declaring a surface is what makes a core service a provider; one that declares none has no boundary to be used across, and the edge is an error rather than a missing contract.
32. A `uses` target that its consumer addresses **directly** declares a `port`. A target reached only through a queue or broker declares none — there is no address at which a consumer reaches it, so a port would be decoration. **Directly** means the consumer holds a [magic ref](#magic-refs) to one of the target's provided parts. That is not a proxy for addressing but the doctrine's own definition of it: [§ Rules](#rules) item 2 says services build their URLs from provided fields at startup — that numbered list, not validation rule 2, so a consumer that reaches a sibling by any other means is already outside the rules. The obligation is keyed on the **edge, not the target** — one core service may call a provider over an `rpc` surface while another enqueues to it, and only the first implies a port. A **`web`-network target is exempt from the second sentence**, because [rule 15](#validation-rules) requires a `port` there regardless: a consumer that reaches a public edge by its URL rather than by an internal name holds no ref to it, and without the exemption rules 15 and 32 would contradict each other on the `frontend` / `api` topology. On `elastic` the first sentence is load-bearing beyond validation — a core service registers a resolvable Service Connect name only where it declares a `port`, so a target nothing addresses directly is also a target nothing can resolve. That is correct by construction rather than by coincidence, and it is why the two sentences are one rule.
33. Every `web`-network core service declares `health_check_path`, and no core service off the `web` network declares one. The field is what an ALB probes. It is consumed by the ALB target group on `elastic` **with the default `reverse_proxy: alb`**, and there alone. **Everywhere else it has no consumer at all**, uniformly: on the `ec2_traefik_eip` / `_pip` variants the compiler emits no target group to carry it (traefik's ECS provider reaches tasks by their `traefik.*` labels instead), and on `fixed` it emits no health-aware traefik labels either. So on two of the three reverse-proxy configurations the field is a declaration nothing reads, and it is required anyway so that a project stays portable between them. Note also that neither traefik path routes on health at all: the ECS provider filters targets on `lastStatus == RUNNING`, which is a lifecycle state and not a health verdict. Whether traefik's Docker provider *passively* withholds routing from a container Docker has marked unhealthy is a property of that tool which nothing in this doctrine verifies: **do not rely on it.** On `fixed` the container probe has exactly two consumers, and neither reroutes traffic — Docker, which reports a status and restarts nothing of its own accord, and [`docex stagetest`](./cicd.md#staging-tests), which reads that status and fails a release on it.
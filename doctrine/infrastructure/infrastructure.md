---
stratum: resident
---

# Infrastructure

This document provides a high level overview of infrastructure, what it's formed of, and how we do it.

Infrastructure includes:
1. Computing Machinery - Servers, VMs, containers, etc.
2. Networking - Load balancers, DNS, etc.
3. Data Storage - Databases, object stores, caches, etc.
4. CI/CD - Build, release, test pipeline
5. Observability - Viewing and storing telemetry (logging, traces, and metrics) 
6. Environments - development, staging, production.
7. Credentials e.g. secrets

Note that many of the choices made regarding infrastructure stem from the practices laid down in the "twelve-factor app" guidelines.

## Foundation

The "foundation" of an infrastructure stack defines how it is hosted in production. The choice comes down to whether the project manages the lifecycle of the machines that run its infrastructure. If it cannot manage that lifecycle, the project is on a **fixed** foundation. If it can, the foundation is **elastic**.

1. **Fixed** - The stack is built on a handful of servers (often just one). They represent a fixed resource pool - machines can not automatically scale up or down. Docker containers run on these machines to provide both core and backing services. Many projects and envs will live on one machine.
2. **Elastic** - The stack is built across the cloud, taking advantage of infrastructure-as-a-service abstractions. Tools like ECS, S3, and Route53 form the infrastructure which runs the project.

In this doctrine, much effort has gone into preventing this major choice from affecting the subsidiary pieces. It should be very easy to transition from a **fixed** to **elastic** foundation; the structure of the code will be identical. 

## Infrastructure as Code

The project repository should fully describe both the code and the infrastructure it runs on. To support both possible foundations, there is one source of truth for infrastructure: the `infra.yml` file. It contains everything that is needed to deterministically create either a docker-compose stack or an OpenTofu HCL file, depending on which is needed. It is the one source of truth. It is written in the [*Clausewitzian Infrastructure Configuration Language* (CICL)](./cicl.md), which is a bespoke invention defined in this doctrine.

### Fixed v. Elastic

When we convert `infra.yml` to docker-compose configuration, we are causing our infrastructure to be hosted on a **fixed** set of discrete machines (most often a single machine). When we produce HCL files for OpenTofu, we are causing it to be provisioned from an **elastic** cloud platform.

This dichotomy is identical to that of the two foundations. However, the foundation refers to the production environment alone - an elastic-foundation project will still have a fixed infrastructure stack for its `dev` and `test` environments on a single machine. That machine might be an EC2 instance or a literal on-site server - it doesn't matter. 

### Infrastructure Tiers

There are three tiers, or types, of infrastructure:
1. Prerequisite Infrastructure - These resources exist outside the scope of any project. They are required for the project to work, but are not constructed or configured by the project.
	+ Examples: an AWS account used for an `elastic` setup, the `web_demux` resource in a `fixed` setup, or the master network in both.
2. Project Infrastructure - These resources are configured and controlled within the scope of the whole project. They are required for environment infrastructure to function.
	+ Examples: the project-level reverse proxy (whether ALB or Traefik), the `fixed`-foundation `web`-networks. (Exception: the `test` env's `web` network is *env*-tier, not project-tier — a non-external, per-slot bridge the `test` stack owns, because `test` is never routed or TLS'd. This is what lets `docex test` run with no projinfra up. See [networks.md](./specifics/networks.md).)
3. Environment Infrastructure - These resources are configured and controlled within the scope of a single environment.
	+ Examples: `elastic` SGs, the `postgres` container for each environment, core service containers.

Project infrastructure tends to be shared across all environments whereas environment infrastructure is *duplicated* across environments. Each environment gets an independent copy, although the exact nature of that copy may differ (e.g. between the `fixed` `dev` environment and an `elastic` `prod`).

Of the three tiers, environment infrastructure is by far the least deterministic. It's designed for the project in `infra.yml` and will vary greatly from project to project. Project infrastructure is more constrained; it's configured by top-level `infra.yml` fields but most of the details are worked out deterministically by the [CICL compiler](./cicl.md). Prerequisite infrastructure is not even described by the compiled output, as it by definition can not be controlled from within project scope. `docex` can, however, perform proactive checks on prerequisite infrastructure to check whether or not it exists in the needed form.

NOTE: Sometimes the word **stack** is used informally to describe a set of environment infrastructure components. "Restart the dev stack" would translate to "restart all services for the `dev` environment".

### Infrastructure Sides

There are two "sides" to infrastructure:
1. The Development Side - This contains the `dev` and `test` environments and the project-tier / prerequisite-tier infrastructure resources needed for them to run.
2. The Production Side - This contains the `stage` and `prod` environments and the project-tier / prerequisite-tier infrastructure resources needed for them to run.

The development side is always a `fixed` machine, and the production side is either a `fixed` machine or the `elastic` AWS platform. Sometimes development and production share a single `fixed` machine.

Except in the case of a single `fixed` machine, project-tier and some prerequisite-tier infrastructure is duplicated across the two sides. This makes infrastructure side a distinct conceptual axis. 

## Environments

Every project has four environments: `dev`, `test`, `stage`, and `prod`. Each environment represents a distinct and independent infrastructure stack running some version of the project code. Environments differ from each other in a few ways:
1. **Infrastructure** - Whether infrastructure is **fixed** or **elastic**.
2. **Configuration** - What config the infrastructure runs with.
3. **Purpose** - Naturally, what the purpose of the environment is.

| Environment Name | Aliases | Purpose | Infrastructure |
| ---------------- | ------- | ------- | -------------- |
| `dev` | "development" | Provides a place for active development and testing. | fixed |
| `test` | "testing" | Lets us test a build with fresh, independent fixed infrastructure. | fixed |
| `stage` | "staging" | Lets us test a release with production-equivalent infrastructure. | same as `prod` |
| `prod` | "production" | Where the project runs for real users at scale. | depends on foundation |

True to 12-factor app principles, all environments should be as similar to each other as possible. This is one reason all our infrastructure is derived from the same `infra.yml` file. 

`dev` and `test` are always fixed. This ensures that those environments can run on any developer's machine without cloud credentials, while still allowing production to be elastic.

### The slot axis

Environments are singletons by default, but a **fixed env may be instantiated into multiple isolated *slots* on one machine.** A slot is not a new environment: the env *string* stays singular (`test`), and each slot's stack differs only by a slot *segment* woven into every physical resource name — `{project}_{env}_s{k}_{codebase}_{service}` (e.g. `s2` for slot 2), analogous to a replica but at the environment level. Slot 1 is the default and adds no segment, so a single-slot project is byte-identical to a slotless one. The slot is a **general primitive**: its first and, for now, only user is `test`, which shards its slow integration tier across N isolated stacks on one host; its intended next user is **parallel development** — two agents working different modifications on one machine (see [§ Deferred](#deferred)). Two boundaries hold the primitive cheap: a slot shares its env's configurable values (config and secrets are looked up per env, not per slot — see [configurable.md](./configurable.md)), and the slot lifecycle and ingress models are *not* generalized here (§ Deferred).

## Networking

Networks are ultimately responsible for enabling requests to reach the right targets. This splits handily into two categories which get treated somewhat differently: ingress and egress.

### Ingress

For ingress, we adopt a semi-decentralized approach. Projects sharing an infrastructure space (an AWS account, an on-prem machine) manage their own reverse proxies for inbound traffic, but all exist on one large master network. This gives blast-radius protection against misconfiguration (one project can't misconfigure another's routing), but not against true outage (if the master network goes down, all projects go down).

### Egress

For egress, we adopt a completely centralized model. Projects sharing infra space also share a master network. A single mechanism performs NAT and grants outbound access to the internet. Full centralization does not bear the same misconfiguration risk (outbound configurations are far more stable and rarely change).

## CI/CD Pipeline

Code built with the `doctrine` all uses one standard way to move code from development into production. This way is a CI/CD pipeline, and all projects will use it for build, release, and deployment. An overview of the pipeline is given below to establish standard terminology and indicate the flow of code through our infrastructure. Deeper info can be found [here](./cicd.md).

The code follows the usual process of:
`source` --(build)--> `build artifact` --(containerize)--> `build image` --(release)--> `release`

The overall code-writing process is:
1. Develop freely in `dev`, making changes and testing in accordance with the [mod process](../practices/modifications.md). The result is the project at a specific commit.
	1. Many 'informal' builds will occur during development.
2. Bring up a fresh `test` environment and run unit and integration tests on the informal build at that final commit.
	1. If tests don't pass, errors must be fixed before proceeding.
3. Formally run the new version down the [CI/CD pipeline](./cicd.md#the-pipeline). This will:
    1. Perform git-based actions: rebasing branches, gate checks, version-tagging a commit.
    2. Run formal build tests on the new build.
    3. Build and store the container images.
    4. Release to stage and run staging tests.
    5. Release to production.

Essentially the entire pipeline can be performed using `docex` commands.

## Repository Structure
One of the core tenets of the `doctrine` is that filepaths encode meaning. By looking at a file's location in the project folder structure, both its location in infrastructure and its architectural purpose should be clear. Architecture path structure is discussed elsewhere in the [hex docs](../hexagonal_architecture/hex_overview.md). Infrastructure path structure is described here.

Projects are composed of *services*:
+ **backing services** which are *not* maintained by the project (e.g. postgres, object stores), and
+ **core services** built from **codebases** which *are* maintained by the project.

Both take the form of containers and both are described by `infra.yml`. However, **codebases** are substantially more complex. Each codebase produces exactly one build artifact, which can be invoked in one or many ways via the [core services](./cicl.md#core-services) it declares. For example, a single codebase might be invoked as one core service to operate as an HTTP-based API *and* as another as a queue-based worker.

This doctrine sets down some hard rules for codebases and their core services:
1. **Codebases never share code**. Each codebase is a distinct source tree. This is a strict choice intended to enforce separation of concerns and prevent confusion. Choosing *how* to achieve this in practice is a design concern. Codebases are very distinct; all that ties them together is a shared purpose, backing services, and build version. Core services of the *same* codebase, by contrast, share everything — they are one artifact started different ways.
2. **Core services execute as stateless processes**. This is a direct principle of the 12-factor app. Processes are stateless and share nothing. All persistent data is stored in a backing service like a database.

An example project structure is shown below:
```
$pr
├── .gitignore
├── README.md
├── CHANGELOG.md
├── project.yml
├── core
│   ├── api
│   │   ├── Dockerfile
│   │   ├── dist
│   │   ├── src
│   │   ├── tests
│   │   ├── migrations
│   │   ├── test.sh
│   │   ├── build.sh
│   │   ├── health.sh
│   │   └── migrate.sh  # Only if needed
│   └── frontend
├── infra
│   ├── infra.yml
│   ├── contracts
│   │   ├── api.web.rest.openapi.yml
│   │   └── api.worker.events.asyncapi.yml
│   ├── stage
│   │   ├── stage_test.sh
│   │   ├── Dockerfile
│   │   └── tests
│   ├── output
│   │   ├── project
│   │   │   ├── development
│   │   │   └── production
│   │   ├── dev
│   │   ├── test
│   │   ├── stage
│   │   └── prod
│   ├── secrets
│   │   ├── dev.env
│   │   ├── test.env
│   │   ├── stage.env
│   │   └── prod.env
│   ├── config
│   │   ├── dev.env
│   │   ├── test.env
│   │   ├── stage.env
│   │   └── prod.env
│   ├── tte
│   │   ├── dev.env
│   │   └── test.env
│   └── deploy_creds
│       ├── .gitignore
│       ├── README.md
│       ├── stage
│       ├── stage.pub   # Not required but conventional
│       ├── prod
│       └── prod.pub    # Not required but conventional
└── plans
    ├── modifications
    ├── core
    └── references
```

Codebases go in the `core` folder. Each is given a name (like `api`) that will match the key under `codebases` in `infra.yml`. Each of these folders is a *codebase root* and will always contain:
+ `dist` - host folder where `build.sh` writes artifacts during dev iteration via the dev container's bind-mount. The formal containerize path keeps artifacts entirely inside `docker build` and does not touch this folder. Typically gitignored.
+ `src` - a folder that contains all source code. Structure within this folder is an architectural concern.
+ `tests` - contains all the tests that `test.sh` will run.
+ `migrations` - contains all migrations that `migrate.sh` will run.
+ `build.sh` - the [build script](./cicd.md#build-step).
+ `test.sh` - the [test script](./cicd.md#build-test-step).
+ `migrate.sh` - the [migrate script](./cicd.md#migrate-step).
+ `health.sh` - the [health probe](./healthchecks.md#the-probe), invoked per core service.
+ `Dockerfile` - the dockerfile which configures the container.

It can also contain a variety of other things depending on the service and its needs.

Infrastructure configuration goes in the `infra` folder. It will contain the critical `infra.yml` and any other infrastructure config that isn't required at the project root.

Lastly, documentation and plans go in the `plans` folder. This is covered much more deeply [here](../practices/docs.md).

### Project Config

Project-scope information is stored in `project.yml`. This is a plain-yaml manifest. It contains:
+ **Project name** - Global project name. Used to string-interpolate many infrastructure names.
+ **Project version** - See [version_control](./version_control.md#format) for more info on the format.

Example `project.yml` file:
```yml
name: some_project
version: "0.0.1"
docex_version: "0.1.0"
```
The `docex_version` field pins which `docex` image runs against the project; it is written by [`docex_install.sh`](./docex.md#project-installation), not by hand.

### Version Control

Version control is done with git using [trunk-based branch conventions](./version_control.md#branch-conventions).

### Codebase Containers

Every codebase must have a Dockerfile which describes the environment the container provides to the code.

Every container built from a codebase places the working directory at a fixed root: `/service`. This root maps to the "codebase folder" in the source code, e.g. `api` in the above example project. Every core service of a codebase runs the same image and therefore sees the same `/service`. `docex` relies on this convention:
1. It bind-mounts to this `/service` in compiled compose.yml output.
2. It expects to find the codebase's scripts like `migrate.sh` at `/service/migrate.sh`.

Dockerfiles will all describe multi-stage builds. The following list of stages must be available for *all* codebases, as the CI/CD scripts will reference them by name. Additional stages may be added "in between" the standard stages if the developer desires.

| Stage Name | CI/CD purpose |
| ---------- | ------------- |
| build | Runs `build.sh` against `src/` to produce the build artifact in `dist/`. The `prod` and `test` stages copy from this stage. Never run as a container itself. |
| dev | Used when "informally" building the container for the `dev` environment. Carries the same build tools as `build` so the developer can re-invoke `build.sh` against bind-mounted source without rebuilding the image. |
| prod | Used when "formally" building the container to upload to the container registry for `stage` and `prod`. Receives the build artifact via `COPY --from=build`. |
| test | Based on `prod` but adds test-running libraries for unit and integration tests for our `test` environment. |

`build.sh` is the canonical build entry point and is invoked by the `build` stage during `docker build`. See [Build Step](./cicd.md#build-step) for how `build.sh` is shared between the formal and dev-iteration paths.

A codebase's Dockerfile `CMD` is not used. Every core service declares its own [`command`](./cicl.md#core-services) in `infra.yml`, which is what the compiler emits — so with several core services sharing one image, no `CMD` could be correct for all of them, and the ambiguity is deleted rather than answered.

Every image must be able to run `./health.sh <service>` for each core service it hosts. What that requires — an HTTP client, a file stat, a language runtime — is the project's to install. See [healthchecks.md](./healthchecks.md).

### Contracts

Contracts define the boundaries of core services. They exist both:
1. As a form of documentation, making it easy for a developer to know how to interact with a core service from the outside without having to understand the interior.
2. To allow contract testing, the details and benefits of which are discussed [here](./tests.md#contract-tests).

The idea is that all [core services](./cicl.md#core-services) are either providers, consumers, or both. A very simple case is a webapp with two codebases: `frontend` and `api`, where `frontend` declares one core service `web` (a webapp) and `api` declares two core services: `web` (an HTTP edge) and `worker` (a queue consumer). The `frontend` communicates with `api.web` over HTTP and `api.web` communicates with `api.worker` over a task queue. This makes:
+ `frontend.web` a consumer only
+ `api.web` a provider and a consumer
+ `api.worker` a provider only

In practice, these relationships are declared by `infra.yml`'s [uses](./cicl.md#uses-relationships) field.

Providers have one contract per [surface](./cicl.md#surfaces), stored at `$pr/infra/contracts/${codebase}.${service}.${surface}.${format}.${ext}`. The format follows from the surface's declared `api_styles`. In the above example:
+ `frontend.web` declares no surfaces — it serves a browser, not a described boundary — so it has no contract.
+ `api.web` declares a `rest` surface, giving `api.web.rest.openapi.yml`.
+ `api.worker` declares an `events` surface, giving `api.worker.events.asyncapi.yml`.

See [contracts](./contracts.md) for more info on formats, requirements, and the like.

Every declared surface *must* have a contract to pass CI checks. Declaring a surface is what makes a core service a provider; a core service that declares none cannot be a `uses` target.

### Infra Filestructure

The `infra` folder holds our infrastructure concerns - driving config, compile config, secrets, and CI/CD credentials.

**output** - Contains the compiled output. Each `infra/output/${env}` folder holds env-tier compose config or HCL files (depending on environment and foundation), and `infra/output/project/{development,production}/` holds the project-tier output for each side. See [compiler output](./cicl.md#compiler-output) for details.
**secrets** - The source of truth for all [secrets](./configurable.md#secrets). Can be generated with `./bin/docex secrets scaffold`.
**config** - The source of truth for all [config](./configurable.md#config). Can be generated with `./bin/docex config scaffold`.
**tte** - Read-only records of [tte vars](./configurable.md#tte-vars) for `dev` and `test`. Generated and managed by `docex`.
**deploy_creds** - Currently used only for `fixed` foundation deployments, this folder holds credentials needed to run the ansible deployment step. These take the form of private keys; corresponding public keys may also be stored there. See [this](./credentials.md#deploy-credentials) for more info.
**stage** - Contains necessary files to perform [stage tests](./tests.md#staging-tests).
**contracts** - Contains contracts which describe core services' [surfaces](./cicl.md#surfaces).

## Observability

This spans the creation of telemetry signals (logs, metrics, traces), their movement through the infrastructure, and the means by which we actually query and view those signals.

Put succinctly, *what gets reported* is a design concern and *how it moves across infrastructure* is a deterministic `docex` concern. It is the project developer's responsibility to follow good [logging practices](../practices/logging.md) within core service code. The infrastructure side is almost entirely deterministic.

See [telemetry](./telemetry.md) for more details.

## Credentials

A credential is any piece of information that *certainly* can not be made public.

This covers:
1. Deploy credentials - the credentials that enable us to control and change infrastructure
2. Secrets - which allow our services to communicate with each other.

More details [here](./credentials.md)

## Deferred

Some things must be deferred for now:
1. Multi-machine `fixed` foundation. We will one day support multiple machines, but this will involve docker-swarm and some other complexities. We assume only one machine for now, hosting all environments.
2. Automated CI/CD flow (in the sense that a pull request kicks off the process). All CI/CD can be achieved with `docex` commands; this can be done manually by a developer with strict discipline. These commands could be worked into GitHub, GitLab, or some other service. That's beyond the scope of this version.
3. Fundamental stage tests. This edition of the doctrine places writing and maintenance of the stage tests entirely in the hand of the developer. A future version could probably define some standard things (e.g. DNS and TLS checks) which run alongside project-defined stage tests.
4. Real defense-in-depth with networks, permissions, and validation cross-service.
5. GPU workloads on `elastic` foundations. The doctrine commits to Fargate for elastic compute, and Fargate does not run GPU workloads; `resources.gpu` is therefore `fixed`-only and rejected on elastic compiles.
6. Parallel development on the slot axis. The [slot axis](#the-slot-axis) is the runtime-name isolation needed for two agents to work different modifications on one machine, and it is delivered now for `test`-sharding. Full parallel development additionally needs code isolation (git worktrees) and, for *browsable* dev stacks, ingress multiplicity (per-slot routing / DNS / cert) — the latter genuinely hard because `dev`, unlike `test`, is publicly routed and TLS'd. Two properties are **explicitly not generalized** with the slot primitive: the slot *lifecycle* (test slots are fungible and reaped when idle; a dev slot is owned by a branch and must survive when idle — antithetical policy on the same name/lock primitive), and ingress multiplicity (untouched). Headless parallel dev (code + tests, no browsing) nearly falls out of the slot axis directly; browsable parallel dev needs the ingress work.
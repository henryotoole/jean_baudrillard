# Mod 094 — Implementation Steps

Doctrine prose only. **No `docex` code, no transfer tables, no tests, no version
artifacts.** Design rationale is in [`overview.md`](./overview.md); the settled
design record is
[`service_processes_refactor.md`](../../advances/004_next/service_processes_refactor.md).

## Ground rules

1. **Repo root** is `/home/ubuntu/.claude/jean_baudrillard`. All paths below are
   relative to it.
2. **The working tree is already dirty** with a large pre-existing
   `docex/plans/campaigns/` → `docex/plans/advances/` rename and ~100 touched
   mod docs. **That is not your work.** Do not commit it, revert it, `git add -A`,
   or otherwise disturb it. Do not run `git commit` at all — the mod cycle's
   commits are taken by the orchestrator.
3. **Do not touch** `doctrine/infrastructure/{cicd,docex,shape,tests,telemetry}.md`,
   `doctrine/infrastructure/specifics/*`, or `doctrine/infrastructure/preinfra/*`.
   Those are Mod 106's scope and will read stale against your output for the rest
   of the advance. That is intended.
4. **Preserve voice and structure.** The doctrine's language is deliberate.
   Prefer surgical edits to rewrites. Keep existing heading levels, list styles,
   link styles (`[text](./path.md#anchor)`), and — critically — the **tab
   indentation** used inside `cicl.md`'s YAML blocks.
5. **Never remove or rename an existing heading.** Every new section is an
   addition. `### Depends-On Relationships` in `cicl.md` and `### Health Checks`
   in `contracts.md` keep their headings; only their bodies change.
6. Terminology, used consistently: a **core service** is a codebase + build
   artifact; it declares one or more **process types**; a process type's
   `command` invokes an **entrypoint** (a code module). Reference form is dotted
   (`api.web`); emitted form is hyphenated (`api-web`).

---

## File 1 — `doctrine/lexicon.md`

### 1.1 Clarify **Core Service**

Replace the `Core Service` row:

```
| Core Service | "application service", "application container" | Any service that executes code which is unique to this project. |
```

with:

```
| Core Service | "application service" | A codebase of project-unique code and the single build artifact produced from it. One source folder, one image, and one or more [process types](#) that invoke it. |
```

Drop the `"application container"` synonym — a core service is no longer one
container. Replace the `(#)` placeholder with no link (the lexicon table does not
link out); the row should simply read `one or more process types that invoke it.`

### 1.2 Add two rows

Insert **immediately after** the `Backing Service` row, preserving column
alignment style:

```
| Process Type | | A named, independently-scaled way of invoking a core service's build artifact — its own role, command, resources, networks, and port. One core service declares one or more. 12-factor's term for this axis. |
| Entrypoint | | The *code module* a process type's `command` invokes. Binds the composition root's driving adapters to a runtime host. Not an infrastructure noun — the word is already spent on the Dockerfile `ENTRYPOINT` and on traefik entrypoints. |
```

---

## File 2 — `doctrine/hexagonal_architecture/internal_dependency_rules.md`

### 2.1 Rewrite the composition-root responsibility list

Replace:

```
The composition root is responsible for:
1. Instantiating every concrete driven adapter.
2. Instantiating every alogic service, injecting the adapters created in step 1.
3. Instantiating every driving adapter (controller), injecting the services created in step 2.
4. Registering every HTTP controller's router with the application.

This means the dependency graph is fully visible and fully traceable from one file, making it easy to understand what concrete implementation is used at every layer.
```

with:

```
The composition root is responsible for:
1. Instantiating every concrete driven adapter.
2. Instantiating every alogic service, injecting the adapters created in step 1.
3. Instantiating every driving adapter (controller) for **every** mechanism, injecting the services created in step 2 — including controllers the currently-running process type will never use. Controller construction is free: it captures a port reference and performs no I/O.

This means the dependency graph is fully visible and fully traceable from one file, making it easy to understand what concrete implementation is used at every layer.

The composition root **constructs**; it does not **activate**. It builds no server, opens no socket, and consumes no queue. Binding the constructed adapters to something that actually runs is the entrypoint's job.
```

### 2.2 Add a new `## Entrypoints` section

Insert **between** `## Composition Root` and `## No Self-Instantiation`:

```
## Entrypoints

A core service's build artifact can be invoked in more than one way — an HTTP edge, a queue consumer, a scheduled job. Each such invocation is a [process type](../infrastructure/cicl.md#process-types), and each process type's `command` invokes exactly one **entrypoint**: a module under `src/entrypoints/` whose only job is to take the graph the composition root built and hand the relevant driving adapters to a runtime host.

**One composition root; one entrypoint per process type.** The rules:

1. An entrypoint calls the composition root's build function and **never** a concrete adapter constructor. The no-self-instantiation rule below is unaffected.
2. **The runtime host is not an adapter.** Nobody ever thought uvicorn was an adapter; a broker's consume loop is not one either. Both belong to the entrypoint. The adapter's job is *translation* — and on the queue side, the return half of that translation is the ack / nack / retry decision.
3. **Never split the root** into `root_web.py` / `root_worker.py`. Two copies of the driven wiring drift, which is precisely the bug class module integration tests exist to catch (see "composition-root mistakes" in [hex_overview.md § Tests](./hex_overview.md#tests)).
4. Where a client library **inverts control** — Celery-style decorators that register handlers at import time — register in the entrypoint, calling into the adapter's handler. A decorator inside the adapter leaks the framework into the module and destroys mocked-port testability.
5. A driven adapter that is genuinely expensive and needed by only one process type should be **lazy internally**, rather than forking the root. If that feels like a band-aid, the honest question is whether this is really a second app.
6. A long-running entrypoint that owns a loop **must expose that loop's liveness**. See [contracts.md § Health Checks](../infrastructure/contracts.md#health-checks) for the required mechanism and thresholds.
```

Do **not** restate the tick mechanism or the 10 s / 30 s thresholds here — rule 6
is a router into the conditional stratum, which is where the specification lives.

---

## File 3 — `doctrine/hexagonal_architecture/hex_overview.md`

### 3.1 Add `entrypoints/` to the `src/` tree

In the `### Structure Specifics` tree under `## Project Structure`, insert
between `│   ├── root.py` and `│   ├── hex`:

```
│   ├── entrypoints
│   │   ├── http.py
│   │   └── worker.py
```

### 3.2 Add a folder-purpose row

In the table below that tree, insert **immediately after** the `root.py` row:

```
| `entrypoints` | One module per [process type](../infrastructure/cicl.md#process-types). Each takes the graph `root.py` built and binds the relevant driving adapters to a runtime host (an ASGI server, a consume loop, a CLI). See [internal_dependency_rules.md § Entrypoints](./internal_dependency_rules.md#entrypoints). |
```

### 3.3 Add a `Queue` row to the controller-mechanism table

In `#### Controller Mechanism`, insert after the `Http` row (keeping `Cli`, `Ws`,
`Grpc` in their current order below it):

```
| `Queue` | Consumes messages from a queue or stream and drives the module with them. | `ContBrokerQueue` |
```

Note for the implementor, not for the file: this is deliberate — a queue consumer
is a *driving* adapter on the same driving port as the HTTP controller, which is
why the driven-pattern table's `Queue` (the producer side) and this row can
coexist without conflict.

### 3.4 Add the entrypoint-testing note

At the **end** of the `### Tests` section — after the "5. Service Integration /
Flow Tests" prose and **before** the `#### Structure` subheading — add a short
paragraph:

```
**Entrypoints are not a test tier.** An entrypoint should be too thin to be worth testing: it calls the composition root and hands the result to a runtime host. If an entrypoint needs a test of its own, it is doing too much, and the surplus belongs in a driving adapter (translation) or in alogic (orchestration).
```

---

## File 4 — `doctrine/infrastructure/infrastructure.md`

### 4.1 Re-scope "core services never share code"

Replace rule 1 under `## Codebase Structure`:

```
1. **Core services never share code**. This is a strict choice intended to enforce separation of concerns and prevent confusion. Choosing *how* to achieve this in practice is a design concern. Core services are very distinct; all that ties them together is a shared purpose, backing services, and build version.
```

with:

```
1. **Core service sources never share code**. This is a strict choice intended to enforce separation of concerns and prevent confusion. Choosing *how* to achieve this in practice is a design concern. Core services are very distinct; all that ties them together is a shared purpose, backing services, and build version. Note the scope: the rule governs *sources*. A core service may be invoked several ways — an HTTP edge, a queue consumer, a nightly job — and those [process types](./cicl.md#process-types) all run the same codebase and the same image, so nothing is shared between them and the rule is not engaged. When only the *invocation* differs, the answer is another process type, not another core service. Two core services are for two genuinely distinct codebases: a different bounded context, a different language, a radically different runtime footprint, or a different security posture.
```

### 4.2 Retarget the example codebase tree

In the tree under "An example codebase is shown below", replace the `core`
subtree:

```
├── core
│   ├── web
│   │   ├── Dockerfile
│   │   ├── dist
│   │   ├── src
│   │   ├── tests
│   │   ├── migrations
│   │   ├── test.sh
│   │   ├── build.sh
│   │   └── migrate.sh  # Only if needed
│   └── worker
```

with:

```
├── core
│   ├── api
│   │   ├── Dockerfile
│   │   ├── dist
│   │   ├── src
│   │   ├── tests
│   │   ├── migrations
│   │   ├── test.sh
│   │   ├── build.sh
│   │   └── migrate.sh  # Only if needed
│   └── frontend
```

and in the same tree replace the `contracts` subtree:

```
│   ├── contracts
│   │   ├── web.openapi.yml
│   │   └── worker.asyncapi.yml
```

with:

```
│   ├── contracts
│   │   ├── api.web.openapi.yml
│   │   └── api.worker.asyncapi.yml
```

**Why:** `web` and `worker` are now process types of one codebase, so showing
them as sibling core services would contradict § Contracts further down this same
file. `api` + `frontend` is a genuinely-separate-codebases pair.

### 4.3 Follow the ripple in the prose below the tree

Replace:

```
Core services go in the `core` folder. Each is given a name (like `web`) that will match the name in `infra.yml`. Each of these folders is a *core service root*. One of these service roots will always contain:
```

with:

```
Core services go in the `core` folder. Each is given a name (like `api`) that will match the key under `core_services` in `infra.yml`. Each of these folders is a *core service root* — one codebase, one build artifact, however many [process types](./cicl.md#process-types) that artifact is invoked as. One of these service roots will always contain:
```

### 4.4 Fix the `/service` prose in § Core Service Containers

Replace:

```
All core service containers place the service working directory at a fixed root: `/service`. This root maps to the "core service folder" in the source code, e.g. `web` in the above example codebase. `docex` relies on this convention:
```

with:

```
All core service containers place the service working directory at a fixed root: `/service`. This root maps to the "core service folder" in the source code, e.g. `api` in the above example codebase. Every process type of a core service runs the same image and therefore sees the same `/service`. `docex` relies on this convention:
```

### 4.5 Note that `command` supersedes the Dockerfile `CMD`

In § Core Service Containers, **after** the multi-stage build-stage table and its
following `build.sh` paragraph, and **before** the `curl` paragraph, insert:

```
A core service's Dockerfile `CMD` is not used. Every process type declares its own [`command`](./cicl.md#process-types) in `infra.yml`, which is what the compiler emits — so with several process types sharing one image, no `CMD` could be correct for all of them, and the ambiguity is deleted rather than answered.
```

### 4.6 Rewrite § Contracts

Replace:

```
The idea is that all core services are either providers, consumers, or both. A very simple case is a webapp with a `frontend` service, a `web` service, and a `worker` service. The `frontend` communicates with `web` over HTTP and `web` communicates with `worker` over a task queue. This makes:
+ `frontend` a consumer only
+ `web` a provider and a consumer
+ `worker` a provider only

In practice, these relationships are inferred from `infra.yml`'s [depends-on](./cicl.md#depends-on-relationships) relationships between core services.

Provider services have a contract which is stored at `$pr/infra/contracts/${service_name}.${contract_format}.yml`. The contract format is dependent upon the communication mechanism between the provider service and its consumers. In the above example:
+ `frontend` has no contract, as it is only a consumer relative to other core services.
+ `web` has contract `web.openapi.yml` because it is driven by a request-based interface.
+ `worker` has contract `worker.asyncapi.yml` because it is driven by a queue system.
```

with:

```
The idea is that all core service [process types](./cicl.md#process-types) are either providers, consumers, or both. A very simple case is a webapp with a `frontend` core service and an `api` core service, where `api` declares two process types: `web` (an HTTP edge) and `worker` (a queue consumer). The `frontend` communicates with `api.web` over HTTP and `api.web` communicates with `api.worker` over a task queue. This makes:
+ `frontend.web` a consumer only
+ `api.web` a provider and a consumer
+ `api.worker` a provider only

Note that `api.web` and `api.worker` are one codebase and one image, and are still a genuine boundary between them: sharing source does not make a queue any less of an interface.

In practice, these relationships are declared by `infra.yml`'s [consumes](./cicl.md#consumes-relationships) field.

Provider process types have a contract which is stored at `$pr/infra/contracts/${service_name}.${process_name}.${contract_format}.yml`. The contract format follows from the provider's role — a request-based boundary is OpenAPI, a queue-based one is AsyncAPI. In the above example:
+ `frontend.web` has no contract, as it is only a consumer relative to other core services.
+ `api.web` has contract `api.web.openapi.yml` because it is driven by a request-based interface.
+ `api.worker` has contract `api.worker.asyncapi.yml` because it is driven by a queue system.
```

### 4.7 Sweep the rest of the file

Grep `doctrine/infrastructure/infrastructure.md` for `worker` and `core/web` and
confirm no other occurrence still presents them as sibling *core services*. Leave
alone any occurrence that is correct in the new model.

---

## File 5 — `doctrine/practices/logging.md`

Single edit. Replace:

```
read it with `docker compose logs -f <svc>-otelcol`
```

with:

```
read it with `docker compose logs -f <svc>-<proc>-otelcol`
```

(Each long-running process type is paired with its own collector sidecar, so the
container name carries both segments.)

---

## File 6 — `doctrine/infrastructure/cicl.md`

The largest file. Work top to bottom.

### 6.1 The worked `infra.yml` example (§ The CICL Format)

Replace the whole fenced ```yml block. **Preserve tab indentation** exactly as
the surrounding file uses it. New content:

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

Immediately **after** the closing fence, add this paragraph:

```
Two things in that example are worth naming. `api.web` and `api.worker` each `consumes` the other — a legal cycle, and the most common web/worker topology there is; see [Consumes Relationships](#consumes-relationships). And the `worker` process type's broker is the `cache` backing service: the doctrine ships no dedicated `queue` role, so a redis broker is declared under the `cache` role. `depends_on` names only backing services, which is why the worker's dependency on `api.web` appears under `consumes` and not there.
```

### 6.2 New section `### Process Types`

Insert **immediately after** that new paragraph and **before** `### Service Fields`.

```
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
```

### 6.3 § Service Fields — rescope the table

Replace the column header `| Core or Backing Service |` with `| Scope |` and
rewrite the table body. The full replacement table:

```
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
```

Then replace the paragraph immediately below it:

```
Note that core services do **not** declare an `image` field. Image references are derived deterministically by the compiler from the top-level [`container_registry`](#container-registry-and-service-images), the project name and version (from `project.yml`), and the service name. See [Container Registry](#container-registry-and-service-images) for the full format.
```

with:

```
Note that core services do **not** declare an `image` field. Image references are derived deterministically by the compiler from the top-level [`container_registry`](#container-registry-and-service-images), the project name and version (from `project.yml`), and the core service name. The image is keyed on the **codebase**, so every process type of a core service runs the same image. See [Container Registry](#container-registry-and-service-images) for the full format.
```

Leave the two paragraphs after that (magic refs, role-specific fields) as they are.

### 6.4 § Environmental Variables — note the two levels

At the end of that section, after the "A given key may appear in **at most one**…"
paragraph, append:

```
Of the three, only `env:` is valid at both the core service and the process type level; `secrets:` and `config:` are codebase-scoped and declared once on the service. A process type's effective environment is the service-level `env:` merged under its own, and the disjointness rule above is evaluated against that effective set. See [Process Types § Field scoping](#field-scoping).
```

### 6.5 New section `### Magic Refs`

Insert **immediately after** `### Provided Fields` and before
`### Environmental Variables`.

```
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
```

### 6.6 § Domain — the two-segment label

Replace:

```
The anatomy of a project's domain is rigidly defined and critical to the "just works" nature of CICL machinery. A full domain describes a specific service container uniquely across all projects. The form is:

`<service>.<env>.<project_name>.<apex_domain>` e.g. `api.dev.myproject.example.com`

Simply by assessing the domain of a request, any machinery with no further context can determine the destination project name, environment, and service container. The `infra.yml` config `apex_domain` field sets the project's bare apex domain e.g. `example.com` or `example.co.uk`. Projects may or may not share apex domains with other projects.
```

with:

```
The anatomy of a project's domain is rigidly defined and critical to the "just works" nature of CICL machinery. A full domain describes a specific process type uniquely across all projects. The form is:

`<service>-<process>.<env>.<project_name>.<apex_domain>` e.g. `api-web.dev.myproject.example.com`

Simply by assessing the domain of a request, any machinery with no further context can determine the destination project name, environment, and service. The `infra.yml` config `apex_domain` field sets the project's bare apex domain e.g. `example.com` or `example.co.uk`. Projects may or may not share apex domains with other projects.

#### The service label is single and hyphen-joined

The process type occupies the *same* label as the core service, joined by a hyphen — `api-web.dev.…`, never `web.api.dev.…`. Three independent reasons, any one of which is decisive:

1. **TLS wildcards cover exactly one label.** The elastic certs are `*.stage.<project>.<apex>`; a `web.api.stage.…` host sits two labels deep and is uncovered, and multi-level wildcards are not valid in TLS, so no cert could cover it.
2. **The domain parse is positional.** The promise above — that machinery with no further context can determine project and environment — holds because the anatomy has a fixed number of parts.
3. The [bare-env and bare-project routes](#bare-subdomains) are defined relative to that four-part form.

**Nothing ever reverse-parses the label back into `(service, process)`.** This is worth stating, because `api-web` looks ambiguous — it could be service `api` + process `web`, or a service literally named `api-web`. Nothing cares. The master network's demux parses the domain *right-anchored* (public suffix, then apex, then the project label immediately left of it) and has no opinion about how many labels sit further left; traefik and the ALB match whole host strings that the compiler generated. The label is a rendered output, never an input to be decomposed. What the ambiguity *does* require is that rendered identities be unique — see [validation rule 5](#validation-rules).

#### Dots for reference, hyphens for emission

One rule covers the whole system. Authoring and reference forms are **dotted**: `consumes:` targets, `domain_default_process`, [magic refs](#magic-refs), and `describe` node ids. Emitted data-plane names are **hyphenated**: container names, security groups, hostnames, log streams, and traefik router keys.
```

### 6.7 § Bare Subdomains — rename the field

In the table, replace `Route to env's `domain_default_service`.` with
``Route to env's `domain_default_process`.``

### 6.8 § Container Registry and Service Images

Replace:

```
with `name` and `version` from `project.yml` and `service_name` from the CICL key under `core_services`. Each core service gets its own image; all images for a project share the project-wide version.
```

with:

```
with `name` and `version` from `project.yml` and `service_name` from the CICL key under `core_services`. Each core service gets its own image; all images for a project share the project-wide version.

The image is keyed on the **codebase**, not the process type. A core service declaring three [process types](#process-types) produces one image, which all three run with different [`command`](#process-types) values. This is the joint the doctrine holds at 1:1 — one codebase, one build artifact — while the artifact-to-process-type joint is 1:N.
```

### 6.9 § Networks

After the numbered list of special network names (the `web` entry), append a
paragraph:

```
`web` membership is restricted on core services: only a `role: web` process type may declare it. A `worker` or `scheduler` process type that wants public ingress *is* a web process type, and should say so. Network membership is declared per **process type**, not per core service — the web edge and the queue consumer of one codebase routinely sit on different networks.
```

### 6.10 § Resources

Replace:

```
The `resources:` field on a core service declares the computing resources the service requires at runtime. It is **required** on every core service.
```

with:

```
The `resources:` field declares the computing resources a [process type](#process-types) requires at runtime. It is **required** on every process type — sizing is invocation-determined, so a web edge and a queue consumer of the same codebase size independently. It is not valid at the core service level.
```

In the same section's **Notes** list, append a bullet:

```
- Compile errors on this block name the full path, e.g. `core_services.api.processes.worker.resources.disk`.
```

### 6.11 § Depends-On Relationships — rewrite the body, keep the heading

**Do not rename the heading.** Replace the body:

```
The relationships between services defined by the `depends_on` block serve several roles:
1. It provides the DAG needed for the compiler to produce infrastructure config which brings infrastructure online in the right order.
2. It describes the [provider / consumer](./infrastructure.md#contracts) relationship between core services. This allows the compiler to ensure these relationships are defined properly; [CI/CD](./cicd.md) `docex` checks rely on this relationship.
3. It defines a dependency chain which lets us check which services are "downstream" in the chain from others.

Furthermore, if Service A references Service B's information via magic ref, then A depends on B. If that relationship doesn't actually show up in A's `depends_on` field, the compiler will trip an error.
```

with:

```
`depends_on` is a **readiness gate**, and it names **backing services only**. It provides the DAG the compiler needs to bring infrastructure online in the right order: a process type that declares `depends_on: [database]` is not started until the database is healthy.

A core process type may **not** appear in a `depends_on` list. Interface coupling between core process types is a different relation with different rules, and lives in [`consumes`](#consumes-relationships).

Furthermore, if a process type references a backing service's information via [magic ref](#magic-refs), it depends on that backing service. If the relationship doesn't show up in the process type's `depends_on` field, the compiler will trip an error.

**`depends_on` is a convenience, never a correctness guarantee.** It is honoured on `fixed` foundations, where the compiler emits it as a compose `condition:`. On `elastic` it is discarded, because it *cannot* be honoured: ECS has no cross-service ordering primitive, and even a deploy-time emulation would hold exactly once and then be silently violated forever after, as ECS independently replaces tasks for scaling, AZ rebalance, failed health checks, and platform updates.

> **Startup ordering is not a substitute for connection resilience.**

Every service must tolerate its dependencies being absent at any moment — not only at startup — because on elastic they will be. Reconnect, back off, and fail requests cleanly; do not assume a dependency that was reachable a second ago still is.
```

### 6.12 New section `### Consumes Relationships`

Insert **immediately after** § Depends-On Relationships, before
`### Reverse Proxy`.

```
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
```

### 6.13 New section `### CICL Version`

Insert **immediately after** `### Git Repo URL` and before
`### Observability Backend` — that is, among the other top-level-field sections.

```
### CICL Version

The top-level `cicl_version` field declares which generation of the CICL format `infra.yml` is written in. The current version is **`"2"`**, which introduced the mandatory [`processes:`](#process-types) block, the [`consumes`](#consumes-relationships) relation, and four-segment [core magic refs](#magic-refs).

`cicl_version: "1"` is **rejected**, not shimmed. A compatibility parser accepting both forms would reintroduce the flat pre-`processes:` shape as a permanent second code path, in exchange for serving a migration that every project performs exactly once. The compiler fails with a message naming the relevant project-upgrade guide.

One consequence is worth knowing before it is needed: a [rollback](./cicd.md#rollback) recompiles the target version's `infra.yml` with the *current* compiler, so rollback across the v1 → v2 boundary is not possible. It aborts at pre-flight, before anything is applied, with a fix-forward message.
```

### 6.14 § Validation Rules — restate and append

Replace rules **5, 7, 10, 12, 14, 15, 16** in place (keeping their numbers and
the surrounding rules untouched):

```
5. The rendered data-plane identity of every emitted service must be unique after naming-policy normalization. The set spans core process types **and** backing services, since both render into the same namespace.
```

```
7. Magic refs which imply a dependency must be matched by a corresponding edge, of the kind the target calls for: a ref to a **backing service** must be matched by a `depends_on` entry on the referencing process type; a ref to a **core process type** must be matched by a `consumes` entry. See [Consumes Relationships](#consumes-relationships) for the one-directional, same-codebase, and service-level-`env:` clarifications.
```

```
10. Every core service **process type** has a `resources:` block declaring at least `cpu` and `memory`.
```

```
12. `domain_default_process`, if set, names a process type that is on the `web` network.
```

```
14. Neither core service names nor process type names can be one of the following: [`dev`, `test`, `stage`, `prod`, `www`], because it makes domain parsing challenging and because a process named `prod` renders `api-prod.dev.myproject.example.com`, which reads as a production host in a dev environment.
```

```
15. Every `web`-network **process type** declares a `port`.
```

```
16. A process type's *effective* `env:` (service-level merged under process-level) does not declare a key that also appears in the core service's `secrets:` or `config:`.
```

Then **append** seven new rules after rule 20:

```
21. `cicl_version` is `"2"`. Earlier generations of the format are rejected, not translated.
22. Every core service declares a non-empty `processes:` block, and declares nothing at the service level outside `{processes, secrets, config, env}`.
23. Every process type declares a `command`.
24. `depends_on` names only backing services. A core process type in a `depends_on` list is an error.
25. `consumes` names only core process types, fully qualified as `<service>.<process>`. A bare core service name is an error, and a process type may not consume itself.
26. `replicas` is not declared on a `scheduler` process type.
27. `worker` and `scheduler` process types do not declare `web` in `networks`.
```

Also amend rule 6 in place, to head off the obvious question:

```
6. Cyclic dependency chains with `depends_on` are not allowed. (Cycles in `consumes` **are** allowed — see [Consumes Relationships](#consumes-relationships).)
```

### 6.15 § Naming and Tagging

Under `#### Fixed Foundation`, replace:

```
2. Docker containers `${project}-${env}-${service}`
```

with:

```
2. Docker containers `${project}-${env}-${service}-${process}`
```

Under `#### Elastic Foundation`, in the `envinfra_tags` list, replace:

```
+ `service`: "${name}"
+ `role`: "${role_name}"
+ `Name`: "${project}_${env}_${service}"
```

with:

```
+ `service`: "${core_service_name}"
+ `process`: "${process_name}"
+ `role`: "${role_name}"
+ `Name`: "${project}_${env}_${service}_${process}"
```

Add to the "Notes on certain tags" list:

```
+ `process` - The process type name. Present on env-tier resources that belong to a specific core service process type; omitted for backing services, which have none.
```

### 6.16 Final sweep of `cicl.md`

Grep the finished file for `domain_default_service` — there must be zero hits.
Then verify every in-file anchor you introduced resolves against an actual
heading: `#process-types`, `#field-scoping`, `#magic-refs`,
`#consumes-relationships`, `#depends-on-relationships`, `#bare-subdomains`,
`#validation-rules`, `#domain`, `#resources`, `#provided-fields`,
`#container-registry-and-service-images`.

---

## File 7 — `doctrine/infrastructure/contracts.md`

### 7.1 The opening paragraph

Replace:

```
Contracts define the boundaries of core services. Core services can be providers, consumers, or both depending on usage relationships defined by `infra.yml`'s [depends-on](./cicl.md#depends-on-relationships) field. Every core service that is a provider will have a contract at `$pr/infra/contracts/${service_name}.${contract_format}.yml`.
```

with:

```
Contracts define the boundaries of core service [process types](./cicl.md#process-types). A process type can be a provider, a consumer, or both, depending on the usage relationships declared by `infra.yml`'s [consumes](./cicl.md#consumes-relationships) field. Every process type that is a provider will have a contract at:

`$pr/infra/contracts/${service_name}.${process_name}.${contract_format}.yml`

```
infra/contracts/
├── api.web.openapi.yml
└── api.worker.asyncapi.yml
```

The path is keyed on the process type unconditionally, and the format alone could not stand in for it: one codebase may run two HTTP process types — a public `api` and an internal `admin`, on different networks with different resources — and both are genuine boundaries deserving their own contract.

**The provider set is (`consumes` targets) ∪ (`web`-network process types).** Both arms are load-bearing. The first is the declared interface graph. The second catches every publicly-reachable boundary even when nothing inside the project consumes it, which is what gives the [health-check](#health-checks) gate something to validate.
```

### 7.2 § Standards — format derives from role

After the format table, replace:

```
Note that while the contract format is dependent upon communication mechanism, it still describes the *core service*. An asyncapi.yml contract describes `worker`, *not* the queue backing service that actually feeds it info.
```

with:

```
The format follows from the **provider's `role`**, not from the shape of the graph: `role: web` → OpenAPI, `role: worker` → AsyncAPI. The role is what fixes the communication mechanism, so it is the honest source.

Note that while the contract format is dependent upon communication mechanism, it still describes the *core service process type*. An asyncapi.yml contract describes `api.worker`, *not* the queue backing service that actually feeds it info. The provider is whoever owns the message schema and the operation's semantics.
```

### 7.3 § Health Checks — full rewrite

**Keep the `### Health Checks` heading.** Replace its entire body:

```
In order to pass staging tests, all hosted core services (e.g. `backend`, `web`, `worker`) must provide health checks, reachable from the open web. Not all core services are actually reachable, so those that are must expose the health checks of those that aren't.

The pattern used is pretty simple - all core services on the `web` network must expose:
`/health` - A route which returns the health of the service as {version: "x.x.x"}.

Furthermore, each of those `web`-network core services must provide health checks for all core services downstream in their [dependency chain](./cicl.md#depends-on-relationships):
`/health/<other_service>` - Returns {version: "x.x.x"} for "other_service"

By enforcing these endpoints in the contract, we allow the developer to implement them however they see fit but ensure that health checks will be available to CI/CD operations.
```

with:

```
In order to pass staging tests, hosted process types must provide health checks reachable from the open web. Not every process type is publicly reachable, so those that are must expose the health of those that aren't.

#### Self health

**Every long-running process type serves `GET /health`** on its declared `port`, on its internal network, returning the service version as `{version: "x.x.x"}`.

For a process type that owns a loop rather than a request cycle — a queue consumer, a stream processor, a polling worker — that endpoint must report the *loop's* liveness, not merely the process's:

- The loop bumps an in-process **monotonic tick** each iteration.
- The `/health` handler returns **503** when that tick is stale.
- **The loop ticks at least every 10 seconds even when idle** — i.e. its receive is bounded, not indefinite — and **the handler's staleness threshold is 30 seconds**.

Both thresholds are doctrine-fixed; there is no per-project knob. Thirty is three times ten, so a healthy loop misses two consecutive ticks before it is called stale — enough slack to absorb scheduling jitter and one slow iteration without flapping, while still failing a wedged loop inside the window the container healthcheck acts on. A long unit of work does not threaten this: the tick belongs to the receive loop, not to the work.

The point of sourcing liveness from the loop is that a separate liveness thread will cheerfully report health while nothing is being processed. A wedged consumer must fail its own probe.

`scheduler` process types are **exempt**. There is no long-running container to probe, and a scheduler is never a `consumes` target — cron invokes it and nobody else does. "Did last night's job run" is a telemetry question, not a health-check one.

#### Fan-out

Each `web`-network process type must additionally expose the health of everything it talks to, at:

`/health/<service>/<process>` — returns `{version: "x.x.x"}` for that process type.

The fan-out set is the **union of `consumes` and [`depends_on`](./cicl.md#depends-on-relationships)**, not `depends_on` alone. The union matters: a web edge does not `depends_on` its worker (it needs the *broker* up, not the consumer), so keying off `depends_on` would silently stop requiring `/health/api/worker` — and a dead consumer is invisible from outside, because requests keep returning 200 while work piles up behind them.

**One hop only.** `/health/<service>/<process>` proxies the target's *self* `/health` with a short hard timeout. It never calls the target's own fan-out endpoints. Without this rule the legal `web ↔ worker` cycle in [`consumes`](./cicl.md#consumes-relationships) recurses.

#### Declared by fields, not by the contract

A `consumes` target must declare both `port` and `health_check_path`. Those two fields **are** the health declaration, and the [check step](./cicd.md#check-step) asserts them — along with `curl` being present in the image, which it already keys off `health_check_path`.

The declaration lives in the fields rather than in the provider's own contract because a `worker`'s contract is AsyncAPI, which describes channels and messages and has no natural place for an HTTP path; forcing `/health` into it would be a contortion. So the responsibilities split cleanly:

- The provider's `port` + `health_check_path` fields declare that it is probeable.
- The provider's AsyncAPI contract describes only its message boundary.
- The **consumer's** OpenAPI contract declares `/health/<service>/<process>`, which is where the existing contract-enforced health machinery already lives.

On elastic there is a second reason the `port` is required: it is exactly what makes a process type Service-Connect-discoverable, which is what lets a sibling `web` process reach its `/health` one hop away.

By enforcing the fan-out endpoints in the contract, we allow the developer to implement them however they see fit but ensure that health checks will be available to CI/CD operations.
```

---

## File 8 — `skills/browser-investigate/SKILL.md`

Two factual renames in § Find the URL to drive. Replace:

```
Build the URL from `project.yml` (the project name) and `infra/infra.yml`
(`apex_domain`, and `domain_default_service`), per the doctrine domain rules:

- Per service on the `web` network:
  `https://<service>.dev.<project>.<apex_domain>`
  (the project segment is hyphenated — `my_project` → `my-project`).
- The `domain_default_service` also answers at the bare-env host:
  `https://dev.<project>.<apex_domain>`.
```

with:

```
Build the URL from `project.yml` (the project name) and `infra/infra.yml`
(`apex_domain`, and `domain_default_process`), per the doctrine domain rules:

- Per process type on the `web` network:
  `https://<service>-<process>.dev.<project>.<apex_domain>`
  (the service and process segments are joined by a hyphen and occupy one
  label; the project segment is hyphenated too — `my_project` → `my-project`).
- The `domain_default_process` also answers at the bare-env host:
  `https://dev.<project>.<apex_domain>`.
```

---

## File 9 — `skills/contracts/SKILL.md`

Three edits to the body. **Do not touch the frontmatter** (`name`,
`description`) — trigger-surface changes are out of scope for this mod.

Replace line 10:

```
Contracts define the boundary of a provider core service; a single file covers the formats, the mandatory endpoints, and how CI uses them.
```

with:

```
Contracts define the boundary of a provider core service *process type*; a single file covers the formats, the mandatory endpoints, and how CI uses them.
```

Replace the `contracts.md` router line:

```
[`contracts.md`](../../doctrine/infrastructure/contracts.md) — contract formats (OpenAPI for HTTP, AsyncAPI for queues), where they live, the mandatory `/health` and downstream `/health/<svc>` endpoints, and how CI checks them.
```

with:

```
[`contracts.md`](../../doctrine/infrastructure/contracts.md) — contract formats (OpenAPI for HTTP, AsyncAPI for queues), where they live, the mandatory `/health` and downstream `/health/<svc>/<proc>` endpoints, the loop-liveness tick a long-running process type owes, and how CI checks them.
```

Replace the two thread bullets:

```
- Provider/consumer relationships are declared via `depends_on` in `infra.yml` — author that in `infra-compile`.
- Provider-side contract tests run in the test suite (`testing`); the check step enforces contract-to-`depends_on` alignment (`cicd-pipeline`).
```

with:

```
- Provider/consumer relationships are declared via `consumes` in `infra.yml` — author that in `infra-compile`. `depends_on` is a separate relation (backing-service readiness) and does not define a contract edge.
- Provider-side contract tests run in the test suite (`testing`); the check step enforces contract-to-`consumes` alignment (`cicd-pipeline`).
```

---

## Verification before reporting done

Run each of these and report the result:

1. `grep -rn "domain_default_service" doctrine/ skills/` — expect hits **only**
   in Mod 106's files: `doctrine/infrastructure/shape.md`,
   `doctrine/infrastructure/specifics/**`. Zero hits in `cicl.md`,
   `contracts.md`, `infrastructure.md`, or `skills/`.
2. `grep -rn "never share code" doctrine/` — the surviving statement must be the
   re-scoped "Core service **sources** never share code".
3. In `cicl.md`, confirm these headings all exist and are unique:
   `### Process Types`, `#### Field scoping`, `### Magic Refs`,
   `### Consumes Relationships`, `### CICL Version`, `### Depends-On Relationships`.
4. In `contracts.md`, confirm `### Health Checks` still exists (its anchor is
   linked from `cicd.md`, `tests.md`, and now
   `internal_dependency_rules.md`).
5. Confirm every relative link you *added* resolves — that the target file
   exists and the `#anchor` matches a real heading in it. Pay particular
   attention to the cross-stratum ones:
   `internal_dependency_rules.md` → `../infrastructure/cicl.md#process-types`
   and `../infrastructure/contracts.md#health-checks`;
   `hex_overview.md` → `../infrastructure/cicl.md#process-types` and
   `./internal_dependency_rules.md#entrypoints`.
6. `git status --porcelain` — confirm the **only** files you modified are the
   nine listed above. Everything else in the dirty tree is pre-existing. **Do
   not commit.**

Report which of the nine files you changed, anything in the design that did not
survive contact with the existing prose, and the output of checks 1-6.

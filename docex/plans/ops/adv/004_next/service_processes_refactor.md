# Core Service Process Types

A design record for decoupling a core service's **build artifact** from its
**process types**, so that one codebase can be invoked in several ways (an HTTP
edge, a queue consumer, a cron job) without being split into separate images
that are forbidden to share code.

> **Status.** **Design settled; no open questions remain.** Ready to be broken
> into mods. Two structural decisions were taken after the first draft and
> propagate throughout: `processes:` is **always required** on a core service
> (there is no single-process shorthand), and worker liveness is established by
> an **in-process tick plus a one-hop probe** rather than a stored heartbeat.
> Consequently this advance is **not additive** — every existing `infra.yml`
> must be rewritten and every core service's emitted names change. The break is
> gated on `cicl_version: "2"`. This is advance-shaped, not a single mod — it
> spans resident doctrine, CICL, `docex`, contracts, health checks, telemetry,
> and naming, and ends in a version cut.

## The Problem

Consider a classic web backend where some operation must become a real queued
task. The doctrine as written prescribes a second core service — its own folder,
its own build image, and (per
[`infrastructure.md`](../../../../doctrine/infrastructure/infrastructure.md))
forbidden to share code with the first. In practice the hex structure resists
this split: the worker needs the same domain, the same repositories, the same
alogic. Nothing about the *domain* changed. Only the *invocation* changed.

### Root cause

One derivation in
[`cicl.md`](../../../../doctrine/infrastructure/cicl.md#container-registry-and-service-images):

> `${project_name}/${service_name}:${version}` … with `service_name` from the
> CICL key under `core_services`. **Each core service gets its own image.**

Image identity is keyed off the CICL service key. Combined with "core services
never share code," a new *scaling unit* therefore forces a new *codebase*. The
doctrine has fused three axes that are independent in general practice:

| Axis | What it governs | 12-factor name |
| ---- | --------------- | -------------- |
| Codebase | what code exists; what may not be shared | app (Factor 1) |
| Build artifact | what gets packaged and pushed | build (Factor 5) |
| Process type | invocation, scaling unit, failure domain | process / concurrency (Factors 6, 8) |

The multi-folder `core/` layout does **not** already decouple these. That is a
monorepo — a repository-layout fact. Under Factor 1 the app boundary is the
folder, not the repo, and the doctrine's own "core services never share code"
rule testifies to this (the rule would be incoherent if the repo were the
codebase unit). Each folder is still one welded codebase / artifact / process
type triple; more folders just means more welded triples.

### Only one joint is defective

- **codebase → build artifact must stay 1:1.** Factor 5 wants exactly one build
  artifact per app per version. The existing derivation is correct as written.
- **build artifact → process type must become 1:N.** This is the entire defect.

The *conceptual* fix is therefore narrow — one nesting level, on one joint. The
*mechanical* cost is not, because making `processes:` mandatory (below) changes
every core service's emitted identity.

### Industry alignment

This moves the doctrine from an idiosyncratic position to the mainstream one,
which is worth recording because it is the strongest argument that the shape is
right:

- 12-factor's Factor 8 is illustrated by a Procfile with `web:`, `worker:`, and
  `clock:` lines — one codebase, one slug, three independently-scaled process
  types. That *is* the `processes:` block, and "process type" is Heroku's own
  term for this axis.
- **Kubernetes:** one image, N workloads — a `web` Deployment, a `worker`
  Deployment, a `CronJob`, all referencing the same tag with different
  `command`/`args`.
- **ECS:** one task-definition family per process type, all pointing at the same
  ECR tag. Exactly this advance's elastic emission.
- **Framework convention:** `gunicorn app.wsgi` / `celery -A app worker` /
  `manage.py cron`. Celery and Sidekiq both assume the worker shares code with
  the web app; splitting the domain across repos to run a consumer would be
  considered a mistake in either ecosystem.
- **The `entrypoints/` directory:** Go's `cmd/server`, `cmd/worker` is *the*
  idiomatic layout (one module, many binaries); .NET does the same with separate
  Web/Worker hosts over a shared Application project.
- **The queue consumer as a driving adapter on the same port** is original
  ports-and-adapters orthodoxy — one adapter per *user* of the application,
  including batch and test drivers, all hitting the same application API.

Two smaller alignments: dropping core→core `depends_on` matches Kubernetes
(which has no cross-service startup-ordering primitive at all) and Compose's own
current documentation stance; and the corollary "startup ordering is not a
substitute for connection resilience" is verbatim the 12-factor position.

The one place the doctrine stays bespoke is **aggregating downstream liveness
into the `web` process's `/health/<svc>/<proc>`**. Industry lets the orchestrator
own per-process probes and an external monitor scrape them. The probe itself —
an in-process tick asserted by a `/health` handler — is textbook; only the
fan-out is a doctrine-specific compensation for stage tests probing from outside
the network.

### Two corroborating findings

1. **The `scheduler` role already has this bug.**
   [`scheduler.md`](../../../../doctrine/infrastructure/specifics/scheduler.md)
   says a scheduler service is "a **core service** (the project's own code, its
   own image)" with e.g. `command: ["python", "-m", "jobs.cleanup"]`. A real
   nightly cleanup must touch the domain — but as its own core service it may
   not import it. Today you must duplicate the domain or write a job that can't
   do anything. Shipped, undetected.

2. **The doctrine already contradicts itself across strata.** A queue consumer
   is a *driving adapter* — `Cont<Resource>Queue` — belonging next to
   `Http`/`Cli`/`Ws`/`Grpc` in the controller-mechanism table, on the *same*
   driving port. The driven table even already carries the `Queue` pattern for
   the producer side. The hex doctrine says "same module, one more adapter";
   the infra doctrine says "new image, no shared code."

### Latent defects in scope

Three fields are declared and documented but never acted upon. All three sit
directly in this advance's blast radius, and the first two are load-bearing for
its motivating example, so they are in scope rather than deferred:

| Field / function | Declared at | Reality |
| ---------------- | ----------- | ------- |
| `replicas` | `../../../src/docex/cicl/model.py:96`, `validate.py:43`, documented in `cicl.md` + `shape.md` | Read by **no emitter**. `emit/hcl.py:560` hardcodes `desired_count = 1`; `compile.py:840` sets `container_name` unconditionally, which Compose forbids alongside scaling. `replicas: 4` has always been inert. |
| `cicl_version` | `../../../src/docex/cicl/model.py:117` | Parsed and never validated or acted on. Exists for exactly the situation this advance creates and has never been used. |
| `_infer_contract_format` | `../../../src/docex/pipeline/check.py:109` | Tests `if service in consumer.depends_on`, then looks up `infra.backing_services.get(service)` — always `None` for a core service. The asyncapi branch is **unreachable**; the function always returns `openapi`. |

"Two web, four workers" — the motivating capability — does not work today even
after nesting lands, because `replicas` is inert.

## Resolution — Code Side

`root.py` **constructs**; entrypoints **activate**. Today `root.py` does both,
and responsibility (4) in
[`internal_dependency_rules.md`](../../../../doctrine/hexagonal_architecture/internal_dependency_rules.md)
— "registering every HTTP controller's router with the application" — is where
Starlette got baked in. That is the one line that moves.

```
core/api/
├── Dockerfile
├── build.sh
└── src
    ├── root.py            # one composition root, full graph, no server
    ├── entrypoints
    │   ├── http.py        # binds Http controllers to uvicorn/gunicorn
    │   └── worker.py      # binds Queue controllers to a consume loop
    └── hex/…
```

```python
# src/root.py — still the ONLY file that calls a concrete adapter constructor
@dataclass(frozen=True)
class Root:
    http:  HttpControllers    # ContScheduleHttp, ContUserHttp, …
    queue: QueueControllers   # ContScheduleQueue, …
    cli:   CliControllers     # ContCleanupCli, …

def build() -> Root:
    repo_calendar = RepoCalendarPostgres(...)                      # 1. driven
    queue_tasks   = QueueTasksRedis(...)
    schedule_svc  = ScheduleService(repo_calendar, queue_tasks)     # 2. alogic
    return Root(                                     # 3. ALL driving adapters
        http  = HttpControllers(schedule=ContScheduleHttp(schedule_svc)),
        queue = QueueControllers(schedule=ContScheduleQueue(schedule_svc)),
        cli   = CliControllers(cleanup=ContCleanupCli(schedule_svc)),
    )
```

Rules that follow:

1. `build()` constructs **every** driving adapter for **every** mechanism,
   regardless of which process type is running. Controller construction is
   free — it captures a port reference and performs no I/O.
2. Entrypoints call `build()`, never a concrete adapter constructor. The
   no-self-instantiation rule survives untouched.
3. **The runtime host is not an adapter.** Nobody ever thought uvicorn was an
   adapter; the broker consume loop isn't one either. Both belong to the
   entrypoint. The adapter's job is *translation* — and on the queue side, the
   return half of that translation is the ack/nack/retry decision.
4. **Never** `root_web.py` / `root_worker.py`. Two copies of the driven wiring
   drift, which is precisely the bug class module integration tests exist to
   catch ("composition-root mistakes: wrong adapter passed to a service").
5. Where a client library inverts control (Celery-style decorators), register in
   the **entrypoint**, calling into the adapter's handler. A decorator inside
   the adapter leaks the framework and destroys mocked-port testability.
6. A driven adapter that is genuinely expensive and needed by only one process
   type should be lazy *internally*, rather than forking the root. If that feels
   like a band-aid, the footprint test below may be telling you it is actually a
   second app.
7. A long-running entrypoint that owns a loop must expose that loop's liveness —
   see [Health Checks](#health-checks).

### HTTP / queue symmetry

| | HTTP | Queue |
| --- | --- | --- |
| Runtime host (owns the loop) | uvicorn / gunicorn | broker consume loop |
| Driving adapter (translates) | `ContScheduleHttp` | `ContScheduleQueue` |
| Driving port | `ContSchedule` | `ContSchedule` — *the same port* |

## Resolution — infra.yml Side

A **mandatory** `processes:` block. There is no flat form and no shorthand:

```yml
core_services:
  api:
    secrets: [STRIPE_API_KEY]           # codebase-scoped
    processes:
      web:
        role: web
        command: ["python", "-m", "entrypoints.http"]
        port: 8080
        networks: [web, internal]
        health_check_path: /health
        resources: { cpu: 1.0, memory: 2GB }
        consumes: [api.worker]
      worker:
        role: worker
        command: ["python", "-m", "entrypoints.worker"]
        port: 8080
        networks: [internal]
        health_check_path: /health
        replicas: 4
        resources: { cpu: 2.0, memory: 4GB }
        depends_on: [taskqueue]
        consumes: [api.web]
      nightly_cleanup:
        role: scheduler
        schedule: "0 3 * * *"
        command: ["python", "-m", "jobs.cleanup"]
        resources: { cpu: 0.25, memory: 512MB }
        networks: [internal]
        depends_on: [appdb]
```

### Why `processes:` is mandatory

Consistency over economy. A shorthand would buy a few saved lines per
single-process service and cost:

- a collapse conditional replicated across every identity derivation (emitted
  name, hostname, contract path, health path, `OTEL_SERVICE_NAME`, tags);
- a "is this the collapsed or the qualified form?" question at every read site;
- a dual-form validation surface, including the ambiguity of a service-level
  `resources:` sitting next to a `processes:` block;
- a permanent second code path.

With the shorthand gone, **every identity is unconditionally two-segment** and
the collapse logic lives in zero places. It also eliminates a naming-collision
class outright (see [Identity and Naming](#identity-and-naming)) and makes the
previously-deferred "shorthand *and* `processes:` together" question
inexpressible rather than merely answered.

`processes:` is required and must be non-empty.

### Field scoping

One principle generates the table, including for fields not yet invented:

> **A field belongs to the codebase iff its value is determined by the source
> code. It belongs to the process type iff its value is determined by the
> invocation.**

| Codebase-scoped (on the core service) | Process-type-scoped |
| ------------------------------------- | ------------------- |
| `processes:` | `role`, `command` |
| `secrets:`, `config:` | `resources`, `replicas` |
| migration ownership (`migrate.sh` runs once) | `networks`, `port` |
| `env:` (shared) | `depends_on`, `consumes` |
| | `env:` (merges over service-level) |
| | every role-specific field (`health_check_path`, `schedule`, …) |

Applying the principle:

- `secrets:` / `config:` — the *code* reads `STRIPE_API_KEY`. Codebase.
- migration ownership — `migrations/` lives in the source tree. Codebase.
- `env:` straddles: some vars are code-determined (`DATABASE_HOST` — the code
  needs a database), some invocation-determined (a worker's concurrency knob).
  A field that straddles the principle is *expected* at both levels, which
  justifies the one exception rather than leaving it an oddity.
- **Role-specific fields follow `role`**, which is invocation-determined, so
  they are process-scoped by derivation. The table never needs revisiting when a
  role gains a field.

**The service level accepts only `{processes, secrets, config, env}`.** Anything
else is a hard error — the same phantom-typo reasoning that makes `processes:`
mandatory. A stray `resources:` at service level fails loudly instead of
silently doing nothing.

**`command` is required on every process type, including `web`.** With multiple
process types on one image, at most one could inherit the Dockerfile `CMD`, and
"which one" is an ambiguity worth deleting rather than answering. Requiring it
universally is self-documenting and makes the Dockerfile `CMD` irrelevant for
core services.

### Naming convention for process types

Not a hard rule — the doctrine's own two-HTTP-boundary example must break it —
but a documented convention, because unspecified naming drifts across projects
(`api.web` / `api.api` / `api.main` / `api.server`) and cross-project
familiarity is a stated doctrine goal:

> **A process type is named after its role** unless a codebase declares two
> process types on the same role. `role: web` → `web`; `role: worker` →
> `worker`; `role: scheduler` → the job's name (`nightly_cleanup`), since a
> codebase commonly has several. A project needing two HTTP boundaries names
> them by boundary (`api.public`, `api.admin`) and deviates deliberately.

### Vocabulary

- **Core service** — keep the term. The core/backing axis is about *whose code
  it is*, which has not moved. It also already failed to map 1:1 onto compose
  services (a core service emits its container, its OTel sidecar, and for
  `scheduler` an Ofelia container), so nesting widens an existing gap rather
  than opening a new one.
- **Process type** — the infra-level declaration; a scaling unit with its own
  role, command, resources, networks, and port. 12-factor's own term.
- **Entrypoint** — reserved for the *code module* a process type's `command`
  invokes. Do **not** promote it to the infra noun: it is already spent three
  times over (Dockerfile `ENTRYPOINT`, traefik entrypoints in
  `fixed_reverse_proxy.md`, and the code module).

Reads as: *"the `api` core service declares three process types; the `worker`
process type's command invokes the `entrypoints/worker.py` entrypoint."*

`scheduler` stops being its own species of service and becomes a process type
whose trigger is cron — which is what 12-factor's canonical Procfile always
said, with its `clock:` line alongside `web:` and `worker:`.

Avoid `engine` as an example service name in the docs — `engine:` is already a
CICL field on backing services.

## Identity and Naming

### The hostname label must be single and hyphen-joined

`{service}-{process}.{env}.{project}.{apex}` — e.g.
`api-web.dev.myproject.example.com`. **Not** `web.api.dev.…`, for three
independent reasons, any one of which is fatal:

1. **TLS wildcards cover exactly one label.** The elastic certs are
   `*.stage.<project>.<apex>`; `web.api.stage.…` sits two labels deep and is
   uncovered. Multi-level wildcards are not valid in TLS, so no cert could
   cover it.
2. **The domain parse is positional.**
   [`cicl.md § Domain`](../../../../doctrine/infrastructure/cicl.md#domain)
   promises that any machinery with no further context can determine project,
   env, and service from the domain. A fixed four-part anatomy keeps that true.
3. The bare-env and bare-project routes are defined relative to a four-part
   form.

**Nothing ever reverse-parses the label back into `(service, process)`.** The
HAProxy demux's Lua parse is right-anchored — public suffix via the PSL, apex as
suffix-plus-one, project as the label immediately left of that
(`fixed_master_network.md:104-116`) — then resolves `<project>-traefik` over
Docker DNS. It has no opinion about how many labels sit left of the project, so
the demux config needs **no change**. Traefik and the ALB match whole host
strings that docex generates, so they do not decompose either. Worth stating in
the doctrine, because it dissolves the apparent ambiguity of `api-web`.

The one artifact to touch: that Lua comment enumerates "the three canonical
doctrine forms" including `<service>.<env>.<project>.<apex_domain>`, which
becomes stale. Behavior unchanged, comment wrong.

### Rule 5 becomes a rendered-identity rule

Two distinct pairs can render one label — service `api` + process `web-v2`, and
service `api-web` + process `v2`, both → `api-web-v2`. Forbidding hyphens does
not help, because naming policies convert `_`→`-` for data-plane names anyway
(`my_api`+`web` and `my`+`api_web` both → `my-api-web`). So:

> **The rendered data-plane identity of every emitted service must be unique
> after naming-policy normalization.** The set spans core process types *and*
> backing services.

That second clause catches a collision today's rule 5 cannot: core service `api`
with a process named `db` renders `api-db`, colliding with a backing service
literally named `api-db` — same docker network, same container name.

### The principle that keeps most emit code unchanged

> **`CompiledService.name` carries the two-segment compiled identity
> (`api-web`); the authoring models keep the authoring names.**

Several things then become correct for free, because they already derive from
`svc.name` / `global_name`: traefik router keys, ECS container names, the paired
sidecar's `{name}-otelcol`, Service Connect `portMappings[].name`, and the
CloudWatch log group via `_log_configuration(…, svc.name, "app")`
(`emit/hcl.py:334`). Log groups therefore become **per process type**, which is
symmetric with everything else and costs nothing but retention; stripping the
process segment to keep them per-codebase would be extra code for a debatable
benefit.

### What is *not* process-qualified

This table is the spine of the upgrade guide.

| Identity | Keyed on | Changes? |
| --- | --- | --- |
| image ref `{registry}/{project}/{service}:{version}`, ECR repo | codebase | no |
| source folder `core/{service}/`, doc folder `plans/core/{service}/` | codebase | no |
| `schema_owned_by` target | codebase | no |
| networks / SGs `{project}-{env}-{network}` | network | no |
| SSM prefix, aggregate env file, compose project name | env | no |
| backing service names, RDS/S3 identifiers, docker volumes | n/a | no |
| container / ECS service / task-def / log group / sidecar / traefik router | process type | **yes** |
| hostname label, contract filename, health path, `OTEL_SERVICE_NAME` | process type | **yes** |

### Rule restatements

| Rule | Now reads |
| ---- | --------- |
| 5 | rendered data-plane identity unique across core process types **and** backing services, post-normalization |
| 7 | kind-aware — see [Magic Refs](#magic-refs) |
| 10 | every **process type** declares `resources` with at least `cpu` and `memory` |
| 12 | `domain_default_process` (renamed) names a **process type** on the `web` network |
| 14 | the reserved-name list (`dev`, `test`, `stage`, `prod`, `www`) applies to **process names** as well as service names |
| 15 | every `web`-network **process type** declares a `port` |
| 16 | evaluated against each process type's *effective* env (service-level ∪ process-level) against the service's `secrets ∪ config` |

`domain_default_service` → **`domain_default_process`**, taking `api.web`. The
old name is a small lie in a doctrine that just spent effort distinguishing the
two nouns, and every `infra.yml` is being rewritten anyway.

Rule 14's *original* justification actually evaporates — a service named `dev`
now renders `dev-web`, which no longer collides with the bare-env host. Keep the
rule anyway and extend it: a process named `prod` renders
`api-prod.dev.myproject.example.com`, which reads as a production host in a dev
env. The rule protects readability, not only the parse.

### Small policy changes

- **`http_host` gains `max_len: 63, overflow: error`.** It currently has no cap,
  harmless when the label was one segment. DNS labels hard-cap at 63, and a
  silently-overlong hostname would fail confusingly at cert-issuance time rather
  than at compile.
- **`alb`'s 32-char `hash_truncate` bites more often.** The policy working as
  designed — the descriptive name survives in the `Name` tag — but target-group
  names will gain hash suffixes where they previously did not. Upgrade-guide
  note.

### Dots for reference, hyphens for emission

`consumes: [api.worker]`, `domain_default_process: api.web`, magic refs,
`describe` node ids — all **dotted**. Container names, SGs, hostnames, log
streams, traefik keys — all **hyphenated**.

## Magic Refs

`../../../src/docex/cicl/magic_refs.py:41-43` is a fixed three-segment pattern,
so `${core_services.api.web.host}` does not parse. This is load-bearing three
times: the cycle example below, the health probe, and any `frontend` → `api.web`
edge.

```yml
${core_services.<service>.<process>.<part>}      # api.web.host — 4 segments
${backing_services.<service>.<part>}             # database.host — 3 segments
```

Asymmetric but honest: backing services have no process types, so there is
nothing to qualify. Same reasoning as the `consumes:` rule — a bare core service
name is illegal rather than shorthand, because a codebase has no single
boundary.

**Parse generically, then arity-check by kind**, rather than widening the regex.
Today a three-segment core ref falls through to `_COMPILE_RE` — which permits
dots (`cicl/substitute.py:38`) — and dies as *"undefined compile-time variable
${core_services.api} … available: [apex_domain, env_name, …]"*, sending the
reader hunting through compile-time variables for something that was never one.
Segment-splitting first yields the message the author needs: *"`core_services`
refs take `<service>.<process>.<part>`; got `api.host` — did you mean
`api.web.host`?"*

### Rule 7 becomes kind-aware

Rule 7 is currently unsatisfiable for core targets, since core→core
`depends_on` becomes illegal. It splits along the same seam as the two relations:

> - A magic ref to a **backing service** must be matched by a `depends_on` entry
>   on the referencing process type.
> - A magic ref to a **core process type** must be matched by a `consumes` entry
>   on the referencing process type.

The invariant survives the split intact, and `consumes:` becomes load-bearing
for *validation* rather than only for contracts and health fan-out.

Three clarifications the rule needs:

- **One-directional: ref ⇒ edge, never edge ⇒ ref.** The cycle proves why.
  `api.web` must declare `consumes: [api.worker]` for the asyncapi contract and
  the health fan-out, but holds no magic ref to the worker — it reaches it
  through the broker. A bidirectional rule would reject the most common
  web/worker topology in existence.
- **Same-codebase is not exempt.** `api.worker` referencing
  `${core_services.api.web.host}` still declares `consumes: [api.web]`. Sharing
  source does not make it not a boundary.
- **A service-level `env:` ref obliges every process type** to declare the edge,
  consistent with `depends_on`. If every process receives `WEB_HOST`, every
  process talks to `api.web`.

### Self-references rejected

`api.web` referencing its own `host` fails, with a hint pointing at `localhost`.
The justification is not merely that it is degenerate: `provides.host` is the
*internal* discovery name, so the one plausible reason to self-reference —
building absolute URLs — would not get what the author expects anyway.

### Free behavior

A ref to a `scheduler` process type already fails with no new code:
`scheduler/container` declares `provides: {}`, and transfer-table validation
rule 7 requires a magic ref to name a part the engine's `provides:` exposes.

### Mechanical follow-ons

`MagicRefDependency` gains `target_process`; its `consumer` becomes the compiled
process identity. The cycle guard key becomes `(kind, target, process, part)`.

## The `worker` Role

`tables/roles/` ships only `cache`, `object_store`, `relational_db`,
`scheduler`, `web`. So `role: worker` fails validation rule 2 today, and
"contract format derives from the provider's `role`" has no `worker` to derive
from. A new bundled table is required:

```yml
# Role: worker
#
# Core service process type — long-running, event-driven, never publicly
# routed. Canonically a queue consumer; a stream processor or polling loop
# fits the same shape. Shares its codebase and image with sibling process
# types.
#
#   - fixed:   one compose service on the codebase's image with the process
#              type's `command`.
#   - elastic: task_definition + ecs_service. NO target_group — a worker is
#              not an ingress target.
#
# `image:`, `cpu:`, `memory:`, `tmpfs:` are derived per-process by the
# compiler, exactly as for `web`.

roles:
  worker:
    description: "Core service process — long-running, event-driven, not publicly routed."
    container:
      foundation: both
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service, container_definition]
      defaults:
        fixed: {}
        elastic:
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
            # NOT target_group — a worker has none. Routes to the ECS
            # container-level healthCheck, so a wedged consume loop gets the
            # task killed and replaced by the service.
            target: container_definition
            healthCheck:
              command: ["CMD-SHELL", "curl -f http://localhost:${port}${field_value} || exit 1"]
              interval: 30
              timeout: 5
              retries: 3
              startPeriod: 10
      provides:
        # A worker that declares a `port` registers as Service-Connect-
        # discoverable on elastic (shape.md § service_discovery), which is what
        # lets a sibling `web` process reach its /health one hop away.
        host:
          fixed: "${global_service_name}"
          elastic: "${global_service_name}"
        port:
          fixed: "${port}"
          elastic: "${port}"
      env: {}
      naming: ecs
```

### It needs a new emit destination: `container_definition`

`health_check_path` on `web` routes to `target_group` on elastic. A worker has
none, so its natural destination is the ECS **container-level** `healthCheck`.
But `render_task_definition` (`../../../src/docex/emit/hcl.py:311-351`) builds
`container_def` procedurally, and `svc.body` — where `fields:` translations land
— supplies *task-level* keys (`cpu`, `memory`, `launch_type`, `network_mode`).
There is currently no route from a transfer-table field into the
`container_definitions` JSON.

Add `container_definition` to the closed set of destinations docex recognizes.
This is what `emits:`/`target:` exists for, it is a plain declarative body
(unlike `schedule`'s procedural cron translation), and it is reusable for any
future container-scoped field (`ulimits`, `stopTimeout`,
`readonlyRootFilesystem`).

Leave `web/container` alone rather than also giving it a container healthCheck —
that changes existing behavior for a marginal gain (ECS-level replacement atop
ALB deregistration). Recorded as deferred.

### `web` membership is rejected

`worker` and `scheduler` process types may not declare `web` in `networks:`. A
process type wanting public ingress *is* `role: web`. Today this is prose-only
for scheduler and unenforced — `_validate_scheduler_services`
(`../../../src/docex/cicl/validate.py:880`) checks only that `schedule` and
`command` are present. One rule covers both roles, alongside the already-settled
"`replicas` on a `scheduler` is a compile error."

### No `default_port`

Tempting to give workers a doctrine-fixed health port so it is free, but that
silently obliges the app to bind it and turns a missed binding into an ECS kill
loop. An explicit `port` keeps the requirement visible — and since `consumes`
targets must declare one anyway, nearly every real worker has it.

## The Two Relations

`depends_on` conflates **liveness coupling** with **interface coupling**. These
coincide for synchronous mechanisms and diverge for asynchronous ones:
`api.web → api.worker` is deliberately decoupled in liveness (web needs the
*queue* up, not the worker) while fully coupled in interface.

| Field | Names | Job | Cycles | Emitted |
| ----- | ----- | --- | ------ | ------- |
| `depends_on` | backing services **only** | readiness gate | fatal | compose `condition:`; nothing on elastic |
| `consumes` | core process types **only** | contracts + health fan-out + rule 7 | **legal** | nothing — CI only |

### Why they cannot merge

The decisive test is cycles. `api.web` enqueues a job; `api.worker` POSTs the
result back to `api.web`'s internal API — so `web consumes api.worker` *and*
`worker consumes api.web`. That is a cycle, it is the most common web/worker
topology in existence, and it is completely fine: interfaces may be mutually
referential. A cycle in `depends_on`, by contrast, is a hard startup deadlock
that compose refuses to start.

So the `consumes` graph is **not a DAG** — it is a directed graph that may
legitimately contain cycles. No single field can carry a cycle rule that is
simultaneously fatal and fine. There is one DAG (`depends_on`) and one cyclic
digraph (`consumes`).

Nor is either field an information-flow graph: `worker` *receives* data from the
queue but `depends_on` it, so readiness edges point toward the dependency
regardless of data direction.

### What `depends_on` actually does today

Verified against `docex` source, because the field's real footprint is narrower
than its documentation:

| Use | Where | Real? |
| --- | ----- | ----- |
| Startup gate on **fixed** | `../../../src/docex/emit/compose.py` (2nd pass, ~L567) | **Yes, load-bearing** |
| Startup gate on **elastic** | `../../../src/docex/emit/hcl.py` — three `pop()`s | **No — discarded** |
| Cycles, unknown targets, magic-ref coherence | `../../../src/docex/cicl/validate.py` rules 6 & 7 | **Yes** |
| Contract-format inference | `../../../src/docex/pipeline/check.py` | Nominally — **broken** |
| DAG rendering | `../../../src/docex/describe/{dag,llm}.py` | Descriptive only |

The compose emitter rewrites short-form into long-form with
`condition: service_healthy` (falling back to `service_started` when the target
declares no healthcheck). Its own `WHY` comment names postgres and a refused TCP
socket from `compose exec` — i.e. its only real job has always been **core →
backing readiness**, never core-to-core ordering. On elastic the three `pop()`s
are all in backing-service renderers and no ECS renderer consumes the field at
all.

So core→core startup ordering is not merely unused — it is unimplementable on
elastic. ECS `dependsOn` exists only *between containers inside one task
definition* (`START`/`COMPLETE`/`SUCCESS`/`HEALTHY`); there is no cross-service
ordering primitive. `docex` could emulate it by polling to steady state at
deploy time, but ECS independently replaces tasks afterwards (scaling, AZ
rebalance, failed health check, platform update) with no ordering — so the
guarantee would hold exactly once and be silently violated forever after.

### Rules

1. **`depends_on` may not name a core service.** It is a fixed-only convenience
   for backing readiness and **never a correctness guarantee**.
2. Retain rule 6 (cycles — *more* important now that `service_healthy` gates are
   emitted) and rule 7 in its new kind-aware form.
3. Compiler-emitted edges — OTel sidecars, Ofelia, the migration service, the
   per-codebase exec service — are unconstrained by rule 1, which governs only
   author-written `infra.yml`.
4. Write the corollary into the doctrine explicitly: **startup ordering is not a
   substitute for connection resilience.** Every service must tolerate its
   dependencies being absent at any moment, because on elastic they will be.
5. `consumes` targets are always fully qualified — `api.worker`, dotted. A bare
   service name is **illegal**, not shorthand for "all its process types": an
   interface edge points at a specific boundary, and a codebase does not have
   one contract.

Sanity check: `frontend → api.web` becomes `consumes:` only, so frontend no
longer waits for web on fixed. That costs nothing — a frontend must tolerate the
API being down regardless, and on elastic it already does.

## Contracts

Path gains the process dimension, unconditionally:

```
$pr/infra/contracts/${service}.${process}.${format}.yml
```

```
infra/contracts/
├── api.web.openapi.yml
└── api.worker.asyncapi.yml
```

Format alone cannot disambiguate: one codebase may have two process types on
the same mechanism (a public `api` and an internal `admin`, different networks
and resources, both HTTP, both genuine boundaries). Key on process type; let
format follow from mechanism.

Rules:

- The provider set is **(`consumes` targets) ∪ (web-network process types)**.
  Both sources are needed: `_gate_contracts`
  (`../../../src/docex/pipeline/check.py:312-331`) deliberately treats any
  web-network service as a provider so the health-endpoint gate has something to
  validate, and driving the set purely off `consumes:` would silently switch
  that off.
- Format derives from the **provider's** `role` (`web` → openapi, `worker` →
  asyncapi), not from graph shape.
- `contracts.md` already holds that the worker is the provider: *"An
  asyncapi.yml contract describes `worker`, not the queue backing service that
  actually feeds it info."* This confirms the direction — the provider is
  whoever owns the message schema and the operation's semantics.
- Filename parsing must count segments from the right. `_gate_health_endpoints`
  currently derives the service name via `path.name.split(".", 1)[0]`
  (`check.py:374`), which yields `api` from `api.web.openapi.yml`.

**Latent bug to fix.** `_infer_contract_format` (`check.py:109-131`) tests
`if service in consumer.depends_on`, then looks up
`infra.backing_services.get(service)` and only returns `asyncapi` if *that*
finds a queue-shaped engine. Contracts describe **core** services, so that
lookup is always `None`: **the asyncapi branch is unreachable and the function
always returns `openapi`.** Its docstring concedes the design ("Phase 3 keeps
this shallow… *Guess* the contract format"). This is why the async-contract path
was never exercised and the `depends_on` flaw went unnoticed. Replace with
role-derived format driven off `consumes:` — a fix, not a refactor.

## Health Checks

**Resolution: in-process tick plus a one-hop probe.** No stored heartbeat, no
new backing service.

- **Every long-running process type serves `GET /health`** on its declared
  `port`, on its internal network, returning `{version: "x.x.x"}` from
  `PROJECT_VERSION`.
- **Liveness is loop-sourced and intra-process.** The consume loop bumps an
  in-process **monotonic** tick each iteration; the `/health` handler returns
  503 when the tick is stale. A wedged loop therefore fails the probe rather
  than a liveness thread cheerfully reporting health while nothing is processed.
- **Doctrine-fixed thresholds: the loop ticks at least every 10 s even when
  idle** (i.e. a bounded receive timeout), and **the handler's staleness
  threshold is 30 s** — 3× slack, no per-project tuning.
- **Fan-out follows the union of `consumes` and `depends_on`**, not
  `depends_on` alone. Otherwise dropping the false `web → worker` liveness edge
  would silently stop requiring `/health/api/worker` — and a dead consumer is
  invisible from outside (requests still 200 while work piles up).
- **Path gains the process dimension as segments:** `/health/api/worker`.
- **One hop only.** `/health/<svc>/<proc>` proxies the target's *self* `/health`
  with a short hard timeout, never its fan-out endpoints. Without this rule the
  legal `web ↔ worker` cycle in `consumes` recurses.
- **A `consumes` target must declare `port` and `health_check_path`.** On
  elastic the `port` is also exactly what makes it Service-Connect-discoverable
  (see [`shape.md § service_discovery`](../../../../doctrine/infrastructure/shape.md#elastic-foundation)).
- **`scheduler` process types are exempt** — no long-running container to probe,
  and a scheduler is never a `consumes` target (cron calls it; nobody else
  does). "Did last night's job run" is a telemetry question, and job-level SDK
  telemetry is already deferred in `scheduler.md`.

### Why the health requirement is declared by fields, not by the contract

A `worker`'s contract is **AsyncAPI**, which describes channels and messages and
has no natural place for an HTTP path. Forcing `/health` into it would be a
contortion. Instead:

- The `port` + `health_check_path` fields **are** the declaration; the `check`
  gate asserts them, plus `curl` in the image.
- The *consumer's* OpenAPI contract declares `/health/<svc>/<proc>`, which is
  where the existing contract-enforced health machinery already lives.
- The worker's AsyncAPI contract describes only its message boundary.

This converges with something already in place: the `curl` gate keys off
`health_check_path` (`check.py:441-461`, mod 059), so the field now required is
already the field that gate watches. No new gate — a new required-field rule
feeding an existing one. **Do not re-key the curl gate off `role`**; the
field-driven form is strictly better and becomes correct automatically once the
field is process-scoped.

### Why not a stored heartbeat

The earlier draft had the worker write `(process, instance, version, ts)` to the
DB or cache from inside the loop, with `web` asserting freshness. Rejected
because it makes a *health-check* requirement conditional on *infrastructure*:
the doctrine cannot guarantee a project has either a cache or a relational DB,
so it would have to force one to be declared. The in-process form also removes
cross-container clock skew entirely (one process, one monotonic clock) and
collapses "storage" and "freshness threshold" into a single intra-process
comparison. See [Rejected Alternatives](#rejected-alternatives) for the
per-storage reasoning.

Accepted costs, recorded honestly: `web`'s health endpoint now performs bounded
network I/O; there is a brief false-negative window during a rolling
replacement, where a TTL'd heartbeat would have ridden through; and per-replica
instance *counts* are not available from a health check. That last one is
correct by design — health checks answer "is the boundary alive," telemetry
answers "how many and how fast."

Also rejected for the health route: a **ping round-trip** through the queue
(needs a reply channel; an endpoint that blocks on queue latency is a liability
under load) and **broker introspection** (engine-specific, and proves
*connected*, not *healthy*). The end-to-end enqueue→effect probe belongs in
**stage tests**.

## Replicas

`replicas` is inert today (see [Latent defects in scope](#latent-defects-in-scope)),
so "two web, four workers" does not work even after nesting lands. Implementing
it is in scope.

### Elastic

`desired_count = replicas` in `render_ecs_service`, clamped to 1 outside `prod`
per `shape.md`. No deployment-config work: nothing is emitted today, so ECS's
defaults (`minimum_healthy_percent = 100`, `maximum_percent = 200`) apply, which
are correct for a static count.

A synergy with the `worker` role: a worker ECS service has no target group, so
without a container healthCheck ECS would treat a task as healthy the instant it
reaches RUNNING and would roll a broken deploy through all four replicas. The
`container_definition`-routed `healthCheck` makes worker rolling deploys
genuinely gated — so that field earns its keep twice.

Sidecars need no thought on elastic: the collector is a container *inside* the
task definition, so N tasks give N sidecars.

### Fixed — unroll, do not scale

`deploy.replicas` plus suppressing `container_name` **does not work**, because
of the sidecar. On fixed the collector pairs via `network_mode: "service:<svc>"`
to share the app container's netns; Compose has no replica-to-replica pairing
semantics, so one sidecar cannot pair with N replicas. `deploy.replicas` also
forces dropping `container_name` (Compose refuses both together), costing the
container-name DNS entry and the readable names operators debug with.

So **the compiler unrolls replicas into N distinct compose services**:

```yml
services:
  myproject-prod-api-web-1:
    container_name: myproject-prod-api-web-1
    networks:
      internal:
        aliases: [myproject-prod-api-web]     # ← load-bearing
      web:
        aliases: [myproject-prod-api-web]
    labels:
      - "traefik.http.routers.myproject-prod-api-web.rule=Host(`api-web.prod...`)"
      - "traefik.http.services.myproject-prod-api-web.loadbalancer.server.port=8080"
  myproject-prod-api-web-1-otelcol:
    network_mode: "service:myproject-prod-api-web-1"
  myproject-prod-api-web-2:
    ...
```

Every existing invariant survives:

- **`provides.host` is unchanged.** The shared network alias `{global_name}`
  resolves to all N containers with Docker DNS round-robin.
- **The sidecar stays 1:1 and stays on loopback**, preserving the identical
  `OTEL_EXPORTER_OTLP_ENDPOINT` across foundations.
- **Traefik aggregates.** Labels key on the *unqualified* `{global_name}`, so
  traefik's docker provider sees N containers declaring one router and one
  service and loads them as N servers. This only holds if the labels stay
  unqualified — a constraint to write down, not leave to chance.
- **`container_name` survives**, so `docker logs …-api-web-3` still works.
- **No host-port collisions**, because web services never publish host ports —
  which is *why* replicas are viable on fixed at all.

Blast radius is small: `replicas` applies only in `prod`, so `dev`, `test`, and
fixed `stage` always unroll to exactly one and emit output identical to today.

### Validation and caveats

- `replicas` on a `scheduler` process type → compile error (Ofelia fires one
  job; a replica count is meaningless).
- A process type with `replicas > 1` **must tolerate siblings**, mirroring
  `scheduler.md`'s existing overlapping-job caveat. Two workers pulling the same
  queue is the normal case; two workers assuming exclusivity is a project bug
  the doctrine cannot catch.
- `shape.md`'s fixed and elastic **Runtime Shape** paragraphs both say the
  reverse proxy load-balances replicas, illustrated with *workers*. Wrong for
  that example: the proxy balances **web** replicas; internal replicas are
  balanced by Docker DNS (fixed) and Service Connect (elastic), with no proxy
  involved.

### Sequencing

This is an independent latent bug, worth fixing even without the advance, but
`replicas` is process-scoped and the motivating example depends on it. Make it
**its own mod inside the advance, sequenced after nesting lands**, so "did we
implement replicas correctly" stays a separable diff.

## Per-Codebase Operations

`migrate` (dev/test), `test`, and `build` are per-**codebase** but must land in a
container. The compose-key lookup breaks in three ways, and the heuristic is
duplicated:

- `../../../src/docex/orchestrate/_common.py:142` `compose_service_key()`
- `../../../src/docex/orchestrate/build.py:104` `_build_one()` — its own copy

Against keys `api-web` / `api-worker`: looking up `api` matches nothing and
`compose_service_key` silently returns `"api"` (its "best-effort fallback"),
yielding "service not running"; looking up a codebase named `web` matches
`sample-dev-api-web` — **wrong container, no error**, which is a latent bug
today; and the replica unroll adds `…-api-web-1` as a third mismatch path.

**One item comes off the docex work list.** *"Containerize — build once per
distinct source folder, deduping process types"* is unnecessary:
`core_services(ctx)` returns top-level `infra.yml` keys and process types nest
inside, so `containerize.py:126` and `build.py:73` already iterate one entry per
codebase.

### Resolution: emit a per-codebase exec service

Rather than pick a process type, the compiler emits one, guarded by a compose
profile so it never starts with `up`:

```yml
  myproject-dev-api-exec:
    profiles: [exec]                                     # not started by `up`
    build: { context: ../../../core/api, target: dev }   # same image; cache hit
    env_file: [<aggregate>]
    environment: { ...service-level env: only... }
    volumes: [ ...the dev bind mounts... ]
    networks: [internal]                # union of the codebase's non-web nets
    depends_on: { myproject-dev-appdb: { condition: service_healthy } }
```

Invoked as `docker compose run --rm myproject-dev-api-exec ./migrate.sh` (and
`./test.sh`, `./build.sh`). `compose run` implicitly enables the target
service's profiles, so the guard costs nothing at the call site.

Why this rather than a pick-one rule — it deletes the question and four other
things with it:

1. **It matches what the doctrine already does for three of four cases.** Fixed
   stage/prod migrate is a one-off container via ansible; elastic migrate is a
   `RunTask` on a separate task definition; scheduler-only `test` already builds
   a one-off container. Only dev/test were the exec outliers, so unifying is a
   dev/prod-parity win rather than a refactor.
2. **It makes the env-scoping boundary enforceable.** Because `env:` is
   process-scoped-mergeable, a pick-one rule has a trap: `DATABASE_*` declared
   on `api.web`'s process-level env breaks an exec into `api.worker`. The exec
   service carries **service-level `env:` only**, which turns that into a rule
   with teeth: *`migrate.sh`, `test.sh`, and `build.sh` may depend only on
   codebase-scoped env* — correct on its own merits, since a migration has no
   business reading a worker's concurrency knob.
3. **It kills the scheduler carve-out.** `scheduler.md § Caveats` currently
   carves out "there is no `test`-stack container to `exec` into…". A
   scheduler-only codebase now takes the identical path; that paragraph gets
   deleted rather than rewritten.
4. **It answers the replica question** — no "which replica" either.
5. **It deletes both copies of the suffix heuristic**, including the wrong-match
   failure that exists today.

Free side benefit: `depends_on` with `condition: service_healthy` means
`compose run` gates on the database being ready, so dev/test migrate stops
assuming the stack is already up.

Costs: one inert emitted compose service per codebase, and container-start
latency (~1 s) instead of `exec` into a warm container — negligible for all
three operations. The `build:` block must mirror the env's stage target (`dev`
in dev, `test` in test) so Docker's cache makes the image free.

Cheaper fallback if the emitter block is unwanted: prefer the `role: web`
process type, else the lowest-sorted long-running one, excluding schedulers
(~10 lines) — but it leaves the env-scoping trap, the replica question, the
scheduler carve-out, and a rule to remember.

## Telemetry Identity

`OTEL_SERVICE_NAME` is documented as the service's `infra.yml` name. With two
process types on one codebase both containers would report
`OTEL_SERVICE_NAME=api`, blending two unrelated workloads across every
dashboard, latency percentile, and error rate in the backend.

**`OTEL_SERVICE_NAME = {service}-{process}`** — exactly `CompiledService.name`,
so this corrects itself once that principle lands. A doc change plus a test, not
an emitter change.

OTel-correct, not merely convenient: the semantic convention requires
`service.name` to be identical across horizontally-scaled instances, and this
value is per *process type*, not per replica. OTel has no dedicated attribute
for the process-type axis, so folding it into `service.name` is standard —
`service.name=api-web` / `api-worker` is what a Kubernetes or Heroku shop emits
from one image across two workloads.

**Two resource attributes appended** so both axes are queryable rather than
recoverable only by a brittle prefix match on a hyphenated name:

```
docex.core_service=${service}
docex.process_type=${process}
```

The `docex.` prefix matches the established precedent of the `docex.project`
docker label. Additive to the existing triple (`service.namespace`,
`service.version`, `deployment.environment.name`, all unchanged).

**`service.instance.id` is deliberately not set.** The correct values (ECS task
ARN, container ID) are runtime-only; the OTel ECS resource detector supplies
them if the app enables it. A project-side option, not doctrine.

### The sidecar arithmetic

One sidecar per long-running process type falls out automatically
(`emit/compose.py:218` pairs per compiled service), and that is correct — netns
pairing is what makes `localhost:4318` identical across foundations, and netns
is per-container by construction. But the multiplication lands on the bill and
must be documented:

> A codebase with N long-running process types running R replicas each carries
> **N × R** collector sidecars, at 0.1 vCPU / 128 MB apiece.

On elastic that overhead is per-task and interacts with Fargate tier rounding,
which `telemetry_infra.md` already warns about in the single-service case
(`cpu: 1.0` → 1.1 desired → rounds to the 2 vCPU tier). A four-replica worker
pays it four times. The existing mitigation (request slightly under a tier
boundary) now needs stating per process type rather than per service.

### Two rules restate more cleanly

- **No sidecar for `scheduler` process types.** Today a whole-service statement;
  per process type it is strictly better — a codebase with `web` +
  `nightly_cleanup` gets one sidecar for the web process and none for the job,
  which the service-level phrasing could not express.
- **Reserved-key enforcement spans both env levels.**
  `_RESERVED_CORE_ENV_KEYS` (`validate.py:52`) currently guards one `env:`
  block; it now evaluates against each process type's effective env, or a
  project could shadow `OTEL_SERVICE_NAME` at process level and slip past.

`service.version` stays `${project_version}` — project-wide, from one image.
That is what makes "a persistent web/worker version mismatch is a real signal"
observable: divergence in the backend means a stuck rollout, not a config
difference.

## CICL Version and Rollback

`cicl_version` is parsed at `model.py:117` and **never validated or acted on**.
It exists for exactly this situation.

**Bump to `cicl_version: "2"` and reject `"1"`** with a message naming the
upgrade guide. One parser, one clear error, and the field finally earns its
place. Specifically *not* a compatibility shim accepting both forms — that
reintroduces the flat shorthand as a permanent second code path.

That exposes a sharp edge the first draft missed.
[`cicd.md § Rollback`](../../../../doctrine/infrastructure/cicd.md#rollback)
step 3 recompiles the target version's `infra.yml` **using the current docex**,
and precondition 1.3 permits any target within one minor version. So after this
advance ships:

```
./bin/docex rollback prod <pre-advance-version>
  → ephemeral worktree at the old tag   (flat infra.yml, cicl_version "1")
  → recompile with current docex        (requires processes:, cicl_version "2")
  → compile error
```

It fails *safely* — the recompile precedes any apply — but during an outage,
which is the one moment you cannot afford to discover it.

**Add a rollback precondition:** check the target tag's `cicl_version` against
what the running docex supports, as part of step 1's pre-flight, and abort with
*"cannot roll back across the CICL v1→v2 boundary — fix forward"* before
touching anything. A precondition, not a capability.

**Operational consequence for the release plan:** for exactly one release cycle
after the advance ships, prod has **no rollback path**. Once a successor version
exists, rollback within the new major works normally. Accept and document the
window rather than building a read-only flat-form parser for one code path.

## Rejected Alternatives

Recorded so they are not re-litigated.

1. **Deep refactor into genuinely separate web and worker images.** Does not
   remove the coupling — it *relocates* it from the code layer to the database
   layer. If both touch the same tables, either one violates `schema_owned_by`
   or the database must split too. Coupling in code is visible, type-checked,
   and refactorable; coupling through a shared schema is invisible, untyped, and
   unrefactorable. A strictly worse trade.

   Legitimate when the split is real — needs at least one of: a different
   bounded context; a radically different runtime footprint (GPU, ffmpeg, model
   weights) making a shared image wasteful; a different security posture
   (untrusted uploads, different IAM role, no DB write); a different language.
   *"It is async now"* is not on that list.

2. **A single `engine` process serving HTTP and consuming in one container.**
   Makes independent scaling impossible (the motivating "two web, four workers"
   is unreachable), collapses failure domains (a runaway job OOMs the HTTP
   edge), shares one connection pool, and has irreconcilable shutdown semantics
   (fast drain vs. long job). Acceptable as a temporary shortcut at trivial
   volume; disqualifying as doctrine because it cannot grow.

3. **A shared internal library consumed by two images.** Permitted by Factor 1,
   and the honest form of (1). Costs a versioning treadmill, lockstep releases,
   and a fourth artifact kind that is neither core nor backing service.

4. **A thin dispatcher worker** that owns no domain and calls back into the web
   service's contract. Preserves "no shared code" honestly and is fine for
   *triggering* (it is what "a cron container that curls an endpoint" is), but
   not for *doing*: capacity is not decoupled, only the trigger moved, and long
   tasks fight HTTP timeouts.

5. **Flat `build: api` instead of nesting.** Cannot express which fields are
   shared vs. per-process-type, needs a dangling-reference validation, and
   requires repeating `secrets:` with a consistency check.

6. **One merged field interpreted by target kind** (`depends_on` meaning
   readiness for backing targets, interface for core targets). Coherent, and the
   compiler *can* tell. Rejected because the cycle rule would become
   target-kind-dependent (fatal for backing, legal for core — hard to state and
   harder to error on), because a reader could no longer tell what an edge means
   without cross-referencing another block, and because it reintroduces the
   original false assertion for human readers even with a correct compiler.
   `depends_on` and `consumes` are not two synonyms: the first is compose's own
   field with compose's semantics, the second is contract-testing's own term
   (Pact's consumer/provider, already used in `contracts.md`).

7. **A flat single-process shorthand alongside `processes:`.** Saves a few lines
   per single-process service; costs a collapse conditional in every identity
   derivation, a "collapsed or qualified?" question at every read site, a
   dual-form validation surface, and a permanent second code path. See
   [Why `processes:` is mandatory](#why-processes-is-mandatory).

8. **Heartbeat in the cache.** Worker `SETEX`es `(process, instance, version)`
   from inside the loop; freshness is the TTL, evaluated by the cache's own
   clock (so no skew), and it yields a live-instance count. Rejected because it
   requires a compile rule forcing any project with a consumed non-web process
   type to declare a `cache` backing service — infrastructure conscripted by a
   health-check requirement.

9. **Heartbeat in the owned relational DB.** Rejected for the same
   infrastructure-conscription reason, plus a table and migration owned by the
   schema owner, constant row churn in a schema meant to model the domain, and a
   genuine cross-container clock-skew comparison.

10. **`deploy.replicas` on fixed.** Cannot pair one netns sidecar with N
    replicas, and forces dropping `container_name`. See
    [Replicas → Fixed](#fixed--unroll-do-not-scale).

11. **A `cicl_version` compatibility shim** accepting both flat and nested
    forms. Bounded, but reintroduces the shorthand as a second permanent parser
    to serve one code path (rollback recompiles) for one release window.

The single graph the merged form was reaching for is still available as a
**view**: `describe/dag.py` should render the union with edge kinds visually
distinguished (solid readiness, dashed interface). One DAG for understanding;
two relations for enforcement.

## Doctrine Files Touched

**Resident stratum:**

- `hexagonal_architecture/internal_dependency_rules.md` — rewrite composition
  root responsibility (4): the root *constructs* driving adapters; entrypoints
  *bind* them to a runtime host. Add: one composition root, one entrypoint per
  process type.
- `hexagonal_architecture/hex_overview.md` — add `entrypoints/` to the `src/`
  tree; add a `Queue` row to the controller-mechanism table; optionally note
  that entrypoints are too thin to test (if one needs a test, it does too much).
- `infrastructure/infrastructure.md` — re-scope "core services never share
  code" to core service **sources**; sibling process types are one codebase, so
  nothing is shared and the rule's intent is preserved. Also § Contracts, where
  provider/consumer relationships are "inferred from `infra.yml`'s depends-on
  relationships" → `consumes`.
- `lexicon.md` — add **Process Type** and **Entrypoint**; clarify **Core
  Service** as codebase + build artifact.
- `practices/logging.md` — the dev telemetry-watching command becomes
  `docker compose logs -f <svc>-<proc>-otelcol`.

**Conditional stratum:**

- `infrastructure/cicl.md` — the mandatory `processes:` block, field scoping,
  `consumes:`, the `depends_on` restriction, `command` required, four-segment
  core magic refs, `domain_default_process`, the two-segment hostname label, and
  rule restatements 5/7/10/12/14/15/16. Plus § Depends-On Relationships, whose
  roles 2 (provider/consumer) and 3 (downstream chain) move to `consumes`.
- `infrastructure/contracts.md` — path, provider derivation (union of `consumes`
  and web-network), format rules, and the health-declared-by-fields rule.
- `infrastructure/cicd.md` — check-step item 3.2 ("contracts exist which match
  `infra.yml` depends-on relationships"); § Build Step's dev-iteration process
  (exec → `compose run` against the exec service); § Rollback's new
  `cicl_version` precondition.
- `infrastructure/docex.md` — the `check` blurb's "`depends_on`-to-contract
  alignment"; the `build` blurb's "inside its running dev-stage container";
  the `role` blurb's magic-ref form.
- `infrastructure/shape.md` — `core_service` and `telemetry_sidecar` rows; both
  **Runtime Shape** paragraphs' replica load-balancing claim.
- `infrastructure/tests.md` — staging liveness "each core service responds to
  its health-check endpoint" → per process type.
- `infrastructure/telemetry.md` — "one per core service container" (:84),
  "injected into each core service" (:113), the `<svc>-otelcol` tail command
  (:125).
- `infrastructure/specifics/scheduler.md` — scheduler as a process type; the
  Ofelia job name and shared codebase image (retiring mod 074's self-contained
  job image); delete the `test.sh` one-off carve-out in § Caveats.
- `infrastructure/specifics/transfer_tables.md` — per-process emission; the new
  `container_definition` destination; § Per-container (fixed)'s
  `container_name` + `aliases` + unqualified-traefik-label rules; § Per-core-service
  env's `OTEL_SERVICE_NAME` row and two new resource attributes; the envinfra tag
  block's `process` tag and process-qualified `Name`; the `worker` role in
  § Authoring Project-Local Transfer Tables' bundled-engine list.
- `infrastructure/specifics/migrations.md` — § Dev and Test Mechanism rewritten
  from `compose exec` to `compose run` against the exec service.
- `infrastructure/specifics/telemetry_infra.md` — § Env Vars Injected on Core
  Services, § Sidecar as Paired Compose Service, § Sidecar as Paired Task
  Container, § Task-Level Resource Allocation (the N × R arithmetic).
- `infrastructure/specifics/networks.md` — per-service attachment becomes
  per-process attachment.
- `infrastructure/preinfra/fixed_master_network.md` — the Lua comment's "three
  canonical doctrine forms".
- A new `upgrade_<version>.md`.

**Tables:** `tables/roles/worker.yml` (new); `tables/naming_policies.yml`
(`http_host` gains `max_len: 63`).

**Skills:** `infra-compile` and `contracts` pointers need checking; the
`testing` skill may need a line on where entrypoints sit.

## docex Work

- `cicl/model.py`, `cicl/validate.py` — mandatory non-empty `processes:` and
  `consumes:`; restrict the service level to `{processes, secrets, config, env}`;
  restrict `depends_on` targets to backing services; scope per-process vs.
  per-service fields, merging `env:` process-over-service; reject bare-service
  `consumes` targets; require `command` on every process type; reject `replicas`
  on a `scheduler`; reject `web` membership on `worker`/`scheduler`; enforce
  `cicl_version: "2"`; rendered-identity uniqueness (rule 5); reserved env keys
  across both levels; rules 10/12/14/15/16 per process type.
- `cicl/compile.py` — expand each core service into N compiled process types
  with two-segment `CompiledService.name`; unroll `replicas` on fixed-prod.
- `cicl/magic_refs.py` — four-segment core refs, three-segment backing refs,
  arity check by kind, `target_process` on `MagicRefDependency`, self-ref
  rejection, extended cycle-guard key.
- `emit/compose.py` — **not** unchanged: the per-codebase exec service; the
  replica unroll with network aliases and unqualified traefik labels;
  `container_name: {global}-{i}`; Ofelia job name and shared codebase image.
- `emit/hcl.py` — one ECS service per process type, all referencing one image;
  `desired_count = replicas`; the new `container_definition` renderer.
- `pipeline/check.py` — replace `_infer_contract_format` with role-derived
  format driven off `consumes:`; provider set = `consumes` targets ∪
  web-network process types; right-anchored contract-filename parsing; assert
  `port` + `health_check_path` on `consumes` targets. **Leave the curl gate
  keyed off `health_check_path`.**
- `pipeline/preinfra.py` — the dev web-hostname DNS check goes per web process
  type.
- `pipeline/rollback.py` — the `cicl_version` compatibility precondition.
- `orchestrate/_common.py` — delete `compose_service_key`; add
  `exec_service_key`.
- `orchestrate/build.py`, `test.py`, `migrate.py` — route through the exec
  service; drop `build.py`'s local suffix heuristic.
- `describe/dag.py`, `describe/llm.py` — render both edge kinds; process
  dimension in node identity.
- Containerize — **no change needed**; `core_services()` already yields one
  entry per codebase.

## Settled Conventions

Decided; recorded here so the mods that implement them need no further input.

1. **`processes:` is always present** on a core service, non-empty; there is no
   flat form and no shorthand.
2. **`consumes` target form** — dotted and fully qualified, `api.worker`. A bare
   service name is illegal rather than shorthand.
3. **`env:` composition** — process-level merges over service-level. It is the
   only field valid at both levels.
4. **Service level accepts only** `{processes, secrets, config, env}`; anything
   else is a hard error.
5. **`command` is required on every process type**, including `web`.
6. **`replicas` on a `scheduler` process type** — a compile error, consistent
   with how `schedule:` is rejected on every non-scheduler role. Inert fields
   fail rather than being silently ignored.
7. **Process types are named after their role** unless a codebase declares two
   on the same role (convention, not rule).
8. **Hostname labels are single and hyphen-joined**; dots for authoring and
   reference, hyphens for emission.
9. **Health thresholds are doctrine-fixed** — 10 s loop tick, 30 s handler
   staleness; fan-out is one hop.
10. **`cicl_version: "2"`** gates the break; `"1"` is rejected, not shimmed.
11. **Log groups are per process type** (automatic from `CompiledService.name`).

## Migration

This advance is **not additive**. Every project must:

1. **Rewrite `infra.yml`** — nest every core service's fields under a
   `processes:` block with at least one named process type; move `secrets:`,
   `config:`, and shared `env:` up to the service level; add `command:` to every
   process type; set `cicl_version: "2"`.
2. **Reclassify every core→core `depends_on`** as `consumes:` (interface) or
   delete it (spurious). Add `consumes:` edges that exist only asynchronously
   (through a broker) and therefore have no magic ref.
3. **Qualify core magic refs** — `${core_services.api.host}` →
   `${core_services.api.web.host}`.
4. **Rename `domain_default_service` → `domain_default_process`** and qualify
   its value.
5. **Rename contract files** — `api.openapi.yml` → `api.web.openapi.yml`.
6. **Add `port` and `health_check_path`** to every process type named in a
   `consumes:` edge, and implement the in-process tick and `/health` handler in
   its entrypoint.
7. **Update health fan-out paths** in the consumer's contract and
   implementation — `/health/api` → `/health/api/web`.
8. **On fixed: add public DNS records for every new web hostname**
   (`api-web.dev.…`) **before** `envinfra up dev`, or Let's Encrypt's
   failed-authorization rate limit will trip. `docex preinfra development`
   surfaces the gap.
9. **Expect new emitted names** for every core service — containers, ECS
   services, task definitions, log groups, sidecars, traefik routers, hostnames.
   The [not-process-qualified table](#what-is-not-process-qualified) is the
   inventory of what *doesn't* move.

**Rollback is unavailable across the boundary.** For one release cycle after
adopting this version, prod has no rollback path; `docex rollback` refuses at
pre-flight with a fix-forward message. Plan the cut accordingly.

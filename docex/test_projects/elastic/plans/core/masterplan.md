# docex_smoke_elastic — Masterplan

## Purpose

This is one of two **doctrine smoke-test projects** that ship inside the `docex/` tree. It is *not* a real product — it exists so that, before cutting a minor or major `docex` version, the operator can drive a real `elastic`-foundation project end-to-end through `projinfra → envinfra → check → merge → containerize → release stage → stagetest → release prod → teardown` and surface the bugs that only appear against real infrastructure.

The companion project at `docex/test_projects/fixed/` exercises the `fixed`-foundation path. Together they cover the two foundations the doctrine commits to.

The architectural shape, services, and flows are **deliberately identical** to the fixed-foundation companion — same one codebase and three core services, same one schema-owning backing service, same two project-local container backings, same `Ping` domain, same health model (one `health.sh` per codebase, invoked per core service), same composition-root-plus-entrypoints layout. The only intended differences are:

1. `foundation: elastic` in `infra.yml` (and the AWS-resource shape that compiles from it).
2. `reverse_proxy: alb` declared explicitly (the doctrine default, also the operator-chosen smoke variant — see mod 044's neutral-on-ALB-vs-EC2-traefik stance).
3. `dev` and `test` still compile to fixed compose stacks (per `shape.md § Shape and Environment`), but `stage` and `prod` compile to AWS HCL — RDS for `appdb`, ECS Fargate for `api-web`/`api-worker`/`api-clock`/`probe`/`events`, ALB at project tier, ECR for images (**one** repo, because there is one codebase), EFS-backed persistent storage for ClickHouse (`events`). There is no EventBridge Scheduler and no scheduled task: the clock is an ordinary `ecs_service`.

That this project's *application code* is identical to the fixed companion's is intentional. Any inter-foundation divergence in source code would mean the parts-only secret-and-env model is leaking — that itself is a doctrine bug. The PRE_CUT_CHECKLIST's audit step diffs the two `core/` trees and fails on real divergence.

## Objectives

1. **Exercise the elastic-foundation release path end-to-end** — master VPC preinfra discovery, project-tier `tofu apply` (with two-phase NS-delegation pause), state backend bootstrap, Route53 zone, ACM cert validation, ALB SNI cert binding, ECR auth, IAM execution-role inline policy, SSM secret push, ECS task definitions, the first-time-release migration ordering swap.
2. **Stay doctrine-faithful** — same as fixed companion. Inception ambiguities surface here and get fixed in doctrine.
3. **Stay cost-bounded** — `teardown.sh` + `verify_clean.sh` are first-class deliverables, not afterthoughts. RDS `deletion_protection` and ECR `force_delete` overrides at retirement time per the smoke-project safety pattern from `docex_process.md`.

## Terms

Identical to fixed companion. `Ping`, `Codebase`, `Core service`, and `Smoke test` carry the same meanings.

## Architecture

### Foundation

`elastic`. `dev` and `test` run as local docker stacks on the dev machine (always fixed-style per shape.md); `stage` and `prod` run as AWS infrastructure in the shared master VPC (region `us-east-1`).

### Domain

`apex_domain: luxrnd.tech` — the bare apex. Project segment derives from `project.yml`'s `name` field DNS-labeled, yielding `docex-smoke-elastic.luxrnd.tech` as the project subdomain. A Route53 hosted zone for `docex-smoke-elastic.luxrnd.tech` is provisioned by `docex projinfra up production`; the operator NS-delegates from the parent `luxrnd.tech` zone (also in Route53, same account) between projinfra's two-phase apply.

Per-env hosts compile to the doctrine's canonical form `<codebase>-<service>.<env>.docex-smoke-elastic.luxrnd.tech` — two segments in one DNS label, hyphen-joined:
- `api-web.dev.docex-smoke-elastic.luxrnd.tech` (local, served by the dev-side per-project Traefik)
- `api-web.test.docex-smoke-elastic.luxrnd.tech` (local, same)
- `api-web.stage.docex-smoke-elastic.luxrnd.tech` (project ALB, stage cert)
- `api-web.prod.docex-smoke-elastic.luxrnd.tech` (project ALB, prod cert)

Plus the bare-env and bare-project forms per `cicl.md § Domain`. ACM issues two certs (stage + prod) with the doctrine-spec SANs.

### Backing Services

| Service | Role | Engine | Engine on elastic | Purpose |
| ------- | ---- | ------ | ----------------- | ------- |
| `appdb` | `relational_db` | postgres 15 | RDS | Stores `pings` rows. `schema_owned_by: api` — a codebase, never a core service. |
| `probe` | `sidecar` (project-local) | nginx | ECS Fargate task | Stateless reachability target. |
| `events` | `analytics_db` (project-local) | clickhouse | ECS Fargate task + EFS | Stateful OLAP backing; EFS mount per AZ; opt-in AWS Backup. |

The two project-local backings are declared in `infra/transfer_tables/{sidecar,clickhouse}.yml`. ClickHouse exercises the doctrine's `persistent_storage` machinery: an `aws_efs_file_system` per service, mount targets in each private subnet, a `volume`+`mountPoints` entry on the ECS task definition with `transit_encryption: ENABLED`. With `backups: true` declared, the compiler also emits `aws_efs_backup_policy.events`.

### Core Services

Same **one codebase and three core services** as the fixed companion: `api`, with core services `web`, `worker`, and `clock`. Same hex modules (`pings`, `processor`, `jobs`, `retention`), same domain types, same ports/adapters/alogic. The code is **literally the same source tree** at the `core/<codebase>/` level — see "Code duplication between fixed and elastic test projects" below.

| Codebase | Core service | Role | Networks | Port | On elastic |
| -------- | ------------ | ---- | -------- | ---- | ---------- |
| `api` | `web` | `web` | `web`, `internal` | 8080 | task_definition + ecs_service + ALB target group |
| `api` | `worker` | `worker` | `internal` | 8081 | task_definition + ecs_service, **no** target group |
| `api` | `clock` | `clock` | `internal` | — | task_definition + ecs_service, **no** target group, **not** Service-Connect-registered, stop-then-start deployment |

One ECR repo and one image tag per **codebase** — so with one codebase there is exactly **one** of each, and all three core services share that tag started three different ways. Likewise **one** `…-migrate` task-definition family.

#### `api` — the application codebase

See [`api/api.md`](./api/api.md). Three core services on one artifact; `web` and `worker` were two separate codebases until CICL v2, purely because pre-v2 CICL could not express "one artifact, two invocations".

- **Hex modules**: [`pings`](./api/hex/pings.md) (driven by `api.web`), [`processor`](./api/hex/processor.md) (driven by `api.worker`), [`jobs`](./api/hex/jobs.md) (deferred by `api.clock`, performed by `api.worker`), and [`retention`](./api/hex/retention.md). They share a codebase but not a module boundary; the sole cross-module import is `jobs`' runner taking `retention`'s **driving port**.
- **Contracts**: three, one per declared **surface** — `api.web.rest.openapi.yml`, `api.worker.rpc.asyncapi.yml`, and `api.worker.events.asyncapi.yml`. The path is `<codebase>.<service>.<surface>.<format>.<ext>`, keyed on the surface rather than on the core service, and the format follows from that surface's `api_styles` rather than from the core service's `role` (`cicl.md § Surfaces`). **Declaring a surface is what makes a core service a provider**, and one that declares none cannot be a `uses` target at all — which is why `api.clock` has no contract.
- **`uses`**: `api.web` uses `api.worker`, one direction only, obliged by the five-segment magic refs `${codebases.api.core_services.worker.{host,port}}` on the web edge.
- **Schema owner**: `schema_owned_by: api`.

`api.web`: a Fargate task in the `web` + `internal` security groups; ALB target group registered with a listener rule matching its per-env hosts. It is the `domain_default_service`, so prod's edge also answers at the bare-env and bare-project hosts.

`api.worker`: a Fargate task in the `internal` security group only — never an ALB target. It declares **no `health_check_path`** (rule 33 confines that field to `web`-network core services) and **serves no `/health`**; its liveness is a **tick file** at `/tmp/worker.tick`, touched by the poll loop and stat'd by `./health.sh worker` from a separate process, emitted as the task definition's container `healthCheck`. A wedged poll loop therefore gets the task killed and replaced by the service. It carries `port: 8081` because `api.web` **addresses its `rpc` surface directly** (`POST /drain`) — rule 32's positive arm — and it declares **two surfaces**, `rpc` and `events`, both resolving to `asyncapi`; two rather than one because their consumer sets are unrelated (`api.web` calls `rpc` synchronously; `events` is produced onto by `api.web` and `api.clock` and consumed here). On elastic that same `port` is also what registers the worker's **Service Connect** name, which is what lets `api.web` resolve it — and since both `api.web` and `api.clock` `uses` this worker, its registration is the single thing keeping `release`'s Service Connect consumer reconcile exercised with a non-empty consumer set. `desired_count = 2` in prod (from `replicas: 2`), 1 in stage.

#### `api.clock` — the scheduler that is an ordinary core service

`api.clock` is a **long-running singleton Fargate task**, not a triggered job. A schedule is a property of an invocation, not of a deployment, so the clock is simply the invocation that owns the cron loop.

- **Schedules**: `prune_pings: "0 3 * * *"` and `heartbeat: "* * * * *"`, bare 5-field UTC cron with no dialect translation. Delivered as a **literal task-definition env entry**, `DOCEX_SCHEDULES_YAML` — the same variable, carrying the same literal YAML, as on the fixed companion. One mechanism, both foundations.
- **It validates its own schedule at startup.** Before entering the loop, the clock compares every scheduled name against `ContJobsCron`'s dispatch table and **exits non-zero** if any has no binding, naming both the offending job and the implemented set. On elastic this means the task fails to stay up and the deploy does not converge — a typo in `schedules:` fails the *release*, rather than surfacing at 03:00 as a logged failure. The reverse — a bound job with no schedule — is legitimate and deliberately unchecked, because `ContJobs` is shared and a job reachable only over HTTP or CLI is a design choice.
- On elastic: `task_definition` + `ecs_service`, **no** target group. Its probe is not routed by any declared field — it arrives as a transfer-table **default** on `role: clock`, `["CMD", "./health.sh", "clock"]`, and a `defaults` probe lands on the engine's default target, which for a core service is the task definition's container. So `./health.sh clock` runs inside the task, stats the cron loop's tick file, and a wedged loop gets the task **killed and replaced** by the service — ECS acts on a failed essential container, which is why the role tables also carry `startPeriod: 10` and why that field is elastic-only.
- **It joins Service Connect as a client-only member.** Its `service_connect_configuration` carries `enabled = true` and the namespace but **no** `service {}` block, because a `service {}` block is emitted only for a core service that declares a `port`. It therefore resolves its peers — `api-worker`, the sidecars — and nothing can resolve *it*, which is exactly right: nothing addresses a clock.
- **It binds no application socket.** Not "listens where nothing reaches it" — nothing at all. Inside the running container `/proc/net/tcp` carries exactly one `LISTEN` entry, docker's embedded DNS resolver at `127.0.0.11`, which every container has. It declares no `port`, no `health_check_path`, and no `surfaces`, and `entrypoints/clock.py` imports neither uvicorn nor fastapi. That is the strongest single piece of evidence that liveness left HTTP, so it is recorded as observed fact rather than as an intention.
- **`deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100`**, emitted for `role: clock` alone. ECS rolling-deploy defaults briefly run two tasks, and a tick landing in that window fires twice; stop-then-start trades a possible **double fire** for a possible **missed fire** — the right trade, since missed fires are already an accepted caveat and jobs must be idempotent regardless.
- **What is gone**: no `aws_scheduler_schedule`, no EventBridge Scheduler, no per-service scheduler-invocation IAM role, and one fewer AWS resource type `verify_clean.sh` has to check for leaks. EventBridge was not merely surplus — it lives outside the VPC and could not have invoked an in-VPC Fargate target at all.
- **Contract**: none, and that is the ordinary rule rather than an exemption. **It declares no surface, and that is what makes it not a provider** (`cicl.md § Surfaces`).
- **It defers; it does not work.** Each fire inserts onto the `jobs` table in RDS; `api.worker` drains it.

#### Why there is only one codebase

Until the clock advance there were two: `api`, and a scheduler-only codebase named `reaper`. When `role: scheduler` was retired, **`reaper` could not become a clock** — a clock defers onto its own codebase's queue, only the schema-owning codebase may enqueue, and `reaper` owned no schema, no worker, and no queue. `api` owns all three. `reaper` was deleted and its retention rule became the [`retention`](./api/hex/retention.md) module.

The walk therefore stopped covering the two-codebase shape — notably the two-ECR-repo count. That loss is deliberate and is recorded in `docex/plans/core/test_projects.md § Shape`, which is where a reader who finds one codebase should look before concluding the doc is stale.

### Composition Roots and Entrypoints

Identical to the fixed companion: one `root.py` per **codebase** that constructs without activating, and one module per core service under `src/entrypoints/` that each core service's `command` invokes. See [`api/api.md`](./api/api.md) § Entrypoints for the worker's loop, signal handling, and liveness tick file, and § Health for the probe that reads it.

### Code duplication between fixed and elastic test projects

Per the kickoff brief: "Two separate projects, one per foundation. Cleaner than a single toggleable project, even if it means some duplication." The two projects each carry their own full copy of `core/api/`. This is doctrine-faithful ("core services never share code"; each project has one project root) and accepts duplication as the cost.

**Smoke-test side benefit:** drift between the two source trees becomes a signal. The PRE_CUT_CHECKLIST's audit step (`diff -r test_projects/fixed/core test_projects/elastic/core`) should produce no output. Differences would mean the parts-only env model is leaking foundation specifics into application code — itself a doctrine bug.

## Flows

Identical to the fixed companion, by name: Ping creation, Ping processing, **Self health** (`GET /health` on `api.web` alone, because the ALB reads it; the worker's and the clock's liveness is a tick file at `/tmp/<svc>.tick` that `./health.sh <svc>` stats from a separate process), **Deferred-job drain** (`POST /jobs/drain` on `api.web` → the worker's `rpc` surface → `{"performed": N}` back out through the edge), backing reachability (`/diagnostics/probe`, `/diagnostics/events`), scheduled deferral, job draining, and clock self health. There is no health fan-out anywhere and none is possible — `healthchecks.md § What this doctrine does not do` forbids one service reporting on another.

On elastic these exercise RDS (postgres), **Service Connect** (peer resolution between core services and the nginx sidecar — and it is the drain flow, not a health hop, that now depends on the sibling `api.web` → `api.worker` resolution), and a TCP connection to ClickHouse on its native port through the EFS-backed Fargate task. Liveness is read from the orchestrator, never over the network: ECS carries every core service's container-health verdict and `docex stagetest` reads it from there.

The deferral flow is where the foundations **converge** rather than diverge: the clock is a plain `ecs_service` reading the same `DOCEX_SCHEDULES_YAML` literal it reads on fixed, enqueueing into RDS instead of a container postgres. Nothing about it is foundation-shaped — which is the point of retiring `role: scheduler`, whose fixed (Ofelia + DooD) and elastic (EventBridge + IAM role) halves shared no mechanism at all.

## Hard Boundaries

Same as fixed companion — including the deliberate **one-codebase** shape, which is not drift and must not be "restored" — plus:

- This project has **no health fan-out**, and no core service reports on another's health. It had a `/health/api/worker` endpoint and deliberately does not any more (`healthchecks.md § What this doctrine does not do`). On elastic that absence is load-bearing rather than cosmetic: liveness is read from the ECS API, not fetched through the ALB, so nothing ever needs an in-network proxy to reach `api.worker` or `api.clock`. `POST /jobs/drain` is not a counter-example — it commands work and returns a count of it, and carries no verdict about whether the worker is well.
- This project does **not** use any AWS resource outside what the elastic transfer tables prescribe. If a real elastic project would need (say) SQS or SNS, that's beyond the smoke test's scope.
- This project does **not** carry IAM roles outside what `docex projinfra up production` provisions at the project tier. If a service-specific *task* role is needed, that's a doctrine gap or a docex bug — flag it.
- This project does **not** opt into the `ec2_traefik_*` reverse-proxy variants. ALB is the doctrine default and the operator-chosen smoke variant. Walking EC2-traefik is a future smoke-walk variant covered by a different setup.

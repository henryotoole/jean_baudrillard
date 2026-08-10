# docex_smoke_fixed — Masterplan

## Purpose

This is one of two **doctrine smoke-test projects** that ship inside the `docex/` tree. It is *not* a real product — it exists so that, before cutting a minor or major `docex` version, the operator can drive a real `fixed`-foundation project end-to-end through `projinfra → envinfra → check → merge → containerize → release stage → stagetest → release prod → teardown` and surface the bugs that only appear against real infrastructure.

The companion project at `docex/test_projects/elastic/` exercises the `elastic`-foundation path. Together they cover the two foundations the doctrine commits to.

## Objectives

1. **Exercise the fixed-foundation release path end-to-end** — the surface that unit tests structurally can't reach.
2. **Stay doctrine-faithful** — every artifact should be what current doctrine prescribes a fixed-foundation project to look like. If walking the inception flow surfaces an ambiguity, the fix lands in the doctrine, not in a workaround here.
3. **Exercise the project-local transfer-table feature** — `infra/transfer_tables/{sidecar,clickhouse}.yml` declare two project-local engines (a stateless nginx sidecar and a stateful ClickHouse analytics_db) so each cut exercises the deep-merge path, container-backings on the dispatch surface, and (on the elastic counterpart) the EFS persistent-storage machinery.

## Terms

| Term | Meaning |
| ---- | ------- |
| Ping | A small unit of work created by the `api.web` core service and consumed (processed) by the `api.worker` core service. Postgres-mediated; no real queue. |
| Job | A named unit of deferred work. `api.clock` enqueues one when a schedule fires; `api.worker` claims and performs it. Carries a name and no payload. |
| Codebase | One source tree, one build artifact, one image. `api` is the only codebase here. |
| Core service | One named way of invoking a codebase's artifact — its own role, command, port, networks, and resources. Emitted as `<codebase>-<service>`. |
| Smoke test | The operator-driven manual walk through `PRE_CUT_CHECKLIST.md` against this project before a `docex` cut. |

## Architecture

### Foundation

`fixed`. Production runs as docker containers on a single host machine — for this test project, the operator's dev machine. All four environments (`dev`, `test`, `stage`, `prod`) run side-by-side on that one host; the per-project Traefik distinguishes them by Host header.

### Domain

`apex_domain: luxrnd.tech` — the bare apex domain (`infra.yml` rule 13). The project segment is derived from `project.yml`'s `name` field DNS-labeled, yielding `docex-smoke-fixed.luxrnd.tech` as the project subdomain. Per-env hosts compile to the doctrine's canonical form `<codebase>-<service>.<env>.docex-smoke-fixed.luxrnd.tech` — two segments in one DNS label, hyphen-joined, e.g. `api-web.prod.docex-smoke-fixed.luxrnd.tech` — plus the bare-env (`<env>.docex-smoke-fixed.luxrnd.tech`) and bare-project (`docex-smoke-fixed.luxrnd.tech`) forms, both of which route to `domain_default_service: api.web`.

TLS certs are issued by the per-project Traefik via Let's Encrypt's DNS-01 challenge against the parent `luxrnd.tech` zone in Route53 (HTTP-01 won't work for wildcards). Traefik's Route53 credentials and ACME email are supplied at runtime as `TRAEFIK_DNS_PROVIDER`/`TRAEFIK_ACME_EMAIL` env vars on the project Traefik container (operator-side setup).

Inbound 443/80 reaches the host machine's HAProxy `web_demux` (preinfra; see `doctrine/infrastructure/preinfra/fixed_master_network.md`), which SNI-routes to the per-project Traefik via the `docex-ingress` bridge.

### Backing Services

| Service | Role | Engine | Purpose |
| ------- | ---- | ------ | ------- |
| `appdb` | `relational_db` | postgres 15 | Stores `pings` rows. `schema_owned_by: api` — a codebase, never a core service. |
| `probe` | `sidecar` (project-local) | nginx | Stateless sidecar reachability target. |
| `events` | `analytics_db` (project-local) | clickhouse | Stateful OLAP container backing; opts into AWS Backup on elastic. |

The two project-local backings exercise the project-local transfer-table feature: `infra/transfer_tables/{sidecar.yml, clickhouse.yml}`. On fixed, `events` mounts a named docker volume; on the elastic counterpart, the engine declares `persistent_storage` and emits an EFS filesystem with mount targets in each private subnet.

### Core Services

**One codebase, three core services.** It is hexagonally-architectured per `doctrine/hexagonal_architecture/` and written in Python.

| Codebase | Core service | Role | Networks | Port | Trigger |
| -------- | ------------ | ---- | -------- | ---- | ------- |
| `api` | `web` | `web` | `web`, `internal` | 8080 | long-running |
| `api` | `worker` | `worker` | `internal` | 8081 | long-running |
| `api` | `clock` | `clock` | `internal` | — | long-running |

One image per **codebase**, so all three run the same tag started three different ways — one build, one registry repo, one `-exec` container, one `migrate.sh` run per release, three sidecars.

#### `api` — the application codebase

See [`api/api.md`](./api/api.md). Three core services on one artifact; `web` and `worker` were two separate codebases until CICL v2, purely because pre-v2 CICL could not express "one artifact, two invocations".

- **Hex modules**: [`pings`](./api/hex/pings.md) (driven by `api.web`), [`processor`](./api/hex/processor.md) (driven by `api.worker`), [`jobs`](./api/hex/jobs.md) (deferred by `api.clock`, performed by `api.worker`), and [`retention`](./api/hex/retention.md) (reached only through the `prune_pings` job). They share a codebase but not a module boundary; the sole cross-module import is `jobs`' runner taking `retention`'s **driving port**, which is the one the doctrine permits.
- **Contracts**: three, one per declared **surface** — `api.web.rest.openapi.yml`, `api.worker.rpc.asyncapi.yml`, and `api.worker.events.asyncapi.yml`. The path is `<codebase>.<service>.<surface>.<format>.<ext>`, keyed on the surface rather than on the core service, and the format follows from that surface's `api_styles` rather than from the core service's `role` (`cicl.md § Surfaces`). **Declaring a surface is what makes a core service a provider.** One that declares none has no boundary to be used across and cannot be a `uses` target at all — which is the whole reason `api.clock` has no contract.
- **`uses`**: `api.web` uses `api.worker`, one direction only. `api.web` holds five-segment magic refs to `${codebases.api.core_services.worker.host}` / `.port`, which is what obliges the edge (rule 7); the worker never calls the web edge, so the reverse edge would be a false declaration.
- **Schema owner**: `schema_owned_by: api`. `migrate.sh` runs once for the codebase, not once per core service.

`api.web` is the `domain_default_service`, so prod's web edge answers at three hosts: `api-web.prod.docex-smoke-fixed.luxrnd.tech`, `prod.docex-smoke-fixed.luxrnd.tech` (bare-env), and `docex-smoke-fixed.luxrnd.tech` (bare-project).

`api.worker` is never routed, and it declares **no `health_check_path`** — rule 33 confines that field to `web`-network core services. It carries `port: 8081` because `api.web` **addresses its `rpc` surface directly** (`POST /drain`), which is rule 32's positive arm: a directly addressed target must declare the port it is addressed on. It declares **two surfaces**, `rpc` and `events`, both resolving to `asyncapi`; they are two rather than one because their consumer sets are unrelated — `api.web` calls `rpc` synchronously and waits for a count, while `events` is produced onto by `api.web` and `api.clock` and consumed here. It **serves no `/health`**: its liveness is a **tick file** at `/tmp/worker.tick`, touched by the poll loop and stat'd by `./health.sh worker` from a separate process. `replicas: 2` is declared and honoured in `prod` only.

`api.web` exposes `GET /health` — the one place HTTP appears in the health model, and only because the reverse proxy has no other way to ask (`healthchecks.md § web services also serve GET /health`) — `POST /jobs/drain`, the consumer side of the worker's `rpc` surface (flow 4), and `GET /diagnostics/probe` + `GET /diagnostics/events`. The last two probe *backing* services rather than core services, and they sit under `/diagnostics` for exactly that reason: left under `/health/*` a reader would reasonably conclude a health fan-out survived under a narrower name, against `healthchecks.md`'s "No service reports on another." They exist so the stage tests catch wiring regressions in Service Connect, SG self-ingress, and EFS mount-target setup on the elastic counterpart.

#### `api.clock` — the scheduler that is an ordinary core service

`api.clock` is a **long-running singleton container**, not a triggered job. That is the whole point of `role: clock`: a schedule is a property of an invocation, not of a deployment, so the clock is simply the invocation that owns the cron loop.

- **Schedules**: declared in `infra.yml` as bare 5-field UTC cron — `prune_pings: "0 3 * * *"` and `heartbeat: "* * * * *"`. The compiler delivers this clock's own job map to the container in **`DOCEX_SCHEDULES_YAML`**, whose value is the *literal rendered YAML* and not a path, identically on both foundations. It also renders `infra/output/<env>/schedules.yml` — a visibility artifact nothing reads at runtime, which is what makes a schedule change show up in review as an infrastructure change.
- **No dialect translation anywhere.** The expression reaches the container verbatim and the codebase's cron library parses it, which deletes a whole class of bug that a cloud scheduling primitive forces.
- **It validates its own schedule at startup.** Before entering the loop, the clock compares every scheduled name against `ContJobsCron`'s dispatch table and **exits non-zero** if any has no binding, naming both the offending job and the implemented set. A typo in `schedules:` fails the *deploy*, visibly, instead of surfacing at 03:00 as a logged failure. The reverse — a bound job with no schedule — is legitimate and deliberately unchecked, because `ContJobs` is shared and a job reachable only over HTTP or CLI is a design choice.
- **It defers; it does not work.** Each fire enqueues onto the `jobs` table and returns. The work is `api.worker`'s.
- **No exemptions.** It gets a container probe like every other core service — `./health.sh clock`, sourced from the cron loop's tick file at `/tmp/clock.tick` — and an OTel sidecar like every other core service. `replicas` is forbidden on a clock — it is a singleton — and on elastic it deploys stop-then-start (`deployment_minimum_healthy_percent = 0` / `maximum = 100`) so a rolling deploy cannot double-fire.
- **It binds no application socket.** Not "listens where nothing reaches it" — nothing at all. Inside the running container `/proc/net/tcp` carries exactly one `LISTEN` entry, docker's embedded DNS resolver at `127.0.0.11`, which every container has. It declares no `port`, no `health_check_path`, and no `surfaces`, and `entrypoints/clock.py` imports neither uvicorn nor fastapi. That is the strongest single piece of evidence that liveness left HTTP, so it is recorded as observed fact rather than as an intention.
- **Contract**: none, and that is the ordinary rule rather than an exemption. **It declares no surface, and that is what makes it not a provider** (`cicl.md § Surfaces`).
- **`uses: [appdb, api.worker]`** — with **no** magic ref to the worker. The clock reaches it through the `jobs` table rather than the mesh, so there is nothing to reference; the edge declares the interface. A ref implies an edge, never the reverse.

#### Why there is only one codebase

Until the clock advance there were two: `api`, and a scheduler-only codebase named `reaper` whose single core service pruned expired pings on a nightly cron. When `role: scheduler` was retired, **`reaper` could not become a clock.** A clock defers onto its own codebase's queue, only the codebase that owns a schema may enqueue, and `reaper` owned no schema (it reached into `api`'s `pings` table), no worker, and no queue. `api` owns all three, so the clock folded in here and `reaper` was deleted; its retention rule became the [`retention`](./api/hex/retention.md) module.

The walk therefore stopped covering the two-codebase shape. That loss is deliberate and is recorded in `docex/plans/core/test_projects.md § Shape`, which is where a reader who finds one codebase should look before concluding the doc is stale.

### Composition Roots and Entrypoints

One `root.py` per **codebase** — not per core service. The root **constructs**: it instantiates `RepoPingsPostgres`, the alogic service, and the driving adapter, and returns them. It **does not activate**: it opens no socket, starts no server, and runs no loop.

Activation lives in `src/entrypoints/`, one module per core service, and each core service's `command` invokes exactly one of them:

| Core service | `command` | Entrypoint owns |
| ------------ | --------- | --------------- |
| `api.web` | `entrypoints/web.py` | uvicorn |
| `api.worker` | `entrypoints/worker.py` | poll loop (pings **and** the job queue), SIGTERM handling, the liveness tick file, and the uvicorn host for the `rpc` surface |
| `api.clock` | `entrypoints/clock.py` | cron loop on a bounded 5 s wait, SIGTERM handling, the liveness tick file — and no server of any kind |

`clock.py` is the doctrine's **reference implementation** of a clock runtime host, and `worker.py` of a loop-owning consumer. Downstream projects copy both, so changes there are made deliberately.

The Dockerfile `CMD` is deliberately irrelevant for core services: `command` is required on every core service and supersedes it.

## Flows

1. **Ping creation.** `POST /pings` on `api.web` → `ContPingsHttp` translates to a driving port call → `PingService.create_ping()` constructs a `Ping`, calls `RepoPings.save()` → row lands in postgres with `processed_at = NULL` → 201 returned.
2. **Ping processing.** `entrypoints/worker.py`'s loop calls `ContProcessorCli.run_once()` once a second → `ProcessorService` claims `pings WHERE processed_at IS NULL` in batches of 32 → for each row the no-op business logic runs → `RepoPings.mark_processed(id)` sets `processed_at = now()` → the loop touches its tick file (flow 3) and sleeps.
3. **Self health.** `GET /health` on `api.web` returns `{"version": "<project version>"}`, straight from the process — and it survives on that core service **alone**, because a load balancer reads it and has no other way to ask (`healthchecks.md § web services also serve GET /health`). The other two core services own loops, and a loop's liveness has to be sourced from the loop: `entrypoints/{worker,clock}.py` touch `/tmp/<svc>.tick` at the end of each successful iteration, and `./health.sh <svc>` — which the orchestrator runs as a **separate process** — stats that file and fails when it is absent or more than 30 s old. An **absent** file fails, deliberately: a loop that never completed an iteration was never alive, and reporting healthy until the first tick would hide a loop that never started. The 30 s threshold lives in `health.sh` because the probe is the only thing that judges it; the ≤10 s cadence lives in the entrypoints (1 s in the worker, 5 s in the clock) because the loop is the only thing that can honour it. **The two numbers are meaningless apart:** 30 is three times 10, so a healthy loop misses two consecutive ticks before it is called stale — slack for jitter and one slow iteration, without giving a wedged loop room to hide.
4. **Deferred-job drain.** `POST /jobs/drain` on `api.web` → `ContJobDrainHttp` → `JobDrainService` → `GwyJobRunnerHttp`, which addresses the worker through the injected `WORKER_HOST` / `WORKER_PORT` → HTTP `POST /drain` against `api.worker`'s `rpc` surface → `ContJobRunnerHttp` → `ContJobRunner.run_once()` → `{"performed": N}` travels back out through the edge to the original caller. This is the **only** flow that crosses a process boundary between two core services, so it is the one that carries the `api.worker` entry in `api.web`'s `uses:`, the five-segment magic refs, and rule 32's positive arm. Its reply is a **count of work performed** — no liveness verdict and no staleness judgement — so it cannot be mistaken for the health fan-out that used to live at `/health/api/worker` and exists nowhere now.
5. **Project-local-backing reachability.** `GET /diagnostics/probe` confirms `api.web` can resolve and reach the `probe` nginx sidecar by service name; `GET /diagnostics/events` confirms it can open a TCP connection to ClickHouse. Both exercise Service Connect / docker network DNS at the smoke-test layer. They sit under `/diagnostics` rather than `/health` because they probe *backing* services, and under `/health/*` a reader would conclude the fan-out survived — against `healthchecks.md`'s "No service reports on another."
6. **Scheduled deferral.** `entrypoints/clock.py`'s loop wakes at most every 5 s, finds a job whose cron expression is due, and calls `ContJobsCron.fire(name)` → the shared driving port `ContJobs` → `JobService` inserts a row into `jobs` → the fire returns. **That is the whole of the clock's involvement.** It performs no work, because a clock is a singleton with no replicas and no queue-level retry, and because only the codebase that owns a schema may write to it. Two jobs are scheduled: `prune_pings` at `0 3 * * *`, and `heartbeat` every minute so this flow is observable inside a smoke walk rather than only at 03:00.
7. **Job draining.** The same `api.worker` pass as flow 2 calls `ContJobRunnerCli.run_once()` → `JobRunnerService` claims a batch `FOR UPDATE SKIP LOCKED` (exclusive against the second replica), looks each row's `name` up in its **perform-side** table, and runs the handler → `prune_pings` calls `retention`'s driving port, computing a cutoff from a 30-day `RetentionWindow` and deleting expired *processed* pings (unprocessed and recently-processed rows survive); `heartbeat` logs and returns. Each row is stamped `finished_at`, with `error` set on failure and the drain continuing past it.
8. **Clock self health.** The clock's half of flow 3's tick mechanism. `entrypoints/clock.py`'s loop touches `/tmp/clock.tick` on each iteration whether or not anything fired — a clock with nothing due is perfectly alive, and that is what makes its bounded 5 s wait sufficient on its own — with one exception: a pass on which *every* due fire raised withholds the tick, for the same reason the worker's failing pass does. `./health.sh clock` stats it. Nothing external reaches the clock at all: it serves nothing, no route proxies it, and the stage tester cannot see it. The probe is therefore the clock's **only** liveness channel — reported by docker here and read from `docker inspect` by `docex stagetest`, acted on directly by ECS on the elastic companion, which kills and replaces the task. Local, but real, and stronger than the served route it replaced: the probe stats the loop's own trace from a separate process, so a wedged loop cannot answer on its own behalf.

## Hard Boundaries

- This project does **not** solve a real problem. The flows are minimal-by-design.
- This project does **not** carry custom transfer tables beyond `sidecar.yml` and `clickhouse.yml`. Those two exist specifically to keep the project-local-transfer-table surface exercised every cut; if a smoke walk surfaces an ambiguity in the doctrine's project-local mechanism, the fix lands in doctrine, not in additional tables here.
- This project does **not** consume a real broker. Both its queues are postgres tables — `pings` for ping work and `jobs` for deferred jobs — because the doctrine ships no `queue` backing-service role. That is the most visible loose end the CICL-v2 advance leaves, and it is recorded in `api.worker.events.asyncapi.yml`'s header rather than hidden.
- **No core service reports on another's health.** This project had a `/health/api/worker` fan-out and deliberately does not any more: `healthchecks.md § What this doctrine does not do` forbids one service reporting on another, and `docex` reads every core service's state from the orchestrator rather than through an in-network proxy. Stated rather than left to be inferred from an absence, for the same reason the one-codebase boundary above is stated at length — a copying project inherits whatever it is not told. `POST /jobs/drain` (flow 4) is not a counter-example: it commands work and returns a count of it, and carries no verdict about whether the worker is well.
- This project has **one codebase**, deliberately. It carried two until the clock advance: `reaper`, a scheduler-only codebase, was deleted when `role: scheduler` was retired. It could not become a clock — a clock defers onto its own codebase's queue, only the schema-owning codebase may enqueue, and `reaper` owned no schema, no worker, and no queue. **This is not drift and it must not be "restored".** What the second codebase used to cover, and what its loss costs the smoke walk, is recorded in `docex/plans/core/test_projects.md § Shape`.
- This project does **not** ship with custom observability, alerting, or anything in the Deferred section of `doctrine/infrastructure/infrastructure.md`. If the smoke test surfaces a need for one of those, that's a Deferred item being un-deferred.

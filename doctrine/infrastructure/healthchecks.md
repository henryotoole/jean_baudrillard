---
stratum: conditional
---

# Health Checks

Any system that autoscales, deploys without supervision, or is judged by machine must be able to answer *"is this thing working?"* without a human looking at it. That answer has to take one form across every project, or the machinery that consumes it has to know something about each project — which is exactly what the `doctrine` exists to prevent.

This file fixes that form. **Every core service supplies a probe; the orchestrator runs it; `docex` reads the orchestrator.** Nothing in the pipeline asks a service about itself over the network, and no service is ever responsible for reporting on another.

## What a health check is for

Three different consumers ask three different questions, and conflating them is what produces baroque health systems.

| Consumer | Question | Answered by |
| -------- | -------- | ----------- |
| The orchestrator (Docker, ECS) | Should this container be restarted, and should it receive traffic? | The **probe** — a command, run inside the container. |
| `docex` | Did the release land, is every service healthy, and at what version? | The **orchestrator's** aggregated state. |
| The reverse proxy | Is this target fit to route to? | `GET /health` over the network — but **only** on `elastic` with `reverse_proxy: alb`. Nowhere else: see below. |

Only the third is HTTP, only on `web`-network core services, and only because an ALB has no other way to ask. Everything else is a command, because a command is the one probe form both orchestrators accept natively.

**Nothing else routes on health, and this is worth stating because it is easy to assume otherwise.** On `fixed` the compiler emits no health-aware traefik labels, so the project traefik probes nothing and the container probe has exactly two consumers — Docker, which restarts nothing of its own accord, and `docex`. On `elastic` with `reverse_proxy: ec2_traefik_eip` or `_pip`, traefik's ECS provider filters targets on `lastStatus == RUNNING`, a **lifecycle** state: a container failing its probe stays `RUNNING` and keeps receiving traffic until the ECS scheduler replaces it. So on two of the three reverse-proxy configurations, a wedged `web` service is removed from service by the orchestrator replacing it, not by the proxy withholding traffic. See [cicl.md rule 33](./cicl.md#validation-rules).

## The probe

Every codebase ships a `health.sh` at its container root — `/service/health.sh`, per [Codebase Containers](./infrastructure.md#codebase-containers). It joins `build.sh`, `test.sh`, and `migrate.sh` as a shim whose entire contract is its exit code:

- **`0`** — this core service is working.
- **non-zero** — it is not.

Nothing else about it is fixed. It may curl a local route, stat a file, query a socket, or run a language-native check; the `doctrine` fixes the interface, not the tool, exactly as it does for [migrations](../practices/databases.md#migrations).

**`health.sh` is invoked per core service**, as `./health.sh <service>`, and this is the one asymmetry against the other three shims. `build.sh`, `test.sh`, and `migrate.sh` are properties of the *source tree* and so are codebase-scoped. Health is a property of a *running process*, and one codebase's web edge and queue consumer are different processes with different failure modes. One file still, because four files to hold four branches of a `case` statement is worse; the compiler supplies the argv so the script never has to guess where it is running.

The [check step](./cicd.md#check-step) asserts the file exists. Nothing can statically assert that it is *correct* — which is why what follows matters.

### What the probe must actually check

The probe must fail when the service has stopped doing its job. That sounds obvious and is the requirement projects most often get wrong, because the easy implementations all report on the wrong thing.

**A service driven by a request cycle** — a `web` edge, an RPC surface — is nearly self-checking: if its server accepts a connection and routes a trivial request, it is serving. A probe that curls its own `/health` is legitimate here.

**A service that owns a loop** — a queue consumer, a stream processor, a poller — is not. Its process can be perfectly alive while its loop is wedged, and the naive probes cannot tell:

- Checking that the process exists proves nothing; a deadlocked process exists.
- Checking a separate liveness thread proves less than nothing. It will cheerfully report health forever while no work is being consumed, converting a loud failure into a silent one.

For these, **liveness must be sourced from the loop itself**:

- The loop records a **monotonic tick** each iteration, somewhere the probe can observe from a separate process — a touched file is the obvious mechanism.
- `health.sh` fails when that tick is stale.
- **The loop ticks at least every 10 seconds even when idle** — its receive must be bounded, not indefinite — and **the staleness threshold is 30 seconds**.

Both thresholds are doctrine-fixed; there is no per-project knob. Thirty is three times ten, so a healthy loop misses two consecutive ticks before it is called stale — enough slack to absorb scheduling jitter and one slow iteration without flapping, while still failing a wedged loop inside the window the orchestrator acts on. A long unit of work does not threaten this: **the tick belongs to the receive loop, not to the work.**

A `clock` core service owns a loop in this sense — it wakes, checks its schedule, and sleeps — so it ticks like any other.

## The orchestrator carries the result

The compiler emits `health.sh <service>` as the container-level health check on both foundations: a `healthcheck:` block on `fixed`, a container `healthCheck` in the task definition on `elastic`. Both accept a command natively, which is why this is a translation and not an adaptation.

Probe cadence — interval, timeout, retry count — is doctrine-fixed and uniform across every core service, and lives in the [transfer tables](./specifics/transfer_tables.md) rather than here. It is not a project-tunable field. A project that believes it needs a different cadence has a probe problem, not a cadence problem.

Detection is therefore not instantaneous: a wedged loop goes stale, then the next scheduled probe fails, then the retry count is exhausted. That lag is deliberate and bounded, and it is the price of not flapping.

The [**exec service**](./specifics/exec_service.md) has no health check. It is a one-off container that runs a script and exits; its liveness question is answered by the exit code it was invoked for.

## `web` services also serve `GET /health`

**Every `web`-network core service serves `GET /health` on its declared `port`**, returning its version as `{version: "x.x.x"}`. This is the *only* place HTTP appears in the health model, and it exists for one reason: on `elastic` the ALB probes its targets over the network and cannot run a command inside a container.

The path is declared by the core service's `health_check_path` field, which compiles to the ALB target group's health check. **That field is the declaration** — it is what the load balancer reads, and the [check step](./cicd.md#check-step) asserts it. A core service that is not on the `web` network has no load balancer in front of it, declares no `health_check_path`, and needs no HTTP surface of any kind — a queue consumer built under this doctrine listens on nothing.

Where a `web`-network core service *also* declares an `openapi` [surface](./cicl.md#surfaces), `GET /health` is part of that surface and belongs in its contract, which the check step asserts as well. This does not hold universally, and there are **two** ways out of it rather than one. A core service can be on the `web` network and declare no surface at all — a frontend serving a browser is the usual case. It can also declare surfaces of which none is `openapi`: [cicl.md](./cicl.md#surfaces)'s own worked `api.mcp` is exactly that, on `web` with a single `rpc` surface resolving to **asyncapi**, so it serves `GET /health` with no `openapi` document for the path to appear in. In both cases there is no contract obligation. The field covers both; the contract covers only the described boundary. See [contracts.md](./contracts.md).

## Version

Version is reported in more than one place, and the places are not interchangeable.

| Source | Carries | Read by |
| ------ | ------- | ------- |
| The probe's **exit code** | Liveness only. | The orchestrator. |
| The **orchestrator** | Version, authoritatively — the image ref on `fixed`, the task-definition revision on `elastic`. | `docex`, during [staging tests](./cicd.md#staging-tests). |
| `GET /health`'s body | The version the running code *believes* it is. | The project's own stage tests, via `PROJECT_VERSION`. |

**The orchestrator wins when they disagree.** Its answer comes from the deployment record rather than from the deployed code, so a container running last week's image cannot misreport it — whereas a self-reported version is only as honest as the build that produced it.

A probe's *output* is deliberately not a channel here. Docker captures healthcheck stdout; ECS surfaces only a status. Anything read from probe output would work on one foundation and silently not on the other.

## What this doctrine does not do

Worth stating plainly, because these are the shapes a health system tends to grow and this one deliberately has none of them.

- **No service reports on another.** There is no proxying, no `/health/<codebase>/<service>`, no fan-out. A consumer's health says nothing about its dependencies, and it is not asked to. `docex` reads every core service's state from the orchestrator directly, so nothing needs an in-network proxy to reach an internal service.
- **No health check crosses the public internet.** Liveness is read from the orchestrator's API, not fetched through the reverse proxy. [Staging tests](./cicd.md#staging-tests) assert ingress and behavior from outside; they do not assert liveness, and they cannot reach a non-`web` core service at all.
- **No HTTP requirement for non-`web` services.** A core service needs a `port` only when something addresses it directly. Health is not such a thing.
- **No per-project thresholds.** The 10s tick and 30s staleness window are fixed, as is probe cadence.

## Backing services

Backing service health is an **engine** concern, not a project one. Where an engine has a meaningful readiness check, its [transfer table](./specifics/transfer_tables.md) supplies it; where it does not, none is emitted. No project writes a `health.sh` for a database.

The one place this is load-bearing is the [exec service](./specifics/exec_service.md), whose readiness gate waits on `service_healthy` for the backing services its codebase `uses` — falling back to `service_started` for an engine that declares no check. A one-off migration must wait for a database that is genuinely accepting connections, which is why that gate exists at all.

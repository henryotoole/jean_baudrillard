---
stratum: conditional
---

# Contracts

This file describes contracts and what the `doctrine` requires of them.

Contracts define the boundaries of [core services](./cicl.md#core-services). A core service can be a provider, a consumer, or both, depending on the usage relationships declared by `infra.yml`'s [consumes](./cicl.md#consumes-relationships) field. Every core service that is a provider will have a contract at:

`$pr/infra/contracts/${codebase_name}.${core_service_name}.${contract_format}.yml`

```
infra/contracts/
├── api.web.openapi.yml
└── api.worker.asyncapi.yml
```

The path is keyed on the core service unconditionally, and the format alone could not stand in for it: one codebase may run two HTTP core services — the `api` codebase's public `web` and an internal `admin`, on different networks with different resources — and both are genuine boundaries deserving their own contract, at `api.web.openapi.yml` and `api.admin.openapi.yml`.

**The provider set is (`consumes` targets) ∪ (`web`-network core services).** Both arms are load-bearing. The first is the declared interface graph. The second catches every publicly-reachable boundary even when nothing inside the project consumes it, which is what gives the [health-check](#health-checks) gate something to validate.

## Standards

Contracts take standard formats defined by the `doctrine` on the basis of consumer-provider communication mechanism. The full table is below:

The doctrine currently provides the following standard contract formats:
| Contract Format | Filepath Name | Communication Mechanisms |
| --------------- | ------------- | ------------------------ |
| OpenAPI | openapi | HTTP request-based communication. |
| AsyncAPI | asyncapi | Queue-based communication. |

The format follows from the **provider's `role`**, not from the shape of the graph: `role: web` → OpenAPI, `role: worker` → AsyncAPI. The role is what fixes the communication mechanism, so it is the honest source.

Note that while the contract format is dependent upon communication mechanism, it still describes the *core service*. An asyncapi.yml contract describes `api.worker`, *not* the queue backing service that actually feeds it info. The provider is whoever owns the message schema and the operation's semantics.

## Mandatory Endpoints

In order for the `doctrine`'s infrastructure system to work, certain core services have mandatory endpoints which must exist in their contracts. If they don't exist, the project` won't pass [CI checks](./cicd.md#check-step).

### Health Checks

In order to pass staging tests, hosted core services must provide health checks reachable from the open web. Not every core service is publicly reachable, so those that are must expose the health of those that aren't.

#### Self health

**Every long-running core service serves `GET /health`** on its declared `port`, on its internal network, returning the service version as `{version: "x.x.x"}`.

For a core service that owns a loop rather than a request cycle — a queue consumer, a stream processor, a polling worker — that endpoint must report the *loop's* liveness, not merely the process's:

- The loop bumps an in-process **monotonic tick** each iteration.
- The `/health` handler returns **503** when that tick is stale.
- **The loop ticks at least every 10 seconds even when idle** — i.e. its receive is bounded, not indefinite — and **the handler's staleness threshold is 30 seconds**.

Both thresholds are doctrine-fixed; there is no per-project knob. Thirty is three times ten, so a healthy loop misses two consecutive ticks before it is called stale — enough slack to absorb scheduling jitter and one slow iteration without flapping, while still failing a wedged loop inside the window the container healthcheck acts on. A long unit of work does not threaten this: the tick belongs to the receive loop, not to the work.

The point of sourcing liveness from the loop is that a separate liveness thread will cheerfully report health while nothing is being processed. A wedged consumer must fail its own probe.

`scheduler` core services are **exempt**. There is no long-running container to probe, and a scheduler is never a `consumes` target — cron invokes it and nobody else does. "Did last night's job run" is a telemetry question, not a health-check one.

#### Fan-out

Each `web`-network core service must additionally expose the health of everything it talks to that is not itself publicly reachable, at:

`/health/<codebase>/<service>` — returns `{version: "x.x.x"}` for that core service.

The fan-out set is **`consumes`**, restricted to targets not themselves on the `web` network. A target on `web` is publicly reachable and answers its own `/health` at its own hostname, so there is nothing for a consumer to proxy — that is what "expose the health of those that aren't" means above.

`consumes` is the source rather than [`depends_on`](./cicl.md#depends-on-relationships) because a web edge does not `depends_on` its worker: it needs the *broker* up, not the consumer. Keying off `depends_on` would silently stop requiring `/health/api/worker`, and a dead consumer is invisible from outside because requests keep returning 200 while work piles up behind them. (This rule was once written as the *union* of the two, from a time when `depends_on` could still name a core service. [Rule 24](./cicl.md#validation-rules) has since restricted `depends_on` to backing services, which have no `<codebase>/<service>` form at all, so the union's second arm can no longer contribute a target. It is stated as `consumes` alone so nobody restores an arm that cannot fire.)

**One hop only.** `/health/<codebase>/<service>` proxies the target's *self* `/health` with a short hard timeout. It never calls the target's own fan-out endpoints. Without this rule the legal `web ↔ worker` cycle in [`consumes`](./cicl.md#consumes-relationships) recurses.

#### Declared by fields, not by the contract

A `consumes` target must declare both `port` and `health_check_path`. Those two fields **are** the health declaration, and the [check step](./cicd.md#check-step) asserts them — along with `curl` being present in the image, which it already keys off `health_check_path`.

The declaration lives in the fields rather than in the provider's own contract because a `worker`'s contract is AsyncAPI, which describes channels and messages and has no natural place for an HTTP path; forcing `/health` into it would be a contortion. So the responsibilities split cleanly:

- The provider's `port` + `health_check_path` fields declare that it is probeable.
- The provider's AsyncAPI contract describes only its message boundary.
- The **consumer's** OpenAPI contract declares `/health/<codebase>/<service>`, which is where the existing contract-enforced health machinery already lives.

On elastic there is a second reason the `port` is required: it is exactly what makes a core service Service-Connect-discoverable, which is what lets a sibling `web` core service reach its `/health` one hop away.

Discoverability alone is not sufficient there, though. A Service Connect client resolves only the endpoints that existed when its task started, so a consumer deployed alongside a brand-new target can fail this fan-out permanently even though both sides are healthy. `docex` closes that at release time — see [`release.md § Service Connect Consumer Reconcile`](./specifics/release.md#service-connect-consumer-reconcile) and [`cicl.md § Resilience covers reachability, not resolvability`](./cicl.md#resilience-covers-reachability-not-resolvability). A `503` here on a freshly provisioned env, with the target reporting healthy, is that failure and not a wedged loop.

By enforcing the fan-out endpoints in the contract, we allow the developer to implement them however they see fit but ensure that health checks will be available to CI/CD operations.
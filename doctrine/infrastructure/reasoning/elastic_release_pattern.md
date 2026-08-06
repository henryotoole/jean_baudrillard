---
stratum: conditional
---

# Elastic Release Pattern

Releasing on `elastic` is substantially more complex than on `fixed`. This is an unfortunate side-effect of name resolution in ECS. ECS has three mechanisms for name resolution:
1. Load Balancer (conventional)
2. Service Discovery
3. Service Connect

The load balancer option is by far the most desirable. It mirrors how name resolution works on the `fixed` side. However, this choice would require a second load balancer for all `elastic` projects to support non-`web` networked (internal) core services. An ALB can either be public-facing or not; it cannot be both at once.

Service Discovery is a legacy version of Service Connect and has some notorious pitfalls. It also can not be used.

This leaves Service Connect. This produces the unfortunate asymmetry between `fixed` and `elastic` because Service Connect is a decentralized, client-side load balancing and resolving system. It is not a worse system, just different.

The trick is that the decentralized system must still centralize service name resolution. Service Connect achieves this with a Cloud Map registry of the discovery names registered in the namespace. Unfortunately, that registry is resolved *exactly once, statically*, when an ECS **deployment** is created; every task in the deployment is served the same fixed copy. A name registered after the deployment does not exist for any of its tasks — it is **unresolvable** rather than merely unreachable, so no amount of application-level backoff ever converges on it, and replacing a task does not help unless the replacement lands in a new deployment.

See [ecs_service_connect.md](../../charts/ecs_service_connect.md) for a full diagram of the name resolution mechanism.

## Why Ordering Cannot Fix This

The obvious response is to create things in dependency order, so no consumer ever starts before a name it needs. That is not available, for two independent reasons.

The first is timing: `tofu apply` creates every env-tier ECS service concurrently, so a consumer and the target it `uses` race, and whichever starts first may never see the other.

The second is fatal to the idea itself. The [`uses`](../cicl.md#uses-relationships) graph may legally [contain cycles](../cicl.md#the-graph-may-contain-cycles) — `api.web` enqueues a job and `api.worker` posts the result back to `api.web`, which is the most common web/worker topology in existence. In a cycle some member must be created first, so there is no creation order to find. Ordering cannot solve a problem whose input admits no valid order.

## The Shape of the Fix: Observe, Don't Enforce

Because the ordering cannot be enforced, the doctrine repairs the outcome instead. After the final apply, `release` asks one question of current AWS state — *is any running consumer task older than the registration of a name it needs?* — and redeploys exactly those consumers for which the answer is yes.

What makes this sound rather than a patch is that both operands are **durable**. An endpoint registration is owned by the ECS service rather than by task liveness, so it survives every task replacement; task start times are AWS-server-issued facts. Nothing is carried across the apply and nothing is remembered between releases, so the step describes the world rather than the run that produced it. Any broken env it can read, it can also repair — including one left behind by an interrupted release, a hand-run `tofu apply`, or a rollback. A trigger keyed on *this release's own actions* would have none of that property: on the re-run of an aborted release every name already exists, and the broken env is set-identical to the healthy one.

The full mechanism — the three properties it exhibits and the implementation details it turns on — is in [release.md § Service Connect Consumer Reconcile](../specifics/release.md#service-connect-consumer-reconcile). The reachability-versus-resolvability distinction that motivates it is in [cicl.md § Resilience covers reachability, not resolvability](../cicl.md#resilience-covers-reachability-not-resolvability).

## Why We Need Name Resolution

Currently, requiring all core services to be reachable via HTTP is an offshoot of requiring HTTP-based healthchecks (see [healthchecks.md](./healthchecks.md)). However, making this universal practice has the additional advantage of allowing any internal-networked core service to be HTTP-reachable. This is a handy advantage for future projects.

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

The trick is that the decentralized system must still centralize service name resolution. Service Connect achieves this with a Cloud Map registry of all ECS Service names (e.g. core service names) that have been registered with it. Unfortunately, this map is written *exactly once, statically* to a service task when it launches. So in order to ensure all tasks have the correct name map, they must all be started *after* the registry has been completely formed. Completely forming the registry requires all ECS services to have launched. So, in practice, for name resolution to work, all ECS services must be launched *twice*; once to fill out the Cloud Map registry, and then once again to ensure all ECS tasks actually have that registry.

See [ecs_service_connect.md](../../charts/ecs_service_connect.md) for a full diagram of the name resolution mechanism.

This requirement means that any release which adds a new named piece of infrastructure must perform a double-rollout. Fortunately most releases are code-only, so the double-rollout must only be performed when infrastructure shape is changing. This shape-changing detection is part of the release process.

## Why We Need Name Resolution

Currently, requiring all core services to be reachable via HTTP is an offshoot of requiring HTTP-based healthchecks (see [healtchecks.md](./healthchecks.md)). However, making this universal practice has the additional advantage of allowing any internal-networked core service to be HTTP-reachable. This is a handy advantage for future projects.
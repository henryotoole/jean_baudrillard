---
name: contracts
description: Doctrine for defining core-service contracts and boundaries — OpenAPI/AsyncAPI provider contracts and the mandatory health-check endpoints. Use this whenever you are defining or changing a service's contract, adding a provider/consumer relationship, or wiring health checks, even if the word "contract" is never used.
metadata:
  type: thread
---

# contracts

Contracts define the boundary of a provider core service *process type*; a single file covers the formats, the mandatory endpoints, and how CI uses them.

## General Information

What contracts are and what they must contain. **Read this now.**

[`contracts.md`](../../doctrine/infrastructure/contracts.md) — contract formats (OpenAPI for HTTP, AsyncAPI for queues), where they live, the mandatory `/health` and downstream `/health/<svc>/<proc>` endpoints, the loop-liveness tick a long-running process type owes, and how CI checks them.

## Thread

- Provider/consumer relationships are declared via `consumes` in `infra.yml` — author that in `infra-compile`. `depends_on` is a separate relation (backing-service readiness) and does not define a contract edge.
- Provider-side contract tests run in the test suite (`testing`); the check step enforces contract-to-`consumes` alignment (`cicd-pipeline`).
- A contract expresses a module's *boundary*; the internal architecture behind it is the Resident hexagonal doctrine, already in context.

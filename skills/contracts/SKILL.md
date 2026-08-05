---
name: contracts
description: Doctrine for defining core-service contracts and boundaries — OpenAPI/AsyncAPI provider contracts and the mandatory health-check endpoints. Use this whenever you are defining or changing a service's contract, adding a provider/consumer relationship, or wiring health checks, even if the word "contract" is never used.
metadata:
  type: thread
---

# contracts

Contracts define the boundary of a provider **core service**; a single file covers the formats, the mandatory endpoints, and how CI uses them.

## General Information

What contracts are and what they must contain. **Read this now.**

[`contracts.md`](../../doctrine/infrastructure/contracts.md) — contract formats (OpenAPI for HTTP, AsyncAPI for queues), where they live, the mandatory `/health` and downstream `/health/<codebase>/<service>` endpoints, the loop-liveness tick a long-running core service owes, and how CI checks them.

## Thread

- Provider/consumer relationships are declared via `uses` in `infra.yml` — author that in `infra-compile`. Only the **core-service** targets of a `uses` list define contract edges; a backing-service target does not.
- Provider-side contract tests run in the test suite (`testing`); the check step enforces contract-to-`uses` alignment (`cicd-pipeline`).
- A contract expresses a module's *boundary*; the internal architecture behind it is the Resident hexagonal doctrine, already in context.

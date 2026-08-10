---
name: contracts
description: Doctrine for defining core-service surfaces and their contracts — which API styles share a surface, the OpenAPI/AsyncAPI format each resolves to, and the health probe every core service owes. Use this whenever you are declaring or changing a service's surfaces, writing a contract, adding a provider/consumer relationship, or wiring health checks, even if the words "contract" or "surface" are never used.
metadata:
  type: thread
---

# contracts

A core service exposes zero or more **surfaces**; each surface is one described boundary and gets exactly one contract file. Declaring a surface is what makes a core service a provider.

## General Information

Read both. **Now.**

[`contracts.md`](../../doctrine/infrastructure/contracts.md) — what a contract is, the four formats and their file extensions, and the `${codebase}.${service}.${surface}.${format}.${ext}` path.

[`healthchecks.md`](../../doctrine/infrastructure/healthchecks.md) — the `health.sh` probe every core service ships, what it must actually check (the loop-liveness tick), and why only `web`-network services also serve `GET /health`.

## Specific Information

**Read on demand.**

[`cicl.md § Surfaces`](../../doctrine/infrastructure/cicl.md#surfaces) — the `api_styles` → format table, the one-format-per-surface rule, and the table deciding when two boundaries are two surfaces versus two core services. Read this when choosing how to split a service that exposes more than one kind of API.

## Thread

- Surfaces are declared in `infra.yml` under a core service — author that in `infra-compile`. A `uses` edge may only target a core service that declares at least one surface.
- Health splits across two mechanisms deliberately: the **probe** (`health.sh`, every core service, command-form) proves liveness to the orchestrator; **`GET /health`** exists only where a load balancer reads it. Only the latter appears in a contract, and only when the service also declares an `openapi` surface.
- Provider-side contract tests run in the test suite (`testing`); the check step enforces surface-to-contract alignment (`cicd-pipeline`).
- A contract expresses a module's *boundary*; the internal architecture behind it is the Resident hexagonal doctrine, already in context.

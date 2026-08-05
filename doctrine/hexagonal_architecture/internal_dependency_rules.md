---
stratum: resident
---

# Dependency Rules

This document describes the hard and fast rules that govern the nature of internal imports within a hexagonal module.

## Dependency Inversion

Dependency inversion should be followed for hexagonal modules in accordance with hexagonal architecture best practices.

## Cross-Module Imports

Code inside a hexagonal module may *never* import files and classes in another hexagonal module, except in the following cases:
1. Driving Ports

## Composition Root

Every project must have a single **composition root** — the one place in the entire codebase where all concrete adapters are instantiated and the full dependency graph is assembled. This will always be called `root.py`. No other file may call a concrete adapter constructor (e.g. `RepoCalendarPostgres()`) to create a new instance.

The composition root is responsible for:
1. Instantiating every concrete driven adapter.
2. Instantiating every alogic service, injecting the adapters created in step 1.
3. Instantiating every driving adapter (controller) for **every** mechanism, injecting the services created in step 2 — including controllers the currently-running core service will never use. Controller construction is free: it captures a port reference and performs no I/O.

This means the dependency graph is fully visible and fully traceable from one file, making it easy to understand what concrete implementation is used at every layer.

The composition root **constructs**; it does not **activate**. It builds no server, opens no socket, and consumes no queue. Binding the constructed adapters to something that actually runs is the entrypoint's job.

## Entrypoints

A codebase's build artifact can be invoked in more than one way — an HTTP edge, a queue consumer, a scheduled job. Each such invocation is a [core service](../infrastructure/cicl.md#core-services), and each core service's `command` invokes exactly one **entrypoint**: a module under `src/entrypoints/` whose only job is to take the graph the composition root built and hand the relevant driving adapters to a runtime host.

**One composition root; one entrypoint per core service.** The rules:

1. An entrypoint calls the composition root's build function and **never** a concrete adapter constructor. The no-self-instantiation rule below is unaffected.
2. **The runtime host is not an adapter.** Nobody ever thought uvicorn was an adapter; a broker's consume loop is not one either. Both belong to the entrypoint. The adapter's job is *translation* — and on the queue side, the return half of that translation is the ack / nack / retry decision.
3. **Never split the root** into `root_web.py` / `root_worker.py`. Two copies of the driven wiring drift, which is precisely the bug class module integration tests exist to catch (see "composition-root mistakes" in [hex_overview.md § Tests](./hex_overview.md#tests)).
4. Where a client library **inverts control** — Celery-style decorators that register handlers at import time — register in the entrypoint, calling into the adapter's handler. A decorator inside the adapter leaks the framework into the module and destroys mocked-port testability.
5. A driven adapter that is genuinely expensive and needed by only one core service should be **lazy internally**, rather than forking the root. If that feels like a band-aid, the honest question is whether this is really a second app.
6. A long-running entrypoint that owns a loop **must expose that loop's liveness**. See [contracts.md § Health Checks](../infrastructure/contracts.md#health-checks) for the required mechanism and thresholds.

## No Self-Instantiation

Controllers and alogic services **must never construct their own dependencies**. They must accept all dependencies as constructor arguments. A controller or service that calls `SomeAdapter()` in its own `__init__` is a violation of this rule, because it hides a wiring decision inside a module rather than leaving it to the composition root.

This rule is what makes the composition root pattern enforceable. If any class self-instantiates a dependency, the composition root loses its ability to control what concrete implementations are used.
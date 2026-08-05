# `processor` — module

## Purpose

Claims unprocessed rows from the `pings` table and marks each one processed. Driven by the `api.worker` core service. Demonstrates a second module inside the same codebase reaching the same table through its own adapter.

## Domain

- **`Ping`** (entity). Same shape as `pings`'s `Ping`, and a **separate file**. The cross-module import rule does not relax because the two modules now share a codebase: a module boundary is a boundary regardless of which build artifact it compiles into. They are intentionally parallel data classes — if they diverge, the smoke test surfaces a contract drift (real projects would put the shared shape in a separate domain layer or accept duplication).
- **No domain services.** All work fits on the entity (`mark_processed`) and a single alogic method that ties it to the repo.

## Driving Ports

- **`ContProcessor`** — single `run_once() -> int` method: process all currently-unprocessed pings and return the count. **Not** `run_forever()`. The loop is not the port's business; see below.

## Driven Ports

- **`RepoPings`** — `claim_unprocessed(limit: int) -> list[Ping]`, `mark_processed(id: UUID, at: datetime) -> None`. Subset of `pings`'s `RepoPings` (no `save`).

## Adapters Included

- **Driving**: `ContProcessorCli` — translation only. One invocation in, a processed count out. It owns no loop, no signal handlers, and no sleep, because **the runtime host is not an adapter** (`internal_dependency_rules.md § Entrypoints`, rule 2). It also deliberately does *not* catch exceptions: swallowing one would report "0 processed" for a failed iteration, and the entrypoint's loop must tell those apart to decide whether to bump the liveness tick.
- **Driven**: `RepoPingsPostgres` — psycopg-based postgres repo.

## Hard Boundaries

- `processor` does not write new pings. Only `pings` does.
- `processor` does not own the loop. The poll loop, the SIGTERM handling, and the liveness tick all live in `src/entrypoints/worker.py`. This module is invoked once per iteration and knows nothing about iteration.
- `processor` does no real work. The "process" step is a no-op stub. If a future smoke test needs actual processing behavior, the doctrine should grow either an enrichment role or an explicit work-handler abstraction — not be ad-hoc'd here.
- `processor` does not coordinate with sibling replicas. With `replicas: 2` in `prod`, two workers poll the same table; the smoke test tolerates the overlap because the "work" is a no-op. Real multi-worker coordination (advisory locks, `FOR UPDATE SKIP LOCKED`) is out of scope for this seed — and note that `replicas` is honoured in `prod` only, so this is the one shape `dev`, `test`, and `stage` cannot rehearse.

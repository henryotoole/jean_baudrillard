# `processor` — module

## Purpose

Polls the `pings` table for unprocessed rows and marks each one processed. Demonstrates a service that reads-then-writes against a schema owned by *another* core service.

## Domain

- **`Ping`** (entity). Same shape as `web`'s `Ping`. Per doctrine cross-module-import rules, this is a separate file in `worker`'s tree, not an import from `web`. They are intentionally parallel data classes — if they diverge, the smoke test surfaces a contract drift (real projects would put the shared shape in a separate domain layer or accept duplication).
- **No domain services.** All work fits on the entity (`mark_processed`) and a single alogic method that ties it to the repo.

## Driving Ports

- **`ContProcessor`** — single `run_forever() -> None` method. Loops: poll, process, sleep, repeat. Exits on SIGTERM.

## Driven Ports

- **`RepoPings`** — `claim_unprocessed(limit: int) -> list[Ping]`, `mark_processed(id: UUID, at: datetime) -> None`. Subset of `web`'s `RepoPings` (no `save`).

## Adapters Included

- **Driving**: `ContProcessorCli` — the long-running loop. Started as the container's main process via the Dockerfile's `CMD`.
- **Driven**: `RepoPingsPostgres` — psycopg-based postgres repo.

## Hard Boundaries

- `processor` does not write new pings. Only `web` does.
- `processor` does no real work. The "process" step is a no-op stub. If a future smoke test needs actual processing behavior, the doctrine should grow either an enrichment role or an explicit work-handler abstraction — not be ad-hoc'd here.
- `processor` does not coordinate with other worker instances. The smoke test runs one worker; multi-worker coordination (advisory locks, `FOR UPDATE SKIP LOCKED`) is out of scope for this seed.

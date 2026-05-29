# `pings` — module

## Purpose

Captures requests as `Ping` rows in postgres for the `worker` service to process. Implements the `POST /pings` write surface and exposes the persistence shape that `worker` reads against.

## Domain

- **`Ping`** (entity). Fields: `id` (UUID), `payload` (str), `created_at` (datetime), `processed_at` (datetime | None).
  - Invariants: `payload` is non-empty; `processed_at` is None at creation and may only be set forward in time once.
  - State transitions: `Ping.mark_processed(at: datetime)` flips `processed_at`. Refuses to re-process an already-processed ping.
- **No domain services.** All meaningful behavior fits on the entity.

## Driving Ports

- **`ContPings`** — single `create(payload: str) -> Ping` method. Called by the HTTP controller.

## Driven Ports

- **`RepoPings`** — `save(ping: Ping) -> None`, `claim_unprocessed(limit: int) -> list[Ping]`, `mark_processed(id: UUID, at: datetime) -> None`.

## Adapters Included

- **Driving**: `ContPingsHttp` — FastAPI router exposing `POST /pings`. Returns 201 with the new ping's UUID on success.
- **Driven**: `RepoPingsPostgres` — psycopg-based postgres repo.

## Hard Boundaries

- `pings` does not own the `processed_at = now()` write — that's `worker`'s job, executed via its own composition root with its own `RepoPings` instance. Two services pointing at the same table is intentional; both reach it via their own adapters.
- `pings` does not implement queue semantics. There is no broker, no acknowledgment, no retry policy. The table *is* the queue, in the simplest possible way.

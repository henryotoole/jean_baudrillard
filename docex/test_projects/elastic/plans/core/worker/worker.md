# worker — service architecture

## Purpose

The background processor for `docex_smoke_elastic`. Polls the `pings` table for unprocessed rows, "processes" each one (a no-op stub), and marks it processed. Internal-only; no HTTP surface.

## Hex modules

One: [`processor`](./hex/processor.md). It owns the polling loop and the `Ping`-processing logic.

Future modules — none planned. Same as `web`: the smoke test exists to exercise doctrine surface, not to grow an application.

## Composition root

`src/root.py` instantiates:
1. `RepoPingsPostgres` (driven adapter)
2. `ProcessorService` (alogic, given the repo)
3. `ContProcessorCli` (driving adapter, given the service)
4. Calls `ContProcessorCli.run_forever()` which blocks for the container lifetime.

## Database

Reads and writes to the same `pings` table whose schema is owned by `web`. `worker` is a consumer of that schema; if the schema changes, `web`'s migration leads and `worker`'s code follows.

## Hard boundaries

- No HTTP surface. No port published. No reverse-proxy/ALB exposure (declared on `internal` only).
- No schema ownership. `worker` does not write migrations.
- No real queue. The `pings` table is the work queue; if real-queue semantics become necessary, that is a doctrine-level decision (add a `queue` role) not a worker-internal one.

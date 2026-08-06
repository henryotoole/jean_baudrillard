# `retention` — hex module

## Purpose

Deletes processed pings that have outlived the retention window.

This module is the retired **`reaper` codebase**, transplanted into `api` and
renamed for what it does rather than for the deployment that used to run it.
Nothing about the rule changed; only its home did. The move was forced by the
clock rule that a clock may only enqueue onto its own codebase's queue: `reaper`
owned no schema, no worker, and no queue, so it could not become a clock, and
its work had to live in the codebase that owns the `pings` table.

## Domain

**`RetentionWindow`** — a frozen value object holding a positive whole number of
days, with one operation, `cutoff(now)`.

The positive-days invariant is enforced at construction rather than by callers.
A zero or negative window would compute a cutoff at or after `now` and reap
*everything*, including rows processed a second ago — so the type refuses to
exist in that state.

## Driving Ports

| Port | Operations | Driven by |
| ---- | ---------- | --------- |
| `ContRetention` | `prune() -> int` — rows deleted | `jobs`' `JobRunnerService`, as the handler for the `prune_pings` job |

There is **no driving adapter** in this module. Nothing outside the codebase
drives it: its only caller is the job runner, which imports this driving port
directly. That is the one cross-module import the doctrine permits
(`internal_dependency_rules.md § Cross-Module Imports`), and the composition
root injects `RetentionService` behind it.

## Driven Ports

| Port | Pattern | Operations |
| ---- | ------- | ---------- |
| `RepoPings` | `Repository` | `delete_processed_before(cutoff) -> int` |

## Adapters Included

| Adapter | Kind | Notes |
| ------- | ---- | ----- |
| `RepoPingsPostgres` | driven | One statement: delete processed pings older than the cutoff |

This is a **parallel implementation** to `pings`' and `processor`' repos, not a
shared one. All three reach the same table; none shares code with the others.
Hex modules do not import each other, and sharing a codebase does not make them
one module.

## Alogic

`RetentionService.prune()` computes the cutoff from an injected clock and hands
it to the repo. The clock is a constructor argument rather than a call to
`datetime.now()` so the operation stays deterministic under test.

## Wiring

The retention window is **30 days**, set in `src/root.py` as `_RETENTION_DAYS`.
It lives in the composition root because it is a wiring decision, not a doctrine
part and not a configurable value — it is not read from `env:`, `secrets:`, or
`config:`.

## Hard Boundaries

- **This module is never fired directly by the clock.** `api.clock` enqueues the
  `prune_pings` job; `api.worker` performs it. The clock defers and does not
  work, so the path from cron to this module always runs through the queue.
- **Only *processed* pings are eligible.** An unprocessed row is never reaped
  regardless of age; losing work that was never done is a different bug from
  reclaiming space.
- **No soft delete, no archive.** The row is gone. This is a smoke project, and
  the doctrine surface being exercised is scheduled deferral, not data
  lifecycle.

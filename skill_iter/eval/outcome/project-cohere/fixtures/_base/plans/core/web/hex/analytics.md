# Module: analytics

## Purpose

Counts how often each short code is used. A click is recorded against a code via
the module's explicit click endpoint, and the module reports the running total
per code.

## Domain

- **Click** — a value object representing a single recorded hit against a short
  code. Its invariant: the code is non-empty.

## Driving Ports

- **ContAnalytics** — the module's use cases:
  - `record_click(code)` — record one click against a short code.
  - `click_count(code)` — return the total number of clicks recorded for a code
    (0 if none).

## Driven Ports

- **RepoClick** — persistence for click tallies (`record`, `count`). Every
  `record` increments a running total; `count` returns it.

## Adapters Included

- **RepoClickMemory** — in-process tally store for dev and tests.
- **ContAnalyticsHttp** — translates the click/count HTTP routes into port calls.

## Hard Boundaries

- The module counts **total** clicks; it does **not** de-duplicate by visitor,
  session, or IP (no unique-visitor counting).
- The module does not attribute clicks to users or store any per-visitor data.

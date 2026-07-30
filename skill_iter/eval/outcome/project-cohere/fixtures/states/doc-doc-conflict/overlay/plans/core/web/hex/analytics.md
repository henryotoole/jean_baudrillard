# Module: analytics

## Purpose

Counts how many **unique visitors** each short code has had. Repeat hits from the
same visitor are collapsed, so the module reports distinct visitors per code.

## Domain

- **Click** — a value object representing a single recorded hit against a short
  code. Its invariant: the code is non-empty.

## Driving Ports

- **ContAnalytics** — the module's use cases:
  - `record_click(code)` — record one click against a short code.
  - `click_count(code)` — return the number of **unique visitors** for a code
    (0 if none).

## Driven Ports

- **RepoClick** — persistence for click tallies (`record`, `count`). `record`
  de-duplicates repeat visitors; `count` returns the number of distinct visitors.

## Adapters Included

- **RepoClickMemory** — in-process tally store for dev and tests.
- **ContAnalyticsHttp** — translates the click/count HTTP routes into port calls.

## Hard Boundaries

- The module reports **unique visitors** (de-duplicated by visitor); it does not
  expose a raw total-click count.
- The module does not attribute clicks to users or store any per-visitor data.

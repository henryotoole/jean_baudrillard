# Module: links

## Purpose

Creates short codes for target URLs and resolves those codes back to their
targets. This is the core module of the service.

## Domain

- **ShortLink** — a value object binding a `code` to a `target_url`. Its
  invariants: the code is exactly 7 characters, is alphanumeric, and the
  target URL must be an http(s) URL.

## Driving Ports

- **ContLinks** — the module's use cases:
  - `shorten(target_url)` — generate a fresh 7-character alphanumeric code for
    the URL, persist the mapping, and return the code.
  - `resolve(code)` — return the target URL for a code, or `None` when the code
    is unknown.

## Driven Ports

- **RepoShortLink** — persistence for short links (`save`,
  `get_by_code`). `get_by_code` returns `None` on a miss.

## Adapters Included

- **RepoShortLinkMemory** — in-process dict-backed store for dev and tests.
- **ContLinksHttp** — translates the shorten/resolve HTTP routes into port calls.

## Hard Boundaries

- The module does not track click analytics or usage counts.
- The module does not enforce URL reachability; it validates only the scheme.

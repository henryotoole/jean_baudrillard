# Linkfold — Masterplan

## Objectives

Linkfold turns long URLs into short, shareable codes, resolves those codes back
to their targets, and tracks how often each code is used. The project is
successful when a user can shorten any http(s) URL, resolve the returned code to
the original target, and see how many times a code has been clicked.

## Concepts

- **Short code** — the compact, generated identifier that stands in for a target URL.
- **Target URL** — the original http(s) address a short code resolves to.
- **Click** — one recorded hit against a short code.

## Architecture

### Foundation

Fixed. All environments run as docker-compose stacks on a single machine.

### Core Services

| Service | Purpose |
| ------- | ------- |
| `web` | HTTP entry point. Hosts the hexagonal `links` and `analytics` modules. |

### `web`

A hexagonally-structured Python service. It contains two modules:

- **`links`** — creates short codes for target URLs and resolves them back.
  See the [module doc](./web/hex/links.md).
- **`analytics`** — counts total clicks per short code. See the
  [module doc](./web/hex/analytics.md).

## Flows

1. **Shorten flow** — A client POSTs a target URL to `web`; the `links` module
   generates a short code, stores the mapping, and returns the code.
2. **Resolve flow** — A client requests a short code from `web`; the `links`
   module looks up the mapping and issues an HTTP 301 permanent redirect to the
   target URL, or returns 404 when the code is unknown.
3. **Click-tracking flow** — A client records a click against a short code via
   the `analytics` module's explicit click endpoint; the `analytics` module
   tallies the total clicks per code (clicks are not de-duplicated by visitor)
   and reports the count on request. Resolving a code does not itself record a
   click; the `links` and `analytics` modules are independent.

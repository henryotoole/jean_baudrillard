# Linkfold — Masterplan

## Objectives

Linkfold turns long URLs into short, shareable codes and resolves those codes
back to their targets. The project is successful when a user can shorten any
http(s) URL and later resolve the returned code to the original target.

## Concepts

- **Short code** — the compact, generated identifier that stands in for a target URL.
- **Target URL** — the original http(s) address a short code resolves to.

## Architecture

### Foundation

Fixed. All environments run as docker-compose stacks on a single machine.

### Core Services

| Service | Purpose |
| ------- | ------- |
| `web` | HTTP entry point. Hosts the hexagonal `links` module. |

### `web`

A hexagonally-structured Python service. It currently contains a single module:

- **`links`** — creates short codes for target URLs and resolves them back.
  See the [module doc](./web/hex/links.md).

## Flows

1. **Shorten flow** — A client POSTs a target URL to `web`; the `links` module
   generates a short code, stores the mapping, and returns the code.
2. **Resolve flow** — A client requests a short code from `web`; the `links`
   module looks up the mapping and redirects (HTTP 302) to the target URL, or
   returns 404 when the code is unknown.

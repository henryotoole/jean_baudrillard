# Mod 002 — Compose emitter: shared `web` network + `tls.certresolver=doctrine`

## Problem

The `C.4 dev sanity` walk of `test_projects/fixed` (per `docex/test_projects/PRE_CUT_CHECKLIST.md`) brought the stack up cleanly post-mod-001 but `https://dev.doctrine-fixed.luxrnd.tech/health` never reached HTTP 200. Two independent emitter bugs collude to break the request path; both are confirmed by manually patching the compiled compose and observing HTTP 200 with a valid Let's Encrypt cert in ~80 s.

### Bug A — `web` network is project-scoped, machine-wide Traefik can't route

The compose emitter follows the `networks.md` rule literally: every CICL network compiles to `${project}_${env}_${name}`, including `web`. So the dev stack's web-tier service joins `docex_smoke_fixed_dev_web`. The machine-wide Traefik runs on the *bare* `web` network with `--providers.docker.network=web`. Traefik's logs say it out loud:

```
Could not find network named "web" for container "/docex-smoke-fixed-dev-web".
Defaulting to first available network (docex_smoke_fixed_dev_internal) for container ...
```

Traefik then tries to forward HTTPS requests to the web container's IP on `docex_smoke_fixed_dev_internal` — a network Traefik isn't on at all. The request hangs and curl times out.

The doctrine's claim that "the machine-wide Traefik watches" the project-scoped network conflates two things: *watching* (reading the Docker socket for labels — works without network attachment) and *routing* (forwarding HTTP — requires network attachment). Watching works; routing requires Traefik to share the network with the target container.

### Bug B — `tls=true` without `certresolver` never triggers ACME

docex emits these labels for `web`-network services:

```
traefik.http.routers.X.tls=true
traefik.http.routers.X.entrypoints=websecure
```

Traefik v3 does NOT propagate an entrypoint-level default `tls.certResolver` into a router that has an explicit `tls={}` from labels. The `tls=true` label produces an empty TLS block on the router, which suppresses the entrypoint default. Result: no resolver assigned, no ACME order ever placed, Traefik serves its self-signed default cert, browsers refuse, request hangs after the failed TLS handshake.

Adding a single label — `traefik.http.routers.X.tls.certresolver=<name>` — triggers ACME immediately and the cert lands in ~80 s.

## Design

### Bug A fix: special-case `web` as a shared external network in *fixed*-foundation output

In the fixed-foundation compose emitter, the network whose CICL name is `web` compiles to:

```yaml
networks:
  web:
    name: web
    external: true
```

rather than `name: ${project}_${env}_web`. Every other CICL network (including the default `internal` network and any project-defined networks) keeps the existing `${project}_${env}_${name}` scoping.

The `web` network is fundamentally the *public-routing plane*: anything on it is meant to be reachable from the public internet via Traefik. Project-scoped naming on `web` would force either per-project Traefik instances (which can't coexist on port 443) or dynamic Traefik network attachment (complex shim). Cross-project visibility on a shared `web` is functionally identical to cross-internet visibility — which is already the threat model for anything on `web`.

The `internal` network — and any other project-defined networks — remain project-scoped. They are the *true* isolation plane: project A's database has no business being reachable from project B's services. That security boundary stays intact.

**Scope: fixed only.** In *elastic*-foundation output the `web` network compiles to an AWS security group, not a Docker network. Security-group names benefit from explicit `${project}_${env}_web` naming in the AWS console and are not subject to the Traefik routing problem this mod solves. The elastic emit path is untouched.

### Bug B fix: emit `tls.certresolver=doctrine` per web-routed service

The compose emitter adds one additional Traefik label per `web`-network service:

```
traefik.http.routers.<global_service_name>.tls.certresolver=doctrine
```

The literal name `doctrine` is the doctrine's prescribed handle for the single machine-wide cert resolver. The operator (running the machine-wide Traefik) is responsible for configuring a Traefik cert resolver with this name, using DNS-01 against Let's Encrypt for whichever DNS provider their project domain lives on. The doctrine prose carries the implementation requirements; the name itself is a coordination convention between docex's emitted labels and the operator's Traefik config.

Why `doctrine` rather than `le` (Traefik's idiomatic shorthand)?
- **Self-documenting in logs.** A Traefik log line `[doctrine: Trying to solve DNS-01]` immediately signals "this resolver exists because the doctrine asked for it."
- **Decoupled from implementation.** The doctrine prose carries the LE/DNS-01 choice. If a future doctrine revision moves to a different CA or challenge type, the resolver name stays stable.
- **Namespaced.** Coexists cleanly with any other resolvers the operator runs for unrelated workloads.

### Scope notes

- **Fixed only for both bugs.** Bug A's fix is fixed-only (elastic doesn't use Docker networks at all). Bug B's fix is also fixed-only — elastic uses ACM, not Traefik, for TLS.
- **`traefik.docker.network=web` label.** During the C.4 manual verification I added this label too. It turns out to be redundant once Bug A is fixed (the container only has one Traefik-reachable network, so Traefik picks it correctly without a hint). Leaving it out of the emitter to keep the label set minimal.

## Five-artifact alignment

Per [`docex_process.md § Additional Artifacts`](../../core/docex_process.md#additional-artifacts):

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | Three edits, fixed-foundation scoped: (1) `networks.md § Implementation by Name` — under the `web` fixed bullet, carve out that the network compiles to bare external `web` rather than `${project}_${env}_web`. (2) `shape2.md § Description of Shape` — clarify that the fixed-foundation `web` is machine-wide-shared; project-scoping applies to `internal` and other networks only. (3) `transfer_tables.md § Foundation Invariants` — extend the `### Per-container (fixed)` web-routing emission rule to include `traefik.http.routers.<name>.tls.certresolver=doctrine`. Plus a one-sentence addition to `PRE_CUT_CHECKLIST.md § A.6` codifying the resolver name. **Pausing for operator review of exact wording before committing prose.** |
| `docex/plans/core/*.md` | No change. |
| `tables/roles/*.yml` | No change. The `web` role's transfer-table entry already drives Traefik label emission via doctrine-shipped logic in the compose emitter; the role table itself is unchanged. |
| `src/docex/**` | `src/docex/emit/compose.py` — (a) special-case the network named `web` in fixed-foundation emit to produce `{name: web, external: true}`; (b) when emitting Traefik labels for a `web`-network service, add `traefik.http.routers.<name>.tls.certresolver=doctrine`. |
| `tests/**` | Two new unit tests in `tests/unit/test_compose_emitter.py`: (1) `web` network is external + named `web` in fixed compile; non-`web` networks remain project-scoped. (2) Every emitted Traefik router gets the `tls.certresolver=doctrine` label. No fixture changes needed — `sample_project` has a web service on the `web` network. |

## Validation

1. `python3 -m pytest tests/unit/` — all previously-passing tests still pass; new tests pass.
2. Rebuild the docex image, re-pin `test_projects/fixed` if needed, recompile.
3. Inspect the compiled compose: the top-level `networks:` block should have `web: {name: web, external: true}` and `internal: {name: docex_smoke_fixed_dev_internal, internal: true}`. The web service's emitted Traefik labels should include `tls.certresolver=doctrine`.
4. With the operator's machine-wide Traefik configured with a resolver named `doctrine` (the operator's prerequisite work — see below), run `./bin/docex up dev` in `test_projects/fixed`; curl `https://dev.doctrine-fixed.luxrnd.tech/health` and expect HTTP 200 with a Let's Encrypt cert.
5. Confirm the same on `test_projects/elastic` for dev/test envs (they compile to compose).

## Decisions captured

1. **Doctrine carve-out for `web` is fixed-only.** Elastic security groups keep `${project}_${env}_${network}` naming.
2. **Resolver name is `doctrine`.** Doctrine-namespaced, implementation-agnostic.
3. **Both bugs ship in one mod.** Both are compose-emitter changes; both block C.4.
4. **No special handling for cross-project exposure on shared `web`.** Service-level auth is the right defense, same as for any internet-facing surface.
5. **No backwards compatibility shim for existing operator Traefik setups.** Operators with a different resolver name (e.g., my own dev machine's current `le-dns`) must rename to match the doctrine.

## Operator prerequisite work (out of mod scope)

After mod 002 ships, the dev-machine Traefik needs:
- The current `le-dns` resolver renamed to `doctrine` (one line in `/home/ubuntu/n3/traefik/traefik.yml`).
- The current `le` (HTTP-01) resolver removed entirely.
- Existing `acme-dns.json` storage moved/renamed to match the new resolver name (or deleted, accepting re-issue on next request).
- The bare `web` Docker network already exists machine-wide; no change needed there.

Nasmyth's labels currently point at `le` for its cert resolver; they'll need to be updated to `doctrine` and certs reissued. Per operator instruction, nasmyth interruption is acceptable.

## Pending pause

Before writing the actual doctrine prose, I'll show side-by-side proposed wording for each of the three doctrine doc changes and the PRE_CUT_CHECKLIST sentence, and get explicit sign-off on phrasing.

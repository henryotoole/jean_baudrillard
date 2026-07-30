# Preinfra dedicated traefiks lack a discovery constraint — cross-project ACME pollution

## Summary

Every **project** traefik on a shared host logs a steady stream of
`ERR Cannot retrieve the ACME challenge for <host>`, for hosts it is otherwise
serving valid certs for. The errors are **not** that traefik failing its own
issuance — they are foreign ACME HTTP-01 validation traffic caused by a
**preinfra dedicated traefik** (`registry-traefik`, and structurally the HyperDX
traefik) that runs with **no Docker-provider discovery constraint**. Over the
shared Docker socket it discovers *every* project's service containers and opens
ACME orders it can never satisfy. Observed on docex **1.5.0** with `field_radio`
and `maptrack` both polluted by the one rogue `registry-traefik`.

docex already emits a `docex.project` discovery constraint for **project**
traefiks; the doctrine's **preinfra dedicated** traefiks
(`container_registry.md`, `telemetry_preinfra.md`) are prescribed with no
equivalent. That omission is the defect.

## Symptom

`field-radio-traefik` logs (46×), and `maptrack-traefik` identically (36×):

```
ERR Cannot retrieve the ACME challenge for radio.dev.field-radio.luxrnd.tech ...
ERR Cannot retrieve the ACME challenge for field-radio.luxrnd.tech ...
ERR Cannot retrieve the ACME challenge for radio.prod.field-radio.luxrnd.tech ...
   (all field-radio hosts: radio.dev, dev, field-radio, stage, prod, radio.prod, radio.stage)
```

Crucially, the affected project traefiks log **only** `Cannot retrieve the ACME
challenge` and **zero** `Unable to obtain ACME certificate` — their own certs are
valid and served (field-radio-traefik's `acme.json` is ~41 KB, populated;
`CN=radio.dev.field-radio.luxrnd.tech` served correctly). So the projects'
own renewal is **not** broken. The message is emitted by traefik's challenge
*server* when it receives a validation request for a token that is not in its
store — i.e. a token minted by a **different** ACME account.

The Let's Encrypt side confirms it:

```
403 unauthorized :: 3.214.203.31: Invalid response from
http://<host>/.well-known/acme-challenge/<token>: 404
```

`:80` is reachable end-to-end (LE gets a 404, not a timeout); DNS is correct
(all hosts → the shared EIP). It is a token-store mismatch, not a routing,
DNS, or firewall problem.

## Root cause

Challenge type: the `doctrine` resolver uses **HTTP-01** on the `web` entrypoint
(:80), confirmed from `field-radio-traefik`'s args:

```
--certificatesresolvers.doctrine.acme.httpchallenge=true
--certificatesresolvers.doctrine.acme.httpchallenge.entrypoint=web
```

Mechanism:

1. `web_demux` :80 (`http_in` → `project_pool_http`) routes by Host header via
   `project_resolver.lua`, forwarding `*.field-radio.luxrnd.tech` to
   `field-radio-traefik`. Routing verified correct (Lua label math + end-to-end
   curl).
2. `registry-traefik` (static config `/opt/docex-preinfra/container_registry/traefik/traefik.yml`)
   has a Docker provider with **no constraints**:
   ```yaml
   providers:
     docker:
       exposedByDefault: false
       network: container_registry-internal   # sets default backend net only — does NOT filter discovery
   ```
   With no `constraints` and a shared Docker socket, it discovers every container
   carrying `traefik.enable=true` — which is every project's service containers
   (they carry Host routers + `tls.certresolver=doctrine` for *their own* project
   traefik). registry-traefik's own log proves it: it opens orders for
   `maptrack-dev-backend` (109×), `maptrack-dev-frontend` (103×), `sample-dev-api`,
   `docex-smoke-*`, and `field-radio-{dev,stage,prod}-radio`.
3. registry-traefik requests those certs from Let's Encrypt and would answer the
   HTTP-01 challenge on *its* :80. But `web_demux` Host-routes the LE validation
   for each host to the **correct project** traefik, which does not hold
   registry-traefik's token → 404 → registry-traefik's order fails forever, and
   the project traefik logs `Cannot retrieve the ACME challenge`.

Project traefiks are configured correctly: `field-radio-traefik` carries
`--providers.docker.constraints=Label(` + "`docex.project`,`field-radio`" + `)`
(docex-emitted; `docex/src/docex/emit/compose.py:793`). It is a victim.

## Classification

**Doctrine defect in the preinfra layer** — not a project bug, not environmental
drift.

- The on-host `registry-traefik/traefik.yml` matches the doctrine's prescribed
  config *verbatim* (`container_registry.md` traefik block) — nothing hand-mistuned.
- The doctrine emits a `docex.project` discovery constraint for **project**
  traefiks but omits the equivalent for **preinfra dedicated** traefiks. Grep for
  "constraint" across `doctrine/infrastructure/preinfra/` returns nothing.
- The HyperDX/telemetry traefik (`telemetry_preinfra.md`) is structurally
  identical and carries the same latent bug (not running on this host, so
  registry-traefik is the sole active rogue here).
- Scope test: `field_radio` and `maptrack` are polluted identically by the one
  common rogue → shared/preinfra, not per-project.

Related prior art: `docex/plans/modifications/047_smoke_walk_polish/overview.md:45`
documents the **inverse** direction (project traefiks picking up preinfra
containers) and fixed only that direction. This is the mirror case.

## Real harm

TLS is fine today (projects serve their own valid certs). The ongoing harm:

1. Constant error noise on every project traefik.
2. **registry-traefik burns Let's Encrypt failed-authorization rate-limit budget**
   against the shared registrable domains (`field-radio.luxrnd.tech`,
   `maptrack.luxrnd.tech`, …). This is a cross-account rate-limit hazard that can
   eventually block a *legitimate* renewal. Worth fixing before real renewals fall
   due.

## Recommended fix

Scope every preinfra dedicated traefik's Docker provider to its own project,
mirroring what docex already does for project traefiks.

**Doctrine source (the real fix):** in the prescribed traefik configs of
`doctrine/infrastructure/preinfra/container_registry.md` and
`telemetry_preinfra.md`, add a provider discovery constraint and a matching
`docex.project` label on the preinfra container:

```yaml
providers:
  docker:
    exposedByDefault: false
    network: container_registry-internal
    constraints: "Label(`docex.project`,`registry`)"   # (`telemetry` for the HyperDX traefik)
```
and add `docex.project=registry` (resp. `telemetry`) to the corresponding
container's labels.

**Immediate host mitigation (unblocks now, pre-fix):**
1. Edit `/opt/docex-preinfra/container_registry/traefik/traefik.yml` — add the
   `constraints` line above.
2. Add `docex.project=registry` to the registry container's labels in
   `/opt/docex-preinfra/container_registry/registry/docker-compose.yml`.
3. Restart `registry-traefik`.

This immediately stops the foreign orders, clears the `Cannot retrieve the ACME
challenge` spam on all project traefiks, and halts the rate-limit burn. A
regression check: bring up a preinfra dedicated traefik alongside a project
stack and assert the preinfra traefik opens ACME orders for *only* its own
host(s).

---

_Findings from the `field_radio` dev investigation, 2026-07-22 (docex 1.5.0). No
changes were made to preinfra or the doctrine; this is a writeup for the next
doctrine update._

# Mod 143 — Preinfra dedicated traefiks need a discovery constraint

## Goal

Give the doctrine's **preinfra dedicated** traefiks (the container registry's
`registry-traefik`, and HyperDX's dedicated traefik on both foundations) a
Docker-provider **discovery constraint** scoped to their own preinfra "project",
mirroring what `docex` already emits for **project** traefiks. Without the
constraint, a preinfra dedicated traefik running on a shared Docker socket
discovers *every* project's `traefik.enable=true` containers and opens ACME
orders it can never satisfy — spamming `Cannot retrieve the ACME challenge` on
every project traefik and burning Let's Encrypt failed-authorization
rate-limit budget against shared registrable domains.

Design record (the full investigation): `../../advances/008_housekeeping/references/acme_cert_issue_fixed.md`.

## Classification

**Doctrine-only edit.** Preinfra dedicated traefiks are configured by hand from
the doctrine's setup docs — they are **not** emitted by `docex`. Confirmed:

- `docex/src/docex/emit/compose.py:784` emits the `docex.project` constraint and
  `:795` the matching label for **project** traefiks (the reference pattern).
- No `docex` src emits any preinfra dedicated traefik config; the only mention is
  a comment in `docex/src/docex/describe/dag.py:23`. `masterplan.md` classifies
  `preinfra` as a *read-only probe*.

Therefore there is **no docex src change, no transfer-table change, and no unit
test** in this mod. The change is entirely in two doctrine files, and its
verification gate is a live preinfra host walk (see § Deferred gate).

## The change

### 1. `doctrine/infrastructure/preinfra/container_registry.md`

- **Docker-provider block** (`traefik.yml`, the `providers.docker` map): add
  `constraints: "Label(\`docex.project\`,\`registry\`)"` (literal backticks —
  traefik constraint syntax).
- **Registry container labels** (the `registry` service): add
  `- "docex.project=registry"`.

### 2. `doctrine/infrastructure/preinfra/telemetry_preinfra.md`

- **Both** `providers.docker` blocks — the **Fixed** dedicated traefik
  (`hyperdx_traefik`, step 4.4) and the **Elastic** dedicated traefik
  (`traefik`, step 4.4) — add
  `constraints: "Label(\`docex.project\`,\`telemetry\`)"`. Both blocks are the
  dedicated HyperDX traefik's docker provider (see § Provider-block roles).
- **HyperDX UI/app service labels** (step 3, the "Common" install section):
  add `- "docex.project=telemetry"`.
- **otel-collector service labels** (step 4, the "Common" install section):
  add `- "docex.project=telemetry"`.

The `docex.project` label value is an **independent, traefik-internal**
discovery key (it need not equal the `web_demux` project name). We use
`registry` / `telemetry` per the design record; the only hard requirement is
that a dedicated traefik's constraint value matches the label value on every
container it serves.

## The constraint↔label pairing (silent-break guard)

Once a traefik carries `constraints: Label(docex.project, X)`, it discovers
**only** containers labeled `docex.project=X`. Every container a dedicated
traefik must serve therefore needs the matching label, or that traefik silently
stops issuing that host's cert. Full enumeration:

**registry-traefik — constraint `Label(docex.project, registry)`:**

| Served container | Has `traefik.enable=true`? | Gets `docex.project=registry`? |
| ---------------- | -------------------------- | ------------------------------ |
| `registry` (the Docker Registry V2 container) | yes | **yes** (added) |

The `registry` container is the **only** `traefik.enable=true` container in the
registry stack. Pairing complete (1 container).

**HyperDX dedicated traefik (fixed `hyperdx_traefik` / elastic `traefik`) — constraint `Label(docex.project, telemetry)`:**

| Served container | Has `traefik.enable=true`? | Gets `docex.project=telemetry`? |
| ---------------- | -------------------------- | ------------------------------- |
| HyperDX UI / `app` service (step 3 labels) | yes | **yes** (added) |
| `otel-collector` service (step 4 labels, receives OTLP) | yes | **yes** (added) |

These two label blocks live in the **Common** HyperDX-install section, so they
apply to **both** the fixed and elastic dedicated traefik. No other container in
the doctrine's HyperDX config carries `traefik.enable=true` (ClickHouse, Mongo,
etc. are not traefik-exposed). Pairing complete (2 containers, both foundations).

## Provider-block roles (confirmed)

`telemetry_preinfra.md` has exactly two `providers.docker` blocks, and both are
the dedicated telemetry traefik's docker provider:

- **Fixed** section, step 4.4 (`container_name: hyperdx_traefik`,
  `network: hyperdx-internal`) — dedicated telemetry traefik, fixed foundation.
- **Elastic** section, step 4.4 (`container_name: traefik`,
  `network: hyperdx-internal`) — dedicated telemetry traefik, elastic foundation.

Both get the `telemetry` constraint.

## Drift check (six artifacts)

- **Doctrine** (rule of record): the two files above — edited.
- **`docex/plans/core/*.md`**: no core doc claims docex emits preinfra dedicated
  traefik config (masterplan: preinfra is a read-only probe). No change.
- **`doctrine_excerpts/`**: `reverse_proxy.md` acknowledges preinfra dedicated
  traefiks exist but makes no claim about their discovery scope; no excerpt
  contradicts the change. No excerpt edit; `index.yml` no resource change.
- **Transfer tables / src / tests**: none — doctrine-only.
- **Skill `preinfra-setup`**: routes to these two docs with **file-level** links
  (no section anchors), so pointers still resolve. No skill edit.

## Deferred gate — verification is PENDING (operator-supervised)

This mod lands the **doctrine edit only**. Verification is an
**operator-supervised live preinfra-host walk** and is **DEFERRED / PENDING**:

> A preinfra dedicated traefik must open ACME orders for **only** its own
> host(s); the `Cannot retrieve the ACME challenge` spam / Let's Encrypt 429
> burn on project traefiks must stop.

The **immediate host mitigation** — editing the live
`/opt/docex-preinfra/.../traefik.yml` + container labels and restarting the
dedicated traefik — is the **operator's**, applied at the walk. It is **not**
part of this commit. This mod does not run, simulate, or apply anything against
a live host.

## Design questions

None. The design record maps the exact sites and the constraint↔label pairing;
the two telemetry provider blocks are confirmed to both be the dedicated
telemetry traefik; no escalation condition is met.

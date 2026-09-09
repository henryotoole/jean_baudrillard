# Mod 143 — Implementation steps

**Repo root:** `/home/ubuntu/.claude/jean_baudrillard`. Branch: `advance_008_housekeeping`
(already checked out; do **not** create a branch).

**Scope:** doctrine-only. Two markdown files. **No** docex src, transfer-table,
test, or core-doc change. Do **not** run, simulate, or apply anything against a
live host — verification is a deferred operator gate.

**Concurrent operator WIP is in the tree** (`RELEASING.md`, deleted
`floating_todo/` files, untracked `docex/plans/advances/009_test_overhaul/`).
Do **not** touch any of it. When committing, stage only the paths this doc names
with explicit `git add <path>` — **never** `git add -A` / `-u` / `.`.

---

## Edit 1 — `doctrine/infrastructure/preinfra/container_registry.md`

### 1a. Docker-provider constraint (in the `traefik.yml` block)

Find this block:

```yaml
providers:
  docker:
    exposedByDefault: false
    network: container_registry-internal
```

Replace with (add the `constraints` line; keep the literal backticks exactly):

```yaml
providers:
  docker:
    exposedByDefault: false
    network: container_registry-internal
    # Scope discovery to this preinfra "project" only. Without it, over the
    # shared docker socket this traefik discovers EVERY project's
    # traefik.enable=true containers and opens ACME orders it can never
    # satisfy — spamming project traefiks and burning Let's Encrypt
    # rate-limit budget. Mirrors the docex-emitted project-traefik constraint.
    constraints: "Label(`docex.project`,`registry`)"
```

### 1b. Registry container label (in the `registry` service's `labels:` list)

Find:

```yaml
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=container_registry-internal"
```

Replace with (insert the `docex.project=registry` label; it must be present on
every container this traefik serves, or the constraint silently drops it):

```yaml
    labels:
      - "traefik.enable=true"
      - "docex.project=registry"
      - "traefik.docker.network=container_registry-internal"
```

---

## Edit 2 — `doctrine/infrastructure/preinfra/telemetry_preinfra.md`

There are **two** `providers.docker` blocks (one in the **Fixed** section step
4.4, one in the **Elastic** section step 4.4). Both are the dedicated HyperDX
traefik's docker provider. Both get the **same** `telemetry` constraint. Because
the two blocks are byte-identical, do these two edits with a unique surrounding
context, or edit each occurrence in place — verify **both** are updated.

### 2a. Both docker-provider blocks

Each occurrence reads:

```yaml
providers:
  docker:
    exposedByDefault: false
    network: hyperdx-internal
```

Change **each** to:

```yaml
providers:
  docker:
    exposedByDefault: false
    network: hyperdx-internal
    # Scope discovery to this preinfra "project" only — otherwise, over the
    # shared docker socket, this dedicated traefik discovers every project's
    # traefik.enable=true containers and opens unsatisfiable ACME orders.
    # Every container this traefik serves must carry docex.project=telemetry
    # (the HyperDX UI/app service and the otel-collector service below).
    constraints: "Label(`docex.project`,`telemetry`)"
```

(Only the first occurrence needs the full comment; the second may carry the same
comment or a short `# See the Fixed block above.` — either is fine, as long as
**both** blocks end up with the `constraints:` line.)

### 2b. HyperDX UI/app service labels (Common install, step 3)

Find:

```yaml
   labels:
     - "traefik.enable=true"
     - "traefik.docker.network=hyperdx-internal"
     - "traefik.http.routers.hyperdx.rule=Host(`hyperdx.${BASE_DOMAIN}`)"
```

Replace with (insert `docex.project=telemetry`):

```yaml
   labels:
     - "traefik.enable=true"
     - "docex.project=telemetry"
     - "traefik.docker.network=hyperdx-internal"
     - "traefik.http.routers.hyperdx.rule=Host(`hyperdx.${BASE_DOMAIN}`)"
```

### 2c. otel-collector service labels (Common install, step 4)

Find:

```yaml
   labels:
     - "traefik.enable=true"
     - "traefik.docker.network=hyperdx-internal"
     - "traefik.http.routers.hyperdx_otlp.rule=Host(`hyperdx.${BASE_DOMAIN}`) && PathPrefix(`/v1/`)"
```

Replace with (insert `docex.project=telemetry`):

```yaml
   labels:
     - "traefik.enable=true"
     - "docex.project=telemetry"
     - "traefik.docker.network=hyperdx-internal"
     - "traefik.http.routers.hyperdx_otlp.rule=Host(`hyperdx.${BASE_DOMAIN}`) && PathPrefix(`/v1/`)"
```

---

## Contracts

No core-service contract changes — this mod touches no core service surface.

## Verification (do NOT touch a live host)

1. **Default test suite** (confirm nothing regressed; no tests added, count
   should be unchanged). From `docex/`:

   ```bash
   .venv/bin/python -m pytest tests -q
   ```

   Expect `1253 passed, 21 deselected`. Timeout 600000ms. Run in foreground.

2. **Linkcheck** from repo root (doctrine was edited — confirm green):

   ```bash
   ./bin/docex linkcheck    # or the repo's linkcheck entry point
   ```

   A `RELEASING.md` / `floating_todo` BROKEN-FILE report is operator WIP —
   **report it, do not touch it or try to fix it**. The two edited doctrine
   files must be clean.

3. Do **not** run the integration suite (no src changed) and do **not** run,
   simulate, or bring up any preinfra host. The live ACME verification is a
   deferred operator gate and is out of scope for this implementation.

## Report back

- Exact before/after of every line changed in both files.
- Confirmation both telemetry `providers.docker` blocks got the constraint.
- Confirmation each served container got its `docex.project=` label
  (registry: `registry`; telemetry: app + otel-collector).
- Test suite count and linkcheck verdict.
- That no docex src / tests / core docs were touched.

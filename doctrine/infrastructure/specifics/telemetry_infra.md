# Telemetry Specifics

This document covers the deterministic infrastructure `docex` emits to fulfill the application telemetry flow promised in [telemetry.md](../telemetry.md). The developer doesn't read this to *use* telemetry — they read it to diagnose when telemetry breaks. The operator and LLM agent read it to understand what `docex` is actually doing.

Scope: how the OTel collector sidecar is shaped, configured, secured, and wired into each core service's runtime, per foundation. Out of scope: the observability backend itself (covered in [telemetry_preinfra.md](../prereq/telemetry_preinfra.md)) and developer-facing OTel SDK practices (covered in [practices/logging.md § With Respect to Telemetry](../../practices/logging.md#with-respect-to-telemetry)).

## Common

Properties of the sidecar that hold across both foundations. The `## Fixed` and `## Elastic` sections below reference these by name and only describe the per-foundation delivery mechanism.

### Sidecar Image

Every sidecar runs `otel/opentelemetry-collector:<digest>` — the lean "core" distribution. The contrib distribution (~10× larger) carries engine-specific receivers (`postgresqlreceiver`, etc.) that the deferred [backing-service telemetry](../telemetry.md#planned-but-not-implemented) would need; until that lands, the core distribution is sufficient.

The image is pinned by digest, not tag — base-layer churn is absorbed by doctrine cuts, not surfaced to projects. The digest moves when the doctrine cuts a new version; projects pinned to a given `docex_version` always pull the same sidecar image.

### Pipeline Shape

Every sidecar runs the same OTel pipeline:

```
otlp receiver  →  batch processor  →  <exporter, env-dependent>
```

- The `otlp` receiver listens on `:4318` (HTTP/protobuf) — matching the `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` the doctrine injects into core services.
- The `batch` processor groups signals before export. Default otelcol settings (200 ms timeout, 8192-signal batch ceiling).
- The exporter varies by environment — see [Per-Env Exporter Configuration](#per-env-exporter-configuration) below.

Receivers, processors, and pipeline shape are identical across both foundations and across all four envs. Only the exporter destination changes.

### Per-Env Exporter Configuration

The sidecar's exporter destination is env-aware, implementing the dev/test vs. stage/prod dichotomy committed to in [telemetry.md § During Development](../telemetry.md#during-development):

| Env | Exporter | Destination | Backend env vars required |
| --- | -------- | ----------- | -------------------------- |
| `dev` | `debug` | sidecar stdout | None |
| `test` | `debug` | sidecar stdout | None |
| `stage` | `otlphttp` | `OBSERVABILITY_BACKEND_URL` with `Authorization: ${TELEMETRY_API_KEY}` | Both |
| `prod` | `otlphttp` | `OBSERVABILITY_BACKEND_URL` with `Authorization: ${TELEMETRY_API_KEY}` | Both |

In `dev` and `test`, telemetry signals are dumped to the sidecar's container stdout via otelcol's `debug` exporter. Developers and LLM agents read them with `docker logs -f <svc>_otelcol`. No backend setup or credentials required to run a dev stack.

In `stage` and `prod`, signals go to the project's observability backend via OTLP over HTTPS. Authentication is API-key in HTTP header per [telemetry.md § Authentication](../telemetry.md#authentication).

The exporter switch is the *only* per-env difference in the sidecar. Image, pipeline, receivers, processors, healthcheck, and resource allocation are identical across all four envs.

### Sidecar Configuration YAML

`docex compile` renders one config file per env. The shape is identical across both foundations and across all sidecars in a given env — the file content does not differ per-service. Structure:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:4318

processors:
  batch: {}

exporters:
  # Emitted in dev/test only:
  debug:
    verbosity: detailed

  # Emitted in stage/prod only:
  otlphttp:
    endpoint: ${env:OBSERVABILITY_BACKEND_URL}
    headers:
      authorization: ${env:TELEMETRY_API_KEY}

extensions:
  health_check:
    endpoint: 127.0.0.1:13133

service:
  extensions: [health_check]
  pipelines:
    traces:  { receivers: [otlp], processors: [batch], exporters: [<debug|otlphttp>] }
    metrics: { receivers: [otlp], processors: [batch], exporters: [<debug|otlphttp>] }
    logs:    { receivers: [otlp], processors: [batch], exporters: [<debug|otlphttp>] }
```

Only one of the `debug` / `otlphttp` exporters is emitted, depending on env. Runtime substitutions (`${env:VAR}`) are read by otelcol at startup from its environment block.

### Env Vars Injected on Core Services

Every core service receives the doctrine-injected env vars defined in [transfer_tables.md § Per-core-service env](./transfer_tables.md#per-core-service-env-both-foundations). The full list:

| Variable | Value | Notes |
| -------- | ----- | ----- |
| `PROJECT_VERSION` | `${project_version}` | Existing doctrine var; not telemetry-specific |
| `OTEL_SERVICE_NAME` | `${service_name}` | OTel-standard service identity |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Same on both foundations — the paired sidecar shares the core service's network namespace, so loopback addressing is universal |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Doctrine-fixed |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.namespace=${project_name},service.version=${project_version},deployment.environment.name=${env_name}` | Drives backend-side filtering |

The application's OTel SDK auto-discovers all of these from its environment. No code change is required at the application layer.

### Env Vars Injected on Sidecars

Every sidecar receives:

| Variable | Value | Required in env | Notes |
| -------- | ----- | --------------- | ----- |
| `OBSERVABILITY_BACKEND_URL` | from `infra.yml`'s top-level `observability_backend_url` | stage, prod | Not consumed by the `debug` exporter, so absence is fine in dev/test |
| `TELEMETRY_API_KEY` | from `secrets/<env>.env` | stage, prod | Not consumed by the `debug` exporter, so absence is fine in dev/test |

The sidecar never receives the application's env vars. Application code never sees `TELEMETRY_API_KEY` or `OBSERVABILITY_BACKEND_URL` — the credential and backend URL are sidecar-scoped per [telemetry.md § Authentication](../telemetry.md#authentication)'s trust model.

### The TELEMETRY_API_KEY Secret

Lives in `infra/secrets/<env>.env` as `TELEMETRY_API_KEY=<value>`. `docex compile` emits it as a required entry in `infra/secrets/example.env` for `stage` and `prod`; it is omitted from the example for `dev` and `test`.

The operator obtains the key from HyperDX (or the configured backend's equivalent) before first stage release per [telemetry_preinfra.md](../prereq/telemetry_preinfra.md).

### Resource Allocation

Each sidecar is doctrine-allocated:

- **CPU**: 0.1 vCPU
- **Memory**: 128 MB

These are doctrine-prescribed defaults; not project-tunable in v1. The sizing is conservative for the v1 pipeline (otlp → batch → exporter) and assumes single-digit signals-per-second per service. Projects emitting at much higher rates may experience batch-processor drops; that is a v1 limitation per [telemetry.md § Storage Window](../telemetry.md#storage-window)'s in-memory-only buffering decision.

### Validation Rules

Two layers. The doctrine prefers compile-time errors over runtime errors:

**Compile-time (syntactic).** `docex compile` enforces:

1. `observability_backend_url` is set on `infra.yml` when compile emits `stage` or `prod` output. Missing value for either fails compile with a message identifying which env requires it. Dev/test compile do not require it.
2. `observability_backend_url`'s value uses the `https://` scheme and parses as a well-formed URL. `http://` is rejected at compile time per [telemetry.md § Authentication](../telemetry.md#authentication).
3. No network calls — preserves the compiler's offline-pure invariant.

**`docex check`-time (reachability).** The CI/CD gate-check sequence per [cicd.md § Check Step](../cicd.md#check-step) adds:

1. An HTTP GET against `observability_backend_url`. Any non-network-error response (2xx/3xx/4xx) passes — the check verifies that the host resolves and the TLS handshake completes. A 401 or 404 means the host is up, which is sufficient to catch typos and DNS misconfigurations.
2. DNS-resolution failure, TLS-handshake failure, or connection refusal aborts the check before merge.

The reachability probe runs only when `stage` or `prod` are within the check's scope — `dev` and `test` don't have a backend URL to probe.

### Failure Modes

| Failure | Symptom | Where to look |
| ------- | ------- | ------------- |
| Backend unreachable at runtime | Sidecar logs export errors; in-memory queue fills; oldest signals dropped on overflow | `docker logs <svc>_otelcol` (fixed) / CloudWatch task logs (elastic); backend's own health page |
| Sidecar crashed | Core service's SDK can't reach `OTEL_EXPORTER_OTLP_ENDPOINT`; SDK buffers briefly, then drops | Sidecar container logs; on elastic, ECS task status — sidecar is `essential: false` so a crash doesn't tear down the task |
| Sidecar config malformed at startup | Sidecar exits non-zero immediately; parse error in logs | `infra/output/<env>/...` — the rendered YAML is fully visible in compile output; compare against the spec in this document |
| `TELEMETRY_API_KEY` missing in stage/prod env | Compile passes (it's syntactic). `docex release` succeeds but sidecar fails to start at runtime with `${env:TELEMETRY_API_KEY}` substitution error | `secrets/<env>.env` — confirm the key is present and non-empty |
| `OBSERVABILITY_BACKEND_URL` typo or stale | `docex check` fails the reachability probe before merge | `infra.yml`'s top-level `observability_backend_url`; the backend's own health |
| API key wrong | Sidecar starts cleanly; backend returns 401 on each export attempt; signals lost | Sidecar logs show 401 from the backend; rotate the key in HyperDX and update `secrets/<env>.env` |
| App signals not appearing in backend at all | Could be SDK not wired up, sidecar unreachable, or backend silently dropping | Bottom-up: confirm SDK init in core service; confirm sidecar healthy (`/13133`); confirm sidecar logs show outgoing export attempts; confirm backend received them |

---

## Fixed

Compose-level mechanics. Sidecar emitted as a paired compose service.

### Sidecar as Paired Compose Service

For each core service `<svc>`, `docex compile` emits an additional compose service named `<svc>_otelcol`. The sidecar shares the core service's network namespace via compose's `network_mode: "service:<svc>"` — it does not declare its own `networks:` (mutually exclusive with `network_mode`).

Netns sharing on fixed deliberately mirrors the ECS task-netns sharing on elastic — the two foundations end up with identical loopback semantics, so `OTEL_EXPORTER_OTLP_ENDPOINT` resolves to the same value on both. It also sidesteps the edge case of a core service that only joins the `web` network: the sidecar inherits whatever networks the core service joins, with no per-network choice for `docex` to make.

Emitted compose entry shape (illustrative — actual emit lives in `src/docex/emit/compose.py`):

```yaml
<svc>_otelcol:
  image: otel/opentelemetry-collector:<digest>
  container_name: ${project}_${env}_<svc>_otelcol
  command: ["--config=/etc/otelcol/config.yaml"]
  network_mode: "service:<svc>"
  configs:
    - source: otelcol_config
      target: /etc/otelcol/config.yaml
  environment:
    OBSERVABILITY_BACKEND_URL: ${OBSERVABILITY_BACKEND_URL:-}
    TELEMETRY_API_KEY: ${TELEMETRY_API_KEY:-}
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:13133"]
    interval: 10s
    timeout: 5s
    retries: 3
  deploy:
    resources:
      limits:
        cpus: "0.1"
        memory: 128M
  restart: unless-stopped
  logging: *default-logging
```

The compose `configs:` top-level block declares `otelcol_config` once per env, sourcing from the rendered config file (see below). All sidecars in the env reference the same config.

### Service Discovery

The core service reaches its sidecar at `localhost:4318` — `network_mode: "service:<svc>"` makes the core service and the sidecar share a loopback. The compiled value of `OTEL_EXPORTER_OTLP_ENDPOINT` on the core service is therefore:

```
http://localhost:4318
```

This is identical to the value on elastic. Application code and the doctrine-injected env var are foundation-agnostic; only the netns-sharing mechanism underneath differs.

### Config Delivery

The sidecar config YAML is rendered to `infra/output/<env>/otelcol-config.yaml` (one file per env, shared by every sidecar in that env). The compose `configs:` mechanism mounts it into each sidecar at `/etc/otelcol/config.yaml`.

The rendered file lives under `infra/output/` and is git-tracked per [cicl.md § Compiler Output](../cicl.md#compiler-output), so PR diffs show exactly what the sidecar will run.

### Secret Delivery

Standard compose `environment:` block on the sidecar reading from the rendered `.env` per [release_mechanism.md § Fixed Foundation: Ansible](./release_mechanism.md#fixed-foundation-ansible).

The `${VAR:-}` syntax (with empty default) means the variables are optional from compose's perspective — `dev.env` and `test.env` don't need to declare them. In `stage.env` and `prod.env` they must be set; if omitted, the sidecar starts but otelcol's `${env:VAR}` substitution in the config fails at startup with a clear error.

### Healthcheck and Startup Ordering

The sidecar runs otelcol's `health_check` extension on `127.0.0.1:13133`, polled by the compose healthcheck for diagnostic visibility — `docker compose ps` shows the sidecar's health status, and the operator can use it to confirm the sidecar started cleanly.

The core service does **not** declare a `depends_on` healthcheck on `<svc>_otelcol`. With `network_mode: "service:<svc>"`, compose enforces an implicit dependency in the *opposite* direction — the sidecar can't start until the core service's container exists (its netns has to be there to share). The core service therefore starts first; the sidecar attaches to its netns immediately after; both processes initialize concurrently.

This means the core service does not have a guaranteed sidecar at `t=0`. The OTel SDK's default batch/retry behavior covers the brief startup window — sidecar readiness is typically 1–2 seconds, well within the SDK's queue tolerance (default queue size of 2048 spans, 5-second flush interval). Signals emitted during the startup window are buffered, not dropped.

---

## Elastic

ECS task-level mechanics. Sidecar emitted as a paired container in the same task definition.

Note: `dev` and `test` are always fixed per [shape2.md § Shape and Environment](../shape2.md#shape-and-environment), so the elastic mechanics below apply only to `stage` and `prod`. The exporter is always `otlphttp`; both `OBSERVABILITY_BACKEND_URL` and `TELEMETRY_API_KEY` are always required on elastic compiles.

### Sidecar as Paired Task Container

For each core service `<svc>`, the ECS task definition contains two containers: the application container and an `<svc>_otelcol` container. They share the task netns. There is no separate ECS service for the sidecar.

Emitted task-definition container fragment for the sidecar (illustrative):

```hcl
container_definitions = jsonencode([
  {
    name      = "<svc>"
    # ... core service definition ...
    dependsOn = [
      { containerName = "<svc>_otelcol", condition = "HEALTHY" }
    ]
  },
  {
    name      = "<svc>_otelcol"
    image     = "otel/opentelemetry-collector:<digest>"
    essential = false
    command   = ["--config=env:OTEL_CONFIG_YAML"]
    cpu       = 102      # ~0.1 vCPU in Fargate units (vCPU × 1024)
    memory    = 128
    environment = [
      { name = "OTEL_CONFIG_YAML",            value = <literal YAML string> },
      { name = "OBSERVABILITY_BACKEND_URL",   value = "<from infra.yml>" }
    ]
    secrets = [
      { name = "TELEMETRY_API_KEY", valueFrom = "/<project>/<env>/TELEMETRY_API_KEY" }
    ]
    healthCheck = {
      command  = ["CMD", "wget", "--spider", "-q", "http://localhost:13133"]
      interval = 10
      timeout  = 5
      retries  = 3
    }
  }
])
```

### Service Discovery

The core service reaches its sidecar at `localhost:4318` — shared task netns. The compiled value of `OTEL_EXPORTER_OTLP_ENDPOINT` on the core service container is therefore:

```
http://localhost:4318
```

This is identical to the value on fixed (where compose's `network_mode: "service:<svc>"` provides the same shared-loopback effect). Application code is identical across both foundations because the URL is identical — not because the SDK abstracts away a difference.

### Config Delivery

The rendered config YAML is embedded as a literal string into the task definition's `OTEL_CONFIG_YAML` env entry. The sidecar's command is:

```
--config=env:OTEL_CONFIG_YAML
```

otelcol's `env:` config-source provider reads its entire config from the named env var at startup. The HCL diff for the task definition (in `infra/output/<env>/main.tf`) contains the full literal YAML — operators can see exactly what the sidecar will run by reading the HCL.

This is an embedded-YAML approach rather than an external config source (S3, SSM) for two reasons:
1. Keeps the secret-flow surface narrow — SSM is reserved for actual secrets per [release_mechanism.md § Secrets](./release_mechanism.md#secrets).
2. The config diff is visible in the same HCL the operator already reviews, not in a separate fetch path.

### Secret Delivery

`TELEMETRY_API_KEY` is delivered via an ECS `secrets[]` entry on the sidecar container, sourcing from `/<project>/<env>/TELEMETRY_API_KEY` in SSM Parameter Store, per [release_mechanism.md § Elastic Foundation: OpenTofu](./release_mechanism.md#elastic-foundation-opentofu). `docex release` pushes the SSM parameter from `infra/secrets/<env>.env` on every deploy.

`OBSERVABILITY_BACKEND_URL` is delivered as a regular `environment[]` entry — the URL is not sensitive.

### Container Dependencies and Essentiality

The sidecar is declared `essential: false` — a sidecar crash doesn't kill the task. The core service stays serving; the SDK harmlessly buffers signals to a dead local port until they're dropped per [Failure Modes](#failure-modes).

The core service declares:

```hcl
dependsOn = [
  { containerName = "<svc>_otelcol", condition = "HEALTHY" }
]
```

so the SDK has somewhere to send from `t=0`. ECS waits on the sidecar's healthcheck (the `health_check` extension on `:13133`) before starting the core service.

### Task-Level Resource Allocation

ECS Fargate tasks declare CPU and memory at the task level; per-container allocations come from the task's totals. The sidecar's 0.1 vCPU / 128 MB allowance adds to whatever the core service requested in `resources:`.

A core service with `resources: { cpu: 1.0, memory: 2GB }` in `infra.yml` produces a Fargate task with task-level `cpu = 1126` (1.1 vCPU × 1024) and `memory = 2176` MB (2048 + 128) per [transfer_tables.md § Resources Translation](./transfer_tables.md#resources-translation). The sidecar's overhead is doctrine-fixed; the core service always receives exactly what it asked for, with the sidecar's allocation added on top.

**Fargate tier rounding.** Fargate only supports discrete (vCPU, memory) combinations. The sidecar's overhead may push the computed task size into the next-tier-up combination (e.g., a project requesting `cpu: 1.0` produces a task needing `1.1 vCPU` total, which on Fargate rounds up to the `2 vCPU` tier). The compiler computes the next supported tier and surfaces the rounding in compile output so the cost implication is visible. Projects sensitive to this can request slightly under a Fargate tier boundary to absorb the sidecar overhead within the same tier.

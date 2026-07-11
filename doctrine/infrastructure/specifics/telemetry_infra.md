---
stratum: conditional
---

# Telemetry Specifics

This document covers the deterministic infrastructure `docex` emits to fulfill the application telemetry flow promised in [telemetry.md](../telemetry.md). The developer doesn't read this to *use* telemetry — they read it to diagnose when telemetry breaks. The operator and LLM agent read it to understand what `docex` is actually doing.

Scope: how the OTel collector sidecar is shaped, configured, secured, and wired into each core service's runtime, per foundation, plus the Class-2 container-stdout path to CloudWatch. Out of scope: the observability backend itself (covered in [telemetry_preinfra.md](../preinfra/telemetry_preinfra.md)) and developer-facing OTel SDK practices (covered in [practices/logging.md § With Respect to Telemetry](../../practices/logging.md#with-respect-to-telemetry)).

## Container stdout/stderr (Class-2 Diagnostics)

Two distinct classes of output leave a core service, and only the first flows through the OTel sidecar this document otherwise describes:

- **Class 1 — SDK telemetry.** Structured logs, traces, and metrics the application emits through the OTel SDK → the paired collector sidecar → the observability backend. Everything below the `## Common` heading concerns this path.
- **Class 2 — raw stdout/stderr.** Crash stacks, panics, output emitted *before* the SDK initializes, and shell scripts like `migrate.sh` — none of which can travel the OTLP path. This is captured separately, by the platform's native container-log mechanism: `docker logs` on **fixed** (the `json-file` driver, per the `x-logging` anchor in [transfer_tables.md](./transfer_tables.md#per-compose-file-fixed)), and on **elastic** by an `awslogs` `logConfiguration` on **every** container in each ECS task definition — the application container, the OTel sidecar, *and* the `_migrate` container.

On elastic, `docex compile` emits a per-env `aws_cloudwatch_log_group` (`/<project>/<env>/<service>`, `retention_in_days = 30`, `managed_by = "doctrine"`), torn down with the env. The group is **tofu-created, not** `awslogs-create-group=true`: the task-execution role grants `logs:CreateLogStream` + `logs:PutLogEvents` but deliberately **not** `logs:CreateLogGroup` (see [elastic_iam.md](./projinfra/elastic_iam.md)), so group creation belongs to tofu — which is also where retention and tagging live.

Class 2 is *diagnostics*, not queryable telemetry; it deliberately does **not** funnel through the sidecar (that would require a second log-router sidecar). Keeping the two paths separate is also why application code must **not** mirror its SDK telemetry to stdout — doing so would double Class-1 records into CloudWatch on top of the backend. See [practices/logging.md § With Respect to Telemetry](../../practices/logging.md#with-respect-to-telemetry).

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

In `dev` and `test`, telemetry signals are dumped to the sidecar's container stdout via otelcol's `debug` exporter. Developers and LLM agents read them with `docker compose logs -f <svc>-otelcol`. No backend setup or credentials required to run a dev stack.

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

Lives in `infra/secrets/<env>.env` as `TELEMETRY_API_KEY=<value>`. It is a doctrine-injected secret in the [secret manifest](./config_and_secrets.md#doctrine-injected-secrets) — `docex secrets scaffold`/`status` surface it, and the stage/prod [required-secret guard](./config_and_secrets.md#required-secret-guard) enforces it. `dev`/`test` sidecars use the debug exporter and ignore it.

The operator obtains the key from HyperDX (or the configured backend's equivalent) before first stage release per [telemetry_preinfra.md](../preinfra/telemetry_preinfra.md).

### Resource Allocation

Each sidecar is doctrine-allocated:

- **CPU**: 0.1 vCPU
- **Memory**: 128 MB

These are doctrine-prescribed defaults; not project-tunable in v1. The sizing is conservative for the v1 pipeline (otlp → batch → exporter) and assumes single-digit signals-per-second per service. Projects emitting at much higher rates may experience batch-processor drops; the v1 pipeline buffers in memory only (no persistent queue), in keeping with [telemetry.md § Storage Window](../telemetry.md#storage-window)'s treatment of telemetry signals as near-ephemeral.

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
| Backend unreachable at runtime | Sidecar logs export errors; in-memory queue fills; oldest signals dropped on overflow | `docker compose logs <svc>-otelcol` (fixed) / CloudWatch task logs (elastic); backend's own health page |
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

For each core service `<svc>`, `docex compile` emits an additional compose service named `<svc>-otelcol`. The sidecar shares the core service's network namespace via compose's `network_mode: "service:<svc>"` — it does not declare its own `networks:` (mutually exclusive with `network_mode`).

Netns sharing on fixed deliberately mirrors the ECS task-netns sharing on elastic — the two foundations end up with identical loopback semantics, so `OTEL_EXPORTER_OTLP_ENDPOINT` resolves to the same value on both. It also sidesteps the edge case of a core service that only joins the `web` network: the sidecar inherits whatever networks the core service joins, with no per-network choice for `docex` to make.

Emitted compose entry shape (illustrative — actual emit lives in `src/docex/emit/compose.py`):

```yaml
<svc>-otelcol:
  image: otel/opentelemetry-collector:<digest>
  container_name: ${project}-${env}-<svc>-otelcol
  command: ["--config=/etc/otelcol/config.yaml"]
  network_mode: "service:<svc>"
  configs:
    - source: otelcol_config
      target: /etc/otelcol/config.yaml
  environment:
    OBSERVABILITY_BACKEND_URL: ${OBSERVABILITY_BACKEND_URL:-}
    TELEMETRY_API_KEY: ${TELEMETRY_API_KEY:-}
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

Standard compose `environment:` block on the sidecar reading from the rendered `.env` per [release.md § Fixed Foundation: Ansible](./release.md#fixed-foundation-ansible).

The `${VAR:-}` syntax (with empty default) means the variables are optional from compose's perspective — `dev.env` and `test.env` don't need to declare them. In `stage.env` and `prod.env` they must be set; if omitted, the sidecar starts but otelcol's `${env:VAR}` substitution in the config fails at startup with a clear error.

### Healthcheck and Startup Ordering

The sidecar runs otelcol's `health_check` extension on `127.0.0.1:13133`, but **no compose `healthcheck:` block is emitted** — the `otel/opentelemetry-collector` image is built `FROM scratch` and carries no probe tool (no wget, curl, or shell), so a container-level healthcheck could never succeed; emitting one would leave compose reporting the sidecar as `health: starting` forever while it actually works fine. The extension stays available for in-band diagnostics from inside the shared netns (e.g. curling `localhost:13133` from the core service's container).

The core service does **not** declare a `depends_on` healthcheck on `<svc>-otelcol`. With `network_mode: "service:<svc>"`, compose enforces an implicit dependency in the *opposite* direction — the sidecar can't start until the core service's container exists (its netns has to be there to share). The core service therefore starts first; the sidecar attaches to its netns immediately after; both processes initialize concurrently.

This means the core service does not have a guaranteed sidecar at `t=0`. The OTel SDK's default batch/retry behavior covers the brief startup window — sidecar readiness is typically 1–2 seconds, well within the SDK's queue tolerance (default queue size of 2048 spans, 5-second flush interval). Signals emitted during the startup window are buffered, not dropped.

---

## Elastic

ECS task-level mechanics. Sidecar emitted as a paired container in the same task definition.

Note: `dev` and `test` are always fixed per [shape.md § Shape and Environment](../shape.md#shape-and-environment), so the elastic mechanics below apply only to `stage` and `prod`. The exporter is always `otlphttp`; both `OBSERVABILITY_BACKEND_URL` and `TELEMETRY_API_KEY` are always required on elastic compiles.

### Sidecar as Paired Task Container

For each core service `<svc>`, the ECS task definition contains two containers: the application container and an `<svc>-otelcol` container. They share the task netns. There is no separate ECS service for the sidecar.

Emitted task-definition container fragment for the sidecar (illustrative):

```hcl
container_definitions = jsonencode([
  {
    name      = "<svc>"
    # ... core service definition ...
    dependsOn = [
      { containerName = "<svc>-otelcol", condition = "START" }
    ]
  },
  {
    name      = "<svc>-otelcol"
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
1. Keeps the secret-flow surface narrow — SSM is reserved for actual secrets per [config_and_secrets.md](./config_and_secrets.md).
2. The config diff is visible in the same HCL the operator already reviews, not in a separate fetch path.

### Secret Delivery

`TELEMETRY_API_KEY` is delivered via an ECS `secrets[]` entry on the sidecar container, sourcing from `/<project>/<env>/TELEMETRY_API_KEY` in SSM Parameter Store, per [release.md § Elastic Foundation: OpenTofu](./release.md#elastic-foundation-opentofu) and [config_and_secrets.md](./config_and_secrets.md). `docex release` pushes the SSM parameter from `infra/secrets/<env>.env` on every deploy.

`OBSERVABILITY_BACKEND_URL` is delivered as a regular `environment[]` entry — the URL is not sensitive.

### Container Dependencies and Essentiality

The sidecar is declared `essential: false` — a sidecar crash doesn't kill the task. The core service stays serving; the SDK harmlessly buffers signals to a dead local port until they're dropped per [Failure Modes](#failure-modes).

The core service declares:

```hcl
dependsOn = [
  { containerName = "<svc>-otelcol", condition = "START" }
]
```

so the sidecar container is started before the core service. The condition is `START`, not `HEALTHY` — the collector image is built `FROM scratch` with no probe tool, so an ECS container `healthCheck` (and therefore a `HEALTHY` gate) can never pass and would block the core container indefinitely. As on fixed, the OTel SDK's default batch queue absorbs anything emitted in the brief window between sidecar start and OTLP listening.

### Task-Level Resource Allocation

ECS Fargate tasks declare CPU and memory at the task level; per-container allocations come from the task's totals. The sidecar's 0.1 vCPU / 128 MB allowance adds to whatever the core service requested in `resources:`.

A core service with `resources: { cpu: 1.0, memory: 2GB }` in `infra.yml` produces a Fargate task whose task-level totals are the core service's request plus the sidecar's overhead — `cpu_desired = 1126` (1024 + 102) and `memory_desired = 2176 MiB` (2048 + 128). The sidecar's overhead is doctrine-fixed; the core service always receives exactly what it asked for, with the sidecar's allocation added on top.

The desired totals are not necessarily what the emitted task definition carries. Per [transfer_tables.md § Resources Translation](./transfer_tables.md#resources-translation), the compiler then rounds the desired `(cpu, memory)` up to the smallest Fargate-supported tier that meets or exceeds both dimensions, and surfaces the rounding in compile output. The sidecar overhead is one of several triggers for this rounding — a project that requests non-tier-aligned values itself will round the same way, with or without a sidecar.

**Practical consequence of the sidecar overhead trigger.** A project requesting `cpu: 1.0` produces a desired `1.1 vCPU` after sidecar overhead, which on Fargate rounds up to the `2 vCPU` tier. Projects sensitive to this can request slightly under a Fargate tier boundary (e.g., `cpu: 0.9`) so the sidecar overhead absorbs within the same tier rather than pushing into the next one.

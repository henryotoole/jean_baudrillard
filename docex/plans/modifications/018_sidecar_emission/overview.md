# Mod 018 — Sidecar emission

## Problem

After mod 017 the foundations are in place: every core service gets `OTEL_*` env vars wiring its OTel SDK at `http://localhost:4318`. But there's *nothing listening* on that port. Mod 018 emits the paired sidecar — the actual OTel Collector container that the SDK exports to.

The doctrine fully specifies what to emit in `doctrine/infrastructure/specifics/telemetry_infra.md`:

- **Both foundations:** one `otel/opentelemetry-collector:<digest>` sidecar per core service, sharing the core service's network namespace, running an identical OTLP→batch→exporter pipeline. Only the exporter destination differs by env: `debug` to stdout for dev/test, `otlphttp` to `OBSERVABILITY_BACKEND_URL` for stage/prod.
- **Fixed:** a paired compose service named `<svc>_otelcol`, joining via `network_mode: "service:<svc>"`, sourcing the config from a compose top-level `configs:` entry, environment vars read from compose's `.env`.
- **Elastic:** a second container in the same ECS task definition, sharing the task netns, config embedded as a literal YAML string in `OTEL_CONFIG_YAML` env var, `TELEMETRY_API_KEY` delivered via ECS `secrets[]`, `essential: false`, core container `dependsOn HEALTHY`.

Plus task-level resource accounting on elastic: the sidecar's doctrine-fixed 0.1 vCPU / 128 MiB adds to the core service's requested resources, and the resulting total is rounded up to the next Fargate-supported tier.

## Scope

In scope:

1. **Sidecar config rendering.** A small new module that produces the OTel Collector YAML in two forms — a file path on fixed and a literal string on elastic — switching the exporter by env.
2. **Compose-side sidecar emission.** `emit/compose.py` grows a second pass that walks core services and appends a paired `<svc>_otelcol` compose service, plus the top-level `configs:` block referencing the rendered YAML.
3. **Compile-side `otelcol-config.yaml` writing.** `run_compile` writes one config file per env under `infra/output/<env>/` on fixed (dev/test of any project; stage/prod of fixed-foundation projects). Elastic envs do not write the file — the YAML is embedded into HCL instead.
4. **HCL-side sidecar emission.** `emit/hcl.py::render_task_definition` grows a second container entry alongside the main core-service container. The migration task definition does NOT get a sidecar (one-shot lifecycle, no application-origin signals).
5. **Task-level resource accounting (elastic).** `_resources_to_elastic` (or its helper `fargate_pair`) now factors in the sidecar's 0.1 vCPU / 128 MiB before tier-rounding. Project's `cpu`/`memory` request is preserved at the container level; task-level totals include the sidecar overhead.
6. **Compile-time rounding visibility.** When the sidecar overhead pushes a service into a higher Fargate tier than its declared resources alone would, log the rounding to stdout during `docex compile`. Per [telemetry_infra.md § Resource Allocation](../../../doctrine/infrastructure/specifics/telemetry_infra.md#resource-allocation): "the compiler computes the next supported tier and surfaces the rounding in compile output so the cost implication is visible."
7. **Sidecar image digest constant.** Pinned in `src/docex/__init__.py` (or a near sibling) alongside `ELASTIC_REGION`. Pinning by digest, not tag, per [telemetry_infra.md § Sidecar Image](../../../doctrine/infrastructure/specifics/telemetry_infra.md#sidecar-image).

Out of scope:

- **Reachability probe** (mod 019). No HTTP GET against `observability_backend_url` from `docex check`.
- **Test-project updates** (mod 019). Smoke projects are walked separately.
- **Cutting 0.11.0** (mod 019 completes the advance, then we cut).
- **Backing-service sidecars.** Backing services do not generate application-origin OTel signals (no app SDK); they don't get sidecars.
- **Migration task-def sidecars.** One-shot lifecycle; `migrate.sh` doesn't emit OTel signals.
- **Backing-service container telemetry collection** (e.g., `postgresqlreceiver` on a contrib collector). The doctrine defers this — see [telemetry.md § Planned but NOT Implemented](../../../doctrine/infrastructure/telemetry.md#planned-but-not-implemented). The lean `otel/opentelemetry-collector` distribution is sufficient.

## Design

### Sidecar config rendering

New module: `src/docex/emit/otelcol.py`.

```python
def render_otelcol_config(env: str) -> str:
    """Render the OTel Collector YAML for `env`. Switches the exporter:
    dev/test → debug (stdout); stage/prod → otlphttp."""
```

Returns a YAML string suitable for two consumers:

- `run_compile` writes it to `infra/output/<env>/otelcol-config.yaml` on fixed envs.
- `render_task_definition` embeds it as the value of the sidecar container's `OTEL_CONFIG_YAML` env entry on elastic envs.

The content is identical across both consumers; only the delivery mechanism differs. Construct the YAML deterministically (sorted keys, no random whitespace) so re-running produces byte-identical output.

Per [telemetry_infra.md § Sidecar Configuration YAML](../../../doctrine/infrastructure/specifics/telemetry_infra.md#sidecar-configuration-yaml):

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:4318
processors:
  batch: {}
exporters:
  debug: {verbosity: detailed}             # dev/test
  # OR
  otlphttp:                                # stage/prod
    endpoint: ${env:OBSERVABILITY_BACKEND_URL}
    headers:
      authorization: ${env:TELEMETRY_API_KEY}
extensions:
  health_check:
    endpoint: 127.0.0.1:13133
service:
  extensions: [health_check]
  pipelines:
    traces:  { receivers: [otlp], processors: [batch], exporters: [<chosen>] }
    metrics: { receivers: [otlp], processors: [batch], exporters: [<chosen>] }
    logs:    { receivers: [otlp], processors: [batch], exporters: [<chosen>] }
```

`<chosen>` is `debug` for dev/test and `otlphttp` for stage/prod. The `${env:...}` substitutions are otelcol's own — preserved verbatim, NOT a docex `$[...]` or compose `${VAR}`.

### Sidecar image digest

The doctrine specifies pinning by digest. New constant in `src/docex/__init__.py`:

```python
# OTel Collector sidecar image. Pinned by digest, not tag, so base-layer
# churn does not surface to projects pinned to a given docex_version. The
# digest moves when docex cuts a new version. See
# doctrine/infrastructure/specifics/telemetry_infra.md § Sidecar Image.
OTEL_COLLECTOR_IMAGE = "otel/opentelemetry-collector:0.115.1@sha256:<digest>"
```

The digest is filled with a real one resolved at implementation time (the sub-agent does a `docker manifest inspect` or equivalent against `otel/opentelemetry-collector:0.115.1` to get a current digest). Tag version `0.115.1` is recent-stable.

### Compose emission (fixed)

`emit/compose.py::emit_compose` walks `compiled.services` once today. The change:

1. Build the existing per-service blocks as today.
2. For each core service `<svc>` (filter on `is_core`), construct a paired `<svc>_otelcol` block:
   ```yaml
   <project>_<env>_<svc>_otelcol:
     image: <OTEL_COLLECTOR_IMAGE>
     container_name: <project>_<env>_<svc>_otelcol
     command: ["--config=/etc/otelcol/config.yaml"]
     network_mode: "service:<global_name_of_svc>"
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
         limits: {cpus: "0.1", memory: 128M}
     restart: unless-stopped
     logging: *default-logging
   ```
3. Insert each sidecar block alongside its core service in the `services:` map. Determinism: services are already sorted; sidecars appear immediately after their paired core service (or, simpler, the whole `services:` map is re-sorted at the end — order in compose is fine to be alphabetical).
4. Add a top-level `configs:` section to the compose document:
   ```yaml
   configs:
     otelcol_config:
       file: ./otelcol-config.yaml
   ```
   The `file:` path is relative to the compose file's directory — `infra/output/<env>/otelcol-config.yaml`, which sits beside `docker-compose.yml`. Compose mounts it into each sidecar at `/etc/otelcol/config.yaml`.

Sidecars do NOT receive `svc.env` (the OTEL_* injection). Those vars are app-side (they go on the core service); the sidecar consumes its config from the bind-mounted file and gets `OBSERVABILITY_BACKEND_URL`/`TELEMETRY_API_KEY` directly from compose's `.env`.

### HCL emission (elastic)

`emit/hcl.py::render_task_definition` builds a `container_def` for the core service. The change:

1. After building `container_def`, if `svc.is_core`, build a second `sidecar_def`:
   ```python
   sidecar_def = {
       "name": f"{svc.name}_otelcol",
       "image": OTEL_COLLECTOR_IMAGE,
       "essential": False,
       "command": ["--config=env:OTEL_CONFIG_YAML"],
       "cpu": 102,        # 0.1 vCPU
       "memory": 128,
       "environment": [
           {"name": "OTEL_CONFIG_YAML", "value": render_otelcol_config(env)},
           {"name": "OBSERVABILITY_BACKEND_URL",
            "value": doc.observability_backend_url},
       ],
       "secrets": [
           {"name": "TELEMETRY_API_KEY",
            "valueFrom": str(_ssm_arn_literal(project, env, "TELEMETRY_API_KEY"))},
       ],
       "healthCheck": {
           "command": ["CMD", "wget", "--spider", "-q",
                       "http://localhost:13133"],
           "interval": 10,
           "timeout": 5,
           "retries": 3,
       },
   }
   ```
2. Add a `dependsOn` entry to the core service's container_def:
   ```python
   container_def["dependsOn"] = [
       {"containerName": f"{svc.name}_otelcol", "condition": "HEALTHY"},
   ]
   ```
3. Include the sidecar in `container_definitions = jsonencode([..., sidecar_def])`. The migration task-def gets only the core container, not the sidecar.

The values `project`, `env`, and `doc.observability_backend_url` need to flow into the render — they're not currently part of the `_RenderCtx`. Threading them through requires either (a) extending `_RenderCtx` (preferred — small, surgical) or (b) passing additional params to `render_task_definition`. Implementation goes with (a).

### Resource accounting

`_resources_to_elastic` in `cicl/compile.py` currently:

```python
cpu_units, memory_mib = fargate_pair(res.cpu, res.memory, service_name=name)
```

Modify the call site so that for core services, the request fed to `fargate_pair` includes the sidecar overhead:

```python
if is_core:
    request_cpu = res.cpu + 0.1                       # sidecar adds 0.1 vCPU
    request_mem_mib = _memory_to_mib(res.memory) + 128  # +128 MiB
else:
    request_cpu = res.cpu
    request_mem_mib = _memory_to_mib(res.memory)
```

Then call a slightly extended `fargate_pair` that accepts the memory directly in MiB (skipping its internal `_memory_to_mib` step), or wrap with a parallel public helper. Either is fine — keep the wrapping logic in `_resources_to_elastic` and add a small `fargate_pair_from_mib(...)` to `cicl/fargate.py` that takes MiB-as-int.

After `fargate_pair` returns the rounded values, **detect rounding**: if the requested-cpu-units (`int(round(request_cpu * 1024))`) is less than the returned `cpu_units` (or the requested MiB is less than the returned MiB), the sidecar overhead caused a tier bump. In that case, print to stdout during `run_compile`:

```
note: core service 'web' (env stage): sidecar overhead pushed task to next
      Fargate tier (1024 -> 2048 vCPU units, 2048 -> 4096 MiB). The core
      container still receives the requested 1.0 vCPU / 2GB; the task
      level totals carry the overhead.
```

This is purely informational — no compile failure, no test gate. It surfaces the cost implication per the doctrine.

### Container-level resource decoupling

A subtle point: in current docex, `_resources_to_elastic` returns `cpu`/`memory` that go on the **task definition** as task-level values. The compiler does NOT separately set per-container limits in current code — Fargate auto-divides resources between containers in the same task, and the doctrine's design relies on this.

The core container still gets exactly what the project asked for at runtime (Fargate will not artificially cap it at the requested amount; the task-level cpu is shared, and the sidecar at `cpu: 102` is a soft reservation). Per the doctrine: "the core service always receives exactly what it asked for, with the sidecar's allocation added on top."

Implementation note: only the task-level totals change. No new container-level `cpu`/`memory` fields needed on the core container.

### Compile output layout

`infra/output/<env>/otelcol-config.yaml` joins the per-env output set:

```
infra/output/
├── project/
│   └── main.tf                    (unchanged)
├── dev/
│   ├── docker-compose.yml
│   └── otelcol-config.yaml        (new)
├── test/
│   ├── docker-compose.yml
│   └── otelcol-config.yaml        (new)
├── stage/
│   ├── docker-compose.yml         (fixed) OR
│   ├── otelcol-config.yaml        (fixed only)
│   ├── playbook.yml               (fixed)
│   └── main.tf                    (elastic)
└── prod/                          same shape as stage
```

`run_compile` emits the config file only when the env is fixed-foundation. Elastic envs embed the YAML in HCL and don't write a separate file.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None (operator handles). |
| `docex/plans/core/*.md` | `compiler.md` gets a row for "What the OTel sidecar config looks like" → `emit/otelcol.py`. `release_flow.md` unchanged (release flow shape is identical; sidecar containers come along for the ride inside the existing task defs). |
| `tables/roles/*.yml` | None (structural emit; no transfer-table entries). |
| `src/docex/**` | New: `src/docex/emit/otelcol.py`. Modified: `src/docex/__init__.py` (+ image constant), `src/docex/cicl/compile.py` (+ resource accounting, sidecar overhead), `src/docex/cicl/fargate.py` (+ MiB-input helper), `src/docex/emit/compose.py` (+ sidecar block, top-level configs), `src/docex/emit/hcl.py` (+ sidecar container in task def, dependsOn on core). |
| `tests/**` | New: `tests/unit/test_otelcol.py` (config YAML rendering, both env exporters), `tests/unit/test_compose_sidecar.py` (sidecar block, network_mode, configs section), `tests/unit/test_hcl_sidecar.py` (paired container in task def, dependsOn, secrets[], no sidecar on migration task), `tests/unit/test_resource_accounting.py` (sidecar overhead, tier rounding, rounding notice). Existing tests may need fixture updates if they assert on whole-file YAML/HCL output. |

## Risk and rollback

- **Backward compatibility:** projects compiling under 0.11.0 will see additional containers and a new config file. Projects that pin to <=0.10.0 are unaffected (they don't read this docex version's output). Any project on 0.11.0 needs `observability_backend_url` set (mod 017's requirement) before compile succeeds — the smoke projects are updated in mod 019 alongside the cut.
- **Resource cost:** elastic projects may see Fargate-tier bumps for marginal core-service sizes (e.g., `cpu: 1.0` requests). The doctrine accepts this trade-off and surfaces it in compile output. Operator can resize core services to absorb the overhead within tier bounds.
- **Rollback:** all emit additions are additive in the output trees. Reverting the mod's commit restores prior compile output exactly.

## What this mod does NOT do

- Does not implement the reachability probe (mod 019).
- Does not update the smoke projects (mod 019).
- Does not cut 0.11.0 (mod 019).
- Does not bundle a contrib collector with engine-specific receivers — the lean image is sufficient per doctrine.
- Does not add a sidecar to backing-service ECS task defs.
- Does not add a sidecar to migration task defs.
- Does not parameterize sidecar resources (0.1 vCPU / 128 MiB is doctrine-fixed; project-level tuning would be a future doctrine extension).

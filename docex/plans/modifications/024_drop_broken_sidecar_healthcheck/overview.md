# Mod 024 — Drop sidecar healthcheck; switch elastic `dependsOn HEALTHY` → `START`

## Problem

The doctrine-prescribed sidecar healthcheck (`wget --spider -q http://localhost:13133`) cannot succeed. The `otel/opentelemetry-collector` image is built `FROM scratch` (distroless minimal) — it contains the `otelcol` binary, a TLS cert bundle, and nothing else. No `wget`, no `curl`, no shell. Verified empirically against `otel/opentelemetry-collector:0.153.0@sha256:74edb…458f`:

```
OCI runtime exec failed: exec failed: unable to start container process:
exec: "wget": executable file not found in $PATH
```

Consequences differ by foundation:

- **Fixed**: docker compose runs the failing healthcheck repeatedly. The sidecar stays `health: starting` forever (the start-period timeout never elapses to "unhealthy" because docker's exec error returns a non-zero exit *after* the start period). Sidecar still works — OTLP receiver listens, signals flow, telemetry forwards. The walk verified this with a probe trace returning `HTTP 200 {"partialSuccess":{}}` from HyperDX. Issue is purely cosmetic on this side.

- **Elastic**: ECS uses `dependsOn = [{ containerName = "<svc>_otelcol", condition = "HEALTHY" }]` on the core container. With a never-passing healthcheck, the core container would never start. Real breakage waiting to surface on the elastic walk.

We considered baking a `curl`/`wget` binary into a custom collector image but that defeats the doctrine's "use the lean collector distribution" principle (per `specifics/telemetry_infra.md § Sidecar Image`). The image gives us nothing to probe with, and the OTel project hasn't standardized a built-in health probe. The practical fix: drop the healthcheck on both sides, switch elastic's `dependsOn` from `HEALTHY` to `START`.

The OTel SDK's default batch queue (2048 spans, 5-second flush) absorbs anything emitted during the brief window between sidecar start and OTLP receiver listening — typically sub-second. Mod 018's overview itself already acknowledged this: "Signals emitted during the startup window are buffered, not dropped." That property is what makes `START` safe.

## Scope

In scope:

1. **`emit/compose.py::_sidecar_block`**: drop the `healthcheck:` block on the fixed sidecar.
2. **`emit/hcl.py::render_task_definition`**: drop the `healthCheck:` block on the elastic sidecar container; change the core container's `dependsOn` condition from `HEALTHY` to `START`.
3. **Tests** that asserted on the healthcheck presence — drop those assertions; add a new test asserting the core container's `dependsOn` condition is `START`.

Out of scope:

- Doctrine prose updates. `specifics/telemetry_infra.md § Healthcheck and Startup Ordering` and the elastic-side `dependsOn HEALTHY` text will need to change, but doctrine edits are operator-owned. Mod 024 only updates the docex code; operator handles the matching prose.
- Embedding a custom probe binary in a derived collector image. Out of scope for v1; would require a separate mod and a derived image pipeline.
- Future: when the OTel project ships a built-in `otelcol probe` subcommand (none today), we could revisit.

## Design

### Fixed (`emit/compose.py`)

Drop the `healthcheck:` block from `_sidecar_block`. The sidecar declares no health status to compose — `docker compose ps` shows it as `running` rather than `health: starting`/`healthy`, which is correct since the container itself is up.

```python
# Before (mod 018)
return {
    ...
    "healthcheck": {
        "test": ["CMD", "wget", "--spider", "-q", "http://localhost:13133"],
        "interval": "10s",
        "timeout": "5s",
        "retries": 3,
    },
    ...
}
```

```python
# After (mod 024)
return {
    ...
    # No healthcheck: the otel/opentelemetry-collector image is built
    # FROM scratch and carries no probe tool. Otelcol's health_check
    # extension still listens on 127.0.0.1:13133 — accessible from
    # inside the shared netns for in-band diagnostics. Mod 024.
    ...
}
```

### Elastic (`emit/hcl.py`)

In `render_task_definition`:

- Drop the sidecar's `healthCheck:` block.
- Change the core container's `dependsOn` condition from `HEALTHY` to `START`.

```python
# Before
container_def["dependsOn"] = [
    {"containerName": f"{svc.name}_otelcol", "condition": "HEALTHY"},
]
sidecar_def = {
    ...
    "healthCheck": {
        "command": ["CMD", "wget", "--spider", "-q", "http://localhost:13133"],
        "interval": 10, "timeout": 5, "retries": 3,
    },
}
```

```python
# After (mod 024)
container_def["dependsOn"] = [
    # START rather than HEALTHY because the collector image has no
    # health probe tool. The OTel SDK's startup buffer absorbs any
    # signals emitted in the brief sidecar-start → OTLP-listening
    # window. Mod 024.
    {"containerName": f"{svc.name}_otelcol", "condition": "START"},
]
sidecar_def = {
    ...
    # No healthCheck: image-side limitation, see mod 024.
}
```

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | Out of scope (operator owns). `specifics/telemetry_infra.md § Healthcheck and Startup Ordering` (fixed) and `§ Container Dependencies and Essentiality` (elastic) need to drop the wget prescription and switch the elastic dependency description to `START`. |
| `docex/plans/core/*.md` | None. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `emit/compose.py::_sidecar_block` (drop healthcheck), `emit/hcl.py::render_task_definition` (drop sidecar healthCheck + change dependsOn). |
| `tests/**` | `tests/unit/test_compose_sidecar.py::test_sidecar_healthcheck_on_13133` — drop. `tests/unit/test_hcl_sidecar.py::test_sidecar_healthcheck_on_13133` — drop. Add a new test asserting the elastic core container's `dependsOn` uses `START` (replacement for any existing HEALTHY assertion). |

## Risk and rollback

- **Risk:** very small. Brief startup window where the sidecar isn't yet listening on 4318. SDK batch queue absorbs it.
- **Rollback:** revert. Fixed reverts to cosmetic "starting forever"; elastic reverts to actually broken.

## What this mod does NOT do

- Does not modify the otelcol config itself.
- Does not modify the image pin.
- Does not derive a new collector image with a probe binary.
- Does not touch the `essential: false` setting on the elastic sidecar — that stays.

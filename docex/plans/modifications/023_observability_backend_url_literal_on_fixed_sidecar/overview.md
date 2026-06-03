# Mod 023 — Hardcode `OBSERVABILITY_BACKEND_URL` on the fixed sidecar

## Problem

Mod 018 emitted the fixed sidecar's environment block as:

```yaml
environment:
  OBSERVABILITY_BACKEND_URL: ${OBSERVABILITY_BACKEND_URL:-}
  TELEMETRY_API_KEY: ${TELEMETRY_API_KEY:-}
```

The intent was: read both from compose's `.env`, with `:-` to keep dev/test working without operator-set values. That's correct for `TELEMETRY_API_KEY` (a secret, lives in `<env>.env`). But `OBSERVABILITY_BACKEND_URL` is **not** a secret — it's a top-level `infra.yml` field. The `.env` file (per `release_mechanism.md § Secrets`) only carries secret env vars; it never receives the backend URL. So compose substituted to empty, otelcol's `env:` config provider read empty, and the sidecar crash-looped:

```
Configuration references empty environment variable {"name": "OBSERVABILITY_BACKEND_URL"}
Error: invalid configuration: exporters::otlphttp: at least one endpoint must be specified
```

The elastic side already handled this correctly (mod 018 emits the literal value from `doc.observability_backend_url` directly on the sidecar container's `environment[]`). Fixed needs to be symmetric.

## Scope

In scope:

- `emit/compose.py::_sidecar_block`: emit `OBSERVABILITY_BACKEND_URL` as a literal value from `doc.observability_backend_url`, not as a `${VAR:-}` reference. `TELEMETRY_API_KEY` stays as `${TELEMETRY_API_KEY:-}` (it IS a secret).
- Thread `observability_backend_url` from `CompiledEnv` through to `_sidecar_block`. The `CompiledEnv` already carries the field (mod 018's threading).
- Update the sidecar-environment unit test.

Out of scope:

- Elastic emit. Already correct.
- Any change to how `TELEMETRY_API_KEY` is delivered.
- Any change to the otelcol config rendering. The config still references `${env:OBSERVABILITY_BACKEND_URL}` and `${env:TELEMETRY_API_KEY}`; what changes is HOW those env vars reach the sidecar container.

## Design

Before (mod 018):
```python
"environment": {
    "OBSERVABILITY_BACKEND_URL": "${OBSERVABILITY_BACKEND_URL:-}",
    "TELEMETRY_API_KEY": "${TELEMETRY_API_KEY:-}",
},
```

After:
```python
"environment": {
    "OBSERVABILITY_BACKEND_URL": observability_backend_url,
    "TELEMETRY_API_KEY": "${TELEMETRY_API_KEY:-}",
},
```

Where `observability_backend_url` is passed into `_sidecar_block` from `emit_compose`, which reads it from `compiled.observability_backend_url`.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None. |
| `docex/plans/core/*.md` | None. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `emit/compose.py` — pass `compiled.observability_backend_url` into `_sidecar_block`, emit it as a literal. |
| `tests/**` | `tests/unit/test_compose_sidecar.py::test_sidecar_environment_uses_default_form` updates to assert literal URL, not `${VAR:-}`. |

## Risk and rollback

- **Risk:** none. We're making fixed match elastic's existing behavior. The URL is non-sensitive config; embedding it in the compose file is identical to embedding it in HCL.
- **Rollback:** revert. Sidecar goes back to crash-looping.

## What this mod does NOT do

- Does not change the `TELEMETRY_API_KEY` delivery — it stays as `${TELEMETRY_API_KEY:-}` from `.env`.
- Does not change the otelcol config content.
- Does not change elastic.
- Does not modify dev/test sidecars' env. Even when URL is set, the dev/test sidecars use the `debug` exporter and don't read `OBSERVABILITY_BACKEND_URL`. Embedding the value is harmless on those envs.

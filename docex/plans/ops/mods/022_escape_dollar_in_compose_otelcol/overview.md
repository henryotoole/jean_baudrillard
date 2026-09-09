# Mod 022 — Escape `$` to `$$` in inline otelcol config (compose-side)

## Problem

Mod 021 moved the otelcol config from a separate file mount to inline `configs.content:` in the compose YAML. Compose interpolates `${VAR}` *inside* `content:` too, and the otelcol config carries lines like:

```yaml
exporters:
  otlphttp:
    endpoint: ${env:OBSERVABILITY_BACKEND_URL}
    headers:
      authorization: ${env:TELEMETRY_API_KEY}
```

The `${env:...}` here is otelcol's own env-substitution syntax — it must reach the sidecar verbatim. Compose sees these as its own `${VAR}` form, can't parse them (no env var named `env:OBSERVABILITY_BACKEND_URL` is defined), and aborts:

```
invalid interpolation format for configs.otelcol_config.content.
You may need to escape any $ with another $.
```

Per docker-compose interpolation rules, a literal `$` in a compose value must be written as `$$`. When compose parses the file, `$$` becomes `$`, so the final container-side value is the original `${env:OBSERVABILITY_BACKEND_URL}` that otelcol expects.

This affects only the compose-side delivery. The elastic side (where the same string is delivered via the `OTEL_CONFIG_YAML` env var on the sidecar container) is unaffected — ECS does not interpolate `$` in env var values; the otelcol `env:` config-source provider then does its own substitution at sidecar startup.

## Scope

In scope:

1. **`emit/compose.py`**: replace `$` with `$$` in the rendered otelcol YAML *only when embedding into compose's `configs.content`*. Surgical — leave `render_otelcol_config(env)` untouched (it's also the source for elastic, which must not be double-escaped).
2. **`tests/unit/test_compose_sidecar.py`**: extend `test_compose_has_top_level_configs_block` to assert the doubled form is present in the emitted compose YAML for stage/prod.
3. **`tests/unit/test_hcl_sidecar.py`** (defensive): explicitly assert the elastic side does NOT double-escape — `OTEL_CONFIG_YAML` carries the single-`$` form.

Out of scope:

- `render_otelcol_config` itself. Stays as the single source of truth for the config content. Delivery mechanisms (compose `content:` vs elastic env var) handle their own escaping needs.
- Any change to dev/test compose. They also embed the config, but their exporter is `debug` which has no `${env:...}` references. The replace is still safe (no `$` characters to substitute), and we apply it uniformly.

## Design

In `emit/compose.py`, where the configs block is built:

```python
# Mod 021: render the otelcol config inline.
content = render_otelcol_config(compiled.env)
# Mod 022: escape any literal $ in the rendered YAML to $$, because
# compose interpolates ${VAR} inside `configs.content` and the otelcol
# config carries `${env:VAR}` references that otelcol must see verbatim.
# Doubling `$` → `$$` makes compose pass through a single literal `$`.
content = content.replace("$", "$$")
if any(s.is_core for s in compiled.services.values()):
    body_doc["configs"] = {
        "otelcol_config": {"content": content},
    }
```

Safe-to-apply uniformly because the rendered config has no legitimate single-`$` characters that need preservation. Only the four `${env:...}` references (two in `endpoint:`, two in `headers.authorization:`) — and only on stage/prod, since dev/test use the `debug` exporter with no `${env:...}`. The replace is a no-op on dev/test content.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None. Compose interpolation is a tool-level mechanism, not doctrine. |
| `docex/plans/core/*.md` | None. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `emit/compose.py` — three lines. |
| `tests/**` | `tests/unit/test_compose_sidecar.py` (assert doubled form on stage), `tests/unit/test_hcl_sidecar.py` (assert single-`$` form preserved on elastic). |

## Risk and rollback

- **Risk:** zero. Compose's `$$` → `$` rule is documented and stable. Otelcol receives the same string either way.
- **Rollback:** revert; mods 020/021 stay in place. The deploy host would once again hit the interpolation error.

## What this mod does NOT do

- Does not modify `render_otelcol_config(env)`. Single source of truth for the YAML content.
- Does not change elastic emit.
- Does not change otelcol's behavior in any way.

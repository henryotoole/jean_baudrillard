# Mod 026 — Escape `$` to `$$` in `_hcl_value` strings

## Problem

Same family as mod 022 (compose-side). HCL interprets `${expr}` as its own template interpolation inside string literals, including inside `jsonencode(...)`. The OTEL_CONFIG_YAML value (mod 018) contains otelcol's env-substitution syntax — `${env:OBSERVABILITY_BACKEND_URL}` and `${env:TELEMETRY_API_KEY}` — which HCL chokes on because of the embedded colon:

```
Error: Extra characters after interpolation expression
  on main.tf line 469, in resource "aws_ecs_task_definition" "web":
 469: value = "...${env:OBSERVABILITY_BACKEND_URL}..."
Template interpolation doesn't expect a colon at this location. Did you
intend this to be a literal sequence to be processed as part of another
language? If so, you can escape it by starting with "$${" instead of
just "${".
```

HCL accepts `$$` as a literal `$` escape, exactly like compose. We need the same `$` → `$$` doubling in `_hcl_value`'s string branch that compose got in mod 022.

## Scope

In scope:

1. `src/docex/emit/hcl.py::_hcl_value`: in the string branch (after mod 025's other escapes), also `replace("$", "$$")`.
2. Update tests that assert on the single-`$` form in HCL source:
   - `tests/unit/test_hcl_sidecar.py::test_elastic_otel_config_yaml_uses_single_dollar` — rename to `_uses_escaped_dollar` and flip the assertion to look for `$${...}` in source.
3. CHANGELOG entry under `[Unreleased] § Fixed`.

Out of scope:

- `HCLLiteral`-wrapped values. Those bypass `_hcl_value`'s string branch entirely (line 61-62: `if isinstance(value, HCLLiteral): return str(value)`), so legitimate HCL expressions like `${aws_db_instance.appdb.address}` are unaffected.
- The compose-side escape (mod 022). That's separate; both are required at their respective emit layers.
- Any change to `render_otelcol_config`. Single source of truth stays.

## Design

```python
# Before (with mod 025)
esc = (
    value.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\t", "\\t")
)
```

```python
# After (mod 026)
esc = (
    value.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("$", "$$")     # HCL interpolation escape
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\t", "\\t")
)
```

Order: backslash first (existing), then quote, then `$` doubling, then control chars. The `$$` substitution must happen *before* any other replacement that might introduce a `$` character — none of our other replacements do, so any order after backslash is fine, but placing it next to the other "structural" escapes keeps the intent visible.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None. |
| `docex/plans/core/*.md` | None. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `emit/hcl.py::_hcl_value` (one more `.replace(...)` call). |
| `tests/**` | `tests/unit/test_hcl_sidecar.py` — flip the single-`$` assertion to look for `$${...}` in HCL source (HCL parses back to single-`$` at apply time; otelcol still sees `${env:...}` exactly). |

## What this mod does NOT do

- Does not change `HCLLiteral` handling.
- Does not change `render_otelcol_config`.
- Does not change compose-side behavior (already handled by mod 022).
- Does not change anything user-visible in the OTLP value: the string ECS env var receives at runtime is still `${env:OBSERVABILITY_BACKEND_URL}`; only the HCL source-file form gets the doubled escape.

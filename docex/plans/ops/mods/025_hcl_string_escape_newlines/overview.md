# Mod 025 — Escape `\n`/`\r`/`\t` in HCL string emit

## Problem

`_hcl_value()` in `src/docex/emit/hcl.py` escapes only `\\` and `"` when emitting strings. Until mod 018 introduced `OTEL_CONFIG_YAML` (a multi-line YAML literal embedded as an HCL string), no emitted string carried any other special character — so the gap stayed invisible.

`tofu init` against the emitted `main.tf` fails:

```
Error: Invalid multi-line string
  on main.tf line 715, in resource "aws_ecs_task_definition" "worker":
 715:     metrics: { receivers: [otlp], ...
Quoted strings may not be split over multiple lines. To produce a
multi-line string, either use the \n escape ... or use the "heredoc"
multi-line template syntax.
```

The OTEL_CONFIG_YAML value contains literal newlines (the rendered otelcol config). When wrapped in HCL `"..."` directly, HCL's parser rejects it.

## Scope

In scope:

- `src/docex/emit/hcl.py::_hcl_value`: also escape `\n` → `\\n`, `\r` → `\\r`, `\t` → `\\t` in the string-handling branch. HCL parses `"a\\nb"` as `"a<newline>b"`; jsonencode then serializes that to JSON's `"a\nb"`. Round-trip is correct.
- Test: assert the emitted HCL escapes a newline-bearing string correctly.

Out of scope:

- Heredoc support. Escape-form is sufficient for the OTEL_CONFIG_YAML case and matches how every other HCL emitter handles arbitrary strings.
- Any other character-class. We escape what HCL's string grammar requires; control chars beyond the common three aren't expected in our emit paths.

## Design

```python
# Before
esc = value.replace("\\", "\\\\").replace('"', '\\"')

# After
esc = (
    value.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\t", "\\t")
)
```

Backslash-replace MUST go first (it does already) so subsequent replacements don't double-escape their own backslashes.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None. |
| `docex/plans/core/*.md` | None. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `emit/hcl.py::_hcl_value` (three more `.replace(...)` calls). |
| `tests/**` | `tests/unit/test_hcl_emitter.py` (or wherever the existing _hcl_value tests live) — add a test for newline escape. Also re-verify the mod-022 `test_elastic_otel_config_yaml_uses_single_dollar` still passes (the substring check uses single-`$` so it should). |

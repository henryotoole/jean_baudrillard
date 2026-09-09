# Mod 022 — Implementation steps

Tiny mod, executed directly.

## Step 1 — Escape `$` in `emit/compose.py`'s configs.content

File: `src/docex/emit/compose.py`.

Update the configs block (added by mod 021):

```python
# Before
if any(s.is_core for s in compiled.services.values()):
    body_doc["configs"] = {
        "otelcol_config": {
            "content": render_otelcol_config(compiled.env),
        },
    }
```

```python
# After
if any(s.is_core for s in compiled.services.values()):
    # Compose interpolates ${VAR} inside `configs.content` too. The
    # otelcol config carries `${env:OBSERVABILITY_BACKEND_URL}` /
    # `${env:TELEMETRY_API_KEY}` references that otelcol must see
    # verbatim; doubling `$` → `$$` makes compose pass through a
    # single literal `$` to the sidecar. Elastic is unaffected
    # (ECS does not interpolate `$`). Mod 022.
    content = render_otelcol_config(compiled.env).replace("$", "$$")
    body_doc["configs"] = {
        "otelcol_config": {"content": content},
    }
```

## Step 2 — Test: assert compose side carries `$$`

File: `tests/unit/test_compose_sidecar.py`.

The existing `test_compose_has_top_level_configs_block` tests against `dev` (where the debug exporter has no `$`). Add a new test asserting the stage shape:

```python
def test_compose_configs_content_escapes_dollar_for_stage(tmp_path: Path):
    """Stage/prod otelcol config embeds `${env:...}` references. Compose
    interpolates ${VAR} inside `configs.content` too, so `$` must be
    doubled to `$$` in the emitted compose YAML — compose then passes
    a single literal `$` to the sidecar at parse time. Mod 022."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "stage")
    content = doc["configs"]["otelcol_config"]["content"]
    # PyYAML reads `$$` back to `$$` in the dict value; the file on
    # disk has the doubled form.
    assert "$${env:OBSERVABILITY_BACKEND_URL}" in content
    assert "$${env:TELEMETRY_API_KEY}" in content
    # No naked `${env:...}` references remain.
    assert "${env:OBSERVABILITY_BACKEND_URL}" not in content.replace("$$", "")
    assert "${env:TELEMETRY_API_KEY}" not in content.replace("$$", "")
```

Note: When PyYAML round-trips a string scalar, `$$` survives as `$$` in the in-memory dict — the YAML literal is identical. Only compose's *interpreter* converts `$$` → `$`. So a test reading the emitted YAML back sees `$$`.

## Step 3 — Defensive test: assert elastic stays single-`$`

File: `tests/unit/test_hcl_sidecar.py`.

Add:

```python
def test_elastic_otel_config_yaml_uses_single_dollar(tmp_path: Path):
    """The OTEL_CONFIG_YAML env var on the elastic sidecar must carry
    `${env:...}` with a single `$`. ECS does not interpolate `$`, and
    otelcol's env-config-source provider does its own substitution at
    sidecar startup. Doubling here would deliver a literal `$$` to
    otelcol, which would fail to substitute. Mod 022."""
    # Use the existing elastic fixture compile helper from the file.
    root = _copy_fixture_elastic(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = (root / "infra" / "output" / "stage" / "main.tf").read_text()
    # The OTEL_CONFIG_YAML env entry on the sidecar container has the
    # single-`$` form. Search for the env block's literal substring.
    assert "${env:OBSERVABILITY_BACKEND_URL}" in hcl
    assert "${env:TELEMETRY_API_KEY}" in hcl
    assert "$${env:" not in hcl  # No accidental double-escape.
```

If `_copy_fixture_elastic` doesn't exist as a helper, copy/adapt one from a sibling test in the same file.

## Step 4 — CHANGELOG entry

Append to `[Unreleased] § Fixed`:

```
- Otelcol config's `${env:...}` references in compose's `configs.content`
  are now escaped to `$${env:...}` so docker compose passes them through
  verbatim — without this, compose interprets them as its own variable
  references and aborts with "invalid interpolation format". Elastic
  delivery (via the `OTEL_CONFIG_YAML` env var on the sidecar) is
  unaffected. Surfaced by the 0.11.0 PRE_CUT_CHECKLIST fixed-stage
  release walk after mod 021. Mod 022.
```

## Step 5 — Run tests

```
python3 -m pytest tests/unit -q
```

All must pass.

# Mod 023 — Implementation steps

Small mod, executed directly.

## Step 1 — Thread `observability_backend_url` into `_sidecar_block`

File: `src/docex/emit/compose.py`.

1. Update `_sidecar_block` signature to accept the URL:
   ```python
   def _sidecar_block(
       svc: CompiledService, project: str, env: str,
       observability_backend_url: str,
   ) -> dict[str, Any]:
   ```

2. Inside, emit the URL as a literal value:
   ```python
   "environment": {
       "OBSERVABILITY_BACKEND_URL": observability_backend_url,
       "TELEMETRY_API_KEY": "${TELEMETRY_API_KEY:-}",
   },
   ```
   The TELEMETRY_API_KEY stays as the `${VAR:-}` form — it's a secret, lives in `<env>.env`.

3. Update the caller in `emit_compose` to pass it:
   ```python
   services[sidecar_name] = _sidecar_block(
       svc, compiled.project, compiled.env,
       compiled.observability_backend_url,
   )
   ```

## Step 2 — Update the unit test

File: `tests/unit/test_compose_sidecar.py`. Find `test_sidecar_environment_uses_default_form` and update it:

```python
def test_sidecar_environment_uses_default_form(tmp_path: Path):
    """The sidecar's environment block carries OBSERVABILITY_BACKEND_URL
    as a literal from infra.yml's top-level field (not a secret, so it
    doesn't flow through compose's .env). TELEMETRY_API_KEY stays as
    `${VAR:-}` — it IS a secret. Mod 023."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecar = next(services[k] for k in services if k.endswith("_otelcol"))
    envb = sidecar["environment"]
    # The literal URL from the fixture's infra.yml.
    assert envb["OBSERVABILITY_BACKEND_URL"] == "https://hyperdx.example.com"
    # TELEMETRY_API_KEY stays as ${VAR:-} for compose to interpolate from .env.
    assert envb["TELEMETRY_API_KEY"] == "${TELEMETRY_API_KEY:-}"
```

Check the actual URL in `tests/fixtures/sample_project/infra/infra.yml` to make the literal assertion exact.

## Step 3 — CHANGELOG entry

Append to `[Unreleased] § Fixed`:

```
- Fixed sidecar's `OBSERVABILITY_BACKEND_URL` env var is now emitted as
  a literal value from `infra.yml`'s top-level field, not as a
  `${OBSERVABILITY_BACKEND_URL:-}` reference. The previous form looked
  the var up in compose's `.env`, but that file only carries secrets;
  the URL was always empty at runtime, and otelcol crashed at startup
  with "exporters::otlphttp: at least one endpoint must be specified".
  Symmetric with elastic, which already embedded the literal URL on
  the sidecar's ECS environment[]. `TELEMETRY_API_KEY` continues to
  flow through compose's `.env` (it IS a secret). Surfaced by the
  0.11.0 PRE_CUT_CHECKLIST fixed-stage release walk. Mod 023.
```

## Step 4 — Run tests

```
python3 -m pytest tests/unit -q
```

All must pass.

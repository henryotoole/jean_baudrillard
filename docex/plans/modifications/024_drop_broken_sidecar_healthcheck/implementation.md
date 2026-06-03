# Mod 024 — Implementation steps

Small mod, executed directly.

## Step 1 — Drop healthcheck on fixed (`emit/compose.py`)

File: `src/docex/emit/compose.py`.

In `_sidecar_block`, remove the `"healthcheck": {...}` block entirely. The returned dict drops one top-level key; no other change to the sidecar block.

Update the docstring to note the absence of healthcheck and the reason.

## Step 2 — Drop healthCheck + flip dependsOn on elastic (`emit/hcl.py`)

File: `src/docex/emit/hcl.py`.

In `render_task_definition`:

1. The `container_def["dependsOn"]` block currently emits:
   ```python
   container_def["dependsOn"] = [
       {"containerName": f"{svc.name}_otelcol", "condition": "HEALTHY"},
   ]
   ```
   Change `"HEALTHY"` to `"START"`.

2. The `sidecar_def` carries a `"healthCheck": {...}` entry. Remove it.

Update inline comments to reference mod 024.

## Step 3 — Update tests

File: `tests/unit/test_compose_sidecar.py`.

Find `test_sidecar_healthcheck_on_13133`. Replace its body with an assertion that the sidecar block has *no* `healthcheck` key:

```python
def test_sidecar_has_no_healthcheck(tmp_path: Path):
    """Mod 024: the otel/opentelemetry-collector image is built FROM
    scratch and carries no probe tool. The doctrine-prescribed
    `wget --spider ...` would always fail. The sidecar emit block
    therefore drops the healthcheck entirely; otelcol's `health_check`
    extension on 127.0.0.1:13133 remains available for in-band probes
    from inside the shared netns."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecar = next(services[k] for k in services if k.endswith("_otelcol"))
    assert "healthcheck" not in sidecar
```

File: `tests/unit/test_hcl_sidecar.py`.

Find `test_sidecar_healthcheck_on_13133`. Replace its body with an assertion that the sidecar has no `healthCheck` in the HCL output:

```python
def test_sidecar_has_no_healthcheck(tmp_path: Path):
    """Mod 024: same image-level constraint as on fixed — drop the
    healthCheck block on the elastic sidecar container."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    # The api container_definitions has the sidecar block (we know from
    # other tests); confirm the healthCheck key is absent.
    # Find the sidecar's `name = "api_otelcol"` line and assert there's
    # no `healthCheck` key in its block.
    sidecar_start = api_td.index('name = "api_otelcol"')
    sidecar_end = api_td.index('},', sidecar_start)
    sidecar_slice = api_td[sidecar_start:sidecar_end]
    assert "healthCheck" not in sidecar_slice
```

Also update `test_core_container_dependsOn_sidecar_healthy` (or whatever its name is — the test asserting `dependsOn` on the core container). Rename to `test_core_container_dependsOn_sidecar_start` and change the assertion from `"HEALTHY"` to `"START"`.

## Step 4 — Run tests

```
python3 -m pytest tests/unit -q
```

All must pass.

## Step 5 — CHANGELOG entry

Append to `[Unreleased] § Fixed`:

```
- Sidecar healthcheck dropped on both foundations. The
  `otel/opentelemetry-collector` image is built `FROM scratch` and
  carries no `wget`/`curl`/shell — the doctrine-prescribed
  `wget --spider http://localhost:13133` could never succeed.
  On fixed the failing healthcheck was cosmetic (sidecar stayed
  `health: starting` forever but functioned correctly); on elastic
  the core container's `dependsOn HEALTHY` would have blocked startup
  indefinitely. Elastic `dependsOn` now uses `START` instead. Otelcol's
  `health_check` extension still listens on 127.0.0.1:13133 inside
  the shared netns for in-band probes. Surfaced by the 0.11.0
  PRE_CUT_CHECKLIST fixed-stage release walk and proactively patched
  before the elastic walk. Mod 024.
```

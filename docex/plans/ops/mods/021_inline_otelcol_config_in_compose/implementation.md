# Mod 021 — Implementation steps

Small mod, executed directly. Three files touched.

## Step 1 — Inline the otelcol config in `emit/compose.py`

File: `src/docex/emit/compose.py`.

1. Add an import at the top:
   ```python
   from docex.emit.otelcol import render_otelcol_config
   ```

2. Replace the existing `configs:` block (post mods 018+020) with the inline form:
   ```python
   # Before (mod 020)
   body_doc["configs"] = {
       "otelcol_config": {
           "file": f"./infra/output/{compiled.env}/otelcol-config.yaml",
       },
   }
   ```
   ```python
   # After (mod 021)
   if any(s.is_core for s in compiled.services.values()):
       body_doc["configs"] = {
           "otelcol_config": {
               "content": render_otelcol_config(compiled.env),
           },
       }
   ```
   The `if any(s.is_core ...)` guard is already present in the mod 020 version — preserve it.

The PyYAML dumper will emit the multi-line string as a literal block scalar (`content: |\n  ...`), which is what compose expects for `content:`.

## Step 2 — Stop writing the standalone `otelcol-config.yaml`

File: `src/docex/cicl/compile.py`, function `run_compile`.

Remove these lines (added by mod 018):
```python
# Sidecar config (one per env; all sidecars share it). Mod 018.
# Elastic envs embed the YAML directly into HCL instead.
(env_dir / "otelcol-config.yaml").write_text(
    render_otelcol_config(env)
)
files_written += 1
```

Also remove the now-unused import at the top of the function:
```python
from docex.emit.otelcol import render_otelcol_config
```

(`render_otelcol_config` is still used by `emit/compose.py` and `emit/hcl.py`.)

## Step 3 — Update the unit test

File: `tests/unit/test_compose_sidecar.py`.

Update `test_compose_has_top_level_configs_block` to assert on the inline `content:` shape. Drop the file-existence check (no file exists anymore).

```python
def test_compose_has_top_level_configs_block(tmp_path: Path):
    """A top-level `configs:` map declares `otelcol_config` with the
    rendered otelcol YAML embedded inline via `content:`. Compose v2.23+
    handles the inline form; this avoids the file-path differences
    between local compose runs and ansible-rendered deploy hosts (mod 021)."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    assert "configs" in doc
    cfg = doc["configs"]
    assert "otelcol_config" in cfg
    content = cfg["otelcol_config"]["content"]
    # The config carries the OTLP receiver block and the dev debug exporter.
    assert "receivers:" in content
    assert "127.0.0.1:4318" in content
    assert "debug:" in content
```

If any other tests in the suite assert on the presence of `infra/output/<env>/otelcol-config.yaml`, drop those assertions too. Use `grep -rn "otelcol-config.yaml" tests/` to find them.

## Step 4 — CHANGELOG entry

Append a second bullet to `[Unreleased] § Fixed` (under mod 020's entry):

```
- Compose `configs.otelcol_config` now uses inline `content:` instead of
  a file mount, so the compose file is self-contained and the otelcol
  config arrives on the deploy host alongside everything else compose
  needs. The previous mod-020 file-mount path resolved correctly under
  local `--project-directory` (= project root) but failed on the
  ansible-rendered deploy host where `--project-directory` is the
  compose file's parent directory. Surfaced by the 0.11.0 PRE_CUT_CHECKLIST
  fixed-stage release walk. Mod 021.
```

## Step 5 — Run tests

```
python3 -m pytest tests/unit -q
```

All must pass.

## What this implementation does NOT do

- Does not touch elastic emit (already inline via `OTEL_CONFIG_YAML`).
- Does not modify the ansible playbook.
- Does not change `render_otelcol_config` itself.
- Does not modify the sidecar block's `configs:` reference (`source: otelcol_config`).

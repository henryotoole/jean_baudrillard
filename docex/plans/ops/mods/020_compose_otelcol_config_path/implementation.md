# Mod 020 — Implementation steps

Tiny mod, executed directly without a sub-agent. Two lines of code change.

## Step 1 — Fix the path in `emit_compose`

File: `src/docex/emit/compose.py`.

Find the `body_doc["configs"] = ...` block (added in mod 018) and update the `file:` value to be project-root-relative:

```python
# Before
body_doc["configs"] = {
    "otelcol_config": {"file": "./otelcol-config.yaml"},
}
```

```python
# After
body_doc["configs"] = {
    "otelcol_config": {
        "file": f"./infra/output/{compiled.env}/otelcol-config.yaml",
    },
}
```

## Step 2 — Update the corresponding unit test

File: `tests/unit/test_compose_sidecar.py`.

The test `test_compose_has_top_level_configs_block` currently asserts on `./otelcol-config.yaml`. Update it to the new value. Use the compiled env in the assertion if the test is parametrized; otherwise use the env the test fixture compiles for (typically `dev` or `test`).

## Step 3 — Run tests

```
python3 -m pytest tests/unit -q
```

All tests must pass.

## Step 4 — Update CHANGELOG.md

Append to `[Unreleased]` under `### Fixed` (creating that subhead if absent):

```
### Fixed

- Compose `configs.otelcol_config.file` now points at
  `./infra/output/<env>/otelcol-config.yaml` instead of
  `./otelcol-config.yaml`. The latter resolved against compose's
  `--project-directory` (= project root) rather than the compose file's
  directory, so docker tried to bind-mount a non-existent file at the
  project root. Surfaced by the 0.11.0 PRE_CUT_CHECKLIST walk. Mod 020.
```

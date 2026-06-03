# Mod 020 — Fix otelcol-config.yaml path in compose `configs` block

## Problem

Mod 018 emits compose's top-level `configs:` block as:

```yaml
configs:
  otelcol_config:
    file: ./otelcol-config.yaml
```

Compose resolves `file:` paths against the `--project-directory` flag, which docex sets to the *project root* (`test_projects/fixed/`), not to the compose file's directory (`infra/output/<env>/`). When `docex test` brought up the test stack, docker daemon tried to bind-mount `test_projects/fixed/otelcol-config.yaml` — which doesn't exist — and failed with:

```
Error response from daemon: invalid mount config for type "bind":
bind source path does not exist:
/home/ubuntu/.claude/jean_baudrillard/docex/test_projects/fixed/otelcol-config.yaml
```

The actual file lives at `infra/output/<env>/otelcol-config.yaml` (next to the compose file). Surfaced by the PRE_CUT_CHECKLIST walk against the 0.11.0 candidate image.

## Scope

In scope:

- `emit/compose.py::emit_compose`: change the emitted `configs.otelcol_config.file` to `./infra/output/<env>/otelcol-config.yaml`. This makes the path resolve correctly under `--project-directory` = project root, mirroring how the existing `build.context: ./core/<svc>` paths work.
- Update `tests/unit/test_compose_sidecar.py::test_compose_has_top_level_configs_block` to assert the new path shape.
- No other surface changes. The `run_compile` path that writes the file is already correct (writes to `<env_dir>/otelcol-config.yaml`).

Out of scope:

- Anything elastic-side. Elastic embeds the config in `OTEL_CONFIG_YAML` env var directly — no file mount, no path concern.
- The sidecar container's `configs:` reference (`target: /etc/otelcol/config.yaml`). That's the *in-container* mount point, unaffected by where compose finds the source file.

## Design

One-character class of change. In `src/docex/emit/compose.py::emit_compose`, the existing line:

```python
body_doc["configs"] = {
    "otelcol_config": {"file": "./otelcol-config.yaml"},
}
```

becomes:

```python
body_doc["configs"] = {
    "otelcol_config": {
        "file": f"./infra/output/{compiled.env}/otelcol-config.yaml",
    },
}
```

The `compiled.env` is already in scope.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None. The doctrine doesn't prescribe the path shape (it's a compiler-internal detail). |
| `docex/plans/core/*.md` | None. No flow-level change. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `emit/compose.py` — one path string. |
| `tests/**` | `tests/unit/test_compose_sidecar.py::test_compose_has_top_level_configs_block` updates its assertion. |

## Risk and rollback

- Risk: zero. The new path matches actual disk layout that mod 018 already creates via `run_compile`. The old path matched nothing.
- Rollback: revert the mod.

## What this mod does NOT do

- Does not change anything elastic-side.
- Does not change the in-container mount path (`/etc/otelcol/config.yaml`).
- Does not refactor the configs block into something more sophisticated (per-service mounts, etc.) — out of scope.

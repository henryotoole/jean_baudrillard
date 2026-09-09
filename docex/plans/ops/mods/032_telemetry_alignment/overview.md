# Mod 032 — Telemetry Alignment

Third mod of the [doctrine-shape-and-tier advance](../../advances/shape_overhaul_mod_list.md). Brings docex's telemetry sidecar emission and naming in line with the doctrine's two telemetry-side updates.

## The Doctrine Changes

From [`_advance_doctrine_shape_and_tiers.md § Telemetry sidecar — name changes propagate`](../_advance_doctrine_shape_and_tiers.md):

1. **All `<svc>_otelcol` → `<svc>-otelcol`.** Container name, compose service name, ECS container name, log paths, error-message references. Per [`telemetry_infra.md`](../../../../doctrine/infrastructure/specifics/telemetry_infra.md) (every occurrence) and [`telemetry.md`](../../../../doctrine/infrastructure/telemetry.md).
2. **New doctrine-injected env vars on every core service**, in addition to the pre-existing `PROJECT_VERSION`: `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` (always `http://localhost:4318`), `OTEL_EXPORTER_OTLP_PROTOCOL` (`http/protobuf`), `OTEL_RESOURCE_ATTRIBUTES` (composed). Per [`transfer_tables.md § Per-core-service env (both foundations)`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#per-core-service-env-both-foundations).

## Significant scope reduction — bullet 2 is already done

`src/docex/cicl/compile.py:600–614` already injects all four `OTEL_*` env vars (plus `PROJECT_VERSION`) on every core service:

```python
env_block["PROJECT_VERSION"] = project_version
env_block["OTEL_SERVICE_NAME"] = name
env_block["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
env_block["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
env_block["OTEL_RESOURCE_ATTRIBUTES"] = (
    f"service.namespace={project_name},"
    f"service.version={project_version},"
    f"deployment.environment.name={env}"
)
```

`validate.py:54–61` comment cites these as "mods 011 (PROJECT_VERSION) + 017 (the OTEL_*…)" — they landed in earlier work that I (the design context) wasn't aware of when drafting the advance list. The doctrine bullet about OTEL injection is therefore already satisfied; mod 032 collapses to just the sidecar rename. **No code change for bullet 2** — the OTEL_RESOURCE_ATTRIBUTES format already matches the doctrine spec exactly.

If something is amiss with the existing injection (a misnamed key, a misformatted RESOURCE_ATTRIBUTES string) the implementer will catch it during sanity sweep. Otherwise: leave bullet 2 alone.

## Concrete surface for bullet 1 (the rename)

Mod 030 already partially flipped the sidecar name — the project/env/svc joiners are now hyphenated, with the `_otelcol` suffix explicitly preserved for this mod. Mod 032 finishes the job.

### Sites that still carry `_otelcol` (target of the flip)

**Source:**

- `src/docex/emit/compose.py:179` — `sidecar_name = f"{project}_{env}_{svc.name}_otelcol"` in `_sidecar_block`. **Doubly wrong now** — both the joiners and the suffix use underscores. The `container_name` field of the emitted sidecar service. Should produce `${project}-${env}-${svc.name}-otelcol`.
- `src/docex/emit/compose.py:329` — `sidecar_name = f"{compiled.project}-{compiled.env}-{svc.name}_otelcol"` in `emit_compose`. Mod 030's partial flip: joiners hyphen, suffix still underscore. The compose service key. Same target form as above.
- `src/docex/emit/hcl.py:328` — `{"containerName": f"{svc.name}_otelcol", "condition": "START"}` in the application container's `dependsOn`. The application waits on the sidecar; the dependency target name must match the sidecar container's name.
- `src/docex/emit/hcl.py:331` — `"name": f"{svc.name}_otelcol"` in the sidecar container definition itself (inside the same ECS task definition as the application). These two must agree.

Comments referencing the suffix (no functional change, but worth flipping for consistency):

- `src/docex/emit/compose.py:327` — comment block mentions `The `_otelcol` suffix is tracked separately for mod 032.` Now satisfied — rewrite to current state.

### Sidecar form distinction across foundations

The compose sidecar lives at the project/env scope (container_name = `${project}-${env}-${svc}-otelcol`). The ECS sidecar lives at the task scope (container name = `${svc}-otelcol`, no project/env prefix — ECS scopes containers per task). This matches `telemetry_infra.md`:

- Compose: `container_name: ${project}-${env}-<svc>-otelcol` (one container per service per env, top-level docker namespace).
- ECS: `containerDefinitions[1].name = <svc>-otelcol` (one container per service per task, task-scoped).

Both forms must change `_otelcol` → `-otelcol`. The `${project}-${env}` prefix is correctly absent on the ECS side; the implementer should preserve that asymmetry.

### Tests

- `tests/unit/test_compose_sidecar.py` — every assertion uses `endswith("_otelcol")` or `endswith("-api_otelcol")`. Flip all to `-otelcol` / `-api-otelcol`.
- `tests/unit/test_hcl_sidecar.py` — assertions like `'name = "api_otelcol"'` and `'containerName = "api_otelcol"'`. Flip to `api-otelcol`.

### Documentation

- `docex/plans/core/compiler.md` and `release_flow.md` may mention sidecar names. Check and refresh.
- `tables/README.md` — no sidecar mention expected; check anyway.

## Ramifications

Same as mods 030 and 031: the test-projects committed `infra/output/` will diff (every sidecar name flips), but we don't recompile per the advance-wide deferral.

The implication for deployed projects: any running container named `${project}_${env}_<svc>_otelcol` (under the old form) is now orphaned from compose's perspective. On the next compose-up after this mod ships, compose will create the new `-otelcol` container and the old one will linger until the operator manually removes it. Per operator decision, no in-flight consumers exist, so this is academic. Documented for the changelog.

The ECS side is cleaner — ECS rolls task definitions and the old containers are torn down with the old revision; the new revision has the new name from the start.

## Operator Decisions

1. **OTEL_* injection** — leave alone (already correct). Implementer confirms by inspection but does not touch.
2. **Test surface** — mechanical `s/_otelcol/-otelcol/g` across source + test files.
3. **Core planning docs** — sweep `docex/plans/core/*.md` for sidecar-name references and flip in this mod.

## What This Mod Is NOT

- Not changing the OTEL pipeline shape (receivers, processors, exporters) — already correct per `telemetry_infra.md`.
- Not adding new telemetry env vars — they're already injected.
- Not changing the OTel collector image pin — that's a doctrine-version concern, not an advance one.
- Not changing telemetry preinfra (HyperDX setup) — that's the `docex-preinfra` skill, untouched.

This is the smallest mod of the advance. Tight scope, mostly a `s/_otelcol/-otelcol/g` sweep with a single doubly-wrong literal-joiner site (`compose.py:179`) that mod 030's partial flip missed.

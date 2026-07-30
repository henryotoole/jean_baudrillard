# Mod 017 — Telemetry foundations

## Problem

The doctrine fully specifies application telemetry across `infrastructure/telemetry.md`, `infrastructure/specifics/telemetry_infra.md`, and `infrastructure/prereq/telemetry_preinfra.md`. Every doctrine-shipped project is supposed to:

1. Carry an `observability_backend_url` toplevel field in `infra.yml`.
2. Receive a small set of doctrine-injected OTel env vars on every core service (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_RESOURCE_ATTRIBUTES=service.namespace=...,service.version=...,deployment.environment.name=...`).
3. Have a paired `otel/opentelemetry-collector` sidecar emitted alongside every core service.
4. Surface `TELEMETRY_API_KEY` as a required entry in `stage`/`prod` `secrets/<env>.env`.
5. Have `docex check` probe the backend URL for reachability before merge.

Today `docex` does zero of that. The doctrine is the only artifact aware that telemetry exists. This is the advance-opening mod: get the *foundations* of telemetry into `docex` so subsequent mods can build sidecar emission and the reachability probe on top of them.

## Scope

Mod 017 = the **non-sidecar, non-reachability** half of the telemetry implementation. Mods 018 and 019 cover the sidecar emit and the reachability probe respectively.

In scope:

1. **`infra.yml` field.** Add `observability_backend_url` to `CICLDocument`. Required (since every project compiles `stage` and `prod`); must parse as a URL with `https://` scheme. See [cicl.md § Observability Backend](../../../doctrine/infrastructure/cicl.md#observability-backend).
2. **Per-core-service env var injection.** Inject the four OTel vars on every core service's `env:` block during compile, both foundations. `PROJECT_VERSION` is already injected (mod 011); the new vars sit beside it. See [transfer_tables.md § Per-core-service env](../../../doctrine/infrastructure/specifics/transfer_tables.md#per-core-service-env-both-foundations).
3. **Reserved env keys.** Extend `_validate_no_project_version_conflict` to forbid the OTel keys too — a project that declares `OTEL_SERVICE_NAME` in its own `env:` or `secrets:` is either duplicating doctrine or lying about its identity.
4. **`example.env` for telemetry secret.** Emit `TELEMETRY_API_KEY` as a required entry in the stage/prod portion of `example.env`. Dev/test do not consume the key (per [telemetry_infra.md § Per-Env Exporter Configuration](../../../doctrine/infrastructure/specifics/telemetry_infra.md#per-env-exporter-configuration), the `debug` exporter writes to stdout and doesn't authenticate).
5. **Test fixtures.** `tests/fixtures/sample_project/infra/infra.yml` and `tests/fixtures/sample_project_elastic/infra/infra.yml` both need `observability_backend_url: "https://hyperdx.example.com"` (already-fictitious domain). Without this, every test that touches compile fails.

Out of scope (deferred):

- **Sidecar emission** (Mod 018). No `<svc>_otelcol` compose service. No paired ECS task-def container. No `otelcol-config.yaml` rendering. No `OTEL_CONFIG_YAML` env var.
- **Reachability probe** (Mod 019). No HTTP GET in `docex check`.
- **Resource accounting for sidecar overhead on elastic** (Mod 018). No Fargate-tier rounding for sidecar's 0.1 vCPU / 128 MB.
- **Test-project updates** (Mod 019). The two smoke-test projects' `infra.yml` files will gain `observability_backend_url` and their `stage/prod.env` will gain `TELEMETRY_API_KEY` when we walk them in mod 019. Out of scope here because mod 017 lands no behavioral change that requires either smoke project to recompile — they pin their own `docex_version` and won't bump until 0.11.0 is cut.

## Design

### 1. `observability_backend_url` field on `CICLDocument`

Add to `src/docex/cicl/model.py`:

```python
class CICLDocument(BaseModel):
    ...
    observability_backend_url: str
    ...
```

Required (no `| None`). The pydantic schema enforces presence; a `model_validator` enforces `https://` scheme and basic URL parseability. Compile-time errors here are preferable to runtime errors in sidecar startup — see [transfer_tables.md § Failure-mode contract](../../../doctrine/infrastructure/specifics/transfer_tables.md#failure-mode-contract).

Validation rules:

- Must be a string.
- Must parse via `urllib.parse.urlparse`.
- Must have `scheme == "https"`. `http://` is rejected at compile time per [telemetry.md § Authentication](../../../doctrine/infrastructure/telemetry.md#authentication) — the API key flows in plaintext over HTTPS, never in the clear.
- Must have a non-empty `netloc` (i.e., a host).

A bad URL surfaces as a pydantic `ValidationError` with the field path and a precise reason, attributable to `infra/infra.yml`.

### 2. Per-core-service OTel env var injection

In `src/docex/cicl/compile.py`, where `PROJECT_VERSION` is already injected (around line 533), add four more entries:

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

These are plain strings — no magic refs, no `$[...]` runtime refs, no `HCLLiteral`. They flow through the same compose `environment:` / ECS `environment[]` emit path as `PROJECT_VERSION` does today, so no emit-side changes are needed.

Backing services do not receive these env vars — per [telemetry.md § Application Telemetry Flow](../../../doctrine/infrastructure/telemetry.md#application-telemetry-flow), the application telemetry flow runs from core service code, and backing services run third-party software with no app-side OTel SDK to consume them.

### 3. Reserved env keys

Generalize `_validate_no_project_version_conflict` to a `_validate_reserved_env_keys` that blocks all five doctrine-injected vars. Keep the same rule code prefix (`rule_reserved_env_key_*`) so failure messages remain self-describing. The set:

```python
_RESERVED_CORE_ENV_KEYS = {
    "PROJECT_VERSION",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_RESOURCE_ATTRIBUTES",
}
```

Failure message names which key was reserved and points at the doctrine reference. Same shape as the existing `rule_project_version_reserved` message.

### 4. `TELEMETRY_API_KEY` in `example.env`

`emit_example_env` in `src/docex/emit/secrets.py` currently emits two groups: core-service `secrets:` and backing-service engine `env:` blocks. Add a third doctrinal group — *doctrine-injected secrets* — appearing once at the top of the file (before service-grouped entries) with a header comment:

```
# Doctrine-injected secrets
# The OTel collector sidecar's authentication key against
# observability_backend_url. Required for stage/prod; sidecars in dev/test
# use the `debug` exporter and do not consume this key.
TELEMETRY_API_KEY=
```

The key is the same across all envs (the operator copies `example.env` to each `<env>.env`), but only stage/prod actually consume it. We document the rule in the comment rather than inventing a per-env `example.env`.

### 5. Test fixtures

Two-line update each:

- `tests/fixtures/sample_project/infra/infra.yml`: add `observability_backend_url: "https://hyperdx.example.com"` toplevel.
- `tests/fixtures/sample_project_elastic/infra/infra.yml`: same.

The value is fictitious and doesn't need to resolve — mod 017 doesn't probe it (that's mod 019).

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None in this mod. Operator is handling doctrine edits (the three stale spots — `infrastructure.md`, `cicd.md`, `inception.md` — they're updating directly). |
| `docex/plans/core/*.md` | `compiler.md` gets a one-line entry in "Where to look when changing things" for "How doctrine env vars are injected on core services" → `cicl/compile.py`. `masterplan.md` doesn't change — the command surface is identical. |
| `tables/roles/*.yml` | None. Per [transfer_tables.md § Per-core-service sidecar](../../../doctrine/infrastructure/specifics/transfer_tables.md#per-core-service-sidecar-both-foundations) the sidecar is a "structural emit" — its config lives in docex code, not transfer tables. The OTel env-var injection is similarly invariant per-foundation and per-core-service; it doesn't belong in any role's `defaults:`. |
| `src/docex/**` | `cicl/model.py` (+ field), `cicl/validate.py` (+ reserved-key generalization + URL scheme check is on the model so this is just rule-naming cleanup), `cicl/compile.py` (+ 4 env entries), `emit/secrets.py` (+ doctrinal group). |
| `tests/**` | Unit tests for: URL validation (good + 3 bad shapes), env-var injection presence (fixed + elastic), reserved-key conflict, `example.env` emission. Existing-test backfills: both sample-project fixtures need the new toplevel field. |

## What this mod does NOT do

- Does not emit any sidecar. Compose output gains no `<svc>_otelcol` service; HCL output gains no second container in the task def. Tests assert *only* the env-var injection — not the presence of a paired sidecar (which doesn't exist yet).
- Does not render `otelcol-config.yaml`. That file appears in mod 018.
- Does not touch `docex check`. Reachability probe is mod 019.
- Does not bump the `docex_version` smoke projects pin. They stay on 0.10.0 until 0.11.0 is cut.
- Does not change `PROJECT_VERSION`'s injection (mod 011's existing behavior). It just gains four siblings.

## Risk and rollback

- **Backwards compatibility:** any existing project that compiles today and lacks `observability_backend_url` now fails compile with a clear pydantic error. The two test fixtures cover this in the same commit; downstream projects (the smoke projects + any operator project) will hit this on their next compile after pinning to 0.11.0, which is when mod 019 also updates them.
- **Rollback:** the field is additive on the model, the env vars are additive on each core service, the example.env header is additive. Reverting the mod's commit cleanly restores prior compile output, modulo the env vars (which app code never reads if its OTel SDK isn't wired — silent no-op).

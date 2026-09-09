# Mod 017 — Implementation steps

Goal: land the telemetry foundations described in `overview.md` — `observability_backend_url` field, OTel env-var injection on core services, `TELEMETRY_API_KEY` in `example.env`, generalized reserved-key validator, plus test backfills. No sidecar emit, no reachability probe, no smoke-project updates (those are mods 018 and 019).

The sub-agent executing this gets a fresh context — every step below is self-contained.

## Step 1 — Add `observability_backend_url` to the CICL model

File: `src/docex/cicl/model.py`.

1. At the top of the file, add an import for `urllib.parse`:

   ```python
   from urllib.parse import urlparse
   ```

2. In `CICLDocument`, add a required field placed alongside the other toplevel fields (after `domain_default_service`, before `core_services`):

   ```python
   # The HTTPS URL of the project's observability backend (HyperDX).
   # Sidecars in stage/prod export OTLP signals here. Required on every
   # project — dev/test sidecars don't consume the URL but the field is
   # validated up-front so misconfigurations surface before stage release.
   # See doctrine/infrastructure/cicl.md § Observability Backend.
   observability_backend_url: str
   ```

3. Add a `model_validator(mode="after")` method on `CICLDocument` (or extend an existing one if natural — but a dedicated one is clearer):

   ```python
   @model_validator(mode="after")
   def _validate_observability_backend_url(self) -> "CICLDocument":
       try:
           parsed = urlparse(self.observability_backend_url)
       except Exception as exc:
           raise ValueError(
               f"observability_backend_url is not a parseable URL: "
               f"{self.observability_backend_url!r} ({exc})"
           )
       if parsed.scheme != "https":
           raise ValueError(
               f"observability_backend_url must use the https:// scheme; "
               f"got {self.observability_backend_url!r}. http:// is rejected "
               f"at compile time per doctrine/infrastructure/telemetry.md "
               f"§ Authentication — the API key flows in plaintext over "
               f"HTTPS, never in the clear."
           )
       if not parsed.netloc:
           raise ValueError(
               f"observability_backend_url has no host: "
               f"{self.observability_backend_url!r}"
           )
       return self
   ```

Per-foundation behavior: identical. Whether the project is fixed or elastic, the URL is consumed by sidecars in stage/prod.

## Step 2 — Inject OTel env vars on core services in `compile.py`

File: `src/docex/cicl/compile.py`.

Around line 533 (immediately after `env_block["PROJECT_VERSION"] = project_version`), add four entries:

```python
# Doctrine-injected OTel env vars on every core service. See
# transfer_tables.md § Per-core-service env (both foundations). Same on
# fixed and elastic — the paired sidecar shares the core service's
# network namespace on both, so localhost:4318 is universal.
env_block["OTEL_SERVICE_NAME"] = name
env_block["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
env_block["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
env_block["OTEL_RESOURCE_ATTRIBUTES"] = (
    f"service.namespace={project_name},"
    f"service.version={project_version},"
    f"deployment.environment.name={env}"
)
```

Where `name` is the loop variable (the service's simple name from `infra.yml`) and `env` is the env being compiled. Confirm by reading the surrounding loop — `for name in sorted(doc.all_services())`.

These vars are plain strings: no magic refs, no `$[...]` runtime refs, no `HCLLiteral`. They flow through the existing compose `environment:` / ECS `environment[]` emit path with no other changes.

## Step 3 — Generalize the reserved-key validator

File: `src/docex/cicl/validate.py`.

1. Rename `_validate_no_project_version_conflict` to `_validate_reserved_env_keys`. Update the dispatch call in `validate_document` (line ~73).
2. Replace the inline `"PROJECT_VERSION"` check with a module-level set declared near the other constants:

   ```python
   # Doctrine-injected env vars on every core service. A project may not
   # declare these in its own env: or secrets: blocks — docex sets them
   # at compile time. See transfer_tables.md § Per-core-service env
   # (both foundations). Mods 011 (PROJECT_VERSION) + 017 (the OTEL_*
   # quartet).
   _RESERVED_CORE_ENV_KEYS = frozenset({
       "PROJECT_VERSION",
       "OTEL_SERVICE_NAME",
       "OTEL_EXPORTER_OTLP_ENDPOINT",
       "OTEL_EXPORTER_OTLP_PROTOCOL",
       "OTEL_RESOURCE_ATTRIBUTES",
   })
   ```

3. Refactor the validator body to iterate `_RESERVED_CORE_ENV_KEYS` and report one issue per (service, source-block, reserved-key) collision:

   ```python
   def _validate_reserved_env_keys(
       doc: CICLDocument,
   ) -> list[ValidationIssue]:
       """Doctrine-reserved env keys on core services. A project that
       declares one of these in its own env: or secrets: block is either
       duplicating doctrine or trying to lie about its identity — both
       are mistakes. Mods 011 + 017.
       """
       issues: list[ValidationIssue] = []
       for svc_name, svc in sorted(doc.core_services.items()):
           for source, block in (
               ("env", svc.env or {}),
               ("secrets", svc.secrets or {}),
           ):
               for key in sorted(set(block) & _RESERVED_CORE_ENV_KEYS):
                   issues.append(ValidationIssue(
                       rule="rule_reserved_env_key",
                       message=(
                           f"core service {svc_name!r} declares "
                           f"{key!r} under `{source}:`. This name is "
                           f"doctrine-reserved: docex auto-injects it "
                           f"on every core service. Remove the "
                           f"declaration. See transfer_tables.md § "
                           f"Per-core-service env."
                       ),
                       where=f"core_services.{svc_name}.{source}",
                   ))
       return issues
   ```

4. Update existing tests that assert on `rule_project_version_reserved`. Two known sites in `tests/unit/test_validate.py` (lines 454 and 468): swap the rule code to `rule_reserved_env_key`.

## Step 4 — Emit `TELEMETRY_API_KEY` in `example.env`

File: `src/docex/emit/secrets.py`.

`emit_example_env` builds a `lines: list[str]` list. After the file-header lines (`# Generated by ...`) and *before* the per-service groups (core secrets then backing-service env), insert a doctrine-injected secrets group:

```python
lines.extend([
    "# Doctrine-injected secrets",
    "# The OTel collector sidecar's authentication key against",
    "# observability_backend_url. Required in stage/prod; sidecars in",
    "# dev/test use the `debug` exporter (stdout) and ignore this key.",
    "TELEMETRY_API_KEY=",
    "",
])
```

Set `any_emitted = True` after this insertion so the final "(no backing services declare runtime env vars)" guard line does not fire — the doctrine-injected group is itself a non-empty emission.

## Step 5 — Update sample-project test fixtures

Two files. One-line addition each.

1. `tests/fixtures/sample_project/infra/infra.yml` — after `container_registry: "registry.example.com"`:

   ```yaml
   observability_backend_url: "https://hyperdx.example.com"
   ```

2. `tests/fixtures/sample_project_elastic/infra/infra.yml` — same.

The value is fictitious; mod 017 doesn't probe it.

## Step 6 — Update unit-test fixtures with `observability_backend_url`

Every test that authors a `CICLDocument` (either as YAML or programmatically) must declare the new required field. Known sites:

- `tests/unit/test_validate.py` — four inline YAML fixtures starting with `cicl_version: "1"`. Find each and add `observability_backend_url: "https://obs.example.com"` after the `domain:` line. The `_BASE_FIXED` constant (~line 12) and three other inline docs (~lines 301, 399, 421).
- `tests/unit/test_magic_refs.py` — the programmatic `CICLDocument(...)` call (~line 46). Add `observability_backend_url="https://obs.example.com"` as a keyword.
- `tests/unit/test_pipeline_bootstrap.py` — the inline YAML at line ~230 (`'domain: example.com\n'`). Add the new field.
- `tests/integration/test_compile.py` — two inline YAML fixtures at lines ~229 and ~316. Add the new field.

Sweep with `grep -rn "cicl_version" tests/` to catch any missed.

## Step 7 — Add new unit tests

New test file: `tests/unit/test_telemetry.py`.

Tests to add (all unit-level — mod 017 has zero behavior crossing docker/AWS/git boundaries):

1. **`test_observability_backend_url_required`** — author a minimal valid `CICLDocument` YAML without the field. Pydantic should reject with a "field required" error.

2. **`test_observability_backend_url_must_be_https`** — author with `observability_backend_url: "http://hyperdx.example.com"`. Pydantic should reject with a message naming the `https://` requirement.

3. **`test_observability_backend_url_must_be_parseable`** — author with `observability_backend_url: "::: not a url :::"`. Pydantic should reject with a URL parse error or empty-netloc error.

4. **`test_observability_backend_url_must_have_host`** — author with `observability_backend_url: "https://"`. Pydantic should reject with the no-host message.

5. **`test_observability_backend_url_accepts_valid_https`** — author with a normal `https://` URL. Validation passes.

6. **`test_otel_env_vars_injected_on_every_core_service_fixed`** — compile a minimal fixed project with two core services. Both should have `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_RESOURCE_ATTRIBUTES` in their compiled `env` block. `OTEL_SERVICE_NAME` should equal the simple service name. `OTEL_RESOURCE_ATTRIBUTES` should embed project name, project version, and env name.

7. **`test_otel_env_vars_injected_on_every_core_service_elastic`** — same for elastic. Confirm the values match across foundations (they should be identical).

8. **`test_otel_env_vars_not_injected_on_backing_services`** — compile a project with a backing service. The backing service's compiled body must not contain any `OTEL_*` keys (those are emitted on the *consumer's* env block, not the backing service itself).

9. **`test_reserved_env_keys_in_env_block_rejected`** — for each of the five reserved keys, assert validation reports `rule_reserved_env_key` when a project declares it in `env:`.

10. **`test_reserved_env_keys_in_secrets_block_rejected`** — same for `secrets:`.

11. **`test_example_env_contains_telemetry_api_key`** — call `emit_example_env` on a `CICLDocument` and confirm the rendered file contains `TELEMETRY_API_KEY=` under the doctrine-injected header.

12. **`test_example_env_telemetry_key_position`** — confirm `TELEMETRY_API_KEY=` appears *before* any per-service section in the rendered file.

13. **`test_otel_resource_attributes_format`** — confirm the format is exactly `service.namespace=<proj>,service.version=<ver>,deployment.environment.name=<env>` (comma-separated, no spaces, no trailing comma) for one example.

Helper fixtures may borrow from the patterns in `test_validate.py` and `test_compose_emitter.py`.

## Step 8 — Update `docex/plans/core/compiler.md`

Add one row to the "Where to look when changing things" table:

```
| How doctrine env vars are injected on core services | `src/docex/cicl/compile.py` — the `env_block[...]` assignments after the resolved-magic-ref loop |
```

Place it after the existing "How magic refs are resolved" row to keep the table logically grouped. Brief, one-liner; no separate section needed.

## Step 9 — Update `CHANGELOG.md`

`docex/CHANGELOG.md`. Under `[Unreleased]`, add an entry under an `### Added` subhead (creating it if absent):

```
### Added

- Compile-time telemetry foundations: `observability_backend_url` toplevel
  field in `infra.yml` (required; https-only, validated); `OTEL_SERVICE_NAME`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, and
  `OTEL_RESOURCE_ATTRIBUTES` injected on every core service's env block;
  `TELEMETRY_API_KEY` documented as a doctrine-injected required secret in
  `infra/secrets/example.env`. Mod 017. Sidecar emit and reachability probe
  follow in mods 018/019.

### Changed

- `_validate_no_project_version_conflict` generalized to
  `_validate_reserved_env_keys` covering PROJECT_VERSION + the four
  doctrine-injected OTEL_* keys. Failure rule code renamed from
  `rule_project_version_reserved` to `rule_reserved_env_key`.
```

(If `[Unreleased]` already has Added/Changed groups, append to them rather than duplicating headers.)

## Step 10 — Run the full test suite

From the project root inside the docex container:

```
pytest tests/unit -q
```

All unit tests should pass. Integration tests (`tests/integration/`) likely also need the fixture update (Step 5/6) but should not require additional logic changes — confirm with `pytest tests/integration -q -k "not real"` if a docker daemon isn't available locally; otherwise skip integration here (mods 018/019 + the cut-walk will cover full integration).

If anything fails that isn't covered by the steps above, *stop* and report the failure. Do not invent fixes outside the spec.

## What this implementation does NOT do

- Does not emit any sidecar service in compose output or task definition.
- Does not render `infra/output/<env>/otelcol-config.yaml`.
- Does not embed `OTEL_CONFIG_YAML` into HCL.
- Does not touch `docex check`.
- Does not modify `tables/roles/*.yml` — the OTel injection is a structural emit per `transfer_tables.md § Per-core-service sidecar`.
- Does not modify the smoke-test projects (`docex/test_projects/{fixed,elastic}/`) — those bump in mod 019.
- Does not update any doctrine `.md` files — the operator is handling those edits in parallel.

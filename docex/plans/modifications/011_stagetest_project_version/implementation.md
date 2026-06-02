# Mod 011 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Doctrine-inject `PROJECT_VERSION` (sourced from `project.yml`'s `version:` field) into two surfaces:

1. The stage tester container — alongside the existing `STAGING_URL`.
2. Every **core service's** runtime environment — emitted by the compiler as a per-core-service foundation invariant. Backing services do NOT receive the var.

Remove `APP_VERSION` from the smoke projects' `web/src/root.py`. Update the smoke project stage tests to assert deployed `/health` version matches the env-injected `PROJECT_VERSION`. Add a validation rule that forbids a project from declaring `PROJECT_VERSION` in its own `infra.yml` (doctrine owns the name).

The doctrine edits for this mod are already landed: `cicd.md § Staging Tests` and `tests.md § Staging Tests § Injected environment` (committed with the campaign doctrine commit); `transfer_tables.md § Per-core-service env (both foundations)` (committed separately as part of mod 011's expanded scope). No further doctrine edits.

## Step 1 — Stage tester injection

File: `src/docex/pipeline/stagetest.py`. Around line 99:

```python
env={"STAGING_URL": staging_url},
```

becomes:

```python
env={
    "STAGING_URL": staging_url,
    "PROJECT_VERSION": ctx.project.version,
},
```

That's the entire change in this file.

## Step 2 — Compile-time injection on core services

File: `src/docex/cicl/compile.py`. The compile loop processes each core service's `env:` block around lines 480-512 (the `if isinstance(svc, CoreService):` branch that builds `env_block`). After the project's own env vars and secrets are resolved into `env_block`, but BEFORE `CompiledService(...)` is constructed (around line 521-541), inject `PROJECT_VERSION`:

```python
        if isinstance(svc, CoreService):
            ...existing env / secrets loop...
            # Doctrine-injected: PROJECT_VERSION on every core service.
            # See transfer_tables.md § Per-core-service env (both foundations).
            # Doctrine wins — the validator forbids the project from
            # declaring this key in its own env: or secrets: blocks.
            env_block["PROJECT_VERSION"] = project_version
```

`project_version` is the local variable already bound earlier in `compile_env` (it's used by `_image_ref` at lines 455-456 and 472-473). Confirm it's in scope at this point; if not, source it the same way (`doc.project_version` or the equivalent — match how the existing code does it).

The injection is a plain string assignment. `project_version` is a literal value from `project.yml`, not a magic ref. No `HCLLiteral`, no `$[...]` runtime ref — just a string. The compose and ECS emitters render plain strings unchanged.

Backing services skip this branch entirely (it's inside `if isinstance(svc, CoreService):`), so they don't get the var — matching the doctrine.

## Step 3 — Validation: forbid project-declared `PROJECT_VERSION`

File: `src/docex/cicl/validate.py`. Add a new validator that fails if any core service's `env:` or `secrets:` block declares `PROJECT_VERSION`:

```python
def _validate_no_project_version_conflict(
    doc: CICLDocument,
) -> list[ValidationIssue]:
    """The `PROJECT_VERSION` env var is doctrine-injected on every core
    service (transfer_tables.md § Per-core-service env). A project that
    declares it explicitly in its own env: or secrets: block is either
    duplicating doctrine or trying to lie about its own version — both
    are mistakes. Mod 011.
    """
    issues: list[ValidationIssue] = []
    for svc_name, svc in doc.core_services.items():
        for key_source, block in (("env", svc.env or {}), ("secrets", svc.secrets or {})):
            if "PROJECT_VERSION" in block:
                issues.append(ValidationIssue(
                    code="PROJECT_VERSION_RESERVED",
                    message=(
                        f"core service {svc_name!r} declares "
                        f"`PROJECT_VERSION` under `{key_source}:`. This name "
                        f"is doctrine-reserved: docex auto-injects it on every "
                        f"core service with the value from `project.yml.version`. "
                        f"Remove the declaration. See transfer_tables.md § "
                        f"Per-core-service env."
                    ),
                ))
    return issues
```

Wire into `validate_document` (around line 52) alongside the other `_validate_*` calls:

```python
    issues.extend(_validate_no_project_version_conflict(doc))
```

Use the existing `ValidationIssue` shape — match whatever the other validators in the file use (some use `code=`, some use `rule=`; mirror the rest of the file).

## Step 4 — Unit tests

### 4a. Stage tester injects `PROJECT_VERSION`

File: `tests/unit/test_pipeline_stagetest.py`. Add a new test after `test_stagetest_url_from_domain`:

```python
def test_stagetest_injects_project_version(sample_ctx, fake_docker):
    """PROJECT_VERSION env var should be injected from project.yml.version
    so stage tests can assert the deployed /health version without
    hand-syncing an EXPECTED_VERSION literal. Mod 011."""
    rc = run_stagetest(sample_ctx, fake_docker)
    assert rc == 0
    run_call = next(c for c in fake_docker.calls if c[0] == "run_one_shot")
    env_items = dict(run_call[3])
    assert env_items["PROJECT_VERSION"] == sample_ctx.project.version
```

Update existing tests that examine `env_items` to NOT assert exact dict equality if they do — they should only check the keys they care about. Otherwise the new `PROJECT_VERSION` key will trip them. Inspect `test_stagetest_url_from_domain` and `test_stagetest_override_url` — they currently do `assert env_items["STAGING_URL"] == ...` which is keyed-access and safe; no change needed.

### 4b. Compile-time injection on core services

File: `tests/unit/test_compose_emitter.py` or wherever core-service compose env assertions live. Add a test:

```python
def test_core_service_compose_environment_carries_project_version():
    """Every core service's compose `environment:` block carries
    PROJECT_VERSION sourced from project.yml.version, on every env
    (dev/test/stage/prod). Mod 011."""
    # Use the existing compose-emit test harness — compile a fixture,
    # parse the YAML, assert env on web and worker.
    ...
    assert compose["services"]["web"]["environment"]["PROJECT_VERSION"] == "<fixture version>"
    assert compose["services"]["worker"]["environment"]["PROJECT_VERSION"] == "<fixture version>"
```

And the converse:

```python
def test_backing_service_compose_environment_lacks_project_version():
    """Backing services do NOT receive PROJECT_VERSION — they run
    third-party software that doesn't consume it. Mod 011."""
    ...
    assert "PROJECT_VERSION" not in compose["services"]["db"].get("environment", {})
```

File: `tests/unit/test_hcl_emitter.py` — equivalent assertions on the elastic side. The ECS task-definition's `environment[]` is a list of `{name, value}` entries. Test pattern:

```python
def test_core_service_task_definition_environment_carries_project_version():
    """Every core service's ECS task definition environment[] carries
    PROJECT_VERSION sourced from project.yml.version. Mod 011."""
    ...
    rendered = render_core(...)
    # PROJECT_VERSION appears as a literal value, not an SSM secret.
    assert '"PROJECT_VERSION"' in rendered
    assert '<fixture version>' in rendered
```

Match the existing test_hcl_emitter.py style — substring/regex matches against the rendered HCL string.

### 4c. Validation rule

File: `tests/unit/test_validate.py`. Add a test:

```python
def test_validate_rejects_project_version_in_env():
    """A core service declaring PROJECT_VERSION in its env: block fails
    validation — the name is doctrine-reserved. Mod 011."""
    # Build a CICL doc with web.env = {"PROJECT_VERSION": "1.2.3"}.
    # Run validate_document. Assert PROJECT_VERSION_RESERVED in issue codes.
    ...
```

Match the existing validate-test fixture construction style in the file.

## Step 5 — Smoke project: drop `APP_VERSION`, adopt `PROJECT_VERSION`

Four files — both smoke projects, src + dist:

- `test_projects/fixed/core/web/src/root.py` and `test_projects/fixed/core/web/dist/root.py`
- `test_projects/elastic/core/web/src/root.py` and `test_projects/elastic/core/web/dist/root.py`

Find the line:

```python
VERSION = os.environ.get("APP_VERSION", "0.0.1")
```

Replace with:

```python
VERSION = os.environ["PROJECT_VERSION"]
```

No fallback. If the env var is missing at runtime, the service should fail loudly at startup — that's the right failure mode for a doctrine-injected variable.

Verify after editing: `diff test_projects/fixed/core/web/src/root.py test_projects/fixed/core/web/dist/root.py` is empty. Same for elastic. (The `dist/` files mirror `src/`.)

The smoke `worker` services do NOT use `APP_VERSION` — their `root.py` doesn't reference a version env var. No worker changes.

## Step 6 — Smoke project: stage test assertion

Two files — both smoke projects:

- `test_projects/fixed/infra/stage/tests/test_smoke.py`
- `test_projects/elastic/infra/stage/tests/test_smoke.py`

After the existing `STAGING_URL = os.environ["STAGING_URL"]` line near the top, add:

```python
PROJECT_VERSION = os.environ["PROJECT_VERSION"]
```

In `test_health_endpoint`, change:

```python
def test_health_endpoint() -> None:
    response = httpx.get(f"{STAGING_URL}/health", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "version" in body
```

to:

```python
def test_health_endpoint() -> None:
    response = httpx.get(f"{STAGING_URL}/health", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == PROJECT_VERSION
```

After this edit, both `test_smoke.py` files should be byte-identical to each other (just like the `migrate.sh` files are after mod 009). Verify: `diff test_projects/fixed/infra/stage/tests/test_smoke.py test_projects/elastic/infra/stage/tests/test_smoke.py` must be empty. If they diverge in some other way (header comment naming the project name, etc.), that's an acceptable divergence — surface in the hand-off.

## Step 7 — Smoke project: Dockerfile comment

Two files — both smoke `infra/stage/Dockerfile`. Find the comment line that mentions `$STAGING_URL`:

```dockerfile
# /project and $STAGING_URL exported, and reports the exit code.
```

Change to:

```dockerfile
# /project bind-mounted, $STAGING_URL and $PROJECT_VERSION exported,
# and reports the exit code.
```

Cosmetic; documentation parity with the new doctrine contract.

## Step 8 — Run the suite

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/ -q
python3 -m pytest tests/integration/test_compile.py -q
```

All must pass. Pre-existing tests that compile fixtures and inspect a core service's resolved env block may need updating — they previously expected the env block to contain only project-declared keys, now it will additionally contain `PROJECT_VERSION`. Search for any such test that does a strict equality check on env (rather than keyed access) and update it to either: (a) assert the project-specific keys it cares about; or (b) explicitly include `PROJECT_VERSION` in the expected set.

If any existing integration test for the smoke project's compose/HCL output asserts on the exact list of env vars, update its expectation. Don't suppress the assertion — make it correct.

## Step 9 — Leave everything uncommitted

No git commits. Design-context LLM reviews before commit.

## Hand-off report

In ≤250 words:

- Files changed, grouped by area: docex source / docex tests / smoke project src (fixed inner) / smoke project src (elastic inner).
- Test pass counts. Confirm `test_stagetest_injects_project_version` and the per-foundation invariant tests ran and passed.
- Any pre-existing tests that needed updating to accommodate the new injected env var — how many, and what kind of assertion change (strict-equality → keyed access, etc.).
- Whether `diff test_smoke.py test_smoke.py` came up empty after step 6.
- Any decisions made beyond implementation.md, especially around: (a) where exactly the `project_version` variable was sourced in compile.py; (b) what `ValidationIssue` shape the new validator uses (matches existing file style); (c) test-harness particulars in `test_compose_emitter.py` / `test_hcl_emitter.py`.
- Anything that smelled off — places where the injection wanted to grow beyond core services, or where the validation rule felt either too strict or not strict enough.

## Out of scope

- `${project_version}` as a CICL compile-time substitution variable. Deferred per overview.md — separable future mod.
- New doctrine-injected env vars beyond `PROJECT_VERSION`. The doctrine notes "adding new injected variables is a doctrine change, not a project change" — same gate applies to future additions.
- Backing service env injection. The doctrine explicitly excludes them; they don't have application code that would consume the var.
- Refactoring `_image_ref` or the project-version sourcing in `compile.py` — only the env-block injection needs the variable, and however it's sourced for `_image_ref` already works.

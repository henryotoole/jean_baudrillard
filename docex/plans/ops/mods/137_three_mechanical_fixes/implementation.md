# Mod 137 — Implementation steps

Three independent fixes. Do them in order; each ends with the relevant tests.
Run the suite as `.venv/bin/python -m pytest tests -q` from the `docex/` project
root (`/home/ubuntu/.claude/jean_baudrillard/docex`). NEVER bare `pytest`. Run
`-m integration` ALONE.

All file paths below are relative to the docex project root
`/home/ubuntu/.claude/jean_baudrillard/docex`.

---

## Fix 1 — `object_store`/`minio` pins its image from `version:`

### 1a. Transfer table — `tables/roles/object_store.yml`

In the `minio` engine:

- **Remove** the hardcoded image line from `defaults.fixed`:
  ```yml
  image: "minio/minio:latest"
  ```
- **Add** a `version` field to `minio`'s `fields:` block, mirroring `postgres`
  (fixed arm only — `minio` is `foundation: fixed`). Place it above the existing
  `versioning` field:
  ```yml
  fields:
    version:
      fixed:
        image: "minio/minio:${field_value}"
    versioning:            # unchanged
      # ... existing comment + body unchanged ...
      fixed:
        x-versioning: ${field_value}
  ```

Leave `s3` untouched — it has no image/version.

### 1b. Enforce required `version` — `src/docex/cicl/validate.py`

Add a new validation function that makes a missing `version` a compile error,
**engine-nuanced**: required only where a foundation-matching engine declares a
`version` field. This makes `minio` (fixed) require it and `s3` (elastic) exempt,
structurally — no engine name is special-cased.

1. Add the function (place it near `_validate_role_specific_fields`):

   ```python
   def _validate_required_version(
       doc: CICLDocument, tables: TransferTables
   ) -> list[ValidationIssue]:
       """A backing service must set `version:` when a foundation-matching engine
       pins its image/version from it.

       cicl.md § Service Fields marks `version` required for backing services; the
       requirement is DERIVED from the engine's own `fields:` block, so an engine
       with no `version` field (e.g. `s3`, an S3 bucket with no image) is exempt
       without a name check. Foundation-scoped: an engine that will not compile for
       this project's foundation cannot make `version` required.
       """
       issues: list[ValidationIssue] = []
       for name, svc in sorted(doc.backing_services.items()):
           if svc.role not in tables.by_role:
               continue
           candidates = svc.engine if isinstance(svc.engine, list) else [svc.engine]
           requiring: list[str] = []
           for cand in candidates:
               try:
                   entry = tables.engine(svc.role, cand)
               except Exception:
                   continue
               if entry.supports(doc.foundation) and "version" in (entry.fields or {}):
                   requiring.append(cand)
           if requiring and not svc.version:
               issues.append(ValidationIssue(
                   rule="rule_version_required",
                   message=(
                       f"backing service {name!r} (role {svc.role!r}, engine(s) "
                       f"{requiring!r}) must declare `version:` — the engine pins "
                       f"its image tag from it and an unpinned tag breaks the "
                       f"determinism promise. See cicl.md § Service Fields."
                   ),
                   where=f"backing_services.{name}.version",
               ))
       return issues
   ```

2. Register it in `validate_document` (the `issues.extend(...)` block near the top
   of the file), e.g. right after the `_validate_role_specific_fields` line:
   ```python
   issues.extend(_validate_required_version(doc, tables))
   ```

### 1c. Tests — `tests/unit/test_validate.py`

Add tests (append near the other backing-service tests). The `_doc` /
`_with_service_block` helpers and `_tables()` are already in the file; the base
`appdb` postgres already carries `version: "15"`, so the base doc must stay clean.

- A `minio` object_store WITHOUT `version:` yields exactly one
  `rule_version_required` issue.
- The same object_store WITH `version: "RELEASE.2024-01-01T00-00-00Z"` (or any
  string) is clean.
- An ELASTIC project (`foundation: elastic`) with an object_store `engine: [minio, s3]`
  and NO `version:` is clean — s3 is the foundation-matching engine and is exempt.
  (Build a minimal elastic doc; do not reuse `_BASE_FIXED` verbatim since it is
  fixed. A small inline elastic doc with one web core service and one object_store
  backing service is enough. Elastic web services still need the fields rule 33/32
  require; copy the shape from an existing elastic test if one exists, otherwise
  keep the core service minimal and rely on the object_store being the subject.)
- (Optional but cheap) `test_valid_doc_passes` still passes — the base has no
  object_store, so it is unaffected; no change needed.

Note: `tests/unit/test_uses_relation.py::_STORE_WITH_CORE_REF` declares a
versionless `minio` but its two tests filter issues by the `rule_3_` / `rule_7_`
prefixes, so the new `rule_version_required` issue does not perturb them. Do NOT
edit that file.

### 1d. (Optional) compose-emit sanity

If a fast unit assertion is convenient, confirm a compiled `minio` with
`version: "X"` emits `image: minio/minio:X` and no `:latest`. If the existing
compose-emitter test file has no minio fixture (it does not), skip rather than
build a whole new fixture — the validate tests plus the postgres precedent cover
the mechanism.

---

## Fix 2 — gate contract spec-version minimums — `src/docex/pipeline/check.py`

### 2a. The floor map

Add next to `_FORMAT_EXTENSIONS` (near line 121), carrying the same "doctrine's
table" framing:

```python
# contract format -> minimum (major, minor) spec version. Transcribed from
# contracts.md § Standards. Only the two versioned formats appear: graphql/proto
# are SDL/IDL with no version key, and are excluded by IMPLEMENTED_CONTRACT_FORMATS
# regardless. Same one-consumer rationale as _FORMAT_EXTENSIONS keeps this here.
_FORMAT_MIN_SPEC_VERSION = {
    "openapi": (3, 2),
    "asyncapi": (3, 0),
}
```

### 2b. The gate

Add `_gate_contract_spec_version` next to `_gate_contract_health_path`. It
iterates the already-materialized `list[ContractExpectation]` — no second walk.
Mirror `_gate_contract_health_path`'s YAML/error discipline: report a
malformed/absent version key ONCE, and do not additionally report the consequence
(a below-floor comparison it could not make).

```python
def _gate_contract_spec_version(
    ctx: ProjectContext,
    contracts: list[ContractExpectation],
    report: CheckReport,
) -> None:
    """Each contract declares a spec version at or above the doctrine floor.

    contracts.md § Standards fixes OpenAPI >= 3.2 and AsyncAPI >= 3.0 — each floor
    is what makes a promised api_style implementable (openapi 3.2 -> itemSchema for
    `stream`; asyncapi 3.0 -> reply for `rpc`). The version key each format declares
    in its own root is the same token as the format name (`openapi:` / `asyncapi:`).

    A malformed or absent version key is reported once, as its own defect — NOT
    also reported as a below-floor consequence it cannot compute, matching
    `_gate_contract_health_path`'s handling of unreadable YAML.
    """
    if ctx.infra is None:
        report.add("contract_spec_version", True, "no infra.yml — skipped")
        return

    problems: list[str] = []
    checked = 0
    for exp in contracts:
        floor = _FORMAT_MIN_SPEC_VERSION.get(exp.fmt)
        if floor is None:
            continue
        try:
            doc = yaml.safe_load(exp.path.read_text()) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{exp.path.name}: malformed YAML ({exc})")
            continue
        raw = doc.get(exp.fmt) if isinstance(doc, dict) else None
        parsed = _parse_major_minor(raw)
        if parsed is None:
            problems.append(
                f"{exp.path.name}: no readable {exp.fmt!r} version key "
                f"(found {raw!r}); expected >= {floor[0]}.{floor[1]}"
            )
            continue
        checked += 1
        if parsed < floor:
            problems.append(
                f"{exp.path.name}: declares {exp.fmt} "
                f"{parsed[0]}.{parsed[1]}, but the doctrine floor is "
                f"{floor[0]}.{floor[1]} (contracts.md § Standards)"
            )

    if problems:
        report.add("contract_spec_version", False, "; ".join(problems))
    else:
        report.add(
            "contract_spec_version",
            True,
            (
                f"{checked} contract(s) meet the spec-version floor"
                if checked
                else "no versioned contracts — nothing to check"
            ),
        )
```

Add a small parse helper near the gate (keeps the gate readable and is easy to
unit-test):

```python
def _parse_major_minor(raw: object) -> tuple[int, int] | None:
    """``"3.2.0"`` / ``3.2`` -> ``(3, 2)``; unparseable -> None.

    Accepts a str or a YAML-numeric (an unquoted ``asyncapi: 3.0`` arrives as a
    float). Only major.minor is compared — the patch is irrelevant to the floor.
    """
    if isinstance(raw, (int, float)):
        raw = str(raw)
    if not isinstance(raw, str):
        return None
    parts = raw.strip().split(".")
    if len(parts) < 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None
```

### 2c. Wire it in

In `run_check`, right after the `_gate_contract_health_path` call (near line 806):

```python
_gate_contract_spec_version(worktree_ctx, contracts, report)
```

### 2d. Fixture conformance — REQUIRED, or two tests go red

Two existing full-`run_check` paths read a below-floor contract and will now fail:

1. `tests/fixtures/sample_project/infra/contracts/api.web.rest.openapi.yml` —
   currently `openapi: "3.0.3"`. `tests/integration/test_check_real.py::test_check_real_happy_path`
   (the one asserting `rc == 0`) reads it. **Bump the version line to
   `openapi: "3.2.0"`.** Change ONLY the `openapi:` version token; leave the rest
   of the contract intact (it must still declare `GET /health`).
2. In `tests/integration/test_check_real.py::test_check_real_fails_on_missing_contract_health_path`,
   the inline rewritten contract body (currently `openapi: '3.0.3'`) — **bump to
   `openapi: '3.2.0'`** so this test isolates its intended health-path failure
   rather than also tripping the new gate. It still asserts `rc == 1`.

### 2e. Tests — `tests/unit/test_contract_health_gates.py`

Add tests for `_gate_contract_spec_version` using the existing `_project` /
`_openapi` / `_ASYNCAPI` helpers and a small runner mirroring
`_health_path_result` (build the contracts list via `_gate_contracts`, then call
the new gate, then fetch the `contract_spec_version` result). Import the new gate.

Cover:
- Below-floor OpenAPI (`openapi: "3.0.3"`) fails; the detail names declared 3.0 and
  required 3.2.
- Below-floor AsyncAPI (`asyncapi: "2.6.0"`) fails.
- At-floor OpenAPI `3.2.0` and AsyncAPI `3.0.0` pass.
- Absent/malformed version key reports once (a contract file whose root has no
  `openapi:`/`asyncapi:` key), and does NOT also emit a below-floor complaint for
  the same file.

The existing `_openapi` helper hardcodes `3.0.3` and `_ASYNCAPI` hardcodes `2.6.0`
— either add version-parametrized variants for these tests or inline the contract
bodies in the new tests. Do NOT change `_openapi`/`_ASYNCAPI` themselves if other
tests depend on their current bodies (they exercise the health-path gate, which
does not read the version) — prefer inline bodies or new local helpers to avoid
disturbing existing tests. Verify by running the file after.

Optionally also add a unit test for `_parse_major_minor` directly.

---

## Fix 3 — consolidate the env-subdomain expression onto `compiled.subdomain`

### 3a. Compiler-owned helper — `src/docex/cicl/compile.py`

Add a public helper near `run_compile` (bottom of the file). It reads the carried
`CompiledEnv.subdomain` rather than re-deriving the string, using the same
`compile_env(...)` idiom `orchestrator_health.py`, `release.py`, and `describe/`
already use:

```python
def env_subdomain_for(ctx: Any, env: str) -> str:
    """The env's bare subdomain ``<env>.<project>.<apex_domain>``, taken from the
    compiler-owned ``CompiledEnv.subdomain`` rather than re-derived by hand.

    Consolidates the two former hand-rolled copies (``aggregate._host_for`` and
    ``up.py``) onto the single derivation the compiler owns (``_env_subdomain``).
    """
    compiled = compile_env(
        ctx.infra,
        ctx.transfer_tables,
        env=env,
        project_name=ctx.project.name,
        project_version=ctx.project.version,
    )
    return compiled.subdomain
```

`compile_env` and `Any` are already available in the module.

### 3b. `src/docex/orchestrate/aggregate.py`

Replace `_host_for`:

```python
def _host_for(ctx: ProjectContext, env: str) -> str:
    from docex.cicl.compile import env_subdomain_for
    return env_subdomain_for(ctx, env)
```

Delete the now-unused `from docex.naming import dns_label` local import inside the
old body (it moved out). Confirm `dns_label` is not used elsewhere in this file
(it is not) before removing any module-level import — note the import here was a
FUNCTION-LOCAL import, so just drop those two lines.

### 3c. `src/docex/orchestrate/up.py`

Replace the manual subdomain block (around lines 208-214):

```python
    if ctx.infra is not None:
        from docex.cicl.compile import env_subdomain_for
        subdomain = env_subdomain_for(ctx, env)
    else:
        subdomain = "<unknown>"
```

Then remove the now-unused module-level `from docex.naming import dns_label`
import (line 19) **only if** `dns_label` is used nowhere else in `up.py` — grep
first. (Current grep shows its sole use is the block being replaced, so the import
should be removed.)

### 3d. Re-grep and record the count

After the edits, run from the project root:

```sh
grep -rn 'f"{env}\.' src/docex/ | grep -iv 'env}.env'
```

and specifically the env-subdomain family:

```sh
grep -rn '{env}\.' src/docex/ | grep -i 'apex\|subdomain\|dns_label\|project_seg'
```

Report the final count of the `<env>.<project>.<apex>` derivation. Expected: the
only remaining occurrence is the canonical `compile.py:_env_subdomain` (the two
hand-rolled copies gone). Do NOT predict — report the grepped number.

### 3e. Tests

Add a unit test that `env_subdomain_for(ctx, env)` returns the compiled subdomain,
and/or that `aggregate._host_for` returns `<env>.<dns_label(project)>.<apex>` for a
project whose name has an underscore (proving the DNS-label path survives the
consolidation). A small on-disk project via the existing test helpers, or reuse a
context fixture. Keep it a unit test — no docker/AWS/git.

---

## Final steps

1. Run the full suite from the project root:
   ```sh
   .venv/bin/python -m pytest tests -q
   ```
   Confirm the default count ROSE from the 1204 baseline (new tests added) and
   nothing is red.
2. Run the integration suite ALONE:
   ```sh
   .venv/bin/python -m pytest tests -q -m integration
   ```
   Confirm `21 passed` (unchanged unless you added an integration test — you should
   not have; all new tests are unit).
3. Report both final counts and the fix-3 grep count.

Do NOT update core planning docs or the changelog — that is the reviewer's step
after execution. Do NOT commit — the driving agent owns the mod commits.

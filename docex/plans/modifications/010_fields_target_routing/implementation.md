# Mod 010 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Introduce the `emits:` / `target:` routing mechanism that the doctrine edits in `transfer_tables.md` now describe. After this mod, a field's per-foundation translation can route to any of the engine's declared emit destinations, not just the engine's primary resource. The motivating bug — `health_check_path: /health` silently dropped from the elastic ALB target group — gets fixed as a free fall-out of the mechanism, not as a special case.

Five role tables get `emits:` declarations; one (`web.yml`) additionally restructures its only cross-target field. Source changes touch `cicl/transfer.py`, `cicl/compile.py`, `cicl/validate.py`, `emit/hcl.py`. New unit tests; one new integration test.

## Step 1 — Define the destination-name closed set

File: `src/docex/cicl/transfer.py`.

Near the top of the file (after imports, before `EngineEntry`), add a module-level constant:

```python
# The closed set of emit destinations the compiler recognizes. Engines
# declare a subset of these in their `emits:` block; fields route to
# one of them via `target:`. Adding a destination requires growing the
# routing layer in compile.py + emit/hcl.py — that's the point: new
# destinations are doctrine knowledge embedded in docex source, not a
# free extension surface in the transfer tables.
EMIT_DESTINATIONS: dict[str, frozenset[str]] = {
    "fixed": frozenset({"compose_service"}),
    "elastic": frozenset({
        "task_definition",
        "ecs_service",
        "target_group",
        "rds_instance",
        "elasticache_cluster",
        "s3_bucket",
    }),
}
```

## Step 2 — Extend `EngineEntry`

Same file, in the `EngineEntry` dataclass (around line 40-86):

a. Add the field:

```python
    # Per-foundation ordered list of emit destinations. First entry =
    # default target (where `defaults:` and any field translation
    # without an explicit `target:` lands). Subsequent entries are
    # alternative destinations selectable via `target:` on a field
    # translation. See transfer_tables.md § emits.
    emits: dict[str, list[str]] = field(default_factory=dict)
```

b. Add a method:

```python
    def default_target(self, foundation: str) -> str:
        """Return the engine's default emit destination for ``foundation``.

        Raises TransferTableError if the engine declares no `emits:` for
        that foundation. Every engine that supports a foundation must
        declare a non-empty emits list for it — checked by validation.
        """
        targets = (self.emits or {}).get(foundation) or []
        if not targets:
            raise TransferTableError(
                f"engine {self.engine!r} of role {self.role!r}: no `emits:` "
                f"declared for foundation {foundation!r}. Every engine must "
                f"declare at least one emit destination per supported "
                f"foundation."
            )
        return targets[0]
```

c. **Change** `field_translation`'s return type from `dict | None` to a `(target, body) | None` tuple:

```python
    def field_translation(
        self, field_name: str, foundation: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Resolve a role-specific field translation to (target, body).

        Returns ``None`` if the engine doesn't define the field for this
        foundation. The ``target`` is the field's explicit ``target:``
        when set, otherwise the engine's default target for this
        foundation. The ``body`` is the translation YAML *minus* the
        ``target:`` key.
        """
        f = (self.fields or {}).get(field_name)
        if f is None:
            return None
        per_foundation = f.get(foundation)
        if per_foundation is None:
            return None
        if not isinstance(per_foundation, dict):
            return None
        body = dict(per_foundation)
        target = body.pop("target", None) or self.default_target(foundation)
        return (target, body)
```

## Step 3 — Parse `emits:` from raw YAML

Same file, `_parse_entry` (around line 228-260). Add `emits` extraction:

```python
    raw_emits = raw.get("emits") or {}
    if not isinstance(raw_emits, dict):
        raise TransferTableError(
            f"role {role!r} engine {engine!r}: `emits:` must be a "
            f"mapping of foundation -> list of destinations"
        )
    emits: dict[str, list[str]] = {}
    for fnd, targets in raw_emits.items():
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            raise TransferTableError(
                f"role {role!r} engine {engine!r}: `emits.{fnd}:` must be "
                f"a list of destination name strings"
            )
        emits[fnd] = list(targets)
```

Then add `emits=emits,` to the `EngineEntry(...)` constructor call.

## Step 4 — Declare `emits:` in every role table

Edit each of `tables/roles/*.yml` to add an `emits:` block to every engine entry. Insert immediately after `foundation:` (or `default_port:` where present), before `defaults:`.

### `tables/roles/relational_db.yml`

`postgres`:
```yml
      emits:
        fixed: [compose_service]
        elastic: [rds_instance]
```

### `tables/roles/cache.yml`

`redis`:
```yml
      emits:
        fixed: [compose_service]
        elastic: [elasticache_cluster]
```

### `tables/roles/object_store.yml`

`minio`:
```yml
      emits:
        fixed: [compose_service]
```

`s3`:
```yml
      emits:
        elastic: [s3_bucket]
```

### `tables/roles/web.yml`

`container`:
```yml
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service, target_group]
```

Also restructure `fields.health_check_path.elastic`. It currently reads:

```yml
        health_check_path:
          fixed:
            healthcheck:
              ...
          elastic:
            target_group_health_check:
              path: ${field_value}
              healthy_threshold: 2
              unhealthy_threshold: 3
              interval: 30
              timeout: 5
```

Change the `elastic:` block to:

```yml
          elastic:
            target: target_group
            health_check:
              path: ${field_value}
              healthy_threshold: 2
              unhealthy_threshold: 3
              interval: 30
              timeout: 5
```

The wrapper key changes from `target_group_health_check` to `health_check` (matches the HCL block name on `aws_lb_target_group`).

### `tables/roles/reverse_proxy.yml`

`traefik`:
```yml
      emits:
        fixed: [compose_service]
```

## Step 5 — Route field translations during compile

File: `src/docex/cicl/compile.py`.

### 5a. Extend `CompiledService`

Around line 277, add a field to `CompiledService`:

```python
    # Field translations that route to a non-default emit target.
    # Keyed by destination name (e.g. "target_group"); the value is the
    # resolved translation body. Empty dict when no fields routed
    # off-default. Mod 010.
    target_extras: dict[str, dict[str, Any]] = field(default_factory=dict)
```

### 5b. Restructure the field-translation loop

In the compile loop (around line 396-428), the existing code does two passes that look like:

```python
        # 1. Start with engine defaults for this foundation.
        body: dict[str, Any] = engine.defaults_for(foundation)
        body = _apply_substitution(body, ctx, foundation, resolver, name)

        # 2. Apply each role-specific field declared on the service.
        extras = (svc.model_extra or {})
        for fname, fvalue in sorted(extras.items()):
            ...
            trans = engine.field_translation(fname, foundation)
            if trans is None:
                continue
            field_ctx = {**ctx, "field_value": fvalue}
            block = _apply_substitution(
                trans, field_ctx, foundation, resolver, name, use_local_ctx=True
            )
            body = _deep_merge(body, block)

        # Special-case backing version
        if isinstance(svc, BackingService) and svc.version is not None:
            trans = engine.field_translation("version", foundation)
            if trans is not None:
                ...
                body = _deep_merge(body, block)
```

`field_translation` now returns `(target, body_dict)` instead of a bare dict. Restructure to route each field's translation by target:

```python
        # 1. Start with engine defaults — these always land on the
        #    engine's default target.
        default_target = engine.default_target(foundation)
        body: dict[str, Any] = engine.defaults_for(foundation)
        body = _apply_substitution(body, ctx, foundation, resolver, name)
        target_extras: dict[str, dict[str, Any]] = {}

        def _route_translation(translation_body: dict[str, Any], target: str, fctx: dict[str, Any]) -> None:
            """Substitute then merge into default body or target_extras."""
            nonlocal body
            resolved = _apply_substitution(
                translation_body, fctx, foundation, resolver, name, use_local_ctx=True
            )
            if target == default_target:
                body = _deep_merge(body, resolved)
            else:
                existing = target_extras.get(target, {})
                target_extras[target] = _deep_merge(existing, resolved)

        # 2. Apply each role-specific field declared on the service.
        extras_yaml = (svc.model_extra or {})
        for fname, fvalue in sorted(extras_yaml.items()):
            if fname in ("version", "schema_owned_by"):
                pass
            translated = engine.field_translation(fname, foundation)
            if translated is None:
                continue
            target, translation_body = translated
            _route_translation(translation_body, target, {**ctx, "field_value": fvalue})

        # Special-case: backing services expose `version` as a field but
        # the value lives on the model, not in model_extra.
        if isinstance(svc, BackingService) and svc.version is not None:
            translated = engine.field_translation("version", foundation)
            if translated is not None:
                target, translation_body = translated
                _route_translation(translation_body, target, {**ctx, "field_value": svc.version})
```

### 5c. Pass `target_extras` into `CompiledService`

At the bottom of the loop where `CompiledService(...)` is constructed (search for `CompiledService(`), add `target_extras=target_extras` to the kwargs.

## Step 6 — Emit `health_check` on `aws_lb_target_group`

File: `src/docex/emit/hcl.py`. Around line 386-394:

```python
    if "web" in nets:
        tg_name = apply_policy(f"{svc.global_name}_tg", alb_policy)
        out.append(f'resource "aws_lb_target_group" "{svc.name}" {{')
        out.append(f'  name        = "{tg_name}"')
        out.append(f'  port        = {svc.port or 80}')
        out.append( '  protocol    = "HTTP"')
        out.append( '  target_type = "ip"')
        out.append( '  vpc_id      = data.terraform_remote_state.project.outputs.vpc_id')
        out.append("}")
        out.append("")
```

Extend to consume `svc.target_extras.get("target_group", {})`. After the `vpc_id` line and before the closing `}`, insert the rendering of any contributed sub-blocks:

```python
        tg_extras = svc.target_extras.get("target_group", {})
        hc = tg_extras.get("health_check")
        if hc:
            out.append("  health_check {")
            # path is a string; numeric fields are integers. Preserve
            # the field-translation ordering by iterating keys in their
            # original declaration order (Python dicts are insertion-
            # ordered, so the order matches the table-side translation).
            for k, v in hc.items():
                if isinstance(v, str):
                    out.append(f'    {k} = "{v}"')
                else:
                    out.append(f'    {k} = {v}')
            out.append("  }")
        out.append("}")
        out.append("")
```

If `tg_extras` contains keys other than `health_check`, leave them unhandled for now — they'd be reserved for future mods. (The validator catches unknown destinations; unknown sub-block keys within a known destination aren't a v1 concern.)

## Step 7 — Validation rules

File: `src/docex/cicl/validate.py`.

Add a new validator function `_validate_emits` and wire it into `validate_document`:

```python
def _validate_emits(
    doc: CICLDocument, tables: TransferTables
) -> list[ValidationIssue]:
    """Check every used engine declares `emits:` correctly, and that
    every `target:` reference resolves to a declared destination.

    See transfer_tables.md § Validation rules 11 + 12. Mod 010.
    """
    from docex.cicl.transfer import EMIT_DESTINATIONS

    issues: list[ValidationIssue] = []

    # Foundations the project may compile for: fixed always; elastic
    # if the project's foundation is elastic.
    project_foundations = ["fixed"]
    if doc.foundation == "elastic":
        project_foundations.append("elastic")

    seen_engines: set[tuple[str, str]] = set()
    for svc_name, svc in doc.all_services().items():
        engine = _engine_for_service(svc, tables, doc.foundation)
        if engine is None:
            continue
        key = (engine.role, engine.engine)
        if key in seen_engines:
            # We already audited this engine via another service.
            pass
        seen_engines.add(key)

        # Rule 11: emits.<foundation> exists and is non-empty for every
        # foundation the engine + project supports. Destination names are
        # in the doctrine-recognized closed set.
        for fnd in project_foundations:
            if not engine.supports(fnd):
                continue
            decls = (engine.emits or {}).get(fnd) or []
            if not decls:
                issues.append(ValidationIssue(
                    code="EMITS_MISSING",
                    message=(
                        f"engine {engine.engine!r} of role {engine.role!r} "
                        f"declares no `emits:` for foundation {fnd!r}. Every "
                        f"engine must declare at least one emit destination "
                        f"per supported foundation. See transfer_tables.md § "
                        f"Validation rule 11."
                    ),
                ))
                continue
            for dest in decls:
                if dest not in EMIT_DESTINATIONS.get(fnd, frozenset()):
                    issues.append(ValidationIssue(
                        code="EMITS_UNKNOWN_DESTINATION",
                        message=(
                            f"engine {engine.engine!r} of role "
                            f"{engine.role!r}: `emits.{fnd}` declares "
                            f"unknown destination {dest!r}. Known "
                            f"destinations for {fnd!r}: "
                            f"{sorted(EMIT_DESTINATIONS.get(fnd, []))}."
                        ),
                    ))

        # Rule 12: every field translation's `target:` (if set) names a
        # destination in the engine's `emits.<foundation>`.
        for field_name, per_field in (engine.fields or {}).items():
            if not isinstance(per_field, dict):
                continue
            for fnd, translation in per_field.items():
                if not isinstance(translation, dict):
                    continue
                target = translation.get("target")
                if target is None:
                    continue
                declared = set((engine.emits or {}).get(fnd) or [])
                if target not in declared:
                    issues.append(ValidationIssue(
                        code="FIELD_TARGET_UNDECLARED",
                        message=(
                            f"engine {engine.engine!r} of role "
                            f"{engine.role!r}: field "
                            f"{field_name!r}.{fnd} declares "
                            f"target={target!r} but engine's "
                            f"emits.{fnd}={sorted(declared)!r} does not "
                            f"include it. See transfer_tables.md § "
                            f"Validation rule 12."
                        ),
                    ))

        # Rule 12 — conditional target check: `target: target_group`
        # requires the consuming service to be on the `web` network.
        # The translation is invalid for any service not on `web`.
        if "web" not in (svc.networks or []):
            for field_name, per_field in (engine.fields or {}).items():
                if not isinstance(per_field, dict):
                    continue
                # Check whether the project actually set this field on this service.
                if field_name not in (svc.model_extra or {}):
                    continue
                trans = per_field.get(doc.foundation)
                if not isinstance(trans, dict):
                    continue
                if trans.get("target") == "target_group":
                    issues.append(ValidationIssue(
                        code="FIELD_TARGET_NOT_APPLICABLE",
                        message=(
                            f"service {svc_name!r} declares field "
                            f"{field_name!r} (routes to `target_group`) "
                            f"but is not on the `web` network. Add `web` "
                            f"to its `networks:` list or remove the "
                            f"field. See transfer_tables.md § Validation "
                            f"rule 12."
                        ),
                    ))

    return issues
```

In `validate_document` (around line 52), add the call:

```python
    issues.extend(_validate_emits(doc, tables))
```

If `_engine_for_service` doesn't exist in `validate.py` yet, mirror however the existing `_validate_role_specific_fields` looks up engines — it does the same kind of lookup, copy that pattern.

## Step 8 — Unit tests

File: `tests/unit/test_transfer.py` — add tests for the schema extension. Probably already exists; if not, create it. Add:

```python
def test_engine_default_target_returns_first_emits_entry():
    entry = EngineEntry(
        role="web", engine="container", foundation="both",
        emits={"fixed": ["compose_service"], "elastic": ["task_definition", "ecs_service", "target_group"]},
        naming="ecs",
    )
    assert entry.default_target("fixed") == "compose_service"
    assert entry.default_target("elastic") == "task_definition"


def test_engine_default_target_errors_when_no_emits_declared():
    entry = EngineEntry(role="web", engine="container", foundation="fixed", naming="ecs")
    with pytest.raises(TransferTableError):
        entry.default_target("fixed")


def test_field_translation_returns_target_and_body():
    entry = EngineEntry(
        role="web", engine="container", foundation="both",
        emits={"elastic": ["task_definition", "target_group"]},
        fields={
            "health_check_path": {
                "elastic": {"target": "target_group", "health_check": {"path": "${field_value}"}},
            },
        },
        naming="ecs",
    )
    target, body = entry.field_translation("health_check_path", "elastic")
    assert target == "target_group"
    assert body == {"health_check": {"path": "${field_value}"}}
    # target: key is stripped from the returned body.
    assert "target" not in body


def test_field_translation_defaults_target_to_first_emit():
    entry = EngineEntry(
        role="relational_db", engine="postgres", foundation="both",
        emits={"elastic": ["rds_instance"]},
        fields={"version": {"elastic": {"engine_version": "${field_value}"}}},
        naming="rds",
    )
    target, body = entry.field_translation("version", "elastic")
    assert target == "rds_instance"
    assert body == {"engine_version": "${field_value}"}
```

File: `tests/unit/test_validate.py` — add validation tests:

```python
def test_validate_emits_missing_for_supported_foundation():
    """An engine that supports elastic but declares no elastic emits
    fails validation per rule 11."""
    # Build a CICL doc using an engine with intentionally-missing emits.
    # See existing validate-test patterns for fixture construction.
    ...


def test_validate_field_target_undeclared():
    """A field translation with a `target:` not in the engine's emits
    list fails per rule 12."""
    ...


def test_validate_field_target_not_applicable_when_service_off_web():
    """`target: target_group` requires the consuming service to be on
    the `web` network. A service that declares the field but isn't on
    `web` fails validation."""
    ...
```

Adapt these to the existing fixture-construction style in the file. The point of each is to assert the issue code (`EMITS_MISSING`, `FIELD_TARGET_UNDECLARED`, `FIELD_TARGET_NOT_APPLICABLE`) appears in `validate_document(...)`'s output for the bad case, and is absent for the good case.

File: `tests/unit/test_hcl_emitter.py` — add a test that `aws_lb_target_group` renders a `health_check` block when `target_extras["target_group"]["health_check"]` is present:

```python
def test_aws_lb_target_group_emits_health_check_from_target_extras():
    """When a web-network service carries a `health_check` block under
    `target_extras["target_group"]`, the emitted target group HCL
    includes a nested `health_check { ... }` block with each key."""
    svc = CompiledService(
        name="web", role="web", engine="container", foundation="elastic",
        is_core=True, global_name="proj_stage_web", body={...minimal...},
        networks=["web", "internal"], depends_on=[], port=8080, env={},
        target_extras={"target_group": {
            "health_check": {
                "path": "/health",
                "healthy_threshold": 2,
                "interval": 30,
            },
        }},
    )
    rendered = render_core(svc, ...)  # adapt to the existing test helper
    assert 'resource "aws_lb_target_group" "web"' in rendered
    assert 'health_check {' in rendered
    assert 'path = "/health"' in rendered
    assert 'healthy_threshold = 2' in rendered
    assert 'interval = 30' in rendered
```

Existing `test_hcl_emitter.py` will have helpers for constructing minimal `CompiledService` instances and a list of project-tier inputs. Reuse those.

## Step 9 — Integration test for the smoke project

File: `tests/integration/test_compile.py`. Add a test that compiles the elastic smoke project and asserts the bug fix:

```python
def test_elastic_smoke_compiles_health_check_into_target_group():
    """The elastic smoke project's `web` service declares
    health_check_path. After mod 010 the compiled HCL must include a
    `health_check { path = "/health" }` block on the ALB target group —
    not on the ECS task definition."""
    # Adapt to existing integration-test compile harness.
    ...
    tf = (output_dir / "stage" / "main.tf").read_text()
    # The target group emits the health check.
    assert 'resource "aws_lb_target_group" "web"' in tf
    assert 'health_check {' in tf
    # The task definition does NOT carry a stray target_group_health_check key.
    assert "target_group_health_check" not in tf
```

This test requires the elastic smoke project's `infra.yml` to declare `health_check_path` on `web`. **Verify before running** — if it doesn't, this test will fail for a reason unrelated to mod 010. If `health_check_path` is missing, add it to the smoke project's `infra.yml` *outside* this mod (in a follow-up commit) — don't bundle a smoke-project change into this mod's source diff. Note in the hand-off report.

## Step 10 — Run the suite

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/
python3 -m pytest tests/integration/test_compile.py -v
```

All must pass. If a pre-existing test was implicitly relying on the old `field_translation` return type (`dict | None` instead of tuple), it will fail with an AttributeError or similar. Update its expectations to match the new signature.

## Step 11 — Leave everything uncommitted

Per the mod process, the design-context LLM reviews before commit. No commits. Both the outer `jean_baudrillard` repo and the inner `test_projects` repos may show dirty trees.

## Hand-off report

In ≤250 words:

- Files changed, grouped by area: tables/ (data), src/docex/ (code), tests/ (tests). Note if any smoke-project files were touched (per step 9 caveat).
- Test pass counts. Confirm the new health-check-block emission test ran and passed. Confirm any pre-existing tests that needed signature updates were updated and pass.
- Whether `health_check_path` was already present in `test_projects/elastic/infra/infra.yml` (step 9) and whether you skipped the integration test or had to add the field elsewhere.
- Any decisions made beyond what implementation.md prescribed — especially around `_engine_for_service` lookup helper or `render_core` test harness if they didn't match my guidance.
- Anything that smelled off: places where the existing source structure resisted the change, or where the routing layer wanted to grow beyond what the doctrine prescribes.

## Out of scope

- New emit destinations beyond the closed set in step 1. If a future mod needs `aws_db_subnet_group` or `aws_iam_role`, that's a separate mod.
- Generalizing `target_extras` to support any HCL block name — for v1 only `health_check` is recognized inside `target_group`. Other sub-block names in a future field translation would need the emit code to grow.
- Backwards compatibility for projects pinned to older docex versions. The change is data + code only; old pinned images keep behaving the old way until repinned.
- Updates to `docex/plans/core/compiler.md` — the design-context LLM handles that during drift review if warranted.

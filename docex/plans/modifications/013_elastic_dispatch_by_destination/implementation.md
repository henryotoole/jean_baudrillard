# Mod 013 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Refactor the elastic emit path so dispatch is keyed on the engine's declared emit destinations, not on engine name and not on `is_core`. Replace `render_core` + `render_backing` with six per-destination renderers + a small dispatch table. The change is mostly internal — bundled engines (postgres, redis, s3, web/container) produce the same HCL they did before. The new capability is that project-local container-backing engines (declaring `emits.elastic: [task_definition, ecs_service]`) now render correctly.

The doctrine edits for this mod are already landed in `transfer_tables.md` ("Container-backing services on elastic" section + clarification of the `emits:` paragraph). No further doctrine edits.

## Step 1 — Carry `emits` through to `CompiledService`

File: `src/docex/cicl/compile.py`. Two changes.

### 1a. Add the field to `CompiledService`

The dataclass is at lines 276-304. Add a new field after `target_extras`:

```python
    # Per-foundation list of emit destinations from the engine's `emits:`
    # block, propagated at compile time so the emitter doesn't need a
    # full TransferTables reference. Empty list for foundations the
    # engine doesn't support. Mod 013.
    emits: dict[str, list[str]] = field(default_factory=dict)
```

### 1b. Populate it in `compile_env`

In the loop around lines 527-541 that constructs `CompiledService(...)`, the local variable `engine` is the resolved `EngineEntry`. Pass `emits=dict(engine.emits)` to the constructor. Match the existing argument style.

If the existing call site doesn't expose `engine` in scope at the construction point, source it the same way the rest of compile_env does (probably via `tables.engine_for(...)` earlier in the loop).

## Step 2 — New emit module structure

File: `src/docex/emit/hcl.py`. The file is being substantially restructured. Here's the target layout (top-down):

```python
# (existing imports + module docstring stay)

# Existing helpers stay: _hcl_value, _hcl_block_body, _ssm_arn_literal,
# _ssm_data_name, _RUNTIME_REF_RE.

# DELETED: _ENGINE_TO_RESOURCE (lines 109-114).

# NEW: dispatch context (small dataclass to pass shared state into renderers).

# NEW: per-destination renderers (6 functions).

# NEW: _DESTINATION_RENDERERS dispatch table (after the renderer functions).

# NEW: _destination_applicable(dest, svc) — conditional gate.

# NEW: render_service(svc, ctx) — single entry point, dispatches by emits.

# DELETED: render_backing (lines 145-247).

# DELETED: render_core (lines 250-445).

# Existing: emit_hcl_project (project-tier emit, lines 460-519). Unchanged.

# Modified: emit_hcl — combines services into one ordered list, calls
# render_service via the Jinja template.
```

The numbered steps below produce that structure incrementally.

## Step 3 — Render context dataclass

Add near the top of `hcl.py`, after the imports and constants:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class _RenderCtx:
    """Shared state passed to every per-destination renderer.

    Each renderer takes ``(svc, ctx)``; the ctx carries what the
    bulk-emit loop has already resolved (project name, env name, ALB
    naming policy, ALB listener priority per web service).
    """
    project: str
    env: str
    alb_policy: NamingPolicy
    priorities: dict[str, int]  # service_name -> ALB listener_rule.priority
```

## Step 4 — SSM substitution helper (extracted from old `render_backing`)

The current `render_backing` walks `svc.body` and replaces `$[VAR]` tokens with `data.aws_ssm_parameter.<name>.value` literals, emitting the corresponding `data "aws_ssm_parameter" "..."` blocks. The new design hoists this to `render_service` so any destination renderer sees the already-substituted body.

Extract this logic into a helper:

```python
def _substitute_body_ssm_refs(
    body: dict[str, Any], project: str, env: str, svc_name: str
) -> tuple[dict[str, Any], list[str]]:
    """Walk a service body, translating each ``$[VAR]`` token into an
    HCL reference to a ``data "aws_ssm_parameter"`` block. Return the
    substituted body and the list of data-source HCL strings to emit
    alongside the resources.

    Lifted from the previous ``render_backing`` so multiple
    per-destination renderers see the same substituted body. The
    semantics are unchanged: a value that is a bare ``$[VAR]`` token
    becomes ``data.aws_ssm_parameter.<svc>_<var>.value``, and a data
    block is emitted at ``/<project>/<env>/<VAR>``.
    """
    data_sources: list[str] = []
    seen_keys: set[str] = set()

    def maybe_substitute(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        m = _RUNTIME_REF_RE.fullmatch(value)
        if m is None:
            return value
        key = m.group(1)
        if key not in seen_keys:
            seen_keys.add(key)
            ds_name = _ssm_data_name(svc_name, key)
            data_sources.append(
                f'data "aws_ssm_parameter" "{ds_name}" {{\n'
                f'  name            = "/{project}/{env}/{key}"\n'
                f'  with_decryption = true\n'
                f'}}'
            )
        ds_name = _ssm_data_name(svc_name, key)
        return HCLLiteral(f"data.aws_ssm_parameter.{ds_name}.value")

    return {k: maybe_substitute(v) for k, v in body.items()}, data_sources
```

## Step 5 — `render_task_definition`

Largely the existing `render_core`'s task-def emission, minus the target_group and ecs_service blocks. Sub-emits the migration task definition when applicable.

```python
def render_task_definition(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit one ``aws_ecs_task_definition``, plus a ``_migrate`` variant
    for schema-owning core services. Shared between core services and
    container-backing services.
    """
    body = dict(svc.body)
    cpu = body.get("cpu", "256")
    memory = body.get("memory", "512")
    ephemeral = body.get("ephemeral_storage")

    env_entries: list[dict[str, Any]] = []
    secret_entries: list[dict[str, Any]] = []
    for k in sorted(svc.env):
        v = svc.env[k]
        if isinstance(v, HCLLiteral):
            env_entries.append({"name": k, "value": HCLLiteral(f'"${{{str(v)}}}"')})
            continue
        if isinstance(v, str):
            m = _RUNTIME_REF_RE.fullmatch(v)
            if m is not None:
                secret_entries.append({
                    "name": k,
                    "valueFrom": _ssm_arn_literal(ctx.project, ctx.env, m.group(1)),
                })
                continue
            env_entries.append({"name": k, "value": v})
            continue
        env_entries.append({"name": k, "value": str(v)})

    container_def: dict[str, Any] = {
        "name": svc.name,
        "image": body.get("image", ""),
        "essential": True,
    }
    if svc.port is not None:
        container_def["portMappings"] = [
            {"containerPort": svc.port, "protocol": "tcp"}
        ]
    if env_entries:
        container_def["environment"] = env_entries
    if secret_entries:
        container_def["secrets"] = secret_entries

    project_tag = svc.body.get("tags", {}).get("project", "")
    env_tag = svc.body.get("tags", {}).get("env", "")

    out: list[str] = []
    out.append(f'resource "aws_ecs_task_definition" "{svc.name}" {{')
    out.append(f'  family                   = "{svc.global_name}"')
    out.append( '  requires_compatibilities = ["FARGATE"]')
    out.append( '  network_mode             = "awsvpc"')
    out.append(f'  cpu                      = "{cpu}"')
    out.append(f'  memory                   = "{memory}"')
    out.append( '  execution_role_arn       = data.terraform_remote_state.project.outputs.task_execution_role_arn')
    if ephemeral:
        out.append("  ephemeral_storage {")
        out.append(f"    size_in_gib = {ephemeral.get('size_in_gib', 21)}")
        out.append("  }")
    out.append("  container_definitions = jsonencode([")
    out.append(f"    {_hcl_value(container_def, indent=4)},")
    out.append("  ])")
    out.append(
        f'  tags = {{ project = "{project_tag}", env = "{env_tag}", '
        f'service = "{svc.name}", role = "{svc.role}", '
        f'managed_by = "doctrine" }}'
    )
    out.append("}")

    # Migration task definition (core schema-owners only).
    if svc.is_core and svc.schema_owned_by_db:
        out.append("")
        mig_family = f"{svc.global_name}_migrate"
        mig_container = {
            "name": svc.name,
            "image": body.get("image", ""),
            "essential": True,
            "command": ["/service/migrate.sh"],
        }
        if env_entries:
            mig_container["environment"] = env_entries
        if secret_entries:
            mig_container["secrets"] = secret_entries
        out.append(f'resource "aws_ecs_task_definition" "{svc.name}_migrate" {{')
        out.append(f'  family                   = "{mig_family}"')
        out.append( '  requires_compatibilities = ["FARGATE"]')
        out.append( '  network_mode             = "awsvpc"')
        out.append(f'  cpu                      = "{cpu}"')
        out.append(f'  memory                   = "{memory}"')
        out.append( '  execution_role_arn       = data.terraform_remote_state.project.outputs.task_execution_role_arn')
        out.append("  container_definitions = jsonencode([")
        out.append(f"    {_hcl_value(mig_container, indent=4)},")
        out.append("  ])")
        out.append(
            f'  tags = {{ project = "{project_tag}", env = "{env_tag}", '
            f'service = "{svc.name}", role = "migrate", '
            f'managed_by = "doctrine" }}'
        )
        out.append("}")

    return "\n".join(out)
```

## Step 6 — `render_ecs_service`

```python
def render_ecs_service(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit one ``aws_ecs_service``. References ``aws_lb_target_group``
    if the service also emits ``target_group`` (web-network services).
    """
    nets = list(svc.networks)
    out: list[str] = []
    out.append(f'resource "aws_ecs_service" "{svc.name}" {{')
    out.append(f'  name            = "{svc.global_name}"')
    out.append( '  cluster         = aws_ecs_cluster.cluster.id')
    out.append(f'  task_definition = aws_ecs_task_definition.{svc.name}.arn')
    out.append( '  launch_type     = "FARGATE"')
    out.append( '  desired_count   = 1')
    out.append("  network_configuration {")
    out.append("    subnets         = data.terraform_remote_state.project.outputs.private_subnet_ids")
    sg_refs = ", ".join(f"aws_security_group.{n}.id" for n in sorted(nets))
    out.append(f"    security_groups = [{sg_refs}]")
    out.append("  }")
    if "web" in nets and "target_group" in svc.emits.get("elastic", []):
        out.append("  load_balancer {")
        out.append(f'    target_group_arn = aws_lb_target_group.{svc.name}.arn')
        out.append(f'    container_name   = "{svc.name}"')
        out.append(f'    container_port   = {svc.port or 80}')
        out.append("  }")
    out.append("}")
    return "\n".join(out)
```

## Step 7 — `render_target_group`

```python
def render_target_group(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_lb_target_group`` + ``aws_lb_listener_rule`` for a
    web-network service. The dispatcher only calls this when
    ``web in svc.networks`` (per ``_destination_applicable``).
    """
    tg_name = apply_policy(f"{svc.global_name}_tg", ctx.alb_policy)
    priority = ctx.priorities.get(svc.name, 100)

    out: list[str] = []
    out.append(f'resource "aws_lb_target_group" "{svc.name}" {{')
    out.append(f'  name        = "{tg_name}"')
    out.append(f'  port        = {svc.port or 80}')
    out.append( '  protocol    = "HTTP"')
    out.append( '  target_type = "ip"')
    out.append( '  vpc_id      = data.terraform_remote_state.project.outputs.vpc_id')
    tg_extras = svc.target_extras.get("target_group", {})
    hc = tg_extras.get("health_check")
    if hc:
        out.append("  health_check {")
        for k, v in hc.items():
            if isinstance(v, str):
                out.append(f'    {k} = "{v}"')
            else:
                out.append(f'    {k} = {v}')
        out.append("  }")
    out.append("}")
    out.append("")
    out.append(f'resource "aws_lb_listener_rule" "{svc.name}" {{')
    out.append( '  listener_arn = aws_lb_listener.alb_https.arn')
    out.append(f'  priority     = {priority}')
    out.append( '  action {')
    out.append( '    type             = "forward"')
    out.append(f'    target_group_arn = aws_lb_target_group.{svc.name}.arn')
    out.append( '  }')
    out.append( '  condition {')
    out.append( '    host_header {')
    hosts_hcl = ", ".join(f'"{h}"' for h in svc.web_hosts)
    out.append(f'      values = [{hosts_hcl}]')
    out.append( '    }')
    out.append( '  }')
    out.append("}")
    return "\n".join(out)
```

## Step 8 — `render_rds_instance`

Carry over the existing RDS path from `render_backing` (lines 197-247 of the old file). It already does subnet group + SG attachment correctly. Just hoist into its own function.

```python
def render_rds_instance(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_db_instance`` + ``aws_db_subnet_group`` for an
    RDS-backed backing service (currently: postgres engine).
    """
    body = dict(svc.body)
    # Doctrine invariant: identifier maps to RDS's `identifier` field.
    body["identifier"] = body.pop("identifier", svc.global_name)
    # Strip keys we don't emit on aws_db_instance.
    body.pop("logging", None)
    body.pop("restart", None)
    body.pop("container_name", None)
    body.pop("depends_on", None)
    body.pop("environment", None)

    nets = list(svc.networks)
    body.pop("networks", None)
    if nets:
        body["vpc_security_group_ids"] = [
            HCLLiteral(f"aws_security_group.{n}.id") for n in sorted(nets)
        ]
        body["db_subnet_group_name"] = HCLLiteral(
            f"aws_db_subnet_group.{svc.name}.name"
        )

    body_str = _hcl_block_body(body)
    out: list[str] = []
    out.append(f'resource "aws_db_instance" "{svc.name}" {{')
    out.append(body_str)
    out.append("}")
    if nets:
        out.append("")
        out.append(f'resource "aws_db_subnet_group" "{svc.name}" {{')
        out.append(f'  name       = "{svc.global_name}"')
        out.append("  subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids")
        out.append("}")
    return "\n".join(out)
```

## Step 9 — `render_elasticache_cluster`

Same pattern, for ElastiCache (redis engine).

```python
def render_elasticache_cluster(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_elasticache_cluster`` + ``aws_elasticache_subnet_group``."""
    body = dict(svc.body)
    body["cluster_id"] = body.pop("identifier", svc.global_name)
    body.pop("logging", None)
    body.pop("restart", None)
    body.pop("container_name", None)
    body.pop("depends_on", None)
    body.pop("environment", None)

    nets = list(svc.networks)
    body.pop("networks", None)
    if nets:
        body["security_group_ids"] = [
            HCLLiteral(f"aws_security_group.{n}.id") for n in sorted(nets)
        ]
        body["subnet_group_name"] = HCLLiteral(
            f"aws_elasticache_subnet_group.{svc.name}.name"
        )

    body_str = _hcl_block_body(body)
    out: list[str] = []
    out.append(f'resource "aws_elasticache_cluster" "{svc.name}" {{')
    out.append(body_str)
    out.append("}")
    if nets:
        out.append("")
        out.append(f'resource "aws_elasticache_subnet_group" "{svc.name}" {{')
        out.append(f'  name       = "{svc.global_name}"')
        out.append("  subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids")
        out.append("}")
    return "\n".join(out)
```

## Step 10 — `render_s3_bucket`

```python
def render_s3_bucket(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_s3_bucket``. No subnet group / SG — S3 is a regional
    service with its own access controls, not a VPC resource.
    """
    body = dict(svc.body)
    body["bucket"] = body.pop("identifier", svc.global_name)
    body.pop("logging", None)
    body.pop("restart", None)
    body.pop("container_name", None)
    body.pop("depends_on", None)
    body.pop("environment", None)
    body.pop("networks", None)

    body_str = _hcl_block_body(body)
    out: list[str] = []
    out.append(f'resource "aws_s3_bucket" "{svc.name}" {{')
    out.append(body_str)
    out.append("}")
    return "\n".join(out)
```

## Step 11 — Dispatch + entry point

After all six renderers, add the dispatch table and the dispatcher:

```python
from typing import Callable

_DESTINATION_RENDERERS: dict[str, Callable[[CompiledService, _RenderCtx], str]] = {
    "task_definition": render_task_definition,
    "ecs_service": render_ecs_service,
    "target_group": render_target_group,
    "rds_instance": render_rds_instance,
    "elasticache_cluster": render_elasticache_cluster,
    "s3_bucket": render_s3_bucket,
}


def _destination_applicable(dest: str, svc: CompiledService) -> bool:
    """Check whether ``dest`` is conditionally emittable for ``svc``."""
    if dest == "target_group":
        return "web" in svc.networks
    return True


def render_service(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Render every elastic destination the service's engine declares,
    in dependency-friendly order (data sources first, then resources).
    """
    substituted_body, data_sources = _substitute_body_ssm_refs(
        svc.body, ctx.project, ctx.env, svc.name
    )
    from dataclasses import replace
    svc_view = replace(svc, body=substituted_body)

    parts: list[str] = []
    if data_sources:
        parts.extend(data_sources)
        parts.append("")  # blank line between data sources and resources

    emits_elastic = svc.emits.get("elastic", [])
    for dest in emits_elastic:
        if not _destination_applicable(dest, svc):
            continue
        renderer = _DESTINATION_RENDERERS.get(dest)
        if renderer is None:
            # Should be impossible after Mod 012's load-time validation
            # (unknown destinations are rejected then). Defensive.
            parts.append(
                f"# unknown destination {dest!r} for service {svc.name!r}; no HCL emitted"
            )
            continue
        parts.append(renderer(svc_view, ctx))
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"
```

## Step 12 — Delete `render_backing` and `render_core`

After step 11 lands, the old `render_backing` (lines 145-247 of the original) and `render_core` (lines 250-445) can be deleted in their entirety. Also delete `_ENGINE_TO_RESOURCE` (lines 109-114).

## Step 13 — Update `emit_hcl`

The orchestrator at lines 522-588 needs to:
1. Build a single ordered service list (backing first by name, then core by name).
2. Construct one `_RenderCtx` with project, env, alb_policy, priorities.
3. Pass `services_sorted` + `render_service` (bound with ctx) to the Jinja template.
4. Drop the old `render_backing` / `render_core` parameters.

```python
def emit_hcl(
    compiled: CompiledEnv,
    out_path: Path,
    *,
    naming_policies: NamingPolicies,
) -> None:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    tpl = env.get_template("main.tf.j2")

    # Order: backing services first, then core services. Alphabetical
    # within each group. Purely cosmetic (tofu builds its own DAG), but
    # keeps the emitted main.tf readable.
    backing = sorted(
        (s for s in compiled.services.values() if not s.is_core),
        key=lambda s: s.name,
    )
    core = sorted(
        (s for s in compiled.services.values() if s.is_core),
        key=lambda s: s.name,
    )
    services_ordered = backing + core

    # ALB listener rules need a unique priority per web-network core service.
    _web_core = [s for s in core if "web" in s.networks]
    priorities = {s.name: 100 + i for i, s in enumerate(_web_core)}

    s3_p = naming_policies.get("s3")
    ddb_p = naming_policies.get("ddb")
    alb_p = naming_policies.get("alb")
    ecs_p = naming_policies.get("ecs")

    ctx = _RenderCtx(
        project=compiled.project,
        env=compiled.env,
        alb_policy=alb_p,
        priorities=priorities,
    )

    def _render(svc: CompiledService) -> str:
        return render_service(svc, ctx)

    rendered = tpl.render(
        project=compiled.project,
        project_version=compiled.project_version,
        env=compiled.env,
        domain=compiled.domain,
        subdomain=compiled.subdomain,
        region=ELASTIC_REGION,
        networks_sorted=sorted(compiled.networks),
        services=services_ordered,
        render_service=_render,
        state_bucket=apply_policy(
            f"{compiled.project}_tofu_state", s3_p
        ),
        state_lock_table=apply_policy(
            f"{compiled.project}_tofu_locks", ddb_p
        ),
        alb_name=apply_policy(
            f"{compiled.project}_{compiled.env}_alb", alb_p
        ),
        ecs_cluster_name=apply_policy(
            f"{compiled.project}_{compiled.env}", ecs_p
        ),
    )
    out_path.write_text(rendered)
```

## Step 14 — Update `main.tf.j2`

File: `src/docex/emit/templates/main.tf.j2`. Replace the two existing loops (around lines 186-196 — `{% for svc in backing_services %}{{ render_backing(svc) }}{% endfor %}` and the analogous core loop) with a single loop:

```jinja
{# Services (backing first, then core; ordering is set in Python). #}
{% for svc in services -%}
{{ render_service(svc) }}

{% endfor %}
```

Keep any surrounding section comments. The blank line after `{{ render_service(svc) }}` separates resource blocks in the rendered HCL.

## Step 15 — Existing unit tests

Files: `tests/unit/test_hcl_emitter.py` (or wherever the bundled HCL emit assertions live).

Existing tests that directly call `render_core(...)` or `render_backing(...)` need to be updated. Two strategies:

A. **Snapshot-style tests** that assert on the rendered `main.tf` content via `emit_hcl` continue to work unchanged — they exercise the orchestrator, not the per-renderer functions. The output HCL for bundled engines should be byte-identical (or differ only in trivial ordering of data-source vs resource blocks). If there's drift, investigate; the goal is no semantic change for bundled engines.

B. **Tests that call `render_core` / `render_backing` directly** — rewrite to call the appropriate per-destination renderer:
- `render_core(svc, ...)` → split into separate assertions against `render_task_definition(svc, ctx)`, `render_ecs_service(svc, ctx)`, `render_target_group(svc, ctx)`.
- `render_backing(svc, ...)` for postgres → `render_rds_instance(svc, ctx)`.
- `render_backing(svc, ...)` for redis → `render_elasticache_cluster(svc, ctx)`.
- `render_backing(svc, ...)` for s3 → `render_s3_bucket(svc, ctx)`.

If a test does multi-resource assertion (e.g., "rendered HCL contains both task_definition and ecs_service"), the cleanest update is to call `render_service(svc, ctx)` and assert against its combined output.

Expect 5-15 tests to need updating.

## Step 16 — New unit tests

File: `tests/unit/test_emit_dispatch.py` (new file). Tests covering the destination-driven dispatch + container-backing service rendering:

```python
"""Mod 013: dispatch by emit destination + container-backing renderable on elastic."""

from __future__ import annotations

from pathlib import Path

import pytest

from docex.cicl.compile import compile_env, CompiledService
from docex.cicl.transfer import load_transfer_tables
from docex.emit.hcl import (
    _RenderCtx, _DESTINATION_RENDERERS,
    render_service, render_task_definition, render_ecs_service,
    render_target_group, render_rds_instance,
)
from docex.naming import NamingPolicy


def _ctx(project="proj", env="stage"):
    """Minimal _RenderCtx for unit tests."""
    return _RenderCtx(
        project=project,
        env=env,
        alb_policy=NamingPolicy(name="alb", separator="hyphen", case="any", max_len=32),
        priorities={},
    )


def _svc(name="sidecar", role="sidecar", engine="nginx", *, is_core=False, networks=None, body=None, emits=None, port=None):
    """Construct a CompiledService for renderer unit tests."""
    return CompiledService(
        name=name,
        role=role,
        engine=engine,
        foundation="elastic",
        is_core=is_core,
        global_name=f"proj_stage_{name}",
        body=body or {"image": "nginx:1.27-alpine", "cpu": "256", "memory": "512"},
        networks=networks or ["internal"],
        depends_on=[],
        port=port,
        env={},
        emits=emits or {"elastic": ["task_definition", "ecs_service"]},
    )


def test_dispatch_table_covers_all_emit_destinations():
    """Every destination in EMIT_DESTINATIONS['elastic'] must have a renderer."""
    from docex.cicl.transfer import EMIT_DESTINATIONS
    for dest in EMIT_DESTINATIONS["elastic"]:
        assert dest in _DESTINATION_RENDERERS, f"no renderer for {dest!r}"


def test_container_backing_renders_task_definition_and_ecs_service():
    """A backing service emitting [task_definition, ecs_service] produces both resources."""
    svc = _svc()
    rendered = render_service(svc, _ctx())
    assert 'resource "aws_ecs_task_definition" "sidecar"' in rendered
    assert 'resource "aws_ecs_service" "sidecar"' in rendered
    # No target_group: not on web network.
    assert "aws_lb_target_group" not in rendered


def test_container_backing_on_internal_network_uses_internal_sg():
    """The ECS service's network_configuration uses the internal SG."""
    svc = _svc(networks=["internal"])
    rendered = render_ecs_service(svc, _ctx())
    assert "security_groups = [aws_security_group.internal.id]" in rendered


def test_postgres_still_renders_rds_instance():
    """Bundled postgres engine emits to rds_instance; rendering must produce
    aws_db_instance (no behavior change for bundled engines after refactor)."""
    svc = _svc(
        name="appdb", role="relational_db", engine="postgres", is_core=False,
        networks=["internal"],
        body={
            "engine": "postgres", "engine_version": "15",
            "instance_class": "db.t3.medium", "allocated_storage": 20,
            "identifier": "proj-stage-appdb",
        },
        emits={"elastic": ["rds_instance"]},
    )
    rendered = render_rds_instance(svc, _ctx())
    assert 'resource "aws_db_instance" "appdb"' in rendered
    assert 'resource "aws_db_subnet_group" "appdb"' in rendered


def test_target_group_skipped_when_not_on_web_network():
    """A service that lists target_group in emits but isn't on web is skipped."""
    svc = _svc(
        networks=["internal"],
        emits={"elastic": ["task_definition", "ecs_service", "target_group"]},
    )
    rendered = render_service(svc, _ctx())
    assert "aws_lb_target_group" not in rendered
    assert "aws_lb_listener_rule" not in rendered


def test_migration_taskdef_only_for_schema_owning_core():
    """A schema-owning core service emits both main and _migrate task definitions."""
    svc = _svc(
        name="web", role="web", engine="container", is_core=True,
        body={"image": "registry/proj/web:0.0.1", "cpu": "256", "memory": "512"},
        emits={"elastic": ["task_definition"]},
    )
    svc.schema_owned_by_db = True  # owns the appdb schema
    rendered = render_task_definition(svc, _ctx())
    assert 'resource "aws_ecs_task_definition" "web"' in rendered
    assert 'resource "aws_ecs_task_definition" "web_migrate"' in rendered
    # Backing services never own schemas, so no migrate variant for them.
    backing = _svc(name="appdb", is_core=False)
    backing.schema_owned_by_db = False
    rendered_backing = render_task_definition(backing, _ctx())
    assert "_migrate" not in rendered_backing


def test_dispatch_unknown_destination_falls_back_gracefully():
    """An unknown destination (defensive — should be impossible after Mod 012)
    emits a comment, not a crash."""
    svc = _svc(emits={"elastic": ["task_definition", "fake_destination"]})
    rendered = render_service(svc, _ctx())
    assert 'resource "aws_ecs_task_definition" "sidecar"' in rendered
    # The fake destination produces a comment line (defensive); core resource still rendered.
    # Note: Mod 012's load-time validation already rejects this in practice;
    # this test exercises the defensive `if renderer is None` branch.
```

## Step 17 — Snapshot-equivalence test (recommended)

Add a test that compiles the existing smoke project fixture (e.g., `tests/fixtures/sample_project/` if it exists, or one of the test-project structures) on elastic foundation and confirms the emitted `main.tf` contains the same resource declarations as before the refactor.

Pragmatic: instead of a true snapshot diff, assert presence/absence of key strings:

```python
def test_smoke_project_emits_unchanged_resource_set(tmp_path: Path):
    """The bundled engine set should produce the same resources before
    and after the refactor — postgres still on RDS, web/worker still on
    ECS, etc."""
    # Use whatever fixture path the existing test_hcl_emitter tests use.
    # Compile, render to a temp main.tf, then assert.
    ...
    assert 'resource "aws_db_instance" "appdb"' in main_tf
    assert 'resource "aws_ecs_task_definition" "web"' in main_tf
    assert 'resource "aws_ecs_service" "web"' in main_tf
    assert 'resource "aws_lb_target_group" "web"' in main_tf
    assert 'resource "aws_ecs_task_definition" "worker"' in main_tf
    # Worker isn't on web; no target_group for it.
    # (Use whichever assertions match the existing fixture's services.)
```

If a similar test already exists, just verify it still passes.

## Step 18 — Run the suite

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/ -q
python3 -m pytest tests/integration/test_compile.py -q
```

All must pass. If any HCL emission test fails:

- **If the diff is purely ordering** (e.g., a data source moved relative to a resource block) and the resulting HCL would still `tofu validate` cleanly, the test assertion can be updated to be order-tolerant (e.g., substring presence instead of exact block matching).
- **If the diff is semantic** (a field missing, a resource gone), it's a regression in the refactor — investigate, do not paper over.

A reasonable smoke for "still works": pipe the emitted `main.tf` for the existing smoke project through `tofu validate` if the binary is available. Don't add that as a test if it requires `tofu init` (downloads AWS provider; not unit-friendly).

## Step 19 — Leave everything uncommitted

No git commits. Design-context LLM reviews before commit.

## Hand-off report

In ≤300 words:

- Files changed (group: compile.py, hcl.py, main.tf.j2, tests added, tests updated).
- Test pass counts (unit + integration).
- Whether the emitted `main.tf` for the bundled engine set looks the same as before — name a smoke project / fixture you compiled and the resources you confirmed present.
- Pre-existing tests that needed updating — count, and which strategy (A or B from Step 15) you used.
- Any decision beyond implementation.md, especially around:
  - Whether `_substitute_body_ssm_refs` was hoisted to `render_service` (per the design) or had to live per-renderer for some reason.
  - The `dataclasses.replace(svc, body=substituted_body)` approach — any unexpected interaction with `CompiledService`'s mutable fields.
  - How the Jinja template's existing structure interacted with the single-loop swap (any other Jinja code referencing `backing_services` / `core_services` / `render_backing` / `render_core` that needed updating).
  - Any tests that asserted on the exact relative ordering of resources within `main.tf` (and how you handled the change).
- Anything that smelled off — places the refactor wanted to grow beyond scope, or places the existing code's contract was murkier than the doctrine documents.

## Out of scope

- ECS Service Connect / Cloud Map integration. Mod 014.
- EFS for stateful container-backing storage. Mod 015.
- New emit destinations beyond the existing six.
- Compose-side dispatch refactor — already engine-agnostic.
- `resources:` block extension to backing services in `infra.yml` — deferred.
- Cross-renderer ordering changes (data sources adjacent to their consumers, etc.) — keep the existing "data sources first, then resources" emission shape.
- Behavioral change for any bundled engine — bundled output should be equivalent (modulo trivial ordering) to pre-refactor output.

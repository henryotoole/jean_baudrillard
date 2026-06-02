"""Mod 013: dispatch by emit destination + container-backing renderable on elastic."""

from __future__ import annotations

from docex.cicl.compile import CompiledService
from docex.cicl.transfer import EMIT_DESTINATIONS
from docex.emit.hcl import (
    _DESTINATION_RENDERERS,
    _RenderCtx,
    render_ecs_service,
    render_rds_instance,
    render_service,
    render_task_definition,
)
from docex.naming import NamingPolicy


def _ctx(project: str = "proj", env: str = "stage") -> _RenderCtx:
    """Minimal _RenderCtx for unit tests."""
    return _RenderCtx(
        project=project,
        env=env,
        alb_policy=NamingPolicy(
            name="alb", separator="hyphen", case="any", max_len=32
        ),
        priorities={},
    )


def _svc(
    name: str = "sidecar",
    role: str = "sidecar",
    engine: str = "nginx",
    *,
    is_core: bool = False,
    networks: list[str] | None = None,
    body: dict | None = None,
    emits: dict | None = None,
    port: int | None = None,
) -> CompiledService:
    """Construct a CompiledService for renderer unit tests."""
    return CompiledService(
        name=name,
        role=role,
        engine=engine,
        foundation="elastic",
        is_core=is_core,
        global_name=f"proj_stage_{name}",
        body=body or {
            "image": "nginx:1.27-alpine",
            "cpu": "256",
            "memory": "512",
        },
        networks=networks or ["internal"],
        depends_on=[],
        port=port,
        env={},
        emits=emits or {"elastic": ["task_definition", "ecs_service"]},
    )


def test_dispatch_table_covers_all_emit_destinations():
    """Every destination in EMIT_DESTINATIONS['elastic'] must have a renderer."""
    for dest in EMIT_DESTINATIONS["elastic"]:
        assert dest in _DESTINATION_RENDERERS, f"no renderer for {dest!r}"


def test_container_backing_renders_task_definition_and_ecs_service():
    """A backing service emitting [task_definition, ecs_service] produces both resources."""
    svc = _svc()
    rendered = render_service(svc, _ctx())
    assert 'resource "aws_ecs_task_definition" "sidecar"' in rendered
    assert 'resource "aws_ecs_service" "sidecar"' in rendered
    # No target_group: not on web network and not in the engine's emits.
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
        name="appdb",
        role="relational_db",
        engine="postgres",
        is_core=False,
        networks=["internal"],
        body={
            "engine": "postgres",
            "engine_version": "15",
            "instance_class": "db.t3.medium",
            "allocated_storage": 20,
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
        name="web",
        role="web",
        engine="container",
        is_core=True,
        body={
            "image": "registry/proj/web:0.0.1",
            "cpu": "256",
            "memory": "512",
        },
        emits={"elastic": ["task_definition"]},
    )
    svc.schema_owned_by_db = True  # owns the appdb schema
    rendered = render_task_definition(svc, _ctx())
    assert 'resource "aws_ecs_task_definition" "web"' in rendered
    assert 'resource "aws_ecs_task_definition" "web_migrate"' in rendered
    # Backing services never own schemas, so no migrate variant for them
    # even if some test were to flip the flag.
    backing = _svc(name="appdb", is_core=False)
    backing.schema_owned_by_db = False
    rendered_backing = render_task_definition(backing, _ctx())
    assert "_migrate" not in rendered_backing


def test_dispatch_unknown_destination_falls_back_gracefully():
    """An unknown destination (defensive — should be impossible after Mod 012)
    emits a comment, not a crash. Mod 012's load-time validation already rejects
    unknown destinations; this exercises the defensive `if renderer is None`
    branch in render_service.
    """
    svc = _svc(emits={"elastic": ["task_definition", "fake_destination"]})
    rendered = render_service(svc, _ctx())
    assert 'resource "aws_ecs_task_definition" "sidecar"' in rendered
    # The fake destination produces a comment line (defensive); the real
    # destinations still render.
    assert "unknown destination 'fake_destination'" in rendered

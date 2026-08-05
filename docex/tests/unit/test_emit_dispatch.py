"""Mod 013: dispatch by emit destination + container-backing renderable on elastic."""

from __future__ import annotations

from docex.cicl.compile import CompiledEnv, CompiledService
from docex.cicl.transfer import EMIT_DESTINATIONS
from docex.emit.hcl import (
    _DESTINATION_RENDERERS,
    _RenderCtx,
    render_ecs_service,
    render_migration_task_definitions,
    render_rds_instance,
    render_service,
    render_task_definition,
)
from docex.naming import NamingPolicy


def _compiled(services: list[CompiledService]) -> CompiledEnv:
    """Minimal CompiledEnv wrapper for the per-codebase renderers."""
    return CompiledEnv(
        env="stage",
        foundation="elastic",
        apex_domain="example.com",
        subdomain="stage.proj.example.com",
        bare_project_subdomain="proj.example.com",
        project="proj",
        project_dns_label="proj",
        project_version="0.0.1",
        container_registry=None,
        services={s.name: s for s in services},
        networks={"internal"},
    )


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
    codebase: str | None = None,
    service: str | None = None,
) -> CompiledService:
    """Construct a CompiledService for renderer unit tests."""
    return CompiledService(
        name=name,
        role=role,
        engine=engine,
        foundation="elastic",
        is_core=is_core,
        global_name=f"proj-stage-{name}",
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
        # Mod 096: the migrate block and the elastic `service` tag read the
        # codebase, so a core stub has to carry it.
        codebase=codebase or (name if is_core else None),
        service=service,
        codebase_global_name=(
            f"proj-stage-{codebase or name}" if is_core else None
        ),
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


def test_migration_taskdef_is_a_separate_per_codebase_pass():
    """Mod 099: ``render_task_definition`` renders exactly one task
    definition. The ``_migrate`` variant moved to
    ``render_migration_task_definitions``, a per-codebase pass — migration is
    a per-codebase operation, so a per-process renderer is the wrong place
    for it."""
    svc = _svc(
        name="web-app",
        role="web",
        engine="container",
        is_core=True,
        codebase="web",
        service="app",
        body={
            "image": "registry/proj/web:0.0.1",
            "cpu": "256",
            "memory": "512",
        },
        emits={"elastic": ["task_definition"]},
    )
    svc.schema_owned_by_db = True  # owns the appdb schema
    rendered = render_task_definition(svc, _ctx())
    assert 'resource "aws_ecs_task_definition" "web-app"' in rendered
    assert "_migrate" not in rendered

    migrations = render_migration_task_definitions(_compiled([svc]), _ctx())
    assert 'resource "aws_ecs_task_definition" "web_migrate"' in migrations
    assert 'family                   = "proj-stage-web-migrate"' in migrations
    # Backing services have no codebase, so they are never grouped and can
    # never produce a migrate variant even with the flag flipped.
    backing = _svc(name="appdb", is_core=False)
    backing.schema_owned_by_db = True
    assert render_migration_task_definitions(_compiled([backing]), _ctx()) == ""


def test_migration_taskdef_resources_are_the_per_dimension_max():
    """Mod 099: the migration is sized at the per-dimension max across the
    codebase's core service — commutative, so it cannot move because a
    sibling was renamed, and it never under-provisions."""
    small = _svc(
        name="api-web", role="web", engine="container", is_core=True,
        codebase="api", service="web",
        body={"image": "i:1", "cpu": "1024", "memory": "2048"},
        emits={"elastic": ["task_definition"]},
    )
    big = _svc(
        name="api-worker", role="worker", engine="container", is_core=True,
        codebase="api", service="worker",
        body={"image": "i:1", "cpu": "512", "memory": "4096"},
        emits={"elastic": ["task_definition"]},
    )
    small.schema_owned_by_db = big.schema_owned_by_db = True
    rendered = render_migration_task_definitions(
        _compiled([big, small]), _ctx()
    )
    assert '  cpu                      = "1024"' in rendered
    assert '  memory                   = "4096"' in rendered
    # Order-independence is the whole point: the reversed input agrees.
    assert rendered == render_migration_task_definitions(
        _compiled([small, big]), _ctx()
    )


# ---------------------------------------------------------------------------
# Mod 014 — ECS Service Connect per-service emission.
# ---------------------------------------------------------------------------


def test_ecs_service_emits_service_connect_block_enabled():
    """Every aws_ecs_service has service_connect_configuration with enabled=true."""
    svc = _svc()
    rendered = render_ecs_service(svc, _ctx())
    assert "service_connect_configuration {" in rendered
    assert "enabled   = true" in rendered
    assert "namespace = aws_service_discovery_private_dns_namespace.env.arn" in rendered


def test_ecs_service_with_port_registers_service_block():
    """A service with a declared port gets a `service {}` block inside SC config."""
    svc = _svc(port=80)
    rendered = render_ecs_service(svc, _ctx())
    assert 'port_name      = "sidecar"' in rendered
    assert 'discovery_name = "proj-stage-sidecar"' in rendered
    assert "client_alias {" in rendered
    assert 'dns_name = "proj-stage-sidecar"' in rendered
    assert "port     = 80" in rendered


def test_ecs_service_without_port_has_no_service_block():
    """A service without a port (e.g., a port-less worker) participates as a
    client only — no inner `service {}` block."""
    svc = _svc(name="worker", port=None)
    rendered = render_ecs_service(svc, _ctx())
    assert "service_connect_configuration {" in rendered
    assert "enabled   = true" in rendered
    # No inner service block — the `service {}` sub-block specifically
    # registers the task as discoverable; worker has nothing to register.
    assert "service {" not in rendered
    assert "client_alias {" not in rendered
    assert "discovery_name" not in rendered


def test_task_definition_port_mapping_has_name_field():
    """Port mappings carry `name = <short_service_name>` so Service Connect's
    port_name reference resolves."""
    svc = _svc(port=8080)
    rendered = render_task_definition(svc, _ctx())
    # The container_def is rendered as HCL via _hcl_value. Scope the
    # assertion to the portMappings block to avoid colliding with the
    # container-level `name = "sidecar"` attribute that already exists.
    pm_start = rendered.find("portMappings")
    assert pm_start != -1, "expected portMappings in rendered task definition"
    pm_end = rendered.find("]", pm_start)
    pm_block = rendered[pm_start:pm_end]
    assert 'name = "sidecar"' in pm_block
    assert "containerPort = 8080" in pm_block


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


# ---------------------------------------------------------------------------
# Mod 015 — EFS for stateful container-backing services on Fargate.
# ---------------------------------------------------------------------------


def test_efs_file_system_in_emit_destinations():
    """Mod 015: efs_file_system is a registered emit destination."""
    from docex.cicl.transfer import EMIT_DESTINATIONS
    assert "efs_file_system" in EMIT_DESTINATIONS["elastic"]
    # Not on fixed — EFS is an elastic-only concept.
    assert "efs_file_system" not in EMIT_DESTINATIONS["fixed"]


def test_efs_destination_dispatched_to_renderer():
    """Mod 015: render_efs_file_system is registered in the dispatch table."""
    from docex.emit.hcl import _DESTINATION_RENDERERS, render_efs_file_system
    assert _DESTINATION_RENDERERS["efs_file_system"] is render_efs_file_system


def test_render_efs_emits_filesystem_and_mount_target():
    """Mod 015: a stateful svc emits aws_efs_file_system + aws_efs_mount_target."""
    svc = _svc(
        name="clickdb",
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    from docex.emit.hcl import render_efs_file_system
    rendered = render_efs_file_system(svc, _ctx())
    assert 'resource "aws_efs_file_system" "clickdb"' in rendered
    assert 'creation_token   = "proj-stage-clickdb"' in rendered
    assert 'encrypted        = true' in rendered
    assert 'resource "aws_efs_mount_target" "clickdb"' in rendered
    assert 'count           = length(data.terraform_remote_state.project.outputs.private_subnet_ids)' in rendered
    # No backup policy by default — project-opt-in.
    assert "aws_efs_backup_policy" not in rendered


def test_render_efs_emits_backup_policy_when_enabled():
    """Mod 015: backups: true in infra.yml emits aws_efs_backup_policy."""
    svc = _svc(
        name="clickdb",
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    svc.target_extras = {"efs_file_system": {"enabled": True}}
    from docex.emit.hcl import render_efs_file_system
    rendered = render_efs_file_system(svc, _ctx())
    assert 'resource "aws_efs_backup_policy" "clickdb"' in rendered
    assert 'status = "ENABLED"' in rendered


def test_render_efs_mount_target_attaches_to_non_web_sgs():
    """Mod 015: EFS mount targets don't get the public web SG, only internal-class ones."""
    svc = _svc(
        name="clickdb",
        networks=["internal", "web"],  # contrived — sidecar normally only on internal
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    from docex.emit.hcl import render_efs_file_system
    rendered = render_efs_file_system(svc, _ctx())
    # internal SG present, web SG absent.
    assert "aws_security_group.internal.id" in rendered
    # The substring `aws_security_group.web.id` must NOT appear inside
    # the mount target's security_groups list.
    assert "aws_security_group.web.id" not in rendered


def test_task_definition_emits_volume_and_mountpoints_when_stateful():
    """Mod 015: render_task_definition emits volume + mountPoints when persistent_storage is set."""
    svc = _svc(
        name="clickdb",
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    rendered = render_task_definition(svc, _ctx())
    assert "volume {" in rendered
    assert 'name = "data"' in rendered
    assert "efs_volume_configuration {" in rendered
    assert "file_system_id     = aws_efs_file_system.clickdb.id" in rendered
    assert 'transit_encryption = "ENABLED"' in rendered
    # mountPoints lives on the container_def. _hcl_value emits the
    # container_def in HCL attribute syntax (it's later passed through
    # jsonencode() at apply time), so we assert against the HCL form.
    assert "mountPoints" in rendered
    assert 'sourceVolume = "data"' in rendered
    assert 'containerPath = "/var/lib/clickhouse"' in rendered
    assert "readOnly = false" in rendered


def test_task_definition_without_persistent_storage_has_no_volumes():
    """Stateless services don't get a volume block."""
    svc = _svc()  # no persistent_storage
    rendered = render_task_definition(svc, _ctx())
    assert "volume {" not in rendered
    assert "efs_volume_configuration" not in rendered
    assert "mountPoints" not in rendered

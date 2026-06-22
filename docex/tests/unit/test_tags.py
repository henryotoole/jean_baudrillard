"""Unit tests for the central tag helper (Mod 060).

Locks the three doctrine tag blocks (cicl.md § Naming and Tagging) and the
two baked-in rules: the env-scoped `service=etc` Name fallback to descriptor
(decision 2) and the per-tier key sets.
"""

from __future__ import annotations

from docex.emit.tags import render_hcl_tags, standard_tags


def test_prerequisite_block():
    tags = standard_tags(
        "prerequisite", shape_name="master_network", descriptor="VPC"
    )
    assert tags == {
        "managed_by": "doctrine-operator",
        "infra_tier": "prerequisite",
        "shape_name": "master_network",
        "descriptor": "VPC",
        "Name": "master_network_VPC",
    }
    # Preinfra carries no project / env / service / role.
    assert "project" not in tags
    assert "env" not in tags
    assert "service" not in tags
    assert "role" not in tags


def test_project_block():
    tags = standard_tags(
        "project", shape_name="dns", descriptor="zone", project="proj"
    )
    assert tags == {
        "managed_by": "doctrine",
        "infra_tier": "project",
        "shape_name": "dns",
        "descriptor": "zone",
        "project": "proj",
        "Name": "proj_dns_zone",
    }
    assert "env" not in tags
    assert "service" not in tags
    assert "role" not in tags


def test_environment_block_per_service():
    tags = standard_tags(
        "environment",
        shape_name="backing_service",
        descriptor="RDS",
        project="proj",
        env="prod",
        service="db",
        role="relational_db",
    )
    assert tags == {
        "managed_by": "doctrine",
        "infra_tier": "environment",
        "shape_name": "backing_service",
        "descriptor": "RDS",
        "project": "proj",
        "env": "prod",
        "service": "db",
        "role": "relational_db",
        # Per-service Name uses the service segment.
        "Name": "proj_prod_db",
    }


def test_environment_block_env_scoped_name_falls_back_to_descriptor():
    """Decision 2: env-scoped resources carry service=etc/role=etc, and the
    Name segment falls back to the descriptor so Names stay unique (every
    such resource would otherwise be `proj_prod_etc`)."""
    tags = standard_tags(
        "environment",
        shape_name="etc",
        descriptor="ecs-cluster",
        project="proj",
        env="prod",
        service="etc",
        role="etc",
    )
    assert tags["service"] == "etc"
    assert tags["role"] == "etc"
    assert tags["Name"] == "proj_prod_ecs-cluster"


def test_all_tag_keys_present_for_env_scoped():
    """Decision 1: every tag key is present everywhere, even on env-scoped
    resources (service/role just become `etc`)."""
    tags = standard_tags(
        "environment",
        shape_name="network",
        descriptor="web",
        project="proj",
        env="dev",
        service="etc",
        role="etc",
    )
    assert set(tags) == {
        "managed_by", "infra_tier", "shape_name", "descriptor",
        "project", "env", "service", "role", "Name",
    }


def test_render_hcl_tags_format():
    rendered = render_hcl_tags(
        {"managed_by": "doctrine", "shape_name": "dns"}
    )
    assert rendered == '  tags = { managed_by = "doctrine", shape_name = "dns" }'

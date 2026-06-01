"""Tests for transfer-table loading and deep-merge semantics."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docex.cicl.transfer import (
    EngineEntry,
    _deep_merge,
    load_transfer_tables,
)
from docex.errors import TransferTableError


def test_deep_merge_dicts():
    base = {"a": {"x": 1, "y": 2}, "b": "k"}
    over = {"a": {"y": 99, "z": 3}, "c": "new"}
    out = _deep_merge(base, over)
    assert out == {"a": {"x": 1, "y": 99, "z": 3}, "b": "k", "c": "new"}


def test_deep_merge_list_replace():
    """Lists are replaced wholesale by override."""
    base = {"a": [1, 2, 3]}
    over = {"a": [9]}
    assert _deep_merge(base, over) == {"a": [9]}


def test_deep_merge_scalar_replace():
    assert _deep_merge({"k": 1}, {"k": 2}) == {"k": 2}


def test_load_bundled_tables():
    tables = load_transfer_tables(project_root=None)
    # All canonical roles must be present.
    assert "web" in tables.by_role
    assert "relational_db" in tables.by_role
    assert "cache" in tables.by_role
    assert "object_store" in tables.by_role
    assert "reverse_proxy" in tables.by_role
    # Postgres on relational_db.
    pg = tables.engine("relational_db", "postgres")
    assert pg.foundation == "both"
    assert "host" in pg.provides
    # Object store has two engines, foundation-split.
    assert tables.engine("object_store", "minio").foundation == "fixed"
    assert tables.engine("object_store", "s3").foundation == "elastic"


def test_engine_for_chooses_by_foundation():
    tables = load_transfer_tables(project_root=None)
    e = tables.engine_for("object_store", ["minio", "s3"], "fixed")
    assert e.engine == "minio"
    e = tables.engine_for("object_store", ["minio", "s3"], "elastic")
    assert e.engine == "s3"


def test_engine_for_no_match_raises():
    tables = load_transfer_tables(project_root=None)
    with pytest.raises(TransferTableError):
        tables.engine_for("object_store", ["minio"], "elastic")


def test_project_local_overrides_bundled(tmp_path: Path):
    """A project-local table overrides a leaf in the bundled table."""
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    override = {
        "roles": {
            "relational_db": {
                "postgres": {
                    "defaults": {
                        "elastic": {
                            "instance_class": "db.t3.large",
                        }
                    }
                }
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "relational_db.yml").write_text(
        yaml.safe_dump(override)
    )
    tables = load_transfer_tables(project_root=proj)
    pg_elastic = tables.engine("relational_db", "postgres").defaults_for("elastic")
    assert pg_elastic["instance_class"] == "db.t3.large"
    # Sibling keys from the bundled table survive.
    assert "allocated_storage" in pg_elastic


# ---------------------------------------------------------------------------
# Mod 005 — naming policies.
# ---------------------------------------------------------------------------


def test_bundled_loader_exposes_naming_policies():
    """The bundled `tables/naming_policies.yml` populates
    ``TransferTables.naming_policies`` with the canonical doctrine set."""
    tables = load_transfer_tables(project_root=None)
    by_name = tables.naming_policies.by_name
    # Every canonical AWS-resource policy must be present.
    for policy_name in ("s3", "rds", "ddb", "alb", "ecs", "ecr_repo", "iam", "ssm_path", "docker", "http_host"):
        assert policy_name in by_name, f"missing policy {policy_name}"
    # Sanity: the s3 policy has the documented rule shape.
    s3 = tables.naming_policies.get("s3")
    assert s3.separator == "hyphen"
    assert s3.case == "lower"
    assert s3.max_len == 63


def test_bundled_engines_reference_known_policies():
    """Every loaded engine entry's `naming` ref resolves in the policy table."""
    tables = load_transfer_tables(project_root=None)
    for engine_entry in tables.all_engines():
        # `get` raises TransferTableError for unknown policies.
        tables.naming_policies.get(engine_entry.naming)


def test_loader_rejects_engine_with_unknown_policy_ref(tmp_path: Path):
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    bad = {
        "roles": {
            "relational_db": {
                "postgres": {"naming": "totally_made_up"},
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "relational_db.yml").write_text(
        yaml.safe_dump(bad)
    )
    with pytest.raises(TransferTableError) as exc_info:
        load_transfer_tables(project_root=proj)
    msg = str(exc_info.value)
    assert "totally_made_up" in msg


def test_loader_rejects_inline_naming_struct(tmp_path: Path):
    """Per mod 005, the old inline `naming:` struct schema is unsupported —
    the loader requires a string policy reference."""
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    legacy = {
        "roles": {
            "object_store": {
                "minio": {
                    "naming": {"separator": "hyphen", "case": "lower", "max_len": 63},
                }
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "object_store.yml").write_text(
        yaml.safe_dump(legacy)
    )
    with pytest.raises(TransferTableError) as exc_info:
        load_transfer_tables(project_root=proj)
    msg = str(exc_info.value)
    assert "naming" in msg
    # The error should point at the doctrine reference.
    assert "policy" in msg.lower() or "string" in msg.lower()


# ---------------------------------------------------------------------------
# Mod 010 — emits: + target: routing on field translations.
# ---------------------------------------------------------------------------


def test_engine_default_target_returns_first_emits_entry():
    entry = EngineEntry(
        role="web",
        engine="container",
        foundation="both",
        emits={
            "fixed": ["compose_service"],
            "elastic": ["task_definition", "ecs_service", "target_group"],
        },
        naming="ecs",
    )
    assert entry.default_target("fixed") == "compose_service"
    assert entry.default_target("elastic") == "task_definition"


def test_engine_default_target_errors_when_no_emits_declared():
    entry = EngineEntry(
        role="web", engine="container", foundation="fixed", naming="ecs"
    )
    with pytest.raises(TransferTableError):
        entry.default_target("fixed")


def test_field_translation_returns_target_and_body():
    entry = EngineEntry(
        role="web",
        engine="container",
        foundation="both",
        emits={"elastic": ["task_definition", "target_group"]},
        fields={
            "health_check_path": {
                "elastic": {
                    "target": "target_group",
                    "health_check": {"path": "${field_value}"},
                },
            },
        },
        naming="ecs",
    )
    result = entry.field_translation("health_check_path", "elastic")
    assert result is not None
    target, body = result
    assert target == "target_group"
    assert body == {"health_check": {"path": "${field_value}"}}
    # The `target:` key is stripped from the returned body.
    assert "target" not in body


def test_field_translation_defaults_target_to_first_emit():
    entry = EngineEntry(
        role="relational_db",
        engine="postgres",
        foundation="both",
        emits={"elastic": ["rds_instance"]},
        fields={"version": {"elastic": {"engine_version": "${field_value}"}}},
        naming="rds",
    )
    result = entry.field_translation("version", "elastic")
    assert result is not None
    target, body = result
    assert target == "rds_instance"
    assert body == {"engine_version": "${field_value}"}


def test_field_translation_returns_none_for_missing_field():
    entry = EngineEntry(
        role="web",
        engine="container",
        foundation="both",
        emits={"elastic": ["task_definition"]},
        naming="ecs",
    )
    assert entry.field_translation("nonexistent", "elastic") is None


def test_field_translation_returns_none_when_foundation_undefined():
    entry = EngineEntry(
        role="web",
        engine="container",
        foundation="both",
        emits={"fixed": ["compose_service"], "elastic": ["task_definition"]},
        fields={"only_fixed": {"fixed": {"a": 1}}},
        naming="ecs",
    )
    assert entry.field_translation("only_fixed", "elastic") is None


def test_emits_parsed_from_bundled_tables():
    """The doctrine's bundled tables now declare `emits:` for every engine."""
    tables = load_transfer_tables(project_root=None)
    postgres = tables.engine("relational_db", "postgres")
    assert postgres.emits == {
        "fixed": ["compose_service"],
        "elastic": ["rds_instance"],
    }
    container = tables.engine("web", "container")
    assert container.emits == {
        "fixed": ["compose_service"],
        "elastic": ["task_definition", "ecs_service", "target_group"],
    }
    minio = tables.engine("object_store", "minio")
    assert minio.emits == {"fixed": ["compose_service"]}
    s3 = tables.engine("object_store", "s3")
    assert s3.emits == {"elastic": ["s3_bucket"]}


def test_loader_rejects_malformed_emits(tmp_path: Path):
    """`emits:` must be a mapping of foundation -> list of strings."""
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    bad = {
        "roles": {
            "relational_db": {
                "postgres": {"emits": "this should be a mapping"},
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "bad.yml").write_text(yaml.safe_dump(bad))
    with pytest.raises(TransferTableError) as exc_info:
        load_transfer_tables(project_root=proj)
    assert "emits" in str(exc_info.value)


def test_project_local_naming_policy_override(tmp_path: Path):
    """A project-local table can declare additional naming policies (or
    override leaf fields of existing ones) and the engines may reference
    them."""
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    override = {
        "naming_policies": {
            "rds": {"separator": "hyphen", "case": "lower", "max_len": 50},
        }
    }
    (proj / "infra" / "transfer_tables" / "policies.yml").write_text(
        yaml.safe_dump(override)
    )
    tables = load_transfer_tables(project_root=proj)
    rds = tables.naming_policies.get("rds")
    assert rds.max_len == 50  # Overridden.
    assert rds.separator == "hyphen"  # Preserved from bundled.

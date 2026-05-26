"""Tests for transfer-table loading and deep-merge semantics."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docex.cicl.transfer import (
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

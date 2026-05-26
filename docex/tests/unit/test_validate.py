"""Tests for cross-document CICL validation."""

from __future__ import annotations

import pytest
import yaml

from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document


def _doc(src: str) -> CICLDocument:
    raw = yaml.safe_load(src)
    return CICLDocument.model_validate(raw)


_BASE_FIXED = """
cicl_version: "1"
foundation: fixed
domain: example.com
container_registry: registry.example.com
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    depends_on: [database]
    resources:
      cpu: 1.0
      memory: 2GB
backing_services:
  database:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


def _tables():
    return load_transfer_tables(project_root=None)


def test_valid_doc_passes():
    doc = _doc(_BASE_FIXED)
    issues = validate_document(doc, _tables())
    assert issues == []


def test_rule_2_unknown_role():
    src = _BASE_FIXED.replace("role: web", "role: nonexistent_role")
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_2_unknown_role" in rules


def test_rule_3_unresolved_magic_ref_unknown_service():
    src = _BASE_FIXED + """
    env:
      X: ${backing_services.missing.host}
"""
    src = src.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    env:\n      X: ${backing_services.missing.host}\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_3_unresolved_magic_ref" in rules


def test_rule_3_unresolved_magic_ref_unknown_part():
    # Refer to a part the engine doesn't expose.
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    env:\n      X: ${backing_services.database.no_such_part}\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_3_unresolved_magic_ref" in rules


def test_rule_6_depends_on_cycle():
    # Force a cycle.
    src = _BASE_FIXED.replace(
        "    depends_on: [database]\n",
        "    depends_on: [database]\n    # api depends on database\n",
    )
    src = src.replace(
        "    schema_owned_by: api\n",
        "    schema_owned_by: api\n    depends_on: [api]\n",
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_6_depends_on_cycle" in rules


def test_rule_7_magic_ref_implies_depends_on():
    # Reference database via magic ref but remove it from depends_on.
    src = _BASE_FIXED.replace(
        "    depends_on: [database]\n",
        "    depends_on: []\n",
    )
    src = src.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    env:\n      X: ${backing_services.database.host}\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_7_magic_ref_implies_depends_on" in rules


def test_rule_8_schema_owned_by_unknown():
    src = _BASE_FIXED.replace(
        "    schema_owned_by: api\n", "    schema_owned_by: nobody\n"
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_8_schema_owned_by_unknown" in rules


def test_rule_9_container_registry_required_on_fixed():
    src = _BASE_FIXED.replace(
        "container_registry: registry.example.com\n", ""
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_9_container_registry_required" in rules


def test_rule_11_no_gpu_on_elastic():
    src = _BASE_FIXED.replace("foundation: fixed", "foundation: elastic")
    src = src.replace(
        "container_registry: registry.example.com\n", ""
    )
    src = src.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n      gpu:\n        count: 1\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_11_no_gpu_on_elastic" in rules

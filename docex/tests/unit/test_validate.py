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
    depends_on: [db]
    resources:
      cpu: 1.0
      memory: 2GB
backing_services:
  db:
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


def test_repo_url_accepted():
    # repo_url is documentary (per cicl.md § Git Repo URL) — the model
    # accepts it without acting on it. Regression for v0.5.0, which
    # rejected the documented field as extra input.
    src = _BASE_FIXED.replace(
        "container_registry: registry.example.com",
        'container_registry: registry.example.com\n'
        'repo_url: "https://github.com/owner/project"',
    )
    doc = _doc(src)
    assert doc.repo_url == "https://github.com/owner/project"
    issues = validate_document(doc, _tables())
    assert issues == []


def test_rule_domain_default_must_be_web():
    src = _BASE_FIXED.replace(
        "container_registry: registry.example.com",
        "container_registry: registry.example.com\ndomain_default_service: db",
    )
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_domain_default_not_web" for i in issues)


def test_rule_domain_default_unknown():
    src = _BASE_FIXED.replace(
        "container_registry: registry.example.com",
        "container_registry: registry.example.com\ndomain_default_service: ghost",
    )
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_domain_default_unknown" for i in issues)


def test_rule_web_service_needs_port():
    # api is on the web network; drop its port.
    src = _BASE_FIXED.replace("    port: 8080\n", "")
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_web_service_needs_port" for i in issues)


def test_rule_env_secrets_overlap():
    # Declare the same key in both api's env: and secrets:.
    src = _BASE_FIXED.replace(
        "    port: 8080\n",
        '    port: 8080\n    env:\n      SHARED: literal\n'
        '    secrets:\n      SHARED: "desc"\n',
    )
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_env_secrets_overlap" for i in issues)


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
        "      memory: 2GB\n    env:\n      X: ${backing_services.db.no_such_part}\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_3_unresolved_magic_ref" in rules


def test_rule_6_depends_on_cycle():
    # Force a cycle.
    src = _BASE_FIXED.replace(
        "    depends_on: [db]\n",
        "    depends_on: [db]\n    # api depends on db\n",
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
    # Reference db via magic ref but remove it from depends_on.
    src = _BASE_FIXED.replace(
        "    depends_on: [db]\n",
        "    depends_on: []\n",
    )
    src = src.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    env:\n      X: ${backing_services.db.host}\n",
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


def test_rule_engine_reserved_name_postgres():
    """A postgres backing service named after a reserved keyword fails
    compile, because RDS would reject the DBName at apply time."""
    # Rename `db` → `database` (a name on postgres's reserved list).
    src = _BASE_FIXED.replace("  db:", "  database:")
    src = src.replace("[db]", "[database]")
    src = src.replace("backing_services.db.", "backing_services.database.")
    # The fixed-foundation _BASE_FIXED has no env refs to db, so the
    # above replace is mostly a no-op — but kept for symmetry with the
    # full elastic flow.
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_engine_reserved_name" in rules


def test_rule_engine_reserved_name_case_insensitive():
    """Matching is case-insensitive — `Database` is just as reserved."""
    src = _BASE_FIXED.replace("  db:", "  Database:")
    src = src.replace("[db]", "[Database]")
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_engine_reserved_name" in rules


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

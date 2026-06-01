"""Tests for cross-document CICL validation."""

from __future__ import annotations

from pathlib import Path

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
    depends_on: [appdb]
    resources:
      cpu: 1.0
      memory: 2GB
backing_services:
  appdb:
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
        "container_registry: registry.example.com\ndomain_default_service: appdb",
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
        "      memory: 2GB\n    env:\n      X: ${backing_services.appdb.no_such_part}\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_3_unresolved_magic_ref" in rules


def test_rule_6_depends_on_cycle():
    # Force a cycle.
    src = _BASE_FIXED.replace(
        "    depends_on: [appdb]\n",
        "    depends_on: [appdb]\n    # api depends on appdb\n",
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
    # Reference appdb via magic ref but remove it from depends_on.
    src = _BASE_FIXED.replace(
        "    depends_on: [appdb]\n",
        "    depends_on: []\n",
    )
    src = src.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    env:\n      X: ${backing_services.appdb.host}\n",
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
    # Rename `appdb` → `database` (a name on postgres's reserved list).
    src = _BASE_FIXED.replace("  appdb:", "  database:")
    src = src.replace("[appdb]", "[database]")
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_engine_reserved_name" in rules


def test_rule_engine_reserved_name_case_insensitive():
    """Matching is case-insensitive — `Database` is just as reserved."""
    src = _BASE_FIXED.replace("  appdb:", "  Database:")
    src = src.replace("[appdb]", "[Database]")
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_engine_reserved_name" in rules


def test_rule_engine_reserved_name_db():
    """RDS rejects ``db`` as a postgres DBName; mod 006 added it to the
    reserved_names list so compile catches it before tofu apply does."""
    src = _BASE_FIXED.replace("  appdb:", "  db:")
    src = src.replace("[appdb]", "[db]")
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_engine_reserved_name" in rules


def test_rule_engine_reserved_name_template0():
    """``template0`` is a postgres internal template DB; RDS rejects it as
    the initial DBName. Mod 006 reserves it."""
    src = _BASE_FIXED.replace("  appdb:", "  template0:")
    src = src.replace("[appdb]", "[template0]")
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


# ---------------------------------------------------------------------------
# Mod 010 — emits: + target: routing validation.
# ---------------------------------------------------------------------------


def test_validate_emits_passes_on_bundled_tables():
    """Every bundled engine declares its `emits:` correctly; validation
    should produce zero EMITS_* / FIELD_TARGET_* issues on a clean doc."""
    doc = _doc(_BASE_FIXED)
    issues = validate_document(doc, _tables())
    codes = {i.rule for i in issues}
    assert "EMITS_MISSING" not in codes
    assert "EMITS_UNKNOWN_DESTINATION" not in codes
    assert "FIELD_TARGET_UNDECLARED" not in codes
    assert "FIELD_TARGET_NOT_APPLICABLE" not in codes


def test_validate_emits_missing_for_supported_foundation(tmp_path: Path):
    """An engine that supports a foundation but declares no emits for it
    fails validation with EMITS_MISSING.

    We exercise this by introducing a project-local role/engine that
    declares `foundation: both` but `emits:` only for fixed. The deep
    merge would preserve the bundled `emits.elastic` on existing engines,
    so a fresh engine is the clean test bed.
    """
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    override = {
        "roles": {
            "custom_thing": {
                "myengine": {
                    "foundation": "both",
                    "naming": "ecs",
                    "emits": {"fixed": ["compose_service"]},
                    "provides": {},
                }
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "override.yml").write_text(
        yaml.safe_dump(override)
    )
    tables = load_transfer_tables(project_root=proj)
    # An elastic doc consuming the custom role so the elastic foundation
    # path triggers.
    src = """
cicl_version: "1"
foundation: elastic
domain: example.com
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    resources:
      cpu: 1.0
      memory: 2GB
backing_services:
  thing:
    role: custom_thing
    engine: myengine
    networks: [internal]
"""
    doc = _doc(src)
    issues = validate_document(doc, tables)
    rules = [i.rule for i in issues]
    assert "EMITS_MISSING" in rules


def test_validate_emits_unknown_destination(tmp_path: Path):
    """An engine declaring an unrecognized destination name fails with
    EMITS_UNKNOWN_DESTINATION."""
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    override = {
        "roles": {
            "relational_db": {
                "postgres": {
                    "emits": {
                        "fixed": ["compose_service"],
                        "elastic": ["not_a_real_destination"],
                    },
                }
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "override.yml").write_text(
        yaml.safe_dump(override)
    )
    tables = load_transfer_tables(project_root=proj)
    src = _BASE_FIXED.replace("foundation: fixed", "foundation: elastic")
    src = src.replace("container_registry: registry.example.com\n", "")
    doc = _doc(src)
    issues = validate_document(doc, tables)
    rules = [i.rule for i in issues]
    assert "EMITS_UNKNOWN_DESTINATION" in rules


def test_validate_field_target_undeclared(tmp_path: Path):
    """A field translation whose `target:` is not in the engine's `emits:`
    list fails with FIELD_TARGET_UNDECLARED."""
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    override = {
        "roles": {
            "relational_db": {
                "postgres": {
                    "fields": {
                        "version": {
                            "elastic": {
                                # target_group isn't in postgres's emits.
                                "target": "target_group",
                                "engine_version": "${field_value}",
                            },
                        },
                    },
                }
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "override.yml").write_text(
        yaml.safe_dump(override)
    )
    tables = load_transfer_tables(project_root=proj)
    src = _BASE_FIXED.replace("foundation: fixed", "foundation: elastic")
    src = src.replace("container_registry: registry.example.com\n", "")
    doc = _doc(src)
    issues = validate_document(doc, tables)
    rules = [i.rule for i in issues]
    assert "FIELD_TARGET_UNDECLARED" in rules


def test_validate_field_target_not_applicable_when_service_off_web():
    """`target: target_group` requires the consuming service to be on the
    `web` network. A service that declares `health_check_path` but isn't
    on `web` fails with FIELD_TARGET_NOT_APPLICABLE."""
    # Build an elastic doc where the web service is taken off the `web`
    # network and given a health_check_path. Health check field still
    # routes to `target_group` per the bundled web.yml.
    src = """
cicl_version: "1"
foundation: elastic
domain: example.com
core_services:
  api:
    role: web
    networks: [internal]
    port: 8080
    health_check_path: /health
    resources:
      cpu: 1.0
      memory: 2GB
"""
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "FIELD_TARGET_NOT_APPLICABLE" in rules


def test_validate_field_target_applicable_when_on_web():
    """Same field on a service that IS on `web` should NOT trip the rule."""
    src = """
cicl_version: "1"
foundation: elastic
domain: example.com
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    health_check_path: /health
    resources:
      cpu: 1.0
      memory: 2GB
"""
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "FIELD_TARGET_NOT_APPLICABLE" not in rules

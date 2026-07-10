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
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
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
    assert any(i.rule == "rule_env_secrets_config_overlap" for i in issues)


def test_rule_env_config_overlap():
    # Same key in env: and config: — rule 16 three-way.
    src = _BASE_FIXED.replace(
        "    port: 8080\n",
        '    port: 8080\n    env:\n      SHARED: literal\n'
        '    config:\n      SHARED: "desc"\n',
    )
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_env_secrets_config_overlap" for i in issues)


def test_rule_secrets_config_overlap():
    # Same key in secrets: and config: — rule 16 three-way.
    src = _BASE_FIXED.replace(
        "    port: 8080\n",
        '    port: 8080\n    secrets:\n      SHARED: "sdesc"\n'
        '    config:\n      SHARED: "cdesc"\n',
    )
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_env_secrets_config_overlap" for i in issues)


def test_rule_env_secrets_config_no_overlap_clean():
    # Distinct keys across all three blocks — no overlap issue.
    src = _BASE_FIXED.replace(
        "    port: 8080\n",
        '    port: 8080\n    env:\n      E: literal\n'
        '    secrets:\n      S: "sdesc"\n    config:\n      C: "cdesc"\n',
    )
    issues = validate_document(_doc(src), _tables())
    assert not any(
        i.rule == "rule_env_secrets_config_overlap" for i in issues
    )


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
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
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
    """An engine declaring an unrecognized destination name is rejected
    at transfer-table load time (mod 012). Was previously surfaced
    downstream as a EMITS_UNKNOWN_DESTINATION validation issue; the
    failure now happens earlier with source attribution, before any
    `infra.yml` compilation can run."""
    from docex.errors import TransferTableError

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
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(project_root=proj)
    msg = str(exc.value)
    assert "infra/transfer_tables/override.yml" in msg
    assert "roles.relational_db.postgres.emits.elastic" in msg
    assert "not_a_real_destination" in msg


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
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
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
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
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


# ---------------------------------------------------------------------------
# Mod 011 — PROJECT_VERSION is doctrine-reserved on every core service.
# ---------------------------------------------------------------------------


def test_validate_rejects_project_version_in_env():
    """A core service declaring PROJECT_VERSION in its env: block fails
    validation — the name is doctrine-reserved. Mod 011."""
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    env:\n      PROJECT_VERSION: \"1.2.3\"\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_reserved_env_key" in rules


def test_validate_rejects_project_version_in_secrets():
    """Same name in secrets: also reserved — doctrine owns the key in
    both places. Mod 011."""
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    secrets:\n      PROJECT_VERSION: \"desc\"\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_reserved_env_key" in rules


def test_validate_rejects_project_version_in_config():
    """config: is now checked against the reserved core env keys too. Mod 079."""
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    config:\n      PROJECT_VERSION: \"desc\"\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_reserved_env_key" in rules


# ---------------------------------------------------------------------------
# Mod 079 — cross-category disjointness (rule 20) + doctrine-injected reserved.
# ---------------------------------------------------------------------------


def test_rule_source_key_category_conflict_config_vs_tte():
    """A core config: key that collides with a backing engine's minted TTE key
    (POSTGRES_PASSWORD from the postgres appdb) is a rule-20 conflict."""
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    config:\n      POSTGRES_PASSWORD: \"desc\"\n",
        1,
    )
    issues = validate_document(_doc(src), _tables())
    conflict = [
        i for i in issues if i.rule == "rule_source_key_category_conflict"
    ]
    assert conflict
    msg = conflict[0].message
    assert "POSTGRES_PASSWORD" in msg
    assert "tte" in msg and "config" in msg


def test_rule_source_key_category_conflict_clean_mixed():
    """A clean project with distinct TTE / secret / config keys has no
    disjointness conflict."""
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    secrets:\n      API_KEY: \"desc\"\n"
        "    config:\n      SOME_URL: \"desc\"\n",
        1,
    )
    issues = validate_document(_doc(src), _tables())
    assert not any(
        i.rule == "rule_source_key_category_conflict" for i in issues
    )


def test_doctrine_injected_key_reserved_in_secrets():
    """Declaring TELEMETRY_API_KEY (doctrine-injected) in secrets: fails with
    exactly one reserved diagnostic — and NOT a disjointness conflict (the
    ownership split delegates the injected key to the reserved check)."""
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    secrets:\n      TELEMETRY_API_KEY: \"desc\"\n",
        1,
    )
    issues = validate_document(_doc(src), _tables())
    reserved = [
        i for i in issues if i.rule == "rule_doctrine_injected_key_reserved"
    ]
    assert len(reserved) == 1
    assert "TELEMETRY_API_KEY" in reserved[0].message
    # Ownership split: the disjointness rule must NOT also fire on this key.
    assert not any(
        i.rule == "rule_source_key_category_conflict"
        and "TELEMETRY_API_KEY" in i.message
        for i in issues
    )


def test_doctrine_injected_key_reserved_in_config():
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    config:\n      TELEMETRY_API_KEY: \"desc\"\n",
        1,
    )
    issues = validate_document(_doc(src), _tables())
    assert (
        len([
            i for i in issues
            if i.rule == "rule_doctrine_injected_key_reserved"
        ])
        == 1
    )
    assert not any(
        i.rule == "rule_source_key_category_conflict" for i in issues
    )


def test_doctrine_injected_key_reserved_in_env():
    src = _BASE_FIXED.replace(
        "      memory: 2GB\n",
        "      memory: 2GB\n    env:\n      TELEMETRY_API_KEY: \"literal\"\n",
        1,
    )
    issues = validate_document(_doc(src), _tables())
    assert any(
        i.rule == "rule_doctrine_injected_key_reserved" for i in issues
    )


# ---------------------------------------------------------------------------
# Mod 031 — apex_domain bare requirement, service-name blacklist,
# reverse_proxy field foundation gate, reverse_proxy role removal.
# ---------------------------------------------------------------------------


def test_apex_domain_must_be_bare():
    """`apex_domain` with a project subdomain (`myproject.example.com`)
    is rejected — the project segment is derived automatically from
    project.yml's name. Rule 13."""
    src = _BASE_FIXED.replace(
        "apex_domain: example.com",
        "apex_domain: myproject.example.com",
    )
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_13_apex_domain_bare" in rules


def test_apex_domain_accepts_two_part_apex():
    """`example.com` is fine (2 parts)."""
    issues = validate_document(_doc(_BASE_FIXED), _tables())
    rules = [i.rule for i in issues]
    assert "rule_13_apex_domain_bare" not in rules


def test_apex_domain_accepts_three_part_country_apex():
    """`example.co.uk` is fine (3 parts; country-code TLD ladder)."""
    src = _BASE_FIXED.replace(
        "apex_domain: example.com",
        "apex_domain: example.co.uk",
    )
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_13_apex_domain_bare" not in rules


@pytest.mark.parametrize("reserved", ["dev", "test", "stage", "prod", "www"])
def test_service_name_blacklist(reserved: str):
    """A service named with any reserved token (`dev`/`test`/`stage`/
    `prod`/`www`) fails validation. Rule 14."""
    # Replace api -> reserved in core_services and update depends_on chain.
    src = _BASE_FIXED.replace("  api:", f"  {reserved}:").replace(
        "schema_owned_by: api", f"schema_owned_by: {reserved}",
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_14_service_name_blacklist" in rules


def test_reverse_proxy_field_rejected_on_fixed():
    """The top-level `reverse_proxy:` field is elastic-only; declaring it
    on a fixed-foundation project fails validation. Rule 18."""
    src = _BASE_FIXED.replace(
        "container_registry: registry.example.com",
        "container_registry: registry.example.com\nreverse_proxy: alb",
    )
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_18_reverse_proxy_elastic_only" in rules


def test_reverse_proxy_field_accepted_on_elastic():
    """`reverse_proxy: alb` on an elastic project compiles cleanly."""
    src = _BASE_FIXED.replace("foundation: fixed", "foundation: elastic")
    src = src.replace("container_registry: registry.example.com\n", "")
    src = src.replace(
        "apex_domain: example.com",
        "apex_domain: example.com\nreverse_proxy: alb",
    )
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_18_reverse_proxy_elastic_only" not in rules


def test_reverse_proxy_field_defaults_to_none():
    """Omitting `reverse_proxy:` on an elastic project is valid (compile-
    time default is `alb` — handled elsewhere in the compiler)."""
    src = _BASE_FIXED.replace("foundation: fixed", "foundation: elastic")
    src = src.replace("container_registry: registry.example.com\n", "")
    doc = _doc(src)
    assert doc.reverse_proxy is None
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_18_reverse_proxy_elastic_only" not in rules


def test_reverse_proxy_role_no_longer_exists():
    """A service declaring `role: reverse_proxy` is rejected — the role
    was removed in mod 031."""
    src = _BASE_FIXED.replace(
        "    role: web\n", "    role: reverse_proxy\n", 1,
    )
    issues = validate_document(_doc(src), _tables())
    rules = [i.rule for i in issues]
    assert "rule_reverse_proxy_role_removed" in rules

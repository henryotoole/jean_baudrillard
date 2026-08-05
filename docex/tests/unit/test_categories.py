"""Mod 078 — the pure source-key classifier (`cicl/categories.py`).

`classify_source_keys` partitions every source key into exactly one of
TTE / secret / config, from `(infra.yml, transfer tables)` alone. These
tests exercise the partition itself and the reporting helpers
(`conflicts`, `category_of`) that later mods (079 validation, 082 push)
build on. See config_and_secrets.md § The Three Categories.
"""

from __future__ import annotations

import yaml

from docex.cicl.categories import (
    Category,
    SourceKeyCategories,
    classify_source_keys,
    config_manifest,
    minted_policies,
    secret_manifest,
)
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


def _tables():
    return load_transfer_tables(project_root=None)


# A postgres backing (POSTGRES_PASSWORD minted -> TTE, POSTGRES_USER fixed ->
# in no category) plus a core service with one bespoke secret and one config.
_MIXED = """
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    secrets:
      STRIPE_KEY: "Stripe secret API key"
    config:
      PARTNER_URL: "Partner API base URL (per-env)"
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
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


def test_mixed_project_partitions_into_three_categories():
    cats = classify_source_keys(_doc(_MIXED), _tables())
    # POSTGRES_PASSWORD is minted -> TTE; POSTGRES_USER is fixed -> in none.
    assert cats.tte == frozenset({"POSTGRES_PASSWORD"})
    # Bespoke core secret + doctrine-injected TELEMETRY_API_KEY.
    assert cats.secret == frozenset({"STRIPE_KEY", "TELEMETRY_API_KEY"})
    assert cats.config == frozenset({"PARTNER_URL"})


def test_disjoint_project_has_no_conflicts():
    cats = classify_source_keys(_doc(_MIXED), _tables())
    assert cats.conflicts() == {}


def test_cross_category_collision_is_reported():
    # Same key declared as both a secret and a config on the one service.
    src = _MIXED.replace(
        "    config:\n      PARTNER_URL:",
        "    config:\n      STRIPE_KEY: \"colliding key\"\n      PARTNER_URL:",
    )
    cats = classify_source_keys(_doc(src), _tables())
    conflicts = cats.conflicts()
    assert "STRIPE_KEY" in conflicts
    assert set(conflicts["STRIPE_KEY"]) == {Category.SECRET, Category.CONFIG}


def test_category_of_resolves_each_category_and_unknowns():
    cats = classify_source_keys(_doc(_MIXED), _tables())
    assert cats.category_of("POSTGRES_PASSWORD") is Category.TTE
    assert cats.category_of("STRIPE_KEY") is Category.SECRET
    assert cats.category_of("PARTNER_URL") is Category.CONFIG
    assert cats.category_of("NOT_A_KEY") is None


def test_two_core_services_sharing_a_secret_dedupe():
    src = """
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    secrets:
      SHARED_KEY: "shared across services"
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 1.0
          memory: 2GB
  worker:
    secrets:
      SHARED_KEY: "shared across services"
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [internal]
        port: 8081
        resources:
          cpu: 1.0
          memory: 2GB
"""
    cats = classify_source_keys(_doc(src), _tables())
    # A frozenset dedupes structurally; the assertion also guards conflicts()
    # from ever seeing the same key twice within one category.
    assert cats.secret == frozenset({"SHARED_KEY", "TELEMETRY_API_KEY"})
    assert cats.conflicts() == {}


def test_minted_policies_maps_postgres_password_to_password_policy():
    doc = _doc(_MIXED)
    tables = _tables()
    policies = minted_policies(doc, tables)
    # postgres declares exactly one minted var (POSTGRES_PASSWORD); its
    # policy is the ``password`` generation policy.
    assert set(policies) == {"POSTGRES_PASSWORD"}
    assert policies["POSTGRES_PASSWORD"] is tables.generation_policies.get(
        "password"
    )
    # The minted set matches the TTE category exactly (no drift).
    assert set(policies) == set(classify_source_keys(doc, tables).tte)


def test_all_keys_is_the_union():
    cats = SourceKeyCategories(
        tte=frozenset({"A"}),
        secret=frozenset({"B"}),
        config=frozenset({"C"}),
    )
    assert cats.all_keys() == frozenset({"A", "B", "C"})


# ---------------------------------------------------------------------------
# secret_manifest — the single source of truth for scaffold/status tooling.
# ---------------------------------------------------------------------------


def test_secret_manifest_keys_sources_and_order():
    manifest = secret_manifest(_doc(_MIXED), _tables())
    by_key = {e.key: e for e in manifest}
    # Doctrine-injected + the core bespoke secret; POSTGRES_* (minted/fixed)
    # are never operator-supplied so they are absent.
    assert set(by_key) == {"TELEMETRY_API_KEY", "STRIPE_KEY"}
    assert "POSTGRES_PASSWORD" not in by_key
    assert "POSTGRES_USER" not in by_key
    # Sources: doctrine-injected -> "doctrine"; core key -> its service.
    assert by_key["TELEMETRY_API_KEY"].source == "doctrine"
    assert by_key["STRIPE_KEY"].source == "api"
    assert by_key["STRIPE_KEY"].desc == "Stripe secret API key"
    # Doctrine-injected surfaces first.
    assert manifest[0].key == "TELEMETRY_API_KEY"


def test_secret_manifest_dedupes_shared_key_keeping_first_source():
    src = """
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    secrets:
      SHARED_KEY: "shared across services"
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 1.0
          memory: 2GB
  worker:
    secrets:
      SHARED_KEY: "declared again on worker"
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [internal]
        port: 8081
        resources:
          cpu: 1.0
          memory: 2GB
"""
    manifest = secret_manifest(_doc(src), _tables())
    shared = [e for e in manifest if e.key == "SHARED_KEY"]
    assert len(shared) == 1
    # `api` sorts before `worker`, so the first declaration wins.
    assert shared[0].source == "api"
    assert shared[0].desc == "shared across services"


# ---------------------------------------------------------------------------
# config_manifest — core-service-declared config keys only.
# ---------------------------------------------------------------------------


def test_config_manifest_yields_declared_config_with_service_source():
    manifest = config_manifest(_doc(_MIXED), _tables())
    by_key = {e.key: e for e in manifest}
    # Only the core-declared config key — no doctrine-injected, no backing
    # engine vars, no secrets.
    assert set(by_key) == {"PARTNER_URL"}
    assert by_key["PARTNER_URL"].source == "api"
    assert by_key["PARTNER_URL"].desc == "Partner API base URL (per-env)"


def test_config_manifest_empty_when_no_config_declared():
    src = """
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    secrets:
      STRIPE_KEY: "Stripe secret API key"
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 1.0
          memory: 2GB
"""
    assert config_manifest(_doc(src), _tables()) == []

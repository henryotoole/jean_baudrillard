"""Unit tests for ``docex.cicl.compile.web_hostnames_for_env``. Mod 054.

This is the single source of truth for a project's public web hostnames,
shared by the compiler's traefik routing and the preinfra dev-DNS check;
it must mirror ``_web_hosts``'s derivation exactly.
"""

from __future__ import annotations

import yaml

from docex.cicl.compile import web_hostnames_for_env
from docex.cicl.model import CICLDocument


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


# Two web services (`api` is the domain_default_service, `admin` is not)
# plus a purely-internal backing service that must never be routed.
_DOC = _doc("""
cicl_version: "1"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
domain_default_service: api
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    resources:
      cpu: 1.0
      memory: 2GB
      disk: 20GB
  admin:
    role: web
    networks: [web]
    port: 8081
    resources:
      cpu: 1.0
      memory: 2GB
      disk: 20GB
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    port: 5432
    networks: [internal]
""")


def test_dev_default_service_gets_per_service_and_bare_env():
    hosts = web_hostnames_for_env(_DOC, "sample", "dev")
    # api (default): per-service + bare-env. admin: per-service only.
    assert "api.dev.sample.example.com" in hosts
    assert "dev.sample.example.com" in hosts
    assert "admin.dev.sample.example.com" in hosts


def test_dev_omits_bare_project_host():
    """The bare-project host is a prod-only routing target — never in dev."""
    hosts = web_hostnames_for_env(_DOC, "sample", "dev")
    assert "sample.example.com" not in hosts


def test_internal_only_service_is_not_routed():
    hosts = web_hostnames_for_env(_DOC, "sample", "dev")
    assert not any(h.startswith("appdb.") for h in hosts)


def test_prod_default_service_adds_bare_project_host():
    hosts = web_hostnames_for_env(_DOC, "sample", "prod")
    assert "sample.example.com" in hosts
    assert "prod.sample.example.com" in hosts


def test_hosts_are_order_stable_and_deduped():
    hosts = web_hostnames_for_env(_DOC, "sample", "dev")
    assert len(hosts) == len(set(hosts))
    # Stable across calls.
    assert hosts == web_hostnames_for_env(_DOC, "sample", "dev")

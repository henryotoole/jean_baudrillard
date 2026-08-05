"""Unit tests for ``docex.cicl.compile.web_hostnames_for_env``. Mod 054.

This is the single source of truth for a project's public web hostnames,
shared by the compiler's traefik routing and the preinfra dev-DNS check;
it must mirror ``_web_hosts``'s derivation exactly.
"""

from __future__ import annotations

import yaml

from docex.cicl.compile import web_hostnames_for_env
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


def _policies():
    return load_transfer_tables(project_root=None).naming_policies


# Two web core service (`api.web` is the domain_default_service,
# `admin.web` is not) plus a purely-internal backing service that must never
# be routed. Mod 096: `api` also carries a non-web `worker` core service, which
# must get no host at all.
_DOC = _doc("""
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
domain_default_service: api.web
codebases:
  api:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 1.0
          memory: 2GB
          disk: 20GB
      worker:
        role: worker
        command: ["python", "-m", "worker"]
        networks: [internal]
        resources:
          cpu: 0.5
          memory: 512MB
          disk: 20GB
  admin:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
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
    hosts = web_hostnames_for_env(_DOC, "sample", "dev", _policies())
    # api.web (default): per-service + bare-env. admin.web: per-service only.
    assert "api-web.dev.sample.example.com" in hosts
    assert "dev.sample.example.com" in hosts
    assert "admin-web.dev.sample.example.com" in hosts


def test_non_web_service_gets_no_host():
    """Mod 096: hosts are per CORE SERVICE, and a non-web one gets none —
    even though its codebase has a web sibling."""
    hosts = web_hostnames_for_env(_DOC, "sample", "dev", _policies())
    assert not any(h.startswith("api-worker.") for h in hosts)


def test_dev_omits_bare_project_host():
    """The bare-project host is a prod-only routing target — never in dev."""
    hosts = web_hostnames_for_env(_DOC, "sample", "dev", _policies())
    assert "sample.example.com" not in hosts


def test_internal_only_service_is_not_routed():
    hosts = web_hostnames_for_env(_DOC, "sample", "dev", _policies())
    assert not any(h.startswith("appdb.") for h in hosts)


def test_prod_default_service_adds_bare_project_host():
    hosts = web_hostnames_for_env(_DOC, "sample", "prod", _policies())
    assert "sample.example.com" in hosts
    assert "prod.sample.example.com" in hosts


def test_hosts_are_order_stable_and_deduped():
    hosts = web_hostnames_for_env(_DOC, "sample", "dev", _policies())
    assert len(hosts) == len(set(hosts))
    # Stable across calls.
    assert hosts == web_hostnames_for_env(_DOC, "sample", "dev", _policies())

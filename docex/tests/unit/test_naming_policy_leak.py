"""Mod 046: regression tests for naming-policy leak residuals.

Doctrine principle (`transfer_tables.md § Naming Policies`): every name
that lands on a data-plane resolvable identifier must derive its project
segment from the DNS-labeled form (underscores → hyphens, lowercased),
never from the raw `project_name` from `project.yml`. Inert AWS record-
key identifiers (IAM, SSM, DDB) preserve underscores.

These tests construct emits against a project whose name carries
underscores (`my_test_proj`) and assert the rendered output uses the
hyphenated form everywhere the data plane sees it. Existing fixtures use
`name: sample` (no underscores), so the bug pre-mod-046 was invisible to
them; this file's whole point is to surface it.

Coverage:

1. Env-tier compose emit — docker network names, OTel sidecar
   container names.
2. Project-tier compose emit — four `-web` networks, project traefik
   container, ACME volume.
3. HCL project-tier emit — Route53 zone, ACM cert domain_name + SANs.
4. HCL env-tier emit — Service Connect namespace name.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from docex.cicl.compile import CompiledEnv, CompiledService
from docex.emit.compose import emit_compose, emit_project_compose
from docex.emit.hcl import emit_hcl, emit_hcl_project
from docex.naming import NamingPolicies, NamingPolicy


def _policies() -> NamingPolicies:
    """The minimum naming-policy set the emitters reach for."""
    return NamingPolicies(by_name={
        "s3": NamingPolicy(
            name="s3", separator="hyphen", case="lower", max_len=63
        ),
        "rds": NamingPolicy(
            name="rds", separator="hyphen", case="lower", max_len=63
        ),
        "ddb": NamingPolicy(
            name="ddb", separator="underscore", case="any", max_len=255
        ),
        "alb": NamingPolicy(
            name="alb", separator="hyphen", case="any", max_len=32
        ),
        "ecs": NamingPolicy(
            name="ecs", separator="hyphen", case="any", max_len=255
        ),
        "iam": NamingPolicy(
            name="iam", separator="underscore", case="any", max_len=64
        ),
        "ssm_path": NamingPolicy(
            name="ssm_path", separator="underscore", case="any", max_len=1024
        ),
        "docker": NamingPolicy(
            name="docker", separator="hyphen", case="any", max_len=None
        ),
        "http_host": NamingPolicy(
            name="http_host", separator="hyphen", case="lower", max_len=None
        ),
    })


def _core_svc(
    project_dns_label: str, env: str, name: str,
    *, networks: list[str], port: int | None = 8080,
    foundation: str = "fixed",
) -> CompiledService:
    """Construct a minimal CompiledService for a core service."""
    global_name = f"{project_dns_label}-{env}-{name}"
    return CompiledService(
        name=name,
        role="web",
        engine="python",
        foundation=foundation,
        is_core=True,
        global_name=global_name,
        body={
            "image": f"my_test_proj/{name}:0.1.0",
            "container_name": global_name,
            "networks": networks,
            "restart": "unless-stopped",
            "logging": {"<<": "*default-logging"},
        },
        networks=networks,
        uses=[],
        port=port,
        env={},
        web_hosts=(
            [f"{name}.{env}.my-test-proj.example.com"]
            if "web" in networks else []
        ),
        emits={"elastic": ["task_definition", "ecs_service"]},
    )


def _compiled_env(
    env: str, *, foundation: str = "fixed",
    networks: set[str] | None = None,
) -> CompiledEnv:
    """Construct a CompiledEnv carrying an underscored project name."""
    nets = networks if networks is not None else {"web", "internal"}
    project = "my_test_proj"
    project_dns_label = "my-test-proj"
    svc = _core_svc(
        project_dns_label, env, "api",
        networks=sorted(nets),
        foundation=foundation,
    )
    return CompiledEnv(
        env=env,
        foundation=foundation,
        apex_domain="example.com",
        subdomain=f"{env}.my-test-proj.example.com",
        bare_project_subdomain="my-test-proj.example.com",
        project=project,
        project_dns_label=project_dns_label,
        project_version="0.1.0",
        container_registry=None,
        services={"api": svc},
        networks=set(nets),
        observability_backend_url="https://hyperdx.example.com",
        reverse_proxy="alb",
    )


# ---------------------------------------------------------------------------
# Env-tier compose
# ---------------------------------------------------------------------------


def test_env_compose_network_names_are_hyphenated(tmp_path: Path):
    """Env-tier docker networks must hyphenate the underscored project segment."""
    compiled = _compiled_env("dev")
    out = tmp_path / "docker-compose.yml"
    emit_compose(compiled, out)
    doc = yaml.safe_load(out.read_text())
    nets = doc["networks"]
    # `web` is external — references the project-tier `<project>-<env>-web`.
    assert nets["web"]["name"] == "my-test-proj-dev-web"
    assert nets["internal"]["name"] == "my-test-proj-dev-internal"
    # The buggy form must never appear.
    assert "my_test_proj-dev-web" not in out.read_text()
    assert "my_test_proj-dev-internal" not in out.read_text()


def test_env_compose_otel_sidecar_container_names_are_hyphenated(tmp_path: Path):
    """The paired OTel sidecar's container_name is a docker identifier — hyphenated."""
    compiled = _compiled_env("stage")
    out = tmp_path / "docker-compose.yml"
    emit_compose(compiled, out)
    doc = yaml.safe_load(out.read_text())
    # Sidecar service key and its container_name both go through the DNS label.
    expected = "my-test-proj-stage-api-otelcol"
    assert expected in doc["services"], sorted(doc["services"])
    assert doc["services"][expected]["container_name"] == expected
    # No underscored form anywhere in the rendered output.
    assert "my_test_proj-stage-api-otelcol" not in out.read_text()


# ---------------------------------------------------------------------------
# Project-tier compose
# ---------------------------------------------------------------------------


def test_project_compose_networks_and_traefik_are_hyphenated(tmp_path: Path):
    """Every name emitted at the project tier is a docker identifier."""
    out = tmp_path / "docker-compose.yml"
    emit_project_compose(project_dns_label="my-test-proj", out_path=out)
    doc = yaml.safe_load(out.read_text())
    # Four -web networks.
    for env in ("dev", "test", "stage", "prod"):
        net_key = f"my-test-proj-{env}-web"
        assert net_key in doc["networks"], (env, sorted(doc["networks"]))
        assert doc["networks"][net_key]["name"] == net_key
    # Project traefik service.
    traefik_key = "my-test-proj-traefik"
    assert traefik_key in doc["services"]
    assert doc["services"][traefik_key]["container_name"] == traefik_key
    # ACME volume — declared with an explicit ``name:`` so the real
    # docker volume is exactly ``<label>-traefik-acme`` (mod 053), not
    # a Compose-prefixed derivative.
    assert "my-test-proj-traefik-acme" in doc["volumes"]
    assert (
        doc["volumes"]["my-test-proj-traefik-acme"]["name"]
        == "my-test-proj-traefik-acme"
    )
    # No buggy form.
    text = out.read_text()
    assert "my_test_proj-traefik" not in text
    assert "my_test_proj-dev-web" not in text


# ---------------------------------------------------------------------------
# HCL project-tier emit
# ---------------------------------------------------------------------------


def test_project_hcl_route53_and_acm_use_dns_label(tmp_path: Path):
    """Route53 zone name and ACM cert domain_name / SANs must hyphenate."""
    out = tmp_path / "project.tf"
    emit_hcl_project(
        project="my_test_proj",
        project_version="0.1.0",
        apex_domain="example.com",
        codebase_names=["api"],
        naming_policies=_policies(),
        out_path=out,
        reverse_proxy="alb",
    )
    rendered = out.read_text()
    # Route53 zone name.
    assert 'name = "my-test-proj.example.com"' in rendered, rendered
    # ACM stage cert.
    assert (
        'domain_name = "*.stage.my-test-proj.example.com"'
        in rendered
    )
    assert '"stage.my-test-proj.example.com",' in rendered
    # ACM prod cert.
    assert 'domain_name = "*.prod.my-test-proj.example.com"' in rendered
    assert '"prod.my-test-proj.example.com",' in rendered
    assert '"my-test-proj.example.com",' in rendered
    # The buggy form (underscored project segment in a DNS name) must not appear.
    assert "my_test_proj.example.com" not in rendered


def test_project_hcl_ec2_traefik_dns_records_use_dns_label(tmp_path: Path):
    """EC2-traefik path also emits Route53 records keyed by DNS hostname."""
    out = tmp_path / "project.tf"
    emit_hcl_project(
        project="my_test_proj",
        project_version="0.1.0",
        apex_domain="example.com",
        codebase_names=["api"],
        naming_policies=_policies(),
        out_path=out,
        # PIP variant emits the boot-time Route53 update inside user_data,
        # which references the project subdomain — exercises both the HCL
        # template and the embedded user_data template.
        reverse_proxy="ec2_traefik_pip",
    )
    rendered = out.read_text()
    # The Route53 zone is shared with the ALB path.
    assert 'name = "my-test-proj.example.com"' in rendered
    # Five A-records driven by Jinja's traefik_records list.
    for fqdn in (
        '"my-test-proj.example.com"',
        '"*.prod.my-test-proj.example.com"',
        '"prod.my-test-proj.example.com"',
        '"*.stage.my-test-proj.example.com"',
        '"stage.my-test-proj.example.com"',
    ):
        assert f"name    = {fqdn}" in rendered, fqdn
    # The PIP-variant user_data resolves the zone by trailing-dot DNS form.
    assert "my-test-proj.example.com." in rendered
    # The buggy form (underscored project segment in a DNS context) must
    # not appear anywhere in the rendered HCL or embedded user_data.
    assert "my_test_proj.example.com" not in rendered


# ---------------------------------------------------------------------------
# HCL env-tier emit
# ---------------------------------------------------------------------------


def test_env_hcl_service_connect_namespace_uses_dns_label(tmp_path: Path):
    """Cloud Map private DNS namespaces resolve via Route53 — name must hyphenate."""
    compiled = _compiled_env("stage", foundation="elastic")
    out = tmp_path / "main.tf"
    emit_hcl(compiled, out, naming_policies=_policies())
    rendered = out.read_text()
    # Service Connect namespace name.
    assert 'name        = "my-test-proj-stage"' in rendered, rendered
    # The buggy form must not appear in the namespace block.
    assert 'name        = "my_test_proj-stage"' not in rendered

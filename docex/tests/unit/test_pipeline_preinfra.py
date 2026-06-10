"""Unit tests for ``docex.pipeline.preinfra``.

Mod 042 replaces the mod 034 stub with real per-(foundation, side)
checks. The runner enumerates every failure in one pass and only
needs an AWS client when the project is elastic and the side is
production.
"""

from __future__ import annotations

import pytest

from docex.pipeline.preinfra import (
    _DOCEX_INGRESS_NETWORK,
    _MASTER_VPC_TAGS,
    _PRIMARY_AZ,
    run_preinfra,
)


def _seed_deploy_keys(ctx, *, envs=("stage", "prod")) -> dict[str, str]:
    """Create ``infra/deploy_creds/<env>`` private keys in ``ctx`` and
    return the apex-derived host for each env (fixed registry probe)."""
    from docex.naming import dns_label

    creds = ctx.project_root / "infra" / "deploy_creds"
    creds.mkdir(parents=True, exist_ok=True)
    label = dns_label(ctx.project.name)
    hosts: dict[str, str] = {}
    for env in envs:
        (creds / env).write_text("PRIVATE KEY")
        if env == "stage":
            hosts[env] = f"stage.{label}.{ctx.infra.apex_domain}"
        else:
            hosts[env] = f"{label}.{ctx.infra.apex_domain}"
    return hosts


# ---------------------------------------------------------------------------
# Helpers — script the FakeAWSClient into a "healthy master VPC" state.
# ---------------------------------------------------------------------------


def _script_healthy_master_vpc(
    fake_aws, *, vpc_id: str = "vpc-master-001",
    public_subnets: list[str] | None = None,
    private_subnets: list[str] | None = None,
    primary_subnet: str | None = "subnet-priv-a",
) -> None:
    """Populate ``fake_aws`` so the elastic-prod preinfra path passes."""
    public_subnets = public_subnets or ["subnet-pub-a", "subnet-pub-b"]
    private_subnets = private_subnets or ["subnet-priv-a", "subnet-priv-b"]
    fake_aws.find_vpc_by_tags_result = vpc_id
    fake_aws.find_subnet_ids_results = {
        (vpc_id, (("tier", "public"),), None): public_subnets,
        (vpc_id, (("tier", "private"),), None): private_subnets,
        (vpc_id, (("tier", "private"),), _PRIMARY_AZ):
            [primary_subnet] if primary_subnet else [],
    }


# ---------------------------------------------------------------------------
# Development side (any foundation)
# ---------------------------------------------------------------------------


def test_preinfra_dev_passes_when_bridge_exists(
    sample_ctx, fake_docker, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(sample_ctx, fake_docker, aws=None, side="development")
    assert rc == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out


def test_preinfra_dev_fails_when_bridge_missing(
    sample_ctx, fake_docker, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    rc = run_preinfra(sample_ctx, fake_docker, aws=None, side="development")
    assert rc == 1
    out = capsys.readouterr().out
    assert _DOCEX_INGRESS_NETWORK in out
    assert "docker network create" in out


def test_preinfra_dev_does_not_call_aws(
    sample_ctx, fake_docker, fake_aws,
):
    """Even when aws is provided, dev side never invokes AWS methods —
    the foundation+side gate short-circuits."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(sample_ctx, fake_docker, aws=fake_aws, side="development")
    assert rc == 0
    # No AWS call recorded.
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert "find_vpc_by_tags" not in aws_method_names
    assert "find_subnet_ids" not in aws_method_names


# ---------------------------------------------------------------------------
# Fixed production side
# ---------------------------------------------------------------------------


def test_preinfra_fixed_prod_checks_docker_not_aws(
    sample_ctx, fake_docker, fake_aws, fake_ssh,
):
    """Fixed-foundation production side never performs AWS lookups
    (the registry-cred probe goes over SSH, not AWS)."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {h: 0 for h in hosts.values()}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=fake_aws, side="production", ssh=fake_ssh,
    )
    assert rc == 0
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert "find_vpc_by_tags" not in aws_method_names


def test_preinfra_fixed_prod_fails_when_bridge_missing(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {h: 0 for h in hosts.values()}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert _DOCEX_INGRESS_NETWORK in out


# ---------------------------------------------------------------------------
# Fixed production side — registry-cred SSH probe (Gap G, mod 050)
# ---------------------------------------------------------------------------


def test_preinfra_fixed_prod_registry_creds_present(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """Both hosts report the cred present → no registry failure, and
    both stage and prod hosts were probed."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {h: 0 for h in hosts.values()}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 0
    probed_hosts = {c[1] for c in fake_ssh.calls if c[0] == "run"}
    assert probed_hosts == set(hosts.values())


def test_preinfra_fixed_prod_registry_creds_missing(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """A non-zero (≠255) exit → 'registry credentials not found … run
    docker login' failure."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    # stage host healthy, prod host reports cred missing (exit 1).
    fake_ssh.results = {hosts["stage"]: 0, hosts["prod"]: 1}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "registry credentials not found" in out
    assert "docker login" in out
    assert hosts["prod"] in out


def test_preinfra_fixed_prod_host_unreachable(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """SSH connect failure (255) → distinct 'could not reach … host'
    failure."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {hosts["stage"]: 0, hosts["prod"]: 255}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "could not reach" in out
    assert hosts["prod"] in out


def test_preinfra_fixed_prod_deploy_key_absent(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """A missing ``infra/deploy_creds/<env>`` → 'missing … needed to
    reach' failure, and that env's host is not probed over SSH."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    # Seed only the stage key; remove the prod key the sample fixture ships.
    (sample_ctx.project_root / "infra" / "deploy_creds" / "prod").unlink()
    hosts = _seed_deploy_keys(sample_ctx, envs=("stage",))
    fake_ssh.results = {hosts["stage"]: 0}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "infra/deploy_creds/prod missing" in out
    # The prod host was skipped — only the stage host was probed.
    probed_hosts = {c[1] for c in fake_ssh.calls if c[0] == "run"}
    prod_host = f"{sample_ctx.project.name}.{sample_ctx.infra.apex_domain}".replace("_", "-").lower()
    assert prod_host not in probed_hosts


def test_preinfra_fixed_prod_with_none_ssh_reports_bug(
    sample_ctx, fake_docker, capsys,
):
    """The dispatcher must construct an SSH client on this branch; if it
    doesn't, preinfra surfaces it as an explicit bug (mirrors aws)."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(sample_ctx, fake_docker, aws=None, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "dispatcher bug" in out


# ---------------------------------------------------------------------------
# Elastic production side
# ---------------------------------------------------------------------------


def test_preinfra_elastic_prod_passes(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(fake_aws)
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out
    # VPC + 3 subnet lookups were performed.
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert aws_method_names.count("find_vpc_by_tags") == 1
    assert aws_method_names.count("find_subnet_ids") == 3
    # The VPC lookup used the doctrine-prescribed tag set.
    vpc_call = next(c for c in fake_aws.calls if c[0] == "find_vpc_by_tags")
    assert vpc_call[1][0] == _MASTER_VPC_TAGS


def test_preinfra_elastic_prod_fails_when_vpc_missing(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_aws.find_vpc_by_tags_result = None
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "master VPC not found" in out
    # Bails on VPC lookup — no subnet lookups attempted.
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert "find_subnet_ids" not in aws_method_names


def test_preinfra_elastic_prod_fails_when_insufficient_public_subnets(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(fake_aws, public_subnets=["subnet-pub-a"])
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "public subnet" in out
    assert "at least 2" in out


def test_preinfra_elastic_prod_fails_when_insufficient_private_subnets(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(
        fake_aws,
        private_subnets=["subnet-priv-a"],
        # Primary still resolves so we isolate the count-shortfall message.
        primary_subnet="subnet-priv-a",
    )
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "private subnet" in out
    assert "at least 2" in out


def test_preinfra_elastic_prod_fails_when_no_primary_az_subnet(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(fake_aws, primary_subnet=None)
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert _PRIMARY_AZ in out
    assert "primary AZ" in out


def test_preinfra_elastic_prod_enumerates_multiple_failures(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    """Bridge missing AND insufficient subnets → both reported in one pass."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    _script_healthy_master_vpc(
        fake_aws,
        public_subnets=["subnet-pub-a"],   # short
        private_subnets=["subnet-priv-a"], # short
        primary_subnet=None,               # primary missing
    )
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    # 4 failures: bridge + 2x subnet shortage + primary AZ missing.
    assert "4 check(s) failed" in out


def test_preinfra_elastic_prod_with_none_aws_reports_bug(
    elastic_ctx, fake_docker, capsys,
):
    """The dispatcher is supposed to construct an AWS client on this
    branch; if it doesn't, preinfra surfaces it as an explicit bug
    rather than silently skipping the elastic checks."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(elastic_ctx, fake_docker, aws=None, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "dispatcher bug" in out


# ---------------------------------------------------------------------------
# Doctrine-prescribed tag scheme guard
# ---------------------------------------------------------------------------


def test_master_vpc_tag_scheme_matches_doctrine():
    """Mod 041's project.tf.j2 data sources filter on these exact tags.
    Drift here would break the elastic prod data-source lookup."""
    assert _MASTER_VPC_TAGS == {
        "Name": "docex-master-vpc",
        "managed_by": "docex-preinfra",
    }
    assert _PRIMARY_AZ == "us-east-1a"
    assert _DOCEX_INGRESS_NETWORK == "docex-ingress"

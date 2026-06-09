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


def test_preinfra_fixed_prod_only_checks_docker(
    sample_ctx, fake_docker, fake_aws,
):
    """Fixed-foundation production side requires only the docker
    bridge — no AWS lookups."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(sample_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 0
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert "find_vpc_by_tags" not in aws_method_names


def test_preinfra_fixed_prod_fails_when_bridge_missing(
    sample_ctx, fake_docker, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    rc = run_preinfra(sample_ctx, fake_docker, aws=None, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert _DOCEX_INGRESS_NETWORK in out


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

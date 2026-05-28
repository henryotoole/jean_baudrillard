"""Focused unit tests for the Phase 4 HCL emitter fixes.

End-to-end structural correctness of the emitted HCL is covered by the
``tofu validate`` integration test. These unit tests cover the
compile-time validations and emission decisions that wouldn't show up
in tofu validate because they short-circuit before HCL emission, or
because they target specific substrings the validator can't easily
flag.

Each test maps to one of the Step 4 sub-fixes in phase_4.md:

  4a — no semicolons in HCL blocks (covered by tofu validate)
  4b — Fargate (cpu, memory) pair validation (here, compile-time)
  4c — ephemeral_storage floor of 21 GiB (here, compile-time)
  4d — $[VAR] -> ECS secrets[] block (here, substring check)
  4e — RDS password via data.aws_ssm_parameter (here, substring check)
  4f — listener_rule host_header is env_subdomain (here, substring check)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.cicl.fargate import fargate_pair
from docex.context import load_project_context
from docex.errors import ValidationError


_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_project_elastic"
)


# ---------------------------------------------------------------------------
# 4b — Fargate (cpu, memory) pair validation.
# ---------------------------------------------------------------------------


def test_fargate_pair_maps_1vcpu_2gb_to_valid_combo():
    """1.0 vCPU + 2GB must map to the valid Fargate pair (1024, 2048)."""
    cpu_units, memory_mib = fargate_pair(1.0, "2GB", service_name="api")
    assert cpu_units == 1024
    assert memory_mib == 2048


def test_fargate_pair_rounds_memory_up_to_valid_value():
    """1.5 GB is not a valid Fargate memory; must round up to 2048 MiB."""
    _cpu, memory_mib = fargate_pair(1.0, "1.5GB", service_name="api")
    assert memory_mib >= 2048
    # And it must be a valid Fargate memory value for 1024 cpu.
    from docex.cicl.fargate import _allowed_memory_mib
    assert memory_mib in _allowed_memory_mib(1024)


def test_fargate_pair_rounds_cpu_up_to_fit_memory():
    """0.25 vCPU + 16 GB needs more CPU than the user requested — the
    validator rounds CPU up rather than failing, since the user's intent
    (give me ~16 GB) is honored. Memory is in MiB; 16 decimal GB is
    ~15259 MiB, which is below 16384 MiB."""
    cpu_units, memory_mib = fargate_pair(0.25, "16GB", service_name="bigapi")
    # 16 GB (decimal) ≈ 15259 MiB; Fargate rounds up to the next valid bucket.
    assert memory_mib >= 15259, "memory must satisfy at least the requested 16 GB"
    assert cpu_units >= 1024, "CPU must have been bumped up to fit the memory"


def test_fargate_pair_rejects_memory_above_max():
    """250 GB exceeds Fargate's 120 GiB ceiling — must raise."""
    with pytest.raises(ValidationError):
        fargate_pair(1.0, "250GB", service_name="bigapi")


# ---------------------------------------------------------------------------
# 4c — ephemeral_storage floor.
# ---------------------------------------------------------------------------


def test_elastic_disk_below_floor_fails_compile(tmp_path: Path):
    """disk: 10GB on an elastic project must fail compile.

    Fargate's ephemeral_storage minimum is 21 GiB. The Phase 1 emitter
    silently rounded; Phase 4 fails loudly.
    """
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    infra_yml = dest / "infra" / "infra.yml"
    infra_yml.write_text(
        infra_yml.read_text().replace("disk: 25GB", "disk: 10GB")
    )
    ctx = load_project_context(dest)
    with pytest.raises(ValidationError):
        run_compile(ctx)


def test_elastic_disk_omitted_compiles(tmp_path: Path):
    """Omitting disk: on elastic is allowed (Fargate defaults to 21 GiB)."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    infra_yml = dest / "infra" / "infra.yml"
    # Drop the disk line entirely.
    new_text = "\n".join(
        line for line in infra_yml.read_text().splitlines()
        if not line.strip().startswith("disk:")
    )
    infra_yml.write_text(new_text)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    prod_tf = (dest / "infra" / "output" / "prod" / "main.tf").read_text()
    # ephemeral_storage block should be omitted entirely.
    assert "ephemeral_storage" not in prod_tf


# ---------------------------------------------------------------------------
# 4d — $[VAR] -> ECS secrets[] block.
# ---------------------------------------------------------------------------


@pytest.fixture
def compiled_prod_tf(tmp_path: Path) -> str:
    """Compile the elastic fixture and return prod main.tf as text."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    return (dest / "infra" / "output" / "prod" / "main.tf").read_text()


def test_elastic_emits_caller_identity_data_source(compiled_prod_tf: str):
    """The data source backing every secrets[] ARN must be emitted."""
    assert 'data "aws_caller_identity" "current"' in compiled_prod_tf


def test_elastic_image_uses_ecr_when_no_registry(compiled_prod_tf: str):
    """With no container_registry, the elastic image ref resolves to the
    project ECR repo URL emitted by the project-tier HCL (read via
    terraform_remote_state), never the <project-ecr> placeholder."""
    tf = compiled_prod_tf
    assert "<project-ecr>" not in tf
    assert (
        "data.terraform_remote_state.project.outputs.ecr_repository_api_url"
        in tf
    )
    assert ":0.1.0" in tf


def test_elastic_secret_named_by_consumer_key(compiled_prod_tf: str):
    """Model-A symmetry: a referenced secret part becomes an ECS secret
    named after the *consumer's* env key (``DATABASE_USER``), with
    ``valueFrom`` pointing at the underlying secret's SSM path
    (``POSTGRES_USER``). The app must never receive the engine's bare var
    name — that would diverge from the fixed/compose side."""
    tf = compiled_prod_tf
    assert 'name = "DATABASE_USER"' in tf
    assert 'name = "DATABASE_PASSWORD"' in tf
    # valueFrom carries the engine's canonical SSM key, not the app's name.
    assert "/prod/POSTGRES_USER" in tf
    assert "/prod/POSTGRES_PASSWORD" in tf
    # The engine's bare var name must NOT be a container env/secret name.
    assert 'name = "POSTGRES_USER"' not in tf
    assert 'name = "POSTGRES_PASSWORD"' not in tf


def test_elastic_does_not_emit_literal_runtime_refs(compiled_prod_tf: str):
    """No ``$[VAR]`` should survive to the emitted HCL.

    All runtime refs must translate to either ``secrets[]`` entries
    (for core services) or ``data.aws_ssm_parameter`` references (for
    backing services).
    """
    assert "$[" not in compiled_prod_tf, (
        "found unresolved $[VAR] in emitted HCL; "
        "Step 4d / 4e translation incomplete"
    )


# ---------------------------------------------------------------------------
# 4e — RDS password via data.aws_ssm_parameter.
# ---------------------------------------------------------------------------


def test_elastic_rds_password_uses_ssm_data_source(compiled_prod_tf: str):
    """The aws_db_instance must reference an SSM data source for password,
    not a literal string."""
    assert 'data "aws_ssm_parameter" "database_postgres_password"' in compiled_prod_tf
    # And the resource must reference it.
    assert "data.aws_ssm_parameter.database_postgres_password.value" in compiled_prod_tf


def test_elastic_rds_username_uses_ssm_data_source(compiled_prod_tf: str):
    """Same pattern for username."""
    assert 'data "aws_ssm_parameter" "database_postgres_user"' in compiled_prod_tf
    assert "data.aws_ssm_parameter.database_postgres_user.value" in compiled_prod_tf


# ---------------------------------------------------------------------------
# 4f — listener_rule host_header uses env_subdomain.
# ---------------------------------------------------------------------------


def test_elastic_listener_rule_uses_per_service_hosts(compiled_prod_tf: str):
    """For prod, the default web service's listener rule matches both the
    bare env subdomain and its per-service host (dual-host)."""
    assert 'values = ["www.example.com", "api.www.example.com"]' in compiled_prod_tf
    # The env name must never appear as a host.
    assert 'values = ["prod"]' not in compiled_prod_tf


def test_elastic_stage_listener_rule_uses_per_service_hosts(tmp_path: Path):
    """Same dual-host for stage."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    stage_tf = (dest / "infra" / "output" / "stage" / "main.tf").read_text()
    assert 'values = ["stage.example.com", "api.stage.example.com"]' in stage_tf
    assert 'values = ["stage"]' not in stage_tf


# ---------------------------------------------------------------------------
# v0.6.0 — project-tier HCL + env-tier terraform_remote_state references.
# ---------------------------------------------------------------------------


@pytest.fixture
def compiled_elastic_project(tmp_path: Path) -> Path:
    """Compile the elastic fixture; return the project root."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    return dest


def test_project_main_tf_written(compiled_elastic_project: Path):
    """Elastic compile writes a project-tier main.tf."""
    project_tf = compiled_elastic_project / "infra" / "output" / "project" / "main.tf"
    assert project_tf.is_file()


def test_project_main_tf_has_zone_vpc_cert_ecr(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "main.tf").read_text()
    assert 'resource "aws_route53_zone" "project"' in tf
    assert 'resource "aws_vpc" "project"' in tf
    assert 'resource "aws_acm_certificate" "project"' in tf
    assert 'resource "aws_acm_certificate_validation" "project"' in tf
    # ECR repo for the `api` core service from the elastic fixture.
    assert 'resource "aws_ecr_repository" "api"' in tf


def test_project_main_tf_uses_project_state_key(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "main.tf").read_text()
    # Distinct state key so env-tier and project-tier states don't collide.
    assert 'key            = "project/terraform.tfstate"' in tf


def test_project_main_tf_emits_outputs(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "main.tf").read_text()
    for out_name in (
        "vpc_id",
        "public_subnet_ids",
        "private_subnet_ids",
        "zone_id",
        "zone_name_servers",
        "certificate_arn",
        "ecr_repository_api_url",
    ):
        assert f'output "{out_name}"' in tf, f"missing output {out_name!r}"


def test_env_main_tf_consumes_project_remote_state(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "prod" / "main.tf").read_text()
    assert 'data "terraform_remote_state" "project"' in tf
    assert 'key    = "project/terraform.tfstate"' in tf
    # And the old tag-based data sources are gone.
    assert 'data "aws_vpc" "project"' not in tf
    assert 'data "aws_acm_certificate" "project"' not in tf
    assert 'data "aws_route53_zone" "project"' not in tf
    assert 'data "aws_subnets"' not in tf


def test_env_main_tf_references_remote_state_outputs(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "prod" / "main.tf").read_text()
    assert "data.terraform_remote_state.project.outputs.vpc_id" in tf
    assert "data.terraform_remote_state.project.outputs.public_subnet_ids" in tf
    assert "data.terraform_remote_state.project.outputs.private_subnet_ids" in tf
    assert "data.terraform_remote_state.project.outputs.zone_id" in tf
    assert "data.terraform_remote_state.project.outputs.certificate_arn" in tf


def test_fixed_compile_skips_project_main_tf(tmp_path: Path):
    """Fixed-foundation projects don't need project-tier HCL."""
    fixed_fixture = (
        Path(__file__).resolve().parent.parent / "fixtures" / "sample_project"
    )
    if not fixed_fixture.is_dir():
        pytest.skip("no fixed fixture available")
    dest = tmp_path / "project"
    shutil.copytree(fixed_fixture, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    project_dir = dest / "infra" / "output" / "project"
    # Either the directory wasn't created or it's empty.
    assert not project_dir.exists() or not list(project_dir.iterdir())

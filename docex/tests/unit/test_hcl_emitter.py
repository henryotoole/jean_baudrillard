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
    assert 'data "aws_ssm_parameter" "appdb_postgres_password"' in compiled_prod_tf
    # And the resource must reference it.
    assert "data.aws_ssm_parameter.appdb_postgres_password.value" in compiled_prod_tf


def test_elastic_rds_username_uses_ssm_data_source(compiled_prod_tf: str):
    """Same pattern for username."""
    assert 'data "aws_ssm_parameter" "appdb_postgres_user"' in compiled_prod_tf
    assert "data.aws_ssm_parameter.appdb_postgres_user.value" in compiled_prod_tf


# ---------------------------------------------------------------------------
# 4f — listener_rule host_header uses env_subdomain.
# ---------------------------------------------------------------------------


def test_elastic_listener_rule_uses_per_service_hosts(compiled_prod_tf: str):
    """For prod, the default web service's listener rule matches the
    per-service host, the bare env subdomain, AND the bare-project host
    (the new mod 031 triple). Order is most-specific → least-specific."""
    assert (
        'values = ["api.prod.sample.example.com", '
        '"prod.sample.example.com", "sample.example.com"]'
        in compiled_prod_tf
    )
    # The env name must never appear as a host.
    assert 'values = ["prod"]' not in compiled_prod_tf


def test_elastic_stage_listener_rule_uses_per_service_hosts(tmp_path: Path):
    """For non-prod envs, the default web service's listener rule matches
    only the per-service host and the bare env subdomain — no bare-project
    third (mod 031 routes that solely to prod)."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    stage_tf = (dest / "infra" / "output" / "stage" / "main.tf").read_text()
    assert (
        'values = ["api.stage.sample.example.com", '
        '"stage.sample.example.com"]'
        in stage_tf
    )
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
    project_tf = compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf"
    assert project_tf.is_file()


def test_project_main_tf_has_zone_vpc_cert_ecr(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    assert 'resource "aws_route53_zone" "project"' in tf
    assert 'resource "aws_vpc" "project"' in tf
    # Mod 037: cert split into stage and prod; no more single `project` cert.
    assert 'resource "aws_acm_certificate" "stage"' in tf
    assert 'resource "aws_acm_certificate" "prod"' in tf
    assert 'resource "aws_acm_certificate_validation" "stage"' in tf
    assert 'resource "aws_acm_certificate_validation" "prod"' in tf
    assert 'resource "aws_acm_certificate" "project"' not in tf
    # ECR repo for the `api` core service from the elastic fixture.
    assert 'resource "aws_ecr_repository" "api"' in tf


def test_project_route53_zone_name_is_project_subdomain(compiled_elastic_project: Path):
    """Mod 037: the project's hosted zone covers `<project>.<apex_domain>`,
    not the bare apex (which belongs to whoever owns the registrar account)."""
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    # Fixture: project name `sample`, apex `example.com`.
    assert 'name = "sample.example.com"' in tf
    # Bare apex is no longer the zone name.
    assert 'name = "example.com"' not in tf


def test_project_stage_cert_sans(compiled_elastic_project: Path):
    """Mod 037: stage cert covers `*.stage.<project>.<apex>` + ergonomic
    `stage.<project>.<apex>`. Nothing else."""
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    assert 'domain_name = "*.stage.sample.example.com"' in tf
    assert '"stage.sample.example.com",' in tf


def test_project_prod_cert_sans(compiled_elastic_project: Path):
    """Mod 037: prod cert covers `*.prod.<project>.<apex>` + ergonomic
    `prod.<project>.<apex>` + bare-project `<project>.<apex>`."""
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    assert 'domain_name = "*.prod.sample.example.com"' in tf
    assert '"prod.sample.example.com",' in tf
    assert '"sample.example.com",' in tf


def test_project_main_tf_no_obsolete_cert_sans(compiled_elastic_project: Path):
    """The pre-mod-037 single cert had `*.dev`, `*.test`, and `*.www` SANs.
    Those are obsolete — dev/test never reach the ALB, `www` was dropped."""
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    assert "*.dev.example.com" not in tf
    assert "*.test.example.com" not in tf
    assert "*.www" not in tf
    # The old apex-wildcard form is also gone.
    assert 'domain_name = "*.example.com"' not in tf


def test_project_main_tf_uses_project_state_key(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    # Distinct state key so env-tier and project-tier states don't collide.
    assert 'key            = "project/terraform.tfstate"' in tf


def test_project_main_tf_emits_outputs(compiled_elastic_project: Path):
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    for out_name in (
        "vpc_id",
        "public_subnet_ids",
        "private_subnet_ids",
        "zone_id",
        "zone_name_servers",
        # Mod 037: per-env cert ARN outputs replace the single `certificate_arn`.
        "stage_cert_arn",
        "prod_cert_arn",
        "ecr_repository_api_url",
    ):
        assert f'output "{out_name}"' in tf, f"missing output {out_name!r}"
    # And the old single-cert output is gone.
    assert 'output "certificate_arn"' not in tf


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
    assert "data.terraform_remote_state.project.outputs.private_subnet_ids" in tf
    assert "data.terraform_remote_state.project.outputs.zone_id" in tf
    # Mod 038: the ALB moved to the project tier. Env-tier consumes its
    # DNS+zone for Route53 alias records, the HTTPS listener ARN for
    # listener rules, and the SG ID for per-network ingress sources.
    assert "data.terraform_remote_state.project.outputs.alb_dns_name" in tf
    assert "data.terraform_remote_state.project.outputs.alb_zone_id" in tf
    assert "data.terraform_remote_state.project.outputs.alb_https_listener_arn" in tf
    assert "data.terraform_remote_state.project.outputs.alb_security_group_id" in tf
    # Mod 038: env-tier no longer references cert ARNs — the project ALB
    # listener owns both certs (prod default + stage SNI binding).
    assert "data.terraform_remote_state.project.outputs.prod_cert_arn" not in tf
    assert "data.terraform_remote_state.project.outputs.stage_cert_arn" not in tf
    # The old single-cert output reference is gone.
    assert "outputs.certificate_arn" not in tf
    # Mod 038: env-tier no longer references public_subnet_ids — the
    # project ALB owns the public subnets.
    assert "outputs.public_subnet_ids" not in tf


def test_stage_env_main_tf_no_cert_ref(compiled_elastic_project: Path):
    """Mod 038: env-tier no longer references cert ARNs; the project
    ALB listener owns both certs (prod default + stage SNI binding)."""
    tf = (compiled_elastic_project / "infra" / "output" / "stage" / "main.tf").read_text()
    assert "data.terraform_remote_state.project.outputs.stage_cert_arn" not in tf
    assert "data.terraform_remote_state.project.outputs.prod_cert_arn" not in tf
    assert "outputs.certificate_arn" not in tf


# ---------------------------------------------------------------------------
# Mod 010 — health_check block on aws_lb_target_group from target_extras.
# ---------------------------------------------------------------------------


def test_aws_lb_target_group_emits_health_check_from_target_extras(tmp_path: Path):
    """When a web-network service declares `health_check_path`, the emitted
    `aws_lb_target_group` HCL must include a nested `health_check { ... }`
    block — not a stray `target_group_health_check` key on the task
    definition. This is the bug mod 010 closes.
    """
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    # Patch the fixture's `web`/`api` service to declare a health check.
    infra_yml = dest / "infra" / "infra.yml"
    infra_yml.write_text(
        infra_yml.read_text().replace(
            "    networks: [web, internal]\n",
            "    networks: [web, internal]\n    health_check_path: /health\n",
            1,
        )
    )
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    tf = (dest / "infra" / "output" / "prod" / "main.tf").read_text()
    # Target group exists and carries a health_check sub-block.
    assert 'resource "aws_lb_target_group" "api"' in tf
    assert "health_check {" in tf
    assert 'path = "/health"' in tf
    assert "healthy_threshold = 2" in tf
    assert "interval = 30" in tf
    # The pre-mod-010 wrapper key must never reach the task definition.
    assert "target_group_health_check" not in tf


def test_aws_lb_target_group_omits_health_check_when_no_field(tmp_path: Path):
    """Services that do not declare `health_check_path` produce a target
    group with no `health_check` block — preserves the prior shape for
    services that opt out."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    tf = (dest / "infra" / "output" / "prod" / "main.tf").read_text()
    assert 'resource "aws_lb_target_group" "api"' in tf
    # No health_check block emitted when no field was declared.
    # (We have to be careful: an aws_db_instance might also emit a
    # `health_check` block in some templates, so scope by service.)
    tg_block_start = tf.find('resource "aws_lb_target_group" "api"')
    tg_block_end = tf.find("}", tg_block_start) + 1
    tg_block = tf[tg_block_start:tg_block_end]
    assert "health_check" not in tg_block


def test_fixed_compile_skips_project_main_tf(tmp_path: Path):
    """Fixed-foundation projects don't emit a project-tier main.tf — the
    production-side output is a compose file, not HCL (mod 035)."""
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
    # No production-side main.tf on fixed; the production side gets a
    # docker-compose.yml instead (verified by other tests).
    assert not (
        dest / "infra" / "output" / "project" / "production" / "main.tf"
    ).exists()


# ---------------------------------------------------------------------------
# Mod 011 — PROJECT_VERSION injected into core service ECS task definitions.
# ---------------------------------------------------------------------------


def test_core_service_task_definition_environment_carries_project_version(
    compiled_prod_tf: str,
):
    """Every core service's ECS task definition environment[] carries
    PROJECT_VERSION sourced from project.yml.version, as a literal value
    (not an SSM secret). Mod 011."""
    tf = compiled_prod_tf
    # PROJECT_VERSION appears as a plain ECS environment[] entry with the
    # fixture's project.yml version "0.1.0".
    assert 'name = "PROJECT_VERSION"' in tf
    assert 'value = "0.1.0"' in tf
    # It must NOT be wired as a secret (no SSM lookup for it).
    assert "/prod/PROJECT_VERSION" not in tf


# ---------------------------------------------------------------------------
# Mod 014 — ECS Service Connect namespace per env.
# ---------------------------------------------------------------------------


def test_service_connect_namespace_emitted_per_env(compiled_prod_tf: str):
    """Mod 014: one aws_service_discovery_http_namespace per env, named
    `<project>-<env>` (mod 030: data-plane resolvable name, hyphen).
    The elastic fixture's project name is `sample`."""
    tf = compiled_prod_tf
    assert 'resource "aws_service_discovery_http_namespace" "env"' in tf
    assert 'name        = "sample-prod"' in tf


def test_service_connect_namespace_emitted_for_stage(tmp_path: Path):
    """Same namespace resource appears in stage main.tf with the stage-suffixed name."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    stage_tf = (dest / "infra" / "output" / "stage" / "main.tf").read_text()
    assert 'resource "aws_service_discovery_http_namespace" "env"' in stage_tf
    assert 'name        = "sample-stage"' in stage_tf


def test_backing_service_hcl_lacks_project_version(compiled_prod_tf: str):
    """Backing services do NOT receive PROJECT_VERSION on elastic — RDS's
    aws_db_instance carries engine credentials, never the project version.
    The fixture's only backing service is `appdb`; scan its block and
    confirm the var isn't present. Mod 011."""
    tf = compiled_prod_tf
    rds_start = tf.find('resource "aws_db_instance" "appdb"')
    assert rds_start != -1, "expected aws_db_instance.appdb in elastic HCL"
    # Find the matching close brace at column 0 for the resource block.
    rds_end = tf.find("\n}\n", rds_start)
    assert rds_end != -1
    rds_block = tf[rds_start:rds_end]
    assert "PROJECT_VERSION" not in rds_block, rds_block


# ---------------------------------------------------------------------------
# Mod 038 — project-tier ALB; listener rules stay env-tier with banded
# priorities (stage [1000, 4999], prod [5000, 9999]).
# ---------------------------------------------------------------------------


def test_mod038_env_listener_rule_uses_remote_state_listener_arn(
    compiled_prod_tf: str,
):
    """The env-tier `aws_lb_listener_rule.listener_arn` references the
    project-tier ALB's HTTPS listener via remote state, never the
    deleted env-tier `aws_lb_listener.alb_https.arn`."""
    tf = compiled_prod_tf
    assert "data.terraform_remote_state.project.outputs.alb_https_listener_arn" in tf
    assert "aws_lb_listener.alb_https.arn" not in tf


def test_mod038_prod_listener_rule_priority_in_prod_band(compiled_prod_tf: str):
    """Prod env's listener-rule priorities live in `[5000, 9999]`. The
    elastic fixture has one web service (`api`), so the rule lands at
    the band's base (5000)."""
    tf = compiled_prod_tf
    assert "priority     = 5000" in tf
    # Pre-mod-038 base (100) must not survive.
    assert "priority     = 100\n" not in tf


def test_mod038_stage_listener_rule_priority_in_stage_band(tmp_path: Path):
    """Stage env's listener-rule priorities live in `[1000, 4999]`. The
    elastic fixture has one web service, so the rule lands at 1000."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    tf = (dest / "infra" / "output" / "stage" / "main.tf").read_text()
    assert "priority     = 1000" in tf
    assert "priority     = 100\n" not in tf


def test_mod038_project_tier_has_alb_set(compiled_elastic_project: Path):
    """Project-tier main.tf carries the ALB SG, the ALB, both listeners,
    and the stage SNI listener_certificate."""
    tf = (
        compiled_elastic_project
        / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert 'resource "aws_security_group" "project_alb"' in tf
    assert 'resource "aws_lb" "project"' in tf
    assert 'resource "aws_lb_listener" "project_https"' in tf
    assert 'resource "aws_lb_listener_certificate" "project_stage"' in tf
    assert 'resource "aws_lb_listener" "project_http"' in tf
    # HTTPS listener default cert = prod; stage cert attaches via
    # aws_lb_listener_certificate.
    assert "certificate_arn   = aws_acm_certificate_validation.prod.certificate_arn" in tf
    assert "certificate_arn = aws_acm_certificate_validation.stage.certificate_arn" in tf


def test_mod038_project_tier_alb_outputs_present(compiled_elastic_project: Path):
    """Six project-tier ALB outputs are exposed for env-tier remote-state
    consumption."""
    tf = (
        compiled_elastic_project
        / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    for out_name in (
        "alb_arn",
        "alb_dns_name",
        "alb_zone_id",
        "alb_https_listener_arn",
        "alb_http_listener_arn",
        "alb_security_group_id",
    ):
        assert f'output "{out_name}"' in tf, f"missing project output {out_name!r}"

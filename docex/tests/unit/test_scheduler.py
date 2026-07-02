"""Tests for the scheduler role (mod 055).

Covers the fixed (ofelia) compose emit, the elastic (EventBridge
Scheduler + RunTask) HCL emit, the OTel-sidecar omission scoped to
one-shot tasks, and the scheduler-specific validation rules.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from docex.cicl.compile import run_compile
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.context import load_project_context


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project_scheduler_fixed"
_ELASTIC = _FIXTURES / "sample_project_scheduler_elastic"


def _copy(fixture: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest


def _compile(fixture: Path, tmp_path: Path) -> Path:
    root = _copy(fixture, tmp_path)
    run_compile(load_project_context(root))
    return root


# ---------------------------------------------------------------------------
# Fixed (ofelia) compose emit
# ---------------------------------------------------------------------------


def _dev_compose(root: Path) -> dict:
    return yaml.safe_load(
        (root / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    )


def test_fixed_emits_ofelia_container(tmp_path: Path):
    doc = _dev_compose(_compile(_FIXED, tmp_path))
    svc = doc["services"]["sample-dev-nightly_cleanup-scheduler"]
    assert svc["image"].startswith("mcuadros/ofelia:")
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in svc["volumes"]
    # No traefik labels — a scheduler is never web-facing.
    assert svc["labels"] == ["docex.project=sample"]
    assert svc["restart"] == "unless-stopped"


def test_fixed_no_long_running_block_for_job(tmp_path: Path):
    """The scheduler job itself is NOT emitted as a normal service block —
    only the paired ofelia container is. No otelcol sidecar either."""
    doc = _dev_compose(_compile(_FIXED, tmp_path))
    services = doc["services"]
    assert "sample-dev-nightly_cleanup" not in services
    assert "sample-dev-nightly_cleanup-otelcol" not in services
    # The ofelia container IS present.
    assert "sample-dev-nightly_cleanup-scheduler" in services


def test_fixed_other_services_unaffected(tmp_path: Path):
    """The ordinary web service keeps its block and its paired sidecar."""
    doc = _dev_compose(_compile(_FIXED, tmp_path))
    services = doc["services"]
    assert "sample-dev-api" in services
    assert "sample-dev-api-otelcol" in services


def test_fixed_ini_schedule_and_image(tmp_path: Path):
    doc = _dev_compose(_compile(_FIXED, tmp_path))
    ini = doc["configs"]["ofelia_nightly_cleanup"]["content"]
    assert '[job-run "nightly_cleanup"]' in ini
    # 5-field "0 3 * * 1-5" -> ofelia 6-field with seconds prepended,
    # NO day-of-week remap (fixed side keeps standard numbering).
    assert "schedule = 0 0 3 * * 1-5" in ini
    assert "image = sample/nightly_cleanup:0.1.0" in ini
    assert "network = sample-dev-internal" in ini
    assert "delete = true" in ini


def test_fixed_ini_env_secret_split(tmp_path: Path):
    """Non-secret resolved env is inlined; secrets are NOT (they arrive via
    the sourced env file)."""
    doc = _dev_compose(_compile(_FIXED, tmp_path))
    ini = doc["configs"]["ofelia_nightly_cleanup"]["content"]
    # Non-secret: DATABASE_HOST resolves to a literal -> inlined.
    assert "DATABASE_HOST=sample-dev-appdb" in ini
    # Secret: DATABASE_USER / _PASSWORD resolve to $[VAR] -> NOT inlined.
    assert "DATABASE_USER=" not in ini
    assert "DATABASE_PASSWORD=" not in ini
    assert "POSTGRES_USER" not in ini
    assert "POSTGRES_PASSWORD" not in ini


def test_fixed_ini_command_wrapper_and_mount(tmp_path: Path):
    doc = _dev_compose(_compile(_FIXED, tmp_path))
    ini = doc["configs"]["ofelia_nightly_cleanup"]["content"]
    assert (
        "command = sh -c '. /run/job.env && exec python -m jobs.cleanup'"
        in ini
    )
    assert 'volume = ["infra/secrets/dev.env:/run/job.env:ro"]' in ini


# ---------------------------------------------------------------------------
# Elastic (EventBridge Scheduler) HCL emit
# ---------------------------------------------------------------------------


def _stage_hcl(root: Path) -> str:
    return (root / "infra" / "output" / "stage" / "main.tf").read_text()


def _slice_td(hcl: str, name: str) -> str:
    marker = f'resource "aws_ecs_task_definition" "{name}" {{'
    idx = hcl.index(marker)
    rest = hcl[idx:]
    return rest[: rest.index("\n}\n") + 2]


def test_elastic_emits_scheduler_schedule(tmp_path: Path):
    hcl = _stage_hcl(_compile(_ELASTIC, tmp_path))
    assert 'resource "aws_scheduler_schedule" "nightly_cleanup" {' in hcl
    # 5-field "0 3 * * *" -> AWS 6-field with ?-day (dow '*' -> '?') + year.
    assert 'schedule_expression          = "cron(0 3 * * ? *)"' in hcl
    assert 'schedule_expression_timezone = "UTC"' in hcl
    assert 'launch_type         = "FARGATE"' in hcl
    assert "assign_public_ip = false" in hcl


def test_elastic_emits_invocation_role(tmp_path: Path):
    hcl = _stage_hcl(_compile(_ELASTIC, tmp_path))
    assert 'resource "aws_iam_role" "nightly_cleanup_scheduler" {' in hcl
    assert 'Service = "scheduler.amazonaws.com"' in hcl
    assert 'resource "aws_iam_role_policy" "nightly_cleanup_scheduler" {' in hcl
    assert 'Action   = "ecs:RunTask"' in hcl
    assert 'Action   = "iam:PassRole"' in hcl
    assert "Resource = aws_ecs_task_definition.nightly_cleanup.arn" in hcl


def test_elastic_scheduler_task_def_has_no_sidecar(tmp_path: Path):
    hcl = _stage_hcl(_compile(_ELASTIC, tmp_path))
    nc = _slice_td(hcl, "nightly_cleanup")
    assert "otelcol" not in nc
    # No ecs_service / target_group for a scheduler.
    assert 'resource "aws_ecs_service" "nightly_cleanup"' not in hcl
    assert 'resource "aws_lb_target_group" "nightly_cleanup"' not in hcl


def test_elastic_web_service_still_has_sidecar(tmp_path: Path):
    """The sidecar omission is scoped to one-shot tasks — a long-running
    web service in the same project MUST still get its sidecar."""
    hcl = _stage_hcl(_compile(_ELASTIC, tmp_path))
    api = _slice_td(hcl, "api")
    assert 'name = "api-otelcol"' in api


def test_elastic_scheduler_task_no_sidecar_resource_overhead(tmp_path: Path):
    """A scheduler RunTask has no paired sidecar, so its task-level cpu/
    memory must NOT carry the sidecar's 0.1 vCPU / 128 MiB overhead — the
    requested 0.25 vCPU / 512 MB lands exactly on the (256, 512) tier."""
    hcl = _stage_hcl(_compile(_ELASTIC, tmp_path))
    nc = _slice_td(hcl, "nightly_cleanup")
    assert 'cpu                      = "256"' in nc
    assert 'memory                   = "512"' in nc


def test_elastic_scheduler_runtask_targets_project_tier_cluster(tmp_path: Path):
    """Mod 071: the ECS cluster is project-tier now — the env main.tf no
    longer declares one. The scheduler RunTask target must reference the
    env's project-tier cluster ARN via remote state so it still has a
    cluster to run in."""
    hcl = _stage_hcl(_compile(_ELASTIC, tmp_path))
    assert 'resource "aws_ecs_cluster" "cluster" {' not in hcl
    assert (
        "arn      = data.terraform_remote_state.project.outputs."
        "ecs_cluster_stage_arn" in hcl
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _tables():
    return load_transfer_tables(project_root=None)


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


_VALID = """
cicl_version: "1"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
core_services:
  job:
    role: scheduler
    schedule: "0 3 * * *"
    command: ["python", "-m", "jobs.cleanup"]
    networks: [internal]
    resources:
      cpu: 0.25
      memory: 512MB
"""


def test_valid_scheduler_passes():
    assert validate_document(_doc(_VALID), _tables()) == []


def test_scheduler_without_schedule_errors():
    src = _VALID.replace('    schedule: "0 3 * * *"\n', "")
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_scheduler_schedule_required" for i in issues)


def test_scheduler_without_command_errors():
    src = _VALID.replace(
        '    command: ["python", "-m", "jobs.cleanup"]\n', ""
    )
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_scheduler_command_required" for i in issues)


def test_scheduler_malformed_cron_errors():
    src = _VALID.replace('"0 3 * * *"', '"0 3 * *"')  # 4 fields
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "rule_scheduler_malformed_cron" for i in issues)


def test_schedule_on_web_service_rejected():
    """`schedule` is a role-specific field declared only on scheduler; on a
    web service rule 4 (undeclared field) rejects it."""
    src = """
cicl_version: "1"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
core_services:
  api:
    role: web
    schedule: "0 3 * * *"
    networks: [web, internal]
    port: 8080
    resources:
      cpu: 1.0
      memory: 2GB
"""
    issues = validate_document(_doc(src), _tables())
    assert any(i.rule == "tt_rule_4_undeclared_field" for i in issues)

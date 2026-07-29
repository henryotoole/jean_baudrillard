"""Tests for Gap E (mod 052): ECS containers emit `awslogs`
`logConfiguration` → a per-(env, service) CloudWatch log group.

Compiles the elastic fixture and inspects the emitted main.tf for the
`logConfiguration` block on all three container kinds (app, OTel
sidecar, `_migrate`) and the `aws_cloudwatch_log_group` resource with
30-day retention and the IAM-matching (raw, underscore-preserving)
name prefix.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from docex.cicl.compile import run_compile
from docex.context import load_project_context


_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_project_elastic"
)


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest


def _stage_hcl(root: Path) -> str:
    return (root / "infra" / "output" / "stage" / "main.tf").read_text()


def _slice_task_def(hcl: str, resource_name: str) -> str:
    marker = f'resource "aws_ecs_task_definition" "{resource_name}" {{'
    idx = hcl.index(marker)
    rest = hcl[idx:]
    end = rest.index("\n}\n")
    return rest[: end + 2]


def test_app_container_has_awslogs_logconfiguration(tmp_path: Path):
    """The application container carries an `awslogs` logConfiguration
    pointing at its log group with the `app` stream prefix."""
    root = _copy_fixture(tmp_path)
    run_compile(load_project_context(root))

    api_td = _slice_task_def(_stage_hcl(root), "api-web")
    assert 'logDriver = "awslogs"' in api_td
    assert "awslogs-group = aws_cloudwatch_log_group.api-web.name" in api_td
    assert 'awslogs-region = "us-east-1"' in api_td
    assert 'awslogs-stream-prefix = "app"' in api_td


def test_sidecar_has_awslogs_logconfiguration(tmp_path: Path):
    """The OTel sidecar also logs to CloudWatch, with the `otelcol`
    stream prefix, sharing the service's log group."""
    root = _copy_fixture(tmp_path)
    run_compile(load_project_context(root))

    api_td = _slice_task_def(_stage_hcl(root), "api-web")
    assert 'awslogs-stream-prefix = "otelcol"' in api_td


def test_migrate_container_has_awslogs_logconfiguration(tmp_path: Path):
    """The `_migrate` container — the headline Class-2 case — logs to
    CloudWatch with the `migrate` stream prefix."""
    root = _copy_fixture(tmp_path)
    run_compile(load_project_context(root))

    mig_td = _slice_task_def(_stage_hcl(root), "api_migrate")
    assert 'logDriver = "awslogs"' in mig_td
    assert "awslogs-group = aws_cloudwatch_log_group.api-web.name" in mig_td
    assert 'awslogs-stream-prefix = "migrate"' in mig_td


def test_no_create_group_option(tmp_path: Path):
    """`awslogs-create-group` is never set — the task-execution role
    lacks CreateLogGroup; tofu owns the group."""
    root = _copy_fixture(tmp_path)
    run_compile(load_project_context(root))

    assert "awslogs-create-group" not in _stage_hcl(root)


def test_log_group_resource_emitted_with_retention(tmp_path: Path):
    """An `aws_cloudwatch_log_group` is emitted per service with 30-day
    retention and the managed_by tag."""
    root = _copy_fixture(tmp_path)
    run_compile(load_project_context(root))

    hcl = _stage_hcl(root)
    assert 'resource "aws_cloudwatch_log_group" "api-web" {' in hcl
    assert "retention_in_days = 30" in hcl
    assert 'managed_by = "doctrine"' in hcl


def test_log_group_name_uses_iam_matching_project_form(tmp_path: Path):
    """The log-group name prefix `/<project>/<env>/` uses the raw,
    underscore-preserving project form so it matches the
    task-execution-role IAM `log-group:/<ssm_path_project>/<env>/*`
    scope — the same form the SSM parameter ARNs use.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    project = ctx.project.name  # raw form (matches ssm_path policy)
    # Log-group name and the SSM ARN prefix share the same `/<project>/<env>/`.
    assert f'name              = "/{project}/stage/api-web"' in hcl
    assert f"parameter/{project}/stage/" in hcl

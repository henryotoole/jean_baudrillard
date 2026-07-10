"""Unit tests for ``docex.pipeline.projinfra``.

Mod 036 wires ``projinfra <up|down> <side>`` on fixed-foundation
projects. The runner:

- ``up`` invokes ``docker compose up -d`` against the per-side
  ``infra/output/project/<side>/docker-compose.yml``.
- ``down`` refuses when any env-tier compose stack for the same project
  is still up; otherwise invokes ``docker compose down`` (volumes
  preserved so the ACME named volume survives).
- Missing compose file: ``up`` errors with exit 1; ``down`` warns and
  exits 0 (nothing to tear down).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.pipeline.projinfra import (
    run_projinfra_elastic_down,
    run_projinfra_fixed_down,
    run_projinfra_fixed_up,
)


# ---------------------------------------------------------------------------
# up
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["development", "production"])
def test_projinfra_fixed_up_runs_compose_up(sample_ctx, fake_docker, side):
    """``up`` invokes ``compose_up`` against the per-side compose file."""
    rc = run_compile(sample_ctx)
    assert rc == 0

    rc = run_projinfra_fixed_up(sample_ctx, fake_docker, side=side)
    assert rc == 0

    expected_path = (
        sample_ctx.project_root
        / "infra" / "output" / "project" / side / "docker-compose.yml"
    )
    compose_up_calls = [c for c in fake_docker.calls if c[0] == "compose_up"]
    assert len(compose_up_calls) == 1, fake_docker.calls
    # FakeDockerClient records compose_up as (method, path, build, detach).
    method, path, build, detach = compose_up_calls[0]
    assert path == str(expected_path)
    # build=False (no build context at project tier); detached.
    assert build is False
    assert detach is True
    # Mod 053: an explicit, project-scoped --project-name is passed so
    # the projinfra stack (traefik + four -web networks) lives under a
    # stable name, not the bogus path-derived 'infra'.
    # Mod 087: that name is now side-independent — BOTH sides yield the
    # SAME project name so a single-host fixed dev/prod converge.
    name_calls = [
        c for c in fake_docker.calls if c[0] == "compose_up_project_name"
    ]
    assert name_calls == [("compose_up_project_name", "sample-projinfra")]


def test_projinfra_fixed_up_missing_compose_file_errors(
    sample_ctx, fake_docker, capsys,
):
    """``up`` without a compiled compose file returns exit 1 and prints
    an actionable error pointing at ``docex compile``. ``compose_up``
    is not invoked."""
    # No `run_compile` here — output dir is empty (copy_fixture clears it).
    rc = run_projinfra_fixed_up(sample_ctx, fake_docker, side="development")
    assert rc == 1
    out = capsys.readouterr().out
    assert "docex compile" in out
    assert not any(c[0] == "compose_up" for c in fake_docker.calls), (
        fake_docker.calls
    )


def test_projinfra_fixed_up_propagates_compose_failure(
    sample_ctx, fake_docker, capsys,
):
    """When ``compose_up`` returns non-zero, the runner propagates the
    exit code and prints the failure."""
    rc = run_compile(sample_ctx)
    assert rc == 0
    fake_docker.default_exit = 0
    expected_path = str(
        sample_ctx.project_root
        / "infra" / "output" / "project" / "development" / "docker-compose.yml"
    )
    # FakeDockerClient compose_up key is ("compose_up", path, build, detach).
    fake_docker.exit_codes[
        ("compose_up", expected_path, False, True)
    ] = 7

    rc = run_projinfra_fixed_up(
        sample_ctx, fake_docker, side="development",
    )
    assert rc == 7
    out = capsys.readouterr().out
    assert "exit code 7" in out


def test_projinfra_fixed_compose_name_is_side_independent(
    sample_ctx, fake_docker,
):
    """Mod 087: both sides run under the SAME Compose project name so a
    single-host fixed dev/prod converge (the second ``up`` adopts the
    first's resources instead of colliding on the shared traefik
    container). Unit-level guard for the bug the fixed smoke walk caught.
    """
    rc = run_compile(sample_ctx)
    assert rc == 0

    assert run_projinfra_fixed_up(sample_ctx, fake_docker, side="development") == 0
    assert run_projinfra_fixed_up(sample_ctx, fake_docker, side="production") == 0

    name_calls = [
        c for c in fake_docker.calls if c[0] == "compose_up_project_name"
    ]
    assert name_calls == [
        ("compose_up_project_name", "sample-projinfra"),
        ("compose_up_project_name", "sample-projinfra"),
    ]


# ---------------------------------------------------------------------------
# down
# ---------------------------------------------------------------------------


def test_projinfra_fixed_down_refuses_when_env_up(
    sample_ctx, fake_docker, capsys,
):
    """If any env-tier compose stack for the project is up,
    ``down`` refuses with exit 1 and does NOT call ``compose_down``."""
    rc = run_compile(sample_ctx)
    assert rc == 0
    fake_docker.any_env_compose_up_results[sample_ctx.project.name] = True

    rc = run_projinfra_fixed_down(
        sample_ctx, fake_docker, side="development",
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "still up" in out
    assert "envinfra down" in out
    # compose_down was not invoked.
    assert not any(c[0] == "compose_down" for c in fake_docker.calls), (
        fake_docker.calls
    )


def test_projinfra_fixed_down_proceeds_when_env_clean(
    sample_ctx, fake_docker,
):
    """When no env stacks are up, ``down`` calls ``compose_down`` with
    volumes preserved (``preserve_volumes=True``) so the ACME volume
    survives."""
    rc = run_compile(sample_ctx)
    assert rc == 0
    fake_docker.any_env_compose_up_results[sample_ctx.project.name] = False

    rc = run_projinfra_fixed_down(
        sample_ctx, fake_docker, side="production",
    )
    assert rc == 0
    compose_down_calls = [
        c for c in fake_docker.calls if c[0] == "compose_down"
    ]
    assert len(compose_down_calls) == 1, fake_docker.calls
    method, path, preserve = compose_down_calls[0]
    assert preserve is True
    assert path == str(
        sample_ctx.project_root
        / "infra" / "output" / "project" / "production" / "docker-compose.yml"
    )
    # Mod 053: down must pass the SAME project name as up so it removes
    # the traefik AND the four -web networks.
    # Mod 087: the name is side-independent, so down targets the same
    # converged project regardless of side.
    name_calls = [
        c for c in fake_docker.calls if c[0] == "compose_down_project_name"
    ]
    assert name_calls == [
        ("compose_down_project_name", "sample-projinfra")
    ]


def test_projinfra_fixed_down_missing_compose_file_warns_and_succeeds(
    sample_ctx, fake_docker, capsys,
):
    """``down`` without a compiled compose file is a tolerated no-op:
    prints a warning, returns 0, and doesn't touch docker beyond the
    env-stack probe."""
    # No `run_compile` here — output dir is empty.
    fake_docker.any_env_compose_up_results[sample_ctx.project.name] = False

    rc = run_projinfra_fixed_down(
        sample_ctx, fake_docker, side="development",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "warning" in out.lower()
    assert "nothing to tear down" in out
    # compose_down never called.
    assert not any(c[0] == "compose_down" for c in fake_docker.calls), (
        fake_docker.calls
    )


# ---------------------------------------------------------------------------
# Mod 052 (Gap F): elastic projinfra down production.
# ---------------------------------------------------------------------------


def _compile_project_tier(ctx):
    """Compile so the project-tier main.tf exists for the destroy step."""
    rc = run_compile(ctx)
    assert rc == 0


def test_projinfra_elastic_down_refuses_when_env_cluster_exists(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """Refuse-if-envs-up: any env whose (project-tier) cluster still holds
    ECS services blocks the teardown. Nothing is destroyed (no tofu, no
    cleanup). Mod 071: probes env-service existence, not cluster existence
    (the clusters are project-tier and always present)."""
    _compile_project_tier(elastic_ctx)
    # Default fake `cluster_has_services=True` → both stage and prod read as live.
    fake_aws.cluster_has_services = True

    rc = run_projinfra_elastic_down(
        elastic_ctx, fake_aws,
        tofu_init=fake_tofu_init, tofu_destroy=fake_tofu_apply,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "env-tier resources still exist" in out
    assert "envinfra down" in out
    assert "Nothing was destroyed" in out
    assert "NS record" not in out
    # No destroy, no cleanup.
    assert fake_tofu_apply.calls == []
    assert not any(c[0] == "ssm_delete_parameters" for c in fake_aws.calls)
    assert not any(c[0] == "s3_delete_bucket" for c in fake_aws.calls)
    assert not any(c[0] == "ddb_delete_table" for c in fake_aws.calls)


def test_projinfra_elastic_down_refuses_on_nonempty_ecr(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """ECR pre-flight: a non-empty repo blocks the teardown. Nothing is
    destroyed."""
    _compile_project_tier(elastic_ctx)
    fake_aws.cluster_has_services = False  # envs are down
    fake_aws.ecr_image_count_results["sample/api"] = 3

    rc = run_projinfra_elastic_down(
        elastic_ctx, fake_aws,
        tofu_init=fake_tofu_init, tofu_destroy=fake_tofu_apply,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "sample/api has 3 image(s)" in out
    assert "Nothing was destroyed" in out
    assert "NS record" not in out
    assert fake_tofu_apply.calls == []
    assert not any(c[0] == "s3_delete_bucket" for c in fake_aws.calls)


def test_projinfra_elastic_down_clean_path_orders_cleanup(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """Clean path: tofu destroy, then SSM delete, then state backend
    (S3 bucket + DDB table) — in that order, state backend last."""
    _compile_project_tier(elastic_ctx)
    fake_aws.cluster_has_services = False
    # ECR empty by default (image count 0).

    rc = run_projinfra_elastic_down(
        elastic_ctx, fake_aws,
        tofu_init=fake_tofu_init, tofu_destroy=fake_tofu_apply,
    )
    assert rc == 0

    # tofu init + destroy ran against the project production dir.
    assert len(fake_tofu_init.calls) == 1
    assert len(fake_tofu_apply.calls) == 1
    workdir = str(fake_tofu_apply.calls[0]["workdir"])
    assert workdir.endswith("infra/output/project/production")

    # Cleanup order: ssm_delete_parameters → s3_delete_bucket → ddb_delete_table.
    cleanup = [
        c[0] for c in fake_aws.calls
        if c[0] in ("ssm_delete_parameters", "s3_delete_bucket", "ddb_delete_table")
    ]
    assert cleanup == ["ssm_delete_parameters", "s3_delete_bucket", "ddb_delete_table"]

    # Cleanup targeted the right names.
    ssm_call = next(c for c in fake_aws.calls if c[0] == "ssm_delete_parameters")
    assert ssm_call[1] == ("/sample/",)
    s3_call = next(c for c in fake_aws.calls if c[0] == "s3_delete_bucket")
    assert s3_call[1] == ("sample-tofu-state",)
    ddb_call = next(c for c in fake_aws.calls if c[0] == "ddb_delete_table")
    assert ddb_call[1] == ("sample_tofu_locks",)


def test_projinfra_elastic_down_prints_delegation_removal_reminder(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """On a successful teardown, docex reminds the operator to remove the
    parent-zone NS delegation it can't manage itself. Mod 072 / campaign 002."""
    _compile_project_tier(elastic_ctx)
    fake_aws.cluster_has_services = False  # envs down; ECR empty by default

    rc = run_projinfra_elastic_down(
        elastic_ctx, fake_aws,
        tofu_init=fake_tofu_init, tofu_destroy=fake_tofu_apply,
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Names the NS record to remove and the parent zone.
    assert "NS record" in out
    assert elastic_ctx.infra.apex_domain in out
    # The child-zone subdomain the operator delegated.
    from docex.naming import dns_label
    assert f"{dns_label(elastic_ctx.project.name)}.{elastic_ctx.infra.apex_domain}" in out

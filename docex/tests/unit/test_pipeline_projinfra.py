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

"""Unit tests for ``docex build``."""

from __future__ import annotations

from pathlib import Path

import pytest

from docex.errors import BuildFailed, EnvNotRunning, EnvNotSupported
from docex.orchestrate.build import run_build


def _seed_dist(ctx, svc: str, contents: dict[str, str] | None = None) -> Path:
    """Create core/<svc>/dist with optional pre-existing files."""
    dist = ctx.project_root / "core" / svc / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    if contents:
        for name, body in contents.items():
            (dist / name).write_text(body)
    return dist


def test_build_errors_when_dev_not_running(sample_ctx, fake_docker):
    fake_docker.ps_services = []  # nothing running
    with pytest.raises(EnvNotRunning):
        run_build(sample_ctx, fake_docker)


def test_build_clears_dist_before_running_build_sh(sample_ctx, fake_docker, monkeypatch):
    # Simulate dev is running. compose_ps returns simple service names.
    fake_docker.ps_services = ["api"]
    # Seed dist/ with a stale file that should disappear before build.
    dist = _seed_dist(sample_ctx, "api", {"stale.txt": "old"})
    assert (dist / "stale.txt").is_file()

    # Have the compose_exec callback simulate build.sh writing a new file.
    def _exec_side_effect(compose_file, service, command, *, env_file=None):
        # build.sh writes to dist/
        if "./build.sh" in command:
            (dist / "fresh.py").write_text("print('hi')")
        # default success
        return 0

    # Replace the bound method on the fake.
    fake_docker.compose_exec = _exec_side_effect  # type: ignore[method-assign]

    rc = run_build(sample_ctx, fake_docker, service="api")
    assert rc == 0

    # Stale file should be gone; fresh one written by "build.sh" should be there.
    assert not (dist / "stale.txt").exists()
    assert (dist / "fresh.py").is_file()


def test_build_fails_if_dist_empty_after_build_sh(sample_ctx, fake_docker):
    fake_docker.ps_services = ["api"]
    _seed_dist(sample_ctx, "api", {"stale.txt": "old"})
    # Default exec returns 0 but writes nothing.
    with pytest.raises(BuildFailed):
        run_build(sample_ctx, fake_docker, service="api")


def test_build_rejects_unknown_service(sample_ctx, fake_docker):
    fake_docker.ps_services = ["api"]
    with pytest.raises(EnvNotSupported):
        run_build(sample_ctx, fake_docker, service="bogus")


def test_build_returns_failure_exit_code_from_build_sh(sample_ctx, fake_docker):
    fake_docker.ps_services = ["api"]
    _seed_dist(sample_ctx, "api")
    # Script build.sh to fail.
    fake_docker.exit_codes[("exit", "compose_exec", "api", ("./build.sh",))] = 3
    rc = run_build(sample_ctx, fake_docker, service="api")
    assert rc == 3

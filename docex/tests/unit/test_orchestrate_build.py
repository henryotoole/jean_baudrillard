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
    """Mod 099 test 13: ``build.sh`` runs in the codebase's exec service, and
    the host-side ``dist/`` contract is unchanged — cleared before, asserted
    non-empty after."""
    # Simulate dev is running. `compose ps --services` returns the compose
    # service KEYS, which are the project-scoped global names.
    fake_docker.ps_services = ["sample-dev-api-web"]
    # Seed dist/ with a stale file that should disappear before build.
    dist = _seed_dist(sample_ctx, "api", {"stale.txt": "old"})
    assert (dist / "stale.txt").is_file()

    seen: list[str] = []

    # Have the one-off-run callback simulate build.sh writing a new file.
    def _run_side_effect(compose_file, service, command, *, env=None,
                         env_file=None, project_dir=None, project_name=None):
        # build.sh writes to dist/
        if "./build.sh" in command:
            seen.append(service)
            (dist / "fresh.py").write_text("print('hi')")
        # default success
        return 0

    # Replace the bound method on the fake.
    fake_docker.compose_run_one_off = _run_side_effect  # type: ignore[method-assign]

    rc = run_build(sample_ctx, fake_docker, service="api")
    assert rc == 0

    # It ran in the exec service, not in a core service's app container.
    assert seen == ["sample-dev-api-exec"]
    # Stale file should be gone; fresh one written by "build.sh" should be there.
    assert not (dist / "stale.txt").exists()
    assert (dist / "fresh.py").is_file()


def test_build_fails_if_dist_empty_after_build_sh(sample_ctx, fake_docker):
    fake_docker.ps_services = ["sample-dev-api-web"]
    _seed_dist(sample_ctx, "api", {"stale.txt": "old"})
    # Default exec returns 0 but writes nothing.
    with pytest.raises(BuildFailed):
        run_build(sample_ctx, fake_docker, service="api")


def test_build_rejects_unknown_service(sample_ctx, fake_docker):
    fake_docker.ps_services = ["sample-dev-api-web"]
    with pytest.raises(EnvNotSupported):
        run_build(sample_ctx, fake_docker, service="bogus")


def test_build_returns_failure_exit_code_from_build_sh(sample_ctx, fake_docker):
    fake_docker.ps_services = ["sample-dev-api-web"]
    _seed_dist(sample_ctx, "api")
    # Script build.sh to fail.
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-dev-api-exec", ("./build.sh",))
    ] = 3
    rc = run_build(sample_ctx, fake_docker, service="api")
    assert rc == 3


def test_build_proceeds_when_the_app_container_is_restarting(
    sample_ctx, fake_docker
):
    """Mod 099 RETIRED Gap D (mod 050) — deliberately, not incidentally.

    Gap D refused ``docex build`` when the codebase's dev container was
    ``restarting``/``unhealthy``. But the commonest cause of a crash-looping
    dev container is an empty ``dist/`` — exactly what ``docex build`` fills —
    so the gate blocked the one command that resolves the state it detected.
    Under ``compose run`` against the exec service the app container's health
    is irrelevant to refreshing ``dist/``, so the gate is gone and the build
    goes through. (The diagnostic's proper home is now
    ``up.py::_diagnose_unhealthy``, which this mod widened.)

    This test is the inversion of the pre-mod
    ``test_build_diagnoses_restarting_container``; it pins the retirement so
    the gate cannot quietly come back.
    """
    fake_docker.ps_services = ["sample-dev-other"]  # env is up, but api is absent
    fake_docker.ps_status = {"sample-dev-api-web": "restarting"}

    dist = _seed_dist(sample_ctx, "api")

    def _run_side_effect(compose_file, service, command, *, env=None,
                         env_file=None, project_dir=None, project_name=None):
        if "./build.sh" in command:
            (dist / "fresh.py").write_text("print('hi')")
        return 0

    fake_docker.compose_run_one_off = _run_side_effect  # type: ignore[method-assign]

    assert run_build(sample_ctx, fake_docker, service="api") == 0


def test_build_still_requires_the_stack_to_be_up(sample_ctx, fake_docker):
    """The *whole-stack* gate stays: ``cicd.md § Build Step`` step 1 still
    says "verify dev is running" (Mod 106's to revisit). Only the
    per-service container gate was retired."""
    fake_docker.ps_services = []
    with pytest.raises(EnvNotRunning) as excinfo:
        run_build(sample_ctx, fake_docker, service="api")
    assert "run 'docex up dev' first" in str(excinfo.value)

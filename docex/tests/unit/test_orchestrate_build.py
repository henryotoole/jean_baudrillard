"""Unit tests for ``docex build``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.errors import BuildFailed, EnvNotRunning, EnvNotSupported
from docex.orchestrate.build import _CLEAR_AND_BUILD, run_build


def _seed_dist(ctx, svc: str, contents: dict[str, str] | None = None) -> Path:
    """Create core/<svc>/dist with optional pre-existing files."""
    dist = ctx.project_root / "core" / svc / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    if contents:
        for name, body in contents.items():
            (dist / name).write_text(body)
    return dist


def _container_like_run(dist: Path, *, honor_clear: bool = True):
    """A ``compose_run_one_off`` stand-in that does what the command says.

    The real exec container is root and executes the command string it is
    handed — so this fake clears ``dist/`` **only if the command actually
    contains the clear**, and writes an artifact only if it invokes
    ``build.sh``.

    That derivation is the point. Mod 119 moved the clear from the host into
    the container, so ``docex`` no longer deletes anything itself. The lazy
    way to keep the old assertion green would be to make this fake clear
    unconditionally — which would pin nothing at all. Deriving the behavior
    from the command keeps the assertion load-bearing: drop the clear from
    ``build.py`` and the fake stops clearing, the stale file survives, and
    the test fails.
    """
    def _run(compose_file, service, command, *, env=None, build=False,
             env_file=None, project_dir=None, project_name=None):
        script = " ".join(command)
        if honor_clear and "find dist -mindepth 1 -delete" in script:
            for child in dist.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        if "build.sh" in script:
            (dist / "fresh.py").write_text("print('hi')")
        return 0
    return _run


def test_build_errors_when_dev_not_running(sample_ctx, fake_docker):
    fake_docker.ps_services = []  # nothing running
    with pytest.raises(EnvNotRunning):
        run_build(sample_ctx, fake_docker)


def test_build_clears_dist_before_running_build_sh(sample_ctx, fake_docker):
    """Mod 099 test 13, updated by Mod 119: ``build.sh`` runs in the
    codebase's exec service, and ``dist/`` is still cleared before it and
    asserted non-empty after — but the clear now happens *inside* that
    container, because the tree is root-owned and the host uid cannot
    unlink inside a root-owned subdirectory."""
    fake_docker.ps_services = ["sample-dev-api-web"]
    dist = _seed_dist(sample_ctx, "api", {"stale.txt": "old"})
    assert (dist / "stale.txt").is_file()

    seen: list[str] = []
    inner = _container_like_run(dist)

    def _run(compose_file, service, command, **kwargs):
        seen.append(service)
        return inner(compose_file, service, command, **kwargs)

    fake_docker.compose_run_one_off = _run  # type: ignore[method-assign]

    assert run_build(sample_ctx, fake_docker, codebase="api") == 0
    assert seen == ["sample-dev-api-exec"]
    assert not (dist / "stale.txt").exists()
    assert (dist / "fresh.py").is_file()


def test_build_command_clears_dist_inside_the_container(sample_ctx, fake_docker):
    """Mod 119. The clear must be in the command handed to the exec
    service, and must precede ``build.sh``."""
    fake_docker.ps_services = ["sample-dev-api-web"]
    # Seeded so step 4's non-empty assertion passes without the fake
    # writing anything (the default fake records and returns 0).
    _seed_dist(sample_ctx, "api", {"stale.txt": "old"})

    assert run_build(sample_ctx, fake_docker, codebase="api") == 0

    runs = [c for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert len(runs) == 1
    cmd = runs[0][3]
    assert cmd[0] == "sh" and cmd[1] == "-c"
    script = cmd[2]
    assert "find dist -mindepth 1 -delete" in script
    assert "./build.sh" in script
    assert script.index("-delete") < script.index("./build.sh")


def test_build_does_not_delete_inside_host_dist(sample_ctx, fake_docker):
    """Mod 119. ``dist/`` is container-owned: everything in it is written as
    root through a bind mount, and a root-owned subdirectory's contents are
    unlinkable by the host uid. ``docex`` may create, list and stat that
    directory; it must never delete inside it from the host.

    Proof by absence: with a container that does nothing, a seeded file is
    still there after ``run_build``. If a host-side clear ever comes back,
    this fails."""
    fake_docker.ps_services = ["sample-dev-api-web"]
    dist = _seed_dist(sample_ctx, "api", {"stale.txt": "old"})

    assert run_build(sample_ctx, fake_docker, codebase="api") == 0
    assert (dist / "stale.txt").is_file()


def test_build_fails_if_dist_empty_after_build_sh(sample_ctx, fake_docker):
    fake_docker.ps_services = ["sample-dev-api-web"]
    # Seeded EMPTY. Pre-Mod-119 this seeded a stale file and relied on
    # docex's own host-side clear to empty dist/; docex no longer deletes
    # anything, so the emptiness has to come from the seed. The claim under
    # test is unchanged: build.sh exits 0, dist/ is empty, docex raises.
    _seed_dist(sample_ctx, "api")
    # Default exec returns 0 but writes nothing.
    with pytest.raises(BuildFailed):
        run_build(sample_ctx, fake_docker, codebase="api")


def test_build_rejects_unknown_service(sample_ctx, fake_docker):
    fake_docker.ps_services = ["sample-dev-api-web"]
    with pytest.raises(EnvNotSupported):
        run_build(sample_ctx, fake_docker, codebase="bogus")


def test_build_returns_failure_exit_code_from_build_sh(sample_ctx, fake_docker):
    fake_docker.ps_services = ["sample-dev-api-web"]
    _seed_dist(sample_ctx, "api")
    # Script build.sh to fail.
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-dev-api-exec",
         ("sh", "-c", _CLEAR_AND_BUILD))
    ] = 3
    rc = run_build(sample_ctx, fake_docker, codebase="api")
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

    # Mod 119: the command is now `sh -c "<clear>; exec ./build.sh"`, so the
    # fake derives its behavior from the command string rather than matching
    # a bare `./build.sh` argv element.
    fake_docker.compose_run_one_off = _container_like_run(dist)  # type: ignore[method-assign]

    assert run_build(sample_ctx, fake_docker, codebase="api") == 0


def test_build_still_requires_the_stack_to_be_up(sample_ctx, fake_docker):
    """The *whole-stack* gate stays: ``cicd.md § Build Step`` step 1 still
    says "verify dev is running" (Mod 106's to revisit). Only the
    per-service container gate was retired."""
    fake_docker.ps_services = []
    with pytest.raises(EnvNotRunning) as excinfo:
        run_build(sample_ctx, fake_docker, codebase="api")
    assert "run 'docex up dev' first" in str(excinfo.value)

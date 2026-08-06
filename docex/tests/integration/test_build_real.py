"""Integration test: ``docex build api`` against a running dev env."""

from __future__ import annotations

import subprocess

import pytest

from docex.context import load_project_context
from docex.orchestrate.build import run_build
from docex.orchestrate.down import run_down
from docex.orchestrate.up import run_up


@pytest.mark.integration
def test_build_refreshes_dist_after_src_edit(fresh_project, docker_client):
    ctx = load_project_context(fresh_project)
    try:
        rc = run_up(ctx, docker_client, env="dev")
        assert rc == 0

        # Drop a brand-new file in src/ that build.sh's cp will pick up.
        src = fresh_project / "core" / "api" / "src"
        marker = src / "phase2_marker.py"
        marker.write_text("MARKER = 'phase2-real-build'\n")

        rc = run_build(ctx, docker_client, codebase="api")
        assert rc == 0

        # Confirm the marker landed in dist/ via the build.sh shell script.
        dist_marker = fresh_project / "core" / "api" / "dist" / "phase2_marker.py"
        assert dist_marker.is_file(), "build.sh should have copied src -> dist"
        assert "phase2-real-build" in dist_marker.read_text()
    finally:
        run_down(ctx, docker_client, env="dev")
        subprocess.run(
            ["docker", "compose", "-f", str(
                fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"
            ), "--project-directory", str(fresh_project),
             "--env-file", str(fresh_project / "infra" / "secrets" / "dev.env"),
             "down", "-v"],
            check=False,
        )


@pytest.mark.integration
def test_build_clears_root_owned_residue(fresh_project, docker_client):
    """Mod 119 regression. Pre-mod, ``run_build`` cleared ``dist/`` from the
    host with ``shutil.rmtree`` and died with ``PermissionError`` on the
    root-owned ``__pycache__`` the dev stack itself had just created.

    The residue is manufactured here with a throwaway root container rather
    than left to arise from the app's import behavior, so the test pins the
    bug deterministically. That is the same mechanism the bug has in the
    field — a container writing through a bind mount as root — and it needs
    no privileges on the host.

    Note the root-owned **directory**: a root-owned *file* directly in
    ``dist/`` is removable by the host uid, because unlink permission comes
    from the parent. The directory is what blocks it.
    """
    ctx = load_project_context(fresh_project)
    dist = fresh_project / "core" / "api" / "dist"
    try:
        assert run_up(ctx, docker_client, env="dev") == 0

        dist.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["docker", "run", "--rm", "-v", f"{dist}:/d", "alpine:latest",
             "sh", "-c",
             "mkdir -p /d/__pycache__ && touch /d/__pycache__/residue.pyc"],
            check=True,
        )
        residue = dist / "__pycache__" / "residue.pyc"
        assert residue.is_file()
        assert residue.stat().st_uid == 0, "residue must be root-owned to pin the bug"

        assert run_build(ctx, docker_client, codebase="api") == 0
        # The seeded residue is gone: the in-container clear reached inside a
        # root-owned directory, which the host uid could not have done.
        #
        # Assert on the residue, NOT on `dist/__pycache__` being absent. The
        # directory legitimately comes back: the fixture's `build.sh` ends
        # with `cp -r src/. dist/`, and `src/__pycache__` exists on any
        # machine where something has imported the fixture (it is gitignored,
        # so whether it exists is machine state). A `__pycache__` copied in by
        # the root exec container is a fresh artifact, not surviving residue —
        # the same reason `dist/app.py` is legitimately root-owned after a
        # build. Do not "restore" the stronger-looking assertion; it pins
        # machine state rather than the fix.
        assert not residue.exists(), (
            "the in-container clear must remove root-owned residue"
        )
        assert any(dist.iterdir())

        # Second run, no cleanup in between: the self-regeneration path.
        # dist/ is now full of root-owned artifacts written by build.sh, and
        # the build must still be repeatably green against them. This is the
        # property that manual `sudo rm -rf` never bought — it fixed one run.
        assert run_build(ctx, docker_client, codebase="api") == 0
        assert any(dist.iterdir())
    finally:
        run_down(ctx, docker_client, env="dev")
        subprocess.run(
            ["docker", "compose", "-f", str(
                fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"
            ), "--project-directory", str(fresh_project),
             "--env-file", str(fresh_project / "infra" / "secrets" / "dev.env"),
             "down", "-v"],
            check=False,
        )

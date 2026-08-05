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

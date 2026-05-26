"""Integration test: real ``docex up dev`` followed by ``docex down dev``.

Gated by ``@pytest.mark.integration``; skipped by default. Run via
``pytest -m integration``. Requires a real docker daemon.
"""

from __future__ import annotations

import pytest
import subprocess

from docex.context import load_project_context
from docex.orchestrate.down import run_down
from docex.orchestrate.up import run_up


@pytest.mark.integration
def test_up_then_down_dev(fresh_project, docker_client):
    ctx = load_project_context(fresh_project)
    try:
        rc = run_up(ctx, docker_client, env="dev")
        assert rc == 0, "docex up dev should exit 0"

        # Confirm a containerized service is running. We pass
        # --project-directory so compose finds the same project as
        # docex itself (which builds project name from the directory
        # passed there, not from cwd).
        compose_file = fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"
        env_file = fresh_project / "infra" / "secrets" / "dev.env"
        out = subprocess.check_output(
            ["docker", "compose", "-f", str(compose_file),
             "--project-directory", str(fresh_project),
             "--env-file", str(env_file),
             "ps", "--services", "--status=running"],
            text=True,
        )
        running = [line.strip() for line in out.splitlines() if line.strip()]
        # compose returns the project-scoped service keys (sample-dev-api).
        assert any(s.endswith("api") for s in running), running
        assert any(s.endswith("database") for s in running), running
    finally:
        run_down(ctx, docker_client, env="dev")
        # Also clean named volumes so the test is hermetic across runs.
        subprocess.run(
            ["docker", "compose", "-f", str(
                fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"
            ), "--project-directory", str(fresh_project),
             "--env-file", str(fresh_project / "infra" / "secrets" / "dev.env"),
             "down", "-v"],
            check=False,
        )

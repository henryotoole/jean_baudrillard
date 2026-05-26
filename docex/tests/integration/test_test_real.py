"""Integration test: ``docex test`` runs end-to-end and tears down."""

from __future__ import annotations

import subprocess

import pytest

from docex.context import load_project_context
from docex.orchestrate.test import run_test


@pytest.mark.integration
def test_docex_test_passes_and_tears_down(fresh_project, docker_client):
    ctx = load_project_context(fresh_project)
    compose_file = fresh_project / "infra" / "output" / "test" / "docker-compose.yml"

    rc = run_test(ctx, docker_client)
    assert rc == 0, "docex test should pass against the sample fixture"

    # After teardown, no test-env containers should be running.
    env_file = fresh_project / "infra" / "secrets" / "test.env"
    ps_out = subprocess.check_output(
        ["docker", "compose", "-f", str(compose_file),
         "--project-directory", str(fresh_project),
         "--env-file", str(env_file),
         "ps", "--services", "--status=running"],
        text=True,
    )
    assert ps_out.strip() == "", (
        f"test env should be torn down; ps still shows: {ps_out!r}"
    )

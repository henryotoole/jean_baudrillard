"""Integration test for ``docex stagetest``.

Brings up the sample fixture's dev stack (acting as a stand-in for a
deployed staging env) and runs ``docex stagetest`` with the staging
URL pointed at ``http://localhost:8080``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.docker import SubprocessDockerClient
from docex.orchestrate.down import run_down
from docex.orchestrate.up import run_up
from docex.pipeline.stagetest import run_stagetest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "sample_project"


@pytest.fixture
def fresh_project(tmp_path: Path) -> Path:
    dest = tmp_path / "stagetest_project"
    shutil.copytree(_FIXTURE, dest, dirs_exist_ok=False)
    return dest


@pytest.mark.integration
def test_stagetest_against_local_dev(fresh_project: Path):
    """Bring up dev, run stagetest pointing at localhost:8080, expect 200."""
    ctx = load_project_context(fresh_project)
    docker = SubprocessDockerClient()
    rc = run_up(ctx, docker, env="dev")
    if rc != 0:
        pytest.skip(f"could not bring up dev stack: rc={rc}")

    try:
        rc = run_stagetest(
            ctx,
            docker,
            staging_url_override="http://localhost:8080",
        )
        assert rc == 0
    finally:
        run_down(ctx, docker, env="dev")
        # Ensure named volumes are dropped — stagetest is throwaway state.
        subprocess.run(
            ["docker", "compose",
             "-f", str(fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"),
             "--project-directory", str(fresh_project),
             "--env-file", str(fresh_project / "infra" / "secrets" / "dev.env"),
             "down", "-v"],
            check=False,
        )

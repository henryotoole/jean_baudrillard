"""Integration test for ``docex stagetest``.

Brings up the sample fixture's dev stack (acting as a stand-in for a
deployed staging env) and runs ``docex stagetest`` against it. Web
services publish no host ports, so the tester is attached to the env's
``web`` docker network and reaches the api by container name.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.docker import SubprocessDockerClient
from docex.naming import dns_label
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
    """Bring up dev, run stagetest against the api over the env's web network
    (web services publish no host ports), expect 200."""
    ctx = load_project_context(fresh_project)
    docker = SubprocessDockerClient()
    rc = run_up(ctx, docker, env="dev")
    if rc != 0:
        pytest.skip(f"could not bring up dev stack: rc={rc}")

    # Both the container name and the env web network are project-env-scoped,
    # HYPHENATED data-plane identifiers (mods 030/035/046): the api container is
    # `<dns_label(project)>-dev-api` (`sample-dev-api`) on the env web network
    # `<dns_label(project)>-dev-web` (`sample-dev-web`). The old `sample_dev_api`
    # / bare-`web` overrides predated that hyphenation and were stale — the
    # integration suite hadn't been re-run since, so they went unnoticed. (Both
    # are orthogonal to envmageddon, which changed no networking or naming.)
    seg = dns_label(ctx.project.name)
    # Post-CICL-v2: the routable container is the `web` CORE SERVICE, so the
    # data-plane name gains a second segment — `sample-dev-api-web`, not
    # `sample-dev-api` (which now names no container at all).
    api_host = f"{seg}-dev-api-web"
    try:
        rc = run_stagetest(
            ctx,
            docker,
            # Reached by container name on the env's web docker network (web
            # services publish no host ports).
            staging_url_override=f"http://{api_host}:8080",
            network_override=f"{seg}-dev-web",
        )
        assert rc == 0
    finally:
        run_down(ctx, docker, env="dev")
        # Ensure named volumes are dropped — stagetest is throwaway state.
        subprocess.run(
            ["docker", "compose",
             "-f", str(fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"),
             "--project-directory", str(fresh_project),
             "--env-file", str(fresh_project / ".docex" / "agg" / "dev.env"),
             "down", "-v"],
            check=False,
        )

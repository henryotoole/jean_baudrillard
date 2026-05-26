"""Integration test for ``docex containerize`` — real buildx, no push.

Brings up a local docker registry container so ``docker push`` has a
real (if throwaway) destination. Tears the registry down after.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.docker import SubprocessDockerClient
from docex.git import SubprocessGitClient
from docex.pipeline.containerize import run_containerize


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "sample_project"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _setup_repo_with_tag(tmp_path: Path, registry: str) -> Path:
    work = tmp_path / "work"
    shutil.copytree(_FIXTURE, work, dirs_exist_ok=False)
    out = work / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    # Point infra.yml at the local registry so the emitted tags are
    # ``localhost:NNNN/sample/api:0.1.0``.
    infra = work / "infra" / "infra.yml"
    infra.write_text(
        infra.read_text().replace(
            'container_registry: "registry.example.com"',
            f'container_registry: "{registry}"',
        )
    )
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "test@docex.test")
    _git(work, "config", "user.name", "docex test")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial: sample fixture")
    # Tag v0.1.0 so containerize's tag-exists check passes.
    _git(work, "tag", "v0.1.0")
    return work


@pytest.fixture
def local_registry():
    """Run a throwaway ``registry:2`` container on a high port."""
    name = "docex-test-registry"
    port = 35000
    # Tear down any leftover from a previous run.
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    res = subprocess.run(
        ["docker", "run", "-d", "--rm",
         "--name", name, "-p", f"{port}:5000",
         "registry:2"],
        check=False, capture_output=True, text=True,
    )
    if res.returncode != 0:
        pytest.skip(f"could not start local registry: {res.stderr}")
    # Wait for the registry to come up.
    for _ in range(30):
        probe = subprocess.run(
            ["curl", "-sf", f"http://localhost:{port}/v2/"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            break
        time.sleep(0.5)
    yield f"localhost:{port}"
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.mark.integration
def test_containerize_real_builds_and_pushes(tmp_path: Path, local_registry):
    work = _setup_repo_with_tag(tmp_path, local_registry)
    ctx = load_project_context(work)
    docker = SubprocessDockerClient()
    git = SubprocessGitClient()

    rc = run_containerize(ctx, docker, git)
    assert rc == 0

    # Confirm the image is in the local docker store.
    expected_tag = f"{local_registry}/sample/api:0.1.0"
    res = subprocess.run(
        ["docker", "image", "inspect", expected_tag],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr

    # And in the registry catalog.
    probe = subprocess.run(
        ["curl", "-sf", f"http://{local_registry}/v2/sample/api/tags/list"],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0, probe.stderr
    assert "0.1.0" in probe.stdout, probe.stdout

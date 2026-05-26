"""Unit tests for ``docex containerize``.

Uses FakeGitClient + FakeDockerClient so the assertions cover the
exact docker buildx + push invocations without spawning subprocesses.
"""

from __future__ import annotations

import pytest

from docex.errors import (
    RegistryPushFailed,
    TagMissing,
    WorkingTreeDirty,
)
from docex.pipeline.containerize import run_containerize


@pytest.fixture
def ready_to_ship(sample_ctx, fake_git):
    """Tweak the FakeGitClient so containerize's preconditions all pass."""
    fake_git.clean = True
    fake_git.branch = "main"
    fake_git.tag_exists_map[f"v{sample_ctx.project.version}"] = True
    return sample_ctx, fake_git


def test_containerize_happy_path_builds_and_pushes_every_core_service(
    ready_to_ship, fake_docker
):
    ctx, fake_git = ready_to_ship
    rc = run_containerize(ctx, fake_docker, fake_git)
    assert rc == 0

    # Exactly one buildx + one push per core service.
    buildx = [c for c in fake_docker.calls if c[0] == "buildx_build"]
    push = [c for c in fake_docker.calls if c[0] == "push"]
    # Sample fixture has 1 core service: api.
    assert len(buildx) == 1
    assert len(push) == 1


def test_containerize_default_platform_is_linux_amd64(ready_to_ship, fake_docker):
    ctx, fake_git = ready_to_ship
    rc = run_containerize(ctx, fake_docker, fake_git)
    assert rc == 0
    buildx = next(c for c in fake_docker.calls if c[0] == "buildx_build")
    assert buildx[4] == "linux/amd64"  # (method, context, dockerfile, target, platform, tag)


def test_containerize_full_tag_format(ready_to_ship, fake_docker):
    ctx, fake_git = ready_to_ship
    rc = run_containerize(ctx, fake_docker, fake_git)
    assert rc == 0
    push = next(c for c in fake_docker.calls if c[0] == "push")
    # ``push(tag)`` records (method, tag).
    tag = push[1]
    # Sample fixture: registry.example.com/sample/api:0.1.0
    assert tag == "registry.example.com/sample/api:0.1.0"


def test_containerize_refuses_dirty_tree(ready_to_ship, fake_docker):
    ctx, fake_git = ready_to_ship
    fake_git.clean = False
    with pytest.raises(WorkingTreeDirty):
        run_containerize(ctx, fake_docker, fake_git)


def test_containerize_refuses_off_main(ready_to_ship, fake_docker):
    ctx, fake_git = ready_to_ship
    fake_git.branch = "feature/abc"
    rc = run_containerize(ctx, fake_docker, fake_git)
    assert rc == 1


def test_containerize_refuses_when_tag_missing(ready_to_ship, fake_docker):
    ctx, fake_git = ready_to_ship
    fake_git.tag_exists_map[f"v{ctx.project.version}"] = False
    with pytest.raises(TagMissing):
        run_containerize(ctx, fake_docker, fake_git)


def test_containerize_surfaces_push_failure(ready_to_ship, fake_docker):
    ctx, fake_git = ready_to_ship
    # Make the push fail.
    fake_docker.exit_codes[("exit", "push")] = 33
    with pytest.raises(RegistryPushFailed):
        run_containerize(ctx, fake_docker, fake_git)



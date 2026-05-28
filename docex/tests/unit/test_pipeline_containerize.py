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


def _make_elastic_ecr_default(sample_ctx, fake_git):
    """Turn the sample ctx into an elastic project with no explicit
    container_registry, and satisfy containerize's git preconditions."""
    sample_ctx.infra.foundation = "elastic"
    sample_ctx.infra.container_registry = None
    fake_git.clean = True
    fake_git.branch = "main"
    fake_git.tag_exists_map[f"v{sample_ctx.project.version}"] = True
    return sample_ctx, fake_git


def test_containerize_elastic_ecr_default(sample_ctx, fake_git, fake_docker, fake_aws):
    """Elastic project with no container_registry: containerize derives the
    ECR registry host from the account ID, logs in, ensures the repo, and
    pushes the ECR-qualified tag."""
    ctx, fake_git = _make_elastic_ecr_default(sample_ctx, fake_git)
    rc = run_containerize(ctx, fake_docker, fake_git, aws=fake_aws)
    assert rc == 0

    expected_registry = "123456789012.dkr.ecr.us-east-1.amazonaws.com"
    aws_methods = [c[0] for c in fake_aws.calls]
    assert "caller_identity" in aws_methods
    assert ("ecr_ensure_repository", ("sample/api",), {}) in fake_aws.calls
    # Logged in to the derived ECR host before pushing.
    assert ("login", expected_registry, "AWS") in fake_docker.calls
    # Pushed the ECR-qualified tag.
    push = next(c for c in fake_docker.calls if c[0] == "push")
    assert push[1] == f"{expected_registry}/sample/api:0.1.0"


def test_containerize_elastic_surfaces_login_failure(sample_ctx, fake_git, fake_docker, fake_aws):
    """A failed ECR login aborts before any push."""
    ctx, fake_git = _make_elastic_ecr_default(sample_ctx, fake_git)
    fake_docker.exit_codes[("exit", "login")] = 1
    with pytest.raises(RegistryPushFailed):
        run_containerize(ctx, fake_docker, fake_git, aws=fake_aws)
    assert not [c for c in fake_docker.calls if c[0] == "push"]



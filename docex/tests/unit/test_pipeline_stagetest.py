"""Unit tests for ``docex stagetest``."""

from __future__ import annotations

from docex.pipeline.stagetest import run_stagetest


def test_stagetest_builds_then_runs(sample_ctx, fake_docker):
    rc = run_stagetest(sample_ctx, fake_docker)
    assert rc == 0
    methods = [c[0] for c in fake_docker.calls]
    assert "build_image" in methods
    assert "run_one_shot" in methods
    # Build must precede run.
    assert methods.index("build_image") < methods.index("run_one_shot")


def test_stagetest_url_from_domain(sample_ctx, fake_docker):
    """STAGING_URL should be derived from infra.yml's ``domain`` field."""
    rc = run_stagetest(sample_ctx, fake_docker)
    assert rc == 0
    run_call = next(c for c in fake_docker.calls if c[0] == "run_one_shot")
    # run_one_shot recorded as
    # (method, image, command_tuple, env_items_tuple, network, mounts_tuple)
    env_items = dict(run_call[3])
    # sample fixture has domain: example.com → https://stage.example.com
    assert env_items["STAGING_URL"] == "https://stage.example.com"


def test_stagetest_injects_project_version(sample_ctx, fake_docker):
    """PROJECT_VERSION env var should be injected from project.yml.version
    so stage tests can assert the deployed /health version without
    hand-syncing an EXPECTED_VERSION literal. Mod 011."""
    rc = run_stagetest(sample_ctx, fake_docker)
    assert rc == 0
    run_call = next(c for c in fake_docker.calls if c[0] == "run_one_shot")
    env_items = dict(run_call[3])
    assert env_items["PROJECT_VERSION"] == sample_ctx.project.version


def test_stagetest_override_url(sample_ctx, fake_docker):
    rc = run_stagetest(sample_ctx, fake_docker, staging_url_override="http://localhost:8080")
    assert rc == 0
    run_call = next(c for c in fake_docker.calls if c[0] == "run_one_shot")
    env_items = dict(run_call[3])
    assert env_items["STAGING_URL"] == "http://localhost:8080"


def test_stagetest_uses_host_network(sample_ctx, fake_docker):
    rc = run_stagetest(sample_ctx, fake_docker)
    assert rc == 0
    run_call = next(c for c in fake_docker.calls if c[0] == "run_one_shot")
    network = run_call[4]
    assert network == "host"


def test_stagetest_bind_mounts_project(sample_ctx, fake_docker):
    rc = run_stagetest(sample_ctx, fake_docker)
    assert rc == 0
    run_call = next(c for c in fake_docker.calls if c[0] == "run_one_shot")
    mounts = run_call[5]
    project_root = sample_ctx.project_root
    assert any(f"{project_root}:/project" == m for m in mounts), mounts


def test_stagetest_propagates_container_exit_code(sample_ctx, fake_docker):
    """If the stage tester exits non-zero, that exit code reaches us."""
    # Use the key shape recorded by FakeDockerClient.
    fake_docker.exit_codes[("exit", "run_one_shot")] = 13
    rc = run_stagetest(sample_ctx, fake_docker)
    assert rc == 13

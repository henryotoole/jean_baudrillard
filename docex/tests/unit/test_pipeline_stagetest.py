"""Unit tests for ``docex stagetest``.

Mod 128 rewrote this file onto ``_run_one_shot_call``. Every test used to reach
into ``fake_docker.calls`` by positional tuple index (``run_call[3]``, ``[4]``,
``[5]``), so any change to the recorded shape broke seven tests at once and none
of them said what they were reading. Naming the fields fixes that.

Every test now also needs a transport: the sample fixture is ``fixed``, so
``run_stagetest``'s orchestrator pre-step reads the deployed env over SSH before
building anything. It is scripted here with a healthy ``FakeSSHClient`` —
**there is no flag that turns the pre-step off, and none may be added** (mod 128
overview § *The gate has no off switch*).
"""

from __future__ import annotations

import pytest

from docex.errors import DeployedServiceUnhealthy
from docex.pipeline.stagetest import run_stagetest

from tests.conftest import FakeSSHClient

_HEALTHY_INSPECT = "healthy|running|registry.example.com/sample/api:0.1.0"


def _run_one_shot_call(fake_docker) -> dict:
    """The recorded ``run_one_shot`` call, with its fields named.

    ``FakeDockerClient`` records it positionally as
    ``(method, image, command, env_items, network, mounts)``.
    """
    call = next(c for c in fake_docker.calls if c[0] == "run_one_shot")
    return {
        "image": call[1],
        "command": call[2],
        "env": dict(call[3]),
        "network": call[4],
        "mounts": call[5],
    }


@pytest.fixture
def healthy_ssh(sample_ctx) -> FakeSSHClient:
    """A deployed fixed stage env that reads back healthy and on-version.

    Also writes the deploy key the pre-step requires before any SSH; the sample
    fixture ships one, and this makes the dependency explicit.
    """
    key = sample_ctx.project_root / "infra" / "deploy_creds" / "stage"
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text("dummy-key\n")
    return FakeSSHClient(capture_out=_HEALTHY_INSPECT)


def test_stagetest_builds_then_runs(sample_ctx, fake_docker, healthy_ssh):
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 0
    methods = [c[0] for c in fake_docker.calls]
    assert "build_image" in methods
    assert "run_one_shot" in methods
    # Build must precede run.
    assert methods.index("build_image") < methods.index("run_one_shot")


def test_stagetest_url_from_apex_domain(sample_ctx, fake_docker, healthy_ssh):
    """STAGING_URL should be derived from infra.yml's ``apex_domain`` field
    combined with the project name per cicl.md § Domain
    (<env>.<project>.<apex_domain>)."""
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 0
    # sample fixture has apex_domain: example.com, project: sample
    # → https://stage.sample.example.com
    assert _run_one_shot_call(fake_docker)["env"]["STAGING_URL"] == (
        "https://stage.sample.example.com"
    )


def test_stagetest_injects_project_version(sample_ctx, fake_docker, healthy_ssh):
    """PROJECT_VERSION env var should be injected from project.yml.version
    so stage tests can assert the deployed /health version without
    hand-syncing an EXPECTED_VERSION literal. Mod 011."""
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 0
    assert _run_one_shot_call(fake_docker)["env"]["PROJECT_VERSION"] == (
        sample_ctx.project.version
    )


def test_stagetest_override_url(sample_ctx, fake_docker, healthy_ssh):
    rc = run_stagetest(
        sample_ctx, fake_docker, ssh=healthy_ssh,
        staging_url_override="http://localhost:8080",
    )
    assert rc == 0
    assert _run_one_shot_call(fake_docker)["env"]["STAGING_URL"] == (
        "http://localhost:8080"
    )


def test_stagetest_uses_host_network(sample_ctx, fake_docker, healthy_ssh):
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 0
    assert _run_one_shot_call(fake_docker)["network"] == "host"


def test_stagetest_bind_mounts_project(sample_ctx, fake_docker, healthy_ssh):
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 0
    mounts = _run_one_shot_call(fake_docker)["mounts"]
    project_root = sample_ctx.project_root
    assert any(f"{project_root}:/project" == m for m in mounts), mounts


def test_stagetest_propagates_container_exit_code(
    sample_ctx, fake_docker, healthy_ssh
):
    """If the stage tester exits non-zero, that exit code reaches us."""
    # Use the key shape recorded by FakeDockerClient.
    fake_docker.exit_codes[("exit", "run_one_shot")] = 13
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 13


# ---------------------------------------------------------------------------
# Mod 128 — the orchestrator pre-step's position in the command.
# ---------------------------------------------------------------------------


def test_orchestrator_pre_step_runs_before_the_tester_is_built(
    sample_ctx, fake_docker, healthy_ssh
):
    """``cicd.md § Staging Tests`` numbers the orchestrator read as step 1: it
    must precede the build, not merely happen somewhere."""
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 0
    assert [c[0] for c in healthy_ssh.calls] == ["capture"]
    assert "build_image" in [c[0] for c in fake_docker.calls]
    # There is no timestamp to compare, so assert the invariant that carries the
    # ordering: the SSH read happened, and the test below proves a *failing*
    # read stops the build entirely.


def test_failing_pre_step_means_the_tester_is_never_built(
    sample_ctx, fake_docker, healthy_ssh
):
    """Worth its own test: an ordering that merely *raised later* would still
    satisfy every other assertion in this file. Nothing docker-side may run."""
    healthy_ssh.capture_out = (
        "unhealthy|running|registry.example.com/sample/api:0.1.0"
    )
    with pytest.raises(DeployedServiceUnhealthy):
        run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    methods = [c[0] for c in fake_docker.calls]
    assert "build_image" not in methods
    assert "run_one_shot" not in methods


def test_missing_apex_domain_still_reports_the_config_bug_first(
    sample_ctx, fake_docker, healthy_ssh
):
    """The STAGING_URL derivation stays ahead of the orchestrator read (see the
    WHY in stagetest.py): a project missing ``apex_domain`` has a config bug, and
    saying so beats reporting whatever the orchestrator happens to say."""
    sample_ctx.infra.apex_domain = ""
    rc = run_stagetest(sample_ctx, fake_docker, ssh=healthy_ssh)
    assert rc == 1
    assert healthy_ssh.calls == []
    assert fake_docker.calls == []

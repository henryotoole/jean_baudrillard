"""Unit tests for the container vessel (Mod 148)."""

from __future__ import annotations

import pytest

from docex.jobs.vessel import ContainerVessel, LaunchResult


def _spec_call(fake_docker):
    """The recorded ``run_detached_spec`` tuple, if any."""
    for c in fake_docker.calls:
        if c[0] == "run_detached_spec":
            return c
    return None


def test_launch_issues_one_run_detached_with_the_job_command(
    sample_ctx, fake_docker
):
    vessel = ContainerVessel(fake_docker, "sample-test-runner")
    res = vessel.launch(sample_ctx, "20260824T000000Z-abc123")
    assert isinstance(res, LaunchResult)
    assert res.rc == 0 and res.name_conflict is False

    detached = [c for c in fake_docker.calls if c[0] == "run_detached"]
    assert len(detached) == 1
    _, name, image, command = detached[0]
    assert name == "sample-test-runner"
    assert command == ("docex", "__run-job", "20260824T000000Z-abc123")


def test_launch_clones_the_inspected_spec_and_filters_env(
    sample_ctx, fake_docker
):
    """Self-inspection clone: image/binds/user/workdir/group_add are carried,
    and env is filtered to HOME only (TERM and DOCEX_* dropped)."""
    vessel = ContainerVessel(fake_docker, "sample-test-runner")
    vessel.launch(sample_ctx, "rid-1")

    spec = _spec_call(fake_docker)
    assert spec is not None
    _, name, binds, user, env, workdir, group_add = spec
    # Image is carried on the primary call tuple.
    detached = [c for c in fake_docker.calls if c[0] == "run_detached"][0]
    assert detached[2] == "docex:test"
    assert user == "1000:1000"
    assert workdir == "/proj"
    assert group_add == ("999",)
    assert binds == (
        "/proj:/proj",
        "/etc/passwd:/etc/passwd:ro",
        "/var/run/docker.sock:/var/run/docker.sock",
    )
    # Env filtering: HOME kept, TERM + DOCEX_* dropped.
    assert env == ("HOME=/home/dev",)


def test_launch_falls_back_to_reconstruct_on_introspection_failure(
    sample_ctx, fake_docker, capsys
):
    fake_docker.inspect_self_raises = True
    vessel = ContainerVessel(fake_docker, "sample-test-runner")
    vessel.launch(sample_ctx, "rid-2")

    # A warning is emitted so the operator knows the spec was reconstructed.
    err = capsys.readouterr().err
    assert "self-inspect" in err and "reconstruct" in err.lower()

    # The reconstructed spec uses image docex:<docex_version> from ctx.
    detached = [c for c in fake_docker.calls if c[0] == "run_detached"][0]
    assert detached[2] == f"docex:{sample_ctx.project.docex_version}"

    spec = _spec_call(fake_docker)
    _, _name, binds, user, env, workdir, _group = spec
    # The documented shim mount contract: project root mirrored, socket, etc.
    proot = str(sample_ctx.project_root)
    assert f"{proot}:{proot}" in binds
    assert "/etc/passwd:/etc/passwd:ro" in binds
    assert "/var/run/docker.sock:/var/run/docker.sock" in binds
    assert workdir == proot
    # Env is HOME-only here too.
    assert all(e.startswith("HOME=") for e in env)


def test_launch_surfaces_name_conflict(sample_ctx, fake_docker):
    fake_docker.run_detached_result = (1, True)
    vessel = ContainerVessel(fake_docker, "sample-test-runner")
    res = vessel.launch(sample_ctx, "rid-3")
    assert res.rc == 1
    assert res.name_conflict is True


def test_is_running_and_remove_delegate_to_docker(fake_docker):
    fake_docker.container_running_results["sample-test-runner"] = True
    vessel = ContainerVessel(fake_docker, "sample-test-runner")
    assert vessel.is_running() is True
    assert vessel.remove() == 0
    assert ("container_rm", "sample-test-runner") in fake_docker.calls

"""Integration test: ``docex test`` runs end-to-end and tears down."""

from __future__ import annotations

import subprocess

import pytest

from docex.context import load_project_context
from docex.orchestrate._common import (
    compose_file_for,
    ensure_compiled,
    env_compose_project,
)
from docex.orchestrate.aggregate import aggregate
from docex.orchestrate.test import run_test


def _test_web_bridge_absent() -> bool:
    """True if the ``sample-test-web`` bridge does NOT exist on the daemon.

    Mod 153 re-tiered ``test``'s web network from an external projinfra
    network to an env-tier bridge the stack creates. A leftover of that name
    would let a run lean on a pre-existing network and invalidate the
    no-projinfra gate.
    """
    probe = subprocess.run(
        ["docker", "network", "inspect", "sample-test-web"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return probe.returncode != 0


@pytest.mark.integration
def test_docex_test_passes_and_tears_down(fresh_project, docker_client):
    ctx = load_project_context(fresh_project)
    compose_file = fresh_project / "infra" / "output" / "test" / "docker-compose.yml"

    # Mod 153: the run must not lean on a leftover projinfra web network —
    # test's web network is now env-tier and created by the stack itself.
    assert _test_web_bridge_absent(), (
        "sample-test-web must NOT pre-exist — mod 153 removed test's projinfra "
        "web dependency; a leftover would invalidate the gate"
    )

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


@pytest.mark.integration
def test_test_web_reachable_over_retiered_bridge(fresh_project, docker_client):
    """Mod 153: the single test slot's web core service is reachable over the
    env-tier, non-external ``sample-test-web`` bridge — and the bridge is
    created by the stack itself (no projinfra).

    ``run_test`` brings the stack up, runs the shims, and tears it down inside
    one call, so an external probe cannot catch the stack mid-flight. This test
    instead brings the ``test`` stack up directly (mirroring ``run_up``: the
    aggregate mints the env's TTE and is fed to compose as the ``--env-file``),
    hits the web service over the bridge, then tears down.
    """
    ctx = load_project_context(fresh_project)
    ensure_compiled(ctx)
    compose_file = compose_file_for(ctx, "test")
    project_name = env_compose_project(ctx, "test")
    # Aggregate mints the env's TTE (e.g. POSTGRES_PASSWORD) and merges
    # secrets/config, exactly as `run_up` does before `compose up`.
    env_file = aggregate(ctx, env="test")

    # Precondition: the bridge does not pre-exist (no projinfra dependency).
    assert _test_web_bridge_absent(), (
        "sample-test-web must NOT pre-exist — a leftover would invalidate "
        "the no-projinfra gate"
    )
    try:
        rc = docker_client.compose_up(
            compose_file, build=True, detach=True,
            env_file=env_file, project_dir=fresh_project,
            project_name=project_name,
        )
        assert rc == 0, "test stack should come up with no projinfra"

        # The bridge exists now, created by the stack — not external.
        assert not _test_web_bridge_absent(), (
            "sample-test-web should have been created by the stack itself"
        )

        # Reach the web core service over that bridge from a one-off
        # container attached to it. The fixture app serves GET /health ->
        # {"version": "0.1.0"} on :8080; the container name is the global
        # name sample-test-api-web. Retry a few times since the web
        # container may need a moment to bind :8080.
        out = subprocess.check_output(
            ["docker", "run", "--rm", "--network", "sample-test-web",
             "alpine:latest", "sh", "-c",
             "for i in $(seq 1 15); do "
             "wget -qO- http://sample-test-api-web:8080/health && exit 0; "
             "sleep 1; done; exit 1"],
            text=True, timeout=90,
        )
        assert '"version"' in out and "0.1.0" in out, out
    finally:
        docker_client.compose_down(
            compose_file, preserve_volumes=False,
            env_file=env_file, project_dir=fresh_project,
            project_name=project_name,
        )

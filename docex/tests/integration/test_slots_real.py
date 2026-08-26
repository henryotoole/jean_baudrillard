"""Integration test (Mod 154): ``docex test --slots 2`` shards, isolates, reaps.

The fixture's suite is tiny by design, so a 2-slot real run is cheap.
This exercises the sharded path end-to-end against a real docker daemon:
two fully name-isolated ``test`` stacks (slot 1 unslotted, slot 2 carrying the
``-s2-`` segment on every physical name) brought up concurrently, the whole
suite sharded across them via the injected ``DOCEX_TEST_SLOT`` /
``DOCEX_TEST_SLOTS``, both torn down on success.
"""
from __future__ import annotations

import subprocess

import pytest

from docex.cicl.compile import compile_slot
from docex.context import load_project_context
from docex.orchestrate.test import run_test


_SLOT2_PROJECT = "sample-test-s2"
_SLOT2_VOLUME = "sample-test-s2-appdb_data"


def _down_slot2() -> None:
    """Reclaim the slot-2 stack + volume (the shared-stack autouse fixture only
    cleans the unslotted ``sample-test``)."""
    subprocess.run(
        ["docker", "compose", "-p", _SLOT2_PROJECT, "down", "-v", "--remove-orphans"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    subprocess.run(
        ["docker", "volume", "rm", "-f", _SLOT2_VOLUME],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


def _running_containers(project: str) -> str:
    return subprocess.check_output(
        ["docker", "ps", "--filter", f"label=com.docker.compose.project={project}",
         "--format", "{{.Names}}"],
        text=True,
    ).strip()


@pytest.mark.integration
def test_docex_test_slots2_shards_isolates_and_tears_down(
    fresh_project, docker_client
):
    ctx = load_project_context(fresh_project)
    _down_slot2()
    try:
        rc = run_test(ctx, docker_client, slots=2)
        assert rc == 0, "sharded 2-slot run should pass against the fixture"

        # The slot-2 stack was compiled with FULLY isolated names — every
        # physical name carries the -s2- segment (Mod 152/153). The run used
        # exactly this artifact.
        slot2_compose = (
            fresh_project / ".docex" / "slots" / "test" / "2" / "docker-compose.yml"
        )
        assert slot2_compose.is_file(), "slot-2 compose file must have been emitted"
        body = slot2_compose.read_text()
        assert "sample-test-s2-api-exec" in body
        assert "sample-test-s2-api-web" in body
        assert "sample-test-s2-appdb_data" in body
        # Slot 1 stays unslotted (tracked output, no segment).
        slot1_compose = (
            fresh_project / "infra" / "output" / "test" / "docker-compose.yml"
        )
        s1 = slot1_compose.read_text()
        assert "sample-test-api-exec" in s1
        assert "sample-test-s2-" not in s1

        # Both stacks torn down on success — no leftover containers in either
        # compose project (slot 1 == sample-test, slot 2 == sample-test-s2).
        assert _running_containers("sample-test") == ""
        assert _running_containers(_SLOT2_PROJECT) == ""
    finally:
        _down_slot2()

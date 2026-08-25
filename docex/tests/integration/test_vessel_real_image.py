"""Integration: drive the **real docex image** as a container vessel, end to end.

This is the coverage the 1388-green suite was missing. Every prior vessel test
either used the fake docker client (unit) or ran a trivial ``alpine`` container
directly through ``run_detached`` (``test_job_vessel_real.py``) — *nothing* ever
launched the real docex image as a vessel and let its ENTRYPOINT run. So the
entrypoint-doubling bug mod 157 fixed (the vessel built
``["docex", "__run-job", <id>]`` against an image whose ``ENTRYPOINT`` is already
``["docex"]``, yielding ``docex docex __run-job <id>`` → "unknown command
'docex'" → exit 64, so the job body never ran and no ``exit`` file was written)
was invisible.

This test closes that gap: it builds a fresh docex image, records a real
``kind="noop"`` run, and drives the **real ``ContainerVessel.launch`` through the
real image**. With the bug the vessel exits 64 and writes no ``exit`` file, so
``run_job_wait`` times out and the ``== 0`` assertion fails; with the fix the
``noop`` body runs and writes ``exit`` = 0.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from docex.docker import SubprocessDockerClient
from docex.jobs import commands, record
from docex.jobs.vessel import ContainerVessel

# The dedicated tag this test builds and drives. NEVER reuse an existing
# ``docex:<version>`` tag — this is a throwaway image built from the repo.
_IMAGE_TAG = "docex:jobs-vessel-itest"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def real_docex_image() -> str:
    """Build the docex image fresh from the repo Dockerfile into the dedicated
    ``docex:jobs-vessel-itest`` tag. A cached rebuild is ~seconds."""
    res = subprocess.run(
        ["docker", "build", "-t", _IMAGE_TAG, str(_REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        pytest.fail(
            f"failed to build {_IMAGE_TAG} from {_REPO_ROOT}:\n"
            f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}"
        )
    return _IMAGE_TAG


@pytest.mark.integration
def test_real_docex_image_vessel_runs_noop_body(
    tmp_path, real_docex_image
):
    # A minimal project so the in-vessel `docex __run-job` can load its context.
    # docex_version drives the reconstructed image ref: docex:jobs-vessel-itest.
    (tmp_path / "project.yml").write_text(
        'name: sample\n'
        'version: "0.1.0"\n'
        'docex_version: "jobs-vessel-itest"\n'
    )

    run_id = record.new_run_id()
    vessel_name = f"docex-vessel-real-{run_id}"
    record.create_record(
        tmp_path,
        record.RunMeta(
            id=run_id,
            kind="noop",
            scope="itest/vessel-real",
            slot=1,
            vessel_kind="container",
            vessel_name=vessel_name,
            created_at=record.now_iso(),
            docex_version="jobs-vessel-itest",
            params={},
        ),
    )

    # On the host, inspect_self raises (this pytest process is not a container),
    # so launch takes the _reconstruct_spec path: image docex:jobs-vessel-itest,
    # docker socket + project root mounted, host uid:gid — the real launch path.
    ctx = types.SimpleNamespace(
        project_root=tmp_path,
        project=types.SimpleNamespace(
            name="sample", docex_version="jobs-vessel-itest"
        ),
    )
    docker = SubprocessDockerClient()

    try:
        res = ContainerVessel(docker, vessel_name).launch(ctx, run_id)
        assert res.name_conflict is False
        assert res.rc == 0  # the detached `docker run` create succeeded

        # Block on the authoritative exit file. With the pre-fix command the
        # vessel exits 64 and writes NO exit file, so this times out and returns
        # WAIT_TIMEOUT_EXIT (75) → the `== 0` assertion FAILS (fail-on-bug).
        # With the fix, run_in_vessel runs the noop body and writes exit = 0.
        assert commands.run_job_wait(ctx, docker, run_id, timeout=120) == 0
        assert record.read_exit(tmp_path, run_id) == 0

        # After it exits (the vessel is not --rm), it is present-but-stopped,
        # and classify reads TERMINAL off the exit file.
        assert docker.container_running(vessel_name) is False
        assert (
            record.classify(tmp_path, run_id, docker)
            is record.Outcome.TERMINAL
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", vessel_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

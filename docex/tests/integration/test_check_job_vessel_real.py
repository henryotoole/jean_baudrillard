"""Integration: a second job kind crosses the real docker boundary (Mod 149).

Mirrors ``test_job_vessel_real.py``'s **trivial short-lived body** approach — a
~1 s alpine container, never a real check suite — but keys the run
``kind="check"`` to prove the detached-container → bind-mounted ``exit`` file →
``run_job_wait`` path works for a durable job kind other than ``test``. A full
real ``docex check`` job is exercised by the close-out manual walk, not here.
"""

from __future__ import annotations

import subprocess
import types

import pytest

from docex.jobs import commands, record


@pytest.mark.integration
def test_real_detached_check_kind_writes_exit_and_wait_reads_it(
    tmp_path, docker_client
):
    ctx = types.SimpleNamespace(project_root=tmp_path)
    run_id = record.new_run_id()
    record.create_record(
        tmp_path,
        record.RunMeta(
            id=run_id, kind="check", scope="itest/check", slot=1,
            vessel_kind="container", vessel_name=f"docex-checkjobtest-{run_id}",
            created_at=record.now_iso(), docex_version="0.0.0", params={},
        ),
    )
    rundir = record.run_dir(tmp_path, run_id)
    name = f"docex-checkjobtest-{run_id}"

    try:
        rc, conflict = docker_client.run_detached(
            name=name,
            image="alpine:latest",
            command=["sh", "-c", "sleep 1; printf '0\\n' > /rundir/exit"],
            binds=[f"{rundir}:/rundir"],
            user="",
            env=[],
            workdir="",
            group_add=[],
        )
        assert rc == 0 and conflict is False

        # The name is the lock: a real re-launch on the same name conflicts.
        rc2, conflict2 = docker_client.run_detached(
            name=name, image="alpine:latest", command=["true"],
            binds=[], user="", env=[], workdir="", group_add=[],
        )
        assert conflict2 is True and rc2 != 0

        # Block on the real exit file the container writes; it is authoritative.
        assert commands.run_job_wait(ctx, docker_client, run_id, timeout=30) == 0
        assert record.read_exit(tmp_path, run_id) == 0

        # After it exits (not --rm), the vessel is present-but-stopped → False,
        # and classify reads TERMINAL off the exit file for kind=check too.
        assert docker_client.container_running(name) is False
        assert record.classify(tmp_path, run_id, docker_client) is record.Outcome.TERMINAL
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )

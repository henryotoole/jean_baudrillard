"""Integration test: ``docex migrate dev`` against a COLD stack.

Mod 113. The exec block's readiness gate is now the compiler's **only**
ordering emission — `uses` emits nothing onto any core or backing service's own
block (cicl.md § Uses Relationships), so this one gate is all that stands
between a one-shot `migrate.sh` and a database that has started but is not yet
accepting connections.

Nothing in either existing suite proves it works:

- ``test_migrate_real.py`` calls ``run_up`` **before** ``run_migrate``, so the
  database is already up and healthy by the time migrate runs. That test passes
  whether the gate says ``service_healthy``, ``service_started``, or is absent
  entirely.
- ``pytest tests/unit`` cannot see it at all — the gate's failure mode is a
  runtime race, not a wrong byte in the emitted YAML. (The emission-level guard
  is ``test_exec_service.py::test_7_uses_gate_is_long_form_and_health_gated``;
  this test is its behavioural half.)

So a regression here would survive both suites and first appear during a smoke
walk as an *intermittent migration failure*, which reads as a flaky database
rather than as a compiler bug. Hence: no prior ``run_up``. ``compose run`` must
bring the database up through the exec block's gate, and the migration must
succeed against it on the first attempt.
"""

from __future__ import annotations

import subprocess

import pytest

from docex.context import load_project_context
from docex.orchestrate.down import run_down
from docex.orchestrate.migrate import run_migrate


@pytest.mark.integration
def test_migrate_on_a_cold_stack_waits_for_the_database(
    fresh_project, docker_client
):
    ctx = load_project_context(fresh_project)
    compose_file = fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"
    try:
        # NO run_up. This is the entire point of the test: the database is not
        # running, so `compose run` on the exec service must start it and the
        # gate must hold until it is actually accepting connections.
        rc = run_migrate(ctx, docker_client, env="dev")
        assert rc == 0, (
            "migrate failed against a cold stack — the exec block's readiness "
            "gate did not hold. Check that it is long-form with "
            "`condition: service_healthy` and not a bare short-form list."
        )

        env_file = fresh_project / ".docex" / "agg" / "dev.env"
        ps_out = subprocess.check_output(
            ["docker", "compose", "-f", str(compose_file),
             "--project-directory", str(fresh_project),
             "--project-name", "sample-dev",
             "--env-file", str(env_file),
             "ps", "--services", "--status=running"],
            text=True,
        )
        db_key = next(
            (s.strip() for s in ps_out.splitlines() if s.strip().endswith("appdb")),
            "appdb",
        )
        # The migration ran, so its table exists. Asserting the OUTCOME rather
        # than just the return code is what keeps a migrate that silently
        # no-ops from reading as a pass.
        result = subprocess.run(
            [
                "docker", "compose", "-f", str(compose_file),
                "--project-directory", str(fresh_project),
                "--project-name", "sample-dev",
                "--env-file", str(env_file),
                "exec", "-T", db_key,
                "psql", "-U", "appuser", "-d", "appdb",
                "-c", "\\dt health",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "health" in result.stdout, (
            f"psql \\dt did not show health table; stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
    finally:
        run_down(ctx, docker_client, env="dev")
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file),
             "--project-directory", str(fresh_project),
             "--project-name", "sample-dev",
             "--env-file", str(fresh_project / ".docex" / "agg" / "dev.env"),
             "down", "-v"],
            check=False,
        )

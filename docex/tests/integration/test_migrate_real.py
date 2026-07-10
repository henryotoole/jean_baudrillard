"""Integration test: ``docex migrate dev`` applies the init migration."""

from __future__ import annotations

import subprocess

import pytest

from docex.context import load_project_context
from docex.orchestrate.down import run_down
from docex.orchestrate.migrate import run_migrate
from docex.orchestrate.up import run_up


@pytest.mark.integration
def test_migrate_dev_creates_health_table(fresh_project, docker_client):
    ctx = load_project_context(fresh_project)
    compose_file = fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"
    try:
        rc = run_up(ctx, docker_client, env="dev")
        assert rc == 0

        # Re-run migrate explicitly — should be idempotent.
        rc = run_migrate(ctx, docker_client, env="dev")
        assert rc == 0

        # Confirm the migration's table exists by asking psql.
        # We exec into the appdb container. The container-facing env now comes
        # from the derived aggregate (TTE ∪ secrets ∪ config), not the raw
        # secrets file — POSTGRES_PASSWORD is a minted TTE value that lives
        # there, so point compose's --env-file at the aggregate.
        env_file = fresh_project / ".docex" / "agg" / "dev.env"
        # Find appdb service's project-scoped global name.
        # Mod 053: match docex's explicit env-tier --project-name
        # (<dns_label>-<env> = "sample-dev") so these probes address the
        # stack docex brought up.
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
        # The default DBName is the backing-service name "appdb" (from the
        # engine table's ${name} substitution), not the project name.
        result = subprocess.run(
            [
                "docker", "compose", "-f", str(compose_file),
                "--project-directory", str(fresh_project),
                "--project-name", "sample-dev",
                "--env-file", str(env_file),
                "exec", "-T", db_key,
                # POSTGRES_USER is now the doctrine-fixed literal `appuser`
                # (kind: fixed), not the old committed `sample`.
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

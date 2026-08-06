"""Integration test: what a *container* receives in ``DOCEX_SCHEDULES_YAML``.

The unit test in ``tests/unit/test_clock.py`` pins what the emitter *writes*
(``$$`` where the source had ``$``). This pins the other half — that a real
``docker compose`` resolves that back to a single literal ``$`` and hands the
container a byte-identical schedule table.

WHY this runs a container rather than ``docker compose config``: ``config``
re-escapes ``$`` back to ``$$`` on output so its output is itself a valid
compose file, which means it *cannot* answer the question being asked. Only
the process's own environment can. The probe is busybox printing one variable,
so it is still cheap.

The emitted ``docker-compose.yml`` stays authoritative — an override file
supplies only the throwaway image and command, so the ``environment`` block
under test is exactly what ``emit_compose`` wrote.

Gated by ``@pytest.mark.integration``; auto-skipped when no docker daemon is
reachable (see ``conftest.py``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import compile_env
from docex.context import load_project_context
from docex.emit.compose import emit_compose


_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures" / "sample_project_clock_fixed"
)

# The `$` is injected post-compile because validation forbids one in an
# authored cron expression. The escaping is emitter behaviour over the whole
# payload, so injecting the hazard here exercises the same code path a future
# grammar change would.
_JOBS = {"nightly_cleanup": "0 3 * * *", "dollar_job": "0 3 * * $X"}

# `$${...}` reaches the container's shell as `${...}` — compose halves it,
# exactly as it must halve the payload.
_OVERRIDE = """
services:
  sample-dev-api-clock:
    image: busybox:latest
    build: !reset null
    volumes: !reset null
    healthcheck: !reset null
    command: ["sh", "-c", "printf '%s' \\"$${DOCEX_SCHEDULES_YAML}\\""]
"""


@pytest.mark.integration
def test_container_receives_a_single_dollar(tmp_path: Path):
    root = tmp_path / "project"
    shutil.copytree(_FIXTURE, root, dirs_exist_ok=False)
    ctx = load_project_context(root)
    compiled = compile_env(
        ctx.infra, ctx.transfer_tables, env="dev",
        project_name=ctx.project.name, project_version=ctx.project.version,
    )
    compiled.services["api-clock"].schedules = dict(_JOBS)
    compose_file = root / "infra" / "output" / "dev" / "docker-compose.yml"
    compose_file.parent.mkdir(parents=True, exist_ok=True)
    emit_compose(compiled, compose_file)

    override = root / "probe.override.yml"
    override.write_text(_OVERRIDE)

    project_name = "sample-dev-clockprobe"
    argv = [
        "docker", "compose",
        "-f", str(compose_file), "-f", str(override),
        "--project-directory", str(root),
        "--project-name", project_name,
        "--env-file", str(root / "infra" / "secrets" / "dev.env"),
    ]
    try:
        delivered = subprocess.check_output(
            [*argv, "run", "--rm", "--no-deps", "-T", "sample-dev-api-clock"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    finally:
        subprocess.run(
            [*argv, "down", "-v", "--remove-orphans"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )

    assert delivered.count("$") == 1, (
        "the container must receive exactly one literal `$`; got "
        f"{delivered!r}"
    )
    assert yaml.safe_load(delivered) == _JOBS

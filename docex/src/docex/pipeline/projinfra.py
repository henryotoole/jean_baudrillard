"""``docex projinfra <direction> <side>`` — project-tier infrastructure
runner. Mod 036 ships the fixed branch (per-project traefik + four
``-web`` networks); mods 037-039 add elastic.

The doctrine-level behavior lives in
``doctrine/infrastructure/specifics/projinfra/overview.md`` and
``doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md``.
This module is the runtime wiring: ``up`` invokes
``docker compose -f <side>/docker-compose.yml up -d``; ``down`` refuses
when env-tier compose stacks for the same project are still up, then
invokes ``docker compose down`` (volumes preserved by default so the
ACME named volume survives).
"""

from __future__ import annotations

from pathlib import Path

from docex.context import ProjectContext
from docex.docker.client import DockerClient


def _project_compose_path(ctx: ProjectContext, side: str) -> Path:
    return (
        ctx.project_root
        / "infra" / "output" / "project" / side / "docker-compose.yml"
    )


def run_projinfra_fixed_up(
    ctx: ProjectContext, docker: DockerClient, *, side: str,
) -> int:
    """Bring up the project-tier compose stack for ``side`` (development
    or production) on a fixed-style projinfra surface.

    On a single-machine fixed project the two sides operate on the same
    docker daemon and converge: running ``up production`` after ``up
    development`` is a docker-compose-up no-op because both emitted
    compose files declare the same resource set.
    """
    compose_file = _project_compose_path(ctx, side)
    if not compose_file.is_file():
        print(
            f"error: {compose_file} not found — run `docex compile` first."
        )
        return 1
    # WHY: build=False — the project-tier compose has no build context;
    # the traefik image is pulled from a registry by digest. Passing
    # --build is harmless but noisy.
    rc = docker.compose_up(compose_file, build=False, detach=True)
    if rc != 0:
        print(
            f"error: `docker compose up` failed with exit code {rc} "
            f"for {compose_file}."
        )
    return rc


def run_projinfra_fixed_down(
    ctx: ProjectContext, docker: DockerClient, *, side: str,
) -> int:
    """Tear down the project-tier compose stack for ``side``.

    Refuses if any env-tier compose stack for this project is still up —
    projinfra is the foundation env-tier sits on. The ACME named volume
    is preserved (``compose_down`` defaults ``preserve_volumes=True``)
    so cert state survives.
    """
    if docker.any_env_compose_up(ctx.project.name):
        print(
            f"error: env-tier compose stacks for project "
            f"{ctx.project.name!r} are still up. Run `docex envinfra "
            f"down <env>` first for every active env, then re-run."
        )
        return 1
    compose_file = _project_compose_path(ctx, side)
    if not compose_file.is_file():
        print(
            f"warning: {compose_file} not found — nothing to tear down."
        )
        return 0
    return docker.compose_down(compose_file, preserve_volumes=True)

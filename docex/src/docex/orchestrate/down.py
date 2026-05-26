"""``docex down <env>`` — tear down a previously-running stack.

Volumes are preserved by default per doctrine (persistent data survives
``docex down``). The ``test`` env's teardown via ``docex test`` is the
one place we pass ``preserve_volumes=False`` — but that's handled there,
not here.
"""

from __future__ import annotations

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.orchestrate._common import (
    assert_fixed_env,
    compose_file_for,
    ensure_compiled,
    env_file_for,
)


def run_down(ctx: ProjectContext, docker: DockerClient, *, env: str) -> int:
    """Tear down the ``<env>`` stack, preserving named volumes."""
    assert_fixed_env(env, command="down")
    # Compose file must exist for down to know what to tear down.
    # We re-compile so the file is fresh even if infra.yml drifted.
    ensure_compiled(ctx)

    compose_file = compose_file_for(ctx, env)
    env_file = env_file_for(ctx, env)
    return docker.compose_down(compose_file, preserve_volumes=True, env_file=env_file)

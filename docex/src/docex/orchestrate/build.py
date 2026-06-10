"""``docex build [<svc>]`` — refresh ``dist/`` in the running dev env.

This is the dev-iteration build path. The canonical, ship-worthy build
happens inside ``docker build`` (which runs ``build.sh`` in the build
stage). ``docex build`` is the convenience equivalent for when a
developer wants fresh artifacts without paying for a container rebuild.

Per cicd.md § Build Step (dev iteration):

  1. Verify dev is running.
  2. Clear ``$pr/core/<svc>/dist/`` on the host.
  3. ``compose exec`` the service's ``./build.sh``.
  4. Assert ``dist/`` is non-empty afterward.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import BuildFailed, EnvNotRunning, EnvNotSupported
from docex.orchestrate._common import (
    compose_file_for,
    core_services,
    ensure_compiled,
    env_file_for,
)


_BUILD_ENV = "dev"


def run_build(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    service: str | None = None,
) -> int:
    """Run ``build.sh`` for one or all core services.

    ``service=None`` builds every core service in deterministic order.
    The first failure short-circuits the rest (matches the doctrine's
    "fail at the first non-zero exit" contract for build).
    """
    ensure_compiled(ctx)

    compose_file = compose_file_for(ctx, _BUILD_ENV)
    if not compose_file.is_file():
        raise EnvNotSupported(
            f"dev compose file not found at {compose_file}; run "
            "'docex compile' (this should not happen — ensure_compiled "
            "should have created it)."
        )

    env_file = env_file_for(ctx, _BUILD_ENV)
    # Verify dev is running by asking compose what services are up.
    running = set(docker.compose_ps(compose_file, env_file=env_file))
    if not running:
        raise EnvNotRunning(
            "dev env is not running; run 'docex up dev' first."
        )

    all_cores = core_services(ctx)
    if service is None:
        targets = all_cores
    else:
        if service not in all_cores:
            raise EnvNotSupported(
                f"service {service!r} is not a core service; "
                f"known core services: {all_cores}"
            )
        targets = [service]

    for svc in targets:
        rc = _build_one(ctx, docker, compose_file, svc, running=running, env_file=env_file)
        if rc != 0:
            return rc
    return 0


def _build_one(
    ctx: ProjectContext,
    docker: DockerClient,
    compose_file: Path,
    svc: str,
    *,
    running: set[str],
    env_file: Path | None,
) -> int:
    """Run the full dev-iteration build path for a single service."""
    # The compose service key is the project-scoped name (e.g.
    # ``sample-dev-api``), not the simple name. ``compose_ps`` returns
    # simple service names per compose's --services output. Find the
    # one whose suffix matches our simple name.
    matching = [s for s in running if s == svc or s.endswith(f"_{svc}") or s.endswith(f"-{svc}")]
    if not matching:
        # ``compose_ps`` (above) lists only *running* services, so a
        # crash-looping container reads as "not running" here. Consult
        # the all-states view to tell a Restarting/unhealthy container
        # apart from a genuinely-absent one and give the operator a
        # diagnostic that points at the real problem. (Gap D, mod 050.)
        status = docker.compose_ps_status(compose_file, env_file=env_file)
        state = next(
            (
                st
                for key, st in status.items()
                if key == svc or key.endswith(f"_{svc}") or key.endswith(f"-{svc}")
            ),
            None,
        )
        if state in ("restarting", "unhealthy"):
            raise EnvNotRunning(
                f"dev container for service {svc!r} is {state}, not "
                f"running — check `docker logs` for it. `docex build` "
                f"needs a healthy dev container; fix the crash (often a "
                f"missing env var or a failed prior build) and retry."
            )
        raise EnvNotRunning(
            f"dev container for service {svc!r} is not running; "
            "run 'docex up dev' first."
        )
    service_key = matching[0]

    # Step 2: clear host-side dist/.
    dist_dir = ctx.project_root / "core" / svc / "dist"
    if dist_dir.exists():
        # Wipe contents, not the directory itself — the bind mount
        # would otherwise need to be re-established by the container.
        for child in dist_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        dist_dir.mkdir(parents=True, exist_ok=True)

    # Step 3: invoke build.sh inside the running container.
    rc = docker.compose_exec(compose_file, service_key, ["./build.sh"], env_file=env_file)
    if rc != 0:
        print(
            f"error: build.sh for service {svc!r} exited {rc}.",
            file=sys.stderr,
        )
        return rc

    # Step 4: assert dist/ non-empty.
    if not dist_dir.exists() or not any(dist_dir.iterdir()):
        raise BuildFailed(
            f"build.sh for {svc!r} exited 0 but {dist_dir} is empty. "
            "Likely causes: build.sh wrote to a different path, or the "
            "container's /service/dist isn't bind-mounted to "
            f"{dist_dir} (check 'docex compile' regenerated the "
            "compose file with the Phase 2 bind-mount patch)."
        )

    print(f"build: refreshed {svc} dist/ ({sum(1 for _ in dist_dir.iterdir())} entries)")
    return 0

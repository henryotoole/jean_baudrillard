"""``docex build [<svc>]`` — refresh ``dist/`` in the running dev env.

This is the dev-iteration build path. The canonical, ship-worthy build
happens inside ``docker build`` (which runs ``build.sh`` in the build
stage). ``docex build`` is the convenience equivalent for when a
developer wants fresh artifacts without paying for a container rebuild.

Per cicd.md § Build Step (dev iteration):

  1. Verify dev is running.
  2. Clear ``$pr/core/<svc>/dist/`` on the host.
  3. ``compose run --rm`` the codebase's exec service with ``./build.sh``
     (Mod 099; ``cicd.md § Build Step`` still says ``exec`` and is Mod
     106's to fix).
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
    env_compose_project,
    exec_service_key,
)
from docex.orchestrate.aggregate import aggregate


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

    # Bring-up site: aggregate so the build exec sees the same env the dev
    # stack was brought up with (compose interpolation on the running stack).
    env_file = aggregate(ctx, env=_BUILD_ENV)
    project_name = env_compose_project(ctx, _BUILD_ENV)
    # Verify dev is running by asking compose what services are up.
    running = set(docker.compose_ps(
        compose_file, env_file=env_file,
        project_dir=ctx.project_root, project_name=project_name,
    ))
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
        rc = _build_one(
            ctx, docker, compose_file, svc,
            env_file=env_file, project_name=project_name,
        )
        if rc != 0:
            return rc
    return 0


def _build_one(
    ctx: ProjectContext,
    docker: DockerClient,
    compose_file: Path,
    svc: str,
    *,
    env_file: Path | None,
    project_name: str,
) -> int:
    """Run the full dev-iteration build path for a single service."""
    # The codebase's exec service — the container that *is* the codebase
    # (Mod 099). `build.sh` therefore sees codebase-scoped env only, and the
    # codebase → container rule is a construction, not a suffix scan.
    service_key = exec_service_key(ctx, _BUILD_ENV, svc)
    # MOD 099 DELETED the per-service "is this container running" gate and
    # its crash-loop diagnostic (Gap D, mod 050) that stood here. Mechanically
    # it had to go: the exec service is `profiles:`-gated and so is never in
    # the running set by construction. But it should have gone anyway — the
    # gate refused to run `docex build` when the dev container was
    # restarting/unhealthy, and the most common cause of a crash-looping dev
    # container is an empty `dist/`, which is exactly what `docex build`
    # fills. It blocked the one command that resolves the state it detected.
    # Under `compose run` the dev container's health is simply irrelevant to
    # refreshing `dist/`. If the diagnostic is ever wanted back, its place is
    # `up.py::_diagnose_unhealthy`, not a precondition on `build`. The
    # whole-stack `if not running: raise EnvNotRunning` in `run_build` stays.

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

    # Step 3: invoke build.sh in a one-off exec-service container.
    #
    # WHY no `build=True` here, unlike the `test`-env one-offs (Mod 103):
    # `docex build` is dev-only and IS the hot iteration loop the dev/test
    # asymmetry exists to protect. The source arrives by bind mount and the
    # Dockerfile `dev` stage exists precisely so `build.sh` can be re-invoked
    # without rebuilding the image — adding `--build` would put a real,
    # non-cached `RUN ./build.sh` image rebuild in front of the one command
    # whose entire purpose is to avoid it. Do not "fix" this omission.
    rc = docker.compose_run_one_off(
        compose_file, service_key, ["./build.sh"], env_file=env_file,
        project_dir=ctx.project_root, project_name=project_name,
    )
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

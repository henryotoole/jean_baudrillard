"""``docex build [<codebase>]`` — refresh ``dist/`` in the running dev env.

This is the dev-iteration build path. The canonical, ship-worthy build
happens inside ``docker build`` (which runs ``build.sh`` in the build
stage). ``docex build`` is the convenience equivalent for when a
developer wants fresh artifacts without paying for a container rebuild.

Per cicd.md § Build Step (dev iteration):

  1. Verify dev is running.
  2. Ensure ``$pr/core/<codebase>/dist/`` exists on the host.
  3. ``compose run --rm`` the codebase's exec service, which clears
     ``/service/dist`` and then runs ``./build.sh`` (Mod 099; Mod 119
     moved the clear inside the container).
  4. Assert ``dist/`` is non-empty afterward.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import BuildFailed, EnvNotRunning, EnvNotSupported
from docex.orchestrate._common import (
    compose_file_for,
    codebases,
    ensure_compiled,
    env_compose_project,
    exec_service_key,
)
from docex.orchestrate.aggregate import aggregate


_BUILD_ENV = "dev"

# The dev-iteration clear + build, run as ONE command inside the codebase's
# exec service.
#
# WHY the clear is not host-side (Mod 119): `core/<codebase>/dist/` is a
# container-owned tree. Everything that writes into it writes as root through
# the bind mount — `up.py::_ensure_initial_dev_build`'s cp, `build.sh` under
# `compose run`, and the dev core service's `__pycache__` on import. The host
# owns the directory node (docex mkdir'd it) and nothing inside. Unlink
# permission comes from the *parent* directory, so the host uid can delete a
# root-owned `dist/app.py` but not anything inside a root-owned
# `dist/__pycache__/` — which is exactly what `shutil.rmtree` used to hit,
# with PermissionError. It was self-regenerating: `run_up` created the residue
# its own `run_build` then could not delete. The container is root and can,
# so the clear goes where the writer is. This also means a checkout that
# already has residue self-heals on the next build with no operator `sudo`.
#
# WHY one command rather than a separate clear container: `docex build` IS the
# hot iteration loop — the same reason this path deliberately does not pass
# `build=True` (see the note in `_build_one`). A second container start is pure
# added latency on the one command whose purpose is to be cheap.
#
# WHY `find -mindepth 1 -delete` rather than `rm -rf dist/*`: the bind-mount
# point itself cannot be removed, and glob-based deletion misses dotfiles
# without a cryptic `./.[!.]* ./..?*` incantation. It is also the idiom the
# doctrine's own sample `build.sh` uses, for this same reason.
#
# DEPENDENCY: the dev stage image must carry `sh` and `find`. `sh` was already
# required (`build.sh` is `#!/bin/sh` and is invoked as `./build.sh`); `find`
# is in both coreutils and busybox, so any base carrying a build toolchain has
# it. Deliberately NOT a doctrine rule: the doctrine's one image requirement
# (`curl`) is backed by a `docex check` gate, and an unenforced image
# requirement is a claim in the rule of record that nothing verifies. The
# failure mode here is loud anyway — `find: not found`, non-zero exit, build
# fails immediately.
_CLEAR_AND_BUILD = (
    "set -e; cd /service; mkdir -p dist; "
    "find dist -mindepth 1 -delete; exec ./build.sh"
)


def run_build(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    codebase: str | None = None,
) -> int:
    """Run ``build.sh`` for one or all codebases.

    ``codebase=None`` builds every codebase in deterministic order.
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

    all_codebases = codebases(ctx)
    if codebase is None:
        targets = all_codebases
    else:
        if codebase not in all_codebases:
            raise EnvNotSupported(
                f"{codebase!r} is not a codebase in infra.yml; "
                f"known codebases: {all_codebases}"
            )
        targets = [codebase]

    for cb in targets:
        rc = _build_one(
            ctx, docker, compose_file, cb,
            env_file=env_file, project_name=project_name,
        )
        if rc != 0:
            return rc
    return 0


def _build_one(
    ctx: ProjectContext,
    docker: DockerClient,
    compose_file: Path,
    codebase: str,
    *,
    env_file: Path | None,
    project_name: str,
) -> int:
    """Run the full dev-iteration build path for a single codebase."""
    # The codebase's exec service — the container that *is* the codebase
    # (Mod 099). `build.sh` therefore sees codebase-scoped env only, and the
    # codebase → container rule is a construction, not a suffix scan.
    service_key = exec_service_key(ctx, _BUILD_ENV, codebase)
    # MOD 099 DELETED the per-codebase "is this container running" gate and
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

    # Step 2: ensure the host-side dist/ directory node exists. Its
    # *contents* are cleared inside the container — see _CLEAR_AND_BUILD.
    dist_dir = ctx.project_root / "core" / codebase / "dist"
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
        compose_file, service_key, ["sh", "-c", _CLEAR_AND_BUILD],
        env_file=env_file, project_dir=ctx.project_root,
        project_name=project_name,
    )
    if rc != 0:
        print(
            f"error: clear+build for codebase {codebase!r} exited {rc} "
            "(ran in the codebase's exec service).",
            file=sys.stderr,
        )
        return rc

    # Step 4: assert dist/ non-empty.
    if not dist_dir.exists() or not any(dist_dir.iterdir()):
        raise BuildFailed(
            f"build.sh for {codebase!r} exited 0 but {dist_dir} is empty. "
            "Likely causes: build.sh wrote to a different path, or the "
            "container's /service/dist isn't bind-mounted to "
            f"{dist_dir} (check 'docex compile' regenerated the "
            "compose file with the Phase 2 bind-mount patch)."
        )

    print(f"build: refreshed {codebase} dist/ ({sum(1 for _ in dist_dir.iterdir())} entries)")
    return 0

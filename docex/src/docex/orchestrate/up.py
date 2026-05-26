"""``docex up <env>`` — bring up a dev/test stack locally.

Per docex.md § up: validates the env is dev/test, recompiles defensively,
brings up the compose stack with --build, then runs migrations against
every schema-owning core service.

Deliberately does *not* auto-tear-down on failure. A half-up stack is
exactly what the developer needs to debug. The teardown contract lives
on ``docex down``.
"""

from __future__ import annotations

import sys

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import BuildFailed, EnvNotRunning
from docex.orchestrate._common import (
    assert_fixed_env,
    compose_file_for,
    compose_service_key,
    core_services,
    ensure_compiled,
    env_file_for,
    services_with_schema,
)


def _ensure_initial_dev_build(
    ctx: ProjectContext, docker: DockerClient, svc: str
) -> None:
    """Populate host ``core/<svc>/dist/`` via a one-shot build-stage run.

    The dev stage Dockerfile's ``RUN ./build.sh`` deposits artifacts
    inside the image at /service/dist, but the host bind mount shadows
    that path at runtime — so without a pre-populated host dist/, the
    dev container's CMD has no app.py to run and crashes in a restart
    loop. We build the "build" stage as a throwaway image and copy
    its /service/dist contents to the host dist/.

    Idempotent: skipped if host dist/ already has contents.
    """
    host_dist = ctx.project_root / "core" / svc / "dist"
    if host_dist.exists() and any(host_dist.iterdir()):
        return  # Already populated; respect host state.

    svc_dir = ctx.project_root / "core" / svc
    dockerfile = svc_dir / "Dockerfile"
    if not dockerfile.is_file():
        return  # Non-conformant fixture; let compose up surface it.

    host_dist.mkdir(parents=True, exist_ok=True)
    image_tag = f"docex-initial-build-{svc}:latest"

    rc = docker.build_image(svc_dir, target="build", tag=image_tag)
    if rc != 0:
        raise BuildFailed(
            f"docker build --target build for service {svc!r} exited {rc}."
        )

    rc = docker.run_one_shot(
        image_tag,
        ["sh", "-c", "cp -r /service/dist/. /host_dist/"],
        mounts=[(host_dist, "/host_dist")],
        remove=True,
    )
    if rc != 0:
        raise BuildFailed(
            f"failed to copy initial build artifacts for {svc!r} "
            f"into host dist/ (docker run exit {rc})."
        )


def run_up(ctx: ProjectContext, docker: DockerClient, *, env: str) -> int:
    """Bring up the ``<env>`` stack and run migrations.

    Returns the first non-zero exit code encountered, or 0 on success.
    """
    assert_fixed_env(env, command="up")
    ensure_compiled(ctx)

    compose_file = compose_file_for(ctx, env)
    env_file = env_file_for(ctx, env)

    # 1a. Dev only: pre-populate the host dist/ for each core service
    # before bringing the stack up. The dev stage Dockerfile's
    # ``RUN ./build.sh`` populates the *in-image* dist/, but the host
    # bind mount shadows that — so without a host-side dist/ the dev
    # container's CMD has nothing to execute and crashes in a restart
    # loop. We do a one-time build.sh by running a throwaway build-stage
    # container with the host dist/ bind-mounted, then proceed to compose
    # up. Idempotent: skipped if dist/ is already populated.
    #
    # Test env intentionally skips this — its images carry artifacts
    # baked in by the build stage and aren't bind-mounted.
    if env == "dev":
        for svc in core_services(ctx):
            _ensure_initial_dev_build(ctx, docker, svc)

    # 1b. Compose up. Compose itself handles "rebuild if Dockerfile or
    # context changed" so we don't add caching on top.
    rc = docker.compose_up(compose_file, build=True, detach=True, env_file=env_file)
    if rc != 0:
        print(
            f"error: 'docker compose up' failed (exit {rc}); stack left as-is.",
            file=sys.stderr,
        )
        return rc

    # 2. Migrations. dev/test migrations run inside the running container.
    schema_owners = services_with_schema(ctx)
    for svc in schema_owners:
        # Compose's service key is the project-scoped global name, not
        # the simple service name from infra.yml.
        key = compose_service_key(ctx, env, svc)
        rc = docker.compose_exec(compose_file, key, ["./migrate.sh"], env_file=env_file)
        if rc != 0:
            print(
                f"error: migrate.sh for service {svc!r} exited {rc}; "
                "stack is up but migrations failed.",
                file=sys.stderr,
            )
            return rc

    domain = ctx.infra.domain if ctx.infra is not None else "<unknown>"
    subdomain = f"{env if env != 'prod' else 'www'}.{domain}"
    print(
        f"Stack up. Compose file: {compose_file}. "
        f"Migrated services: {schema_owners or '(none)'}. "
        f"Domain: {subdomain}"
    )
    return 0

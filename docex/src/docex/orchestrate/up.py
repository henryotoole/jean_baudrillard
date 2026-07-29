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
from docex.naming import dns_label
from docex.orchestrate._common import (
    assert_fixed_env,
    compose_file_for,
    core_services,
    ensure_compiled,
    env_compose_project,
    exec_service_key,
    scheduler_only_services,
    services_with_schema,
)
from docex.orchestrate.aggregate import aggregate


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


def _ensure_codebase_image(
    ctx: ProjectContext, docker: DockerClient, svc: str
) -> None:
    """Build a codebase's dev-local image tag, for dev.

    In ``dev``, the codebase tag is the Dockerfile ``dev`` stage — for every
    process type, including a cron job. Two facts make that invariant
    load-bearing rather than arbitrary (Mod 103):

    1. Ofelia spawns the job through the Docker API with **no bind mounts**,
       so the job runs whatever ``/service/dist`` the image carries. The
       doctrinal ``dev`` stage bakes it (``RUN ./build.sh``), which is the
       same assumption :func:`_ensure_initial_dev_build` already documents.
    2. The tag is **codebase**-keyed (Mod 096) and Mod 099's exec service
       builds the same tag at ``target: dev``. ``compose run`` only builds
       when the image is *absent*, so a ``prod``-stage image sitting on that
       tag is reused by ``docex build`` / ``test`` / ``migrate`` — and the
       doctrinal ``prod`` stage carries no ``build.sh`` and no ``test.sh``.
       Mod 074's ``prod`` build therefore **broke ``docex build dev``** for
       any project with a scheduler-only codebase. Two consumers of one tag
       must agree on what is inside it.

    The tag is derived through the same ``_image_ref`` the compiler uses, so
    it is byte-identical to what was written into the Ofelia INI's
    ``image =`` and to what the exec service's ``image:`` names.

    A missing ``core/<svc>/Dockerfile`` is a real error here (nothing else
    builds this tag), so — unlike :func:`_ensure_initial_dev_build`, which
    tolerates non-conformant fixtures — we let ``docker build`` surface it
    loudly.
    """
    from docex.cicl.compile import _image_ref

    svc_dir = ctx.project_root / "core" / svc
    image_ref = _image_ref(
        ctx.infra.container_registry if ctx.infra else None,
        ctx.project.name,
        svc,
        ctx.project.version,
        env="dev",
        foundation="fixed",
    )
    rc = docker.build_image(svc_dir, target="dev", tag=str(image_ref))
    if rc != 0:
        raise BuildFailed(
            f"docker build --target dev for core service {svc!r} "
            f"exited {rc}. In dev, the codebase's image tag is the "
            f"Dockerfile `dev` stage — every consumer of that tag (the "
            f"exec service, an Ofelia job) expects that stage."
        )


# Per-state operator guidance for a partial bring-up. Keyed by the
# coarse state ``compose_ps_status`` reports. ``running``/``created`` are
# not failures and carry no diagnostic.
_DIAGNOSTICS = {
    "restarting": (
        "container is restart-looping — check `docker logs {name}`; "
        "common causes: missing env var, crash on startup."
    ),
    "unhealthy": (
        "healthcheck never passed — verify the healthcheck "
        "endpoint/tooling is present in the image."
    ),
    "exited": "container exited — check `docker logs {name}`.",
}


def _diagnose_unhealthy(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    env: str,
    compose_file,
    env_file,
) -> None:
    """Print one diagnostic line per non-running service in the stack.

    Diagnosis only — no auto-fix, no teardown (a half-up stack is what
    the developer needs to debug). Called on a compose/migrate failure
    where a partial or unhealthy stack is the likely culprit.

    Mod 099: iterates the ``compose_ps_status`` map itself rather than
    deriving a compose key per *core codebase*. The old form could only ever
    report a core service, so an unhealthy backing service — the single most
    likely reason ``up`` fails — was invisible to the very function that
    exists to diagnose ``up`` failures. Reporting by compose key also names
    the exact container the operator passes to ``docker logs``.
    """
    status = docker.compose_ps_status(
        compose_file,
        env_file=env_file,
        project_dir=ctx.project_root,
        project_name=env_compose_project(ctx, env),
    )
    if not status:
        return
    for key in sorted(status):
        diag = _DIAGNOSTICS.get(status[key])
        if diag is None:
            continue
        print(
            f"envinfra up: service {key!r}: {diag.format(name=key)}",
            file=sys.stderr,
        )


def run_up(ctx: ProjectContext, docker: DockerClient, *, env: str) -> int:
    """Bring up the ``<env>`` stack and run migrations.

    Returns the first non-zero exit code encountered, or 0 on success.
    """
    assert_fixed_env(env, command="up")
    ensure_compiled(ctx)

    compose_file = compose_file_for(ctx, env)
    # Bring-up: build the aggregate (TTE ∪ secrets ∪ config), minting the
    # env's TTE store if absent, and feed it to compose as the --env-file.
    env_file = aggregate(ctx, env=env)
    project_name = env_compose_project(ctx, env)

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
        # Scheduler-ONLY codebases are the ones with no bind-mounted compose
        # service at all; a codebase that also declares a long-running
        # process type still needs its host-side dist/ pre-populated.
        schedulers = set(scheduler_only_services(ctx))
        for svc in core_services(ctx):
            # Scheduler-only codebases aren't bind-mounted and never run as
            # a compose service, so the host-dist/ pre-populate is
            # meaningless for them. They instead need their codebase image
            # built below by `_ensure_codebase_image`.
            if svc in schedulers:
                continue
            _ensure_initial_dev_build(ctx, docker, svc)
        # Mod 103: a scheduler-only codebase has no non-gated compose service,
        # so nothing in the compose graph builds its image — `up --build` skips
        # the `profiles: [exec]` exec service, and `compose run` builds only when
        # the image is absent. docex builds it here. A codebase that also
        # declares a long-running process type needs nothing: `compose up
        # --build` below builds that same tag, at the same `dev` target.
        for svc in scheduler_only_services(ctx):
            _ensure_codebase_image(ctx, docker, svc)

    # 1b. Compose up. Compose itself handles "rebuild if Dockerfile or
    # context changed" so we don't add caching on top.
    #
    # Mod 075: pass the ABSOLUTE env-file path as DOCEX_SECRETS_ENV_FILE so
    # Compose interpolates it into any scheduler's ofelia INI `volume`
    # source. A relative source fails at the Docker API (ofelia spawns the
    # job outside Compose). Harmless when the stack has no scheduler.
    # Mod 080: this is the aggregate — the scheduler job needs TTE + secrets
    # + config, not just the raw secrets file (which no longer holds TTE).
    rc = docker.compose_up(
        compose_file, build=True, detach=True, env_file=env_file,
        project_dir=ctx.project_root, project_name=project_name,
        extra_env={"DOCEX_SECRETS_ENV_FILE": str(env_file)},
    )
    if rc != 0:
        print(
            f"error: 'docker compose up' failed (exit {rc}); stack left as-is.",
            file=sys.stderr,
        )
        _diagnose_unhealthy(
            ctx, docker, env=env, compose_file=compose_file, env_file=env_file
        )
        return rc

    # 2. Migrations. dev/test migrations run as a one-off container built
    # from the codebase's exec service (Mod 099), so `migrate.sh` sees
    # codebase-scoped env only and needs no app container to exec into.
    #
    # WHY build=(env == "test") (Mod 103): in `test` the image *is* the
    # artifact under test, so a one-off must never run a stale one — and
    # `compose run` builds only when the image is ABSENT, silently reusing a
    # stale image otherwise. In `dev` the source arrives by bind mount and the
    # `dev` stage exists precisely so `build.sh` can be re-invoked without
    # rebuilding the image, so forcing a rebuild there would contradict the
    # rationale for the stage and slow the hot loop.
    schema_owners = services_with_schema(ctx)
    for svc in schema_owners:
        key = exec_service_key(ctx, env, svc)
        rc = docker.compose_run_one_off(
            compose_file, key, ["./migrate.sh"], build=(env == "test"),
            env_file=env_file,
            project_dir=ctx.project_root, project_name=project_name,
        )
        if rc != 0:
            print(
                f"error: migrate.sh for service {svc!r} exited {rc}; "
                "stack is up but migrations failed.",
                file=sys.stderr,
            )
            _diagnose_unhealthy(
                ctx, docker, env=env, compose_file=compose_file, env_file=env_file
            )
            return rc

    if ctx.infra is not None:
        apex_domain = ctx.infra.apex_domain
        # Canonical bare-env host per cicl.md § Domain:
        # <env>.<project>.<apex_domain>. Project segment is DNS-labeled.
        project_seg = dns_label(ctx.project.name)
        subdomain = f"{env}.{project_seg}.{apex_domain}"
    else:
        subdomain = "<unknown>"
    print(
        f"Stack up. Compose file: {compose_file}. "
        f"Migrated services: {schema_owners or '(none)'}. "
        f"Domain: {subdomain}"
    )
    return 0

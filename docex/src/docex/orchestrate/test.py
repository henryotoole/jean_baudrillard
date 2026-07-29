"""``docex test`` — the build-test step.

Per cicd.md § Build Test Step:

  1. Bring up the test env (compose handles `docker build`, which
     runs build.sh in the build stage so test images carry correct
     artifacts).
  2. Migrate against the test env.
  3. Run each core service's test.sh, collecting exit codes.
  4. Always tear down with ``preserve_volumes=False`` (test env is
     throwaway; fresh runs get fresh databases).

The teardown happens in a ``finally`` block so a Python exception in
steps 2-3 still tears the env down. Exit 0 only if every step exited 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.naming import dns_label
from docex.orchestrate._common import (
    compose_file_for,
    core_services,
    ensure_compiled,
    env_compose_project,
    exec_service_key,
    scheduler_only_services,
    services_with_schema,
)
from docex.orchestrate.aggregate import aggregate


_TEST_ENV = "test"


def _run_scheduler_tests(
    ctx: ProjectContext,
    docker: DockerClient,
    svc: str,
    *,
    project_dir: "Path | None",
) -> int:
    """Run a scheduler service's test.sh via a one-off container.

    A scheduler has no long-running container in the ``test`` stack
    (scheduler.md § Caveats — the compiler emits no Ofelia container for
    ``test``), so it cannot be ``compose exec``-ed like other core
    services. Build its ``test``-stage image and run ``test.sh`` as a
    one-off (mirrors ``up.py::_ensure_scheduler_image``'s build-directly
    pattern). The scheduler's tests are self-contained unit/module tests
    per the doctrine, so no env-tier stack/network is attached.
    """
    base = project_dir if project_dir is not None else ctx.project_root
    svc_dir = base / "core" / svc
    tag = f"docex-test-{dns_label(ctx.project.name)}-{svc}:latest"
    rc = docker.build_image(svc_dir, target="test", tag=tag)
    if rc != 0:
        return rc
    return docker.run_one_shot(tag, ["./test.sh"])


def run_test(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    project_dir: "Path | None" = None,
    env_file_override: "Path | None" = None,
    project_name: "str | None" = None,
) -> int:
    """Run the full build-test cycle. Returns process exit code.

    ``project_dir`` and ``env_file_override`` exist for ``docex check``,
    which calls ``run_test`` against an ephemeral worktree whose
    configurable-value files (gitignored) don't exist on disk. The check
    pipeline passes the host path of the worktree as ``project_dir`` so
    compose resolves build contexts and bind-mounts to the worktree, and
    the worktree's aggregate (``.docex/agg/test.env``, built after
    mirroring the source files in) as ``env_file_override`` so compose's
    ``${VAR}`` substitutions resolve cleanly.

    ``project_name`` overrides the compose ``--project-name``; ``docex
    check`` passes a worktree-unique name so its throwaway ``test`` stack
    can't collide with (or get torn down alongside) a real ``test`` env
    stack on the same host. Defaults to the standard env-tier name.
    """
    ensure_compiled(ctx)
    compose_file = compose_file_for(ctx, _TEST_ENV)
    # Bring-up site. With no override this builds the test aggregate here;
    # ``docex check`` passes its own already-built worktree aggregate as the
    # override (it mirrors the gitignored source files into the worktree and
    # aggregates there — see pipeline/check.py).
    env_file = (
        env_file_override
        if env_file_override is not None
        else aggregate(ctx, env=_TEST_ENV)
    )
    if project_name is None:
        project_name = env_compose_project(ctx, _TEST_ENV)

    first_failure: int = 0
    try:
        # 1. compose up --build -d
        rc = docker.compose_up(
            compose_file, build=True, detach=True,
            env_file=env_file, project_dir=project_dir,
            project_name=project_name,
        )
        if rc != 0:
            print(
                f"error: 'docker compose up' for test env exited {rc}.",
                file=sys.stderr,
            )
            return rc

        # 2. migrate every schema-owning service.
        for svc in services_with_schema(ctx):
            key = exec_service_key(ctx, _TEST_ENV, svc)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./migrate.sh"],
                env_file=env_file, project_dir=project_dir,
                project_name=project_name,
            )
            if rc != 0:
                print(
                    f"error: migrate.sh for {svc!r} in test env exited {rc}.",
                    file=sys.stderr,
                )
                first_failure = rc
                # Per the doctrine, build test fails on first failure.
                return rc

        # 3. test.sh for each core service, in the codebase's exec service.
        schedulers = set(scheduler_only_services(ctx))
        for svc in core_services(ctx):
            # MOD 103 DELETES THIS BRANCH. The carve-out existed because a
            # scheduler-only codebase had no exec-able container in the test
            # stack; Mod 099's exec service is emitted for every codebase,
            # scheduler-only ones included, so the branch below is now
            # unnecessary rather than merely awkward. It stays here only to
            # keep the two mods' diffs separable.
            if svc in schedulers:
                rc = _run_scheduler_tests(ctx, docker, svc, project_dir=project_dir)
            else:
                key = exec_service_key(ctx, _TEST_ENV, svc)
                rc = docker.compose_run_one_off(
                    compose_file, key, ["./test.sh"],
                    env_file=env_file, project_dir=project_dir,
                    project_name=project_name,
                )
            if rc != 0:
                print(
                    f"error: test.sh for {svc!r} exited {rc}.",
                    file=sys.stderr,
                )
                first_failure = rc
                return rc
    finally:
        # 4. Always tear down — even if a Python exception interrupted
        # us. preserve_volumes=False: test env's data is throwaway.
        td_rc = docker.compose_down(
            compose_file, preserve_volumes=False,
            env_file=env_file, project_dir=project_dir,
            project_name=project_name,
        )
        if td_rc != 0 and first_failure == 0:
            # Don't mask a real test failure with a teardown failure,
            # but do surface teardown failures when tests passed.
            print(
                f"warning: teardown exited {td_rc}.",
                file=sys.stderr,
            )

    return first_failure

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
from docex.orchestrate._common import (
    compose_file_for,
    compose_service_key,
    core_services,
    ensure_compiled,
    env_compose_project,
    env_file_for,
    services_with_schema,
)


_TEST_ENV = "test"


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
    secret files (gitignored) don't exist on disk. The check pipeline
    passes the host path of the worktree as ``project_dir`` so compose
    resolves build contexts and bind-mounts to the worktree, and the
    main project's ``infra/secrets/test.env`` as ``env_file_override``
    so compose's ``${VAR}`` substitutions resolve cleanly.

    ``project_name`` overrides the compose ``--project-name``; ``docex
    check`` passes a worktree-unique name so its throwaway ``test`` stack
    can't collide with (or get torn down alongside) a real ``test`` env
    stack on the same host. Defaults to the standard env-tier name.
    """
    ensure_compiled(ctx)
    compose_file = compose_file_for(ctx, _TEST_ENV)
    env_file = env_file_override if env_file_override is not None else env_file_for(ctx, _TEST_ENV)
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
            key = compose_service_key(ctx, _TEST_ENV, svc)
            rc = docker.compose_exec(
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

        # 3. test.sh for each core service.
        for svc in core_services(ctx):
            key = compose_service_key(ctx, _TEST_ENV, svc)
            rc = docker.compose_exec(
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

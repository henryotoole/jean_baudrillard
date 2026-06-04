"""``docex rollback <env> <target_version>`` — emergency reversion.

Per cicd.md § Rollback: narrow-window, code-only, at most one minor
version back. Reuses release machinery with migrations skipped.

The shape is:

  1. Aggressively check preconditions before touching any env state
     (branch + clean tree + tag existence + one-minor-back + every
     core service's image present in the registry).
  2. Create an ephemeral worktree at ``v<target_version>``.
  3. Recompile the worktree's ``infra.yml`` with the *current* ``docex``
     so the rolled-back compose/HCL reflects today's transfer-table
     rules (the operator's working tree is left untouched).
  4. Hand off to ``_release_fixed`` / ``_release_elastic`` with
     ``skip_migrations=True``.
  5. Tear down the worktree on every exit path.
"""

from __future__ import annotations

import sys
from typing import Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext, load_project_context
from docex.docker.client import DockerClient
from docex.errors import (
    EnvNotSupported,
    RollbackPreconditionFailed,
    WorkingTreeDirty,
)
from docex.git.client import GitClient
from docex.orchestrate._common import core_services
from docex.pipeline._worktree import (
    cleanup_worktree,
    make_temp_branch,
    validate_one_minor_back,
    worktree_path_for,
)
from docex.pipeline.release import _release_elastic, _release_fixed


RunPlaybook = Callable[..., int]
TofuInit = Callable[..., int]
TofuApply = Callable[..., int]
TofuPlan = Callable[..., int]


def run_rollback(
    ctx: ProjectContext,
    *,
    env: str,
    target_version: str,
    docker: DockerClient,
    git: GitClient,
    aws: AWSClient,
    ansible_runner: RunPlaybook,
    tofu_init: TofuInit,
    tofu_apply: TofuApply,
    tofu_plan: TofuPlan,
    dry_run: bool = False,
) -> int:
    """Roll ``env`` back to ``target_version``. Returns exit code.

    All dependencies are injected for the same reason ``release`` injects
    them: the unit tests substitute recorders.
    """
    if env not in ("stage", "prod"):
        raise EnvNotSupported(
            f"rollback target {env!r} is not supported; only 'stage' and 'prod'."
        )

    project_root = ctx.project_root
    infra = ctx.infra
    if infra is None:
        print(
            "error: rollback requires infra/infra.yml (none found).",
            file=sys.stderr,
        )
        return 1

    # ---- Preconditions (fail-fast on cheap checks, fail-aggregated on
    #      cross-service image probe so the operator sees the full list).

    if git.current_branch(project_root) != "main":
        raise RollbackPreconditionFailed(
            "rollback must run from 'main'. Check out main and try again."
        )
    if not git.is_clean(project_root):
        raise WorkingTreeDirty(
            "rollback refuses to run with a dirty working tree. "
            "Commit or stash first."
        )

    tag_name = f"v{target_version}"
    if not git.tag_exists(project_root, tag_name):
        raise RollbackPreconditionFailed(
            f"no tag {tag_name!r} exists in this repo. List available "
            f"versions with 'git tag -l v*' and supply a valid target."
        )

    current = ctx.project.version
    err = validate_one_minor_back(current, target_version)
    if err is not None:
        raise RollbackPreconditionFailed(err)

    # WHY: aggregate every missing image into one diagnostic rather than
    # failing on the first miss. Under emergency pressure the operator
    # benefits from the full picture; the probes are cheap.
    missing = _missing_images(
        ctx, docker=docker, aws=aws, target_version=target_version,
    )
    if missing:
        raise RollbackPreconditionFailed(
            "rollback aborted — image(s) missing in registry:\n  - "
            + "\n  - ".join(missing)
            + "\nThis target version was not fully containerized, or the "
            "registry no longer retains it."
        )

    # ---- Worktree + recompile -----------------------------------------
    worktree = worktree_path_for(project_root, f"rollback-{target_version}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    temp_branch = make_temp_branch("rollback", target_version)

    rc = git.worktree_add(project_root, worktree, branch=temp_branch, ref=tag_name)
    if rc != 0:
        print(
            f"error: 'git worktree add' for {tag_name!r} exited {rc}.",
            file=sys.stderr,
        )
        return rc

    try:
        worktree_ctx = load_project_context(worktree)

        # Imported lazily to mirror release.py's pattern (avoids a
        # pipeline -> compile -> ... cycle at module load).
        from docex.cicl.compile import run_compile

        rc = run_compile(worktree_ctx)
        if rc != 0:
            print(
                f"error: recompile of {tag_name!r} exited {rc}.",
                file=sys.stderr,
            )
            return rc

        # ---- Apply via release machinery, migrations skipped ----------
        if infra.foundation == "elastic":
            return _release_elastic(
                worktree_ctx,
                env=env,
                aws=aws,
                tofu_init=tofu_init,
                tofu_apply=tofu_apply,
                tofu_plan=tofu_plan,
                skip_migrations=True,
                dry_run=dry_run,
            )
        return _release_fixed(
            worktree_ctx,
            env=env,
            ansible_runner=ansible_runner,
            skip_migrations=True,
            dry_run=dry_run,
        )
    finally:
        cleanup_worktree(project_root, worktree, temp_branch, git)


def _missing_images(
    ctx: ProjectContext,
    *,
    docker: DockerClient,
    aws: AWSClient,
    target_version: str,
) -> list[str]:
    """Probe every core service's image at ``target_version``.

    Returns the list of missing ``<registry>/<project>/<svc>:<version>``
    refs, or an empty list if all are present. Foundation determines
    the probe mechanism: fixed → ``docker manifest inspect``; elastic →
    ECR ``describe_images``.
    """
    infra = ctx.infra
    assert infra is not None  # caller checks
    project = ctx.project.name

    # Resolve the registry the same way containerize does. For elastic
    # ECR-default (no explicit container_registry), the registry host
    # is derived from the AWS account ID.
    registry = infra.container_registry
    if not registry:
        if infra.foundation == "elastic":
            account = aws.caller_identity()
            registry = f"{account}.dkr.ecr.us-east-1.amazonaws.com"
        else:
            return ["<no container_registry configured>"]

    missing: list[str] = []
    for svc in core_services(ctx):
        ref = f"{registry.rstrip('/')}/{project}/{svc}:{target_version}"
        if infra.foundation == "elastic":
            present = aws.ecr_image_exists(f"{project}/{svc}", target_version)
        else:
            present = docker.manifest_inspect(ref)
        if not present:
            missing.append(ref)
    return missing

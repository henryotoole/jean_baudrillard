"""``docex rollback <env> <target_version>`` — emergency reversion.

Per cicd.md § Rollback: narrow-window, code-only, at most one minor
version back. Reuses release machinery with migrations skipped.

The shape is:

  1. Aggressively check preconditions before touching any env state
     (branch + clean tree + tag existence + one-minor-back + the
     target's CICL generation + every codebase's image present in
     the registry).
  2. Create an ephemeral worktree at ``v<target_version>``.
  3. Recompile the worktree's ``infra.yml`` with the *current* ``docex``
     so the rolled-back compose/HCL reflects today's transfer-table
     rules (the operator's working tree is left untouched).
  4. Hand off to ``_release_fixed`` / ``_release_elastic`` with
     ``skip_migrations=True``.
  5. Tear down the worktree on every exit path.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Callable

import yaml

from docex.aws.client import AWSClient
from docex.cicl.model import CURRENT_CICL_VERSION
from docex.context import ProjectContext, load_project_context
from docex.docker.client import DockerClient
from docex.errors import (
    EnvNotSupported,
    RollbackPreconditionFailed,
    WorkingTreeDirty,
)
from docex.git.client import GitClient
from docex.orchestrate._common import codebases
from docex.ssh.client import SSHClient
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
    ssh: SSHClient,
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
    # WHY: tolerate dirt under ``infra/output/`` because ``docex release``
    # rewrites that directory implicitly via its compile step — an
    # emergency operator who just released will legitimately have those
    # files modified vs HEAD and shouldn't be forced to commit them
    # before rolling back. Source dirt (under ``core/``, contracts,
    # secrets, etc.) is still refused, since that signals work in flight
    # that could confuse rollback semantics.
    if not git.is_clean_excluding(project_root, ["infra/output/"]):
        raise WorkingTreeDirty(
            "rollback refuses to run with uncommitted source changes. "
            "Commit or stash them first. (Dirt under 'infra/output/' "
            "is tolerated — that's the compile-output the release path "
            "rewrites implicitly.)"
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

    # WHY: rollback recompiles the target's infra.yml with the *current*
    # docex (cicd.md § Rollback step 3), so a target written in an older
    # CICL generation cannot be rolled back to at all. Check it here —
    # ahead of the registry probe and well ahead of the worktree — so an
    # operator mid-outage learns it before anything is touched, rather
    # than from a compile error inside a worktree. Ordered ahead of the
    # image probe by decisiveness, not just cost: a missing image can be
    # rebuilt from the tag, a boundary crossing cannot be resolved by
    # anything except fixing forward, so the image list would be noise.
    # See cicl.md § CICL Version.
    target_cicl, read_err = _target_cicl_version(
        project_root, git=git, tag_name=tag_name,
    )
    if read_err is not None:
        raise RollbackPreconditionFailed(
            f"rollback aborted — {read_err}.\n"
            "Nothing has been touched. Rollback recompiles the target "
            "version's infra.yml with the current docex, so it cannot "
            "proceed without reading it.\n\n"
            + _FIX_FORWARD
        )
    if target_cicl != CURRENT_CICL_VERSION:
        raise RollbackPreconditionFailed(
            _boundary_message(tag_name, target_cicl)
        )

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

        # WHY: the release functions read env-scoped credentials and
        # secrets via worktree_ctx.project_root. Those files
        # (infra/deploy_creds/<env>, infra/secrets/<env>.env,
        # infra/config/<env>.env) are gitignored per doctrine bootstrap
        # defaults, so they don't follow `git worktree add` — they live
        # only in the operator's main project tree. Mirror them in before
        # dispatching. (The fixed release also reads the host tte.env, but
        # that is fetched over SSH from the host, not from the worktree.)
        for src_rel in (
            f"infra/deploy_creds/{env}",
            f"infra/secrets/{env}.env",
            f"infra/config/{env}.env",
        ):
            src = project_root / src_rel
            if src.is_file():
                dst = worktree / src_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

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
            ssh=ssh,
            skip_migrations=True,
            dry_run=dry_run,
        )
    finally:
        cleanup_worktree(project_root, worktree, temp_branch, git)


def _target_cicl_version(
    project_root: Path,
    *,
    git: GitClient,
    tag_name: str,
) -> tuple[str | None, str | None]:
    """Read ``cicl_version`` from ``infra/infra.yml`` at ``tag_name``.

    Returns ``(version, read_error)`` — exactly one is non-None, except
    that an ``infra.yml`` which parses but declares no ``cicl_version``
    yields ``(None, None)``.

    WHY a single-key read rather than ``CICLDocument`` validation: a
    pre-v2 ``infra.yml`` fails full validation for several unrelated
    reasons at once (no ``core_services:``, ``domain_default_service``,
    core-service-level ``resources:`` under ``extra="forbid"``), and which
    one pydantic reports first decides what the operator sees. "You are
    across the v1 boundary" is the only fact that matters here, and it
    is the one a single-key read cannot get wrong. It also has to work
    on a file that is not a valid CICL document at all.
    """
    raw = git.show(project_root, tag_name, "infra/infra.yml")
    if raw is None:
        return None, f"could not read infra/infra.yml at tag {tag_name!r}"
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, (
            f"infra/infra.yml at tag {tag_name!r} is not parseable YAML: {exc}"
        )
    if not isinstance(doc, dict):
        return None, (
            f"infra/infra.yml at tag {tag_name!r} does not parse to a mapping"
        )
    value = doc.get("cicl_version")
    # WHY str(): an unquoted ``cicl_version: 2`` arrives as an int. The
    # compiler's own model would reject that document for the type, but
    # rollback's job here is to classify the target, not re-validate it,
    # and calling an unquoted 2 "across the boundary" would be a lie.
    return (None if value is None else str(value)), None


_FIX_FORWARD = (
    "Fix forward instead:\n"
    "  1. On main, fix the defect and bump project.yml past the broken "
    "version.\n"
    "  2. ./bin/docex check  →  merge  →  containerize  →  release <env>"
)


# Generations this docex RECOGNIZES as older than the one it compiles. A
# target declaring one of these gets the boundary message (which explains the
# condition and says it clears after one release); anything else is genuinely
# unknown and gets the generic branch.
_RECOGNIZED_OLDER_CICL = ("1", "2")


def _boundary_message(tag_name: str, target_cicl: str | None) -> str:
    """Compose the abort text for a target docex cannot compile.

    Splits on *why* the target is uncompilable, because the two cases
    call for different operator expectations: a RECOGNIZED older
    generation is a known one-release-cycle condition, an unrecognized
    generation is not.

    WHY parameterized on the target's own generation rather than
    hard-coding a boundary: every CICL bump makes the previous generation
    "the old one", and a message naming a fixed pair goes stale in the same
    instant the constant moves — which is exactly when the operator is
    reading it.
    """
    if target_cicl is None or target_cicl in _RECOGNIZED_OLDER_CICL:
        declared = (
            f'declares cicl_version "{target_cicl}"'
            if target_cicl is not None
            else "declares no cicl_version, so it predates the field"
        )
        generation = target_cicl if target_cicl is not None else "1"
        return (
            f"rollback aborted — cannot roll back across the CICL "
            f"v{generation}→v{CURRENT_CICL_VERSION} boundary.\n"
            "Nothing has been touched.\n"
            f"\nTarget {tag_name}'s infra/infra.yml {declared}. This docex "
            f'compiles only cicl_version "{CURRENT_CICL_VERSION}", and '
            "rollback recompiles the target's infra.yml with the *current* "
            "docex (cicd.md § Rollback step 3) — so no rollback to "
            "this target can succeed.\n\n"
            + _FIX_FORWARD
            + f'\n\nOnce a second cicl_version "{CURRENT_CICL_VERSION}" '
            "release exists, rollback works normally."
        )
    return (
        f"rollback aborted — target {tag_name}'s infra/infra.yml declares "
        f"cicl_version {target_cicl!r}, which this docex does not compile "
        f'(it compiles "{CURRENT_CICL_VERSION}").\n'
        "Nothing has been touched.\n\n" + _FIX_FORWARD
    )


def _missing_images(
    ctx: ProjectContext,
    *,
    docker: DockerClient,
    aws: AWSClient,
    target_version: str,
) -> list[str]:
    """Probe every codebase's image at ``target_version``.

    Returns the list of missing ``<registry>/<project>/<codebase>:<version>``
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
    for cb in codebases(ctx):
        ref = f"{registry.rstrip('/')}/{project}/{cb}:{target_version}"
        if infra.foundation == "elastic":
            present = aws.ecr_image_exists(f"{project}/{cb}", target_version)
        else:
            present = docker.manifest_inspect(ref)
        if not present:
            missing.append(ref)
    return missing

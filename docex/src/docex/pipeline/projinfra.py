"""``docex projinfra <direction> <side>`` — project-tier infrastructure
runner. Mod 036 ships the fixed branch (per-project traefik + four
``-web`` networks); mods 037-039 add elastic.

The doctrine-level behavior lives in
``doctrine/infrastructure/specifics/projinfra/projinfra.md`` and
``doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md``.
This module is the runtime wiring: ``up`` invokes
``docker compose -f <side>/docker-compose.yml up -d``; ``down`` refuses
when env-tier compose stacks for the same project are still up, then
invokes ``docker compose down`` (volumes preserved by default so the
ACME named volume survives).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import TofuApplyFailed
from docex.naming import apply_policy, dns_label


TofuRunner = Callable[..., int]

# The elastic environments whose env-tier must be torn down before the
# project tier (refuse-if-envs-up gate).
_ELASTIC_ENVS = ("stage", "prod")


def _project_compose_path(ctx: ProjectContext, side: str) -> Path:
    return (
        ctx.project_root
        / "infra" / "output" / "project" / side / "docker-compose.yml"
    )


def _project_compose_project(ctx: ProjectContext, side: str) -> str:
    """The explicit compose ``--project-name`` for a project-tier stack.

    ``<dns_label(project)>-projinfra-<side>`` — project-scoped, DNS-labeled,
    and stable across docex versions. Passed at both ``up`` and ``down`` so
    compose owns and can remove the per-project traefik AND the four ``-web``
    networks (which previously leaked under the bogus path-derived name
    ``infra``, per mod 053 / Cluster 1).
    """
    return f"{dns_label(ctx.project.name)}-projinfra-{side}"


def run_projinfra_fixed_up(
    ctx: ProjectContext, docker: DockerClient, *, side: str,
) -> int:
    """Bring up the project-tier compose stack for ``side`` (development
    or production) on a fixed-style projinfra surface.

    On a single-machine fixed project the two sides operate on the same
    docker daemon and converge: running ``up production`` after ``up
    development`` is a docker-compose-up no-op because both emitted
    compose files declare the same resource set.
    """
    compose_file = _project_compose_path(ctx, side)
    if not compose_file.is_file():
        print(
            f"error: {compose_file} not found — run `docex compile` first."
        )
        return 1
    # WHY: build=False — the project-tier compose has no build context;
    # the traefik image is pulled from a registry by digest. Passing
    # --build is harmless but noisy.
    rc = docker.compose_up(
        compose_file, build=False, detach=True,
        project_dir=ctx.project_root,
        project_name=_project_compose_project(ctx, side),
    )
    if rc != 0:
        print(
            f"error: `docker compose up` failed with exit code {rc} "
            f"for {compose_file}."
        )
    return rc


def run_projinfra_fixed_down(
    ctx: ProjectContext, docker: DockerClient, *, side: str,
) -> int:
    """Tear down the project-tier compose stack for ``side``.

    Refuses if any env-tier compose stack for this project is still up —
    projinfra is the foundation env-tier sits on. The ACME named volume
    is preserved (``compose_down`` defaults ``preserve_volumes=True``)
    so cert state survives.
    """
    if docker.any_env_compose_up(ctx.project.name):
        print(
            f"error: env-tier compose stacks for project "
            f"{ctx.project.name!r} are still up. Run `docex envinfra "
            f"down <env>` first for every active env, then re-run."
        )
        return 1
    compose_file = _project_compose_path(ctx, side)
    if not compose_file.is_file():
        print(
            f"warning: {compose_file} not found — nothing to tear down."
        )
        return 0
    return docker.compose_down(
        compose_file, preserve_volumes=True,
        project_dir=ctx.project_root,
        project_name=_project_compose_project(ctx, side),
    )


def run_projinfra_elastic_down(
    ctx: ProjectContext,
    aws: AWSClient,
    *,
    tofu_init: TofuRunner,
    tofu_destroy: TofuRunner,
) -> int:
    """Tear down the elastic project-tier — the inverse of ``run_bootstrap``.

    Order (Mod 052, Gap F):
      1. **Refuse-if-envs-up:** if any env's ECS cluster still exists,
         refuse and tell the operator to tear envs down first. Project
         tier is the foundation env-tier sits on.
      2. **ECR pre-flight:** if any project ECR repo is non-empty, refuse
         and report (reproducible build artifacts, but surfaced like
         every other blocker for consistency — empty and re-run).
      3. ``tofu destroy`` the project-tier ``main.tf``.
      4. Cleanup: delete the project's SSM parameters, then the state
         backend (S3 bucket + DynamoDB lock table). The state backend is
         removed **last** — nothing tofu-managed remains by then.

    Both gates run *before* anything is destroyed: a refusal leaves the
    project tier fully intact. docex never disables a protection or
    force-empties a repo itself.
    """
    project = ctx.project.name
    policies = ctx.transfer_tables.naming_policies
    ecs_policy = policies.get("ecs")

    # ---- Gate 1: refuse if any env-tier ECS cluster still exists. -----
    live_envs: list[str] = []
    for env in _ELASTIC_ENVS:
        cluster = apply_policy(f"{project}_{env}", ecs_policy)
        if aws.ecs_cluster_exists(cluster):
            live_envs.append(env)
    if live_envs:
        print(
            f"error: refusing to tear down the project tier — env-tier "
            f"resources still exist for: {', '.join(live_envs)}."
        )
        for env in live_envs:
            print(f"  - run `docex envinfra down {env}` first")
        print("\nNothing was destroyed.")
        return 1

    # ---- Gate 2: refuse on any non-empty project ECR repository. ------
    core_names = sorted((ctx.infra.core_services or {}) if ctx.infra else {})
    nonempty: list[tuple[str, int]] = []
    for name in core_names:
        repo = f"{project}/{name}"
        count = aws.ecr_repository_image_count(repo)
        if count > 0:
            nonempty.append((repo, count))
    if nonempty:
        print(
            "error: refusing to tear down the project tier — the following "
            "ECR repository(ies) still hold images:"
        )
        for repo, count in nonempty:
            print(f"  - {repo} has {count} image(s); empty it and re-run")
        print("\nNothing was destroyed.")
        return 1

    # ---- Step 3: tofu destroy the project tier. -----------------------
    project_dir = (
        ctx.project_root / "infra" / "output" / "project" / "production"
    )
    main_tf = project_dir / "main.tf"
    if not main_tf.is_file():
        print(
            f"warning: {main_tf} not found — skipping project-tier "
            f"`tofu destroy` (already removed?). Proceeding to cleanup."
        )
    else:
        rc_init = tofu_init(project_dir, backend=True)
        if rc_init != 0:
            raise TofuApplyFailed(
                f"'tofu init' in {project_dir} exited {rc_init}"
            )
        rc = tofu_destroy(project_dir, auto_approve=True)
        if rc != 0:
            raise TofuApplyFailed(
                f"project-tier 'tofu destroy' exited {rc}"
            )

    # ---- Step 4: cleanup — SSM, then state backend (last). ------------
    ssm_project = apply_policy(project, policies.get("ssm_path"))
    aws.ssm_delete_parameters(f"/{ssm_project}/")

    bucket = apply_policy(f"{project}_tofu_state", policies.get("s3"))
    table = apply_policy(f"{project}_tofu_locks", policies.get("ddb"))
    aws.s3_delete_bucket(bucket)
    aws.ddb_delete_table(table)

    print(
        f"projinfra down production: project {project!r} project-tier "
        f"and state backend removed."
    )
    return 0

"""``docex migrate <env>`` — apply database migrations.

dev/test: ``compose exec`` the ``./migrate.sh`` script inside each
schema-owning service's running container.

Stage/prod, fixed (Phase 3): invoke the ``migrate``-tagged step of the
env's emitted Ansible playbook.

Stage/prod, elastic (Phase 4): ECS RunTask of the per-service
``*_migrate`` task definition emitted by ``docex compile``. Each task
runs ``/service/migrate.sh`` inside a container based on the new
build image, joined to the env's private subnets + internal SG so it
can reach RDS.
"""

from __future__ import annotations

import sys
from typing import Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import AnsibleRunFailed, ECSTaskFailed, EnvNotSupported
from docex.naming import apply_policy
from docex.orchestrate._common import (
    compose_file_for,
    compose_service_key,
    ensure_compiled,
    env_file_for,
    services_with_schema,
)


_FIXED_ENVS = ("dev", "test")


RunPlaybook = Callable[..., int]


def run_migrate(
    ctx: ProjectContext,
    docker: DockerClient | None,
    *,
    env: str,
    ansible_runner: RunPlaybook | None = None,
    aws: AWSClient | None = None,
) -> int:
    """Apply migrations against ``<env>``.

    dev/test paths use docker compose exec (Phase 2). stage/prod paths
    use ansible (Phase 3, fixed) or ECS RunTask (Phase 4, elastic).

    The dispatcher passes whichever transports are relevant for the
    env + foundation; the unused ones are tolerated as None.
    """
    if env in ("stage", "prod"):
        return _migrate_stage_prod(
            ctx, env=env, ansible_runner=ansible_runner, aws=aws,
        )

    if env not in _FIXED_ENVS:
        raise EnvNotSupported(
            f"unknown env {env!r}; valid envs are: dev, test, stage, prod"
        )

    if docker is None:
        # dev/test always need docker; the dispatcher always passes it.
        raise EnvNotSupported(
            f"'docex migrate {env}' requires a docker client; internal "
            f"dispatch bug."
        )

    ensure_compiled(ctx)
    compose_file = compose_file_for(ctx, env)
    env_file = env_file_for(ctx, env)
    schema_owners = services_with_schema(ctx)
    if not schema_owners:
        print(
            f"no schema-owning services declared; "
            f"'docex migrate {env}' is a no-op."
        )
        return 0

    for svc in schema_owners:
        key = compose_service_key(ctx, env, svc)
        rc = docker.compose_exec(compose_file, key, ["./migrate.sh"], env_file=env_file)
        if rc != 0:
            print(
                f"error: migrate.sh for {svc!r} in {env} exited {rc}.",
                file=sys.stderr,
            )
            return rc
    print(f"migrate {env}: applied migrations for {len(schema_owners)} service(s).")
    return 0


def _migrate_stage_prod(
    ctx: ProjectContext,
    *,
    env: str,
    ansible_runner: RunPlaybook | None,
    aws: AWSClient | None,
) -> int:
    """Stage/prod path. Fixed → ansible --tags migrate; elastic → ECS RunTask."""
    infra = ctx.infra
    if infra is None:
        print(
            f"error: 'docex migrate {env}' requires infra/infra.yml.",
            file=sys.stderr,
        )
        return 1

    if infra.foundation == "elastic":
        if aws is None:
            print(
                "error: elastic migrate requires an AWSClient. "
                "(Internal dispatch bug.)",
                file=sys.stderr,
            )
            return 1
        return _migrate_elastic(ctx, env=env, aws=aws)

    # ---- Fixed-foundation path -------------------------------------
    if ansible_runner is None:
        # Defensive: the dispatcher always passes one in for stage/prod
        # on fixed; this branch is just a safety net for hand-callers.
        from docex.ansible import run_playbook as ansible_runner_  # type: ignore

        ansible_runner = ansible_runner_

    project_root = ctx.project_root
    private_key = project_root / "infra" / "deploy_creds" / env
    if not private_key.is_file():
        print(
            f"error: expected SSH deploy key at "
            f"{private_key.relative_to(project_root)}; see credentials.md.",
            file=sys.stderr,
        )
        return 1

    ensure_compiled(ctx)
    out_dir = project_root / "infra" / "output" / env
    playbook = out_dir / "playbook.yml"
    inventory = out_dir / "inventory.yml"
    config = out_dir / "ansible.cfg"
    for required in (playbook, inventory):
        if not required.is_file():
            print(
                f"error: expected compiled file at "
                f"{required.relative_to(project_root)}; "
                "did 'docex compile' fail?",
                file=sys.stderr,
            )
            return 1

    rc = ansible_runner(
        playbook,
        inventory,
        config=config if config.is_file() else None,
        private_key=private_key,
        tags=["migrate"],
    )
    if rc != 0:
        raise AnsibleRunFailed(
            f"ansible-playbook --tags migrate for {env!r} exited {rc}."
        )
    print(f"migrate {env}: applied migrations via ansible playbook.")
    return 0


def _migrate_elastic(
    ctx: ProjectContext, *, env: str, aws: AWSClient
) -> int:
    """Run each schema-owning service's migration task on Fargate.

    Sequence per release_mechanism.md § Migrations § Elastic-foundation
    mechanism:

      1. Look up the env's ECS cluster + the project VPC's private subnets
         + the internal SG. These were emitted with deterministic names
         by the compiler.
      2. For each ``services_with_schema(ctx)`` core service:
         a. Compose the migration task definition family name
            (``${project}_${env}_${svc}_migrate``, with hyphenation per
            the engine's naming rules).
         b. ``RunTask`` against that family.
         c. Poll until the task stops; capture the container exit code.
         d. Non-zero exit → abort the rest of the loop.

      Each migration task definition is provisioned by ``tofu apply``
      (the compiler emits ``aws_ecs_task_definition.${svc}_migrate``)
      so on a typical release the latest revision is what RunTask picks
      up. Standalone ``docex migrate`` invocations assume the latest
      revision is already current — re-apply tofu first if not.
    """
    schema_owners = services_with_schema(ctx)
    if not schema_owners:
        print(
            f"no schema-owning services declared; "
            f"'docex migrate {env}' is a no-op."
        )
        return 0

    project = ctx.project.name
    # Resource naming follows the compiler's naming policies:
    #   ECS cluster: ``ecs`` policy → ``<project>-<env>`` (hyphen, mod 030)
    #   security group: ``<project>_<env>_internal`` (literal underscores in main.tf.j2)
    tables = ctx.transfer_tables
    ecs_policy = tables.naming_policies.get("ecs")
    cluster_name = apply_policy(f"{project}_{env}", ecs_policy)
    sg_name = f"{project}_{env}_internal"

    # Look up cluster + subnets + SG once for the whole batch.
    cluster_arn = aws.get_ecs_cluster_arn(cluster_name)
    vpc_id = _lookup_project_vpc(aws, project=project)
    subnets = aws.get_default_subnets(vpc_id=vpc_id, tier="private")
    if not subnets:
        raise ECSTaskFailed(
            f"no private subnets found for project {project!r}; ensure "
            f"the project VPC + subnets are tagged correctly."
        )
    sg_id = aws.get_security_group_id(vpc_id=vpc_id, name=sg_name)

    for svc in schema_owners:
        # Migration task definition family — matches the elastic HCL
        # emitter (render_task_definition: ``mig_family = svc.global_name + "_migrate"``).
        # We re-derive the global_name here rather than threading the
        # compiled context through orchestrate/.
        family = _migration_task_family(ctx, project=project, env=env, svc=svc)

        print(f"migrate {env}: starting ECS task for {svc!r} ({family})...")
        task_arn = aws.ecs_run_task(
            cluster=cluster_arn,
            task_definition=family,
            subnets=subnets,
            security_groups=[sg_id],
        )
        exit_code = aws.ecs_wait_for_task(
            cluster=cluster_arn, task_arn=task_arn
        )
        if exit_code != 0:
            raise ECSTaskFailed(
                f"migration task for {svc!r} exited {exit_code}; "
                f"aborting before remaining services. ARN: {task_arn}"
            )
        print(f"migrate {env}: {svc!r} migration succeeded (exit 0).")

    print(
        f"migrate {env}: applied migrations for "
        f"{len(schema_owners)} service(s) via ECS."
    )
    return 0


def _lookup_project_vpc(aws: AWSClient, *, project: str) -> str:
    """Resolve the project VPC's ID.

    The compiler's emitted HCL uses ``data.aws_vpc.project`` with a
    ``tags = { project = <name> }`` filter. We mirror that lookup here
    via a small detour — Phase 4 doesn't expose a ``describe_vpcs`` on
    the AWSClient Protocol because only this one call needs it; if a
    second use-case appears, promote it. For now we hit boto3 through
    the shared client's internal cache directly.
    """
    # Lazy access to the underlying client. Tests using FakeAWSClient
    # should override this via ``_lookup_project_vpc`` on the fake (see
    # tests/conftest.py).
    if hasattr(aws, "lookup_project_vpc"):
        return aws.lookup_project_vpc(project=project)  # type: ignore[attr-defined]
    # Production path — Boto3AWSClient exposes a cached ec2 client.
    ec2 = aws._client("ec2")  # type: ignore[attr-defined]
    resp = ec2.describe_vpcs(
        Filters=[{"Name": "tag:project", "Values": [project]}]
    )
    vpcs = resp.get("Vpcs", [])
    if not vpcs:
        raise ECSTaskFailed(
            f"no VPC tagged project={project!r}; was the project-tier "
            f"VPC provisioned?"
        )
    return str(vpcs[0]["VpcId"])


def _migration_task_family(
    ctx: ProjectContext, *, project: str, env: str, svc: str
) -> str:
    """Derive the migration task definition family for a service.

    Must match the compiler's elastic HCL emitter
    (`render_task_definition`: ``mig_family = svc.global_name + "-migrate"``).
    We re-resolve the engine's naming policy so this works without
    re-compiling the project context.
    """
    tables = ctx.transfer_tables
    core = ctx.infra.core_services.get(svc) if ctx.infra else None
    if core is None:
        # Fallback: best-effort hyphen form (mod 030 data-plane naming).
        return f"{project}-{env}-{svc}-migrate"
    engines = tables.role(core.role)
    engine_entry = None
    for eng_name in sorted(engines):
        entry = engines[eng_name]
        if entry.supports("elastic"):
            engine_entry = entry
            break
    if engine_entry is None:
        return f"{project}-{env}-{svc}-migrate"
    policy = tables.naming_policies.get(engine_entry.naming)
    raw = f"{project}_{env}_{svc}"
    return f"{apply_policy(raw, policy)}-migrate"

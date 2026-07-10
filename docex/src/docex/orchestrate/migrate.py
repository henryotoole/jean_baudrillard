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
    env_compose_project,
    services_with_schema,
)
from docex.orchestrate.aggregate import aggregate

# Mod 060: single source of truth for the master-VPC identity tags. The
# migrate RunTask discovers the VPC by the SAME semantic tags the preinfra
# check and the project.tf.j2 data source use — importing rather than
# re-declaring so the three filters can never drift apart again (the drift
# that the 1.2.0 elastic smoke walk caught here).
from docex.pipeline.preinfra import _MASTER_VPC_TAGS

_MASTER_VPC_NOT_FOUND = (
    "no master VPC found in account (expected the preinfra identity tags "
    f"{_MASTER_VPC_TAGS}). Stand it up per `elastic_master_network.md`."
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
    # dev/test migrate is a bring-up site: aggregate so the migration exec
    # sees the minted TTE credentials the running container was started with.
    env_file = aggregate(ctx, env=env)
    project_name = env_compose_project(ctx, env)
    schema_owners = services_with_schema(ctx)
    if not schema_owners:
        print(
            f"no schema-owning services declared; "
            f"'docex migrate {env}' is a no-op."
        )
        return 0

    for svc in schema_owners:
        key = compose_service_key(ctx, env, svc)
        rc = docker.compose_exec(
            compose_file, key, ["./migrate.sh"], env_file=env_file,
            project_dir=ctx.project_root, project_name=project_name,
        )
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
    #   security group: ``<project>-<env>-internal`` (mod 040 hyphenated
    #     env-tier SG names — main.tf.j2 emits via the same Jinja replace
    #     filter the doctrine prescribes for data-plane identifiers).
    tables = ctx.transfer_tables
    ecs_policy = tables.naming_policies.get("ecs")
    cluster_name = apply_policy(f"{project}_{env}", ecs_policy)
    # Mod 040 + mod 046: env-tier SG names hyphenate the project segment,
    # not just the joiners. Run the project name through `_dns_label`
    # (same translation `http_host` / `docker` policies apply) so the
    # underscored project (`docex_smoke_elastic`) renders as
    # `docex-smoke-elastic-stage-internal` — matching the actual SG.
    project_dns = project.replace("_", "-").lower()
    sg_name = f"{project_dns}-{env}-internal"

    # Look up cluster + subnets + SG once for the whole batch.
    cluster_arn = aws.get_ecs_cluster_arn(cluster_name)
    vpc_id = _lookup_master_vpc(aws)
    subnets = aws.get_default_subnets(vpc_id=vpc_id, tier="private")
    if not subnets:
        raise ECSTaskFailed(
            f"no private subnets tagged tier=private found in the master "
            f"VPC; ensure the preinfra master VPC + subnets are tagged "
            f"per `elastic_master_network.md`."
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


def _lookup_master_vpc(aws: AWSClient) -> str:
    """Resolve the shared master VPC's ID.

    Every elastic project lives in a shared master VPC. The migration
    RunTask needs that VPC ID to launch the task into the project's
    private subnets — same VPC the compiled HCL data-sources via
    ``data.aws_vpc.master``.

    Mod 060: the VPC is discovered by the **semantic identity tags** from
    ``cicl.md § Naming and Tagging`` (the preinfra block) —
    ``managed_by=doctrine-operator`` + ``infra_tier=prerequisite`` +
    ``shape_name=master_network`` — NOT the redundant console-only
    ``Name``. This MUST match ``pipeline/preinfra.py``'s
    ``_MASTER_VPC_TAGS`` and the ``data "aws_vpc" "master"`` filter in
    ``templates/project.tf.j2``; all three are the same contract.
    """
    if hasattr(aws, "lookup_master_vpc"):
        return aws.lookup_master_vpc()  # type: ignore[attr-defined]
    # Production path — Boto3AWSClient exposes a cached ec2 client.
    # If a future doctrine change exposes find_vpc_by_tags publicly on
    # the AWSClient protocol, this method can switch to that uniformly.
    if hasattr(aws, "find_vpc_by_tags"):
        vpc_id = aws.find_vpc_by_tags(  # type: ignore[attr-defined]
            _MASTER_VPC_TAGS
        )
        if vpc_id is None:
            raise ECSTaskFailed(_MASTER_VPC_NOT_FOUND)
        return vpc_id
    ec2 = aws._client("ec2")  # type: ignore[attr-defined]
    resp = ec2.describe_vpcs(
        Filters=[
            {"Name": f"tag:{k}", "Values": [v]}
            for k, v in _MASTER_VPC_TAGS.items()
        ]
    )
    vpcs = resp.get("Vpcs", [])
    if not vpcs:
        raise ECSTaskFailed(_MASTER_VPC_NOT_FOUND)
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

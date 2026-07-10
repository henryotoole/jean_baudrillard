"""``docex release <env>`` — deploy a containerized build to stage/prod.

Phase 3 implemented the fixed-foundation branch (ansible-playbook
against an inventory). Phase 4 fills in the elastic branch (SSM push
→ ECS RunTask migration → ``tofu init`` + ``tofu apply``).

Per [release_mechanism.md § Elastic Foundation: OpenTofu] and § Migrations
§ Elastic-foundation mechanism: the order is non-negotiable. Secrets
go to SSM first so the migration task (which reads them) sees a
consistent picture; the migration runs before tofu apply so the new
schema is in place when the rolling deploy of the application code
begins.
"""

from __future__ import annotations

import sys
from typing import Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.errors import (
    AnsibleRunFailed,
    EnvNotSupported,
    TofuApplyFailed,
)
from docex.naming import apply_policy
from docex.orchestrate._common import ensure_compiled, services_with_schema
from docex.ssh.client import SSHClient


# Type alias for the injected ansible runner (Phase 3, fixed branch).
RunPlaybook = Callable[..., int]
# Type alias for the injected tofu runners (Phase 4, elastic branch).
TofuInit = Callable[..., int]
TofuApply = Callable[..., int]
TofuPlan = Callable[..., int]


def run_release(
    ctx: ProjectContext,
    *,
    env: str,
    ansible_runner: RunPlaybook | None = None,
    aws: AWSClient | None = None,
    tofu_init: TofuInit | None = None,
    tofu_apply: TofuApply | None = None,
    ssh: SSHClient | None = None,
) -> int:
    """Deploy the containerized build to ``env``. Returns exit code.

    ``ansible_runner`` (+ ``ssh`` to read the host TTE store) is required
    for the fixed-foundation branch; ``aws`` and the tofu runners are
    required for the elastic branch. The dispatcher always passes all of
    them (some are unused depending on foundation).
    """
    if env in ("dev", "test"):
        raise EnvNotSupported(
            f"'docex release {env}' is not a thing — use 'docex up {env}' "
            "for local stacks."
        )
    if env not in ("stage", "prod"):
        raise EnvNotSupported(
            f"unknown env {env!r}; valid envs are: dev, test, stage, prod"
        )

    infra = ctx.infra
    if infra is None:
        print(
            "error: release requires infra/infra.yml (none found).",
            file=sys.stderr,
        )
        return 1

    if infra.foundation == "elastic":
        if aws is None or tofu_init is None or tofu_apply is None:
            print(
                "error: elastic release requires an AWSClient and the "
                "tofu_init / tofu_apply runners. (Internal dispatch bug.)",
                file=sys.stderr,
            )
            return 1
        return _release_elastic(
            ctx, env=env, aws=aws,
            tofu_init=tofu_init, tofu_apply=tofu_apply,
        )

    # ---- Fixed-foundation path ---------------------------------------
    if ansible_runner is None or ssh is None:
        print(
            "error: fixed release requires an ansible runner and an SSH "
            "client. (Internal dispatch bug.)",
            file=sys.stderr,
        )
        return 1
    return _release_fixed(ctx, env=env, ansible_runner=ansible_runner, ssh=ssh)


def _release_fixed(
    ctx: ProjectContext,
    *,
    env: str,
    ansible_runner: RunPlaybook,
    ssh: SSHClient,
    skip_migrations: bool = False,
    dry_run: bool = False,
) -> int:
    """Apply a fixed-foundation release. ``release`` calls this with the
    flag defaults (False/False); ``rollback`` passes True for both flags
    when reverting a prod env in check-mode dry-run, or just
    ``skip_migrations=True`` for a real reversion.
    """
    project_root = ctx.project_root

    private_key = project_root / "infra" / "deploy_creds" / env
    if not private_key.is_file():
        print(
            f"error: expected SSH deploy key at {private_key.relative_to(project_root)}; "
            "see credentials.md § Deploy Credentials.",
            file=sys.stderr,
        )
        return 1

    env_file = project_root / "infra" / "secrets" / f"{env}.env"
    if not env_file.is_file():
        print(
            f"error: expected env secrets at {env_file.relative_to(project_root)}; "
            "see credentials.md § Env Secrets.",
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
                f"{required.relative_to(project_root)}; did 'docex compile' fail?",
                file=sys.stderr,
            )
            return 1

    extra_vars: dict[str, str] = {}
    if not dry_run:
        # Build the runtime aggregate + host-TTE superset. WHY skip under
        # dry_run: ``ansible --check`` mutates nothing, so minting into the
        # host store (impure) and pushing a fresh aggregate would be a real
        # side effect on a supposedly side-effect-free path (mirrors the
        # elastic dry-run's no-SSM-push rule).
        from docex.orchestrate.aggregate import aggregate_fixed_prod

        agg_file, tte_file = aggregate_fixed_prod(
            ctx, env=env, ssh=ssh, key=private_key
        )
        extra_vars = {
            "agg_env_file": str(agg_file),
            "tte_store_file": str(tte_file),
        }

    rc = ansible_runner(
        playbook,
        inventory,
        config=config if config.is_file() else None,
        private_key=private_key,
        skip_tags=["migrate"] if skip_migrations else None,
        check_mode=dry_run,
        extra_vars=extra_vars or None,
    )
    if rc != 0:
        raise AnsibleRunFailed(
            f"ansible-playbook for env {env!r} exited {rc}. "
            "See playbook output above for the failing task."
        )
    if dry_run:
        print(f"release: {env} dry-run completed (ansible --check).")
    else:
        suffix = " (migrations skipped)" if skip_migrations else ""
        print(f"release: {env} deployed successfully{suffix}.")
    return 0


def _release_elastic(
    ctx: ProjectContext,
    *,
    env: str,
    aws: AWSClient,
    tofu_init: TofuInit,
    tofu_apply: TofuApply,
    tofu_plan: TofuPlan | None = None,
    skip_migrations: bool = False,
    dry_run: bool = False,
) -> int:
    """Elastic release flow.

    Steady-state order, per release_mechanism.md:
      1. SSM push
      2. ECS migrate (against the existing cluster + RDS)
      3. tofu apply (rolls out the new image)

    First-release adjustment: when the env's ECS cluster doesn't exist
    yet, step 2 is structurally impossible — the migration task can't
    run against a cluster that hasn't been created. In that case the
    flow becomes:
      1. SSM push
      3. tofu apply (creates cluster, RDS, task definitions, *and* the
          ECS service running the new image)
      2. ECS migrate (against the now-live cluster/RDS)

    Subsequent releases against the same env find the cluster present
    and fall back to the doctrine order. Both orders end with the
    migration having run and the new image deployed.
    """
    project_root = ctx.project_root
    project_name = ctx.project.name

    env_file = project_root / "infra" / "secrets" / f"{env}.env"
    if not env_file.is_file():
        print(
            f"error: expected env secrets at {env_file.relative_to(project_root)}; "
            "see release_mechanism.md § Secrets.",
            file=sys.stderr,
        )
        return 1

    ensure_compiled(ctx)

    out_dir = project_root / "infra" / "output" / env
    main_tf = out_dir / "main.tf"
    if not main_tf.is_file():
        print(
            f"error: expected compiled file at "
            f"{main_tf.relative_to(project_root)}; did 'docex compile' fail?",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        # WHY: dry-run is side-effect-free. Skip SSM push (operator can't
        # un-push) and apply; just init the workdir and emit a plan so
        # the operator can read what would change.
        if tofu_plan is None:
            print(
                "error: elastic dry-run requires a tofu_plan runner. "
                "(Internal dispatch bug.)",
                file=sys.stderr,
            )
            return 1
        rc_init = tofu_init(out_dir)
        if rc_init != 0:
            raise TofuApplyFailed(
                f"'tofu init' for env {env!r} exited {rc_init}"
            )
        rc_plan = tofu_plan(out_dir)
        if rc_plan != 0:
            raise TofuApplyFailed(
                f"'tofu plan' for env {env!r} exited {rc_plan}"
            )
        print(
            f"release: dry-run completed for {env!r}; review the 'tofu plan' "
            f"output above to see what would change."
        )
        return 0

    # 1. Aggregate the three configurable-value categories into SSM (the
    # elastic aggregate is the /<project>/<env>/ prefix itself). TTE is
    # minted-if-absent (SecureString, put-if-absent so a lost local copy
    # never clobbers the live RDS credential); secrets/config are
    # overwritten. See config_and_secrets.md § 4.2.
    from docex.orchestrate.aggregate import aggregate_elastic

    pushed = aggregate_elastic(ctx, env=env, aws=aws)
    print(
        f"release: pushed {pushed} configurable value(s) to SSM under "
        f"/{project_name}/{env}/ (TTE minted-if-absent, secrets/config overwritten)"
    )

    # Mod 070: ec2_traefik projects no longer push routing config at release
    # time. The project traefik discovers routes from each task's traefik.*
    # dockerLabels via its ECS provider (elastic analog of the fixed docker
    # provider) — routing intent lives on the workloads. See ec2_traefik.md
    # § Routing Discovery.

    if skip_migrations:
        # Rollback path: no first-release detection (rollback only
        # targets a populated env), no migration task-def bump, no
        # RunTask. A single unrestricted apply converges the env to the
        # recompiled (older) HCL.
        rc_init = tofu_init(out_dir)
        if rc_init != 0:
            raise TofuApplyFailed(
                f"'tofu init' for env {env!r} exited {rc_init}"
            )
        rc_apply = tofu_apply(out_dir, auto_approve=True)
        if rc_apply != 0:
            raise TofuApplyFailed(
                f"'tofu apply' for env {env!r} exited {rc_apply}"
            )
        print(
            f"release: {env} deployed successfully via OpenTofu "
            f"(migrations skipped)."
        )
        return 0

    # First-time-release detection. Mod 071: the ECS cluster is now
    # project-tier and always exists (both stage + prod), so its mere
    # existence no longer distinguishes a first release from a steady-state
    # one. Instead we key off env-service existence: a first release is one
    # where the env's cluster holds no ECS services yet — the env-tier
    # ``tofu apply`` is what creates them. On such a release the migrate
    # step must wait until after apply, or RunTask would find no infra.
    ecs_policy = ctx.transfer_tables.naming_policies.get("ecs")
    cluster_name = apply_policy(f"{project_name}_{env}", ecs_policy)
    first_release = not aws.ecs_cluster_has_services(cluster_name)
    if first_release:
        print(
            f"release: no ECS services in cluster {cluster_name!r} — "
            f"first-time release detected; applying infra before migrate."
        )

    # Imported here to avoid an orchestrate -> pipeline cycle at module
    # load time. The migrate function expects a docker client even on
    # elastic paths to satisfy its uniform signature; pass None here —
    # the elastic branch does not touch it.
    from docex.orchestrate.migrate import run_migrate

    def _do_migrate() -> int:
        return run_migrate(ctx, docker=None, env=env, aws=aws)  # type: ignore[arg-type]

    def _do_apply() -> None:
        rc_init = tofu_init(out_dir)
        if rc_init != 0:
            raise TofuApplyFailed(
                f"'tofu init' for env {env!r} exited {rc_init}"
            )
        rc_apply = tofu_apply(out_dir, auto_approve=True)
        if rc_apply != 0:
            raise TofuApplyFailed(
                f"'tofu apply' for env {env!r} exited {rc_apply}"
            )

    if first_release:
        # apply → migrate
        _do_apply()
        rc_mig = _do_migrate()
        if rc_mig != 0:
            print(
                f"error: first-release migration phase exited {rc_mig} after "
                f"tofu apply succeeded. The env's infra is up but its schema "
                f"is in an unknown state — fix the migration and re-run "
                f"`docex release {env}`.",
                file=sys.stderr,
            )
            return rc_mig
    else:
        # Steady-state: bump migration task-def revisions, migrate, then full apply.
        # WHY: RunTask in _do_migrate() resolves the LATEST registered
        # revision, which without a pre-step is the *previous* release's
        # task-def — stale env/secret refs and the prior image tag. The
        # targeted apply pushes each migration task-def to match the
        # current release's emitted HCL so migrate sees fresh content.
        # Main service task-defs are intentionally NOT in the target
        # set — the rolling deploy of the new application code happens
        # only after migrations succeed.
        # See release_mechanism.md § Elastic-foundation mechanism step 2.
        schema_owners = services_with_schema(ctx)
        if schema_owners:
            rc_init = tofu_init(out_dir)
            if rc_init != 0:
                raise TofuApplyFailed(
                    f"'tofu init' for env {env!r} exited {rc_init}"
                )
            targets = [
                f"aws_ecs_task_definition.{svc}_migrate"
                for svc in schema_owners
            ]
            rc_pre = tofu_apply(out_dir, auto_approve=True, targets=targets)
            if rc_pre != 0:
                raise TofuApplyFailed(
                    f"pre-migrate targeted 'tofu apply' for env {env!r} "
                    f"exited {rc_pre}; aborting release before migrate."
                )

        rc_mig = _do_migrate()
        if rc_mig != 0:
            print(
                f"error: migration phase exited {rc_mig}; aborting release "
                f"before tofu apply.",
                file=sys.stderr,
            )
            return rc_mig
        _do_apply()

    print(f"release: {env} deployed successfully via OpenTofu.")
    return 0

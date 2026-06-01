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
from pathlib import Path
from typing import Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.errors import (
    AnsibleRunFailed,
    EnvNotSupported,
    SSMPushFailed,
    TofuApplyFailed,
)
from docex.naming import apply_policy
from docex.orchestrate._common import ensure_compiled


# Type alias for the injected ansible runner (Phase 3, fixed branch).
RunPlaybook = Callable[..., int]
# Type alias for the injected tofu runners (Phase 4, elastic branch).
TofuInit = Callable[..., int]
TofuApply = Callable[..., int]


def run_release(
    ctx: ProjectContext,
    *,
    env: str,
    ansible_runner: RunPlaybook | None = None,
    aws: AWSClient | None = None,
    tofu_init: TofuInit | None = None,
    tofu_apply: TofuApply | None = None,
) -> int:
    """Deploy the containerized build to ``env``. Returns exit code.

    ``ansible_runner`` is required for the fixed-foundation branch;
    ``aws`` and the tofu runners are required for the elastic branch.
    The dispatcher always passes all four (some are unused depending
    on foundation).
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
    if ansible_runner is None:
        print(
            "error: fixed release requires an ansible runner. "
            "(Internal dispatch bug.)",
            file=sys.stderr,
        )
        return 1
    return _release_fixed(ctx, env=env, ansible_runner=ansible_runner)


def _release_fixed(
    ctx: ProjectContext, *, env: str, ansible_runner: RunPlaybook
) -> int:
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

    rc = ansible_runner(
        playbook,
        inventory,
        config=config if config.is_file() else None,
        private_key=private_key,
    )
    if rc != 0:
        raise AnsibleRunFailed(
            f"ansible-playbook for env {env!r} exited {rc}. "
            "See playbook output above for the failing task."
        )
    print(f"release: {env} deployed successfully.")
    return 0


def _release_elastic(
    ctx: ProjectContext,
    *,
    env: str,
    aws: AWSClient,
    tofu_init: TofuInit,
    tofu_apply: TofuApply,
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

    # 1. Push secrets to SSM.
    pushed = _push_secrets(aws, env_file, project=project_name, env=env)
    print(f"release: pushed {pushed} secret(s) to SSM under /{project_name}/{env}/")

    # First-time-release detection: the env's ECS cluster (named per
    # the ``ecs`` naming policy on the project/env pair) is created by
    # tofu apply. If it isn't there yet, the migrate step would error
    # with "no ACTIVE ECS cluster" before tofu had a chance to create it.
    ecs_policy = ctx.transfer_tables.naming_policies.get("ecs")
    cluster_name = apply_policy(f"{project_name}_{env}", ecs_policy)
    first_release = not aws.ecs_cluster_exists(cluster_name)
    if first_release:
        print(
            f"release: ECS cluster {cluster_name!r} not yet provisioned — "
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
        # migrate → apply (doctrine order)
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


def _push_secrets(
    aws: AWSClient,
    env_file: Path,
    *,
    project: str,
    env: str,
) -> int:
    """Read ``env_file`` and push each ``KEY=value`` pair to SSM.

    Returns the number of secrets pushed. Raises ``SSMPushFailed`` on
    the first error so the release aborts before any AWS-side mutation
    of running services. Per release_mechanism.md § Secrets, SSM is
    clobbered every release (``overwrite=True``).
    """
    count = 0
    try:
        text = env_file.read_text()
    except OSError as e:
        raise SSMPushFailed(f"cannot read {env_file}: {e}") from e

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            # Tolerate but warn. The .env format is forgiving by spec
            # (release_mechanism.md doesn't mandate strict parsing).
            print(
                f"warning: skipping unparseable line in {env_file.name}: {line!r}",
                file=sys.stderr,
            )
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip optional surrounding quotes on the value.
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        path = f"/{project}/{env}/{key}"
        try:
            aws.ssm_put_parameter(path, value, overwrite=True)
        except Exception as e:
            raise SSMPushFailed(
                f"failed pushing {key!r} to {path!r}: {e}"
            ) from e
        count += 1
    return count

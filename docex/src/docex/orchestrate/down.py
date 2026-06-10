"""``docex envinfra down <env>`` — tear down a previously-running stack.

Two teardown shapes by foundation/env:

- **dev/test, and fixed stage/prod:** the compose stack is stopped and
  removed; named volumes are preserved per doctrine (persistent data
  survives ``down``). The ``test`` env's teardown via ``docex test`` is
  the one place we pass ``preserve_volumes=False`` — handled there, not
  here.
- **elastic stage/prod:** ``tofu destroy`` against the env's
  ``infra/output/<env>/main.tf`` (its ECS/RDS/SG/records). Mod 052
  (Gap F). A **pre-flight deletion-protection gate** scans for
  deletion-protected RDS instances in the env and **refuses before
  destroying anything** if any are found — docex never disables a
  protection itself; the operator clears it deliberately and re-runs.

The up/down asymmetry (``up`` is dev/test-only, ``down`` covers all
envs) is intentional: bringing an env up needs a versioned build (so
stage/prod up is ``release``'s job), but teardown is build-agnostic.
"""

from __future__ import annotations

from typing import Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import EnvNotSupported, TofuApplyFailed
from docex.naming import apply_policy
from docex.orchestrate._common import (
    compose_file_for,
    ensure_compiled,
    env_file_for,
)


TofuRunner = Callable[..., int]

_ELASTIC_ENVS = ("stage", "prod")


def run_down(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    env: str,
    aws: AWSClient | None = None,
    tofu_init: TofuRunner | None = None,
    tofu_destroy: TofuRunner | None = None,
) -> int:
    """Tear down the ``<env>`` stack.

    dev/test (and fixed stage/prod) go through ``compose_down`` with
    volumes preserved. Elastic stage/prod go through the RDS-protection
    gate + ``tofu destroy`` (Gap F); the dispatcher injects ``aws`` and
    the tofu runners for that path.
    """
    if env not in ("dev", "test", "stage", "prod"):
        raise EnvNotSupported(
            f"unknown env {env!r}; valid envs are: dev, test, stage, prod"
        )

    is_elastic = (
        ctx.infra is not None
        and ctx.infra.foundation == "elastic"
        and env in _ELASTIC_ENVS
    )

    # Re-compile so the file (compose or HCL) is fresh even if infra.yml
    # drifted.
    ensure_compiled(ctx)

    if is_elastic:
        return _down_elastic(
            ctx, env=env, aws=aws,
            tofu_init=tofu_init, tofu_destroy=tofu_destroy,
        )

    # Fixed-style teardown (dev/test, or fixed stage/prod).
    compose_file = compose_file_for(ctx, env)
    env_file = env_file_for(ctx, env)
    return docker.compose_down(compose_file, preserve_volumes=True, env_file=env_file)


def _down_elastic(
    ctx: ProjectContext,
    *,
    env: str,
    aws: AWSClient | None,
    tofu_init: TofuRunner | None,
    tofu_destroy: TofuRunner | None,
) -> int:
    """Elastic env-tier teardown with the deletion-protection gate."""
    if aws is None or tofu_init is None or tofu_destroy is None:
        print(
            "error: elastic envinfra down requires an AWSClient and the "
            "tofu_init / tofu_destroy runners. (Internal dispatch bug.)"
        )
        return 1

    project = ctx.project.name

    # ---- Pre-flight gate: refuse BEFORE destroying anything. ----------
    # Env RDS instances are named `<project_dns_label>-<env>-<svc>` (the
    # `rds` naming policy: hyphenated, lowercased). The shared prefix is
    # `apply_policy("<project>_<env>", rds) + "-"`.
    rds_policy = ctx.transfer_tables.naming_policies.get("rds")
    rds_prefix = apply_policy(f"{project}_{env}", rds_policy) + "-"
    protected = aws.rds_protected_instances(rds_prefix)
    if protected:
        print(
            f"error: refusing to tear down env {env!r} — the following RDS "
            f"instance(s) are deletion-protected:"
        )
        for ident in protected:
            print(f"  - {ident} (DeletionProtection=true)")
        print(
            "\ndocex never disables a protection itself. Disable "
            "`deletion_protection` on each instance above (out-of-band, "
            "deliberately) and re-run `docex envinfra down "
            f"{env}`. Nothing was destroyed."
        )
        return 1

    out_dir = ctx.project_root / "infra" / "output" / env
    main_tf = out_dir / "main.tf"
    if not main_tf.is_file():
        print(
            f"warning: {main_tf} not found — nothing to tear down."
        )
        return 0

    rc_init = tofu_init(out_dir)
    if rc_init != 0:
        raise TofuApplyFailed(
            f"'tofu init' for env {env!r} exited {rc_init}"
        )
    rc = tofu_destroy(out_dir, auto_approve=True)
    if rc != 0:
        raise TofuApplyFailed(
            f"'tofu destroy' for env {env!r} exited {rc}"
        )
    print(f"envinfra down: {env} env-tier destroyed via OpenTofu.")
    return 0

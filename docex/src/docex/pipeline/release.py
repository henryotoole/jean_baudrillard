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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.errors import (
    AnsibleRunFailed,
    EnvNotSupported,
    RequiredSecretsUnset,
    TofuApplyFailed,
)
from docex.naming import apply_policy
from docex.orchestrate._common import ensure_compiled, codebases_with_schema
from docex.ssh.client import SSHClient


# Type alias for the injected ansible runner (Phase 3, fixed branch).
RunPlaybook = Callable[..., int]
# Type alias for the injected tofu runners (Phase 4, elastic branch).
TofuInit = Callable[..., int]
TofuApply = Callable[..., int]
TofuPlan = Callable[..., int]


def _require_secrets_present(ctx: ProjectContext, env: str) -> None:
    """Abort a stage/prod release if a required secret is unset.

    Required secret = any key in the secret manifest (core `secrets:` +
    backing `kind: secret` + doctrine-injected). "Unset" = absent from
    infra/secrets/<env>.env or present with an empty value. TTE (docex-minted,
    put-if-absent) and config (non-secret) do NOT gate a release.
    See config_and_secrets.md § Required-Secret Guard.
    """
    from docex.cicl.categories import secret_manifest
    from docex.envfile import read_env_file

    manifest = secret_manifest(ctx.infra, ctx.transfer_tables)
    values = read_env_file(ctx.project_root / "infra" / "secrets" / f"{env}.env")
    unset = [e.key for e in manifest if values.get(e.key, "") == ""]
    if unset:
        raise RequiredSecretsUnset(env, unset)


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

    _require_secrets_present(ctx, env)

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


#: How long to wait for a reconciled consumer's rolling deploy to settle.
#: Bounded because a slow rollout must not hang a release forever; generous
#: because a Fargate task pull + healthcheck start period is minutes, not
#: seconds.
_RECONCILE_STABLE_TIMEOUT_S = 600

#: Grace added to a name's registration time before comparing it against the
#: consumer's PRIMARY deployment age. Ties are resolved toward redeploying by
#: the ``<=`` in the comparison itself; this widens that further, on purpose.
#:
#: WHY it is non-zero, and why sixty: this is NOT a clock-skew allowance. The
#: genuine uncertainty is small — advance 005's recon bracketed the freeze
#: instant to (deployment createdAt - 11.6s, +2.4s], and Cloud Map's
#: ``CreateDate`` precedes the name's appearance in the control plane's served
#: cluster list by under a second. Five seconds would cover both.
#:
#: Sixty seconds instead COLLAPSES THE CONCURRENT-CREATION WINDOW INTO A
#: REDEPLOY. Within roughly a minute of a consumer's deployment we stop trying
#: to adjudicate whether a name was visible to it and simply redeploy, because
#: (a) that window is exactly where the boundary is unmeasurable — ECS does not
#: expose its internal ordering, and two timestamps seconds apart do not report
#: who won; and (b) the two errors are not symmetric. A false negative there is
#: permanent and silent: an env that exits 0 with both sides reporting healthy
#: and every call across the edge failing. A false positive is one rolling
#: deploy.
#:
#: The cost lands only where the race is real — one rolling deploy per consumer
#: on a first release or a shape change. On an ordinary code-only release the
#: gap between a deployment and a long-established name is days or weeks, the
#: comparison is not close, and the step is still a no-op.
_RECONCILE_SKEW_MARGIN_S = 60


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes read as UTC.

    boto3 returns aware datetimes, so this never fires in production. It exists
    so that a naive value — from a test double, or a future SDK change — cannot
    raise ``TypeError`` in the middle of a release.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _reconcile_candidates(
    compiled: Any,
    *,
    endpoint_created: dict[str, datetime],
) -> list[tuple[str, list[tuple[str, datetime]]]]:
    """Consumers worth reading a deployment age for, with their registered targets.

    Pure: no AWS. Returns ``(consumer_global_name, [(target_global_name,
    created)])`` for every core service that declares at least one core ``uses``
    target which is actually registered in the namespace. A consumer with no
    such target can never fire, so it is dropped here and costs no API call.
    """
    out: list[tuple[str, list[tuple[str, datetime]]]] = []
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        if not svc.is_core or not svc.uses_core:
            continue
        # WHY: `update_service` against an ECS service that does not exist is
        # an error, not a no-op, so a core service that emits no `ecs_service`
        # must be skipped rather than redeployed.
        #
        # DO NOT DELETE THIS AS DEAD. After Mod 116 no *bundled* core role can
        # reach this branch — `web`, `worker` and `clock` all emit an
        # `ecs_service`. It is reachable only through a PROJECT-LOCAL transfer
        # table declaring a core role whose elastic `emits` omits
        # `ecs_service`. That makes the branch untestable from the bundled
        # tables and permanently load-bearing: without it the failure appears
        # as a release aborting mid-flight in a downstream project with a
        # custom role table, which is the hardest place to diagnose it.
        if "ecs_service" not in svc.emits.get("elastic", []):
            continue

        targets: list[tuple[str, datetime]] = []
        for key in sorted(svc.uses_core):
            target = compiled.services.get(key)
            # An unresolvable target cannot survive validation, but the
            # reconcile must not be the thing that raises if one ever does.
            if target is None:
                continue
            # Only a target that emits an `ecs_service` gets a Service Connect
            # registration, so only such a target can appear in the namespace.
            if "ecs_service" not in target.emits.get("elastic", []):
                continue
            created = endpoint_created.get(target.global_name)
            if created is None:
                continue
            targets.append((target.global_name, _as_utc(created)))
        if targets:
            out.append((svc.global_name, targets))
    return out


def _consumer_reconcile_set(
    candidates: list[tuple[str, list[tuple[str, datetime]]]],
    *,
    deployment_created: dict[str, datetime],
) -> list[tuple[str, str]]:
    """Consumers that must be redeployed, as ``(consumer, triggering target)``.

    A consumer qualifies when its PRIMARY deployment was created at or before
    the Cloud Map ``CreateDate`` of a name it ``uses`` (plus
    ``_RECONCILE_SKEW_MARGIN_S``). A Service Connect Envoy is served a cluster
    list fixed for its deployment's task-set ARN, so no task in such a
    deployment can ever resolve that target — replacing tasks inside the
    deployment does not help, and the application retrying forever does not
    either.

    A consumer absent from ``deployment_created`` fires. An unreadable
    deployment age cannot be shown to postdate anything, and the safe direction
    is one rolling deploy rather than a silently broken env.

    Both operands are durable AWS state read after the apply, which is what
    makes this self-healing: it describes the world rather than this release.
    An interrupted release, a hand-run ``tofu apply``, or a service created out
    of band all leave a state the next release reads correctly.

    It is also SELF-CLEARING BY CONSTRUCTION: `forceNewDeployment` mints a new
    PRIMARY deployment with a fresh `createdAt`, so a re-run of the same release
    reads a consumer that now postdates its targets and skips it. Idempotency
    here is structural, not asserted.

    Mod 123 replaced mod 114's task-`startedAt` operand, which measured the
    wrong event: `CreateDate` is stamped at ECS *service* creation, so a task
    of that service always starts after it, and the comparison could not fire
    whenever consumer and target were created by the same apply.
    """
    out: list[tuple[str, str]] = []
    margin = timedelta(seconds=_RECONCILE_SKEW_MARGIN_S)
    for consumer, targets in candidates:
        created_at = deployment_created.get(consumer)
        if created_at is None:
            out.append((consumer, targets[0][0]))
            continue
        created_at = _as_utc(created_at)
        for global_name, created in targets:
            if created_at <= created + margin:
                out.append((consumer, global_name))
                break
    return out


def _reconcile_service_connect_consumers(
    ctx: ProjectContext,
    *,
    env: str,
    aws: AWSClient,
    cluster_name: str,
) -> int:
    """Redeploy consumers whose deployment predates a name they must resolve.

    Closes the start-order race described in
    ``cicl.md § Uses Relationships``: ECS Service Connect fixes a service's
    resolvable endpoint set at *deployment* creation, so a consumer deployed
    alongside its target may permanently fail to resolve it. Redeploying the
    consumer after everything is registered is the only fix — ordering cannot
    work, because a ``uses`` cycle (``web ↔ worker``, the most common
    topology there is) has no valid creation order.

    Mod 123: the consumer operand is the age of its PRIMARY ECS **deployment**,
    not of its tasks. Service Connect freezes a deployment's resolvable name set
    at deployment creation — every Envoy in it is served a cluster list keyed to
    the deployment's task-set ARN — so a task replaced inside a stale deployment
    comes up just as unable to resolve. Mod 114 compared task ``startedAt``
    against the same registration and could not fire when consumer and target
    were created by one apply, which is every first release; the 1.7.0 elastic
    walk found it inert on `prod`.

    Both operands are still post-apply durable state, so the step remains
    self-contained and self-healing, and on a converged env every consumer's
    deployment postdates every name it ``uses``, nothing fires, and no service
    is touched.
    """
    from docex.cicl.compile import compile_env

    if ctx.infra is None:  # pragma: no cover — release already required it
        return 0

    endpoint_created = aws.service_connect_endpoints(cluster_name)
    if not endpoint_created:
        # Nothing is registered, so there is no registration for any
        # deployment to predate.
        #
        # WHY this prints: every no-fire path in this step says which one it
        # was. A silent skip is indistinguishable from a step that never ran,
        # and an operator reading a release log — or a smoke walk asked to
        # confirm a `skip` verdict — cannot tell "converged" from "read
        # nothing" without being told. On a first release this particular line
        # is a red flag, not reassurance: the namespace should not be empty
        # after the apply that created it.
        print(
            "release: Service Connect reconcile — no endpoints registered in "
            f"the {env} namespace; nothing to compare against."
        )
        return 0

    compiled = compile_env(
        ctx.infra,
        ctx.transfer_tables,
        env=env,
        project_name=ctx.project.name,
        project_version=ctx.project.version,
    )

    candidates = _reconcile_candidates(
        compiled, endpoint_created=endpoint_created,
    )
    if not candidates:
        print(
            "release: Service Connect reconcile — no core service declares a "
            "core `uses` target; nothing to reconcile."
        )
        return 0

    # One batched read over exactly the consumers that could fire. A converged
    # env therefore pays one ListServices plus one DescribeServices.
    deployment_created = aws.ecs_primary_deployment_times(
        cluster_name, [c for c, _ in candidates],
    )

    pairs = _consumer_reconcile_set(
        candidates, deployment_created=deployment_created,
    )
    if not pairs:
        print(
            f"release: Service Connect reconcile — {len(candidates)} consumer(s) "
            "checked, all deployments postdate the endpoints they `uses`; "
            "nothing to redeploy."
        )
        return 0

    for consumer, target in pairs:
        print(
            f"release: reconciling Service Connect consumer {consumer!r} — "
            f"its current deployment predates the registration of its `uses` "
            f"target {target!r}, and no task in that deployment can resolve an "
            f"endpoint added after the deployment was created."
        )
        try:
            aws.ecs_force_new_deployment(cluster_name, consumer)
        except Exception as exc:
            # Hard failure: the reconcile is mandated because a consumer that
            # cannot resolve a name it `uses` is broken, and an env whose
            # consumers cannot reach their targets is not released.
            print(
                f"error: could not force a new deployment of {consumer!r}: "
                f"{exc}. Its `uses` target {target!r} was registered after "
                f"{consumer!r}'s current deployment was created, "
                f"so {consumer!r} cannot resolve it until redeployed — and "
                f"NOTHING EXTERNAL WILL SHOW IT: both services report healthy, "
                f"the release looks clean, and the work silently does not "
                f"arrive. Re-run "
                f"`docex release {env}`, or redeploy it by hand.",
                file=sys.stderr,
            )
            return 1

    services = [c for c, _ in pairs]
    stable = aws.ecs_wait_services_stable(
        cluster_name, services, timeout_s=_RECONCILE_STABLE_TIMEOUT_S,
    )
    if not stable:
        # Warning, not failure: update_service was accepted and ECS will
        # converge on its own. Failing here would fail an otherwise-good
        # release over rollout latency.
        print(
            f"warning: reconciled {len(services)} consumer(s) but they had not "
            f"reached steady state within {_RECONCILE_STABLE_TIMEOUT_S}s. The "
            f"deployments were accepted and should converge; until they do, "
            f"those consumers may fail to resolve their `uses` targets with no "
            f"external signal at all — both sides report healthy and the work "
            f"silently does not arrive."
        )
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

    # Mod 109: the env's Service Connect namespace shares the ECS cluster's
    # name, so one expression serves both. Computed here — ahead of the
    # `skip_migrations` return, because both the first-release detector and the
    # consumer reconcile need it — so there is exactly one naming expression
    # and no chance of the two drifting apart.
    ecs_policy = ctx.transfer_tables.naming_policies.get("ecs")
    cluster_name = apply_policy(f"{project_name}_{env}", ecs_policy)

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
        # Mod 114: the check describes the env rather than the release that
        # produced it, so the rollback path simply runs it — no reasoning about
        # whether a rollback moves the shape is needed. A rollback that
        # deregisters a name and leaves consumer tasks predating a surviving
        # one is repaired here rather than discovered by `stagetest`.
        rc_rec = _reconcile_service_connect_consumers(
            ctx, env=env, aws=aws, cluster_name=cluster_name,
        )
        if rc_rec != 0:
            return rc_rec
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
    # (``cluster_name`` is computed above, before the ``skip_migrations``
    # return, because the rollback path's consumer reconcile needs it too.)
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
        schema_owners = codebases_with_schema(ctx)
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

    # Mod 109: after the FINAL apply on both branches — a new core service can
    # be added to a long-lived env just as easily as to a fresh one, which is
    # exactly the `upgrade_1.6.0` path for downstream projects.
    rc_rec = _reconcile_service_connect_consumers(
        ctx, env=env, aws=aws, cluster_name=cluster_name,
    )
    if rc_rec != 0:
        return rc_rec

    print(f"release: {env} deployed successfully via OpenTofu.")
    return 0

"""``AWSClient`` Protocol — the chokepoint for every AWS operation docex performs.

Same discipline as ``DockerClient`` / ``GitClient``: any module other
than :mod:`docex.aws.boto3_client` is forbidden from importing ``boto3``.
The Protocol covers **every** AWS operation docex performs, which is what makes
the boto3 ban enforceable. Read the method list below rather than a summary — it
is the surface, and any prose count here would be one refactor from wrong. The
families, for orientation:

  - STS — ``caller_identity``, for SSM ARN derivation
  - SSM Parameter Store — the elastic aggregate (``release``)
  - S3 + DynamoDB — the tofu state backend (``docex projinfra up production``)
  - ECR — registry auth, image existence, image counts (``containerize``,
    ``preinfra``, the rollback image probes)
  - ECS — task-definition register / RunTask / wait (elastic migrate), plus
    cluster, service, deployment and task inspection (the ``stagetest``
    pre-step and the release-time Service Connect consumer reconcile)
  - Cloud Map — Service Connect endpoint discovery, for that same reconcile
  - EC2 — VPC / subnet / security-group discovery for release-time HCL
    prerequisites
  - RDS — the deletion-protection probe that gates ``envinfra down``

Methods that return exit codes are intentionally absent — boto3 raises
exceptions on failure. The orchestrate/pipeline layer catches the boto3
exception types (re-exported via the implementation module) and turns
them into ``DocexError`` subclasses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class AWSClient(Protocol):
    """Abstraction over the AWS SDK (boto3)."""

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def caller_identity(self) -> str:
        """Return the AWS account ID of the active credentials.

        Sourced from STS ``GetCallerIdentity``. Cached per-instance is
        permitted (the account ID doesn't change mid-process).
        """
        ...

    # ------------------------------------------------------------------
    # SSM Parameter Store
    # ------------------------------------------------------------------

    def ssm_get_parameter(self, name: str) -> str | None:
        """Return the decrypted value of the SSM parameter at ``name``, or
        None if it does not exist.

        Used for TTE put-if-absent: SSM is the authoritative store on
        elastic (ECS reads it), so ``aggregate_elastic`` reads a minted
        key back before minting and only mints when SSM has none — a
        lost local copy can never clobber the live RDS credential.
        See config_and_secrets.md § authoritative-store rule (elastic).
        """
        ...

    def ssm_put_parameter(
        self,
        name: str,
        value: str,
        *,
        overwrite: bool = True,
        param_type: str = "SecureString",
    ) -> None:
        """Upsert an SSM parameter at the given path.

        Used by ``release`` to push the three configurable-value
        categories to ``/<project>/<env>/<KEY>``. ``param_type`` is one
        of ``SecureString`` (TTE + secrets) or ``String`` (config — a
        non-secret, fine to appear in task defs/logs); it defaults to
        ``SecureString`` so every legacy caller is unchanged.
        ``overwrite=True`` is the default — secrets/config are clobbered
        on every release; TTE is pushed with ``overwrite=False``
        (put-if-absent). See config_and_secrets.md § 4.2.
        """
        ...

    def ssm_delete_parameters(self, path_prefix: str) -> None:
        """Delete every SSM parameter whose name begins with ``path_prefix``.

        Mod 052 (Gap F): teardown cleanup. ``path_prefix`` is a path like
        ``/<project>/<env>/`` or ``/<project>/`` — every parameter under
        it is removed. Idempotent: a prefix matching nothing is a no-op.
        """
        ...

    # ------------------------------------------------------------------
    # S3 (bootstrap)
    # ------------------------------------------------------------------

    def s3_bucket_exists(self, name: str) -> bool:
        """Return True iff a bucket with this exact name exists and is
        owned by the caller. Used for idempotent bootstrap."""
        ...

    def s3_create_bucket(
        self, name: str, *, region: str, tags: dict[str, str] | None = None
    ) -> None:
        """Create a new S3 bucket in the given region.

        The doctrine pins ``us-east-1``; the ``region`` argument is
        plumbed through anyway so the signature is honest about what
        the implementation requires. In ``us-east-1`` the CreateBucket
        call must omit the LocationConstraint (a long-standing AWS
        quirk); the implementation handles this.

        ``tags`` (Mod 060) carries the projinfra tag block for the tofu
        state bucket; applied via ``put_bucket_tagging`` after create.
        """
        ...

    def s3_enable_versioning(self, name: str) -> None:
        """Enable versioning on the bucket. Idempotent."""
        ...

    def s3_enable_encryption(self, name: str) -> None:
        """Enable AES256 server-side encryption on the bucket. Idempotent."""
        ...

    def s3_block_public_access(self, name: str) -> None:
        """Enable all four block-public-access settings on the bucket. Idempotent."""
        ...

    # ------------------------------------------------------------------
    # DynamoDB (bootstrap)
    # ------------------------------------------------------------------

    def ddb_table_exists(self, name: str) -> bool:
        """Return True iff a DynamoDB table with this name exists."""
        ...

    def ddb_create_locking_table(
        self, name: str, *, tags: dict[str, str] | None = None
    ) -> None:
        """Create the OpenTofu state-locking table (LockID/string PK,
        on-demand billing). Per elastic_bootstrap.md.

        ``tags`` (Mod 060) carries the projinfra tag block for the tofu
        lock table; passed as ``Tags=[…]`` on ``create_table``.
        """
        ...

    def ddb_delete_table(self, name: str) -> None:
        """Delete a DynamoDB table. Mod 052 (Gap F): used to remove the
        OpenTofu state-lock table during ``projinfra down production``.
        A missing table is tolerated (idempotent teardown)."""
        ...

    # ------------------------------------------------------------------
    # Mod 052 (Gap F): teardown probes / deletions
    # ------------------------------------------------------------------

    def rds_protected_instances(self, prefix: str) -> list[str]:
        """Return the identifiers of RDS instances whose identifier begins
        with ``prefix`` and which have ``DeletionProtection`` enabled.

        Mod 052 (Gap F): the env-down safety gate. ``docex envinfra down
        <elastic env>`` calls this with the env's instance prefix
        (hyphenated ``<project_dns_label>-<env>-``); a non-empty result
        means the env contains deletion-protected stateful resources, so
        the command refuses-and-reports *before* destroying anything.
        docex never disables a protection itself.
        """
        ...

    def s3_delete_bucket(self, name: str) -> None:
        """Empty and delete an S3 bucket. Mod 052 (Gap F): removes the
        OpenTofu state-backend bucket during ``projinfra down production``
        — the last thing torn down, once nothing tofu-managed remains. A
        missing bucket is tolerated (idempotent teardown)."""
        ...

    def ecr_repository_image_count(self, repository: str) -> int:
        """Return the number of images in an ECR repository.

        Mod 052 (Gap F): the ``projinfra down production`` pre-flight. A
        non-empty repo is surfaced as a blocker (the operator empties it
        and re-runs). A missing repository returns 0 (nothing to block on).
        """
        ...

    # ------------------------------------------------------------------
    # ECS (release migrations)
    # ------------------------------------------------------------------

    def ecs_register_task_definition(self, family: str, definition: dict) -> str:
        """Register a new revision of the task definition. Returns ARN.

        ``definition`` is the dict form expected by boto3's
        ``register_task_definition`` (keys like ``containerDefinitions``,
        ``cpu``, ``memory``, ``networkMode``, etc.).

        In Phase 4 the migration task definition is actually emitted as
        a Terraform resource and managed via ``tofu apply``; this
        method exists for completeness and for tests that prefer the
        direct-register pattern.
        """
        ...

    def ecs_run_task(
        self,
        *,
        cluster: str,
        task_definition: str,
        subnets: list[str],
        security_groups: list[str],
    ) -> str:
        """``RunTask`` against the given Fargate cluster. Returns task ARN.

        Fargate-only path: ``launchType='FARGATE'``,
        ``networkConfiguration.awsvpcConfiguration`` populated.
        """
        ...

    def ecs_wait_for_task(
        self, *, cluster: str, task_arn: str, timeout_s: int = 600
    ) -> int:
        """Poll ``DescribeTasks`` until the task has stopped. Returns
        the container's exit code.

        Raises :class:`docex.errors.ECSTaskFailed` on timeout or on a
        STOPPED task whose container has no recorded exit code (which
        usually indicates a Fargate platform-side failure to start the
        container at all). A non-zero exit code is returned, not
        raised — the caller decides the policy.
        """
        ...

    # ------------------------------------------------------------------
    # ECR (containerize — elastic ECR-default push)
    # ------------------------------------------------------------------

    def ecr_authorization_token(self) -> tuple[str, str]:
        """Return ``(username, password)`` for ``docker login`` to the
        project's ECR registry.

        Sourced from ECR ``GetAuthorizationToken``; the returned token
        decodes to ``AWS:<password>``. Used by ``containerize`` when an
        elastic project relies on the default ECR (no explicit
        ``container_registry``).
        """
        ...

    def ecr_image_exists(self, repository: str, tag: str) -> bool:
        """Return True iff the ECR repository ``repository`` contains an
        image with the given ``tag``.

        Used by ``rollback`` to confirm every codebase has an image
        at the target version before any infra is touched. Maps to ECR
        ``describe_images`` with ``imageTag=<tag>``;
        ``ImageNotFoundException`` and ``RepositoryNotFoundException``
        return False, other exceptions propagate.
        """
        ...

    # ------------------------------------------------------------------
    # Lookups (release-time HCL prerequisites)
    # ------------------------------------------------------------------

    def get_default_subnets(self, *, vpc_id: str, tier: str) -> list[str]:
        """Return the IDs of the project VPC's subnets in the given tier.

        ``tier`` is ``"public"`` or ``"private"``; the lookup uses the
        ``tier=<tier>`` tag the project-tier OpenTofu provisioning
        applies to each subnet.
        """
        ...

    def get_security_group_id(self, *, vpc_id: str, name: str) -> str:
        """Return the SG ID for a security group with the given Name tag
        in the given VPC. Raises if not found."""
        ...

    def get_ecs_cluster_arn(self, name: str) -> str:
        """Return the ARN of the ECS cluster with the given name. Raises
        if not found."""
        ...

    def ecs_cluster_exists(self, name: str) -> bool:
        """Return True iff an ACTIVE ECS cluster with the given name
        exists. Retained for completeness; since mod 071 the ECS clusters
        are project-tier and always present, so this no longer distinguishes
        a first release — see :meth:`ecs_cluster_has_services`.
        """
        ...

    def ecs_cluster_has_services(self, name: str) -> bool:
        """Return True iff the ECS cluster with the given name has at least
        one registered ECS service.

        Mod 071: the ECS clusters are project-tier and always exist, so
        cluster existence no longer distinguishes a first-time release from
        a steady-state one. Env-service existence does: ``release`` treats an
        empty cluster as a first release (migrations must wait until after
        ``tofu apply`` creates the services), and ``projinfra down`` treats a
        non-empty cluster as a still-live env (refuses project teardown). A
        cluster that does not exist reads as having no services (False).
        """
        ...

    # ------------------------------------------------------------------
    # Mod 109 / 114 / 123: Service Connect consumer reconcile.
    # ------------------------------------------------------------------

    def service_connect_endpoints(self, namespace_name: str) -> dict[str, datetime]:
        """Service Connect endpoint names in a namespace, mapped to their
        Cloud Map ``CreateDate``.

        These are the Cloud Map service names inside the env's namespace — the
        aliases a Service Connect *client* can resolve, and only if they existed
        when its **deployment** was created. ``CreateDate`` is the durable fact the
        release's consumer reconcile compares **deployment** ages against: the
        name is created when the ECS **service** is created, before any of its
        tasks exist, and it survives every task replacement beneath it.

        **A namespace that does not exist reads as the empty mapping**, which is
        the honest answer on a first release: nothing is registered yet.

        Implementations MUST exclude the ``aws-ecs-sc.client.<uuid>.<service>``
        bookkeeping entries that ECS creates for every client-only participant.
        Those register no endpoint, nothing can ``uses`` them, and they are not
        resolvable aliases — so returning them would make this method's contract
        false.
        """
        ...

    def ecs_primary_deployment_times(
        self, cluster: str, services: list[str],
    ) -> dict[str, datetime]:
        """``createdAt`` of the PRIMARY deployment of each named ECS service.

        This is the operand the release's consumer reconcile compares endpoint
        registrations against. A Service Connect Envoy identifies itself to the
        ECS control plane by its **task-set ARN** — the deployment id — and is
        served a cluster list fixed for that deployment; tasks launched later
        into the same deployment inherit it and never re-read the namespace. So
        the durable question is how old the *deployment* is, not how old its
        tasks are (mod 123; mod 114 asked the second and could not fire).

        Two omissions are deliberate and are part of the contract:

        - **A service with no PRIMARY deployment is absent from the mapping.**
        - **A service ECS does not return (missing, or reported under
          ``failures``) is absent from the mapping.**

        Absence is not an error and must not raise. The caller reads a missing
        entry as "redeploy", which is the safe direction: an unreadable
        deployment age cannot be shown to postdate anything.

        Implementations MUST accept any number of services; ``DescribeServices``
        caps at 10 per call, and chunking is the implementation's business.
        """
        ...

    # ------------------------------------------------------------------
    # Mod 128: stagetest's orchestrator liveness/version read.
    # ------------------------------------------------------------------

    def ecs_list_service_task_arns(self, cluster: str, service: str) -> list[str]:
        """Task ARNs of ``service`` with ``desiredStatus=RUNNING``.

        **Raises** when the cluster does not exist, when the service does not
        exist, or when credentials are absent. An empty list means the service
        exists and genuinely has no running tasks — a real, checkable fact, not
        an error.

        **Contrast ``ecs_primary_deployment_times`` immediately above, whose
        contract is the inverse of this one.** That method deliberately swallows
        ``ClusterNotFoundException`` and reports absent services as absent,
        because its caller reads absence as "redeploy" — the safe direction
        *there*. Here the safe direction is the opposite: ``stagetest``'s gate
        must never let an unreadable service be indistinguishable from a healthy
        one. Do not copy that swallow into this method.
        """
        ...

    def ecs_describe_tasks(
        self, cluster: str, task_arns: list[str],
    ) -> list[dict[str, str]]:
        """One dict per task **ECS returned**, keyed ``task_arn``,
        ``last_status``, ``health_status``, ``task_definition``.

        A missing ``healthStatus`` normalises to ECS's own ``"UNKNOWN"``, never
        ``""``, so the caller's diagnosis stays honest.

        Accepts any number of ARNs; ``DescribeTasks`` caps at 100 and chunking
        is the implementation's business.

        **A task ECS does not return — absent, or reported under ``failures`` —
        is simply absent from the result, and that is deliberate**: it is how the
        shrinking-task-set race becomes *visible* to the caller. The caller MUST
        compare the returned count against the requested count and treat a
        shortfall as unreadable state. That policy lives in
        ``pipeline/orchestrator_health.py``, not here, because this adapter
        reports what AWS said and does not decide what it means.
        """
        ...

    def ecs_task_definition_images(self, task_definition: str) -> dict[str, str]:
        """Container name → image ref, for one task-definition ARN or
        ``family:revision``.

        **Raises** if the revision cannot be read (deregistered, throttled,
        denied). An unreadable revision must never be reported as an empty
        mapping: downstream, an empty mapping reads as "no container to check",
        which would silently convert an unanswerable version question into a
        pass.
        """
        ...

    def ecs_force_new_deployment(self, cluster: str, service: str) -> None:
        """Force a new deployment of an ECS service without changing it.

        The only supported way to make a running Service Connect client pick
        up endpoints registered after it started — see mod 109 and
        `cicl.md § Uses Relationships`.
        """
        ...

    def ecs_wait_services_stable(
        self, cluster: str, services: list[str], *, timeout_s: int,
    ) -> bool:
        """Block until every named service reaches steady state.

        Returns ``False`` on timeout rather than raising: a slow rollout is
        not the same failure as a rejected one, and the caller decides which
        of the two is fatal.
        """
        ...

    # ------------------------------------------------------------------
    # Mod 042: preinfra master VPC discovery.
    # ------------------------------------------------------------------

    def find_vpc_by_tags(self, tags: dict[str, str]) -> str | None:
        """Return the first VPC ID matching every (key, value) in tags,
        or None if no match. Operator setup should produce exactly one
        master VPC; if multiple match, the first is returned.

        Used by ``docex preinfra production`` and the elastic migrate
        RunTask to discover the doctrine-prescribed master VPC by its
        semantic identity tags (``managed_by=doctrine-operator`` +
        ``infra_tier=prerequisite`` + ``shape_name=master_network`` per
        ``cicl.md § Naming and Tagging``; mod 060).
        """
        ...

    def find_subnet_ids(
        self,
        *,
        vpc_id: str,
        tags: dict[str, str],
        availability_zone: str | None = None,
    ) -> list[str]:
        """Return subnet IDs in ``vpc_id`` matching all ``tags``. If
        ``availability_zone`` is set, also filter by it. Empty list when
        nothing matches.

        Used by ``docex preinfra production`` to count tagged subnets
        on the master VPC (``tier=public`` / ``tier=private``) and to
        verify the primary-AZ private subnet that elastic workloads pin
        to.
        """
        ...

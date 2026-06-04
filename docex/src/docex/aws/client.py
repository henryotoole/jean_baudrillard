"""``AWSClient`` Protocol — the chokepoint for every AWS operation docex performs.

Same discipline as ``DockerClient`` / ``GitClient``: any module other
than :mod:`docex.aws.boto3_client` is forbidden from importing ``boto3``.
The Protocol covers the union of AWS operations Phase 4 needs:

  - ``caller_identity`` — STS account-ID lookup for SSM ARN derivation
  - SSM Parameter Store push (used by ``release`` to clobber per-env secrets)
  - S3 + DynamoDB create/inspect (used by ``bootstrap``)
  - ECS task definition register + RunTask + wait (used by elastic migrate)
  - EC2 / ECS lookups for release-time HCL prerequisites

Methods that return exit codes are intentionally absent — boto3 raises
exceptions on failure. The orchestrate/pipeline layer catches the boto3
exception types (re-exported via the implementation module) and turns
them into ``DocexError`` subclasses.
"""

from __future__ import annotations

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

    def ssm_put_parameter(self, name: str, value: str, *, overwrite: bool = True) -> None:
        """Upsert an SSM ``SecureString`` parameter at the given path.

        Used by ``release`` to push ``infra/secrets/<env>.env`` values
        to ``/<project>/<env>/<KEY>``. ``overwrite=True`` is the docex
        default — the doctrine deliberately clobbers SSM on every
        release; see release_mechanism.md § Secrets.
        """
        ...

    # ------------------------------------------------------------------
    # S3 (bootstrap)
    # ------------------------------------------------------------------

    def s3_bucket_exists(self, name: str) -> bool:
        """Return True iff a bucket with this exact name exists and is
        owned by the caller. Used for idempotent bootstrap."""
        ...

    def s3_create_bucket(self, name: str, *, region: str) -> None:
        """Create a new S3 bucket in the given region.

        The doctrine pins ``us-east-1``; the ``region`` argument is
        plumbed through anyway so the signature is honest about what
        the implementation requires. In ``us-east-1`` the CreateBucket
        call must omit the LocationConstraint (a long-standing AWS
        quirk); the implementation handles this.
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

    def ddb_create_locking_table(self, name: str) -> None:
        """Create the OpenTofu state-locking table (LockID/string PK,
        on-demand billing). Per elastic_bootstrap.md."""
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

        Used by ``rollback`` to confirm every core service has an image
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
        exists. Used by ``release`` to distinguish a first-time release
        (the cluster hasn't been provisioned yet, so migrations must
        wait until after ``tofu apply``) from a subsequent release
        (cluster exists; migrations run first per the doctrine order).
        """
        ...

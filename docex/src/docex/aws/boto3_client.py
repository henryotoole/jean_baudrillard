"""boto3-backed implementation of :class:`docex.aws.client.AWSClient`.

This is the *only* module in docex permitted to ``import boto3``.
Every other module — orchestrate, pipeline, tests — talks to AWS
through the :class:`AWSClient` Protocol so the chokepoint stays narrow
and unit tests can substitute :class:`tests.conftest.FakeAWSClient`.

Errors are mapped from boto3's ``ClientError`` / ``BotoCoreError`` into
either :class:`docex.errors.AWSCredentialsMissing` (when creds are
absent) or surfaced as-is for the caller to wrap in a domain-specific
``DocexError``. Per the Phase 4 spec, methods do not silently swallow
errors.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import boto3  # noqa: S402 - chokepoint; see module docstring.
from botocore.config import Config
from botocore.exceptions import (  # noqa: S402
    BotoCoreError,
    ClientError,
    NoCredentialsError,
)

from docex import ELASTIC_REGION
from docex.errors import AWSCredentialsMissing, ECSTaskFailed


def _config() -> Config:
    """boto3 client config with conservative retries."""
    return Config(
        region_name=ELASTIC_REGION,
        retries={"max_attempts": 5, "mode": "standard"},
    )


class Boto3AWSClient:
    """Concrete :class:`AWSClient` backed by boto3.

    Construction is cheap: clients are created lazily on first use and
    cached on the instance. This keeps unit tests (which construct
    ``Boto3AWSClient`` but never call into AWS) fast.
    """

    def __init__(self, *, region: str = ELASTIC_REGION) -> None:
        self._region = region
        self._session: Any = None
        self._clients: dict[str, Any] = {}
        self._account_id: str | None = None

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _session_(self) -> Any:
        if self._session is None:
            try:
                self._session = boto3.session.Session(region_name=self._region)
            except NoCredentialsError as e:
                raise AWSCredentialsMissing(str(e)) from e
        return self._session

    def _client(self, service: str) -> Any:
        if service not in self._clients:
            try:
                self._clients[service] = self._session_().client(
                    service, config=_config()
                )
            except NoCredentialsError as e:
                raise AWSCredentialsMissing(str(e)) from e
        return self._clients[service]

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def caller_identity(self) -> str:
        if self._account_id is not None:
            return self._account_id
        try:
            sts = self._client("sts")
            resp = sts.get_caller_identity()
        except NoCredentialsError as e:
            raise AWSCredentialsMissing(str(e)) from e
        self._account_id = str(resp["Account"])
        return self._account_id

    # ------------------------------------------------------------------
    # SSM
    # ------------------------------------------------------------------

    def ssm_put_parameter(
        self, name: str, value: str, *, overwrite: bool = True
    ) -> None:
        ssm = self._client("ssm")
        ssm.put_parameter(
            Name=name,
            Value=value,
            Type="SecureString",
            Overwrite=overwrite,
        )

    # ------------------------------------------------------------------
    # S3
    # ------------------------------------------------------------------

    def s3_bucket_exists(self, name: str) -> bool:
        s3 = self._client("s3")
        try:
            s3.head_bucket(Bucket=name)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            # head_bucket returns 404 for missing buckets; 403 if the
            # bucket exists but the caller can't see it (different owner).
            # We treat 404 as "doesn't exist" and re-raise everything else.
            if code in ("404", "NoSuchBucket", "NotFound"):
                return False
            raise

    def s3_create_bucket(self, name: str, *, region: str) -> None:
        s3 = self._client("s3")
        # us-east-1 quirk: CreateBucket rejects LocationConstraint for
        # us-east-1 specifically. Every other region requires it.
        if region == "us-east-1":
            s3.create_bucket(Bucket=name)
        else:
            s3.create_bucket(
                Bucket=name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )

    def s3_enable_versioning(self, name: str) -> None:
        s3 = self._client("s3")
        s3.put_bucket_versioning(
            Bucket=name,
            VersioningConfiguration={"Status": "Enabled"},
        )

    def s3_enable_encryption(self, name: str) -> None:
        s3 = self._client("s3")
        s3.put_bucket_encryption(
            Bucket=name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        }
                    }
                ]
            },
        )

    def s3_block_public_access(self, name: str) -> None:
        s3 = self._client("s3")
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )

    # ------------------------------------------------------------------
    # DynamoDB
    # ------------------------------------------------------------------

    def ddb_table_exists(self, name: str) -> bool:
        ddb = self._client("dynamodb")
        try:
            ddb.describe_table(TableName=name)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return False
            raise

    def ddb_create_locking_table(self, name: str) -> None:
        ddb = self._client("dynamodb")
        ddb.create_table(
            TableName=name,
            AttributeDefinitions=[{"AttributeName": "LockID", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "LockID", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # Block until the table is ACTIVE so subsequent operations
        # (or, more commonly, a re-run of bootstrap) don't race.
        waiter = ddb.get_waiter("table_exists")
        waiter.wait(TableName=name)

    # ------------------------------------------------------------------
    # ECS
    # ------------------------------------------------------------------

    def ecs_register_task_definition(self, family: str, definition: dict) -> str:
        ecs = self._client("ecs")
        body = dict(definition)
        body["family"] = family
        resp = ecs.register_task_definition(**body)
        return str(resp["taskDefinition"]["taskDefinitionArn"])

    def ecs_run_task(
        self,
        *,
        cluster: str,
        task_definition: str,
        subnets: list[str],
        security_groups: list[str],
    ) -> str:
        ecs = self._client("ecs")
        resp = ecs.run_task(
            cluster=cluster,
            taskDefinition=task_definition,
            launchType="FARGATE",
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": list(subnets),
                    "securityGroups": list(security_groups),
                    "assignPublicIp": "DISABLED",
                }
            },
        )
        tasks = resp.get("tasks", [])
        if not tasks:
            failures = resp.get("failures", [])
            raise ECSTaskFailed(
                f"RunTask returned no tasks; failures={failures!r}"
            )
        return str(tasks[0]["taskArn"])

    def ecs_wait_for_task(
        self, *, cluster: str, task_arn: str, timeout_s: int = 600
    ) -> int:
        ecs = self._client("ecs")
        deadline = time.monotonic() + timeout_s
        poll_interval = 5
        while True:
            resp = ecs.describe_tasks(cluster=cluster, tasks=[task_arn])
            tasks = resp.get("tasks", [])
            if not tasks:
                raise ECSTaskFailed(
                    f"describe_tasks returned no record for {task_arn!r}"
                )
            task = tasks[0]
            last_status = task.get("lastStatus", "")
            if last_status == "STOPPED":
                containers = task.get("containers", [])
                if not containers:
                    raise ECSTaskFailed(
                        f"task {task_arn!r} STOPPED with no containers; "
                        f"stoppedReason={task.get('stoppedReason')!r}"
                    )
                # We RunTask exactly one container (Fargate constraint
                # in our doctrine) so containers[0] is THE container.
                exit_code = containers[0].get("exitCode")
                if exit_code is None:
                    # Container never started — Fargate couldn't pull
                    # the image, network failed, IAM denied, etc.
                    reason = containers[0].get("reason") or task.get(
                        "stoppedReason"
                    )
                    raise ECSTaskFailed(
                        f"task {task_arn!r} STOPPED without an exit code; "
                        f"reason={reason!r}"
                    )
                return int(exit_code)
            if time.monotonic() > deadline:
                raise ECSTaskFailed(
                    f"task {task_arn!r} did not stop within {timeout_s}s "
                    f"(last status={last_status!r})"
                )
            time.sleep(poll_interval)

    # ------------------------------------------------------------------
    # ECR
    # ------------------------------------------------------------------

    def ecr_authorization_token(self) -> tuple[str, str]:
        ecr = self._client("ecr")
        resp = ecr.get_authorization_token()
        data = resp["authorizationData"][0]
        token = base64.b64decode(data["authorizationToken"]).decode("utf-8")
        username, _, password = token.partition(":")
        return username, password

    # ------------------------------------------------------------------
    # EC2 / ECS lookups
    # ------------------------------------------------------------------

    def get_default_subnets(self, *, vpc_id: str, tier: str) -> list[str]:
        ec2 = self._client("ec2")
        resp = ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "tag:tier", "Values": [tier]},
            ]
        )
        return sorted(s["SubnetId"] for s in resp.get("Subnets", []))

    def get_security_group_id(self, *, vpc_id: str, name: str) -> str:
        ec2 = self._client("ec2")
        resp = ec2.describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "group-name", "Values": [name]},
            ]
        )
        groups = resp.get("SecurityGroups", [])
        if not groups:
            raise ECSTaskFailed(
                f"no security group named {name!r} in VPC {vpc_id!r}"
            )
        return str(groups[0]["GroupId"])

    def get_ecs_cluster_arn(self, name: str) -> str:
        ecs = self._client("ecs")
        resp = ecs.describe_clusters(clusters=[name])
        clusters = resp.get("clusters", [])
        if not clusters or clusters[0].get("status") != "ACTIVE":
            raise ECSTaskFailed(
                f"no ACTIVE ECS cluster named {name!r}"
            )
        return str(clusters[0]["clusterArn"])

    def ecs_cluster_exists(self, name: str) -> bool:
        ecs = self._client("ecs")
        resp = ecs.describe_clusters(clusters=[name])
        clusters = resp.get("clusters", [])
        return bool(clusters) and clusters[0].get("status") == "ACTIVE"


__all__ = ["Boto3AWSClient", "BotoCoreError", "ClientError", "NoCredentialsError"]

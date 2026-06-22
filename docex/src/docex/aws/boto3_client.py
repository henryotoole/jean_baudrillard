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

    def ssm_delete_parameters(self, path_prefix: str) -> None:
        ssm = self._client("ssm")
        paginator = ssm.get_paginator("describe_parameters")
        names: list[str] = []
        for page in paginator.paginate(
            ParameterFilters=[
                {"Key": "Name", "Option": "BeginsWith", "Values": [path_prefix]}
            ]
        ):
            names.extend(p["Name"] for p in page.get("Parameters", []))
        # DeleteParameters accepts at most 10 names per call.
        for i in range(0, len(names), 10):
            ssm.delete_parameters(Names=names[i : i + 10])

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

    def s3_create_bucket(
        self, name: str, *, region: str, tags: dict[str, str] | None = None
    ) -> None:
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
        # Mod 060: S3 has no create-time tagging — apply the projinfra tag
        # block in a separate idempotent put_bucket_tagging call.
        if tags:
            s3.put_bucket_tagging(
                Bucket=name,
                Tagging={"TagSet": [
                    {"Key": k, "Value": v} for k, v in tags.items()
                ]},
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

    def s3_delete_bucket(self, name: str) -> None:
        s3 = self._client("s3")
        try:
            # Empty the bucket first — DeleteBucket fails on a non-empty
            # one. The state backend is versioned, so delete object
            # versions and delete-markers, not just current keys.
            paginator = s3.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=name):
                to_delete = [
                    {"Key": o["Key"], "VersionId": o["VersionId"]}
                    for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
                ]
                if to_delete:
                    s3.delete_objects(
                        Bucket=name, Delete={"Objects": to_delete}
                    )
            s3.delete_bucket(Bucket=name)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket", "NotFound"):
                return  # already gone — idempotent teardown
            raise

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

    def ddb_create_locking_table(
        self, name: str, *, tags: dict[str, str] | None = None
    ) -> None:
        ddb = self._client("dynamodb")
        # Mod 060: DynamoDB supports create-time tagging.
        kwargs: dict = {}
        if tags:
            kwargs["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        ddb.create_table(
            TableName=name,
            AttributeDefinitions=[{"AttributeName": "LockID", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "LockID", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
            **kwargs,
        )
        # Block until the table is ACTIVE so subsequent operations
        # (or, more commonly, a re-run of bootstrap) don't race.
        waiter = ddb.get_waiter("table_exists")
        waiter.wait(TableName=name)

    def ddb_delete_table(self, name: str) -> None:
        ddb = self._client("dynamodb")
        try:
            ddb.delete_table(TableName=name)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return  # already gone — idempotent teardown
            raise

    # ------------------------------------------------------------------
    # Mod 052 (Gap F): teardown probes / deletions
    # ------------------------------------------------------------------

    def rds_protected_instances(self, prefix: str) -> list[str]:
        rds = self._client("rds")
        protected: list[str] = []
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for inst in page.get("DBInstances", []):
                identifier = inst.get("DBInstanceIdentifier", "")
                if identifier.startswith(prefix) and inst.get("DeletionProtection"):
                    protected.append(identifier)
        return sorted(protected)

    def ecr_repository_image_count(self, repository: str) -> int:
        ecr = self._client("ecr")
        try:
            count = 0
            paginator = ecr.get_paginator("list_images")
            for page in paginator.paginate(repositoryName=repository):
                count += len(page.get("imageIds", []))
            return count
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "RepositoryNotFoundException":
                return 0  # missing repo — nothing to block on
            raise

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
        # Mod 027: after RunTask returns a task ARN, the immediately-
        # following describe_tasks call can briefly return tasks: []
        # due to ECS API eventual consistency. Tolerate empty
        # responses for up to 30 s of polling before raising; once
        # the task has been observed at least once, an empty response
        # in subsequent polls retains its sharp meaning ("vanished").
        seen_once = False
        consistency_deadline = time.monotonic() + 30
        while True:
            resp = ecs.describe_tasks(cluster=cluster, tasks=[task_arn])
            tasks = resp.get("tasks", [])
            if not tasks:
                if seen_once or time.monotonic() > consistency_deadline:
                    raise ECSTaskFailed(
                        f"describe_tasks returned no record for {task_arn!r}"
                    )
                time.sleep(poll_interval)
                continue
            seen_once = True
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

    def ecr_image_exists(self, repository: str, tag: str) -> bool:
        ecr = self._client("ecr")
        try:
            ecr.describe_images(
                repositoryName=repository,
                imageIds=[{"imageTag": tag}],
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            # RepositoryNotFoundException is also treated as "absent":
            # if the repo itself is missing, the image obviously is too,
            # and the caller wants a clean "image missing" diagnostic
            # rather than a raised exception.
            if code in ("ImageNotFoundException", "RepositoryNotFoundException"):
                return False
            raise
        return True

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

    # ------------------------------------------------------------------
    # Mod 042: preinfra master VPC discovery
    # ------------------------------------------------------------------

    def find_vpc_by_tags(self, tags: dict[str, str]) -> str | None:
        ec2 = self._client("ec2")
        filters = [
            {"Name": f"tag:{key}", "Values": [value]}
            for key, value in tags.items()
        ]
        resp = ec2.describe_vpcs(Filters=filters)
        vpcs = resp.get("Vpcs", [])
        if not vpcs:
            return None
        return str(vpcs[0]["VpcId"])

    def find_subnet_ids(
        self,
        *,
        vpc_id: str,
        tags: dict[str, str],
        availability_zone: str | None = None,
    ) -> list[str]:
        ec2 = self._client("ec2")
        filters: list[dict[str, Any]] = [
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
        for key, value in tags.items():
            filters.append({"Name": f"tag:{key}", "Values": [value]})
        if availability_zone is not None:
            filters.append(
                {"Name": "availability-zone", "Values": [availability_zone]}
            )
        resp = ec2.describe_subnets(Filters=filters)
        return sorted(s["SubnetId"] for s in resp.get("Subnets", []))


__all__ = ["Boto3AWSClient", "BotoCoreError", "ClientError", "NoCredentialsError"]

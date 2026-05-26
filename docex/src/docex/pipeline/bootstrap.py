"""``docex bootstrap`` — idempotent setup of the elastic project state backend.

Per :doc:`elastic_bootstrap.md` (doctrine/infrastructure/specifics):

- Creates an S3 bucket ``<project>-tofu-state`` with versioning,
  AES256 encryption, and all four block-public-access settings.
- Creates a DynamoDB table ``<project>-tofu-locks`` with a string
  ``LockID`` primary key and on-demand billing.
- Idempotent. Safe to re-run; a second invocation finds the resources
  in place and reconciles their configuration (re-enabling versioning,
  re-applying encryption, etc.).

Fixed-foundation projects don't need this; the command short-circuits
with a clean "no-op" message.
"""

from __future__ import annotations

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.errors import BootstrapFailed


# CICL simplification: only us-east-1 is supported.
_REGION = "us-east-1"


def run_bootstrap(ctx: ProjectContext, aws: AWSClient) -> int:
    """Create or reconcile the project's OpenTofu state backend.

    Returns process exit code (0 on success).
    """
    if ctx.infra is not None and ctx.infra.foundation == "fixed":
        print("docex bootstrap is a no-op for fixed-foundation projects.")
        return 0

    project = ctx.project.name
    bucket = f"{project}-tofu-state"
    table = f"{project}-tofu-locks"

    try:
        # S3 bucket — idempotent create.
        if not aws.s3_bucket_exists(bucket):
            aws.s3_create_bucket(bucket, region=_REGION)
            print(f"bootstrap: created S3 bucket {bucket}")
        else:
            print(f"bootstrap: S3 bucket {bucket} already exists")

        # Reconcile bucket-level settings every run. Each is idempotent
        # at the AWS API level — putting the same config twice is a no-op.
        aws.s3_enable_versioning(bucket)
        aws.s3_enable_encryption(bucket)
        aws.s3_block_public_access(bucket)

        # DynamoDB lock table — idempotent create.
        if not aws.ddb_table_exists(table):
            aws.ddb_create_locking_table(table)
            print(f"bootstrap: created DynamoDB table {table}")
        else:
            print(f"bootstrap: DynamoDB table {table} already exists")
    except Exception as exc:
        # Surface a clean DocexError so the dispatcher renders nicely.
        raise BootstrapFailed(
            f"bootstrap failed against project {project!r} in region {_REGION!r}: {exc}"
        ) from exc

    print(
        f"bootstrap: project {project!r} state backend ready "
        f"(region={_REGION})."
    )
    return 0

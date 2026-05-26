"""Unit tests for ``docex bootstrap``.

Verifies:

- On an elastic project, the command creates the S3 bucket + DynamoDB
  table when they're absent, reconciling versioning / encryption /
  block-public-access on every run.
- Idempotence: re-running with both already-present does NOT call
  ``create_bucket`` / ``create_table`` but DOES re-call the reconcile
  setters.
- Fixed-foundation projects short-circuit with a "no-op" message.
- Any AWS exception is wrapped in :class:`BootstrapFailed`.
"""

from __future__ import annotations

import pytest

from docex.errors import BootstrapFailed
from docex.pipeline.bootstrap import run_bootstrap


def _names(calls: list[tuple]) -> list[str]:
    return [c[0] for c in calls]


def test_bootstrap_creates_bucket_and_table_when_absent(elastic_ctx, fake_aws):
    fake_aws.bucket_exists = False
    fake_aws.table_exists = False
    rc = run_bootstrap(elastic_ctx, fake_aws)
    assert rc == 0
    names = _names(fake_aws.calls)
    # Existence probe → create → reconciliation calls all happen.
    assert "s3_bucket_exists" in names
    assert "s3_create_bucket" in names
    assert "s3_enable_versioning" in names
    assert "s3_enable_encryption" in names
    assert "s3_block_public_access" in names
    assert "ddb_table_exists" in names
    assert "ddb_create_locking_table" in names
    # Order: create_bucket must precede the reconcile setters.
    assert names.index("s3_create_bucket") < names.index("s3_enable_versioning")


def test_bootstrap_is_idempotent_when_resources_exist(elastic_ctx, fake_aws):
    """Re-running with bucket + table already present: no creates, but
    versioning/encryption/block-public-access are still reapplied."""
    fake_aws.bucket_exists = True
    fake_aws.table_exists = True
    rc = run_bootstrap(elastic_ctx, fake_aws)
    assert rc == 0
    names = _names(fake_aws.calls)
    assert "s3_create_bucket" not in names
    assert "ddb_create_locking_table" not in names
    # But reconciliation setters STILL run (idempotent at AWS layer).
    assert "s3_enable_versioning" in names
    assert "s3_enable_encryption" in names
    assert "s3_block_public_access" in names


def test_bootstrap_fixed_foundation_is_no_op(sample_ctx, fake_aws, capsys):
    rc = run_bootstrap(sample_ctx, fake_aws)
    assert rc == 0
    # No AWS calls at all on the fixed-foundation short-circuit.
    assert fake_aws.calls == []
    assert "no-op" in capsys.readouterr().out


def test_bootstrap_wraps_aws_exception_in_bootstrap_failed(elastic_ctx, fake_aws):
    """Any AWS exception in the bootstrap pipeline surfaces as a
    BootstrapFailed for clean error reporting at the dispatcher."""
    fake_aws.bucket_exists = False
    # Make create_bucket raise on first call.
    fake_aws.raise_on["s3_create_bucket"] = RuntimeError("aws down")
    with pytest.raises(BootstrapFailed) as exc_info:
        run_bootstrap(elastic_ctx, fake_aws)
    assert "aws down" in str(exc_info.value)


def test_bootstrap_uses_project_scoped_resource_names(elastic_ctx, fake_aws):
    """Bucket = ``<project>-tofu-state``; table = ``<project>-tofu-locks``."""
    run_bootstrap(elastic_ctx, fake_aws)
    # The fixture's project name is 'sample'.
    bucket_calls = [c for c in fake_aws.calls if c[0] == "s3_bucket_exists"]
    table_calls = [c for c in fake_aws.calls if c[0] == "ddb_table_exists"]
    assert bucket_calls and bucket_calls[0][1][0] == "sample-tofu-state"
    assert table_calls and table_calls[0][1][0] == "sample-tofu-locks"

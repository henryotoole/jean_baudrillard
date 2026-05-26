"""``AWSClient`` abstraction and the boto3-backed implementation.

Phase 4 adds AWS operations (SSM, S3 + DynamoDB for bootstrap, ECS for
release migrations, EC2 lookups) parallel to Phase 2's ``DockerClient``
and Phase 3's ``GitClient``. Same chokepoint discipline: ``boto3`` is
imported ONLY from :mod:`docex.aws.boto3_client`.
"""

from __future__ import annotations

from docex.aws.client import AWSClient
from docex.aws.boto3_client import Boto3AWSClient

__all__ = ["AWSClient", "Boto3AWSClient"]

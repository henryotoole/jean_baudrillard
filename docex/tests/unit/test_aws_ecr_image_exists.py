"""Unit tests for ``Boto3AWSClient.ecr_image_exists``.

Mod 029: rollback probes ECR for every core service's image at the
target version before any infra is touched. The probe must distinguish
"image absent" from "everything else" (real API errors propagate).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from docex.aws.boto3_client import Boto3AWSClient


def _client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": code}},
        operation_name="DescribeImages",
    )


def test_ecr_image_exists_returns_true_on_success(monkeypatch):
    client = Boto3AWSClient()
    fake_ecr = MagicMock()
    fake_ecr.describe_images.return_value = {"imageDetails": [{"imageTag": "0.1.0"}]}
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecr)
    assert client.ecr_image_exists("proj/api", "0.1.0") is True
    fake_ecr.describe_images.assert_called_once_with(
        repositoryName="proj/api",
        imageIds=[{"imageTag": "0.1.0"}],
    )


def test_ecr_image_exists_returns_false_on_image_not_found(monkeypatch):
    client = Boto3AWSClient()
    fake_ecr = MagicMock()
    fake_ecr.describe_images.side_effect = _client_error("ImageNotFoundException")
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecr)
    assert client.ecr_image_exists("proj/api", "0.1.0") is False


def test_ecr_image_exists_returns_false_on_repository_not_found(monkeypatch):
    client = Boto3AWSClient()
    fake_ecr = MagicMock()
    fake_ecr.describe_images.side_effect = _client_error("RepositoryNotFoundException")
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecr)
    assert client.ecr_image_exists("proj/api", "0.1.0") is False


def test_ecr_image_exists_propagates_unexpected_client_error(monkeypatch):
    client = Boto3AWSClient()
    fake_ecr = MagicMock()
    fake_ecr.describe_images.side_effect = _client_error("AccessDeniedException")
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecr)
    with pytest.raises(ClientError):
        client.ecr_image_exists("proj/api", "0.1.0")

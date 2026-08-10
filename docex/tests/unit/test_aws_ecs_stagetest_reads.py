"""Boto3-adapter tests for the three reads behind ``stagetest``'s orchestrator
pre-step (mod 128).

The pipeline-level tests in ``test_orchestrator_health.py`` run against
``FakeAWSClient`` and therefore cannot see the shape of the boto3 calls, the
chunking, or the ``desiredStatus`` filter the port's contract mandates. These
can.

The contract that matters most here is **the inverse of the neighbouring
method's**: ``ecs_primary_deployment_times`` deliberately swallows
``ClusterNotFoundException`` because its caller reads absence as "redeploy" —
the safe direction there. ``ecs_list_service_task_arns`` must let it propagate,
because ``stagetest``'s gate must never let an unreadable service look like a
healthy one. Both behaviours are asserted in adjacent tests below so the
contrast is visible in one screenful.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docex.aws.boto3_client import Boto3AWSClient


class _ClusterNotFoundException(Exception):
    """Stands in for ``ecs.exceptions.ClusterNotFoundException``."""


def _paginator(pages: list[dict]) -> MagicMock:
    pag = MagicMock()
    pag.paginate.return_value = pages
    return pag


def _ecs_with_exceptions() -> MagicMock:
    """A fake ecs client whose ``.exceptions.ClusterNotFoundException`` is a real
    catchable class, as boto3's is."""
    fake = MagicMock()
    fake.exceptions.ClusterNotFoundException = _ClusterNotFoundException
    return fake


# ---------------------------------------------------------------------------
# ecs_list_service_task_arns
# ---------------------------------------------------------------------------


def test_list_service_task_arns_pins_desired_status_running(monkeypatch):
    """``desiredStatus=RUNNING`` must actually be passed. Without it ListTasks
    also returns STOPPED tasks, and a stopped task's health would be judged as
    if it were live."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    pag = _paginator([
        {"taskArns": ["arn:task/a", "arn:task/b"]},
        {"taskArns": ["arn:task/c"]},
    ])
    fake_ecs.get_paginator.return_value = pag
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_list_service_task_arns("sample-stage", "sample-stage-api-web") == [
        "arn:task/a", "arn:task/b", "arn:task/c",
    ]
    assert pag.paginate.call_args.kwargs == {
        "cluster": "sample-stage",
        "serviceName": "sample-stage-api-web",
        "desiredStatus": "RUNNING",
    }


def test_list_service_task_arns_empty_is_a_fact_not_an_error(monkeypatch):
    """An existing service with no running tasks reads as ``[]``. The caller
    turns that into ``DeployedServiceUnhealthy``; this layer just reports it."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    fake_ecs.get_paginator.return_value = _paginator([{"taskArns": []}])
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_list_service_task_arns("sample-stage", "svc") == []


def test_list_service_task_arns_propagates_cluster_not_found(monkeypatch):
    """THE contract. Contrast the next test."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    pag = MagicMock()
    pag.paginate.side_effect = _ClusterNotFoundException("no such cluster")
    fake_ecs.get_paginator.return_value = pag
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    with pytest.raises(_ClusterNotFoundException):
        client.ecs_list_service_task_arns("sample-stage", "svc")


def test_primary_deployment_times_still_swallows_cluster_not_found(monkeypatch):
    """The neighbour's inverse contract, asserted adjacently on purpose: these
    two methods must NOT be made consistent with each other. There, absence
    means "redeploy" (safe). Here, absence must mean "we could not look"."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    fake_ecs.describe_services.side_effect = _ClusterNotFoundException("gone")
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_primary_deployment_times("sample-stage", ["svc"]) == {}


# ---------------------------------------------------------------------------
# ecs_describe_tasks
# ---------------------------------------------------------------------------


def test_describe_tasks_chunks_at_one_hundred(monkeypatch):
    """``DescribeTasks`` accepts at most 100 tasks per call, so 250 ARNs must
    become three calls of 100 / 100 / 50."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    arns = [f"arn:task/{i:03d}" for i in range(250)]

    def _describe(cluster, tasks):
        return {"tasks": [
            {
                "taskArn": arn,
                "lastStatus": "RUNNING",
                "healthStatus": "HEALTHY",
                "taskDefinitionArn": "arn:td/sample:7",
            }
            for arn in tasks
        ]}

    fake_ecs.describe_tasks.side_effect = _describe
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    out = client.ecs_describe_tasks("sample-stage", arns)
    assert [r["task_arn"] for r in out] == arns
    assert [
        len(call.kwargs["tasks"])
        for call in fake_ecs.describe_tasks.call_args_list
    ] == [100, 100, 50]
    assert fake_ecs.describe_tasks.call_args.kwargs["cluster"] == "sample-stage"


def test_describe_tasks_missing_health_status_normalises_to_unknown(monkeypatch):
    """Never ``""``. ECS's own sentinel is ``UNKNOWN``, and the caller's
    diagnosis ("no container declares a health check") depends on reading it."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    fake_ecs.describe_tasks.return_value = {"tasks": [
        {"taskArn": "arn:task/a", "lastStatus": "RUNNING",
         "taskDefinitionArn": "arn:td/sample:7"},
    ]}
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_describe_tasks("sample-stage", ["arn:task/a"]) == [{
        "task_arn": "arn:task/a",
        "last_status": "RUNNING",
        "health_status": "UNKNOWN",
        "task_definition": "arn:td/sample:7",
    }]


def test_describe_tasks_omits_tasks_reported_under_failures(monkeypatch):
    """A task ECS does not return is simply absent from the result — that is how
    the shrinking-task-set race becomes visible to the caller, which compares
    the returned count against the requested count. Deciding what a shortfall
    *means* is the pipeline's job, not this adapter's."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    fake_ecs.describe_tasks.return_value = {
        "tasks": [
            {"taskArn": "arn:task/a", "lastStatus": "RUNNING",
             "healthStatus": "HEALTHY", "taskDefinitionArn": "arn:td/sample:7"},
        ],
        "failures": [{"arn": "arn:task/b", "reason": "MISSING"}],
    }
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    out = client.ecs_describe_tasks("sample-stage", ["arn:task/a", "arn:task/b"])
    assert [r["task_arn"] for r in out] == ["arn:task/a"]


def test_describe_tasks_no_arns_makes_no_call(monkeypatch):
    """``tasks=[]`` is a boto3 validation error, not an empty result."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_describe_tasks("sample-stage", []) == []
    assert fake_ecs.describe_tasks.call_count == 0


# ---------------------------------------------------------------------------
# ecs_task_definition_images
# ---------------------------------------------------------------------------


def test_task_definition_images_maps_container_name_to_image(monkeypatch):
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    fake_ecs.describe_task_definition.return_value = {"taskDefinition": {
        "containerDefinitions": [
            {"name": "api-web", "image": "reg/sample/api:0.1.0"},
            {"name": "api-web-otelcol", "image": "otel/collector@sha256:abc"},
        ],
    }}
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_task_definition_images("arn:td/sample:7") == {
        "api-web": "reg/sample/api:0.1.0",
        "api-web-otelcol": "otel/collector@sha256:abc",
    }
    assert fake_ecs.describe_task_definition.call_args.kwargs == {
        "taskDefinition": "arn:td/sample:7",
    }


def test_task_definition_images_propagates_unreadable_revision(monkeypatch):
    """An unreadable revision (deregistered, throttled, denied) must raise. An
    empty mapping would read downstream as "no container to check", silently
    converting an unanswerable version question into a pass."""
    client = Boto3AWSClient()
    fake_ecs = _ecs_with_exceptions()
    fake_ecs.describe_task_definition.side_effect = RuntimeError(
        "ClientError: ClientException — Unable to describe task definition"
    )
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    with pytest.raises(RuntimeError):
        client.ecs_task_definition_images("arn:td/sample:7")

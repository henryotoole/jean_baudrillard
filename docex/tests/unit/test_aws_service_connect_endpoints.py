"""Unit tests for the mod-114 adapter reads behind the Service Connect
consumer reconcile.

Mod 114: the reconcile compares two durable AWS timestamps — a Cloud Map
endpoint's ``CreateDate`` and the ``startedAt`` of a consumer's oldest running
task. These tests pin the two adapter methods that produce them, because the
pipeline-level tests run against a fake and so cannot see the shape of the
boto3 calls or the filtering the port's contract mandates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from docex.aws.boto3_client import Boto3AWSClient


def _t(minute: int) -> datetime:
    return datetime(2026, 8, 5, 20, minute, tzinfo=timezone.utc)


def _paginator(pages: list[dict]) -> MagicMock:
    pag = MagicMock()
    pag.paginate.return_value = pages
    return pag


def test_service_connect_endpoints_filters_client_bookkeeping_entries(monkeypatch):
    """ECS creates one `aws-ecs-sc.client.<uuid>.<service>` Cloud Map entry per
    client-only participant. It registers no endpoint and nothing can `uses` it,
    so returning it would make the port's contract — "the names a client task
    can resolve" — false."""
    client = Boto3AWSClient()
    fake_sd = MagicMock()
    namespaces = _paginator([
        {"Namespaces": [{"Name": "sample-prod", "Id": "ns-abc123"}]},
    ])
    services = _paginator([
        {"Services": [
            {"Name": "sample-prod-api-web", "CreateDate": _t(40)},
            {"Name": "aws-ecs-sc.client.7f3c-uuid.sample-prod-api-web",
             "CreateDate": _t(59)},
        ]},
        {"Services": [
            {"Name": "sample-prod-api-worker", "CreateDate": _t(46)},
            # No CreateDate: cannot be compared against, so it is dropped.
            {"Name": "sample-prod-orphan"},
        ]},
    ])
    fake_sd.get_paginator.side_effect = lambda op: {
        "list_namespaces": namespaces, "list_services": services,
    }[op]
    monkeypatch.setattr(client, "_client", lambda _name: fake_sd)

    assert client.service_connect_endpoints("sample-prod") == {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(46),
    }
    # The namespace filter must be applied server-side, on the resolved ID.
    assert services.paginate.call_args.kwargs["Filters"] == [
        {"Name": "NAMESPACE_ID", "Values": ["ns-abc123"], "Condition": "EQ"},
    ]


def test_service_connect_endpoints_absent_namespace_reads_as_empty(monkeypatch):
    """First release: the env namespace is created by the same apply that
    creates the services, so "absent" and "empty" coincide. `list_services` is
    never reached — there is no namespace ID to filter on."""
    client = Boto3AWSClient()
    fake_sd = MagicMock()
    list_services = _paginator([])
    fake_sd.get_paginator.side_effect = lambda op: {
        "list_namespaces": _paginator([{"Namespaces": [{"Name": "other", "Id": "ns-x"}]}]),
        "list_services": list_services,
    }[op]
    monkeypatch.setattr(client, "_client", lambda _name: fake_sd)

    assert client.service_connect_endpoints("sample-prod") == {}
    list_services.paginate.assert_not_called()


def test_ecs_running_task_start_times_filters_and_chunks(monkeypatch):
    """Only genuinely RUNNING tasks with a `startedAt` count, and DescribeTasks
    accepts at most 100 ARNs per call — 150 tasks must become two calls."""
    client = Boto3AWSClient()
    fake_ecs = MagicMock()
    arns = [f"arn:task/{i}" for i in range(150)]
    fake_ecs.get_paginator.return_value = _paginator([
        {"taskArns": arns[:80]}, {"taskArns": arns[80:]},
    ])

    def _describe(cluster, tasks):
        if len(tasks) == 100:
            return {"tasks": [
                {"lastStatus": "RUNNING", "startedAt": _t(40)},
                # Desired RUNNING but not there yet: it has not read the
                # namespace, so it cannot be stale.
                {"lastStatus": "PENDING", "startedAt": _t(41)},
                # RUNNING but no startedAt reported — same reasoning.
                {"lastStatus": "RUNNING"},
            ]}
        return {"tasks": [{"lastStatus": "RUNNING", "startedAt": _t(46)}]}

    fake_ecs.describe_tasks.side_effect = _describe
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_running_task_start_times("sample-prod", "sample-prod-api-web") == [
        _t(40), _t(46),
    ]
    assert fake_ecs.describe_tasks.call_count == 2
    assert fake_ecs.get_paginator.return_value.paginate.call_args.kwargs == {
        "cluster": "sample-prod",
        "serviceName": "sample-prod-api-web",
        "desiredStatus": "RUNNING",
    }


def test_ecs_running_task_start_times_missing_service_reads_as_no_tasks(monkeypatch):
    """A service ECS reports as non-existent reads as `[]`, not an error: a
    service with no tasks cannot hold a stale one."""
    client = Boto3AWSClient()
    fake_ecs = MagicMock()

    class ServiceNotFoundException(Exception):
        pass

    class ClusterNotFoundException(Exception):
        pass

    fake_ecs.exceptions.ServiceNotFoundException = ServiceNotFoundException
    fake_ecs.exceptions.ClusterNotFoundException = ClusterNotFoundException
    pag = MagicMock()
    pag.paginate.side_effect = ServiceNotFoundException("no such service")
    fake_ecs.get_paginator.return_value = pag
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_running_task_start_times("sample-prod", "gone") == []
    fake_ecs.describe_tasks.assert_not_called()

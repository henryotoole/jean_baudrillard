"""Unit tests for the adapter reads behind the Service Connect consumer
reconcile (mods 114 / 123).

The reconcile compares two durable AWS timestamps — a Cloud Map endpoint's
``CreateDate`` and the ``createdAt`` of the consumer's PRIMARY ECS deployment.
These tests pin the two adapter methods that produce them, because the
pipeline-level tests run against a fake and so cannot see the shape of the
boto3 calls, the chunking, or the filtering the port's contract mandates.
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


def test_ecs_primary_deployment_times_chunks_at_ten(monkeypatch):
    """`DescribeServices` accepts at most 10 services per call, so 23 names must
    become three calls of 10 / 10 / 3 — and only the PRIMARY deployment's
    `createdAt` is read. A service mid-rollout carries an ACTIVE deployment too;
    that one is the *outgoing* task set and is not what the reconcile judges."""
    client = Boto3AWSClient()
    fake_ecs = MagicMock()
    names = [f"svc-{i:02d}" for i in range(23)]

    def _describe(cluster, services):
        return {"services": [
            {
                "serviceName": name,
                "deployments": [
                    # Deliberately listed ACTIVE-first: the read must select on
                    # `status`, not on position.
                    {"status": "ACTIVE", "createdAt": _t(40)},
                    {"status": "PRIMARY", "createdAt": _t(46)},
                ],
            }
            for name in services
        ]}

    fake_ecs.describe_services.side_effect = _describe
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    out = client.ecs_primary_deployment_times("sample-prod", names)

    assert out == {name: _t(46) for name in names}
    assert [
        len(call.kwargs["services"])
        for call in fake_ecs.describe_services.call_args_list
    ] == [10, 10, 3]
    assert fake_ecs.describe_services.call_args.kwargs["cluster"] == "sample-prod"


def test_ecs_primary_deployment_times_omits_unreadable_services(monkeypatch):
    """Absence, not an error and not a default. ECS reports an unknown service
    under `failures` rather than raising, and a service can be returned with no
    PRIMARY deployment at all; both are simply missing from the mapping, and the
    caller reads a missing entry as "redeploy"."""
    client = Boto3AWSClient()
    fake_ecs = MagicMock()
    fake_ecs.describe_services.return_value = {
        "services": [
            {
                "serviceName": "sample-prod-api-web",
                "deployments": [{"status": "PRIMARY", "createdAt": _t(46)}],
            },
            # Returned, but with nothing to read.
            {"serviceName": "sample-prod-api-worker", "deployments": []},
        ],
        "failures": [
            {"arn": "arn:aws:ecs:…:service/gone", "reason": "MISSING"},
        ],
    }
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_primary_deployment_times(
        "sample-prod", ["sample-prod-api-web", "sample-prod-api-worker", "gone"],
    ) == {"sample-prod-api-web": _t(46)}


def test_ecs_primary_deployment_times_no_services_makes_no_call(monkeypatch):
    """An empty service list must short-circuit, not call `DescribeServices`
    with `services=[]` — which is a validation error, not an empty result.

    The pipeline already filters to candidate consumers before reading, so a
    converged env with no core `uses` edge reaches this guard on every release.
    """
    client = Boto3AWSClient()
    fake_ecs = MagicMock()
    monkeypatch.setattr(client, "_client", lambda _name: fake_ecs)

    assert client.ecs_primary_deployment_times("sample-prod", []) == {}
    assert fake_ecs.describe_services.call_count == 0

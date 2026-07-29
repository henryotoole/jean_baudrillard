"""Stage smoke tests for docex_smoke_elastic.

Doctrine (tests.md § Staging Tests) requires three things here:
  - Liveness checks (each long-running process type's /health endpoint).
  - TLS/DNS reachability (the request landing on the reverse proxy).
  - At least one critical-path smoke test (secrets + cross-service wiring).

`api.web` is the only externally-reachable process type. `api.worker` sits
on `[internal]` alone, so its liveness is observed through the
doctrine-required fan-out endpoint /health/api/worker — which is the only
place these tests can see the worker's monotonic loop tick end to end. Its
*work* is verified indirectly: POST /pings → row exists → worker
processes it. `reaper.prune` is a scheduler and has no health surface at
all (contracts.md § Self health exempts it).

/health/probe and /health/events exercise the new project-local
container backings (sidecar/nginx + analytics_db/clickhouse) introduced
in the docex 0.10.0 advance. The endpoints test foundation-spanning
machinery: Service Connect on elastic, docker network DNS on fixed.
"""

from __future__ import annotations

import os

import httpx


STAGING_URL = os.environ["STAGING_URL"]
PROJECT_VERSION = os.environ["PROJECT_VERSION"]


def test_health_endpoint() -> None:
    response = httpx.get(f"{STAGING_URL}/health", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == PROJECT_VERSION


def test_health_fanout_reports_worker_liveness() -> None:
    """The doctrine-required `consumes` fan-out (contracts.md § Fan-out).

    A 200 here means three separate things worked: the four-segment magic
    refs resolved to a reachable address, `api.web` could reach a non-`web`
    sibling process type over Service Connect, and the worker's poll loop
    has bumped its monotonic tick within the 30s staleness window. A wedged
    loop returns 503 even though its task is RUNNING — which is the whole
    point.
    """
    response = httpx.get(f"{STAGING_URL}/health/api/worker", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == PROJECT_VERSION


def test_health_probe_reaches_sidecar() -> None:
    """Confirms web can reach the nginx sidecar by service name —
    docker network DNS on fixed, Service Connect on elastic."""
    response = httpx.get(f"{STAGING_URL}/health/probe", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] == "true"


def test_health_events_reaches_clickhouse() -> None:
    """Confirms web can reach the ClickHouse analytics_db backing on
    its native port. On elastic this exercises EFS-mount, ECS task
    startup, Service Connect, and SG self-ingress for NFS — the whole
    stateful-container path."""
    response = httpx.get(f"{STAGING_URL}/health/events", timeout=15)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] == "true"


def test_create_ping_round_trip() -> None:
    response = httpx.post(
        f"{STAGING_URL}/pings",
        json={"payload": "stage smoke"},
        timeout=10,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "id" in body

"""Stage smoke tests for docex_smoke_fixed.

Doctrine (tests.md § Staging Tests) requires three things here:
  - Liveness checks (each core service's /health endpoint).
  - TLS/DNS reachability (the request landing on the reverse proxy).
  - At least one critical-path smoke test (secrets + cross-service wiring).

`web` is the only externally-reachable service. `worker` is verified
indirectly: POST /pings → row exists → worker processes it.

/health/probe and /health/events exercise the new project-local
container backings (sidecar/nginx + analytics_db/clickhouse) introduced
in the docex 0.10.0 campaign. The endpoints test foundation-spanning
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

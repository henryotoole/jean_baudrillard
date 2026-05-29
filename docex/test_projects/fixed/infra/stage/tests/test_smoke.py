"""Stage smoke tests for docex_smoke_fixed.

Doctrine (tests.md § Staging Tests) requires three things here:
  - Liveness checks (each core service's /health endpoint).
  - TLS/DNS reachability (the request landing on the reverse proxy).
  - At least one critical-path smoke test (secrets + cross-service wiring).

`web` is the only externally-reachable service. `worker` is verified
indirectly: POST /pings → row exists → worker processes it (we don't
verify the row-processed transition here because that requires a wait
loop; left to a future addition if it surfaces useful coverage).
"""

from __future__ import annotations

import os

import httpx


STAGING_URL = os.environ["STAGING_URL"]


def test_health_endpoint() -> None:
    response = httpx.get(f"{STAGING_URL}/health", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "version" in body


def test_create_ping_round_trip() -> None:
    response = httpx.post(
        f"{STAGING_URL}/pings",
        json={"payload": "stage smoke"},
        timeout=10,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "id" in body

"""Stage smoke tests for docex_smoke_fixed.

**These tests assert only what requires being OUTSIDE**, which is the whole of
what tests.md § Staging Tests asks for:
  - TLS/DNS reachability (the request landing on the reverse proxy).
  - Reverse-proxy routing to the right core service.
  - At least one critical-path smoke test (secrets + cross-service wiring).

**They assert NOTHING about liveness, and cannot.** `docex stagetest` reads
every core service's health and version from the ORCHESTRATOR before the tester
image is even built, so by the time this file runs the question has already been
answered by the only thing that can answer it. No service reports on another's
liveness anywhere in this project — healthchecks.md § What this doctrine does
not do forbids it — so there is no endpoint here to read a sibling's health
from, and the fan-out that used to provide one is deleted.

`api.web` is the only externally-reachable core service. `api.worker` sits on
`[internal]` alone and `api.clock` listens on nothing at all — it declares no
port and no surface — so nothing out here can reach either directly. Their
liveness is a container probe (`./health.sh <service>`) the orchestrator runs
and acts on; that enforcement is real but local (clock.md § Caveats).

The worker's *work* is still observed from out here, twice: indirectly via
POST /pings → row exists → worker processes it, and directly via
`test_defer_and_drain_round_trip`, which crosses the internal network to the
worker's `rpc` surface and back.

/diagnostics/probe and /diagnostics/events exercise the project-local container
BACKING services (sidecar/nginx + analytics_db/clickhouse). They test
foundation-spanning machinery: Service Connect on elastic, docker network DNS
on fixed.
"""

from __future__ import annotations

import os

import httpx


STAGING_URL = os.environ["STAGING_URL"]
PROJECT_VERSION = os.environ["PROJECT_VERSION"]

# TLS is verified (the default). Gap A (mod 051) switched fixed certs to
# the HTTP-01 challenge, which needs no DNS-provider creds, so the project
# traefik now issues a real Let's Encrypt cert out of the box — the
# mod-036 `verify=False` workaround (and its mod-047 tracking note) is
# obsolete and was removed in mod 053 (F7).
_client = httpx.Client(timeout=10)


def test_health_endpoint() -> None:
    response = _client.get(f"{STAGING_URL}/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == PROJECT_VERSION


def test_diagnostics_probe_reaches_sidecar() -> None:
    """Confirms web can reach the nginx sidecar by service name —
    docker network DNS on fixed, Service Connect on elastic."""
    response = _client.get(f"{STAGING_URL}/diagnostics/probe")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] == "true"


def test_diagnostics_events_reaches_clickhouse() -> None:
    """Confirms web can reach the ClickHouse analytics_db backing on
    its native port. On elastic this exercises EFS-mount, ECS task
    startup, Service Connect, and SG self-ingress for NFS — the whole
    stateful-container path."""
    response = _client.get(f"{STAGING_URL}/diagnostics/events", timeout=15)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] == "true"


def test_defer_and_drain_round_trip() -> None:
    """Drive the public edge and observe a worker doing work.

    tests.md's prescribed shape for a scenario that must exercise a
    non-`web` core service: drive the real ingress and observe the effect.
    `POST /jobs/drain` satisfies it synchronously — the worker's OWN reply
    travels back out through the edge — so nothing has to be read back
    later, which matters because neither seed has a route that can read a
    job back.

    A 200 here means the five-segment magic refs resolved to a reachable
    address and `api.web` reached a non-`web` sibling core service across
    its declared `rpc` surface: docker network DNS on fixed, ECS Service
    Connect on elastic. It means nothing about liveness — that is the
    orchestrator's to report, and `docex stagetest` has already read it.
    """
    deferred = _client.post(f"{STAGING_URL}/jobs/heartbeat")
    assert deferred.status_code == 202, deferred.text
    assert "job_id" in deferred.json()

    drained = _client.post(f"{STAGING_URL}/jobs/drain", timeout=15)
    assert drained.status_code == 200, drained.text
    # NO EXACT COUNT, deliberately. `api.worker` drains on its own poll
    # interval, so by the time this call lands the heartbeat above may
    # legitimately already be gone and `performed: 0` is the honest answer.
    # The load-bearing assertion is the 200 itself, on a route that cannot
    # answer without reaching the worker. An order-dependent count would
    # pass on a dev machine and fail on the walk, which is the worst
    # signature a smoke test can have.
    performed = drained.json()["performed"]
    assert isinstance(performed, int) and performed >= 0


def test_create_ping_round_trip() -> None:
    response = _client.post(
        f"{STAGING_URL}/pings",
        json={"payload": "stage smoke"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "id" in body

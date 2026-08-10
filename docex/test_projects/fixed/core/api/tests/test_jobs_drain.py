"""Tests for the drain boundary: `api.web` asking `api.worker` to drain.

**Both tests are stub-backed on purpose, and the reason is the `test` env's
shape rather than convenience.** `docex test` brings the whole stack up before
running `test.sh`, so while this suite runs there is a live `api.clock`
deferring jobs onto the `jobs` table and a live `api.worker` claiming and
performing them. Any assertion whose truth requires "we were the one who
drained it" is wrong by construction against that database
(test_projects.md § The test env has no sole actor). Stubs remove the third
party entirely, which is what lets the assertions below use `==`.

Neither test reaches the network. The gateway that would — `GwyJobRunnerHttp`
— has no reachable worker from inside the `test` container, and the live edge
is covered from outside by the stage smoke test's
`test_defer_and_drain_round_trip`.

Follows `test_jobs_alogic.py`'s stub idiom.
"""

from __future__ import annotations

import sys


sys.path.insert(0, "/service/dist")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from hex.jobs.adapters.driving.cont_job_runner_http import ContJobRunnerHttp  # noqa: E402
from hex.jobs.alogic.job_drain_service import JobDrainService  # noqa: E402


class _StubGateway:
    """Stub GwyJobRunner — the driven port `JobDrainService` holds.

    Records calls; reaches no network. `api.worker` is unreachable from the
    `test` container, which is exactly the collaborator a driven port exists
    to let a test replace.
    """

    def __init__(self, performed: int = 0) -> None:
        self.calls = 0
        self._performed = performed

    def drain_now(self) -> int:
        self.calls += 1
        return self._performed


class _StubRunner:
    """Stub ContJobRunner — the driving port `ContJobRunnerHttp` translates onto."""

    def __init__(self, performed: int = 0, raises: bool = False) -> None:
        self.calls = 0
        self._performed = performed
        self._raises = raises

    def run_once(self) -> int:
        self.calls += 1
        if self._raises:
            raise RuntimeError("queue exploded")
        return self._performed


def _client(runner: _StubRunner) -> TestClient:
    app = FastAPI()
    app.include_router(ContJobRunnerHttp(service=runner).router)
    return TestClient(app)


def test_drain_service_returns_the_gateways_count_and_calls_it_once() -> None:
    # The alogic tier. `JobDrainService` is a one-line delegation, and this is
    # the assertion that keeps it one line: the count is passed through
    # untouched and the gateway is reached exactly once. A future edit that
    # retried, cached, or reinterpreted `0` breaks this test, which is the
    # point of writing it against a thin service.
    gateway = _StubGateway(performed=4)
    service = JobDrainService(gateway=gateway)

    assert service.drain_now() == 4
    assert gateway.calls == 1

    # `performed: 0` is a SUCCESS and must survive the layer unchanged —
    # the worker's own loop drains on its interval, so an empty queue is the
    # ordinary outcome of asking at the wrong moment.
    empty = _StubGateway(performed=0)
    assert JobDrainService(gateway=empty).drain_now() == 0
    assert empty.calls == 1


def test_runner_http_translates_a_drain_request_into_a_port_call() -> None:
    # A driving-adapter test in the doctrine's sense: it verifies TRANSLATION
    # — request in, port call, response out — and not downstream behaviour
    # (hex_overview.md § Tests). The port is stubbed, so nothing here touches
    # a queue, and what is under test is the wiring of route, status code, and
    # response body.
    runner = _StubRunner(performed=3)

    response = _client(runner).post("/drain")

    assert response.status_code == 200, response.text
    assert response.json() == {"performed": 3}
    assert runner.calls == 1


def test_runner_http_translates_a_failed_drain_into_503() -> None:
    # The other half of translation: an exception out of the port must become
    # a 503 rather than a 500 traceback, mirroring `cont_jobs_http.py`'s
    # existing idiom. 503 means the batch could not be claimed at all and
    # nothing was performed — distinct from a successful `{"performed": 0}`.
    response = _client(_StubRunner(raises=True)).post("/drain")

    assert response.status_code == 503, response.text

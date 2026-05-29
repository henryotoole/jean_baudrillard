"""Smoke tests for `web`.

These run in the `test` stage container against the live test-env stack
(real postgres). They verify the wiring docex composes works end-to-end.
"""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient


sys.path.insert(0, "/service/dist")

from root import build_app  # noqa: E402  — must come after sys.path mutation


def test_health_reports_version() -> None:
    app = build_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert "version" in response.json()


def test_post_pings_persists_a_row() -> None:
    app = build_app()
    client = TestClient(app)
    response = client.post("/pings", json={"payload": "hello"})
    assert response.status_code == 201
    assert "id" in response.json()

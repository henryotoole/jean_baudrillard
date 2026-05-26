"""Stage smoke test for the sample fixture.

Runs against ``$STAGING_URL`` (passed in by ``docex stagetest``);
asserts the deployed api service answers its /health endpoint with
200. The single check is enough to confirm: (a) the staging deploy
got far enough that traefik routes traffic, and (b) the api
container started and is responsive.
"""

from __future__ import annotations

import os

import httpx


def test_health() -> None:
    url = os.environ["STAGING_URL"].rstrip("/")
    res = httpx.get(f"{url}/health", timeout=10.0)
    assert res.status_code == 200, (
        f"expected 200 from {url}/health, got {res.status_code}: {res.text!r}"
    )

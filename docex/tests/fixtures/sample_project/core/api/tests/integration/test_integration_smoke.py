"""One passing integration-tier smoke test. The point of this fixture is
to exercise the test_integration.sh shim, not to test the app itself."""

from __future__ import annotations


def test_passes() -> None:
    assert True

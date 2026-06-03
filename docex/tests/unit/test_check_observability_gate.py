"""Unit tests for the ``observability_backend_reachable`` gate.

Per mod 019: ``docex check`` probes ``observability_backend_url`` before
allowing a merge. The gate's contract:

- Any HTTP response (2xx/3xx/4xx, via ``HTTPError``) passes — host is up.
- DNS resolution failure, TLS handshake failure, connection refusal, or
  timeout fails the gate.

Tests mock ``urllib.request.urlopen`` so they never touch the network.
"""

from __future__ import annotations

import socket
import urllib.error
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from docex.pipeline.check import (
    CheckReport,
    _gate_observability_backend_url_reachable,
)


@dataclass
class _StubInfra:
    """Minimal stand-in for ``CICLDocument`` exposing just the field the
    gate reads. The real ``CICLDocument`` validates URL shape at
    construction time and isn't worth the ceremony in a unit test."""

    observability_backend_url: str


@dataclass
class _StubCtx:
    """Minimal ``ProjectContext`` for the gate — it only reads ``infra``."""

    infra: _StubInfra | None


def _ctx(url: str = "https://hyperdx.example.com") -> _StubCtx:
    return _StubCtx(infra=_StubInfra(observability_backend_url=url))


def _find_result(report: CheckReport, name: str):
    """Return the single result with the given name, or fail the test."""
    matches = [r for r in report.results if r.name == name]
    assert len(matches) == 1, (
        f"expected exactly one {name!r} result, got {matches!r}"
    )
    return matches[0]


def test_gate_passes_on_200():
    """A successful 2xx response means the host is up — gate passes."""
    report = CheckReport()
    fake_response = MagicMock()
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)
    with patch(
        "docex.pipeline.check.urllib.request.urlopen",
        return_value=fake_response,
    ):
        _gate_observability_backend_url_reachable(_ctx(), report)
    result = _find_result(report, "observability_backend_reachable")
    assert result.passed is True
    assert "reachable" in result.detail


def test_gate_passes_on_4xx_via_HTTPError():
    """A 401 means the host responded (just refused auth) — gate passes."""
    report = CheckReport()
    exc = urllib.error.HTTPError(
        "https://hyperdx.example.com", 401, "Unauthorized", hdrs={}, fp=None
    )
    with patch(
        "docex.pipeline.check.urllib.request.urlopen", side_effect=exc
    ):
        _gate_observability_backend_url_reachable(_ctx(), report)
    result = _find_result(report, "observability_backend_reachable")
    assert result.passed is True
    assert "HTTP 401" in result.detail


def test_gate_passes_on_404_via_HTTPError():
    """A 404 also means the host responded — gate passes."""
    report = CheckReport()
    exc = urllib.error.HTTPError(
        "https://hyperdx.example.com", 404, "Not Found", hdrs={}, fp=None
    )
    with patch(
        "docex.pipeline.check.urllib.request.urlopen", side_effect=exc
    ):
        _gate_observability_backend_url_reachable(_ctx(), report)
    result = _find_result(report, "observability_backend_reachable")
    assert result.passed is True
    assert "HTTP 404" in result.detail


def test_gate_fails_on_URLError():
    """DNS failure / TLS handshake failure surfaces as URLError — fail."""
    report = CheckReport()
    exc = urllib.error.URLError("Name or service not known")
    url = "https://hyperdx.example.com"
    with patch(
        "docex.pipeline.check.urllib.request.urlopen", side_effect=exc
    ):
        _gate_observability_backend_url_reachable(_ctx(url), report)
    result = _find_result(report, "observability_backend_reachable")
    assert result.passed is False
    assert url in result.detail


def test_gate_fails_on_timeout():
    """A 10s timeout fails the gate — host is unresponsive."""
    report = CheckReport()
    with patch(
        "docex.pipeline.check.urllib.request.urlopen",
        side_effect=TimeoutError("timed out"),
    ):
        _gate_observability_backend_url_reachable(_ctx(), report)
    result = _find_result(report, "observability_backend_reachable")
    assert result.passed is False
    assert "unreachable" in result.detail


def test_gate_fails_on_socket_timeout():
    """socket.timeout is the legacy exception class — must also fail.

    On Python 3.10+ ``socket.timeout`` is aliased to ``TimeoutError`` but
    the gate's ``except`` clause names both defensively.
    """
    report = CheckReport()
    with patch(
        "docex.pipeline.check.urllib.request.urlopen",
        side_effect=socket.timeout("timed out"),
    ):
        _gate_observability_backend_url_reachable(_ctx(), report)
    result = _find_result(report, "observability_backend_reachable")
    assert result.passed is False
    assert "unreachable" in result.detail


def test_gate_skipped_without_infra():
    """No infra.yml → gate passes (with a "skipped" detail) and never
    issues a network call."""
    report = CheckReport()
    ctx = _StubCtx(infra=None)
    with patch(
        "docex.pipeline.check.urllib.request.urlopen"
    ) as mock_urlopen:
        _gate_observability_backend_url_reachable(ctx, report)
    result = _find_result(report, "observability_backend_reachable")
    assert result.passed is True
    assert result.detail == "no infra.yml — skipped"
    mock_urlopen.assert_not_called()


def test_gate_uses_10s_timeout():
    """The gate must pass ``timeout=10`` to ``urlopen`` — short enough to
    fail an unreachable host quickly, long enough for slow TLS handshakes.
    """
    report = CheckReport()
    fake_response = MagicMock()
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)
    with patch(
        "docex.pipeline.check.urllib.request.urlopen",
        return_value=fake_response,
    ) as mock_urlopen:
        _gate_observability_backend_url_reachable(_ctx(), report)
    # Verify timeout=10 was passed.
    _args, kwargs = mock_urlopen.call_args
    assert kwargs.get("timeout") == 10

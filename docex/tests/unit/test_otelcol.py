"""Tests for the OTel Collector sidecar config rendering (mod 018).

Covers the exporter switch by env (debug for dev/test, otlphttp for
stage/prod), the pipeline references, the health-check extension, and
determinism.
"""

from __future__ import annotations

import pytest

from docex.emit.otelcol import render_otelcol_config


# ---------------------------------------------------------------------------
# Exporter selection by env
# ---------------------------------------------------------------------------


def test_dev_config_uses_debug_exporter():
    """dev → debug exporter writing to sidecar stdout."""
    cfg = render_otelcol_config("dev")
    assert "debug:" in cfg
    assert "verbosity: detailed" in cfg
    assert "otlphttp:" not in cfg


def test_test_config_uses_debug_exporter():
    """test → debug exporter (same as dev)."""
    cfg = render_otelcol_config("test")
    assert "debug:" in cfg
    assert "verbosity: detailed" in cfg
    assert "otlphttp:" not in cfg


def test_stage_config_uses_otlphttp():
    """stage → otlphttp targeting the observability backend with API
    key auth. Both substitutions use otelcol's `${env:...}` form
    verbatim — they are *not* compose or docex refs."""
    cfg = render_otelcol_config("stage")
    assert "otlphttp:" in cfg
    assert "endpoint: ${env:OBSERVABILITY_BACKEND_URL}" in cfg
    assert "authorization: ${env:TELEMETRY_API_KEY}" in cfg
    assert "debug:" not in cfg


def test_prod_config_uses_otlphttp():
    """prod → otlphttp (same as stage)."""
    cfg = render_otelcol_config("prod")
    assert "otlphttp:" in cfg
    assert "endpoint: ${env:OBSERVABILITY_BACKEND_URL}" in cfg
    assert "authorization: ${env:TELEMETRY_API_KEY}" in cfg
    assert "debug:" not in cfg


# ---------------------------------------------------------------------------
# Pipeline structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env,expected_exporter",
    [
        ("dev", "debug"),
        ("test", "debug"),
        ("stage", "otlphttp"),
        ("prod", "otlphttp"),
    ],
)
def test_pipelines_reference_chosen_exporter(env: str, expected_exporter: str):
    """All three pipelines (traces, metrics, logs) must reference the
    same exporter for the env."""
    cfg = render_otelcol_config(env)
    for signal in ("traces", "metrics", "logs"):
        # The pipeline line contains "exporters: [<chosen>]".
        assert f"exporters: [{expected_exporter}]" in cfg, (
            f"missing exporter {expected_exporter!r} reference for "
            f"signal {signal!r} in env {env!r}"
        )
        # And the pipeline line itself must appear (basic shape).
        assert f"{signal}:" in cfg


@pytest.mark.parametrize("env", ["dev", "test", "stage", "prod"])
def test_health_check_extension_on_13133(env: str):
    """Both env classes embed health_check on 127.0.0.1:13133. The
    sidecar's compose/HCL healthcheck probes this endpoint."""
    cfg = render_otelcol_config(env)
    assert "health_check:" in cfg
    assert "endpoint: 127.0.0.1:13133" in cfg


@pytest.mark.parametrize("env", ["dev", "test", "stage", "prod"])
def test_receiver_endpoint_on_4318(env: str):
    """Every env's YAML has the OTLP HTTP receiver on 127.0.0.1:4318 —
    matches the OTEL_EXPORTER_OTLP_ENDPOINT injected on every core
    service (mod 017)."""
    cfg = render_otelcol_config(env)
    assert "receivers:" in cfg
    assert "otlp:" in cfg
    assert "endpoint: 127.0.0.1:4318" in cfg


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test", "stage", "prod"])
def test_config_is_deterministic(env: str):
    """Re-rendering with identical input produces byte-identical output."""
    a = render_otelcol_config(env)
    b = render_otelcol_config(env)
    assert a == b

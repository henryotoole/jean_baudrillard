"""Tests for the sidecar's task-level resource accounting on elastic (mod 018).

Covers the overhead arithmetic (0.1 vCPU / 128 MiB added to the
core's request), Fargate-tier rounding, the stdout rounding notice
when overhead bumps a service into a higher tier, and the absence of
this overhead on backing services and per-container fields.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.cicl.compile import _resources_to_elastic, run_compile
from docex.cicl.model import Resources
from docex.context import load_project_context


_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_project_elastic"
)


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest


def _stage_hcl(root: Path) -> str:
    return (root / "infra" / "output" / "stage" / "main.tf").read_text()


# ---------------------------------------------------------------------------
# Sidecar overhead arithmetic.
# ---------------------------------------------------------------------------


def test_core_service_resources_include_sidecar_overhead_cpu():
    """A core service with ``cpu: 1.0, memory: 2GB`` is requesting 1024
    Fargate units bare. With sidecar overhead (+0.1 vCPU = 102 units),
    the request becomes 1126 units which rounds up to the next Fargate
    CPU bucket: 2048.
    """
    res = Resources(cpu=1.0, memory="2GB")
    out = _resources_to_elastic(res, service_name="api", is_core=True)
    assert out["cpu"] == "2048"


def test_core_service_resources_include_sidecar_overhead_memory():
    """For ``cpu: 1.0, memory: 2GB`` core service + sidecar (128 MiB),
    once CPU is rounded up to 2048 (see above), the smallest allowed
    memory is 4096 MiB (the lowest valid for cpu=2048).
    """
    res = Resources(cpu=1.0, memory="2GB")
    out = _resources_to_elastic(res, service_name="api", is_core=True)
    assert out["memory"] == "4096"


def test_backing_service_resources_no_sidecar_overhead():
    """When ``is_core`` is False (e.g. a container-backing service that
    routes through ``task_definition``), no overhead is added. Same
    inputs that produced (2048, 4096) for a core service produce
    (1024, 2048) here — matching the pre-mod-018 behavior.
    """
    res = Resources(cpu=1.0, memory="2GB")
    out = _resources_to_elastic(res, service_name="appdb", is_core=False)
    assert out["cpu"] == "1024"
    assert out["memory"] == "2048"


# ---------------------------------------------------------------------------
# Stdout rounding notice.
# ---------------------------------------------------------------------------


def test_rounding_notice_printed_when_tier_bumps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """When sidecar overhead bumps the request into a higher Fargate
    tier than the bare-core request alone would, ``docex compile``
    prints a one-line notice to stdout naming the service. The sample
    elastic fixture's `api` service has cpu=1.0 / mem=2GB which is a
    classic tier-bump case.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    captured = capsys.readouterr().out
    assert "note: core service 'api'" in captured
    assert "sidecar overhead pushed task to next Fargate tier" in captured


def test_rounding_notice_not_printed_when_no_bump(
    capsys: pytest.CaptureFixture[str],
):
    """A core service whose bare resources already have headroom for
    the sidecar's overhead — both CPU and memory stay in the same
    Fargate tier — does NOT trigger the notice.

    cpu=0.15 → 154 units (tier 256); with sidecar +102 = 256 units
    (still tier 256). memory=350MB → 334 MiB (tier 512); with sidecar
    +128 = 462 MiB (still tier 512). Both unchanged → no notice.
    """
    capsys.readouterr()  # clear prior stdout
    res = Resources(cpu=0.15, memory="350MB")
    _ = _resources_to_elastic(res, service_name="tinyapi", is_core=True)
    captured = capsys.readouterr().out
    assert "tinyapi" not in captured
    assert "sidecar overhead pushed task to next Fargate tier" not in captured


# ---------------------------------------------------------------------------
# Per-container resources unaffected.
# ---------------------------------------------------------------------------


def test_core_container_runtime_resources_unaffected(tmp_path: Path):
    """Per-container fields: Fargate auto-divides task resources between
    containers; we don't set per-container `cpu`/`memory` on the core
    container. The sidecar carries explicit `cpu: 102, memory: 128`;
    the core container has no `cpu`/`memory` field of its own.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    # Slice the api task def.
    marker = 'resource "aws_ecs_task_definition" "api" {'
    idx = hcl.index(marker)
    rest = hcl[idx:]
    end = rest.index("\n}\n")
    api_td = rest[: end + 2]

    # The api task def's container_definitions array has two dicts.
    # The sidecar dict contains the unique marker
    # `command = ["--config=env:OTEL_CONFIG_YAML"]`; everything in
    # container_definitions BEFORE that marker is the core's dict.
    cd_idx = api_td.index("container_definitions")
    after_cd = api_td[cd_idx:]
    sidecar_marker = "--config=env:OTEL_CONFIG_YAML"
    sidecar_idx = after_cd.index(sidecar_marker)
    core_portion = after_cd[:sidecar_idx]

    # The core's portion must NOT carry per-container cpu/memory values
    # (the sidecar's `cpu = 102` / `memory = 128` appear only after the
    # marker, in the sidecar portion).
    assert "cpu = 102" not in core_portion, core_portion
    assert "memory = 128" not in core_portion, core_portion

    # Task-level cpu / memory still appears outside container_definitions,
    # carrying the sidecar-inclusive totals.
    pre = api_td[:cd_idx]
    assert 'cpu                      = "2048"' in pre
    assert 'memory                   = "4096"' in pre

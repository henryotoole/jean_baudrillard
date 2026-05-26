"""Tests for the Resources translation step."""

from __future__ import annotations

import pytest

from docex.cicl.compile import (
    _disk_to_gib,
    _memory_to_mib,
    _resources_to_elastic,
    _resources_to_fixed,
)
from docex.cicl.model import GPUSpec, Resources


def test_memory_to_mib_gb():
    # 2 GB decimal = 2,000,000,000 bytes ≈ 1907 MiB.
    assert _memory_to_mib("2GB") == 1907


def test_memory_to_mib_mb():
    assert _memory_to_mib("500MB") == 477


def test_disk_to_gib_rounds_up():
    # 20 GB decimal = 20,000,000,000 bytes ≈ 18.6 GiB → 19 GiB rounded up.
    assert _disk_to_gib("20GB") == 19


def test_fixed_resources_basic():
    res = Resources(cpu=1.5, memory="2GB")
    out = _resources_to_fixed(res)
    assert out["deploy"]["resources"]["limits"]["cpus"] == "1.5"
    assert out["deploy"]["resources"]["limits"]["memory"] == "2GB"
    assert "tmpfs" not in out


def test_fixed_resources_with_disk_and_gpu():
    res = Resources(cpu=2.0, memory="4GB", disk="10GB", gpu=GPUSpec(count=1))
    out = _resources_to_fixed(res)
    # docker tmpfs `size=` rejects `GB`/`MB`; the emitter translates
    # to lowercase short-form (Phase 3 Step 1).
    assert out["tmpfs"] == ["/tmp:size=10g"]
    devices = out["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["driver"] == "nvidia"
    assert devices[0]["count"] == 1


def test_elastic_resources_basic():
    # Phase 4: ``_resources_to_elastic`` runs the requested CPU/memory
    # through Fargate's allow-list. 1 vCPU + 2 GB decimal lands at
    # (1024 units, 2048 MiB) — the smallest valid (cpu=1024) pair >=
    # 1907 MiB. Disk 30 GB decimal -> 28 GiB binary, well above the
    # 21 GiB floor.
    res = Resources(cpu=1.0, memory="2GB", disk="30GB")
    out = _resources_to_elastic(res, service_name="api")
    assert out["cpu"] == "1024"
    assert out["memory"] == "2048"
    assert out["ephemeral_storage"]["size_in_gib"] == 28


def test_elastic_resources_disk_below_floor_raises():
    """``disk:`` < 21 GiB on Fargate is a hard compile-time error."""
    import pytest
    from docex.errors import ValidationError

    res = Resources(cpu=1.0, memory="2GB", disk="20GB")
    with pytest.raises(ValidationError) as exc:
        _resources_to_elastic(res, service_name="api")
    assert "rule_fargate_disk_below_floor" in str(exc.value)


def test_elastic_resources_disk_omitted_omits_ephemeral_storage():
    """When ``disk:`` is absent, accept Fargate's 21 GiB default by
    omitting ``ephemeral_storage`` from the task definition."""
    res = Resources(cpu=1.0, memory="2GB", disk=None)
    out = _resources_to_elastic(res, service_name="api")
    assert "ephemeral_storage" not in out


def test_elastic_resources_invalid_fargate_pair_raises():
    """A pair outside Fargate's bucketing fails loudly."""
    import pytest
    from docex.errors import ValidationError

    # 16 vCPU + 200 GB memory is well above Fargate's 122,880 MiB max.
    res = Resources(cpu=16.0, memory="200GB")
    with pytest.raises(ValidationError) as exc:
        _resources_to_elastic(res, service_name="api")
    assert "rule_fargate_pair_invalid" in str(exc.value)

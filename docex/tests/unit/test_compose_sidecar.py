"""Tests for the paired OTel Collector sidecar in compose emission (mod 018).

Compiles a fixture project and inspects the emitted docker-compose.yml
for the sidecar service, its network_mode pairing with the core
service, the top-level configs block, the env defaults, and the health
check.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

import docex
from docex.cicl.compile import run_compile
from docex.context import load_project_context


_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_project"


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest


def _compose_doc(root: Path, env: str) -> dict:
    path = root / "infra" / "output" / env / "docker-compose.yml"
    return yaml.safe_load(path.read_text())


def _sidecar_names(services: dict) -> list[str]:
    return [k for k in services if k.endswith("_otelcol")]


def test_sidecar_emitted_per_core_service(tmp_path: Path):
    """One sidecar per core service, none for backing services."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecars = _sidecar_names(services)
    # The fixture has one core service (`api`) and one backing (`appdb`).
    assert len(sidecars) == 1, sorted(services)
    assert sidecars[0].endswith("_api_otelcol")
    # No sidecar for the backing appdb.
    assert not any(k.endswith("_appdb_otelcol") for k in services)


def test_sidecar_network_mode_pairs_with_core(tmp_path: Path):
    """Each sidecar's network_mode points at the paired core's global name."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    api_global = next(k for k in services if k.endswith("_api") and "otelcol" not in k)
    sidecar = next(services[k] for k in services if k.endswith("_api_otelcol"))
    assert sidecar["network_mode"] == f"service:{api_global}"


def test_sidecar_has_no_networks_list(tmp_path: Path):
    """`network_mode` is mutually exclusive with `networks:` per docker-compose."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecar = next(services[k] for k in services if k.endswith("_otelcol"))
    assert "networks" not in sidecar


def test_sidecar_uses_pinned_image_constant(tmp_path: Path):
    """Sidecar `image` is the pinned `docex.OTEL_COLLECTOR_IMAGE` constant."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecar = next(services[k] for k in services if k.endswith("_otelcol"))
    assert sidecar["image"] == docex.OTEL_COLLECTOR_IMAGE


def test_compose_has_top_level_configs_block(tmp_path: Path):
    """A top-level `configs:` map declares `otelcol_config` with the
    rendered otelcol YAML embedded inline via `content:`. Mod 021 moved
    from file-mount to inline content so the compose file is self-
    contained and the otelcol config arrives on the deploy host with
    everything else compose needs."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    assert "configs" in doc
    cfg = doc["configs"]
    assert "otelcol_config" in cfg
    content = cfg["otelcol_config"]["content"]
    # The dev config carries the OTLP receiver block and the debug exporter
    # (dev/test use `debug`; stage/prod use `otlphttp`).
    assert "receivers:" in content
    assert "127.0.0.1:4318" in content
    assert "debug:" in content
    # No separate otelcol-config.yaml file is written anymore (mod 021).
    sidecar_yaml = root / "infra" / "output" / "dev" / "otelcol-config.yaml"
    assert not sidecar_yaml.exists()


def test_compose_configs_content_escapes_dollar_for_stage(tmp_path: Path):
    """Stage/prod otelcol config embeds `${env:...}` references. Compose
    interpolates ${VAR} inside `configs.content` too, so `$` must be
    doubled to `$$` in the emitted compose YAML — compose then passes
    a single literal `$` to the sidecar at parse time. Mod 022."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "stage")
    content = doc["configs"]["otelcol_config"]["content"]
    # The compose file has the doubled form; the test reads the in-memory
    # dict which preserves `$$` (PyYAML round-trips literal scalars).
    assert "$${env:OBSERVABILITY_BACKEND_URL}" in content
    assert "$${env:TELEMETRY_API_KEY}" in content
    # No naked `${env:...}` references remain (stripping `$$` from the
    # content and looking for `${env:` should find nothing).
    assert "${env:OBSERVABILITY_BACKEND_URL}" not in content.replace("$$", "")
    assert "${env:TELEMETRY_API_KEY}" not in content.replace("$$", "")


def test_sidecar_environment_uses_default_form(tmp_path: Path):
    """`OBSERVABILITY_BACKEND_URL` is emitted as a literal from
    `infra.yml`'s top-level field (it's config, not a secret). Mod 023.
    `TELEMETRY_API_KEY` stays as `${TELEMETRY_API_KEY:-}` so compose
    interpolates it from `.env` (it IS a secret); the `:-` keeps
    dev/test compose green without the operator-supplied key."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecar = next(services[k] for k in services if k.endswith("_otelcol"))
    env = sidecar["environment"]
    assert env["OBSERVABILITY_BACKEND_URL"] == "https://hyperdx.luxrnd.tech"
    assert env["TELEMETRY_API_KEY"] == "${TELEMETRY_API_KEY:-}"


def test_sidecar_has_no_healthcheck(tmp_path: Path):
    """Mod 024: the otel/opentelemetry-collector image is built FROM
    scratch and carries no probe tool. The doctrine-prescribed
    `wget --spider ...` could never succeed. The sidecar emit block
    drops the healthcheck entirely; otelcol's `health_check` extension
    on 127.0.0.1:13133 remains available for in-band probes from
    inside the shared netns."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecar = next(services[k] for k in services if k.endswith("_otelcol"))
    assert "healthcheck" not in sidecar


def test_sidecar_resource_limits(tmp_path: Path):
    """Sidecar carries the doctrine-fixed 0.1 vCPU / 128 MiB limits."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    doc = _compose_doc(root, "dev")
    services = doc["services"]
    sidecar = next(services[k] for k in services if k.endswith("_otelcol"))
    limits = sidecar["deploy"]["resources"]["limits"]
    assert limits["cpus"] == "0.1"
    assert limits["memory"] == "128M"

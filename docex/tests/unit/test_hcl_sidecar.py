"""Tests for the paired OTel Collector sidecar in HCL (elastic) emission (mod 018).

Compiles the elastic fixture and inspects the emitted main.tf for the
sidecar container definition, dependsOn on core, the OTEL_CONFIG_YAML
env entry, the TELEMETRY_API_KEY secret reference, the health check,
and the absence of a sidecar on the migration task definition and
backing-service task definitions.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import docex
from docex.cicl.compile import run_compile
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


def _slice_task_def(hcl: str, resource_name: str) -> str:
    """Return the substring of HCL for a single ``aws_ecs_task_definition``
    resource (from the opening ``resource "..." "..." {`` to the
    matching closing ``\\n}\\n``).
    """
    marker = f'resource "aws_ecs_task_definition" "{resource_name}" {{'
    idx = hcl.index(marker)
    rest = hcl[idx:]
    end = rest.index("\n}\n")
    return rest[: end + 2]


def test_task_def_has_paired_sidecar_container(tmp_path: Path):
    """`aws_ecs_task_definition.api` carries both `api` and
    `api_otelcol` containers in container_definitions."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    assert 'name = "api"' in api_td
    assert 'name = "api_otelcol"' in api_td


def test_core_container_dependsOn_sidecar_start(tmp_path: Path):
    """Mod 024: core container's `dependsOn` uses condition START
    rather than HEALTHY because the otel/opentelemetry-collector
    image has no probe tool — a HEALTHY condition would block startup
    indefinitely. The OTel SDK's batch queue absorbs the brief window
    between sidecar start and OTLP-listening."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    assert 'containerName = "api_otelcol"' in api_td
    assert 'condition = "START"' in api_td
    assert 'condition = "HEALTHY"' not in api_td


def test_sidecar_is_not_essential(tmp_path: Path):
    """Sidecar `essential: false` so its crash doesn't take down the
    task — telemetry is best-effort.

    The migration task def is `essential: true` for the core only; the
    main task def is `essential: true` for core + `essential: false`
    for the sidecar.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    # In the api task def, both `essential = true` (core) and
    # `essential = false` (sidecar) must appear.
    assert "essential = true" in api_td
    assert "essential = false" in api_td


def test_sidecar_uses_pinned_image_constant(tmp_path: Path):
    """Sidecar's `image` field is the pinned constant from docex.__init__."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    assert docex.OTEL_COLLECTOR_IMAGE in api_td


def test_sidecar_has_OTEL_CONFIG_YAML_env(tmp_path: Path):
    """Sidecar's environment[] carries OTEL_CONFIG_YAML containing the
    rendered config YAML (recognizable by the receivers: block)."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    assert 'name = "OTEL_CONFIG_YAML"' in api_td
    # The literal YAML config is embedded as the value.
    assert "receivers:" in api_td
    assert "127.0.0.1:4318" in api_td
    # Mod 025: newlines must be \\n-escaped (HCL quoted strings can't
    # span lines). The emitted HCL is one line per env var entry; if
    # we see a literal newline inside the OTEL_CONFIG_YAML value the
    # HCL parser would reject the file. Assert the escape is in place.
    assert "\\n" in api_td
    # And the value itself sits on a single line (no real newlines
    # between the surrounding quotes).
    yaml_line = next(
        line for line in api_td.splitlines()
        if "OTEL_CONFIG_YAML" in line and "value" in line
        or (line.lstrip().startswith("value") and "receivers:" in line)
    )
    # Sanity: the yaml_line carries the receivers block on a single line.
    assert "receivers:" in yaml_line


def test_sidecar_has_observability_backend_url_env(tmp_path: Path):
    """Sidecar's environment[] carries OBSERVABILITY_BACKEND_URL with
    the value declared in infra.yml."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    assert 'name = "OBSERVABILITY_BACKEND_URL"' in api_td
    # The fixture's `observability_backend_url` is "https://hyperdx.example.com".
    assert "https://hyperdx.example.com" in api_td


def test_sidecar_has_telemetry_api_key_secret(tmp_path: Path):
    """Sidecar's secrets[] entry references SSM at /<project>/<env>/TELEMETRY_API_KEY."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    assert 'name = "TELEMETRY_API_KEY"' in api_td
    project_name = ctx.project.name
    assert f"parameter/{project_name}/stage/TELEMETRY_API_KEY" in api_td


def test_migration_task_def_has_no_sidecar(tmp_path: Path):
    """Migration task-def for a schema-owning service has only one
    container — `migrate.sh` is one-shot and emits no app-origin signals."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    mig_td = _slice_task_def(hcl, "api_migrate")
    # The container_definitions has the core container only — no sidecar.
    assert 'name = "api"' in mig_td
    assert 'name = "api_otelcol"' not in mig_td


def test_sidecar_has_no_healthcheck(tmp_path: Path):
    """Mod 024: same image-level constraint as on fixed. The
    otel/opentelemetry-collector image has no probe tool, so the
    sidecar container has no `healthCheck` entry. The core container's
    `dependsOn` uses START (asserted separately) to gate startup
    without waiting on an unhealable health check."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    api_td = _slice_task_def(hcl, "api")
    # No healthCheck key anywhere in the api task definition.
    assert "healthCheck" not in api_td
    # No `http://localhost:13133` either — it only appeared inside the
    # healthcheck command before mod 024. (The otelcol config's own
    # `endpoint: 127.0.0.1:13133` is encoded inside the OTEL_CONFIG_YAML
    # value, but that value uses literal double-quotes around its newline
    # payload, so the substring `"127.0.0.1:13133"` shows up there.
    # Search for the healthCheck-specific form instead.)
    assert "wget" not in api_td


def test_backing_service_task_def_has_no_sidecar(tmp_path: Path):
    """Backing-service task defs (RDS, S3, ElastiCache) on elastic don't
    emit task definitions at all — RDS is `aws_db_instance`, etc. For
    completeness, assert no `<backing>_otelcol` container shows up
    anywhere in the emitted HCL.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    # The fixture's `appdb` is a postgres backing service.
    assert "appdb_otelcol" not in hcl


def test_elastic_otel_config_yaml_escapes_dollar_in_hcl_source(tmp_path: Path):
    """HCL source carries `$${env:...}` (doubled `$`) — HCL parses
    `$${expr}` back to a literal `${expr}` in the string value, which
    is what otelcol's env: config provider expects in the
    OTEL_CONFIG_YAML payload at sidecar startup.

    Without this escape, HCL would treat `${env:...}` as its own
    template interpolation and reject the colon. Mod 026."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    hcl = _stage_hcl(root)
    # HCL source has the doubled form.
    assert "$${env:OBSERVABILITY_BACKEND_URL}" in hcl
    assert "$${env:TELEMETRY_API_KEY}" in hcl
    # No naked single-`$` interpolation that would conflict with HCL
    # syntax. (HCLLiteral-wrapped values like
    # `${aws_db_instance.appdb.address}` use legitimate HCL refs —
    # check that the escape didn't accidentally hit them.)
    assert "${env:" not in hcl.replace("$${env:", "")

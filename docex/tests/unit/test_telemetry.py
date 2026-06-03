"""Tests for the compile-time telemetry foundations (mod 017).

Covers the ``observability_backend_url`` field validation, the four
doctrine-injected OTel env vars on every core service, the
generalized reserved-env-key validator, and the
``TELEMETRY_API_KEY`` documented in ``example.env``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from docex.cicl.compile import compile_env
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.emit.secrets import emit_example_env


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


def _tables():
    return load_transfer_tables(project_root=None)


_MINIMAL_FIXED = """
cicl_version: "1"
foundation: fixed
domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    depends_on: [appdb]
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    resources:
      cpu: 1.0
      memory: 2GB
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


_MINIMAL_ELASTIC = """
cicl_version: "1"
foundation: elastic
domain: example.com
observability_backend_url: "https://obs.example.com"
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    depends_on: [appdb]
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    resources:
      cpu: 1.0
      memory: 2GB
      disk: 25GB
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


# ---------------------------------------------------------------------------
# observability_backend_url field validation (pydantic-level).
# ---------------------------------------------------------------------------


def test_observability_backend_url_required():
    """A doc that omits the field is rejected by pydantic with a
    field-required error."""
    src = """
cicl_version: "1"
foundation: fixed
domain: example.com
container_registry: registry.example.com
core_services: {}
"""
    with pytest.raises(ValidationError) as exc:
        _doc(src)
    assert "observability_backend_url" in str(exc.value)


def test_observability_backend_url_must_be_https():
    src = _MINIMAL_FIXED.replace(
        'observability_backend_url: "https://obs.example.com"',
        'observability_backend_url: "http://obs.example.com"',
    )
    with pytest.raises(ValidationError) as exc:
        _doc(src)
    assert "https" in str(exc.value).lower()


def test_observability_backend_url_must_be_parseable():
    src = _MINIMAL_FIXED.replace(
        'observability_backend_url: "https://obs.example.com"',
        'observability_backend_url: "::: not a url :::"',
    )
    with pytest.raises(ValidationError):
        _doc(src)


def test_observability_backend_url_must_have_host():
    src = _MINIMAL_FIXED.replace(
        'observability_backend_url: "https://obs.example.com"',
        'observability_backend_url: "https://"',
    )
    with pytest.raises(ValidationError) as exc:
        _doc(src)
    assert "host" in str(exc.value).lower()


def test_observability_backend_url_accepts_valid_https():
    doc = _doc(_MINIMAL_FIXED)
    assert doc.observability_backend_url == "https://obs.example.com"
    issues = validate_document(doc, _tables())
    assert issues == []


# ---------------------------------------------------------------------------
# OTel env vars injected on every core service (mod 017).
# ---------------------------------------------------------------------------


_OTEL_KEYS = {
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_RESOURCE_ATTRIBUTES",
}


def _multi_core_fixed_doc() -> CICLDocument:
    """A fixed-foundation doc with two core services to verify per-service
    injection on every core."""
    src = """
cicl_version: "1"
foundation: fixed
domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    resources:
      cpu: 1.0
      memory: 2GB
  worker:
    role: web
    networks: [web, internal]
    port: 9090
    resources:
      cpu: 1.0
      memory: 2GB
"""
    return _doc(src)


def _multi_core_elastic_doc() -> CICLDocument:
    src = """
cicl_version: "1"
foundation: elastic
domain: example.com
observability_backend_url: "https://obs.example.com"
core_services:
  api:
    role: web
    networks: [web, internal]
    port: 8080
    resources:
      cpu: 1.0
      memory: 2GB
      disk: 25GB
  worker:
    role: web
    networks: [web, internal]
    port: 9090
    resources:
      cpu: 1.0
      memory: 2GB
      disk: 25GB
"""
    return _doc(src)


def test_otel_env_vars_injected_on_every_core_service_fixed():
    doc = _multi_core_fixed_doc()
    compiled = compile_env(
        doc, _tables(),
        env="dev",
        project_name="myproj",
        project_version="1.2.3",
    )
    for svc_name in ("api", "worker"):
        env_block = compiled.services[svc_name].env
        for key in _OTEL_KEYS:
            assert key in env_block, (svc_name, key, sorted(env_block))
        assert env_block["OTEL_SERVICE_NAME"] == svc_name
        assert env_block["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"
        assert env_block["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
        attrs = env_block["OTEL_RESOURCE_ATTRIBUTES"]
        assert "service.namespace=myproj" in attrs
        assert "service.version=1.2.3" in attrs
        assert "deployment.environment.name=dev" in attrs


def test_otel_env_vars_injected_on_every_core_service_elastic():
    doc = _multi_core_elastic_doc()
    compiled = compile_env(
        doc, _tables(),
        env="prod",
        project_name="myproj",
        project_version="1.2.3",
    )
    for svc_name in ("api", "worker"):
        env_block = compiled.services[svc_name].env
        for key in _OTEL_KEYS:
            assert key in env_block, (svc_name, key, sorted(env_block))
        assert env_block["OTEL_SERVICE_NAME"] == svc_name
        assert env_block["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"
        assert env_block["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
        attrs = env_block["OTEL_RESOURCE_ATTRIBUTES"]
        assert "service.namespace=myproj" in attrs
        assert "service.version=1.2.3" in attrs
        assert "deployment.environment.name=prod" in attrs


def test_otel_env_vars_not_injected_on_backing_services():
    doc = _doc(_MINIMAL_FIXED)
    compiled = compile_env(
        doc, _tables(),
        env="dev",
        project_name="myproj",
        project_version="1.2.3",
    )
    appdb = compiled.services["appdb"]
    assert appdb.is_core is False
    # The backing service's env block should contain no OTEL_* keys.
    for key in _OTEL_KEYS:
        assert key not in appdb.env, (key, sorted(appdb.env))
    # And the engine-rendered body of the backing service likewise.
    for key in _OTEL_KEYS:
        assert key not in appdb.body, (key, sorted(appdb.body))


# ---------------------------------------------------------------------------
# Generalized reserved-env-key validator.
# ---------------------------------------------------------------------------


_RESERVED_KEYS = [
    "PROJECT_VERSION",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_RESOURCE_ATTRIBUTES",
]


@pytest.mark.parametrize("reserved_key", _RESERVED_KEYS)
def test_reserved_env_keys_in_env_block_rejected(reserved_key: str):
    # Insert the reserved key into the env: block of the api service.
    src = _MINIMAL_FIXED.replace(
        "    env:\n",
        f"    env:\n      {reserved_key}: \"some value\"\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_reserved_env_key" in rules, (reserved_key, rules)


@pytest.mark.parametrize("reserved_key", _RESERVED_KEYS)
def test_reserved_env_keys_in_secrets_block_rejected(reserved_key: str):
    # Append a secrets: block declaring the reserved key on api.
    src = _MINIMAL_FIXED.replace(
        "      memory: 2GB\n",
        f"      memory: 2GB\n    secrets:\n      {reserved_key}: \"desc\"\n",
        1,
    )
    doc = _doc(src)
    issues = validate_document(doc, _tables())
    rules = [i.rule for i in issues]
    assert "rule_reserved_env_key" in rules, (reserved_key, rules)


# ---------------------------------------------------------------------------
# example.env TELEMETRY_API_KEY surfacing.
# ---------------------------------------------------------------------------


def test_example_env_contains_telemetry_api_key(tmp_path: Path):
    doc = _doc(_MINIMAL_FIXED)
    out = tmp_path / "example.env"
    emit_example_env(doc, _tables(), out)
    text = out.read_text()
    assert "# Doctrine-injected secrets" in text
    assert "TELEMETRY_API_KEY=" in text


def test_example_env_telemetry_key_position(tmp_path: Path):
    """The doctrine-injected secrets group must appear before any
    per-service header in the rendered file."""
    doc = _doc(_MINIMAL_FIXED)
    out = tmp_path / "example.env"
    emit_example_env(doc, _tables(), out)
    text = out.read_text()
    telemetry_idx = text.index("TELEMETRY_API_KEY=")
    # `appdb` is a backing service in the fixture; its header appears
    # later in the file.
    appdb_idx = text.index("# appdb")
    assert telemetry_idx < appdb_idx, (
        f"TELEMETRY_API_KEY should precede per-service sections; got "
        f"telemetry_idx={telemetry_idx}, appdb_idx={appdb_idx}"
    )


def test_otel_resource_attributes_format():
    """OTEL_RESOURCE_ATTRIBUTES must use the canonical comma-separated
    `key=value` form with no spaces and no trailing comma."""
    doc = _doc(_MINIMAL_FIXED)
    compiled = compile_env(
        doc, _tables(),
        env="stage",
        project_name="myproj",
        project_version="9.9.9",
    )
    attrs = compiled.services["api"].env["OTEL_RESOURCE_ATTRIBUTES"]
    assert attrs == (
        "service.namespace=myproj,"
        "service.version=9.9.9,"
        "deployment.environment.name=stage"
    )

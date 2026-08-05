"""Tests for the compile-time telemetry foundations (mod 017).

Covers the ``observability_backend_url`` field validation, the four
doctrine-injected OTel env vars on every core service, the
generalized reserved-env-key validator, and the
``TELEMETRY_API_KEY`` surfaced in the secret manifest.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from docex.cicl.compile import compile_env
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.cicl.categories import secret_manifest


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


def _tables():
    return load_transfer_tables(project_root=None)


_MINIMAL_FIXED = """
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        uses: [appdb]
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
cicl_version: "3"
foundation: elastic
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
codebases:
  api:
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        uses: [appdb]
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
cicl_version: "3"
foundation: fixed
apex_domain: example.com
container_registry: registry.example.com
codebases: {}
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
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 1.0
          memory: 2GB
  worker:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 9090
        resources:
          cpu: 1.0
          memory: 2GB
"""
    return _doc(src)


def _multi_core_elastic_doc() -> CICLDocument:
    src = """
cicl_version: "3"
foundation: elastic
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
codebases:
  api:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 1.0
          memory: 2GB
          disk: 25GB
  worker:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
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
    # Mod 096: the compiled identity is two-segment, and
    # OTEL_SERVICE_NAME follows it (`api-web`, not `api`).
    #
    # Mod 102: two codebases each naming their core service `web` — so
    # docex.service is `web` on both while docex.codebase differs.
    # That is the useful shape: it catches an implementation that sourced
    # either attribute from the fused compiled name.
    for svc_name, codebase, service in (
        ("api-web", "api", "web"),
        ("worker-web", "worker", "web"),
    ):
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
        assert f"docex.codebase={codebase}" in attrs
        assert f"docex.service={service}" in attrs


def test_otel_env_vars_injected_on_every_core_service_elastic():
    doc = _multi_core_elastic_doc()
    compiled = compile_env(
        doc, _tables(),
        env="prod",
        project_name="myproj",
        project_version="1.2.3",
    )
    # Mod 096: the compiled identity is two-segment, and
    # OTEL_SERVICE_NAME follows it (`api-web`, not `api`).
    for svc_name, codebase, service in (
        ("api-web", "api", "web"),
        ("worker-web", "worker", "web"),
    ):
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
        assert f"docex.codebase={codebase}" in attrs
        assert f"docex.service={service}" in attrs


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
# TELEMETRY_API_KEY surfacing in the secret manifest.
# ---------------------------------------------------------------------------


def test_secret_manifest_contains_telemetry_api_key():
    manifest = secret_manifest(_doc(_MINIMAL_FIXED), _tables())
    by_key = {e.key: e for e in manifest}
    assert "TELEMETRY_API_KEY" in by_key
    assert by_key["TELEMETRY_API_KEY"].source == "doctrine"


def test_secret_manifest_telemetry_key_position():
    """The doctrine-injected TELEMETRY_API_KEY must precede a core service's
    own bespoke secret in the manifest ordering."""
    # postgres declares no `kind: secret` env vars, so key off a core
    # service's own `secrets:` entry instead of a backing one.
    src = _MINIMAL_FIXED.replace(
        "    core_services:\n",
        "    secrets:\n      API_KEY: \"bespoke api key\"\n    core_services:\n",
        1,
    )
    manifest = secret_manifest(_doc(src), _tables())
    keys = [e.key for e in manifest]
    telemetry_idx = keys.index("TELEMETRY_API_KEY")
    api_idx = keys.index("API_KEY")
    assert telemetry_idx < api_idx, (
        f"TELEMETRY_API_KEY should precede per-service secrets; got "
        f"telemetry_idx={telemetry_idx}, api_idx={api_idx}"
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
    attrs = compiled.services["api-web"].env["OTEL_RESOURCE_ATTRIBUTES"]
    # Mod 102 appended the two docex.* attributes AFTER the original triple.
    # Kept as exact equality on purpose: this is the pin that the triple's
    # keys, values, and order did not change. Do not weaken to substrings.
    assert attrs == (
        "service.namespace=myproj,"
        "service.version=9.9.9,"
        "deployment.environment.name=stage,"
        "docex.codebase=api,"
        "docex.service=web"
    )


# ---------------------------------------------------------------------------
# Mod 102 — the two axes are independently queryable.
# ---------------------------------------------------------------------------


_MULTI_SERVICE_FIXED = """
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 1.0
          memory: 2GB
      worker:
        role: worker
        command: ["python", "-m", "entrypoints.worker"]
        networks: [internal]
        resources:
          cpu: 0.5
          memory: 1GB
"""


def test_docex_attributes_decompose_the_fused_identity():
    """The point of Mod 102's two attributes: one codebase, two core services,
    and BOTH axes queryable on their own.

    `docex.codebase` is identical across the pair (so "every core service
    of `api`" is one exact-match query) while `OTEL_SERVICE_NAME` and
    `docex.service` differ (so "every `worker`" is too). Neither question
    needs a prefix/suffix match on the hyphenated `service.name`.
    """
    compiled = compile_env(
        _doc(_MULTI_SERVICE_FIXED), _tables(),
        env="dev",
        project_name="myproj",
        project_version="1.2.3",
    )
    web = compiled.services["api-web"].env
    worker = compiled.services["api-worker"].env

    assert web["OTEL_SERVICE_NAME"] == "api-web"
    assert worker["OTEL_SERVICE_NAME"] == "api-worker"

    # Same codebase axis...
    assert "docex.codebase=api" in web["OTEL_RESOURCE_ATTRIBUTES"]
    assert "docex.codebase=api" in worker["OTEL_RESOURCE_ATTRIBUTES"]
    # ...different service axis.
    assert "docex.service=web" in web["OTEL_RESOURCE_ATTRIBUTES"]
    assert "docex.service=worker" in worker["OTEL_RESOURCE_ATTRIBUTES"]
    assert "docex.service=worker" not in web["OTEL_RESOURCE_ATTRIBUTES"]
    assert "docex.service=web" not in worker["OTEL_RESOURCE_ATTRIBUTES"]


def test_service_instance_id_set_nowhere():
    """`service.instance.id` is deliberately unset: the correct values (the
    ECS task ARN, the container ID) are runtime-only, so the compiler has
    nothing true to put there. The OTel ECS resource detector supplies them if
    the application opts in — a project-side option, not doctrine.

    Asserted on BOTH compiled env surfaces of every service on both
    foundations, so the claim cannot rot in the codebase-scoped surface while
    holding in the core-service-scoped one.
    """
    for doc, env in (
        (_multi_core_fixed_doc(), "dev"),
        (_multi_core_elastic_doc(), "prod"),
    ):
        compiled = compile_env(
            doc, _tables(),
            env=env,
            project_name="myproj",
            project_version="1.2.3",
        )
        for name, svc in compiled.services.items():
            for surface, block in (
                ("env", svc.env), ("codebase_env", svc.codebase_env),
            ):
                assert "service.instance.id" not in str(block), (
                    env, name, surface,
                )

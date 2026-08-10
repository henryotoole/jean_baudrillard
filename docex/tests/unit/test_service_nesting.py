"""Mod 096 — core-service nesting: schema and validation coverage.

One codebase key in ``infra.yml`` expands into N compiled services, one
per core service. This module covers the *authoring* half of that break —
the ``core_services:`` block's schema, ``ServiceRef``, the ``cicl_version`` gate,
and the validation rules the expansion adds or re-scopes (5, 12, 14, 16, 21,
22, 23, 24, 26, 27, 33) — plus the ``http_host`` naming policy that now
governs the emitted hostname label.

Mod 125 retired rule 28. Item 17's subject was never rule 28 itself but the
core-service SCOPING of ``health_check_path``, so it is repointed at rule 33's
off-web arm, which reads the very same ``model_extra``.

The emit half (one codebase, three core services, both foundations) lives in
``test_service_expansion_emit.py``, which needs a purpose-built project on
disk rather than an in-memory document.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from docex.cicl.model import CICLDocument, ServiceRef
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import _RESERVED_CORE_ENV_KEYS, validate_document
from docex.naming import apply_policy, dns_label


def _tables():
    return load_transfer_tables(project_root=None)


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


def _issues(src: str) -> list[str]:
    return [i.rule for i in validate_document(_doc(src), _tables())]


_HEAD = """
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
"""

_WEB_SERVICE = """\
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        health_check_path: /health
        resources:
          cpu: 1.0
          memory: 2GB
"""

_BASE = _HEAD + "codebases:\n  api:\n    core_services:\n" + _WEB_SERVICE


def test_base_document_is_clean():
    """Guard against vacuous passes below: the shared base validates clean."""
    assert _issues(_BASE) == []


# ---------------------------------------------------------------------------
# 1-4, 22 — rule 22: the codebase level is `{core_services, secrets, config,
# env}`.
# ---------------------------------------------------------------------------


def test_1_core_services_absent_rejected():
    src = _HEAD + """
codebases:
  api:
    secrets:
      K: "desc"
"""
    with pytest.raises(PydanticValidationError) as exc:
        _doc(src)
    assert "core_services" in str(exc.value)


def test_2_core_services_empty_rejected():
    src = _HEAD + "codebases:\n  api:\n    core_services: {}\n"
    with pytest.raises(PydanticValidationError) as exc:
        _doc(src)
    assert "core_services" in str(exc.value)


def test_3_codebase_level_resources_names_core_services_block():
    """A stray codebase-level `resources:` gets the targeted migration
    message, not bare pydantic 'Extra inputs are not permitted'."""
    src = _BASE + "    resources:\n      cpu: 1.0\n      memory: 2GB\n"
    with pytest.raises(PydanticValidationError) as exc:
        _doc(src)
    msg = str(exc.value)
    assert "core_services:" in msg
    assert "'resources'" in msg
    assert "upgrade_1.6.0.md" in msg
    assert "Extra inputs are not permitted" not in msg


@pytest.mark.parametrize(
    "block, field",
    [
        ("    role: web\n", "role"),
        ('    command: ["python", "-m", "x"]\n', "command"),
    ],
)
def test_4_codebase_level_role_or_command_names_core_services_block(block, field):
    with pytest.raises(PydanticValidationError) as exc:
        _doc(_BASE + block)
    msg = str(exc.value)
    assert "core_services:" in msg
    assert repr(field) in msg


# ---------------------------------------------------------------------------
# 5-6 — rule 23: `command` is required and non-empty on EVERY core service.
# ---------------------------------------------------------------------------


def test_5_service_without_command_rejected():
    src = _BASE.replace('        command: ["python", "/service/dist/root.py"]\n', "")
    with pytest.raises(PydanticValidationError) as exc:
        _doc(src)
    assert "command" in str(exc.value)


@pytest.mark.parametrize("empty", ["[]", '""'])
def test_6_empty_command_rejected(empty):
    src = _BASE.replace(
        '        command: ["python", "/service/dist/root.py"]\n',
        f"        command: {empty}\n",
    )
    with pytest.raises(PydanticValidationError) as exc:
        _doc(src)
    assert "command must not be" in str(exc.value)


# ---------------------------------------------------------------------------
# 7-8 — rule 21: the cicl_version gate.
# ---------------------------------------------------------------------------


def test_7_cicl_version_1_rejected_with_upgrade_pointer():
    with pytest.raises(PydanticValidationError) as exc:
        _doc(_BASE.replace('cicl_version: "3"', 'cicl_version: "1"'))
    msg = str(exc.value)
    # Both guides, in chain order — a v1 document migrates through 1.6.0's
    # `core_services:` nesting AND 1.7.0's relation merge before it compiles.
    assert "upgrade_1.6.0.md" in msg
    assert "upgrade_1.7.0.md" in msg
    assert "core_services:" in msg
    assert "`uses`" in msg
    # It must land the author on the CURRENT generation, not an intermediate.
    assert 'cicl_version: "3"' in msg


def test_8_unknown_cicl_version_rejected_with_distinct_message():
    with pytest.raises(PydanticValidationError) as exc:
        _doc(_BASE.replace('cicl_version: "3"', 'cicl_version: "4"'))
    msg = str(exc.value)
    assert "unknown cicl_version" in msg
    # Distinct from the v1 message: no migration guide, nothing to migrate.
    assert "upgrade_1.6.0.md" not in msg


def test_8b_real_v1_document_surfaces_the_version_message_not_field_errors():
    """A *genuinely* v1 ``infra.yml`` — flat core services, no ``core_services:``
    block, ``domain_default_service`` — must surface the version message.

    Tests 7 and 8 above feed a valid v2 document with only the version string
    swapped, which nested validation accepts, so they would still pass with the
    gate in a ``mode="after"`` validator. This one would not: an ``after``
    validator never runs, because ``Codebase`` fails first and the operator
    gets a wall of per-codebase field-scoping errors plus ``extra_forbidden`` on
    ``domain_default_service`` instead. That is the single most-read error the
    1.6.0 release produces — every downstream project hits it exactly once,
    while upgrading — so the gate must fire ``mode="before"``, on the raw
    mapping, ahead of the nested models.
    """
    v1 = """
cicl_version: "1"
foundation: fixed
apex_domain: example.com
domain_default_service: web
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  web:
    role: web
    command: ["python", "/service/dist/root.py"]
    networks: [web, internal]
    port: 8080
    resources:
      cpu: 1.0
      memory: 2GB
"""
    with pytest.raises(PydanticValidationError) as exc:
        _doc(v1)
    msg = str(exc.value)
    assert "cicl_version '1' is no longer supported" in msg
    assert "upgrade_1.6.0.md" in msg
    # Exactly one error, and none of the noise the `after` placement produced.
    assert "1 validation error" in msg
    assert "moved from the codebase to the core service" not in msg
    assert "domain_default_service" not in msg


# ---------------------------------------------------------------------------
# 9-11 — rule 5: rendered data-plane identity collisions.
# ---------------------------------------------------------------------------


def _two_service_doc(cb_a, svc_a, cb_b, svc_b) -> str:
    def blk(cb, svc):
        return (
            f"  {cb}:\n    core_services:\n      {svc}:\n"
            f"        role: worker\n"
            f'        command: ["python", "-m", "x"]\n'
            f"        networks: [internal]\n"
            f"        resources:\n          cpu: 0.5\n          memory: 512MB\n"
        )
    return _HEAD + "codebases:\n" + blk(cb_a, svc_a) + blk(cb_b, svc_b)


def test_9_rule_5_collision_form_a_two_service_pairs():
    """`api` + `web-v2` renders the same as `api-web` + `v2`."""
    src = _two_service_doc("api", "web-v2", "api-web", "v2")
    assert "rule_5_rendered_identity_collision" in _issues(src)


def test_10_rule_5_collision_form_b_core_vs_backing():
    src = _HEAD + """
codebases:
  api:
    core_services:
      db:
        role: worker
        command: ["python", "-m", "x"]
        networks: [internal]
        resources:
          cpu: 0.5
          memory: 512MB
backing_services:
  api-db:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
"""
    assert "rule_5_rendered_identity_collision" in _issues(src)


def test_11_rule_5_collision_form_c_underscore_normalization():
    """`my_api`+`web` and `my`+`api_web` both render `my-api-web`."""
    src = _two_service_doc("my_api", "web", "my", "api_web")
    assert "rule_5_rendered_identity_collision" in _issues(src)


def test_rule_5_distinct_identities_clean():
    src = _two_service_doc("api", "web", "api", "worker")
    # Two entries for the same service key collapse in YAML, so build the
    # non-colliding case explicitly instead.
    src = _two_service_doc("api", "web", "billing", "worker")
    assert "rule_5_rendered_identity_collision" not in _issues(src)


# ---------------------------------------------------------------------------
# Mod 099 — rule 5's domain grows to the compiler-emitted derivatives.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service,derivative",
    [
        # The suffix Mod 099 adds: `api`'s exec container renders `api-exec`.
        ("exec", "the exec container"),
        # Pre-existing, and exposed the same way: `api`'s migration task
        # definition renders `api-migrate`, whose HCL resource address
        # `aws_ecs_task_definition.api_migrate` is the one migrate.py and
        # release.py reconstruct.
        ("migrate", "the migration task definition"),
    ],
)
def test_rule_5_rejects_service_colliding_with_own_codebase_derivative(
    service: str, derivative: str
):
    """A core service whose compiled identity is byte-identical to one of the
    compiler's *codebase*-keyed derivatives. `api` + core service `exec` renders
    `api-exec`, the same compose key as `api`'s exec container: one would
    silently clobber the other."""
    src = _HEAD + f"""
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
      {service}:
        role: worker
        command: ["python", "-m", "x"]
        networks: [internal]
        resources:
          cpu: 0.5
          memory: 512MB
"""
    issues = validate_document(_doc(src), _tables())
    rule5 = [i for i in issues if i.rule == "rule_5_rendered_identity_collision"]
    assert rule5, [i.rule for i in issues]
    # The message must name the DERIVATIVE, not a service the author never
    # wrote — otherwise it is baffling.
    assert derivative in rule5[0].message, rule5[0].message


def test_rule_5_rejects_collision_with_a_siblings_collector_sidecar():
    """`-otelcol` is a *per-core-service* derivative, so its collision form is
    cross-codebase: codebase `api` core service `web` gets the sidecar
    `api-web-otelcol`, and a sibling codebase `api-web` with a core service named
    `otelcol` renders exactly that. A pre-existing, unguarded hole on both
    foundations — Mod 099 is the occasion, not the cause."""
    src = _two_service_doc("api", "web", "api-web", "otelcol")
    issues = validate_document(_doc(src), _tables())
    rule5 = [i for i in issues if i.rule == "rule_5_rendered_identity_collision"]
    assert rule5, [i.rule for i in issues]
    assert "the collector sidecar" in rule5[0].message, rule5[0].message


def test_rule_5_derivatives_do_not_over_reject():
    """Not over-eager: codebase `api-exec` with a core service `x` renders
    `api-exec-x`, which does not collide with codebase `api`'s `api-exec`.
    Rule 5 is keyed on collision, not on a reserved-name list — a name that
    collides with nothing stays legal."""
    src = _two_service_doc("api", "web", "api-exec", "x")
    assert "rule_5_rendered_identity_collision" not in _issues(src)




# ---------------------------------------------------------------------------
# 12-14 — DELETED (mod 113). Rules 6 and 24 are RETIRED in 1.7.0 and their
# numbers tombstoned, never reused.
#
#   test_12_core_to_core_depends_on_rejected_and_names_consumes
#   test_13_backing_to_core_depends_on_rejected
#       Rule 24 restricted `depends_on` to backing services. There is one
#       relation now and its shape rule is rule 25, which permits a core target
#       outright — so there is nothing left to reject. The successor coverage
#       (a bare CODEBASE name in `uses` is still an error) lives in
#       test_uses_relation.py::test_1_bare_codebase_name_rejected.
#
#   test_14_backing_service_cycle_still_fatal
#       Rule 6's DFS is gone. A backing service declares no outbound edges, so
#       it is a graph SINK and a backing-targeted cycle cannot be CONSTRUCTED,
#       let alone detected — acyclicity is a property of the graph's shape
#       rather than a rule enforced against it (cicl.md § The graph may contain
#       cycles). Pinned in its only possible form by
#       test_uses_relation.py::test_uses_on_a_backing_service_is_rejected_
#       with_a_targeted_message.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 15-16 — rules 26 and 27: fields and networks a role forbids.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["worker", "clock"])
def test_16_web_network_on_non_web_role_rejected(role):
    src = _HEAD + f"""
codebases:
  svc:
    core_services:
      p:
        role: {role}
        command: ["python", "-m", "x"]
        networks: [web, internal]
        port: 8080
        resources:
          cpu: 0.25
          memory: 512MB
"""
    assert "rule_27_web_network_on_non_web_role" in _issues(src)


def test_16_web_network_on_web_role_clean():
    assert "rule_27_web_network_on_non_web_role" not in _issues(_BASE)


# ---------------------------------------------------------------------------
# 17 — the `health_check_path` rule reads the CORE SERVICE.
#
# Mod 125: rule 28 is retired, but this item's SUBJECT was always the scoping,
# not the obligation — so it is repointed at rule 33's off-web arm, which reads
# the same `model_extra`. Read it off the Codebase and it sees permanently empty
# extras and passes while checking nothing, exactly as before.
# ---------------------------------------------------------------------------


def test_17_health_check_path_read_off_the_core_service():
    """Regression for the silent pass Mod 095's corporal flagged: reading
    `health_check_path` off the Codebase sees permanently empty extras
    once the field is core-service-scoped."""
    src = _HEAD + """
codebases:
  consumer:
    core_services:
      worker:
        role: worker
        command: ["python", "-m", "x"]
        networks: [internal]
        health_check_path: /health
        resources:
          cpu: 0.5
          memory: 512MB
"""
    assert "rule_33_health_check_path_off_web" in _issues(src)


# ---------------------------------------------------------------------------
# 18 — rule 14 covers core service names too.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reserved", ["dev", "test", "stage", "prod", "www"])
def test_18_reserved_service_name_rejected(reserved):
    src = _BASE.replace("      web:\n", f"      {reserved}:\n")
    issues = validate_document(_doc(src), _tables())
    hits = [i for i in issues if i.rule == "rule_14_service_name_blacklist"]
    assert hits
    assert reserved in hits[0].message


# ---------------------------------------------------------------------------
# 19 — rule 12: domain_default_service is a dotted, web-network core service.
# ---------------------------------------------------------------------------


_WITH_WORKER = _BASE + """\
      worker:
        role: worker
        command: ["python", "-m", "worker"]
        networks: [internal]
        resources:
          cpu: 0.5
          memory: 512MB
"""


def _with_default(src: str, value: str) -> str:
    return src.replace(
        "container_registry: registry.example.com",
        f"container_registry: registry.example.com\ndomain_default_service: {value}",
    )


def test_19_bare_service_name_rejected():
    assert "rule_domain_default_malformed" in _issues(_with_default(_BASE, "api"))


def test_19_unknown_service_rejected():
    assert "rule_domain_default_unknown" in _issues(_with_default(_BASE, "api.nope"))


def test_19_non_web_service_rejected():
    assert "rule_domain_default_not_web" in _issues(
        _with_default(_WITH_WORKER, "api.worker")
    )


def test_19_web_service_clean():
    assert _issues(_with_default(_BASE, "api.web")) == []


# ---------------------------------------------------------------------------
# 20-21 — rule 16 and the reserved env keys, against the EFFECTIVE env.
# ---------------------------------------------------------------------------


def _with_service_env(src: str, body: str) -> str:
    return src.replace(
        "        port: 8080\n", f"        port: 8080\n        env:\n{body}"
    )


def test_20_service_env_key_colliding_with_codebase_secrets_rejected():
    src = _with_service_env(_BASE, "          SHARED: literal\n").replace(
        "    core_services:\n", '    secrets:\n      SHARED: "desc"\n    core_services:\n'
    )
    assert "rule_env_secrets_config_overlap" in _issues(src)


@pytest.mark.parametrize("reserved_key", sorted(_RESERVED_CORE_ENV_KEYS))
def test_21_service_env_cannot_shadow_a_reserved_key(reserved_key: str):
    """Every doctrine-reserved key, not just `OTEL_SERVICE_NAME`. Parametrized
    off the validator's own frozenset so a key added there without core-service-level
    coverage fails here rather than passing silently."""
    src = _with_service_env(_BASE, f'          {reserved_key}: "mine"\n')
    issues = validate_document(_doc(src), _tables())
    hits = [i for i in issues if i.rule == "rule_reserved_env_key"]
    assert hits, reserved_key
    # The diagnostic points at the core service, not the codebase.
    assert "core_services.web.env" in hits[0].where


def test_21_codebase_level_reserved_key_reported_once_not_per_process():
    """A codebase-level `env:` key is one fact, not N — reporting it
    once per core service would multiply one mistake into N diagnostics."""
    src = _WITH_WORKER.replace(
        "    core_services:\n", '    env:\n      OTEL_SERVICE_NAME: "mine"\n    core_services:\n'
    )
    issues = validate_document(_doc(src), _tables())
    hits = [
        i for i in issues
        if i.rule == "rule_reserved_env_key" and "OTEL_SERVICE_NAME" in i.message
    ]
    assert len(hits) == 1
    assert hits[0].where == "codebases.api.env"


# ---------------------------------------------------------------------------
# 22 — a bare (three-segment) core magic ref, caught by the shared arity
# checker (Mod 097 folded 096's dedicated rule id into `rule_3_magic_ref_arity`).
# ---------------------------------------------------------------------------


def test_22_bare_core_magic_ref_rejected_with_arity_message():
    src = _with_service_env(
        _BASE, "          UPSTREAM: ${codebases.api.host}\n"
    )
    issues = validate_document(_doc(src), _tables())
    hits = [i for i in issues if i.rule == "rule_3_magic_ref_arity"]
    assert hits
    assert "${codebases.<codebase>.core_services.<service>.<part>}" in hits[0].message


# ---------------------------------------------------------------------------
# 23 — ServiceRef.
# ---------------------------------------------------------------------------


def test_23_service_ref_round_trips():
    ref = ServiceRef.parse("api.web")
    assert (ref.codebase, ref.service) == ("api", "web")
    assert ref.dotted == "api.web"
    assert ref.compiled == "api-web"
    assert ServiceRef.parse(ref.dotted) == ref


@pytest.mark.parametrize("raw", ["api", "api.web.x", "", "api.", ".web", " . "])
def test_23_service_ref_rejects_malformed(raw):
    with pytest.raises(ValueError) as exc:
        ServiceRef.parse(raw)
    assert "<codebase>.<service>" in str(exc.value)


# ---------------------------------------------------------------------------
# 24 — the http_host policy is byte-identical to dns_label at <= 63 chars.
# ---------------------------------------------------------------------------


_HTTP_HOST_INPUTS = [
    "api",
    "api-web",
    "api_web",
    "My_Api-Web",
    "a",
    "a" * 63,
    "some_service-with_mixed_Case",
]


@pytest.mark.parametrize("name", _HTTP_HOST_INPUTS)
def test_24_http_host_policy_matches_dns_label(name):
    """The hard guard from the design record. Wiring the `http_host` policy
    into `_web_hosts` must not silently change a single existing hostname —
    a changed label invalidates TLS certs and DNS records."""
    policy = _tables().naming_policies.get("http_host")
    assert apply_policy(name, policy) == dns_label(name)


def test_24_http_host_over_63_chars_raises():
    policy = _tables().naming_policies.get("http_host")
    with pytest.raises(Exception) as exc:
        apply_policy("a" * 64, policy)
    assert "63" in str(exc.value)

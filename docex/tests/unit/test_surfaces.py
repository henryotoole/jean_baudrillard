"""Mod 125 — the CICL *surface* language.

Covers the `Surface` model, the transcribed style -> format table, and rules 29
(one contract format per surface), 30 (surface names), 31 (a `uses` target
declares a surface) and 32 (a directly-addressed target declares a `port`).

WHY 31 and 32 live here rather than in `test_uses_relation.py`: both are
consequences of the *surface model* — 31 requires one, and 32's entire
justification is what a consumer does with one — while
`test_uses_relation.py` is dedicated to rules 7 and 25's one-relation merge.
Rule 33 lives in `test_validate.py`, beside rule 15, its sibling.

In-memory documents in the style of `test_uses_relation.py` /
`test_clock.py`. Every rule gets a RED case and a GREEN case: a validation
rule's pass means nothing until the rule has been observed failing.

Unit tests only — nothing here crosses docker, AWS, or git.
"""

from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from docex.cicl.model import (
    API_STYLE_FORMATS,
    IMPLEMENTED_CONTRACT_FORMATS,
    CICLDocument,
    Surface,
)
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.errors import ValidationIssue


def _tables():
    return load_transfer_tables(project_root=None)


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


def _all(src: str) -> list[ValidationIssue]:
    return validate_document(_doc(src), _tables())


def _rules(src: str) -> list[str]:
    return [i.rule for i in _all(src)]


def _hits(src: str, rule: str) -> list[ValidationIssue]:
    return [i for i in _all(src) if i.rule == rule]


_HEAD = """\
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
"""

_APPDB = """\
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""

_REST = {"rest": ["rest"]}
_EVENTS = {"events": ["events"]}


def _svc(
    name: str,
    role: str = "worker",
    *,
    port: int | None = None,
    health_check_path: bool = False,
    uses: list[str] | None = None,
    surfaces: dict[str, list[str]] | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """One core service block. Surfaces are `{surface_name: [api_styles]}`."""
    lines = [
        f"      {name}:",
        f"        role: {role}",
        '        command: ["python", "-m", "x"]',
        "        networks: [web, internal]" if role == "web"
        else "        networks: [internal]",
    ]
    if port is not None:
        lines.append(f"        port: {port}")
    if health_check_path:
        lines.append("        health_check_path: /health")
    if uses is not None:
        lines.append(f"        uses: {json.dumps(uses)}")
    if surfaces:
        lines.append("        surfaces:")
        for surface_name, styles in surfaces.items():
            lines.append(f"          {surface_name}:")
            lines.append(f"            api_styles: {json.dumps(styles)}")
    if env:
        lines.append("        env:")
        lines += [f"          {k}: {json.dumps(v)}" for k, v in env.items()]
    lines += [
        "        resources:",
        "          cpu: 0.5",
        "          memory: 512MB",
    ]
    return "\n".join(lines) + "\n"


def _codebase(name: str, *svcs: str, env: dict[str, str] | None = None) -> str:
    out = f"  {name}:\n"
    if env:
        out += "    env:\n"
        out += "".join(f"      {k}: {json.dumps(v)}\n" for k, v in env.items())
    return out + "    core_services:\n" + "".join(svcs)


def _src(*codebases: str, backing: str = "") -> str:
    return _HEAD + "codebases:\n" + "".join(codebases) + backing


def _web(**kw) -> str:
    """`api.web`: on the `web` network, so it carries a port (rule 15) and a
    `health_check_path` (rule 33) unless a case overrides them."""
    kw.setdefault("port", 8080)
    kw.setdefault("health_check_path", True)
    return _svc("web", "web", **kw)


def _solo_web(*, backing: str = "", **kw) -> str:
    """A one-codebase, one-core-service document: just `api.web`."""
    return _src(_codebase("api", _web(**kw)), backing=backing)


# The shared base: `api.web` alone, no surfaces anywhere. Declaring no surface
# is legal — it is what makes a core service a non-provider.
_BASE = _solo_web()

_WORKER_HOST = "${codebases.api.core_services.worker.host}"


def test_base_document_is_clean():
    """Guard against vacuous passes below: the shared base validates clean."""
    assert _rules(_BASE) == []


# ---------------------------------------------------------------------------
# 1-6 — the Surface model and the transcribed doctrine table.
# ---------------------------------------------------------------------------


def test_1_style_format_table_matches_the_doctrine():
    """The anti-drift pin on a TRANSCRIBED doctrine table.

    `API_STYLE_FORMATS` is a copy of `cicl.md § Surfaces`' own eight-row table,
    so it is asserted literally rather than derived from anything — a derived
    assertion would drift in lockstep with the bug it is meant to catch.
    """
    assert API_STYLE_FORMATS == {
        "rest": "openapi",
        "stream": "openapi",
        "webhook": "openapi",
        "rpc": "asyncapi",
        "events": "asyncapi",
        "socket": "asyncapi",
        "graphql": "graphql",
        "grpc": "proto",
    }
    # contracts.md § Standards: GraphQL and Proto are planned, not implemented.
    assert IMPLEMENTED_CONTRACT_FORMATS == {"openapi", "asyncapi"}


def test_2_empty_api_styles_is_a_parse_error():
    """`min_length=1` is what lets rule 29 never reason about the empty set."""
    src = _src(_codebase("api", _svc("worker", surfaces={"events": []})))
    with pytest.raises(PydanticValidationError):
        _doc(src)


def test_3_singular_api_style_typo_is_a_parse_error():
    """`api_style:` (singular) is the typo the block invites. Under
    `extra="allow"` it would be silently ignored, producing a surface with no
    styles rather than an error — which is why `Surface` forbids extras."""
    src = _src(_codebase("api", _svc("worker", surfaces=_EVENTS))).replace(
        "api_styles:", "api_style:"
    )
    with pytest.raises(PydanticValidationError) as exc:
        _doc(src)
    assert "api_style" in str(exc.value)


def test_4_absent_surfaces_is_an_empty_dict_and_validates_clean():
    """A non-provider is legal, and this is exactly a clock's state."""
    doc = _doc(_BASE)
    assert doc.codebases["api"].core_services["web"].surfaces == {}
    assert validate_document(doc, _tables()) == []


def test_5_authored_surfaces_is_not_an_undeclared_field():
    """The `_STANDARD_SERVICE_FIELDS` pin. `CoreService` is `extra="allow"`, so
    if `surfaces` were not a declared field it would land in `model_extra` and
    resurface as `tt_rule_4_undeclared_field` — a message about transfer-table
    field declarations, which is the wrong answer to a correct block."""
    src = _solo_web(surfaces=_REST)
    assert "tt_rule_4_undeclared_field" not in _rules(src)
    assert _rules(src) == []


def test_6_formats_resolves_styles_through_the_table():
    assert Surface(api_styles=["rest", "stream", "webhook"]).formats() == {
        "openapi"
    }
    # Unknown styles are omitted rather than raising — rule 29 reports them
    # under their own id, and one mistake must not surface twice.
    assert Surface(api_styles=["rest", "bogus"]).formats() == {"openapi"}


# ---------------------------------------------------------------------------
# 7-12 — Rule 29: a surface's api_styles resolve to exactly one format.
# ---------------------------------------------------------------------------


def test_7_three_openapi_styles_in_one_surface_pass():
    """`cicl.md § Surfaces`' own worked case: all three are openapi, so one
    contract carries them."""
    src = _solo_web(surfaces={"rest": ["rest", "stream", "webhook"]})
    assert _rules(src) == []


def test_8_mixed_contract_formats_rejected():
    src = _solo_web(surfaces={"rest": ["rest", "rpc"]})
    hits = _hits(src, "rule_29_mixed_contract_formats")
    assert len(hits) == 1
    assert "split these into two surfaces" in hits[0].message.lower()
    assert hits[0].where == "codebases.api.core_services.web.surfaces.rest"


def test_9_unknown_api_style_is_its_own_id():
    """An unknown style does not also read as a mixed-format surface: it
    resolves to no format at all, so `formats()` stays a singleton."""
    src = _solo_web(surfaces={"rest": ["bogus"]})
    rules = _rules(src)
    assert "rule_29_unknown_api_style" in rules
    assert "rule_29_mixed_contract_formats" not in rules


def test_10_graphql_is_defined_language_but_not_implemented():
    """Ruling 4: this is enforced at COMPILE, not deferred to a later gate, and
    the author must hear "not yet implemented" rather than "unknown style"."""
    src = _solo_web(surfaces={"graphql": ["graphql"]})
    hits = _hits(src, "rule_contract_format_not_implemented")
    assert len(hits) == 1
    assert "not yet implemented" in hits[0].message
    assert "graphql" in hits[0].message
    assert "rule_29_unknown_api_style" not in _rules(src)


def test_11_grpc_resolves_to_the_unimplemented_proto_format():
    src = _solo_web(surfaces={"grpc": ["grpc"]})
    hits = _hits(src, "rule_contract_format_not_implemented")
    assert len(hits) == 1
    assert "proto" in hits[0].message


def test_12_two_surfaces_of_the_same_format_are_legal():
    """`cicl.md § Surfaces`' public/admin case: same format, genuinely
    different consumers and auth. Rule 29 is per-surface, not per-service."""
    src = _solo_web(surfaces={"rest_public": ["rest"], "rest_admin": ["rest"]})
    assert _rules(src) == []


# ---------------------------------------------------------------------------
# 13-14 — Rule 30: surface names.
# ---------------------------------------------------------------------------


def test_13_dotted_surface_name_rejected():
    """A surface name is one segment of a contract filename parsed
    right-anchored into four fields, so a dot makes the path ambiguous. Like
    rule 5's, this is a name-SHAPE rule and raises rather than aggregating."""
    src = _solo_web(surfaces={"rest.public": ["rest"]})
    with pytest.raises(PydanticValidationError) as exc:
        _doc(src)
    assert "rule 30" in str(exc.value)
    assert "rest.public" in str(exc.value)


def test_14_underscored_and_hyphenated_surface_names_accepted():
    src = _solo_web(surfaces={"rest_public": ["rest"], "rest-admin": ["rest"]})
    assert set(_doc(src).codebases["api"].core_services["web"].surfaces) == {
        "rest_public", "rest-admin",
    }
    assert _rules(src) == []


# ---------------------------------------------------------------------------
# 15-18 — Rule 31: a core-service `uses` target declares a surface.
# ---------------------------------------------------------------------------


def test_15_uses_target_with_a_surface_is_clean():
    src = _src(_codebase(
        "api",
        _web(uses=["api.worker"], surfaces=_REST),
        _svc("worker", surfaces=_EVENTS),
    ))
    assert _rules(src) == []


def test_16_uses_target_without_a_surface_rejected():
    src = _src(_codebase(
        "api",
        _web(uses=["api.worker"], surfaces=_REST),
        _svc("worker"),
    ))
    hits = _hits(src, "rule_31_uses_target_declares_no_surface")
    assert len(hits) == 1
    # The EDGE is the fault, not the target: the fix is on the consumer's
    # `uses:` list or on the target, and the author is told both options.
    assert hits[0].where == "codebases.api.core_services.web.uses"
    assert "drop the edge" in hits[0].message


def test_17_backing_uses_target_is_untouched_by_rule_31():
    """A backing service has no surfaces and never will — rule 31 governs core
    targets only."""
    src = _solo_web(uses=["appdb"], backing=_APPDB)
    assert _rules(src) == []


def test_18_typod_core_target_reports_rule_25_and_not_rule_31():
    """The reason rule 31 is nested inside `_validate_uses` rather than written
    as a sibling: a target that does not exist must not ALSO be reported as
    declaring no surface."""
    src = _src(_codebase(
        "api",
        _web(uses=["api.wroker"], surfaces=_REST),
        _svc("worker", surfaces=_EVENTS),
    ))
    rules = _rules(src)
    assert "rule_25_unresolved_uses" in rules
    assert "rule_31_uses_target_declares_no_surface" not in rules


# ---------------------------------------------------------------------------
# 19-25 — Rule 32: a DIRECTLY-ADDRESSED `uses` target declares a `port`.
#
# "Directly addressed" is per-EDGE and detected as "the consumer holds a magic
# ref to the target". See `_validate_uses_addressing`'s docstring for why that
# signal and not one derived from the target's `api_styles`.
# ---------------------------------------------------------------------------


def test_19_direct_target_without_a_port_rejected():
    src = _src(_codebase(
        "api",
        _web(uses=["api.worker"], surfaces=_REST, env={"W": _WORKER_HOST}),
        _svc("worker", surfaces=_EVENTS),
    ))
    hits = _hits(src, "rule_32_direct_target_needs_port")
    assert len(hits) == 1
    assert "'api.web'" in hits[0].message
    assert hits[0].where == "codebases.api.core_services.worker.port"


def test_20_direct_target_with_a_port_is_clean():
    src = _src(_codebase(
        "api",
        _web(uses=["api.worker"], surfaces=_REST, env={"W": _WORKER_HOST}),
        _svc("worker", port=8081, surfaces=_EVENTS),
    ))
    assert _rules(src) == []


def test_21_queue_reached_target_declaring_a_port_rejected():
    """No consumer holds a magic ref to it, so there is no address at which one
    reaches it and the port is decoration."""
    src = _src(_codebase(
        "api",
        _web(surfaces=_REST),
        _svc("worker", port=8081, surfaces=_EVENTS),
        _svc("clock", uses=["api.worker"]),
    ))
    hits = _hits(src, "rule_32_unaddressed_target_declares_port")
    assert len(hits) == 1
    assert "8081" in hits[0].message
    assert "'api.clock'" in hits[0].message
    assert hits[0].where == "codebases.api.core_services.worker.port"


def test_22_queue_reached_target_without_a_port_is_clean():
    src = _src(_codebase(
        "api",
        _web(surfaces=_REST),
        _svc("worker", surfaces=_EVENTS),
        _svc("clock", uses=["api.worker"]),
    ))
    assert _rules(src) == []


def test_rule_32_web_target_reached_by_public_url_is_exempt():
    """The `web`-network carve-out, and it is NOT laxity.

    Rule 15 requires a `port` on every web-network core service. A
    `frontend.web` declaring `uses: [api.web]` reaches it by public URL out of
    `config:` — a browser cannot resolve an internal hostname — so it holds no
    magic ref. Without the carve-out, rule 32's negative arm would demand
    `api.web` drop the very port rule 15 requires, and the two rules would
    contradict each other on the doctrine's most common two-codebase topology.
    """
    src = _src(
        _codebase("api", _web(surfaces=_REST)),
        _codebase("frontend", _svc(
            "web", "web", port=3000, health_check_path=True, uses=["api.web"],
        )),
    )
    rules = _rules(src)
    assert "rule_32_unaddressed_target_declares_port" not in rules
    # And rule 15 is silent too — the port the carve-out preserves is present.
    assert "rule_web_service_needs_port" not in rules
    assert rules == []


def test_24_codebase_level_ref_addresses_the_target_for_every_core_service():
    """Mirrors rule 7's third clarification: a ref in a codebase-level `env:`
    is received by EVERY core service of that codebase, so every one of them
    addresses the target directly and the port obligation holds."""
    src = _src(
        _codebase("api", _svc("worker", surfaces=_EVENTS)),
        _codebase(
            "consumer",
            # port + health_check_path so the document carries no rule-15/33
            # issue of its own — a red case must fail for the reason it names.
            _svc(
                "web", "web", port=3000, health_check_path=True,
                uses=["api.worker"],
            ),
            _svc("runner", uses=["api.worker"]),
            env={"W": _WORKER_HOST},
        ),
    )
    hits = _hits(src, "rule_32_direct_target_needs_port")
    assert len(hits) == 1
    assert "'consumer.web'" in hits[0].message
    assert "'consumer.runner'" in hits[0].message


def test_25_self_uses_produces_no_rule_32_verdict():
    """Rule 25 owns the self-edge. Without the skip the negative arm would fire
    here — the worker is off `web`, declares a port, and its only `uses`
    consumer (itself) holds no ref — so this case is not vacuous."""
    src = _src(_codebase(
        "api",
        _web(surfaces=_REST),
        _svc("worker", port=8081, uses=["api.worker"], surfaces=_EVENTS),
    ))
    rules = _rules(src)
    assert "rule_25_self_uses" in rules
    assert not [r for r in rules if r.startswith("rule_32_")]

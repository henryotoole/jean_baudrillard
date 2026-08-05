"""Tests for the magic-ref resolver."""

from __future__ import annotations

import pytest

from docex.cicl.magic_refs import (
    MagicRefArityError,
    MagicRefResolver,
    find_magic_refs,
)
from docex.cicl.model import (
    BackingService,
    CICLDocument,
    Codebase,
    CoreService,
    Resources,
)
from docex.cicl.transfer import EngineEntry, EnvVarSpec, TransferTables
from docex.cicl.validate import validate_document
from docex.errors import SubstitutionError


def _engines() -> dict[str, EngineEntry]:
    """One EngineEntry per compiled identity in the synthetic topology.

    Fresh objects per call: tests that rewrite a `provides` template (the
    cycle test) must not leak into their neighbours.
    """
    db_engine = EngineEntry(
        role="relational_db",
        engine="postgres",
        foundation="both",
        provides={
            "host": {"fixed": "${global_service_name}", "elastic": "@aws_db_instance.${name}.endpoint"},
            "port": {"fixed": "${port}", "elastic": "${port}"},
            "user": {"fixed": "$[POSTGRES_USER]", "elastic": "$[POSTGRES_USER]"},
            "password": {"fixed": "$[POSTGRES_PASSWORD]", "elastic": "$[POSTGRES_PASSWORD]"},
            "sslmode": {"fixed": "disable", "elastic": "require"},
        },
        env={
            "POSTGRES_USER": EnvVarSpec(
                name="POSTGRES_USER", kind="fixed", value="appuser",
                desc="Postgres role name — doctrine-fixed, not a secret.",
            ),
            "POSTGRES_PASSWORD": EnvVarSpec(
                name="POSTGRES_PASSWORD", kind="minted", policy="password",
                desc="Postgres role password — generated once per env.",
            ),
        },
        naming="rds",
    )

    def _container(role: str, provides: dict) -> EngineEntry:
        return EngineEntry(
            role=role, engine="container", foundation="both",
            provides=provides, naming="ecs",
        )

    host_part = {
        "host": {"fixed": "${global_service_name}", "elastic": "${global_service_name}"},
    }
    return {
        "db": db_engine,
        # A hyphenated backing service — same engine shape, different context.
        "my-db": _db_engine_like(db_engine),
        "api-web": _container("web", dict(host_part)),
        "api-worker": _container("worker", dict(host_part)),
        # Rule-of-record free behavior: `scheduler` publishes no discovery
        # surface at all, so it can never be a magic-ref target.
        "api-nightly_cleanup": _container("scheduler", {}),
        "my-api-web": _container("web", dict(host_part)),
    }


def _db_engine_like(src: EngineEntry) -> EngineEntry:
    """A second, independent postgres EngineEntry with the same shape."""
    return EngineEntry(
        role=src.role, engine=src.engine, foundation=src.foundation,
        provides={k: dict(v) for k, v in src.provides.items()},
        env=dict(src.env), naming=src.naming,
    )


def _make_doc(foundation: str = "fixed") -> CICLDocument:
    def _proc(role: str, **kw) -> CoreService:
        return CoreService(
            role=role,
            command=["python", "/service/dist/root.py"],
            resources=Resources(cpu=1.0, memory="2GB"),
            **kw,
        )

    return CICLDocument(
        cicl_version="2",
        foundation=foundation,
        apex_domain="example.com",
        observability_backend_url="https://obs.example.com",
        container_registry="reg.example.com",
        codebases={
            "api": Codebase(
                env={},
                core_services={
                    "web": _proc(
                        "web", networks=["web", "internal"],
                        depends_on=["db"], port=8080,
                    ),
                    "worker": _proc("worker", networks=["internal"]),
                    "nightly_cleanup": _proc("scheduler", networks=["internal"]),
                },
            ),
            # Hyphenated names are legal and must round-trip through both
            # regexes — see test_hyphenated_names_round_trip.
            "my-api": Codebase(
                env={},
                core_services={
                    "web": _proc(
                        "web", networks=["web", "internal"], port=8080,
                    ),
                },
            ),
        },
        backing_services={
            "db": BackingService(
                role="relational_db",
                networks=["internal"],
                engine="postgres",
                version="15",
                port=5432,
                schema_owned_by="api",
            ),
            "my-db": BackingService(
                role="relational_db",
                networks=["internal"],
                engine="postgres",
                version="15",
                port=5432,
                schema_owned_by="api",
            ),
        },
    )


def _make_tables(engines: dict[str, EngineEntry]) -> TransferTables:
    return TransferTables(
        by_role={
            "relational_db": {"postgres": engines["db"]},
            "web": {"container": engines["api-web"]},
            "worker": {"container": engines["api-worker"]},
            "scheduler": {"container": engines["api-nightly_cleanup"]},
        }
    )


def _make_resolver(foundation: str = "fixed") -> tuple[MagicRefResolver, EngineEntry]:
    """Build a resolver wired up to a minimal postgres engine.

    Returns (resolver, db_engine) so tests can pre-populate engines
    in arbitrary topologies.
    """
    engines = _engines()
    doc = _make_doc(foundation)
    tables = _make_tables(engines)

    def _ctx(name: str, port: int, role: str) -> dict:
        return {
            "name": name,
            "global_service_name": f"p-dev-{name}",
            "port": port,
            "project_name": "p", "env_name": "dev", "role_name": role,
            "env_subdomain": "dev.example.com",
        }

    resolver = MagicRefResolver(
        doc=doc,
        tables=tables,
        foundation=foundation,
        contexts={
            # Mod 096: keyed on the compiled identity, matching the compiler.
            "api-web": _ctx("api-web", 8080, "web"),
            "api-worker": _ctx("api-worker", 8080, "worker"),
            "api-nightly_cleanup": _ctx("api-nightly_cleanup", 8080, "scheduler"),
            "my-api-web": _ctx("my-api-web", 8080, "web"),
            "db": _ctx("db", 5432, "relational_db"),
            "my-db": _ctx("my-db", 5432, "relational_db"),
        },
        engines=engines,
    )
    return resolver, engines["db"]


def test_find_magic_refs():
    refs = find_magic_refs(
        "a ${backing_services.x.y} b ${codebases.z.core_services.p.w} c"
    )
    assert [(m.kind, m.body) for m in refs] == [
        ("backing_services", "x.y"),
        ("codebases", "z.core_services.p.w"),
    ]


def test_find_magic_refs_matches_malformed_refs():
    """Capture is body-agnostic on purpose: whether a string IS a magic ref
    is decided independently of whether it is WELL-FORMED. A malformed ref
    must still be *seen*, or it falls through and is emitted verbatim."""
    refs = find_magic_refs("${codebases.api.host}")
    assert [(m.kind, m.body) for m in refs] == [("codebases", "api.host")]
    with pytest.raises(MagicRefArityError):
        refs[0].parse()


def test_resolve_simple_magic_ref():
    resolver, _ = _make_resolver()
    rendered = resolver.resolve_in_string(
        "${backing_services.db.host}", consumer="api-web"
    )
    assert rendered.value == "p-dev-db"


def test_resolve_minted_part_propagates_runtime_ref():
    """A magic ref to a minted part (whose template is a bare $[VAR])
    resolves to that ref and propagates the VAR into the consumer's
    runtime refs, so the compiler can wire it into the container."""
    resolver, _ = _make_resolver()
    rendered = resolver.resolve_in_string(
        "${backing_services.db.password}", consumer="api-web"
    )
    assert rendered.value == "$[POSTGRES_PASSWORD]"
    assert "POSTGRES_PASSWORD" in rendered.runtime_refs
    assert "POSTGRES_PASSWORD" in resolver.runtime_refs["api-web"]


def test_resolve_fixed_part_inlines_literal():
    """Mod 077: a magic ref to a `kind: fixed` part (POSTGRES_USER →
    appuser) is inlined to its literal at compile time and never reaches
    the runtime layer — so the var is absent from the consumer's
    runtime refs."""
    resolver, _ = _make_resolver()
    rendered = resolver.resolve_in_string(
        "${backing_services.db.user}", consumer="api-web"
    )
    assert rendered.value == "appuser"
    assert "POSTGRES_USER" not in rendered.runtime_refs
    assert "POSTGRES_USER" not in resolver.runtime_refs.get("api", set())


def test_magic_ref_hcl_passthrough_on_elastic():
    resolver, _ = _make_resolver(foundation="elastic")
    rendered = resolver.resolve_in_string(
        "${backing_services.db.host}", consumer="api-web"
    )
    assert rendered.raw_hcl is True
    assert "aws_db_instance.db.endpoint" in rendered.value


def test_magic_ref_unknown_service():
    resolver, _ = _make_resolver()
    with pytest.raises(SubstitutionError):
        resolver.resolve_in_string(
            "${backing_services.nope.host}", consumer="api-web"
        )


def test_magic_ref_unknown_part():
    resolver, _ = _make_resolver()
    with pytest.raises(SubstitutionError):
        resolver.resolve_in_string(
            "${backing_services.db.nope}", consumer="api-web"
        )


def test_dependency_tracking():
    resolver, _ = _make_resolver()
    resolver.resolve_in_string(
        "${backing_services.db.host}", consumer="api-web"
    )
    deps = [(d.consumer, d.target, d.part) for d in resolver.deps]
    assert ("api-web", "db", "host") in deps


def test_magic_ref_empty_resolution_errors():
    """A magic ref to a part that resolves to empty (e.g. an unset port
    with no engine default) is a hard error, not a silent empty emit."""
    resolver, _ = _make_resolver()
    # Simulate a db with neither a declared port nor an engine
    # default: the port context var is empty, so ${port} resolves to "".
    resolver.contexts["db"]["port"] = ""
    with pytest.raises(SubstitutionError):
        resolver.resolve_in_string(
            "${backing_services.db.port}", consumer="api-web"
        )


def test_resolve_sslmode_part_compile_time_constant():
    """sslmode is a doctrine-provided part with foundation-specific
    compile-time constants — `disable` on fixed, `require` on elastic —
    so projects can reference it without encoding foundation-aware
    logic. See mod 009."""
    resolver_fixed, _ = _make_resolver(foundation="fixed")
    rendered_fixed = resolver_fixed.resolve_in_string(
        "${backing_services.db.sslmode}", consumer="api-web"
    )
    assert rendered_fixed.value == "disable"
    assert rendered_fixed.raw_hcl is False
    assert rendered_fixed.runtime_refs == set()

    resolver_elastic, _ = _make_resolver(foundation="elastic")
    rendered_elastic = resolver_elastic.resolve_in_string(
        "${backing_services.db.sslmode}", consumer="api-web"
    )
    assert rendered_elastic.value == "require"
    assert rendered_elastic.raw_hcl is False
    assert rendered_elastic.runtime_refs == set()


# ---------------------------------------------------------------------------
# Mod 097 — four-segment core refs.
# ---------------------------------------------------------------------------


def test_four_segment_core_ref_resolves():
    for foundation in ("fixed", "elastic"):
        resolver, _ = _make_resolver(foundation=foundation)
        rendered = resolver.resolve_in_string(
            "${codebases.api.core_services.web.host}", consumer="api-worker"
        )
        assert rendered.value == "p-dev-api-web", foundation


def test_three_segment_core_ref_arity_message():
    resolver, _ = _make_resolver()
    with pytest.raises(MagicRefArityError) as exc:
        resolver.resolve_in_string(
            "${codebases.api.host}", consumer="api-worker"
        )
    msg = str(exc.value)
    assert "${codebases.<codebase>.core_services.<service>.<part>}" in msg
    assert "Did you mean ${codebases.api.core_services.<service>.host}?" in msg


def test_four_segment_backing_ref_arity_message():
    resolver, _ = _make_resolver()
    with pytest.raises(MagicRefArityError) as exc:
        resolver.resolve_in_string(
            "${backing_services.db.web.host}", consumer="api-web"
        )
    msg = str(exc.value)
    assert "${backing_services.<service>.<part>}" in msg
    assert "no core service" in msg
    assert "Did you mean ${backing_services.db.host}?" in msg

    # The two arity messages come from one generator and must stay
    # recognizable siblings.
    with pytest.raises(MagicRefArityError) as core_exc:
        resolver.resolve_in_string(
            "${codebases.api.host}", consumer="api-worker"
        )
    for m in (msg, str(core_exc.value)):
        assert m.endswith("See cicl.md § Magic Refs.")


def test_hyphenated_names_round_trip():
    """Regression pin. A hyphen used to decide whether a ref was *seen* at
    all: `${codebases.my-api.core_services.web.host}` matched neither _MAGIC_RE nor
    _COMPILE_RE and was written verbatim into the emitted compose/HCL."""
    resolver, _ = _make_resolver()
    core = resolver.resolve_in_string(
        "${codebases.my-api.core_services.web.host}", consumer="api-web"
    )
    assert core.value == "p-dev-my-api-web"
    assert "${" not in core.value

    backing = resolver.resolve_in_string(
        "${backing_services.my-db.host}", consumer="api-web"
    )
    assert backing.value == "p-dev-my-db"
    assert "${" not in backing.value


def test_self_reference_rejected():
    resolver, _ = _make_resolver()
    with pytest.raises(SubstitutionError) as exc:
        resolver.resolve_in_string(
            "${codebases.api.core_services.web.host}", consumer="api-web"
        )
    assert "localhost" in str(exc.value)


def test_cycle_through_two_processes_of_one_codebase():
    resolver, _ = _make_resolver()
    resolver.engines["api-web"].provides["host"] = {
        "fixed": "${codebases.api.core_services.worker.host}",
        "elastic": "${codebases.api.core_services.worker.host}",
    }
    resolver.engines["api-worker"].provides["host"] = {
        "fixed": "${codebases.api.core_services.web.host}",
        "elastic": "${codebases.api.core_services.web.host}",
    }
    with pytest.raises(SubstitutionError) as exc:
        resolver.resolve_in_string(
            "${codebases.api.core_services.web.host}", consumer="my-api-web"
        )
    assert "cyclic magic-ref chain" in str(exc.value)


def test_scheduler_service_ref_rejected():
    """Free behavior, pinned deliberately: `scheduler` engines declare
    `provides: {}`, so a scheduler core service publishes no discovery
    surface and cannot be a magic-ref target. This test exists so that a
    future change to tables/roles/scheduler.yml cannot silently open it."""
    resolver, _ = _make_resolver()
    with pytest.raises(SubstitutionError) as exc:
        resolver.resolve_in_string(
            "${codebases.api.core_services.nightly_cleanup.host}", consumer="api-web"
        )
    assert "exposes no parts" in str(exc.value)


def test_dependency_records_target_process():
    resolver, _ = _make_resolver()
    resolver.resolve_in_string(
        "${codebases.api.core_services.web.host}", consumer="api-worker"
    )
    resolver.resolve_in_string(
        "${backing_services.db.host}", consumer="api-worker"
    )
    recorded = [
        (d.consumer, d.target, d.target_service, d.part) for d in resolver.deps
    ]
    assert ("api-worker", "api", "web", "host") in recorded
    assert ("api-worker", "db", None, "host") in recorded


# ---------------------------------------------------------------------------
# Mod 097 — the same rules on the validator surface.
# ---------------------------------------------------------------------------


def _rule_3_issues(
    template: str, *, codebase: str = "api", service: str = "worker"
) -> list:
    """Validate a doc carrying ``template`` in one core service's env.

    Filters to rule 3 — the synthetic document trips unrelated rules, which
    is expected and not this mod's business.
    """
    doc = _make_doc()
    doc.codebases[codebase].core_services[service].env["UPSTREAM"] = template
    issues = validate_document(doc, _make_tables(_engines()))
    return [i for i in issues if i.rule.startswith("rule_3_")]


def test_validator_accepts_four_segment_core_ref():
    assert _rule_3_issues("${codebases.api.core_services.web.host}") == []


def test_validator_flags_three_segment_core_ref_arity():
    hits = _rule_3_issues("${codebases.api.host}")
    assert [i.rule for i in hits] == ["rule_3_magic_ref_arity"]
    assert "${codebases.<codebase>.core_services.<service>.<part>}" in hits[0].message


def test_validator_flags_unknown_service_of_known_codebase():
    hits = _rule_3_issues("${codebases.api.core_services.nope.host}")
    assert [i.rule for i in hits] == ["rule_3_unresolved_magic_ref"]
    assert "declares no core service 'nope'" in hits[0].message
    assert "nightly_cleanup" in hits[0].message
    assert "worker" in hits[0].message


def test_validator_flags_self_reference():
    hits = _rule_3_issues("${codebases.api.core_services.web.host}", service="web")
    assert [i.rule for i in hits] == ["rule_3_self_magic_ref"]
    assert "localhost" in hits[0].message

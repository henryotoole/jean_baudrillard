"""Tests for the magic-ref resolver."""

from __future__ import annotations

import pytest

from docex.cicl.magic_refs import MagicRefResolver, find_magic_refs
from docex.cicl.model import (
    BackingService,
    CICLDocument,
    CoreService,
    Resources,
)
from docex.cicl.transfer import EngineEntry, TransferTables
from docex.errors import SubstitutionError


def _make_resolver(foundation: str = "fixed") -> tuple[MagicRefResolver, EngineEntry]:
    """Build a resolver wired up to a minimal postgres engine.

    Returns (resolver, db_engine) so tests can pre-populate engines
    in arbitrary topologies.
    """
    db_engine = EngineEntry(
        role="relational_db",
        engine="postgres",
        foundation="both",
        provides={
            "host": {"fixed": "${global_service_name}", "elastic": "@aws_db_instance.${name}.endpoint"},
            "port": {"fixed": "${port}", "elastic": "${port}"},
            "user": {"fixed": "$[POSTGRES_USER]", "elastic": "$[POSTGRES_USER]"},
        },
        env={"POSTGRES_USER": "the postgres user"},
        naming="rds",
    )
    api_engine = EngineEntry(
        role="web",
        engine="container",
        foundation="both",
        provides={
            "host": {"fixed": "${global_service_name}", "elastic": "${global_service_name}"},
        },
        naming="ecs",
    )
    doc = CICLDocument(
        cicl_version="1",
        foundation=foundation,
        domain="example.com",
        container_registry="reg.example.com",
        core_services={
            "api": CoreService(
                role="web",
                networks=["web", "internal"],
                resources=Resources(cpu=1.0, memory="2GB"),
                depends_on=["db"],
                port=8080,
                env={},
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
        },
    )
    tables = TransferTables(
        by_role={
            "relational_db": {"postgres": db_engine},
            "web": {"container": api_engine},
        }
    )
    resolver = MagicRefResolver(
        doc=doc,
        tables=tables,
        foundation=foundation,
        contexts={
            "api": {
                "name": "api",
                "global_service_name": "p-dev-api",
                "port": 8080,
                "project_name": "p", "env_name": "dev", "role_name": "web",
                "env_subdomain": "dev.example.com",
            },
            "db": {
                "name": "db",
                "global_service_name": "p-dev-db",
                "port": 5432,
                "project_name": "p", "env_name": "dev", "role_name": "relational_db",
                "env_subdomain": "dev.example.com",
            },
        },
        engines={"api": api_engine, "db": db_engine},
    )
    return resolver, db_engine


def test_find_magic_refs():
    refs = find_magic_refs("a ${backing_services.x.y} b ${core_services.z.w} c")
    assert refs == [
        ("backing_services", "x", "y"),
        ("core_services", "z", "w"),
    ]


def test_resolve_simple_magic_ref():
    resolver, _ = _make_resolver()
    rendered = resolver.resolve_in_string(
        "${backing_services.db.host}", consumer="api"
    )
    assert rendered.value == "p-dev-db"


def test_resolve_secret_part_propagates_runtime_ref():
    """A magic ref to a secret part (whose template is a bare $[VAR])
    resolves to that ref and propagates the VAR into the consumer's
    runtime refs, so the compiler can wire it into the container."""
    resolver, _ = _make_resolver()
    rendered = resolver.resolve_in_string(
        "${backing_services.db.user}", consumer="api"
    )
    assert rendered.value == "$[POSTGRES_USER]"
    assert "POSTGRES_USER" in rendered.runtime_refs
    assert "POSTGRES_USER" in resolver.runtime_refs["api"]


def test_magic_ref_hcl_passthrough_on_elastic():
    resolver, _ = _make_resolver(foundation="elastic")
    rendered = resolver.resolve_in_string(
        "${backing_services.db.host}", consumer="api"
    )
    assert rendered.raw_hcl is True
    assert "aws_db_instance.db.endpoint" in rendered.value


def test_magic_ref_unknown_service():
    resolver, _ = _make_resolver()
    with pytest.raises(SubstitutionError):
        resolver.resolve_in_string(
            "${backing_services.nope.host}", consumer="api"
        )


def test_magic_ref_unknown_part():
    resolver, _ = _make_resolver()
    with pytest.raises(SubstitutionError):
        resolver.resolve_in_string(
            "${backing_services.db.nope}", consumer="api"
        )


def test_dependency_tracking():
    resolver, _ = _make_resolver()
    resolver.resolve_in_string(
        "${backing_services.db.host}", consumer="api"
    )
    deps = [(d.consumer, d.target, d.part) for d in resolver.deps]
    assert ("api", "db", "host") in deps


def test_magic_ref_empty_resolution_errors():
    """A magic ref to a part that resolves to empty (e.g. an unset port
    with no engine default) is a hard error, not a silent empty emit."""
    resolver, _ = _make_resolver()
    # Simulate a db with neither a declared port nor an engine
    # default: the port context var is empty, so ${port} resolves to "".
    resolver.contexts["db"]["port"] = ""
    with pytest.raises(SubstitutionError):
        resolver.resolve_in_string(
            "${backing_services.db.port}", consumer="api"
        )

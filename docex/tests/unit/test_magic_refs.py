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
            "url": {"fixed": "postgres://$[POSTGRES_USER]@${global_service_name}:${port}/${name}"},
        },
        env={"POSTGRES_USER": "the postgres user"},
        naming={"separator": "hyphen", "case": "lower", "max_len": 63},
    )
    api_engine = EngineEntry(
        role="web",
        engine="container",
        foundation="both",
        provides={
            "host": {"fixed": "${global_service_name}", "elastic": "${global_service_name}"},
        },
        naming={"separator": "hyphen", "case": "lower", "max_len": 63},
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
                depends_on=["database"],
                port=8080,
                env={},
            ),
        },
        backing_services={
            "database": BackingService(
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
            "database": {
                "name": "database",
                "global_service_name": "p-dev-database",
                "port": 5432,
                "project_name": "p", "env_name": "dev", "role_name": "relational_db",
                "env_subdomain": "dev.example.com",
            },
        },
        engines={"api": api_engine, "database": db_engine},
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
        "${backing_services.database.host}", consumer="api"
    )
    assert rendered.value == "p-dev-database"


def test_resolve_magic_ref_chain_with_runtime_refs():
    """A magic ref pointing at a template that itself contains $[VAR]
    propagates the VAR into the consumer's runtime refs."""
    resolver, _ = _make_resolver()
    rendered = resolver.resolve_in_string(
        "${backing_services.database.url}", consumer="api"
    )
    # The DB url template renders out to the fixed form.
    assert "postgres://" in rendered.value
    assert "p-dev-database" in rendered.value
    assert "POSTGRES_USER" in rendered.runtime_refs
    assert "POSTGRES_USER" in resolver.runtime_refs["api"]


def test_magic_ref_hcl_passthrough_on_elastic():
    resolver, _ = _make_resolver(foundation="elastic")
    rendered = resolver.resolve_in_string(
        "${backing_services.database.host}", consumer="api"
    )
    assert rendered.raw_hcl is True
    assert "aws_db_instance.database.endpoint" in rendered.value


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
            "${backing_services.database.nope}", consumer="api"
        )


def test_dependency_tracking():
    resolver, _ = _make_resolver()
    resolver.resolve_in_string(
        "${backing_services.database.host}", consumer="api"
    )
    deps = [(d.consumer, d.target, d.part) for d in resolver.deps]
    assert ("api", "database", "host") in deps

"""Unit tests for the `docex roles` / `docex role` reference commands."""

from __future__ import annotations

import json

from docex.cicl.transfer import load_transfer_tables
from docex.roles import describe_role, list_roles


def _tables():
    # Bundled tables only — no project-local extensions needed here.
    return load_transfer_tables(None)


_ALL_ROLES = {"web", "relational_db", "cache", "object_store", "reverse_proxy"}


def test_loader_parses_role_descriptions():
    tables = _tables()
    assert tables.description("relational_db") == "Relational database backing service."
    # The reserved `description` key must NOT be parsed as an engine.
    assert "description" not in tables.role("relational_db")
    assert set(tables.roles()) >= _ALL_ROLES


def test_list_roles_text(capsys):
    rc = list_roles(_tables(), fmt="text")
    assert rc == 0
    out = capsys.readouterr().out
    for role in _ALL_ROLES:
        assert role in out


def test_list_roles_llm(capsys):
    rc = list_roles(_tables(), fmt="llm")
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    names = {r["name"] for r in payload["roles"]}
    assert names >= _ALL_ROLES
    db = next(r for r in payload["roles"] if r["name"] == "relational_db")
    assert db["description"] == "Relational database backing service."
    assert db["engines"] == ["postgres"]


def test_describe_role_text(capsys):
    rc = describe_role(_tables(), "relational_db", fmt="text")
    assert rc == 0
    out = capsys.readouterr().out
    assert "postgres" in out
    assert "default_port: 5432" in out
    assert "(secret)" in out  # user/password parts are flagged


def test_describe_role_llm(capsys):
    rc = describe_role(_tables(), "relational_db", fmt="llm")
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["role"] == "relational_db"
    eng = payload["engines"][0]
    assert eng["name"] == "postgres"
    assert eng["default_port"] == 5432
    assert set(eng["parts"]) == {"host", "port", "db", "user", "password"}
    assert eng["parts"]["user"]["secret"] is True
    assert eng["parts"]["host"]["secret"] is False
    assert eng["parts"]["host"]["foundations"] == ["elastic", "fixed"]


def test_describe_role_multi_engine_llm(capsys):
    """object_store splits engines per foundation (minio fixed, s3 elastic)."""
    rc = describe_role(_tables(), "object_store", fmt="llm")
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert {e["name"] for e in payload["engines"]} == {"minio", "s3"}


def test_describe_role_unknown_returns_1(capsys):
    rc = describe_role(_tables(), "bogus", fmt="text")
    assert rc == 1

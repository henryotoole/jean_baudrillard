"""Mod 077 — the compiler inlines `kind: fixed` engine env vars.

A `$[VAR]` token naming a `kind: fixed` engine env var (postgres'
``POSTGRES_USER`` → ``appuser``) is resolved to its literal ``value:`` at
compile time and never reaches the runtime layer. ``minted``/``secret``
vars (``POSTGRES_PASSWORD``) stay as runtime pass-through refs.

These tests prove fixed→literal on both foundations and at both
resolution sites (the backing body and the ``provides:`` template a core
consumer reads through). See transfer_tables.md § Anatomy of a Role
Definition and the postgres walking example.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from docex.cicl.compile import run_compile
from docex.context import load_project_context

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project"
_ELASTIC = _FIXTURES / "sample_project_elastic"


def _compile(fixture: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(fixture, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    assert run_compile(ctx) == 0
    return dest


def _svc(compose: dict, suffix: str) -> dict:
    return next(b for k, b in compose["services"].items() if k.endswith(suffix))


# ---------------------------------------------------------------------------
# Fixed foundation
# ---------------------------------------------------------------------------


def test_fixed_backing_body_inlines_fixed_user(tmp_path: Path):
    """Site 1: the postgres backing body. POSTGRES_USER (fixed) is the
    literal ``appuser``; POSTGRES_PASSWORD (minted) survives as a compose
    runtime ref."""
    dest = _compile(_FIXED, tmp_path)
    compose = yaml.safe_load(
        (dest / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    )
    db = _svc(compose, "appdb")
    assert db["environment"]["POSTGRES_USER"] == "appuser"
    assert db["environment"]["POSTGRES_PASSWORD"] == "${POSTGRES_PASSWORD}"


def test_fixed_healthcheck_inlines_fixed_user(tmp_path: Path):
    """The healthcheck test string carries the inlined literal, not a ref."""
    dest = _compile(_FIXED, tmp_path)
    compose = yaml.safe_load(
        (dest / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    )
    db = _svc(compose, "appdb")
    test = " ".join(db["healthcheck"]["test"])
    assert "pg_isready -U appuser" in test
    assert "POSTGRES_USER" not in test


def test_fixed_core_consumer_inlines_via_provides(tmp_path: Path):
    """Site 2: a core service reading ``${backing.appdb.user}`` gets the
    inlined literal through the provider's ``provides.user`` template,
    while ``${backing.appdb.password}`` stays a runtime ref."""
    dest = _compile(_FIXED, tmp_path)
    compose = yaml.safe_load(
        (dest / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    )
    api = _svc(compose, "api")
    assert api["environment"]["DATABASE_USER"] == "appuser"
    assert api["environment"]["DATABASE_PASSWORD"] == "${POSTGRES_PASSWORD}"


def test_fixed_no_user_ref_survives(tmp_path: Path):
    """No POSTGRES_USER *reference* survives in the compiled compose output.

    The postgres container's ``environment`` key ``POSTGRES_USER: appuser``
    is legitimate (that is how the engine is configured); what must be gone
    is any unresolved runtime ref — the bare ``$[POSTGRES_USER]`` and the
    compose ``${POSTGRES_USER}`` interpolation forms."""
    dest = _compile(_FIXED, tmp_path)
    compose = (dest / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    assert "$[POSTGRES_USER]" not in compose
    assert "${POSTGRES_USER}" not in compose


# ---------------------------------------------------------------------------
# Elastic foundation
# ---------------------------------------------------------------------------


def test_elastic_rds_username_is_literal(tmp_path: Path):
    """The RDS instance body carries the inlined literal username."""
    dest = _compile(_ELASTIC, tmp_path)
    tf = (dest / "infra" / "output" / "prod" / "main.tf").read_text()
    assert 'username = "appuser"' in tf


def test_elastic_only_password_reaches_ssm(tmp_path: Path):
    """Exactly one SSM data source for the DB (POSTGRES_PASSWORD); the
    fixed POSTGRES_USER never reaches SSM at all."""
    dest = _compile(_ELASTIC, tmp_path)
    tf = (dest / "infra" / "output" / "prod" / "main.tf").read_text()
    ssm = re.findall(r'data "aws_ssm_parameter" "([a-z0-9_]+)"', tf)
    assert ssm == ["appdb_postgres_password"]
    assert "POSTGRES_USER" not in tf
    assert "POSTGRES_PASSWORD" in tf


def test_elastic_consumer_user_is_plain_env_password_is_secret(tmp_path: Path):
    """The consumer task-def carries DATABASE_USER as a plain environment
    literal (``appuser``) and DATABASE_PASSWORD as a secrets[] entry whose
    valueFrom points at the POSTGRES_PASSWORD SSM path."""
    dest = _compile(_ELASTIC, tmp_path)
    tf = (dest / "infra" / "output" / "prod" / "main.tf").read_text()
    # DATABASE_USER inlined as a plain environment entry.
    assert 'name = "DATABASE_USER"' in tf
    assert 'value = "appuser"' in tf
    # DATABASE_PASSWORD is a secret sourced from SSM.
    assert 'name = "DATABASE_PASSWORD"' in tf
    assert "/prod/POSTGRES_PASSWORD" in tf
    # No unresolved runtime ref survives.
    assert "$[" not in tf

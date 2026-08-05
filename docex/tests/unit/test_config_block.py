"""Mod 078 — a core-service `config:` key compiles to the same runtime-ref
shape as a secret on both foundations, and never leaks into the secret manifest.

A `config:` key is wired at compile as a self-referential runtime ref
(`env_block[KEY] = "$[KEY]"`), so it flows through the *existing* secret
emit paths unchanged: compose `${KEY}` on fixed, an ECS `secrets[]`
`valueFrom` an SSM path on elastic. No emitter changes. See the overview
and config_and_secrets.md.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from docex.cicl.categories import secret_manifest
from docex.cicl.compile import run_compile
from docex.context import load_project_context

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project"
_ELASTIC = _FIXTURES / "sample_project_elastic"


def _copy_with_api_config(fixture: Path, dest: Path) -> Path:
    """Copy a fixture and add a `config:` block to its `api` core service."""
    shutil.copytree(fixture, dest, symlinks=False, dirs_exist_ok=False)
    infra_path = dest / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["codebases"]["api"]["config"] = {
        "PARTNER_URL": "Partner API base URL (per-env)"
    }
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return dest


def _svc(compose: dict, suffix: str) -> dict:
    return next(b for k, b in compose["services"].items() if k.endswith(suffix))


def test_fixed_config_key_wired_as_compose_runtime_ref(tmp_path: Path):
    dest = _copy_with_api_config(_FIXED, tmp_path / "project")
    ctx = load_project_context(dest)
    assert run_compile(ctx) == 0
    compose = yaml.safe_load(
        (dest / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    )
    api = _svc(compose, "api-web")
    # Same shape as a secret: a compose ${KEY} interpolation ref.
    assert api["environment"]["PARTNER_URL"] == "${PARTNER_URL}"


def test_elastic_config_key_wired_as_ecs_secret(tmp_path: Path):
    dest = _copy_with_api_config(_ELASTIC, tmp_path / "project")
    ctx = load_project_context(dest)
    assert run_compile(ctx) == 0
    tf = (dest / "infra" / "output" / "prod" / "main.tf").read_text()
    # A config key rides the existing secrets[] path: a container secret named
    # after the key, valueFrom the /<project>/<env>/PARTNER_URL SSM path.
    assert 'name = "PARTNER_URL"' in tf
    assert "/prod/PARTNER_URL" in tf
    # No unresolved runtime ref survives.
    assert "$[PARTNER_URL]" not in tf


def test_config_key_absent_from_secret_manifest(tmp_path: Path):
    """The secret manifest is secrets-only; a `config:` key must not appear
    in it (config values float in infra/config/<env>.env)."""
    dest = _copy_with_api_config(_FIXED, tmp_path / "project")
    ctx = load_project_context(dest)
    assert run_compile(ctx) == 0
    keys = {e.key for e in secret_manifest(ctx.infra, ctx.transfer_tables)}
    assert "PARTNER_URL" not in keys

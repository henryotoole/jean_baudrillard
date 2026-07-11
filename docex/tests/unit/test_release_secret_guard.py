"""Mod 091 — the release-time required-secret guard
(`pipeline/release.py::_require_secrets_present`).

A stage/prod release aborts if any *required secret* (core `secrets:` +
backing `kind: secret` + doctrine-injected `TELEMETRY_API_KEY`) is unset
(absent or empty) in `infra/secrets/<env>.env`. TTE (docex-minted) and config
(non-secret) never gate a release. See config_and_secrets.md § Required-Secret
Guard.

The guard is pure (local env-file read + raise), crosses no docker/AWS/git
boundary, so it is exercised here with unit tests only. The `sample_project`
fixture supplies a postgres backing (POSTGRES_PASSWORD → minted TTE, the
negative control); we add a bespoke core secret (STRIPE_KEY) and a config key
(PARTNER_URL) so all three categories are represented.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from docex.context import load_project_context
from docex.envfile import write_env_file
from docex.errors import RequiredSecretsUnset
from docex.pipeline.release import _require_secrets_present

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_project"


def _ctx(dest: Path):
    """Copy the sample fixture, give its `api` service a bespoke secret + a
    config key, and load a ProjectContext against it. Required secrets for the
    result: TELEMETRY_API_KEY (doctrine) + STRIPE_KEY (core). TTE:
    POSTGRES_PASSWORD. Config: PARTNER_URL."""
    shutil.copytree(_FIXTURE, dest, symlinks=False, dirs_exist_ok=False)
    infra_path = dest / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["core_services"]["api"]["secrets"] = {"STRIPE_KEY": "Stripe secret API key"}
    doc["core_services"]["api"]["config"] = {
        "PARTNER_URL": "Partner API base URL (per-env)"
    }
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return load_project_context(dest)


def _write(ctx, env: str, values: dict[str, str]) -> None:
    write_env_file(
        ctx.project_root / "infra" / "secrets" / f"{env}.env", values
    )


def test_all_required_secrets_set_does_not_raise(tmp_path: Path):
    ctx = _ctx(tmp_path / "project")
    _write(ctx, "stage", {"TELEMETRY_API_KEY": "tk", "STRIPE_KEY": "sk"})
    _require_secrets_present(ctx, "stage")  # no raise


def test_empty_required_core_secret_raises(tmp_path: Path):
    ctx = _ctx(tmp_path / "project")
    _write(ctx, "stage", {"TELEMETRY_API_KEY": "tk", "STRIPE_KEY": ""})
    with pytest.raises(RequiredSecretsUnset) as exc:
        _require_secrets_present(ctx, "stage")
    assert "STRIPE_KEY" in exc.value.keys
    assert "STRIPE_KEY" in str(exc.value)


def test_absent_required_core_secret_raises(tmp_path: Path):
    ctx = _ctx(tmp_path / "project")
    _write(ctx, "stage", {"TELEMETRY_API_KEY": "tk"})  # STRIPE_KEY absent
    with pytest.raises(RequiredSecretsUnset) as exc:
        _require_secrets_present(ctx, "stage")
    assert "STRIPE_KEY" in exc.value.keys


def test_missing_secrets_file_lists_every_required_key(tmp_path: Path):
    ctx = _ctx(tmp_path / "project")
    (ctx.project_root / "infra" / "secrets" / "stage.env").unlink()
    with pytest.raises(RequiredSecretsUnset) as exc:
        _require_secrets_present(ctx, "stage")
    # read_env_file returns {} for a missing file → all required keys unset.
    assert set(exc.value.keys) == {"TELEMETRY_API_KEY", "STRIPE_KEY"}


def test_doctrine_injected_telemetry_key_is_required(tmp_path: Path):
    ctx = _ctx(tmp_path / "project")
    _write(ctx, "stage", {"STRIPE_KEY": "sk"})  # TELEMETRY_API_KEY absent
    with pytest.raises(RequiredSecretsUnset) as exc:
        _require_secrets_present(ctx, "stage")
    assert "TELEMETRY_API_KEY" in exc.value.keys


def test_tte_key_absent_or_empty_does_not_gate(tmp_path: Path):
    ctx = _ctx(tmp_path / "project")
    # Required secrets set; POSTGRES_PASSWORD (TTE) absent, then explicitly
    # empty — neither may gate the release.
    _write(ctx, "stage", {"TELEMETRY_API_KEY": "tk", "STRIPE_KEY": "sk"})
    _require_secrets_present(ctx, "stage")  # no raise (TTE absent)
    _write(
        ctx,
        "stage",
        {"TELEMETRY_API_KEY": "tk", "STRIPE_KEY": "sk", "POSTGRES_PASSWORD": ""},
    )
    _require_secrets_present(ctx, "stage")  # no raise (TTE empty)


def test_config_key_absent_or_empty_does_not_gate(tmp_path: Path):
    ctx = _ctx(tmp_path / "project")
    _write(
        ctx,
        "stage",
        {"TELEMETRY_API_KEY": "tk", "STRIPE_KEY": "sk", "PARTNER_URL": ""},
    )
    _require_secrets_present(ctx, "stage")  # no raise (config never gates)

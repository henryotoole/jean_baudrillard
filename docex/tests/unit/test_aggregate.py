"""Mod 080 — aggregation machinery (`orchestrate/aggregate.py`).

`ensure_tte` mints-if-absent into the authoritative dev/test store
(`infra/tte/<env>.env`) and never re-mints on a re-run. `aggregate`
writes the derived `.docex/agg/<env>.env` = TTE ∪ secrets ∪ config,
defends against a cross-source key collision (compile guarantees
disjointness — rule 20), and refuses stage/prod until Mods 081/082.
See config_and_secrets.md § Aggregation, § TTE Vars.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.envfile import read_env_file, write_env_file
from docex.errors import AggregationError
from docex.orchestrate.aggregate import (
    aggregate,
    aggregate_path,
    ensure_tte,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _postgres_ctx(tmp_path, *, secrets=None, config=None):
    """A fresh postgres-backed project (the ``sample_project`` fixture) with
    optional bespoke ``infra/secrets/dev.env`` + ``infra/config/dev.env``.

    The fixture's committed dev secrets file is comment-only (engine-managed
    keys live in the TTE store), so tests supply their own disjoint content.
    """
    fixture = _REPO_ROOT / "tests" / "fixtures" / "sample_project"
    dest = tmp_path / "proj"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    write_env_file(dest / "infra" / "secrets" / "dev.env", secrets or {})
    write_env_file(dest / "infra" / "config" / "dev.env", config or {})
    return load_project_context(dest)


def test_ensure_tte_mints_postgres_password_when_absent(tmp_path):
    ctx = _postgres_ctx(tmp_path)
    store = ctx.project_root / "infra" / "tte" / "dev.env"
    assert not store.exists()

    minted = ensure_tte(ctx, env="dev")
    assert "POSTGRES_PASSWORD" in minted
    assert minted["POSTGRES_PASSWORD"]  # non-empty
    # It was persisted to the authoritative store.
    assert read_env_file(store)["POSTGRES_PASSWORD"] == minted["POSTGRES_PASSWORD"]


def test_ensure_tte_reuses_existing_value_on_rerun(tmp_path):
    ctx = _postgres_ctx(tmp_path)
    first = ensure_tte(ctx, env="dev")["POSTGRES_PASSWORD"]
    second = ensure_tte(ctx, env="dev")["POSTGRES_PASSWORD"]
    assert first == second  # no re-mint


def test_ensure_tte_preserves_a_preexisting_value(tmp_path):
    ctx = _postgres_ctx(tmp_path)
    store = ctx.project_root / "infra" / "tte" / "dev.env"
    write_env_file(store, {"POSTGRES_PASSWORD": "preset-value"})
    minted = ensure_tte(ctx, env="dev")
    assert minted["POSTGRES_PASSWORD"] == "preset-value"


def test_aggregate_writes_union_of_three_sources(tmp_path):
    ctx = _postgres_ctx(
        tmp_path,
        secrets={"STRIPE_KEY": "sk_test_abc"},
        config={"PARTNER_URL": "https://partner.example"},
    )
    out = aggregate(ctx, env="dev")
    assert out == aggregate_path(ctx, "dev")
    assert out.is_file()

    merged = read_env_file(out)
    # A minted TTE value...
    assert merged["POSTGRES_PASSWORD"]
    # ...a bespoke secret...
    assert merged["STRIPE_KEY"] == "sk_test_abc"
    # ...and a config value.
    assert merged["PARTNER_URL"] == "https://partner.example"
    # The aggregate password matches the persisted TTE store.
    store = read_env_file(ctx.project_root / "infra" / "tte" / "dev.env")
    assert merged["POSTGRES_PASSWORD"] == store["POSTGRES_PASSWORD"]


def test_aggregate_defensive_collision_raises(tmp_path):
    # A secret that shadows the minted TTE key — compile would have caught
    # this (rule 20); aggregation refuses defensively.
    ctx = _postgres_ctx(tmp_path, secrets={"POSTGRES_PASSWORD": "shadow"})
    with pytest.raises(AggregationError):
        aggregate(ctx, env="dev")


def test_aggregate_rejects_stage(tmp_path):
    ctx = _postgres_ctx(tmp_path)
    with pytest.raises(AggregationError) as exc:
        aggregate(ctx, env="stage")
    assert "081/082" in str(exc.value)

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
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.envfile import read_env_file, write_env_file
from docex.errors import AggregationError
from docex.errors import SSMPushFailed
from docex.orchestrate.aggregate import (
    aggregate,
    aggregate_elastic,
    aggregate_fixed_prod,
    aggregate_path,
    ensure_tte,
    ensure_tte_elastic,
    ensure_tte_fixed,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _postgres_ctx(tmp_path, *, env="dev", secrets=None, config=None):
    """A fresh postgres-backed project (the ``sample_project`` fixture) with
    optional bespoke ``infra/secrets/<env>.env`` + ``infra/config/<env>.env``.

    The fixture's committed secrets files are comment-only (engine-managed
    keys live in the TTE store), so tests supply their own disjoint content.
    """
    fixture = _REPO_ROOT / "tests" / "fixtures" / "sample_project"
    dest = tmp_path / "proj"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    write_env_file(dest / "infra" / "secrets" / f"{env}.env", secrets or {})
    write_env_file(dest / "infra" / "config" / f"{env}.env", config or {})
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


# ---------------------------------------------------------------------------
# Mod 081 — fixed stage/prod release aggregation.
# ---------------------------------------------------------------------------


@dataclass
class _StubSSH:
    """Minimal ``SSHClient`` stub — ``capture`` returns a canned host
    tte.env string. Local to the module so it doesn't depend on the
    repo's (ambiguous) shared conftest import."""

    capture_out: str = ""
    capture_rc: int = 0
    calls: list = field(default_factory=list)

    def run(self, host, key_path, command, *, user="deploy"):
        self.calls.append(("run", host, str(key_path), command, user))
        return 0

    def capture(self, host, key_path, command, *, user="deploy"):
        self.calls.append(("capture", host, str(key_path), command, user))
        return (self.capture_rc, self.capture_out)


def _fake_ssh(*, out="", rc=0):
    return _StubSSH(capture_out=out, capture_rc=rc)


def test_ensure_tte_fixed_mints_when_host_store_empty(tmp_path):
    ctx = _postgres_ctx(tmp_path, env="stage")
    ssh = _fake_ssh(out="")  # host store not yet provisioned
    key = ctx.project_root / "infra" / "deploy_creds" / "stage"

    minted = ensure_tte_fixed(ctx, env="stage", ssh=ssh, key=key)
    assert minted["POSTGRES_PASSWORD"]  # freshly minted
    # It was staged to the control-node file for ansible to render back.
    staged = ctx.project_root / ".docex" / "agg" / "stage.tte.env"
    assert read_env_file(staged)["POSTGRES_PASSWORD"] == minted["POSTGRES_PASSWORD"]
    # The read went to the host over SSH, capturing tte.env.
    assert any(c[0] == "capture" and "tte.env" in c[3] for c in ssh.calls)


def test_ensure_tte_fixed_reads_host_store_with_sudo(tmp_path):
    """Mod 089: the host tte.env is rendered root:root 0600 by the playbook,
    so the `deploy` SSH user must `sudo` to read it. Reading without sudo
    returns "Permission denied" (masked into an empty read), which would make
    docex re-mint every release and lock the live DB out of its own credential.
    Guard that the capture command uses `sudo cat`."""
    ctx = _postgres_ctx(tmp_path, env="stage")
    ssh = _fake_ssh(out="POSTGRES_PASSWORD=live\n")
    key = ctx.project_root / "infra" / "deploy_creds" / "stage"

    ensure_tte_fixed(ctx, env="stage", ssh=ssh, key=key)

    tte_reads = [
        c for c in ssh.calls if c[0] == "capture" and "tte.env" in c[3]
    ]
    assert tte_reads, ssh.calls
    assert all("sudo cat" in c[3] for c in tte_reads), tte_reads


def test_ensure_tte_fixed_preserves_host_value_no_remint(tmp_path):
    ctx = _postgres_ctx(tmp_path, env="stage")
    ssh = _fake_ssh(out="POSTGRES_PASSWORD=live\n")
    key = ctx.project_root / "infra" / "deploy_creds" / "stage"

    minted = ensure_tte_fixed(ctx, env="stage", ssh=ssh, key=key)
    assert minted["POSTGRES_PASSWORD"] == "live"  # host value wins, no re-mint
    staged = ctx.project_root / ".docex" / "agg" / "stage.tte.env"
    assert read_env_file(staged)["POSTGRES_PASSWORD"] == "live"


def test_ensure_tte_fixed_ssh_unreachable_raises(tmp_path):
    ctx = _postgres_ctx(tmp_path, env="stage")
    ssh = _fake_ssh(rc=255)
    key = ctx.project_root / "infra" / "deploy_creds" / "stage"

    with pytest.raises(AggregationError) as exc:
        ensure_tte_fixed(ctx, env="stage", ssh=ssh, key=key)
    assert "255" in str(exc.value)


def test_aggregate_fixed_prod_unions_host_tte_secrets_config(tmp_path):
    ctx = _postgres_ctx(
        tmp_path,
        env="stage",
        secrets={"STRIPE_KEY": "sk_live_abc"},
        config={"PARTNER_URL": "https://partner.example"},
    )
    ssh = _fake_ssh(out="POSTGRES_PASSWORD=live\n")
    key = ctx.project_root / "infra" / "deploy_creds" / "stage"

    agg, staged = aggregate_fixed_prod(ctx, env="stage", ssh=ssh, key=key)
    assert agg == aggregate_path(ctx, "stage")
    assert staged == ctx.project_root / ".docex" / "agg" / "stage.tte.env"

    merged = read_env_file(agg)
    assert merged["POSTGRES_PASSWORD"] == "live"      # from the host store
    assert merged["STRIPE_KEY"] == "sk_live_abc"      # bespoke secret
    assert merged["PARTNER_URL"] == "https://partner.example"  # config


def test_aggregate_fixed_prod_secrets_tte_collision_raises(tmp_path):
    # A secret that shadows the minted TTE key — compile would have caught
    # this (rule 20); aggregation refuses defensively.
    ctx = _postgres_ctx(
        tmp_path, env="stage", secrets={"POSTGRES_PASSWORD": "shadow"}
    )
    ssh = _fake_ssh(out="POSTGRES_PASSWORD=live\n")
    key = ctx.project_root / "infra" / "deploy_creds" / "stage"
    with pytest.raises(AggregationError):
        aggregate_fixed_prod(ctx, env="stage", ssh=ssh, key=key)


def test_aggregate_fixed_prod_rejects_dev(tmp_path):
    ctx = _postgres_ctx(tmp_path, env="dev")
    ssh = _fake_ssh()
    key = ctx.project_root / "infra" / "deploy_creds" / "dev"
    with pytest.raises(AggregationError):
        aggregate_fixed_prod(ctx, env="dev", ssh=ssh, key=key)


# ---------------------------------------------------------------------------
# Mod 082 — elastic stage/prod release aggregation (SSM push).
# ---------------------------------------------------------------------------
#
# On elastic there is no aggregate FILE — the SSM prefix /<project>/<env>/ IS
# the aggregate. TTE is minted-if-absent (put-if-absent, SSM is authoritative;
# never clobber the live RDS credential), secrets overwrite as SecureString,
# config overwrite as String. Tests use the FakeAWSClient's in-memory SSM.


def _elastic_ctx(tmp_path, *, env="stage", secrets=None, config=None):
    """A fresh elastic postgres-backed project (``sample_project_elastic``),
    with optional bespoke secrets/config files written for ``env``. The
    committed secrets file is comment-only (engine creds are minted TTE)."""
    fixture = _REPO_ROOT / "tests" / "fixtures" / "sample_project_elastic"
    dest = tmp_path / "proj_elastic"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    if secrets is not None:
        write_env_file(dest / "infra" / "secrets" / f"{env}.env", secrets)
    if config is not None:
        write_env_file(dest / "infra" / "config" / f"{env}.env", config)
    return load_project_context(dest)


def test_ensure_tte_elastic_mints_when_ssm_empty(tmp_path, fake_aws):
    ctx = _elastic_ctx(tmp_path)
    minted = ensure_tte_elastic(ctx, env="stage", aws=fake_aws)
    assert minted == 1
    path = "/sample/stage/POSTGRES_PASSWORD"
    value, ptype = fake_aws.ssm_store[path]
    assert value  # non-empty generated credential
    assert ptype == "SecureString"
    # Put-if-absent: it was minted with overwrite=False.
    put = [c for c in fake_aws.calls if c[0] == "ssm_put_parameter"]
    assert put and put[0][2]["overwrite"] is False


def test_ensure_tte_elastic_preserves_live_value_no_remint(tmp_path, fake_aws):
    """SSM is authoritative on elastic: a present TTE param is never re-minted
    or clobbered (the lost-copy → RDS-lockout hazard)."""
    ctx = _elastic_ctx(tmp_path)
    path = "/sample/stage/POSTGRES_PASSWORD"
    fake_aws.ssm_store[path] = ("live-rds-password", "SecureString")

    minted = ensure_tte_elastic(ctx, env="stage", aws=fake_aws)
    assert minted == 0
    # The live value is untouched — no put was issued for it.
    assert fake_aws.ssm_store[path] == ("live-rds-password", "SecureString")
    assert not [c for c in fake_aws.calls if c[0] == "ssm_put_parameter"]


def test_aggregate_elastic_pushes_all_three_categories(tmp_path, fake_aws):
    ctx = _elastic_ctx(
        tmp_path,
        secrets={"STRIPE_KEY": "sk_live_abc"},
        config={"PARTNER_URL": "https://partner.example"},
    )
    n = aggregate_elastic(ctx, env="stage", aws=fake_aws)
    assert n == 3  # 1 minted TTE + 1 secret + 1 config

    store = fake_aws.ssm_store
    # TTE — SecureString, minted-if-absent.
    assert store["/sample/stage/POSTGRES_PASSWORD"][1] == "SecureString"
    # secret — SecureString, overwritten.
    assert store["/sample/stage/STRIPE_KEY"] == ("sk_live_abc", "SecureString")
    # config — String (non-secret; fine in task defs/logs), overwritten.
    assert store["/sample/stage/PARTNER_URL"] == (
        "https://partner.example",
        "String",
    )
    # secrets/config were pushed with overwrite=True.
    puts = {c[1][0]: c[2] for c in fake_aws.calls if c[0] == "ssm_put_parameter"}
    assert puts["/sample/stage/STRIPE_KEY"]["overwrite"] is True
    assert puts["/sample/stage/PARTNER_URL"]["overwrite"] is True


def test_aggregate_elastic_preserves_live_tte_but_repushes_rest(tmp_path, fake_aws):
    """A present TTE value stays put (0 minted) while secrets/config are still
    overwritten — the rollback-safe shape."""
    ctx = _elastic_ctx(tmp_path, secrets={"STRIPE_KEY": "sk_new"})
    fake_aws.ssm_store["/sample/stage/POSTGRES_PASSWORD"] = ("live", "SecureString")

    n = aggregate_elastic(ctx, env="stage", aws=fake_aws)
    assert n == 1  # 0 minted + 1 secret
    assert fake_aws.ssm_store["/sample/stage/POSTGRES_PASSWORD"] == (
        "live",
        "SecureString",
    )
    assert fake_aws.ssm_store["/sample/stage/STRIPE_KEY"] == ("sk_new", "SecureString")


def test_aggregate_elastic_secret_tte_collision_raises(tmp_path, fake_aws):
    # A secret shadowing the minted TTE key — compile would have caught this
    # (rule 20); aggregation refuses defensively before any SSM write.
    ctx = _elastic_ctx(tmp_path, secrets={"POSTGRES_PASSWORD": "shadow"})
    with pytest.raises(AggregationError):
        aggregate_elastic(ctx, env="stage", aws=fake_aws)
    assert fake_aws.ssm_store == {}  # nothing pushed


def test_aggregate_elastic_rejects_dev(tmp_path, fake_aws):
    ctx = _elastic_ctx(tmp_path, env="dev")
    with pytest.raises(AggregationError):
        aggregate_elastic(ctx, env="dev", aws=fake_aws)


def test_aggregate_elastic_wraps_put_failure_as_ssm_push_failed(tmp_path, fake_aws):
    ctx = _elastic_ctx(tmp_path)
    fake_aws.raise_on["ssm_put_parameter"] = RuntimeError("network down")
    with pytest.raises(SSMPushFailed):
        aggregate_elastic(ctx, env="stage", aws=fake_aws)

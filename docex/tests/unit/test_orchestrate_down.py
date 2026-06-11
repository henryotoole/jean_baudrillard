"""Unit tests for ``docex envinfra down`` (``run_down``)."""

from __future__ import annotations

import pytest

from docex.errors import EnvNotSupported
from docex.orchestrate.down import run_down


def test_down_rejects_unknown_env(sample_ctx, fake_docker):
    with pytest.raises(EnvNotSupported):
        run_down(sample_ctx, fake_docker, env="bogus")


def test_down_calls_compose_down_with_preserve_volumes(sample_ctx, fake_docker):
    rc = run_down(sample_ctx, fake_docker, env="dev")
    assert rc == 0

    down_calls = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(down_calls) == 1
    # (method, compose_file_str, preserve_volumes)
    assert down_calls[0][2] is True
    # Mod 053: down passes the same env-tier project name as up so compose
    # finds and removes the right stack.
    name_calls = [
        c for c in fake_docker.calls if c[0] == "compose_down_project_name"
    ]
    assert name_calls == [("compose_down_project_name", "sample-dev")]


def test_down_fixed_stage_uses_compose_down(sample_ctx, fake_docker):
    """Mod 052: on a fixed-foundation project, stage/prod down is now a
    valid compose teardown (no longer rejected)."""
    rc = run_down(sample_ctx, fake_docker, env="stage")
    assert rc == 0
    down_calls = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(down_calls) == 1
    assert down_calls[0][2] is True


# ---------------------------------------------------------------------------
# Mod 052 (Gap F): elastic env teardown + RDS deletion-protection gate.
# ---------------------------------------------------------------------------


def test_down_elastic_stage_refuses_on_protected_rds(
    elastic_ctx, fake_docker, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """When the env contains a deletion-protected RDS, the pre-flight gate
    refuses, reports the instance, returns non-zero, and `tofu_destroy` is
    never invoked — nothing is destroyed."""
    # The env RDS prefix is the `rds`-policy form of `<project>_<env>` + "-".
    fake_aws.rds_protected_results["sample-stage-"] = ["sample-stage-appdb"]

    rc = run_down(
        elastic_ctx, fake_docker, env="stage",
        aws=fake_aws, tofu_init=fake_tofu_init, tofu_destroy=fake_tofu_apply,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "deletion-protected" in out
    assert "sample-stage-appdb" in out
    assert "Nothing was destroyed" in out
    # No tofu destroy/init happened.
    assert fake_tofu_apply.calls == []
    assert fake_tofu_init.calls == []
    # The protection scan was the gate.
    assert any(c[0] == "rds_protected_instances" for c in fake_aws.calls)


def test_down_elastic_stage_clean_calls_tofu_destroy(
    elastic_ctx, fake_docker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """No protected RDS → `tofu init` then `tofu destroy` against the env
    main.tf."""
    rc = run_down(
        elastic_ctx, fake_docker, env="stage",
        aws=fake_aws, tofu_init=fake_tofu_init, tofu_destroy=fake_tofu_apply,
    )
    assert rc == 0
    assert len(fake_tofu_init.calls) == 1
    assert len(fake_tofu_apply.calls) == 1
    workdir = fake_tofu_apply.calls[0]["workdir"]
    assert str(workdir).endswith("infra/output/stage")
    # No compose_down on the elastic stage path.
    assert not any(c[0] == "compose_down" for c in fake_docker.calls)

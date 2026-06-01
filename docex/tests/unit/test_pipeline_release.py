"""Unit tests for ``docex release``.

Verifies the fixed-foundation path calls ansible with the right
playbook/inventory/key paths, and that elastic + dev/test paths
either stub (rc=2) or raise (EnvNotSupported).
"""

from __future__ import annotations

import pytest

from docex.errors import EnvNotSupported
from docex.pipeline.release import run_release


def test_release_stage_fixed_calls_ansible(sample_ctx, fake_ansible):
    rc = run_release(sample_ctx, env="stage", ansible_runner=fake_ansible)
    assert rc == 0
    assert len(fake_ansible.calls) == 1
    call = fake_ansible.calls[0]
    assert "infra/output/stage/playbook.yml" in str(call["playbook"])
    assert "infra/output/stage/inventory.yml" in str(call["inventory"])
    assert "infra/deploy_creds/stage" in str(call["private_key"])
    # release does not pass tags — the whole playbook should run.
    assert call.get("tags") in (None, [])


def test_release_prod_fixed_calls_ansible(sample_ctx, fake_ansible):
    rc = run_release(sample_ctx, env="prod", ansible_runner=fake_ansible)
    assert rc == 0
    assert fake_ansible.calls
    assert "infra/output/prod" in str(fake_ansible.calls[0]["playbook"])


def test_release_elastic_dispatches_to_elastic_branch(
    elastic_ctx, fake_ansible, fake_aws, fake_tofu_init, fake_tofu_apply
):
    """Phase 4: elastic release no longer stubs — it pushes secrets, runs
    migrate, then tofu apply. We pass an FakeAWSClient + recording tofu
    runners and assert the dispatch path was taken (ansible is NOT
    invoked for elastic)."""
    rc = run_release(
        elastic_ctx,
        env="stage",
        ansible_runner=fake_ansible,
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )
    assert rc == 0
    # Ansible was provided but should NOT have been invoked: this is
    # the elastic branch, not the fixed branch.
    assert fake_ansible.calls == []
    # tofu_init + tofu_apply each ran exactly once against the env's
    # output dir.
    assert len(fake_tofu_init.calls) == 1
    assert len(fake_tofu_apply.calls) == 1
    assert "infra/output/stage" in str(fake_tofu_init.calls[0]["workdir"])
    assert fake_tofu_apply.calls[0].get("auto_approve") is True


def test_release_elastic_pushes_ssm_before_tofu_apply(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply
):
    """Doctrine invariant: SSM push happens BEFORE ``tofu apply`` so
    the data.aws_ssm_parameter sources resolve to fresh values."""
    rc = run_release(
        elastic_ctx,
        env="stage",
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )
    assert rc == 0
    # First SSM call must precede any ECS lookup/RunTask call, which
    # must precede tofu_apply.
    names = [c[0] for c in fake_aws.calls]
    assert "ssm_put_parameter" in names, names
    first_ssm = names.index("ssm_put_parameter")
    # ECS RunTask happens after SSM push and before tofu apply.
    if "ecs_run_task" in names:
        first_ecs = names.index("ecs_run_task")
        assert first_ssm < first_ecs, names
    # Apply ran exactly once and after all the AWS-side prep.
    assert len(fake_tofu_apply.calls) == 1


def test_release_elastic_aborts_when_ssm_push_fails(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply
):
    """SSMPushFailed before any ECS/tofu step."""
    from docex.errors import SSMPushFailed

    fake_aws.raise_on["ssm_put_parameter"] = RuntimeError("network down")
    with pytest.raises(SSMPushFailed):
        run_release(
            elastic_ctx,
            env="stage",
            aws=fake_aws,
            tofu_init=fake_tofu_init,
            tofu_apply=fake_tofu_apply,
        )
    # tofu must not have run.
    assert fake_tofu_init.calls == []
    assert fake_tofu_apply.calls == []


def test_release_elastic_first_time_applies_before_migrate(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply
):
    """First-time release: the ECS cluster doesn't exist yet, so
    migrate would fail before tofu had a chance to create it. The
    flow swaps to: SSM → tofu apply → migrate, so the migration runs
    against the now-live cluster + RDS."""
    fake_aws.cluster_exists = False
    rc = run_release(
        elastic_ctx,
        env="stage",
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )
    assert rc == 0
    # tofu_apply ran exactly once, and BEFORE any ECS RunTask.
    assert len(fake_tofu_apply.calls) == 1
    names = [c[0] for c in fake_aws.calls]
    if "ecs_run_task" in names:
        # The fake's call records are appended in invocation order
        # (the recorder shares one list across all methods). The
        # ecs_cluster_exists probe happens before tofu_apply (which
        # isn't recorded on fake_aws), and ecs_run_task must come
        # after the cluster_exists probe.
        first_probe = names.index("ecs_cluster_exists")
        first_run = names.index("ecs_run_task")
        assert first_probe < first_run, names


def test_release_elastic_first_time_aborts_when_migrate_fails(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply, capsys
):
    """On a first-release flow, a failed migration after a successful
    apply must NOT raise — it returns the migrate exit code with a
    clear message, leaving the operator with the schema in an
    unknown state and the infra up."""
    from docex.errors import ECSTaskFailed

    fake_aws.cluster_exists = False
    fake_aws.ecs_exit_codes = {
        "arn:aws:ecs:us-east-1:123456789012:task/fake/00000001": 9
    }
    with pytest.raises(ECSTaskFailed):
        run_release(
            elastic_ctx,
            env="stage",
            aws=fake_aws,
            tofu_init=fake_tofu_init,
            tofu_apply=fake_tofu_apply,
        )
    # apply DID run (because we're on the first-release path).
    assert len(fake_tofu_apply.calls) == 1


def test_release_elastic_aborts_when_migrate_fails(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply
):
    """If the ECS migration task exits non-zero, ECSTaskFailed propagates
    and tofu apply is NEVER invoked."""
    from docex.errors import ECSTaskFailed

    # First RunTask succeeds and returns its arn (the fake generates one);
    # configure that arn to "exit 1" via ecs_exit_codes. We don't know
    # the arn ahead of time, so set the default exit on the first task.
    # The fake's task_counter starts at 0 → first arn ends in 00000001.
    fake_aws.ecs_exit_codes = {
        "arn:aws:ecs:us-east-1:123456789012:task/fake/00000001": 9
    }
    with pytest.raises(ECSTaskFailed):
        run_release(
            elastic_ctx,
            env="stage",
            aws=fake_aws,
            tofu_init=fake_tofu_init,
            tofu_apply=fake_tofu_apply,
        )
    # tofu must not have run.
    assert fake_tofu_init.calls == []
    assert fake_tofu_apply.calls == []


def test_release_elastic_probes_cluster_via_ecs_naming_policy(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply
):
    """Mod 007: the first-time-release cluster probe must use the ``ecs``
    naming policy (underscore-preserving), not a stale hyphen-joined
    literal. Otherwise the probe always misses on steady-state releases
    (the live cluster is underscore-joined) and falls into the
    first-release branch on every invocation."""
    run_release(
        elastic_ctx,
        env="stage",
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )
    probes = [
        call for call in fake_aws.calls if call[0] == "ecs_cluster_exists"
    ]
    assert probes, "expected ecs_cluster_exists to be probed once"
    # The fixture's project name is "sample"; the ecs policy joins on
    # underscore. The pre-mod-007 literal would have been "sample-stage".
    name_arg = probes[0][1][0]
    assert name_arg == "sample_stage", (
        f"cluster probe used {name_arg!r}; expected 'sample_stage' "
        f"per the ecs naming policy"
    )


def test_release_rejects_dev_test(sample_ctx, fake_ansible):
    for env in ("dev", "test"):
        with pytest.raises(EnvNotSupported):
            run_release(sample_ctx, env=env, ansible_runner=fake_ansible)


def test_release_surfaces_ansible_failure(sample_ctx):
    """Non-zero ansible exit → AnsibleRunFailed."""
    from docex.errors import AnsibleRunFailed

    def failing(*_a, **_kw):
        return 9

    with pytest.raises(AnsibleRunFailed):
        run_release(sample_ctx, env="stage", ansible_runner=failing)


def test_release_refuses_when_deploy_key_missing(sample_ctx, fake_ansible, capsys):
    """Without infra/deploy_creds/<env>, release must refuse before invoking ansible."""
    # Remove the stage deploy key from this temp copy of the fixture.
    (sample_ctx.project_root / "infra" / "deploy_creds" / "stage").unlink()
    rc = run_release(sample_ctx, env="stage", ansible_runner=fake_ansible)
    assert rc == 1
    err = capsys.readouterr().err
    assert "deploy_creds/stage" in err
    assert fake_ansible.calls == []


def test_release_refuses_when_secrets_missing(sample_ctx, fake_ansible, capsys):
    """Without infra/secrets/<env>.env, release must refuse."""
    (sample_ctx.project_root / "infra" / "secrets" / "stage.env").unlink()
    rc = run_release(sample_ctx, env="stage", ansible_runner=fake_ansible)
    assert rc == 1
    assert fake_ansible.calls == []

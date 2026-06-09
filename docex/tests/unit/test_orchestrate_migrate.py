"""Unit tests for ``docex migrate``.

Phase 3 update: stage/prod on a *fixed* project now drives ansible
(no longer a stub); only the elastic stage/prod path stays stubbed.
"""

from __future__ import annotations

import pytest

from docex.errors import EnvNotSupported
from docex.orchestrate.migrate import run_migrate


def test_migrate_stage_fixed_calls_ansible_with_migrate_tag(sample_ctx, fake_docker):
    """Phase 3: stage/prod on fixed now invokes ansible-playbook
    ``--tags migrate``. The dispatcher injects ``ansible_runner``."""
    calls: list[dict] = []

    def fake_runner(playbook, inventory, **kwargs):
        calls.append({"playbook": playbook, "inventory": inventory, **kwargs})
        return 0

    rc = run_migrate(sample_ctx, fake_docker, env="stage", ansible_runner=fake_runner)
    assert rc == 0, calls
    assert len(calls) == 1
    call = calls[0]
    assert call["tags"] == ["migrate"]
    # Inventory + playbook paths should land under infra/output/stage/.
    assert "infra/output/stage/playbook.yml" in str(call["playbook"])
    assert "infra/output/stage/inventory.yml" in str(call["inventory"])
    assert "infra/deploy_creds/stage" in str(call["private_key"])


def test_migrate_prod_fixed_calls_ansible(sample_ctx, fake_docker):
    calls: list[dict] = []

    def fake_runner(playbook, inventory, **kwargs):
        calls.append({"playbook": playbook, "inventory": inventory, **kwargs})
        return 0

    rc = run_migrate(sample_ctx, fake_docker, env="prod", ansible_runner=fake_runner)
    assert rc == 0
    assert calls and calls[0]["tags"] == ["migrate"]


def test_migrate_stage_elastic_runs_ecs_task_per_schema_owner(
    elastic_ctx, fake_docker, fake_aws
):
    """Phase 4: elastic stage/prod no longer stubs — it RunTasks the
    per-service migration task definition on Fargate and polls for
    completion. Sample fixture has one schema-owning service (api)."""
    calls: list = []

    def fake_runner(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    rc = run_migrate(
        elastic_ctx, fake_docker, env="stage",
        ansible_runner=fake_runner, aws=fake_aws,
    )
    assert rc == 0
    # Ansible runner is NOT invoked on the elastic branch.
    assert calls == []
    names = [c[0] for c in fake_aws.calls]
    # The migrate path looks up cluster + vpc + subnets + sg once
    # before its RunTask loop.
    assert "get_ecs_cluster_arn" in names
    assert "get_default_subnets" in names
    assert "get_security_group_id" in names
    # Exactly one RunTask (sample fixture has a single schema owner).
    assert names.count("ecs_run_task") == 1
    assert names.count("ecs_wait_for_task") == 1


def test_migrate_stage_elastic_first_failure_aborts(
    elastic_ctx, fake_docker, fake_aws
):
    """If an ECS migration task exits non-zero, ECSTaskFailed bubbles
    up before any further service is migrated."""
    from docex.errors import ECSTaskFailed

    # First task arn (the fake's counter generates 00000001) → exit 9.
    fake_aws.ecs_exit_codes = {
        "arn:aws:ecs:us-east-1:123456789012:task/fake/00000001": 9
    }
    with pytest.raises(ECSTaskFailed):
        run_migrate(
            elastic_ctx, fake_docker, env="stage", aws=fake_aws,
        )


def test_migrate_dev_calls_compose_exec_per_schema_owner(sample_ctx, fake_docker):
    rc = run_migrate(sample_ctx, fake_docker, env="dev")
    assert rc == 0
    exec_calls = [c for c in fake_docker.calls if c[0] == "compose_exec"]
    # One per schema-owning service. Sample fixture has just api.
    assert len(exec_calls) == 1
    # The compose service key is the project-scoped global name.
    assert exec_calls[0][2].endswith("api")
    assert exec_calls[0][3] == ("./migrate.sh",)


def test_migrate_test_calls_compose_exec(sample_ctx, fake_docker):
    rc = run_migrate(sample_ctx, fake_docker, env="test")
    assert rc == 0
    exec_calls = [c for c in fake_docker.calls if c[0] == "compose_exec"]
    assert len(exec_calls) == 1
    assert exec_calls[0][2].endswith("api")


def test_migrate_dev_short_circuits_on_failure(sample_ctx, fake_docker):
    fake_docker.exit_codes[
        ("exit", "compose_exec", "sample-dev-api", ("./migrate.sh",))
    ] = 9
    rc = run_migrate(sample_ctx, fake_docker, env="dev")
    assert rc == 9


def test_migrate_rejects_unknown_env(sample_ctx, fake_docker):
    with pytest.raises(EnvNotSupported):
        run_migrate(sample_ctx, fake_docker, env="bogus")

"""Unit tests for ``stagetest``'s orchestrator liveness/version pre-step.

One test per row of mod 128's overview § *Every way this step could fail to be
able to answer* (the 22-row table). Every test asserts **the specific exception
type** and a distinctive message fragment — never merely that *something*
raised, because a ``TypeError`` from a mis-built fake is also a red test and
proves nothing. That trap is this mod's entire subject matter.

Row numbers below refer to that table.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from docex.cicl.compile import compile_env
from docex.context import load_project_context
from docex.errors import (
    AWSCredentialsMissing,
    DeployedServiceUnhealthy,
    OrchestratorStateUnreadable,
)
from docex.pipeline import orchestrator_health as oh
from docex.pipeline.orchestrator_health import assert_deployed_healthy

from tests.conftest import FakeAWSClient, FakeSSHClient

# The sample fixtures compile one core service in `stage`.
_CONTAINER = "sample-stage-api-web"      # fixed: container_name == global_name
_ECS_SERVICE = "sample-stage-api-web"    # elastic: ECS service name
_APP_CONTAINER = "api-web"               # elastic: container inside the task def
_CLUSTER = "sample-stage"
_HOST = "stage.sample.example.com"
_VERSION = "0.1.0"
_GOOD_IMAGE = f"registry.example.com/sample/api:{_VERSION}"
_TASKDEF = "arn:aws:ecs:us-east-1:1:task-definition/sample-stage-api-web:7"
_ARN = "arn:aws:ecs:us-east-1:1:task/sample-stage/aaaa"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _deploy_key(ctx) -> Path:
    return ctx.project_root / "infra" / "deploy_creds" / "stage"


def _write_deploy_key(ctx) -> None:
    """The fixed path requires infra/deploy_creds/<env> before any SSH.

    The sample fixture already ships one; this makes the requirement explicit at
    each call site rather than depending on that.
    """
    key = _deploy_key(ctx)
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text("dummy-key\n")


def _fixed_ssh(*, out: str = f"healthy|running|{_GOOD_IMAGE}", rc: int = 0):
    return FakeSSHClient(capture_out=out, capture_rc=rc)


def _healthy_elastic_aws(
    *,
    last_status: str = "RUNNING",
    health_status: str = "HEALTHY",
    image: str = _GOOD_IMAGE,
) -> FakeAWSClient:
    """A FakeAWSClient scripted into a healthy single-task elastic env.

    Note every field it has to *set*: the fake's defaults are all empty, i.e.
    "nothing is deployed". A fake whose default is green would be the same
    defect mod 128 is about, one layer down.
    """
    return FakeAWSClient(
        ecs_service_task_arns={_ECS_SERVICE: [_ARN]},
        ecs_task_records={
            _ARN: {
                "task_arn": _ARN,
                "last_status": last_status,
                "health_status": health_status,
                "task_definition": _TASKDEF,
            },
        },
        ecs_task_definition_images_results={_TASKDEF: {_APP_CONTAINER: image}},
    )


def _empty_core_ctx(tmp_path: Path):
    """A project that compiles to zero core services (row #1).

    Modelled on ``test_compile.py``'s
    ``test_project_tier_task_execution_policy_empty_core_services``, which is
    what proved this state reachable rather than theoretical.
    """
    proj = tmp_path / "empty"
    (proj / "infra").mkdir(parents=True)
    (proj / "project.yml").write_text(
        'name: empty_proj\nversion: "0.0.1"\ndocex_version: "1.7.0"\n'
    )
    (proj / "infra" / "infra.yml").write_text(
        'cicl_version: "3"\n'
        "foundation: elastic\n"
        "apex_domain: example.com\n"
        'observability_backend_url: "https://obs.example.com"\n'
        "codebases: {}\n"
        "backing_services: {}\n"
    )
    return load_project_context(proj)


# ---------------------------------------------------------------------------
# Happy paths — both foundations.
# ---------------------------------------------------------------------------


def test_fixed_happy_path(sample_ctx, capsys):
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh()
    assert assert_deployed_healthy(
        sample_ctx, env="stage", aws=None, ssh=ssh
    ) is None
    out = capsys.readouterr().out
    assert "1 core service(s), 1 instance(s) healthy" in out
    assert f"version {_VERSION}" in out


def test_elastic_happy_path(elastic_ctx, capsys):
    aws = _healthy_elastic_aws()
    assert assert_deployed_healthy(
        elastic_ctx, env="stage", aws=aws, ssh=None
    ) is None
    out = capsys.readouterr().out
    assert "1 core service(s), 1 instance(s) healthy" in out


# ---------------------------------------------------------------------------
# Rows #1-#3 — both foundations.
# ---------------------------------------------------------------------------


def test_no_core_services_fails_rather_than_passing_vacuously(tmp_path):
    """Row #1. An empty check set is not a healthy environment."""
    ctx = _empty_core_ctx(tmp_path)
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(
            ctx, env="stage", aws=FakeAWSClient(), ssh=None
        )
    assert "no core services" in str(exc.value)
    assert "empty check set is not a healthy environment" in str(exc.value)


def test_unknown_foundation_raises_rather_than_falling_through(
    sample_ctx, monkeypatch
):
    """Row #2. `foundation` is schema-validated, so this is only reachable by
    forcing it — guarded because a fall-through `else` is a silent pass."""
    real = compile_env

    def _quantum(*args, **kwargs):
        return dataclasses.replace(real(*args, **kwargs), foundation="quantum")

    monkeypatch.setattr(oh, "compile_env", _quantum)
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(
            sample_ctx, env="stage", aws=FakeAWSClient(), ssh=_fixed_ssh()
        )
    assert "unknown foundation 'quantum'" in str(exc.value)


def test_missing_ssh_on_fixed_is_an_internal_dispatch_bug(sample_ctx):
    """Row #3, fixed half. Never a skip."""
    _write_deploy_key(sample_ctx)
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=None)
    assert "Internal dispatch bug" in str(exc.value)
    assert "SSH client" in str(exc.value)


def test_missing_aws_on_elastic_is_an_internal_dispatch_bug(elastic_ctx):
    """Row #3, elastic half."""
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=None, ssh=None)
    assert "Internal dispatch bug" in str(exc.value)
    assert "AWSClient" in str(exc.value)


# ---------------------------------------------------------------------------
# Rows #4-#14 — elastic.
# ---------------------------------------------------------------------------


def test_absent_aws_credentials_propagate(elastic_ctx):
    """Row #4. verify_clean.sh's exact failure: an expired session must not
    read as a clean env."""
    aws = _healthy_elastic_aws()
    aws.raise_on["ecs_list_service_task_arns"] = AWSCredentialsMissing(
        "no AWS credentials found"
    )
    with pytest.raises(AWSCredentialsMissing):
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)


def test_absent_ecs_cluster_propagates(elastic_ctx):
    """Row #5. The pre-step must not swallow ClusterNotFoundException the way
    its neighbour ecs_primary_deployment_times deliberately does."""

    class ClusterNotFoundException(Exception):
        pass

    aws = _healthy_elastic_aws()
    aws.raise_on["ecs_list_service_task_arns"] = ClusterNotFoundException(
        f"cluster {_CLUSTER} not found"
    )
    with pytest.raises(ClusterNotFoundException):
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)


def test_absent_ecs_service_propagates(elastic_ctx):
    """Row #6."""

    class ServiceNotFoundException(Exception):
        pass

    aws = _healthy_elastic_aws()
    aws.raise_on["ecs_list_service_task_arns"] = ServiceNotFoundException(
        f"service {_ECS_SERVICE} not found"
    )
    with pytest.raises(ServiceNotFoundException):
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)


def test_empty_task_list_is_not_healthy(elastic_ctx):
    """Row #7 — the central trap. A service with zero RUNNING tasks must fail,
    never read as 'every task is healthy'."""
    aws = FakeAWSClient(ecs_service_task_arns={_ECS_SERVICE: []})
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert "zero RUNNING tasks" in str(exc.value)
    assert "empty task list is not a healthy service" in str(exc.value)


def test_task_health_unknown_is_unreadable_not_unhealthy(elastic_ctx):
    """Row #9. The elastic twin of NOHEALTH: no container declares a probe."""
    aws = _healthy_elastic_aws(health_status="UNKNOWN")
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert "no container in this task declares a health check" in str(exc.value)
    assert "pre-1.7.0" in str(exc.value)


def test_task_unhealthy_is_the_honest_answer(elastic_ctx):
    """Row #10, health half."""
    aws = _healthy_elastic_aws(health_status="UNHEALTHY")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert "healthStatus='UNHEALTHY'" in str(exc.value)


def test_task_not_running_is_the_honest_answer(elastic_ctx):
    """Row #10, lastStatus half."""
    aws = _healthy_elastic_aws(last_status="PENDING")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert "lastStatus='PENDING'" in str(exc.value)


def test_starting_task_is_not_misdiagnosed_as_a_probeless_image(elastic_ctx):
    """A task listed by `desiredStatus=RUNNING` that has not reached RUNNING yet
    reports `healthStatus=UNKNOWN` — the *same* value a pre-1.7.0 task
    definition reports. Judged health-first, a slow rollout would be diagnosed
    as a missing probe and the operator sent to look at their `health.sh`.

    Pins the ORDERING, not the verdict: both orders fail loudly, so the gate is
    honest either way. Only this order is accurate.
    """
    aws = _healthy_elastic_aws(last_status="PENDING", health_status="UNKNOWN")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    msg = str(exc.value)
    assert "is not running" in msg
    assert "lastStatus='PENDING'" in msg
    # The wrong diagnosis must NOT appear.
    assert "declares no health check" not in msg
    assert "pre-1.7.0" not in msg


def test_unreadable_task_definition_propagates(elastic_ctx):
    """Row #11. A deregistered/throttled/denied revision must never be read as
    'assume the version is right'."""

    class ClientError(Exception):
        pass

    aws = _healthy_elastic_aws()
    aws.raise_on["ecs_task_definition_images"] = ClientError(
        "ClientError: task definition deregistered"
    )
    with pytest.raises(ClientError):
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)


def test_task_definition_without_the_app_container_is_unreadable(elastic_ctx):
    """Row #12. Unreachable via the current emitter; guarded because 'version
    unreadable' silently becoming 'version correct' is this mod's whole point."""
    aws = _healthy_elastic_aws()
    aws.ecs_task_definition_images_results[_TASKDEF] = {
        "sample-stage-api-web-otelcol": "otel/collector:1.2.3",
    }
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert f"declares no container named '{_APP_CONTAINER}'" in str(exc.value)


def test_digest_pinned_image_has_no_readable_version(elastic_ctx):
    """Row #13, digest half."""
    aws = _healthy_elastic_aws(
        image="registry.example.com/sample/api@sha256:" + "ab" * 32
    )
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert "digest-pinned" in str(exc.value)


def test_untagged_image_has_no_readable_version(elastic_ctx):
    """Row #13, no-tag half. The registry host's own `:port` must not be
    mistaken for a tag — hence the rsplit('/') before looking for ':'."""
    aws = _healthy_elastic_aws(image="registry.example.com:5000/sample/api")
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert "carries no version tag" in str(exc.value)


def test_elastic_version_mismatch_quotes_the_full_ref(elastic_ctx):
    """Row #14."""
    stale = "registry.example.com/sample/api:0.0.9"
    aws = _healthy_elastic_aws(image=stale)
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert stale in str(exc.value)          # the FULL ref, not just the tag
    assert f"version {_VERSION!r}" in str(exc.value)


# ---------------------------------------------------------------------------
# Row #8 — the bounded re-read.
# ---------------------------------------------------------------------------


def test_rereads_once_then_fails_and_never_masks_an_unhealthy_service(
    elastic_ctx, monkeypatch
):
    """Row #8 constraint 3, the test that keeps the retry honest.

    An unhealthy task is *returned* by describe_tasks, so the task set never
    shrinks and the re-read is never spent. The verdict must be
    DeployedServiceUnhealthy — not OrchestratorStateUnreadable.
    """
    monkeypatch.setattr(oh, "_TASK_SET_REREAD_DELAY_S", 0)
    aws = _healthy_elastic_aws(health_status="UNHEALTHY")
    with pytest.raises(DeployedServiceUnhealthy):
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    lists = [c for c in aws.calls if c[0] == "ecs_list_service_task_arns"]
    assert len(lists) == 1, "an unhealthy service must not trigger a re-read"


def test_shrinking_task_set_rereads_exactly_once_then_fails(
    elastic_ctx, monkeypatch
):
    """Row #8 constraints 1 + 2. Two list calls, then unreadable — never a
    loop, and never confusable with the unhealthy verdict."""
    monkeypatch.setattr(oh, "_TASK_SET_REREAD_DELAY_S", 0)
    ghost = _ARN + "-ghost"
    aws = _healthy_elastic_aws()
    # Listed but never described: models the task that stopped between the two
    # calls (real DescribeTasks would report it under `failures`).
    aws.ecs_service_task_arns[_ECS_SERVICE] = [_ARN, ghost]
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    msg = str(exc.value)
    assert "after a re-read" in msg
    assert ghost in msg
    lists = [c for c in aws.calls if c[0] == "ecs_list_service_task_arns"]
    describes = [c for c in aws.calls if c[0] == "ecs_describe_tasks"]
    assert len(lists) == 2, "exactly one re-read, not a poll loop"
    assert len(describes) == 2


def test_reread_that_resolves_passes(elastic_ctx, monkeypatch):
    """The re-read exists to survive a task replaced mid-read: a second pass
    that is consistent must pass, or the retry buys nothing."""
    monkeypatch.setattr(oh, "_TASK_SET_REREAD_DELAY_S", 0)
    ghost = _ARN + "-ghost"
    aws = _healthy_elastic_aws()
    aws.ecs_service_task_arns[_ECS_SERVICE] = [_ARN, ghost]

    real_list = aws.ecs_list_service_task_arns

    def _shrink_after_first(cluster, service):
        arns = real_list(cluster, service)
        # ECS finished replacing the task; the second read is consistent.
        aws.ecs_service_task_arns[_ECS_SERVICE] = [_ARN]
        return arns

    aws.ecs_list_service_task_arns = _shrink_after_first  # type: ignore[method-assign]
    assert assert_deployed_healthy(
        elastic_ctx, env="stage", aws=aws, ssh=None
    ) is None


def test_reread_finding_zero_tasks_is_unhealthy_not_a_vacuous_pass(
    elastic_ctx, monkeypatch
):
    """A second pass that lists NO tasks is not 'short' by count, so it must be
    caught explicitly — otherwise the loop over zero records checks nothing and
    the step passes vacuously, which is precisely this mod's defect."""
    monkeypatch.setattr(oh, "_TASK_SET_REREAD_DELAY_S", 0)
    ghost = _ARN + "-ghost"
    aws = _healthy_elastic_aws()
    aws.ecs_service_task_arns[_ECS_SERVICE] = [_ARN, ghost]

    real_list = aws.ecs_list_service_task_arns

    def _empty_after_first(cluster, service):
        arns = real_list(cluster, service)
        aws.ecs_service_task_arns[_ECS_SERVICE] = []
        return arns

    aws.ecs_list_service_task_arns = _empty_after_first  # type: ignore[method-assign]
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(elastic_ctx, env="stage", aws=aws, ssh=None)
    assert "zero RUNNING tasks (on a re-read)" in str(exc.value)


# ---------------------------------------------------------------------------
# Rows #15-#22 — fixed.
# ---------------------------------------------------------------------------


def test_missing_deploy_key_fails_before_any_ssh(sample_ctx):
    """Row #15. No deploy key present, and nothing may be captured."""
    _deploy_key(sample_ctx).unlink()  # the fixture ships one
    ssh = _fixed_ssh()
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "infra/deploy_creds/stage" in str(exc.value)
    assert ssh.calls == [], "the key check must precede any SSH"


def test_ssh_255_is_unreachable_host(sample_ctx):
    """Row #16. Checked before the generic non-zero branch, which would
    otherwise blame docker for an SSH failure."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out="", rc=255)
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "cannot reach host" in str(exc.value)
    assert "ssh 255" in str(exc.value)


def test_docker_inspect_nonzero_is_unreadable(sample_ctx):
    """Row #17."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out="Error: No such object: sample-stage-api-web", rc=1)
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    msg = str(exc.value)
    assert "exited 1" in msg
    assert "No such object" in msg
    assert "sudo was denied" in msg


@pytest.mark.parametrize("out", ["", "   ", "healthy", "healthy|running", "|running|img:1"])
def test_rc_zero_with_unusable_output_is_unreadable(sample_ctx, out):
    """Row #18 — 'could not answer, returned nothing, and nothing read as
    clean' made explicit. rc 0 plus garbled stdout must never be a pass."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out=out)
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "output is unusable" in str(exc.value)


def test_nohealth_sentinel_is_unreadable_not_unhealthy(sample_ctx):
    """Row #19. An image that declares no healthcheck — the fixed twin of
    ECS's UNKNOWN."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out=f"NOHEALTH|running|{_GOOD_IMAGE}")
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "declares no healthcheck" in str(exc.value)
    assert "pre-1.7.0" in str(exc.value)


def test_health_starting_has_its_own_message(sample_ctx):
    """Row #20. Probed during the start period."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out=f"starting|running|{_GOOD_IMAGE}")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "start period" in str(exc.value)


def test_health_unhealthy_is_the_honest_answer(sample_ctx):
    """Row #21, health half."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out=f"unhealthy|running|{_GOOD_IMAGE}")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "health='unhealthy'" in str(exc.value)


def test_state_not_running_is_the_honest_answer(sample_ctx):
    """Row #21, state half. A healthy-but-exited container is still down."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out=f"healthy|exited|{_GOOD_IMAGE}")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "state='exited'" in str(exc.value)


def test_exited_probeless_container_is_reported_as_down_not_as_probeless(sample_ctx):
    """The fixed twin of the elastic ordering test above. A container that is
    both stopped and probe-less is *down*; "your image declares no healthcheck"
    is the less useful of two true statements and would send the operator to the
    wrong place."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(out=f"NOHEALTH|exited|{_GOOD_IMAGE}")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    msg = str(exc.value)
    assert "is not running" in msg
    assert "state='exited'" in msg
    assert "pre-1.7.0" not in msg


def test_fixed_version_mismatch_quotes_the_full_ref(sample_ctx):
    """Row #22 / #14 on the fixed side."""
    _write_deploy_key(sample_ctx)
    stale = "registry.example.com/sample/api:0.0.9"
    ssh = _fixed_ssh(out=f"healthy|running|{stale}")
    with pytest.raises(DeployedServiceUnhealthy) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert stale in str(exc.value)


def test_fixed_digest_pinned_image_is_unreadable(sample_ctx):
    """Row #22 / #13 on the fixed side."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh(
        out="healthy|running|registry.example.com/sample/api@sha256:" + "cd" * 32
    )
    with pytest.raises(OrchestratorStateUnreadable) as exc:
        assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    assert "digest-pinned" in str(exc.value)


# ---------------------------------------------------------------------------
# The fixed path's SSH command shape.
# ---------------------------------------------------------------------------


def test_fixed_issues_one_inspect_per_container_with_the_right_shape(sample_ctx):
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh()
    assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    captures = [c for c in ssh.calls if c[0] == "capture"]
    assert len(captures) == 1, "one capture per container, not one batched call"
    host, key, cmd = captures[0][1], captures[0][2], captures[0][3]
    assert host == _HOST
    assert key.endswith("infra/deploy_creds/stage")
    assert "sudo docker inspect" in cmd
    assert cmd.endswith(f" {_CONTAINER}")
    assert "NOHEALTH" in cmd


def test_inspect_command_never_masks_failure(sample_ctx):
    """Pins the design decision against a well-meaning future edit that makes
    this call consistent with aggregate.py's TTE read. There, an unreadable
    store must degrade to empty; here it must degrade to failure."""
    _write_deploy_key(sample_ctx)
    ssh = _fixed_ssh()
    assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    cmd = next(c for c in ssh.calls if c[0] == "capture")[3]
    assert "2>/dev/null" not in cmd
    assert "|| true" not in cmd


def test_fixed_enumerates_replicas_rather_than_assuming_one(
    sample_ctx, monkeypatch
):
    """The replica count is computed via `effective_replicas`, not assumed —
    `stage`'s clamp to 1 lives in another module and could change."""
    _write_deploy_key(sample_ctx)
    monkeypatch.setattr(oh, "effective_replicas", lambda svc, env: 3)
    ssh = _fixed_ssh()
    assert_deployed_healthy(sample_ctx, env="stage", aws=None, ssh=ssh)
    containers = [c[3].rsplit(" ", 1)[1] for c in ssh.calls if c[0] == "capture"]
    assert containers == [
        f"{_CONTAINER}-1", f"{_CONTAINER}-2", f"{_CONTAINER}-3",
    ]


# ---------------------------------------------------------------------------
# The gate has no off switch.
# ---------------------------------------------------------------------------


def test_public_surface_carries_no_disable_flag():
    """Mod 128 overview § *The gate has no off switch*. A parameter whose only
    function is to disable a health gate is the artifact advance 005 found eight
    times; once it exists in the signature the next caller in a hurry uses it."""
    import inspect

    params = set(inspect.signature(assert_deployed_healthy).parameters)
    assert params == {"ctx", "env", "aws", "ssh"}

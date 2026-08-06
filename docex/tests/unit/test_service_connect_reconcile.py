"""Mods 109 + 114 — the Service Connect consumer reconcile.

Regression guard for a cut-blocking defect found by the 1.6.0 pre-cut elastic
smoke walk at ``PRE_CUT_CHECKLIST § D.11``: on a first-time elastic release the
doctrine-mandated ``uses`` fan-out failed *permanently*, decided by a
start-order race.

ECS Service Connect fixes a client task's resolvable endpoint set at task start
(AWS: "New endpoints that are added to the namespace after the most recent
deployment won't be added to the task configuration"), and ``docex`` emits the
consumer's and the used service's ``aws_ecs_service`` with no ordering between them.
On the walk ``api-web`` started 15 s before its worker and returned
``503 … Name or service not known`` for the rest of that task's life.

Ordering cannot fix it: a ``uses`` cycle (``web ↔ worker``) has no valid
creation order. So the fix is a post-apply redeploy of affected consumers, and
these tests pin its trigger — which must be *precise*, because firing on every
release would add a rolling deploy to every deploy, and firing never would ship
the bug.

**Mod 114 replaced the trigger's operands with durable ones.** Mod 109 diffed
the post-apply namespace against a snapshot taken before any apply, and that
snapshot lived in one process's memory. So a release that registered a name and
was then interrupted left a permanently broken env that *exits 0* on every
re-run: the re-run's own snapshot already contains the new name, the diff is
empty, and the stale consumer is never replaced. The question is now asked of
post-apply AWS state alone — *is any running consumer task older than the
registration of a name it needs?* — and the aborted-release re-run below is the
case the old trigger got wrong.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from docex.context import load_project_context
from docex.pipeline.release import _release_elastic


_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_project_elastic"
)

# A core `uses` target must declare `port` and `health_check_path` — those two
# fields *are* its health declaration (contracts.md § Declared by fields), and
# on elastic the port is what makes it Service-Connect-discoverable at all.
_WORKER = {
    "role": "worker",
    "command": ["python", "/service/dist/entrypoints/worker.py"],
    "port": 8081,
    "health_check_path": "/health",
    "networks": ["internal"],
    "uses": ["appdb"],
    "resources": {"cpu": 0.25, "memory": "512MB", "disk": "25GB"},
}

_SCHEDULER = {
    "role": "scheduler",
    "schedule": "0 3 * * *",
    "command": ["python", "-m", "jobs.cleanup"],
    "networks": ["internal"],
    "uses": ["appdb"],
    "resources": {"cpu": 0.25, "memory": "512MB"},
}

# Mod 115. A clock is an ORDINARY long-running core service on elastic — it
# emits an `aws_ecs_service` like any other, so the reconcile must treat it
# on the same terms as `web` and `worker`. The stop-then-start deployment
# percentages are an emitter concern and change nothing here.
_CLOCK = {
    "role": "clock",
    "command": ["python", "-m", "entrypoints.clock"],
    "port": 8082,
    "health_check_path": "/health",
    "networks": ["internal"],
    "uses": ["appdb", "api.worker"],
    "resources": {"cpu": 0.25, "memory": "512MB", "disk": "25GB"},
    "schedules": {"nightly_cleanup": "0 3 * * *"},
}


def _t(minute: int, second: int = 0) -> datetime:
    """A timestamp on the walk's clock. Aware, as boto3's always are."""
    return datetime(2026, 8, 5, 20, minute, second, tzinfo=timezone.utc)


def _project(tmp_path: Path, mutate) -> object:
    """The elastic fixture with `mutate` applied to its parsed infra.yml."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, dirs_exist_ok=False)
    shutil.rmtree(dest / "infra" / "output", ignore_errors=True)
    infra_path = dest / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    mutate(doc)
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return load_project_context(dest)


@pytest.fixture
def web_uses_worker(tmp_path: Path):
    """`api.web` uses `api.worker` — the walk's topology."""
    def mutate(doc):
        svcs = doc["codebases"]["api"]["core_services"]
        svcs["worker"] = dict(_WORKER)
        svcs["web"]["uses"] = [*svcs["web"].get("uses", []), "api.worker"]
    return _project(tmp_path, mutate)


def _redeployed(fake_aws) -> list[str]:
    """Service names passed to ``ecs_force_new_deployment``, in order."""
    return [
        kwargs["service"]
        for method, _args, kwargs in fake_aws.calls
        if method == "ecs_force_new_deployment"
    ]


def _waited(fake_aws) -> list[list[str]]:
    """Service lists passed to ``ecs_wait_services_stable``, in order."""
    return [
        kwargs["services"]
        for method, _args, kwargs in fake_aws.calls
        if method == "ecs_wait_services_stable"
    ]


def _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply, env="prod"):
    return _release_elastic(
        ctx,
        env=env,
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )


def test_aborted_release_rerun_redeploys_stale_consumer(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """**The reason mod 114 exists.** Release N registered
    `sample-prod-api-worker` and aborted before the reconcile; the operator
    re-runs. On the re-run both names are already in the namespace, so mod
    109's before/after diff was EMPTY and nothing was redeployed — the release
    exited 0 over an env whose `api-web` task, started at 20:40, six minutes
    before the worker's name existed, can never resolve it for as long as it
    lives.

    The durable comparison sees it: oldest task 20:40 < registration 20:46.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_task_start_times = {"sample-prod-api-web": [_t(40)]}
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"], (
        "the consumer whose task predates its target's registration must be "
        "redeployed, even though no name appeared during this release"
    )


def test_client_bookkeeping_entries_do_not_trigger_a_redeploy(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """ECS puts one `aws-ecs-sc.client.<uuid>.<service>` entry in the namespace
    per client-only participant. It registers nothing, nothing can `uses` it,
    and it is not a resolvable alias — so however new it is, it is not a reason
    to redeploy anybody. Here it is 13 minutes newer than the consumer's task
    while every real endpoint predates it.

    The pipeline sees an *unfiltered* namespace on purpose: the adapter does the
    filtering (see `test_aws_service_connect_endpoints.py`), and this asserts
    that the comparison being keyed on `target.global_name` holds the line even
    if that filter were ever lost.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(40),
        "aws-ecs-sc.client.7f3c-uuid.sample-prod-api-web": _t(59),
    }
    fake_aws.ecs_task_start_times = {"sample-prod-api-web": [_t(46)]}
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_converged_env_is_a_no_op(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The property that keeps ordinary releases cheap — and it is **emergent,
    not arranged**. Nothing special-cases an image-tag release as cheap; every
    consumer task simply postdates every name it `uses`, so the comparison
    finds nothing and no service is touched.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(40),
    }
    fake_aws.ecs_task_start_times = {
        "sample-prod-api-web": [_t(46)],
        "sample-prod-api-worker": [_t(46)],
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []
    assert _waited(fake_aws) == [], (
        "nothing was redeployed, so nothing should be waited on either"
    )


def test_new_target_redeploys_its_consumer(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The walk's exact failure, in the new formulation. The worker's endpoint
    is registered after `api-web`'s task started, so `api-web` — which has been
    returning 503 on the fan-out ever since — must be redeployed."""
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_task_start_times = {
        "sample-prod-api-web": [_t(41)],
        "sample-prod-api-worker": [_t(47)],
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"]


def test_uses_cycle_redeploys_both_sides(
    tmp_path: Path, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """`web ↔ worker` is legal and, per cicl.md, the most common web/worker
    topology there is. It is also the case ordering *cannot* express: in a cycle
    someone must be created first. Both members must be redeployed, and the
    reconcile must not recurse or error on the cycle."""
    def mutate(doc):
        svcs = doc["codebases"]["api"]["core_services"]
        svcs["worker"] = dict(_WORKER)
        svcs["worker"]["uses"] = [*svcs["worker"].get("uses", []), "api.web"]
        svcs["web"]["uses"] = [*svcs["web"].get("uses", []), "api.worker"]
    ctx = _project(tmp_path, mutate)

    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_task_start_times = {
        "sample-prod-api-web": [_t(40)],
        "sample-prod-api-worker": [_t(40)],
    }
    rc = _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert sorted(_redeployed(fake_aws)) == [
        "sample-prod-api-web", "sample-prod-api-worker",
    ]


def test_clock_skew_tie_redeploys(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """Ties break toward redeploying. The two timestamps come from two
    different AWS services, so sub-second skew is possible; `<=` covers it.

    This pins the `<=` against a later "tidy-up" to `<`. A false positive costs
    one rolling deploy; a false negative costs a permanently broken env that
    exits 0. Never round toward silence.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    # EXACTLY equal to the target's CreateDate.
    fake_aws.ecs_task_start_times = {"sample-prod-api-web": [_t(46)]}
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"], (
        "an exact tie must resolve toward redeploying — this is what `<=` buys"
    )


def test_task_one_second_after_registration_is_not_redeployed(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The other side of the tie. The margin is ZERO, so a task that starts even
    slightly after the registration is left alone — it read a namespace that
    already held the name and resolved it on its first probe cycle.

    This is what stops the margin being "fixed" to 60 s: the name is created
    with the ECS *service*, before any task exists, so on a correct first
    release every task starts 30-90 s after it. Any non-zero window would
    redeploy every consumer on every first release.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_task_start_times = {"sample-prod-api-web": [_t(46, 1)]}
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_consumer_of_preexisting_target_is_not_redeployed(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The comparison is per-CONSUMER, not per-namespace. `api-web`'s own target
    predates its task, so it can already resolve it — the presence of some
    unrelated, newer endpoint is not a reason to restart it."""
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(40),
        "sample-prod-something": _t(59),   # unrelated newcomer
    }
    fake_aws.ecs_task_start_times = {"sample-prod-api-web": [_t(46)]}
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_consumer_with_no_running_tasks_is_not_redeployed(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """No running tasks means nothing can be stale, and whatever starts later
    reads a namespace that already holds every name."""
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_task_start_times = {}
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_scheduler_consumer_is_never_redeployed(
    tmp_path: Path, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """A scheduler emits no `ecs_service`, so there is nothing to redeploy —
    and `update_service` against a non-existent service is an error, not a
    no-op. Even holding a `uses` edge, it must be skipped."""
    def mutate(doc):
        svcs = doc["codebases"]["api"]["core_services"]
        svcs["worker"] = dict(_WORKER)
        svcs["nightly"] = dict(_SCHEDULER)
        svcs["nightly"]["uses"] = [*svcs["nightly"].get("uses", []), "api.worker"]
    ctx = _project(tmp_path, mutate)

    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_task_start_times = {
        "sample-prod-api-nightly": [_t(40)],
        "sample-prod-api-web": [_t(40)],
    }
    rc = _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert "sample-prod-api-nightly" not in _redeployed(fake_aws)


def test_clock_consumer_is_redeployed_on_the_same_terms(
    tmp_path: Path, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """Mod 115: a clock is an ORDINARY service to the release path.

    It emits an `aws_ecs_service`, so unlike the scheduler above it *can* be
    redeployed — and it must be, on exactly the same predicate as `web`. Here
    both consumers' tasks predate the worker's registration, so both are
    replaced; no role test anywhere singles the clock out.
    """
    def mutate(doc):
        svcs = doc["codebases"]["api"]["core_services"]
        svcs["worker"] = dict(_WORKER)
        svcs["clock"] = dict(_CLOCK)
        svcs["web"]["uses"] = [*svcs["web"].get("uses", []), "api.worker"]
    ctx = _project(tmp_path, mutate)

    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
        "sample-prod-api-clock": _t(46),
    }
    fake_aws.ecs_task_start_times = {
        "sample-prod-api-web": [_t(40)],
        "sample-prod-api-clock": [_t(40)],
    }
    rc = _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert sorted(_redeployed(fake_aws)) == [
        "sample-prod-api-clock", "sample-prod-api-web",
    ]


def test_converged_clock_is_left_alone(
    tmp_path: Path, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The other half of "ordinary": the cheap path is emergent for a clock
    too. Its task postdates the name it `uses`, so nothing is touched."""
    def mutate(doc):
        svcs = doc["codebases"]["api"]["core_services"]
        svcs["worker"] = dict(_WORKER)
        svcs["clock"] = dict(_CLOCK)
    ctx = _project(tmp_path, mutate)

    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(40),
        "sample-prod-api-clock": _t(40),
    }
    fake_aws.ecs_task_start_times = {
        "sample-prod-api-web": [_t(46)],
        "sample-prod-api-worker": [_t(46)],
        "sample-prod-api-clock": [_t(46)],
    }
    rc = _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_slow_rollout_warns_but_does_not_fail_the_release(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """`update_service` was accepted and ECS will converge; failing an
    otherwise-good release over rollout latency would be wrong."""
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_task_start_times = {"sample-prod-api-web": [_t(40)]}
    fake_aws.ecs_services_stable = False
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    out = capsys.readouterr().out
    assert "warning" in out and "steady state" in out

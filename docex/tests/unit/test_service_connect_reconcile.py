"""The elastic release's Service Connect consumer reconcile (mods 109/114/123).

RULE FOR THIS FILE: every timestamp in a fixture must belong to ONE
INTERNALLY-CONSISTENT TIMELINE. A consumer's own endpoint `CreateDate` and its
own PRIMARY deployment `createdAt` are two views of the same ECS service and
cannot contradict each other; a target's `CreateDate` and a consumer's
deployment age must sit in an order AWS could actually produce.

This is not pedantry. Mod 114's version of this file was green against a
predicate that could not fire, because its fixtures described a world that
cannot exist: `api-web`'s endpoint created at 20:46 while one of its own tasks
started at 20:40 — six minutes before its own service existed. Every "fires"
assertion rested on that shape, so the suite exercised the code path and never
once tested the predicate. A green suite built on an impossible world is
evidence of nothing at all.
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

# On elastic the `port` is what makes a core `uses` target
# Service-Connect-discoverable at all: `render_ecs_service` emits the
# `service_connect_configuration.service {}` block — the registered, resolvable
# name this whole file reconciles against — only for a service that declares one.
#
# Mod 125 therefore makes this file's worker a DIRECTLY-ADDRESSED target rather
# than a queue-reached one, which is what it always was in substance. Two
# consequences, both rule-driven:
#   - it declares an `rpc` surface (rule 31; asyncapi), not `events` — its
#     consumers resolve and call it, they do not enqueue to it;
#   - every consumer holds a magic ref to it (`_WORKER_REF` below), because
#     cicl.md § Rules item 2 is how an in-project service is addressed at all —
#     and that ref is exactly what rule 32's positive arm reads to REQUIRE the
#     port this file depends on.
# It declares no `health_check_path`: rule 33 confines that field to
# `web`-network core services.
_WORKER = {
    "role": "worker",
    "command": ["python", "/service/dist/entrypoints/worker.py"],
    "port": 8081,
    "networks": ["internal"],
    "uses": ["appdb"],
    "surfaces": {"rpc": {"api_styles": ["rpc"]}},
    "resources": {"cpu": 0.25, "memory": "512MB", "disk": "25GB"},
}

# The address parts a consumer of `api.worker` builds its Service Connect URL
# from at startup. Merged into any core service that lists `api.worker` in
# `uses:` — see the note on `_WORKER`.
_WORKER_REF = {
    "WORKER_HOST": "${codebases.api.core_services.worker.host}",
    "WORKER_PORT": "${codebases.api.core_services.worker.port}",
}


def _addresses_worker(svc: dict) -> None:
    """Make ``svc`` a direct consumer of ``api.worker``: the edge plus the ref."""
    svc["uses"] = [*svc.get("uses", []), "api.worker"]
    svc["env"] = {**svc.get("env", {}), **_WORKER_REF}


# Mod 115. A clock is an ORDINARY long-running core service on elastic — it
# emits an `aws_ecs_service` like any other, so the reconcile must treat it
# on the same terms as `web` and `worker`. The stop-then-start deployment
# percentages are an emitter concern and change nothing here.
#
# It reaches `api.worker` the same way `api.web` does here — by resolving its
# Service Connect name — so it carries the same magic ref (`_WORKER_REF`) and
# for the same rule-32 reason. Its own `port: 8082` is nobody's `uses` target,
# so rule 32 is silent on it. It declares no `health_check_path` (rule 33) and
# no surface: nothing uses a clock, which is what makes it a non-provider.
_CLOCK = {
    "role": "clock",
    "command": ["python", "-m", "entrypoints.clock"],
    "port": 8082,
    "networks": ["internal"],
    "uses": ["appdb", "api.worker"],
    "env": dict(_WORKER_REF),
    "resources": {"cpu": 0.25, "memory": "512MB", "disk": "25GB"},
    "schedules": {"nightly_cleanup": "0 3 * * *"},
}


def _t(minute: int, second: int = 0) -> datetime:
    """A Cloud Map name's `CreateDate`, on the walk's clock. Aware, as boto3's
    always are."""
    return datetime(2026, 8, 5, 20, minute, second, tzinfo=timezone.utc)


def _d(minute: int, second: int = 0) -> datetime:
    """A PRIMARY deployment's `createdAt`, on the same clock as :func:`_t`.

    Distinct from `_t` only for readability at the call site: a fixture then
    reads as two columns — when names were registered, and when deployments
    were created — which have to be orderable against each other by eye for
    the module docstring's timeline rule to be checkable at all.
    """
    return _t(minute, second)


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
        _addresses_worker(svcs["web"])
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


def test_converged_env_is_a_no_op(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """The property that keeps ordinary releases cheap — and it is **emergent,
    not arranged**. Nothing special-cases an image-tag release as cheap; every
    consumer's deployment simply postdates every name it `uses` by more than the
    margin, so the comparison finds nothing and no service is touched.

    The skip is also ANNOUNCED, and that is asserted here. A silent skip is
    indistinguishable from a step that never ran, which is precisely the
    ambiguity a smoke walk asked to confirm a `skip` verdict cannot resolve.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(40),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(50),
        "sample-prod-api-worker": _d(50),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []
    assert _waited(fake_aws) == [], (
        "nothing was redeployed, so nothing should be waited on either"
    )
    out = capsys.readouterr().out
    assert "consumer(s) checked" in out and "nothing to redeploy" in out, (
        "a skip must say so — silence cannot be told apart from a step that "
        "short-circuited before it compared anything"
    )


def test_code_only_release_weeks_later_is_free(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """**The case the whole no-op property rests on.** On an ordinary code-only
    release into a long-lived env the names are five weeks old and the fresh
    deployments are minutes old, so the comparison is not close by orders of
    magnitude — a 60 s margin is nowhere near enough to bridge it.

    If this ever fires, the margin has stopped being a bounded cost paid on
    first releases and shape changes, and has become a rolling deploy on every
    release of every consumer.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        "sample-prod-api-worker": datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": datetime(2026, 8, 5, 20, 40, tzinfo=timezone.utc),
        "sample-prod-api-worker": datetime(2026, 8, 5, 20, 40, tzinfo=timezone.utc),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_new_target_concurrent_with_consumer_deployment_fires(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The walk's failure shape, in the new formulation. `api-worker`'s name is
    registered five seconds before `api-web`'s deployment is created — inside
    the concurrent-creation window, where which of the two won is a race the
    timestamps do not report. The step stops trying to adjudicate it and
    redeploys.

    `api-worker` itself is left alone: it `uses` only `appdb`, a backing
    service, so it is not a candidate at all.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46, 8),
        "sample-prod-api-worker": _t(46, 5),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(46, 10),
        "sample-prod-api-worker": _d(46, 6),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"]


def test_aborted_release_rerun_redeploys_stale_consumer(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """**The hole mod 114 existed to close, and did not.** Release N created
    `api-web`'s deployment at 20:46:02 and registered `sample-prod-api-worker`
    at 20:46:05, then aborted before the reconcile. The operator re-runs; the
    re-run's apply is a no-op, so *nothing moves* — the deployment is still the
    one from release N and the name is still the one from release N.

    Mod 109's before/after diff was empty here because the re-run's own
    snapshot already contained the new name. Mod 114's task comparison could
    not fire either: `api-web`'s tasks necessarily started after `api-web`'s own
    service was created, hence after the worker's name. The deployment age is
    the first operand that reads this state correctly.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46, 5),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(46, 2),
        "sample-prod-api-worker": _d(46, 6),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"], (
        "the consumer whose deployment predates its target's registration must "
        "be redeployed, even though no name appeared during this release"
    )


def test_exact_tie_at_margin_redeploys(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """Ties break toward redeploying. The comparison is `<=` against
    `CreateDate + 60s`, so a deployment created at exactly that instant is
    inside the window.

    This pins the `<=` against a later "tidy-up" to `<`. A false positive costs
    one rolling deploy; a false negative costs a permanently broken env that
    exits 0. Never round toward silence.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_deployment_times = {
        # EXACTLY the target's CreateDate plus the 60 s margin.
        "sample-prod-api-web": _d(47),
        "sample-prod-api-worker": _d(46, 1),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"], (
        "an exact tie must resolve toward redeploying — this is what `<=` buys"
    )


def test_one_second_past_margin_is_left_alone(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The boundary from the other side, one second later. The
    concurrent-creation window is over, so the step goes back to reading the
    timestamps at face value and leaves the consumer alone.

    Together with `test_exact_tie_at_margin_redeploys` this pins the margin's
    width to exactly 60 s from both directions. Widening it is not free: past
    this line it starts firing on shapes where the ordering was demonstrably
    fine.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(47, 1),
        "sample-prod-api-worker": _d(46, 1),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_client_bookkeeping_entries_do_not_trigger_a_redeploy(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """ECS puts one `aws-ecs-sc.client.<uuid>.<service>` entry in the namespace
    per client-only participant. It registers nothing, nothing can `uses` it,
    and it is not a resolvable alias — so however new it is, it is not a reason
    to redeploy anybody. Here it is 13 minutes newer than the consumer's
    deployment, while every real endpoint predates that deployment by six.

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
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(46),
        "sample-prod-api-worker": _d(46),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []


def test_uses_cycle_redeploys_both_sides(
    tmp_path: Path, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """`web ↔ worker` is legal and, per cicl.md, the most common web/worker
    topology there is. It is also the case ordering *cannot* express: in a cycle
    someone must be created first. Both deployments are concurrent with both
    names, so both members must be redeployed — in one pass, and without the
    reconcile recursing or erroring on the cycle."""
    def mutate(doc):
        svcs = doc["codebases"]["api"]["core_services"]
        svcs["worker"] = dict(_WORKER)
        svcs["worker"]["uses"] = [*svcs["worker"].get("uses", []), "api.web"]
        # This is the only mutate where `api.web` is itself a `uses` target, so
        # it is the only one where rule 31 asks it for a surface. It needs no
        # magic ref back: rule 32's negative arm carves out `web`-network
        # targets, whose port rule 15 already requires.
        svcs["web"]["surfaces"] = {"rest": {"api_styles": ["rest"]}}
        _addresses_worker(svcs["web"])
    ctx = _project(tmp_path, mutate)

    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46, 4),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(46, 1),
        "sample-prod-api-worker": _d(46, 5),
    }
    rc = _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert sorted(_redeployed(fake_aws)) == [
        "sample-prod-api-web", "sample-prod-api-worker",
    ]


def test_consumer_absent_from_deployment_map_is_redeployed(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """No readable PRIMARY deployment — the service missing, reported under
    `failures`, or carrying no PRIMARY entry — and the consumer fires.

    An unreadable deployment age cannot be shown to postdate anything, so the
    safe direction is one rolling deploy rather than a silently broken env. The
    names here are ten minutes older than the worker's deployment, so a
    *readable* age would have skipped; the redeploy is caused by the absence
    alone.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(40),
        "sample-prod-api-worker": _t(40),
    }
    fake_aws.ecs_deployment_times = {
        # `sample-prod-api-web` deliberately omitted.
        "sample-prod-api-worker": _d(50),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"]


def test_walk_regression_first_prod_release(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The 1.7.0 elastic smoke walk, with its real numbers.

    `api-web`'s PRIMARY deployment was created 14:06:40; `api-worker`'s Cloud
    Map name at 14:07:02.391 — 22 seconds later. `api-web` returned 503 on the
    fan-out for 20+ minutes and TWO clean `release prod` runs repaired nothing.
    This must fire.
    """
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": datetime(2026, 8, 6, 14, 6, 41, tzinfo=timezone.utc),
        "sample-prod-api-worker": datetime(
            2026, 8, 6, 14, 7, 2, 391000, tzinfo=timezone.utc,
        ),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": datetime(2026, 8, 6, 14, 6, 40, tzinfo=timezone.utc),
        "sample-prod-api-worker": datetime(
            2026, 8, 6, 14, 7, 3, tzinfo=timezone.utc,
        ),
    }
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"]


def test_clock_consumer_is_redeployed_on_the_same_terms(
    tmp_path: Path, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """Mod 115: a clock is an ORDINARY service to the release path.

    It emits an `aws_ecs_service`, so it *can* be redeployed — and it must
    be, on exactly the same predicate as `web`. Here both consumers'
    deployments are created within seconds of the worker's registration, so
    both are replaced; no role test anywhere singles the clock out.
    """
    def mutate(doc):
        svcs = doc["codebases"]["api"]["core_services"]
        svcs["worker"] = dict(_WORKER)
        svcs["clock"] = dict(_CLOCK)
        _addresses_worker(svcs["web"])
    ctx = _project(tmp_path, mutate)

    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": _t(46),
        "sample-prod-api-worker": _t(46, 4),
        "sample-prod-api-clock": _t(46, 8),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(46, 1),
        "sample-prod-api-worker": _d(46, 5),
        "sample-prod-api-clock": _d(46, 9),
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
    too. Its deployment postdates the name it `uses` by ten minutes, so nothing
    is touched."""
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
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(50),
        "sample-prod-api-worker": _d(50),
        "sample-prod-api-clock": _d(50),
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
        "sample-prod-api-worker": _t(46, 4),
    }
    fake_aws.ecs_deployment_times = {
        "sample-prod-api-web": _d(46, 1),
        "sample-prod-api-worker": _d(46, 5),
    }
    fake_aws.ecs_services_stable = False
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    out = capsys.readouterr().out
    assert "warning" in out and "steady state" in out

"""Mod 109 — the Service Connect consumer reconcile.

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
"""

from __future__ import annotations

import shutil
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


def test_reconcile_redeploys_consumer_of_newly_registered_target(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The walk's exact failure. The worker's endpoint appears during this
    release, so `api-web` — which started without it — must be redeployed."""
    fake_aws.service_connect_endpoints = [
        set(),                          # before the apply: nothing registered
        {"sample-prod-api-worker"},     # after: the worker is now discoverable
    ]
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == ["sample-prod-api-web"], (
        "the consumer of the newly registered target must be redeployed"
    )


def test_no_reconcile_when_namespace_unchanged(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The test that keeps ordinary releases cheap. A steady-state release
    registers nothing new, so the reconcile must be a complete no-op — not a
    rolling deploy bolted onto every deploy forever."""
    # One-element script = constant: identical before and after.
    fake_aws.service_connect_endpoints = [
        {"sample-prod-api-web", "sample-prod-api-worker"},
    ]
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert _redeployed(fake_aws) == []
    assert _waited(fake_aws) == [], (
        "no endpoints changed, so nothing should be waited on either"
    )


def test_reconcile_handles_uses_cycle(
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

    fake_aws.service_connect_endpoints = [
        set(),
        {"sample-prod-api-web", "sample-prod-api-worker"},
    ]
    rc = _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert sorted(_redeployed(fake_aws)) == [
        "sample-prod-api-web", "sample-prod-api-worker",
    ]


def test_consumer_of_preexisting_target_is_not_redeployed(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply,
):
    """The diff is per-TARGET, not per-namespace. `api-web`'s only target was
    already registered, so `api-web` can already resolve it — the appearance of
    some unrelated endpoint is not a reason to restart it."""
    fake_aws.service_connect_endpoints = [
        {"sample-prod-api-worker"},                          # target already there
        {"sample-prod-api-worker", "sample-prod-something"},  # unrelated newcomer
    ]
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

    fake_aws.service_connect_endpoints = [
        set(),
        {"sample-prod-api-worker"},
    ]
    rc = _run(ctx, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    assert "sample-prod-api-nightly" not in _redeployed(fake_aws)


def test_slow_rollout_warns_but_does_not_fail_the_release(
    web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """`update_service` was accepted and ECS will converge; failing an
    otherwise-good release over rollout latency would be wrong."""
    fake_aws.service_connect_endpoints = [set(), {"sample-prod-api-worker"}]
    fake_aws.ecs_services_stable = False
    rc = _run(web_uses_worker, fake_aws, fake_tofu_init, fake_tofu_apply)
    assert rc == 0
    out = capsys.readouterr().out
    assert "warning" in out and "steady state" in out

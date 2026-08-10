"""``stagetest``'s orchestrator liveness/version pre-step.

Implements step 1 of ``cicd.md § Staging Tests``: before the stage-tester image
is built, read every core service's health and version **from the orchestrator**
for the env under test, and fail there if anything is unhealthy, on the wrong
version, **or unreadable**.

Rule of record: ``healthchecks.md § Version`` — the orchestrator wins.

| Foundation | Liveness | Version |
| --- | --- | --- |
| ``fixed``   | ``docker inspect``'s ``.State.Health.Status == healthy`` **and** ``.State.Status == running``, read over SSH to the deployed host | ``.Config.Image``'s tag |
| ``elastic`` | every RUNNING task's ``healthStatus == HEALTHY`` and ``lastStatus == RUNNING`` | the task's own task-definition revision's app-container image tag |

**Probe output is never parsed.** Liveness is the orchestrator's *aggregated*
state; version is the *deployment record*. ``healthchecks.md`` is explicit that a
healthcheck's stdout is captured by Docker and is not surfaced by ECS at all, so
anything read out of a probe's output would work on one foundation and silently
not on the other. Parsing it would produce exactly the shape this module exists
to prevent: a check that appears to answer and does not.

Two failure classes, deliberately distinct — see ``errors.py``:

- ``DeployedServiceUnhealthy``   — the orchestrator answered, and the answer is bad.
- ``OrchestratorStateUnreadable`` — docex could not obtain an answer at all.

This module's public surface is one function and **it has no flag that disables
it** (mod 128 overview § *The gate has no off switch*). A parameter whose only
job is to switch off a health gate is the artifact advance 005 found eight times;
once it exists in a signature the next caller in a hurry uses it. Tests inject a
scripted transport instead.
"""

from __future__ import annotations

import time

from docex.aws.client import AWSClient
from docex.cicl.compile import CompiledEnv, CompiledService, compile_env, effective_replicas
from docex.context import ProjectContext
from docex.errors import DeployedServiceUnhealthy, OrchestratorStateUnreadable
from docex.naming import ecs_cluster_name
from docex.ssh.client import SSHClient

#: Go-template read for one container. The ``NOHEALTH`` sentinel exists because
#: ``{{.State.Health.Status}}`` against a container whose image declares no
#: healthcheck is a nil-pointer *template* error: it would fail loudly by
#: accident. The sentinel fails loudly on purpose, with the right diagnosis.
_INSPECT_FORMAT = (
    "{{if .State.Health}}{{.State.Health.Status}}{{else}}NOHEALTH{{end}}"
    "|{{.State.Status}}|{{.Config.Image}}"
)

#: Delay before the single bounded re-read of a shrinking ECS task set. A module
#: constant rather than a parameter: the re-read is not configurable and must not
#: become a poll loop. Tests monkeypatch it to 0 rather than actually sleeping.
_TASK_SET_REREAD_DELAY_S = 2.0


def assert_deployed_healthy(
    ctx: ProjectContext,
    *,
    env: str,
    aws: AWSClient | None,
    ssh: SSHClient | None,
) -> None:
    """Assert every core service deployed to ``env`` is healthy and on version.

    Returns ``None`` on success (printing a per-service verdict and a summary);
    raises ``DeployedServiceUnhealthy`` or ``OrchestratorStateUnreadable``
    otherwise. Takes no flag that disables it and must never grow one.
    """
    if ctx.infra is None:  # pragma: no cover — stagetest already required it
        raise OrchestratorStateUnreadable(
            "cannot read deployed state without infra/infra.yml."
        )

    compiled = compile_env(
        ctx.infra,
        ctx.transfer_tables,
        env=env,
        project_name=ctx.project.name,
        project_version=ctx.project.version,
    )
    cores = sorted(
        (s for s in compiled.services.values() if s.is_core),
        key=lambda s: s.name,
    )

    # WHY guarded rather than assumed impossible: I argued a project must have at
    # least one core service (`domain_default_service` names one), and then a
    # baseline run surfaced test_compile.py's
    # `test_project_tier_task_execution_policy_empty_core_services`, which
    # compiles exactly such a project on purpose. "Nothing was checked" is not
    # "everything is healthy" — an empty check set is the canonical
    # couldn't-answer-and-read-as-clean shape.
    if not cores:
        raise OrchestratorStateUnreadable(
            f"the compiled {env} env declares no core services, so nothing was "
            "checked. An empty check set is not a healthy environment — "
            "stagetest cannot certify an env it read nothing about."
        )

    # Exhaustive dispatch. A fall-through `else` that returned normally would be
    # a silent pass over an unrecognised foundation, which is the exact defect
    # this module is a reaction to.
    if compiled.foundation == "fixed":
        if ssh is None:
            raise OrchestratorStateUnreadable(
                "fixed orchestrator read requires an SSH client. "
                "(Internal dispatch bug.)"
            )
        instances = _check_fixed(compiled, ctx, env=env, cores=cores, ssh=ssh)
    elif compiled.foundation == "elastic":
        if aws is None:
            raise OrchestratorStateUnreadable(
                "elastic orchestrator read requires an AWSClient. "
                "(Internal dispatch bug.)"
            )
        instances = _check_elastic(compiled, ctx, env=env, cores=cores, aws=aws)
    else:
        raise OrchestratorStateUnreadable(
            f"unknown foundation {compiled.foundation!r}; cannot read deployed "
            "state. stagetest refuses to certify an env it does not know how to "
            "interrogate."
        )

    # WHY the counts are in the message: a zero would then be visible in a log
    # even if a guard above were ever removed. Same reasoning as release.py's
    # "every no-fire path says which one it was."
    print(
        f"stagetest: orchestrator pre-step passed — {len(cores)} core "
        f"service(s), {instances} instance(s) healthy on version "
        f"{ctx.project.version}."
    )


# ---------------------------------------------------------------------------
# Fixed — `docker inspect` over SSH to the deployed host.
# ---------------------------------------------------------------------------


def _check_fixed(
    compiled: CompiledEnv,
    ctx: ProjectContext,
    *,
    env: str,
    cores: list[CompiledService],
    ssh: SSHClient,
) -> int:
    """Inspect every core container on the deployed fixed host. Returns the
    number of container instances verified."""
    key = ctx.project_root / "infra" / "deploy_creds" / env
    if not key.is_file():
        # Checked before any SSH, and with the message shape `_release_fixed`
        # uses so the two read the same to an operator.
        raise OrchestratorStateUnreadable(
            f"expected SSH deploy key at {key.relative_to(ctx.project_root)}; "
            "cannot read the deployed env's health without it. See "
            "credentials.md § Deploy Credentials."
        )

    # `compiled.subdomain` IS `<env>.<dns_label(project)>.<apex>` — the same
    # string `aggregate._host_for` derives. Read the carried field rather than
    # re-deriving it or reaching into another module's private helper.
    host = compiled.subdomain

    checked = 0
    for svc in cores:
        # Compute the replica names rather than assuming one: `stage`'s clamp to
        # a single instance lives in another module and could change.
        count = effective_replicas(svc, env)
        if count == 1:
            containers = [svc.global_name]
        else:
            containers = [f"{svc.global_name}-{i}" for i in range(1, count + 1)]
        for container in containers:
            # WHY sudo: the release playbook runs `become: true`, so containers
            # are root-owned and the `deploy` user must sudo to inspect them.
            # `deploy` has passwordless sudo (release_mechanism.md § Fixed
            # Foundation: Ansible). Same reasoning as aggregate.py's TTE read.
            #
            # WHY NO `2>/dev/null || true`: the precedent this call copies
            # (aggregate.py's `sudo cat ... 2>/dev/null || true`) carries both,
            # and a future reader will want to make the two consistent. DO NOT.
            # There, an unreadable TTE store must degrade to "empty" or docex
            # re-mints and locks the host out of its own credentials. Here, an
            # unreadable container must degrade to **failure**. Masking the rc
            # and the stderr is precisely the defect mod 128 exists to prevent.
            cmd = f"sudo docker inspect --format '{_INSPECT_FORMAT}' {container}"
            rc, out = ssh.capture(host, key, cmd)

            if rc == 255:
                # SSH's own connection-failure code. Checked before the generic
                # non-zero branch, which would otherwise blame docker.
                raise OrchestratorStateUnreadable(
                    f"cannot reach host {host!r} to inspect {container!r} "
                    "(ssh 255: host unreachable, or key/auth refused)."
                )
            if rc != 0:
                raise OrchestratorStateUnreadable(
                    f"`docker inspect {container}` on {host!r} exited {rc}; "
                    f"output: {out.strip()!r}. Likely causes: the container "
                    "does not exist (was this env released?), the docker "
                    "daemon is down, or sudo was denied."
                )

            fields = [f.strip() for f in out.strip().split("|")]
            if len(fields) != 3 or not all(fields):
                # THE "could not answer, returned nothing, and nothing read as
                # clean" case, made explicit. rc 0 with unusable stdout is what a
                # drifted --format string or an unexpected remote docker version
                # produces, and it must never be mistaken for a healthy verdict.
                raise OrchestratorStateUnreadable(
                    f"`docker inspect {container}` on {host!r} exited 0 but its "
                    f"output is unusable: {out!r}. Expected three "
                    "'|'-separated fields (health|state|image). docex cannot "
                    "tell whether this container is healthy, so it fails."
                )
            health, state, image = fields

            # WHY state is judged BEFORE the NOHEALTH sentinel — same reasoning
            # as the elastic path's lastStatus check: a container that is not
            # running is a "this is down" fact, and diagnosing it as "your
            # image declares no healthcheck" would send the operator to the
            # wrong place. Both orders fail; only this one is accurate.
            if state != "running":
                raise DeployedServiceUnhealthy(
                    f"container {container!r} on {host!r} is not running: "
                    f"state={state!r} (want 'running'), health={health!r}."
                )
            if health == "NOHEALTH":
                raise OrchestratorStateUnreadable(
                    f"container {container!r} on {host!r} is running but "
                    "declares no healthcheck, so its health is unknowable. Its "
                    "image is likely a pre-1.7.0 build from before every core "
                    f"service owed a probe ({image}). See healthchecks.md."
                )
            if health == "starting":
                raise DeployedServiceUnhealthy(
                    f"container {container!r} on {host!r} is still inside its "
                    "healthcheck start period (health=starting). It has not yet "
                    "reported healthy; re-run stagetest once it has."
                )
            if health != "healthy":
                raise DeployedServiceUnhealthy(
                    f"container {container!r} on {host!r} is not healthy: "
                    f"health={health!r}, state={state!r} (want 'healthy' / "
                    "'running')."
                )

            _assert_version(image, ctx.project.version, where=f"{container!r} on {host!r}")
            print(
                f"stagetest: {container} — healthy, running, image {image}."
            )
            checked += 1
    return checked


# ---------------------------------------------------------------------------
# Elastic — ECS task state + task-definition revision.
# ---------------------------------------------------------------------------


def _check_elastic(
    compiled: CompiledEnv,
    ctx: ProjectContext,
    *,
    env: str,
    cores: list[CompiledService],
    aws: AWSClient,
) -> int:
    """Read every core ECS service's RUNNING tasks. Returns the number of tasks
    verified."""
    cluster = ecs_cluster_name(
        ctx.project.name, env, ctx.transfer_tables.naming_policies
    )

    checked = 0
    for svc in cores:
        # WHY there is no `try` around this call, and none may be added: letting
        # AWSCredentialsMissing, ClusterNotFoundException and
        # ServiceNotFoundException propagate IS the implementation of the
        # can't-answer modes for absent credentials, absent cluster, and absent
        # service. Catching any of them here is how "docex could not look" turns
        # into "nothing looked wrong."
        arns = aws.ecs_list_service_task_arns(cluster, svc.global_name)
        if not arns:
            # THE CENTRAL EMPTY-SET TRAP. A service with zero running tasks is
            # not "all of its tasks are healthy" — it is down.
            raise DeployedServiceUnhealthy(
                f"ECS service {svc.global_name!r} in cluster {cluster!r} has "
                "zero RUNNING tasks. An empty task list is not a healthy "
                "service."
            )
        records = aws.ecs_describe_tasks(cluster, arns)

        if len(records) < len(arns):
            # The bounded re-read. A task can stop between ListTasks and
            # DescribeTasks — ECS replaces tasks on its own schedule (scaling, AZ
            # rebalance, platform updates), so one unlucky replacement mid-read
            # is not evidence about the release. `ecs_wait_for_task` already
            # carries a 30s window for the same class of eventual consistency.
            #
            # ONE re-read, then fail — never a loop that can decide "probably
            # fine." What advance 005 condemned was a check reporting OK when it
            # could not answer; a re-read that exhausts and then raises does not
            # do that.
            #
            # BOTH calls are redone: the truthful question on the second pass is
            # "what tasks does this service have *now*", not "where did that one
            # ARN go".
            #
            # SCOPED TO A SHRINKING TASK SET ONLY — never to a task that was
            # returned and reported unhealthy. That scoping is what makes the
            # re-read structurally unable to mask an unhealthy service: an
            # unhealthy task is *present* in `records` and is judged below, on
            # the first pass, without a second look.
            time.sleep(_TASK_SET_REREAD_DELAY_S)
            arns = aws.ecs_list_service_task_arns(cluster, svc.global_name)
            if not arns:
                raise DeployedServiceUnhealthy(
                    f"ECS service {svc.global_name!r} in cluster {cluster!r} "
                    "has zero RUNNING tasks (on a re-read). An empty task list "
                    "is not a healthy service."
                )
            records = aws.ecs_describe_tasks(cluster, arns)
            if len(records) < len(arns):
                missing = sorted(set(arns) - {r["task_arn"] for r in records})
                raise OrchestratorStateUnreadable(
                    f"ECS returned no record for {len(missing)} of "
                    f"{len(arns)} listed task(s) of service "
                    f"{svc.global_name!r}: {missing}. The task set was **still "
                    "inconsistent after a re-read**, so docex cannot say what "
                    "is running. This is not a verdict about the service's "
                    "health — re-run stagetest."
                )

        # `runningCount` vs `desiredCount` is deliberately NOT checked, and no
        # `describe_services` call is made. On `stage`, `effective_replicas`
        # clamps every core service to 1, so the only reachable shortfall is
        # zero tasks — already caught above, loudly. A third AWS call to detect
        # a state `stage` cannot be in is cost without coverage. Recorded here
        # because a silent omission is indistinguishable from an oversight.
        for record in sorted(records, key=lambda r: r["task_arn"]):
            arn = record["task_arn"]
            health = record["health_status"]
            last = record["last_status"]

            # WHY lastStatus is judged BEFORE healthStatus: we list tasks by
            # `desiredStatus=RUNNING`, which includes tasks that have not
            # reached RUNNING yet — and ECS reports healthStatus=UNKNOWN for
            # those. Judged in the other order, a task merely still starting
            # gets diagnosed as "no container declares a health check" and the
            # operator is sent to look at their probe instead of at a slow
            # rollout. Both orders fail, so the gate is honest either way; only
            # this one is *accurate*.
            if last != "RUNNING":
                raise DeployedServiceUnhealthy(
                    f"ECS task {arn!r} of service {svc.global_name!r} is not "
                    f"running: lastStatus={last!r} (want 'RUNNING'), "
                    f"healthStatus={health!r}. If this is a rollout in "
                    "progress, re-run stagetest once it has converged."
                )
            if health == "UNKNOWN":
                # The elastic twin of the fixed path's NOHEALTH sentinel: ECS
                # aggregates healthStatus only over containers that declare a
                # health check, and reports UNKNOWN when none does. Reachable
                # here only for a task that IS running, which is what makes the
                # pre-1.7.0 diagnosis below trustworthy.
                raise OrchestratorStateUnreadable(
                    f"ECS task {arn!r} of service {svc.global_name!r} reports "
                    "healthStatus=UNKNOWN while RUNNING: no container in this "
                    "task declares a health check, so its health is "
                    "unknowable. Its task definition is likely a pre-1.7.0 "
                    "revision from before every core service owed a probe. "
                    "See healthchecks.md."
                )
            if health != "HEALTHY":
                raise DeployedServiceUnhealthy(
                    f"ECS task {arn!r} of service {svc.global_name!r} is not "
                    f"healthy: healthStatus={health!r}, lastStatus={last!r} "
                    "(want 'HEALTHY' / 'RUNNING')."
                )

            # A raise from this call propagates: a revision we cannot read
            # (deregistered, throttled, denied) must never be read as "assume
            # the version is right".
            images = aws.ecs_task_definition_images(record["task_definition"])
            # `svc.name` is the two-segment compiled identity (`api-clock`), which
            # is what the HCL emitter names the app container inside the task
            # definition.
            if svc.name not in images:
                raise OrchestratorStateUnreadable(
                    f"task definition {record['task_definition']!r} declares no "
                    f"container named {svc.name!r} (found: "
                    f"{sorted(images)}); docex cannot read the deployed "
                    "version. Unreachable via the current emitter and guarded "
                    "anyway, because an unreadable version silently becoming a "
                    "correct one is the failure this step exists to prevent."
                )
            _assert_version(
                images[svc.name], ctx.project.version, where=f"task {arn!r}"
            )
            print(
                f"stagetest: {svc.global_name} task {arn} — HEALTHY, RUNNING, "
                f"image {images[svc.name]}."
            )
            checked += 1
    return checked


# ---------------------------------------------------------------------------
# Shared version read.
# ---------------------------------------------------------------------------


def _version_from_image_ref(ref: str) -> str:
    """The version tag of a container image ref.

    Raises ``OrchestratorStateUnreadable`` when no tag can be read — a
    digest-pinned ref (``repo@sha256:…``) or one with no ``:`` after the final
    ``/``.

    Unreachable today: ``_image_ref`` never digest-pins a *core service* image
    (only the otelcol sidecar is pinned, and the sidecar is not checked).
    Guarded anyway, and for one line: an unreadable version silently becoming a
    correct one is the exact failure this module exists to prevent.
    """
    if "@" in ref:
        raise OrchestratorStateUnreadable(
            f"image ref {ref!r} is digest-pinned and carries no version tag; "
            "docex cannot read the deployed version from it."
        )
    last_segment = ref.rsplit("/", 1)[-1]
    if ":" not in last_segment:
        raise OrchestratorStateUnreadable(
            f"image ref {ref!r} carries no version tag; docex cannot read the "
            "deployed version from it."
        )
    return last_segment.rsplit(":", 1)[1]


def _assert_version(ref: str, expected: str, *, where: str) -> None:
    """Assert an image ref's tag is ``expected``, else raise."""
    found = _version_from_image_ref(ref)
    if found != expected:
        # The message quotes the FULL ref, not just the tag: which registry and
        # repository the wrong version came from is the operator's next question.
        raise DeployedServiceUnhealthy(
            f"{where} is running image {ref!r} (version {found!r}), but this "
            f"project is version {expected!r}. stagetest must not certify a "
            "version it is not testing."
        )

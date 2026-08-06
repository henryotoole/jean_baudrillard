# Mod 123 — Implementation Steps

Replace the Service Connect consumer reconcile's consumer-side operand: **task
`startedAt` → the consumer's PRIMARY ECS deployment `createdAt`**, and widen the
margin from 0 to 60 s.

Everything is relative to the docex codebase root
`/home/ubuntu/.claude/jean_baudrillard/docex`, except the doctrine files, which
are under `/home/ubuntu/.claude/jean_baudrillard/doctrine`.

Read `overview.md` in this folder first. §§ 3, 4 and 5.1 there carry reasoning
this file references and does not repeat.

Work on branch `005_process_type_solidification`. Do not commit; the mod cycle's
review step reads the uncommitted diff.

---

## The one-line summary of the defect

`CreateDate` is stamped when the ECS **service** is created, so a task of that
service always starts *after* it. Whenever a consumer's tasks are (re)started by
the same apply that creates a target's name — every first release, and every
release that bumps the consumer's image — `startedAt <= CreateDate` cannot be
true. The check is inert exactly where it was built to fire.

The resolvable name set is actually frozen at **deployment** creation: each Envoy
identifies to the ECS control plane by its task-set ARN (the deployment id) and
is served a cluster list fixed for that deployment. Tasks launched later into the
same deployment inherit it and never re-read the namespace.

---

## Step 0 — Baseline

```bash
cd /home/ubuntu/.claude/jean_baudrillard/docex
git rev-parse --abbrev-ref HEAD          # expect 005_process_type_solidification
python -m pytest tests/unit -q 2>&1 | tail -3
python -m pytest -m integration -q 2>&1 | tail -3
```

Record both counts. Baseline is **unit 1007, integration 20 passed / 0 failed**.
Any pre-existing failure is reported, not fixed here.

---

## Step 1 — The red test

Write this one first and watch it fail against the current code. It is the walk's
real failure, as data.

Append to `tests/unit/test_service_connect_reconcile.py` (it will be rewritten
wholesale in Step 7; this is only to establish red):

```python
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
```

It errors today (`FakeAWSClient` has no `ecs_deployment_times`). That is the
intended red.

---

## Step 2 — `src/docex/aws/client.py`: the port

**Delete** the whole `ecs_running_task_start_times` stub (currently `:326-343`),
docstring included.

**Add**, in the same `Mod 109 / 114` block — retitle that comment banner to
`Mod 109 / 114 / 123: Service Connect consumer reconcile.`:

```python
    def ecs_primary_deployment_times(
        self, cluster: str, services: list[str],
    ) -> dict[str, datetime]:
        """``createdAt`` of the PRIMARY deployment of each named ECS service.

        This is the operand the release's consumer reconcile compares endpoint
        registrations against. A Service Connect Envoy identifies itself to the
        ECS control plane by its **task-set ARN** — the deployment id — and is
        served a cluster list fixed for that deployment; tasks launched later
        into the same deployment inherit it and never re-read the namespace. So
        the durable question is how old the *deployment* is, not how old its
        tasks are (mod 123; mod 114 asked the second and could not fire).

        Two omissions are deliberate and are part of the contract:

        - **A service with no PRIMARY deployment is absent from the mapping.**
        - **A service ECS does not return (missing, or reported under
          ``failures``) is absent from the mapping.**

        Absence is not an error and must not raise. The caller reads a missing
        entry as "redeploy", which is the safe direction: an unreadable
        deployment age cannot be shown to postdate anything.

        Implementations MUST accept any number of services; ``DescribeServices``
        caps at 10 per call, and chunking is the implementation's business.
        """
        ...
```

Leave `service_connect_endpoints`, `ecs_force_new_deployment` and
`ecs_wait_services_stable` untouched. In `service_connect_endpoints`'s docstring,
change the clause "``CreateDate`` is the durable fact the release's consumer
reconcile compares task ages against" to "…compares **deployment** ages
against".

---

## Step 3 — `src/docex/aws/boto3_client.py`: the adapter

**Delete** `ecs_running_task_start_times` (`:527-553`).

**Add** in its place:

```python
    def ecs_primary_deployment_times(
        self, cluster: str, services: list[str],
    ) -> dict[str, datetime]:
        if not services:
            return {}
        ecs = self._client("ecs")
        out: dict[str, datetime] = {}
        # DescribeServices accepts at most 10 services per call.
        for i in range(0, len(services), 10):
            chunk = services[i:i + 10]
            try:
                resp = ecs.describe_services(cluster=cluster, services=chunk)
            except ecs.exceptions.ClusterNotFoundException:
                # No cluster means no deployments to read; every service reads
                # as absent, and the caller treats absence as "redeploy".
                continue
            for svc in resp.get("services", []):
                name = svc.get("serviceName")
                if not name:
                    continue
                for dep in svc.get("deployments", []):
                    if dep.get("status") != "PRIMARY":
                        continue
                    created = dep.get("createdAt")
                    if created is not None:
                        out[name] = created
                    break
        return out
```

Notes for whoever writes this:
- `describe_services` reports unknown services under `failures`, not as an
  exception — leaving them out of `out` is the whole handling required.
- Do **not** add a `services_stable` wait here; the caller already owns waiting.
- `_SC_CLIENT_ENTRY_PREFIX` and `service_connect_endpoints` are unchanged.

---

## Step 4 — `src/docex/pipeline/release.py`

### 4a. The margin constant (`:217-234`)

Replace the whole `_RECONCILE_SKEW_MARGIN_S` block — constant and comment — with:

```python
#: Grace added to a name's registration time before comparing it against the
#: consumer's PRIMARY deployment age. Ties are resolved toward redeploying by
#: the ``<=`` in the comparison itself; this widens that further, on purpose.
#:
#: WHY it is non-zero, and why sixty: this is NOT a clock-skew allowance. The
#: genuine uncertainty is small — advance 005's recon bracketed the freeze
#: instant to (deployment createdAt - 11.6s, +2.4s], and Cloud Map's
#: ``CreateDate`` precedes the name's appearance in the control plane's served
#: cluster list by under a second. Five seconds would cover both.
#:
#: Sixty seconds instead COLLAPSES THE CONCURRENT-CREATION WINDOW INTO A
#: REDEPLOY. Within roughly a minute of a consumer's deployment we stop trying
#: to adjudicate whether a name was visible to it and simply redeploy, because
#: (a) that window is exactly where the boundary is unmeasurable — ECS does not
#: expose its internal ordering, and two timestamps seconds apart do not report
#: who won; and (b) the two errors are not symmetric. A false negative there is
#: permanent and silent: an env that exits 0 with both sides reporting healthy
#: and every call across the edge failing. A false positive is one rolling
#: deploy.
#:
#: The cost lands only where the race is real — one rolling deploy per consumer
#: on a first release or a shape change. On an ordinary code-only release the
#: gap between a deployment and a long-established name is days or weeks, the
#: comparison is not close, and the step is still a no-op.
_RECONCILE_SKEW_MARGIN_S = 60
```

Do **not** write "covers clock skew" anywhere in this file. Mod 114 shipped an
inert check behind a plausible-but-false load-bearing sentence in this exact
comment; a second one is not acceptable.

`_RECONCILE_STABLE_TIMEOUT_S = 600` and `_as_utc` are unchanged.

### 4b. Split the predicate (replaces `_consumer_reconcile_set`, `:247-321`)

Two functions. The first is pure and AWS-free; the second does the comparison.
This split exists so the deployment read can be **one batched call** over exactly
the consumers that could possibly fire.

```python
def _reconcile_candidates(
    compiled: Any,
    *,
    endpoint_created: dict[str, datetime],
) -> list[tuple[str, list[tuple[str, datetime]]]]:
    """Consumers worth reading a deployment age for, with their registered targets.

    Pure: no AWS. Returns ``(consumer_global_name, [(target_global_name,
    created)])`` for every core service that declares at least one core ``uses``
    target which is actually registered in the namespace. A consumer with no
    such target can never fire, so it is dropped here and costs no API call.
    """
    out: list[tuple[str, list[tuple[str, datetime]]]] = []
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        if not svc.is_core or not svc.uses_core:
            continue
        # WHY: `update_service` against an ECS service that does not exist is
        # an error, not a no-op, so a core service that emits no `ecs_service`
        # must be skipped rather than redeployed.
        #
        # DO NOT DELETE THIS AS DEAD. After Mod 116 no *bundled* core role can
        # reach this branch — `web`, `worker` and `clock` all emit an
        # `ecs_service`. It is reachable only through a PROJECT-LOCAL transfer
        # table declaring a core role whose elastic `emits` omits
        # `ecs_service`. That makes the branch untestable from the bundled
        # tables and permanently load-bearing: without it the failure appears
        # as a release aborting mid-flight in a downstream project with a
        # custom role table, which is the hardest place to diagnose it.
        if "ecs_service" not in svc.emits.get("elastic", []):
            continue

        targets: list[tuple[str, datetime]] = []
        for key in sorted(svc.uses_core):
            target = compiled.services.get(key)
            # An unresolvable target cannot survive validation, but the
            # reconcile must not be the thing that raises if one ever does.
            if target is None:
                continue
            # Only a target that emits an `ecs_service` gets a Service Connect
            # registration, so only such a target can appear in the namespace.
            if "ecs_service" not in target.emits.get("elastic", []):
                continue
            created = endpoint_created.get(target.global_name)
            if created is None:
                continue
            targets.append((target.global_name, _as_utc(created)))
        if targets:
            out.append((svc.global_name, targets))
    return out


def _consumer_reconcile_set(
    candidates: list[tuple[str, list[tuple[str, datetime]]]],
    *,
    deployment_created: dict[str, datetime],
) -> list[tuple[str, str]]:
    """Consumers that must be redeployed, as ``(consumer, triggering target)``.

    A consumer qualifies when its PRIMARY deployment was created at or before
    the Cloud Map ``CreateDate`` of a name it ``uses`` (plus
    ``_RECONCILE_SKEW_MARGIN_S``). A Service Connect Envoy is served a cluster
    list fixed for its deployment's task-set ARN, so no task in such a
    deployment can ever resolve that target — replacing tasks inside the
    deployment does not help, and the application retrying forever does not
    either.

    A consumer absent from ``deployment_created`` fires. An unreadable
    deployment age cannot be shown to postdate anything, and the safe direction
    is one rolling deploy rather than a silently broken env.

    Both operands are durable AWS state read after the apply, which is what
    makes this self-healing: it describes the world rather than this release.
    An interrupted release, a hand-run ``tofu apply``, or a service created out
    of band all leave a state the next release reads correctly.

    It is also SELF-CLEARING BY CONSTRUCTION: `forceNewDeployment` mints a new
    PRIMARY deployment with a fresh `createdAt`, so a re-run of the same release
    reads a consumer that now postdates its targets and skips it. Idempotency
    here is structural, not asserted.

    Mod 123 replaced mod 114's task-`startedAt` operand, which measured the
    wrong event: `CreateDate` is stamped at ECS *service* creation, so a task
    of that service always starts after it, and the comparison could not fire
    whenever consumer and target were created by the same apply.
    """
    out: list[tuple[str, str]] = []
    margin = timedelta(seconds=_RECONCILE_SKEW_MARGIN_S)
    for consumer, targets in candidates:
        created_at = deployment_created.get(consumer)
        if created_at is None:
            out.append((consumer, targets[0][0]))
            continue
        created_at = _as_utc(created_at)
        for global_name, created in targets:
            if created_at <= created + margin:
                out.append((consumer, global_name))
                break
    return out
```

`Callable` may become an unused import in this module — check and remove it from
the `typing` import if so.

### 4c. `_reconcile_service_connect_consumers` (replaces `:324-422`)

Keep the function's name, signature, return contract, redeploy loop, error
handling and bounded wait. Change the middle and the docstring.

Docstring: replace the "Mod 114:" paragraph with:

```
    Mod 123: the consumer operand is the age of its PRIMARY ECS **deployment**,
    not of its tasks. Service Connect freezes a deployment's resolvable name set
    at deployment creation — every Envoy in it is served a cluster list keyed to
    the deployment's task-set ARN — so a task replaced inside a stale deployment
    comes up just as unable to resolve. Mod 114 compared task ``startedAt``
    against the same registration and could not fire when consumer and target
    were created by one apply, which is every first release; the 1.7.0 elastic
    walk found it inert on `prod`.

    Both operands are still post-apply durable state, so the step remains
    self-contained and self-healing, and on a converged env every consumer's
    deployment postdates every name it ``uses``, nothing fires, and no service
    is touched.
```

Body — replace the `started_cache` / `task_started` closure and the
`_consumer_reconcile_set(...)` call with:

```python
    candidates = _reconcile_candidates(
        compiled, endpoint_created=endpoint_created,
    )
    if not candidates:
        return 0

    # One batched read over exactly the consumers that could fire. A converged
    # env therefore pays one ListServices plus one DescribeServices.
    deployment_created = aws.ecs_primary_deployment_times(
        cluster_name, [c for c, _ in candidates],
    )

    pairs = _consumer_reconcile_set(
        candidates, deployment_created=deployment_created,
    )
    if not pairs:
        return 0
```

Operator-facing messages — two strings change:

- The per-consumer redeploy line: `"its oldest running task predates the
  registration of its `uses` target {target!r}, and a client cannot resolve an
  endpoint added after it started."` becomes `"its current deployment predates
  the registration of its `uses` target {target!r}, and no task in that
  deployment can resolve an endpoint added after the deployment was created."`
- The redeploy-failure line: `"Its `uses` target {target!r} was registered after
  {consumer!r}'s tasks started"` becomes `"…was registered after {consumer!r}'s
  current deployment was created"`.

### 4d. Call sites — do not touch

`_release_elastic`'s two calls (rollback branch, post-final-apply) stay exactly
as they are, including their surrounding comments.

---

## Step 5 — `tests/conftest.py`: `FakeAWSClient`

- `:540` — replace
  `ecs_task_start_times: dict[str, list[datetime]] = field(default_factory=dict)`
  with
  `ecs_deployment_times: dict[str, datetime] = field(default_factory=dict)`.
- Update the class docstring's bullet list if it mentions task start times.
- `:753-759` — replace the recorder:

```python
    def ecs_primary_deployment_times(
        self, cluster: str, services: list[str],
    ) -> dict[str, datetime]:
        self._record(
            "ecs_primary_deployment_times",
            cluster=cluster, services=list(services),
        )
        # Only the requested services, and only those scripted — so a test can
        # exercise "absent from the mapping → fire" by simply omitting one.
        return {
            name: self.ecs_deployment_times[name]
            for name in services
            if name in self.ecs_deployment_times
        }
```

---

## Step 6 — `tests/unit/test_aws_service_connect_endpoints.py`

Delete `test_ecs_running_task_start_times_filters_and_chunks` (`:83`) and
`test_ecs_running_task_start_times_missing_service_reads_as_no_tasks` (`:119`),
plus any now-unused stub they relied on.

Add two adapter tests in the same style (monkeypatched boto3 stub):

1. `test_ecs_primary_deployment_times_chunks_at_ten` — pass 23 service names,
   assert `describe_services` was called three times with chunk sizes
   `10, 10, 3`, and that only `status == "PRIMARY"` deployments are read (script
   a service carrying both an `ACTIVE` and a `PRIMARY` deployment and assert the
   PRIMARY's `createdAt` is what comes back).
2. `test_ecs_primary_deployment_times_omits_unreadable_services` — a service
   returned under `failures`, and a service with an empty `deployments` list,
   are both **absent** from the mapping rather than raising or defaulting.

---

## Step 7 — `tests/unit/test_service_connect_reconcile.py`: rewrite

Keep the module's existing scaffolding: `_FIXTURE_ELASTIC`, `_WORKER`, `_t`,
`_project`, the `web_uses_worker` fixture, `_redeployed`, `_waited`, `_run`.

**Add this module docstring, and do not paraphrase it away** — it is the point of
the mod:

```python
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
```

Then write the cases below. `_d(...)` helper suggested for deployment times, on
the same clock as `_t`; use whatever reads cleanly, but keep timelines coherent.

| Test | Fixture shape | Assert |
| ---- | ------------- | ------ |
| `test_converged_env_is_a_no_op` | names at 20:40; both deployments at 20:50 | no redeploy, **and** no `ecs_wait_services_stable` call |
| `test_code_only_release_weeks_later_is_free` | names 2026-07-01; deployments 2026-08-05 | no redeploy; docstring names this as the case the whole no-op property rests on |
| `test_new_target_concurrent_with_consumer_deployment_fires` | `api-web` deployment 20:46:10, `api-worker` name 20:46:05 (and worker's own deployment 20:46:06) | `["sample-prod-api-web"]` |
| `test_aborted_release_rerun_redeploys_stale_consumer` | release N created worker's name at 20:46:05 and web's deployment at 20:46:02, then aborted; the re-run's apply is a no-op so both are unchanged | `["sample-prod-api-web"]`; docstring states this is the hole mod 114 existed to close and did not |
| `test_exact_tie_at_margin_redeploys` | web deployment = worker name + exactly 60 s | fires |
| `test_one_second_past_margin_is_left_alone` | web deployment = worker name + 61 s | does not fire; docstring pins the boundary from the other side |
| `test_client_bookkeeping_entries_do_not_trigger_a_redeploy` | keep the existing intent: an `aws-ecs-sc.client.<uuid>.…` entry far newer than the consumer's deployment, all real endpoints older | no redeploy |
| `test_uses_cycle_redeploys_both_sides` | keep the existing cycle fixture; both deployments concurrent with both names | both fire, one pass |
| `test_consumer_absent_from_deployment_map_is_redeployed` | script `ecs_deployment_times` **omitting** `sample-prod-api-web` | fires; docstring: an unreadable deployment age cannot be shown to postdate anything, so the safe direction is a redeploy |
| `test_walk_regression_first_prod_release` | Step 1's test, verbatim | fires |
| `test_clock_consumer_is_redeployed_on_the_same_terms` | port the existing clock fixture onto deployment times | fires |
| `test_converged_clock_is_left_alone` | port | no redeploy |
| `test_slow_rollout_warns_but_does_not_fail_the_release` | port; `fake_aws.ecs_services_stable = False` | `rc == 0`, warning path |

**Delete `test_consumer_with_no_running_tasks_is_not_redeployed` outright.**
Running tasks are no longer an operand, so its premise is gone rather than
changed. Do not adapt it into a `desired_count: 0` test — a zero-count service
still has a PRIMARY deployment and is judged on the same terms as any other.

Also delete `test_task_one_second_after_registration_is_not_redeployed` and
`test_consumer_of_preexisting_target_is_not_redeployed`; they are superseded by
`test_one_second_past_margin_is_left_alone` and
`test_code_only_release_weeks_later_is_free`.

---

## Step 8 — `tests/unit/test_pipeline_rollback.py`

`test_rollback_elastic_reconcile_is_a_noop` (`:580`) still passes unchanged — the
sample elastic fixture's `api.web` declares `uses: [appdb]` only, so
`_reconcile_candidates` finds no core-uses consumer and never reads a deployment
age.

But its docstring claims something it does not test ("every consumer task still
postdates every registration"), which is the § 3 pattern in miniature. Replace
that sentence with an honest one:

```
    What this asserts is the WIRING: the rollback branch runs the reconcile step
    like any other release, with a populated namespace. It does not exercise the
    predicate — the sample elastic fixture declares no core `uses` edge, so
    there is no consumer to judge. The predicate itself is covered in
    `test_service_connect_reconcile.py`.
```

Add an assertion that `ecs_primary_deployment_times` was **not** called, which is
what proves the candidate-filtering shortcut works and a converged rollback pays
one API call.

---

## Step 9 — Doctrine

Four files. The wording below is ratified; reproduce it, do not improve it.

### 9a. `doctrine/infrastructure/cicl.md:419`

Replace the paragraph beginning "ECS Service Connect fixes a client task's set"
with:

> ECS Service Connect fixes a service's set of **resolvable endpoint names at deployment creation**. Each Envoy sidecar identifies itself to the ECS control plane by its task-set ARN — the deployment id — and is served a cluster list fixed for that deployment; tasks launched later into the same deployment inherit it rather than re-reading the namespace. An endpoint registered in the namespace *after* a deployment was created is not merely unreachable from its tasks — it is unresolvable, for the life of the deployment. The name does not exist. Backing off and retrying never converges, because there is nothing to converge on.

### 9b. `doctrine/infrastructure/cicl.md:421`

The next paragraph reads "So a core service created alongside a `uses` target it
has never seen registered can be permanently unable to reach it…". Change "a
core service created alongside" to "a core service **deployed** alongside" and
leave the rest.

### 9c. `doctrine/infrastructure/cicl.md:423`

Replace the whole `**docex** closes this at release time` paragraph with:

> **`docex` closes this at release time**, by redeploying, after the apply, any consumer whose current deployment was created before the registration of a name it `uses`. Note carefully that this is *not* the deploy-time ordering emulation rejected above, and the distinction is what makes it sound: an endpoint **registration is durable state**, owned by the service rather than by task liveness, and it survives every task replacement. Holding once is therefore permanently sufficient — once a consumer's deployment postdates the names it needs, every task ECS starts into that deployment (scaling, AZ rebalance, failed health check, platform update) inherits the same correct cluster list. A readiness gate decays because liveness changes; a deployment's resolved name set does not. Because *both* halves of the comparison are durable — deployment age as much as registration age — the check describes the env rather than the release that produced it, and any broken env it can read it can also repair. See [release.md § Service Connect Consumer Reconcile](./specifics/release.md#service-connect-consumer-reconcile).

The old text credited "every later task starts into a namespace that already
contains the name". That is the claim recon 2 refuted directly — a replacement
task inside the same deployment probed 47 times over 8 minutes and never saw the
name. The conclusion survives; the mechanism does not.

### 9d. `doctrine/infrastructure/specifics/release.md:98`

Replace with:

> ECS Service Connect fixes a service's set of resolvable endpoint names **at deployment creation** — each Envoy is served a cluster list keyed to its deployment's task-set ARN, and later tasks in that deployment inherit it. An endpoint registered after a deployment was created is unresolvable from every task in it — not slow, not intermittently unreachable, but absent. See [`cicl.md § Resilience covers reachability, not resolvability`](../cicl.md#resilience-covers-reachability-not-resolvability) for why application-level retrying cannot recover from this.

### 9e. `release.md:100-104` — the question and the steps

The sentence ending "…`release` asks one question of current AWS state — **is any
running consumer task older than the registration of a name it needs?** — and
repairs whatever it finds:" becomes "…— **is any consumer's current deployment
older than the registration of a name it needs?** — and repairs whatever it
finds:".

Steps 1 and 2 become:

> 1. Reads the Cloud Map `CreateDate` of every endpoint name in the env namespace, and the `createdAt` of the PRIMARY deployment of each core service that declares a core `uses` target.
> 2. Redeploys (`forceNewDeployment`) every core service whose PRIMARY deployment was created at or before the `CreateDate` of a name it `uses`, plus a fixed margin.

Step 3 is unchanged.

### 9f. `release.md:110` — the first property bullet

"Where every consumer task postdates every name it `uses`, the comparison finds
nothing…" becomes "Where every consumer's **deployment** postdates every name it
`uses`, the comparison finds nothing…". The rest of the bullet stands.

`release.md:111`'s per-consumer bullet: "A consumer whose own targets all predate
its tasks" becomes "…all predate its deployment".

### 9g. `release.md:116` — the steady-state bullet, gains a second reason

> - **The read must not see the apply's own churn.** `aws_ecs_service` is emitted with `wait_for_steady_state = true`, so the apply does not return until its rollouts have settled. That matters twice: the step must not read tasks that are already on their way out, and it must not read a deployment `createdAt` that is about to be superseded by one the same apply is still creating.

### 9h. `release.md:117` — **the reversal**

Replace the whole `**Ties break toward redeploying.**` bullet with:

> - **Ties break toward redeploying, and the margin is deliberately wide.** The comparison is `<=`, and a fixed 60-second margin is added to the registration time before comparing. That margin is not a clock-skew allowance — the genuine uncertainty is far smaller than a minute. It exists to collapse the **concurrent-creation window** into a redeploy: when a consumer's deployment and a target's name are created seconds apart, which one won is a race whose outcome the two timestamps do not report, so the step stops trying to read it and simply acts. The cost is one rolling deploy per consumer on a first release or a shape change — the releases where the race is real — and nothing at all on an ordinary code-only release, where the gap is days or weeks and the comparison is not close. A false positive costs one rolling deploy; a false negative costs a permanently broken env that exits 0. Never round toward silence.

The clause being deleted — "never widen the tie into a grace window, which would
fire on nearly every consumer on every first release, since the name is created
with the ECS service before any of its tasks exist" — was written as a
trap-marker against exactly this change. It is true of task `startedAt` and false
of deployment `createdAt`. Remove it; do not soften it.

### 9i. `release.md:122`

"with no launch-time name freeze" becomes "with no deployment-time name freeze".

### 9j. `doctrine/infrastructure/reasoning/elastic_release_pattern.md:18`

Replace the sentence beginning "Unfortunately, a client task's copy of that
registry is written *exactly once, statically*, when the task launches." with:

> Unfortunately, that registry is resolved *exactly once, statically*, when an ECS **deployment** is created; every task in the deployment is served the same fixed copy. A name registered after the deployment does not exist for any of its tasks — it is **unresolvable** rather than merely unreachable, so no amount of application-level backoff ever converges on it, and replacing a task does not help unless the replacement lands in a new deployment.

---

## Step 10 — The advance design record

`docex/plans/advances/005_process_type_solidification/service_connect_reconcile_trigger.md`.

1. **Status block** — add a line: mod 123 replaced the consumer operand a second
   time; the record below is corrected in place and its § Verified measurements
   stand.
2. **Vocabulary precision 1**, the `> **Corrected by measurement.**` block —
   replace its final sentences. The current text says the correction
   "**strengthens the fix** — `CreateDate` sits earlier relative to any task, so
   `startedAt < CreateDate` is strictly more conservative". Replace with:

   > **This inference was inverted, and it is the error that shipped mod 114 inert.** Pushing `CreateDate` *earlier* relative to any task makes `startedAt <= CreateDate` **harder** to satisfy, not easier. A task of a service always starts after that service was created, so wherever a consumer's tasks are (re)started by the same apply that creates a target's name — every first release, and every release that bumps the consumer's image — the comparison cannot fire at all. It remains satisfiable only where the consumer is entirely untouched by the apply and its tasks are already old. Mod 123 replaces the operand with the consumer's PRIMARY deployment `createdAt`; see [§ Recon 2](#recon-2).

3. **Vocabulary precision 2** ("The read is per-task-launch, not per-deployment…
   Same reason a task replaced for any other cause comes up correct with no
   intervention") — **strike it as false** and replace with:

   > 2. **The read is per-deployment, not per-task-launch.** `forceNewDeployment` works because it creates a **new deployment**, and a deployment's cluster list is resolved when the deployment is created. A task replaced for any other cause — scaling, AZ rebalance, a failed health check — lands in the *same* deployment and inherits the same stale list, so it does **not** come up correct. [§ Recon 2](#recon-2) measured this directly.

4. **§ The invariant** — "every consumer task must be younger than every name it
   needs" becomes "every consumer **deployment** must be younger than every name
   it needs".
5. **§ The fix**, the operand table — the "Consumer task age" row becomes
   "Consumer deployment age | `DescribeServices` on the consumer's ECS service;
   take `deployments[?status=='PRIMARY'].createdAt`, batched at 10 services per
   call". The paragraph beneath ("Redeploy core service `P` iff some running task
   of `P` started before…") becomes deployment-based.
6. **§ Three implementation details that matter, detail 2** — replace with the
   § 5.1 reasoning from mod 123's `overview.md`: the margin is a deliberate
   widening that collapses the concurrent-creation window into a redeploy, not a
   skew allowance; 60 s; the asymmetry of the two errors.
7. **New § Recon 2**, placed after § Verified. Carry, verbatim in substance:
   - the mechanism (task-set ARN identity, fixed cluster list, inheritance);
   - the timestamp table from `overview.md` § 4 (47-probe replacement task;
     2.4 s-after invisible; 11.6 s-before visible with `desiredCount: 0`;
     `updatedAt` inert);
   - the bracket `(createdAt − 11.6 s, createdAt + 2.4 s]` and the note that the
     mechanism says the instant *is* `createdAt`, the bracket being measurement
     granularity;
   - the explicit statement that task `createdAt`/`startedAt` and
     `deployments[].updatedAt` are both excluded as operands.
8. § Verified's Q1/Q2 stay as written — they are correct measurements. Q1's
   "After task replacement" note may gain one clause: the replacement resolved
   because `forceNewDeployment` created a new *deployment*, not because the task
   was new.

---

## Step 11 — `docex/test_projects/PRE_CUT_CHECKLIST.md`

### 11a. D.9 and D.11 — record both operands

Add this box to **both** `### D.9 Release stage` and `### D.11 Release prod`. In
D.9 place it after the `api-clock` box; in D.11 after the
`/health/api/worker` box. Substitute the env in the cluster name.

```markdown
- [ ] **Record both reconcile operands, and the verdict.** For each consumer
  (`api-web` and `api-worker` — they form a `uses` cycle):
  ```bash
  aws ecs describe-services --cluster docex-smoke-elastic-<env> \
    --services api-web api-worker \
    --query "services[].[serviceName,deployments[?status=='PRIMARY']|[0].createdAt]"
  aws servicediscovery list-services \
    --query "Services[].[Name,CreateDate]"
  ```
  Write both timestamps into the walk log. **Expected verdict: `fire` on the
  first `prod` release** — deployment and name are created seconds apart — and
  **`skip` on the code-only 0.0.21 release**, where the gap is days. `release`
  prints one `release: reconciling Service Connect consumer …` line per consumer
  it fires on; the presence or absence of that line **is** the verdict, and it
  must agree with the two timestamps you recorded.

  > **Why this box exists.** The 1.7.0 walk measured the wrong timestamp (task
  > `startedAt`, mod 114) and `force-new-deployment` overwrote the evidence
  > before anyone knew which one mattered — so the failure had to be inferred
  > from a 503 rather than read off the operands. Recording both is what lets a
  > walk *confirm* the predicate instead of inferring it from a green fan-out.
```

### 11b. A.2.1 — the ordering carve-out

Append to `### A.2.1 Test projects are self-contained git repos`, after the two
existing boxes:

```markdown
> **Ordering carve-out — A.2.1 vs. C.6 / D.8.** A.2.1 describes each inner
> repo's *resting* state (on `main`, clean, `v<version>` at HEAD) and is asserted
> **before** [C.6](#c6-check--containerize) / [D.8](#d8-check--containerize).
> Those steps then deliberately restructure the history into the feature-branch
> shape their prerequisite demands — `main` at the **prior** release, the new
> version on a feature branch checked out now — and `merge` returns the repo to
> `main` with the new version at HEAD. The two states are mutually exclusive by
> design. Re-asserting A.2.1 between the restructure and `merge` will fail, and
> that failure is expected: **do not "repair" it by moving the tag**, which
> silently defeats the `check` version-bump gate.
```

Add to the feature-branch prerequisite blockquote in **both** C.6 and D.8:
"This deliberately conflicts with [A.2.1](#a21-test-projects-are-self-contained-git-repos)'s
resting state — see its ordering carve-out."

### 11c. B.16 — prose precision

In the B.16 item, replace "the exec block still carries `condition:
service_healthy` over the union of that codebase's **backing-targeted** `uses`
edges" with:

> the exec block still carries a `depends_on` entry over the union of that codebase's **backing-targeted** `uses` edges — `condition: service_healthy` where the target block declares a `healthcheck:`, `condition: service_started` where it does not (the fixed project's committed output shows `appdb → service_healthy`, `probe`/`events` → `service_started`)

---

## Step 12 — Gates

```bash
cd /home/ubuntu/.claude/jean_baudrillard/docex
python -m pytest tests/unit -q 2>&1 | tail -5
python -m pytest -m integration -q 2>&1 | tail -5
```

Then the retired-operand grep — it must return **nothing**:

```bash
grep -rn "startedAt\|ListTasks\|list_tasks\|ecs_running_task_start_times\|ecs_task_start_times" \
  src/ tests/ --include='*.py'
```

(`plans/` and `doctrine/` may still mention `startedAt` in historical prose; the
grep is scoped to code on purpose.)

Report the unit/integration counts against Step 0's baseline. Expected movement:
the reconcile file's case count changes, two adapter tests are swapped for two
others, and three tests are **deleted** (`test_consumer_with_no_running_tasks_is_not_redeployed`,
`test_task_one_second_after_registration_is_not_redeployed`,
`test_consumer_of_preexisting_target_is_not_redeployed`). Anything else moving is
a finding — report it, do not paper over it.

---

## Step 13 — Rebuild the candidate image

```bash
cd /home/ubuntu/.claude/jean_baudrillard
# use the repo's standard docex image build (see docex/plans/core or build script)
docker images docex:1.7.0
cd docex/test_projects/fixed   && ./bin/docex --version
cd ../elastic                  && ./bin/docex --version
```

Both must print `1.7.0`, and the image must postdate this mod's changes so the
follow-on partial elastic re-walk (D.9–D.11) exercises the fixed code. If the
build command is not obvious from the repo, stop and report rather than guessing
at it.

---

## Out of scope — do not do these

- **Core planning docs** (`docex/plans/core/release_flow.md`, `compiler.md`).
  They carry the same false claim and are corrected in the mod cycle's
  documentation step, not here.
- `CHANGELOG.md` — same.
- Any change to `service_connect_endpoints`, the `aws-ecs-sc.client.` filter,
  `ecs_force_new_deployment`, `ecs_wait_services_stable`,
  `_RECONCILE_STABLE_TIMEOUT_S`, the bounded wait, either call site in
  `_release_elastic`, or any emitted HCL (`wait_for_steady_state` stays).
- Implementing an unconditional-redeploy fallback. It is the escape hatch if the
  re-walk shows this predicate misfiring; it is not built now.
- Building the "standing invariant / `check`-time diagnosis" idea.
- Any `cicl_version` bump, `infra.yml` change, or upgrade-guide entry — this
  changes no authored surface.
- Committing. The review step reads the uncommitted diff.

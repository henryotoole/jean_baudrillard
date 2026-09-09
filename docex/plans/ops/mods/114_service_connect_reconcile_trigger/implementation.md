# Mod 114 — Implementation Steps

Implements the design in [`overview.md`](./overview.md). Read it first — the
*why* is there, and several choices below look arbitrary without it.

Repo root for every path in this document: `/home/ubuntu/.claude/jean_baudrillard`.
Code paths are relative to `docex/`; doctrine paths to `doctrine/`.

**One-line summary:** the elastic release's Service Connect reconcile stops
diffing the namespace against a pre-apply snapshot and instead asks, of
post-apply AWS state, *"is any running consumer task older than the registration
of a name it uses?"*

Work in this order. Steps 1–2 are the tests that must **fail** against today's
code before anything else changes.

---

## Step 0 — Baseline

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
python -m pytest tests/unit -q          # expect 996 passing
```

Branch is `005_process_type_solidification`. Do not switch branches. Do not
commit — the driving agent commits.

---

## Step 1 — Write the two failing tests first

These go in `tests/unit/test_service_connect_reconcile.py`, which is rewritten
wholesale in step 7. Write them now, in whatever temporary shape lets them run,
and **watch them fail** against the current predicate. The point is to see the
defect with your own eyes before deleting it; if the aborted-release test passes
against unmodified code, something about the fixture is wrong and the rest of
this mod is being built on sand.

**1a. The aborted-release re-run.** Topology: `api.web` `uses` `api.worker`.
Release N registered `sample-prod-api-worker` and aborted before the reconcile;
the operator re-runs. Post-apply state on the re-run:

- namespace: `sample-prod-api-web` and `sample-prod-api-worker` both present,
  `CreateDate` 20:46:00.
- `sample-prod-api-web`'s running tasks: one, `startedAt` 20:40:00 — it started
  before the worker's name existed and can never resolve it.

Expected: `sample-prod-api-web` is redeployed. Today's code sees an unchanged
name set across the apply, computes an empty diff, and redeploys nothing.

**1b. Client bookkeeping filter, pipeline level.** Same topology, converged:
every consumer task postdates every real endpoint. Add one namespace entry
`aws-ecs-sc.client.7f3c-uuid.sample-prod-api-web` with a `CreateDate` *newer*
than the consumer's tasks. Expected: **no** redeploy.

Both need the fake-client changes from step 5 to express their scripting, so
write step 5 first if that is easier — but do not touch `release.py` or
`hcl.py` until both tests exist and 1a is observed red.

---

## Step 2 — `aws/client.py`: the port

Replace the `service_connect_endpoint_names` protocol method (currently at
`:303-315`) and add one method. Keep the `# Mod 109` section banner, extending it
to `Mod 109 / 114`.

```python
def service_connect_endpoints(self, namespace_name: str) -> dict[str, datetime]:
    """Service Connect endpoint names in a namespace, mapped to their
    Cloud Map ``CreateDate``.

    These are the Cloud Map service names inside the env's namespace — the
    aliases a Service Connect *client* task can resolve, and only if they
    existed when that task started. ``CreateDate`` is the durable fact the
    release's consumer reconcile compares task ages against: the name is
    created when the ECS **service** is created, before any of its tasks
    exist, and it survives every task replacement beneath it.

    **A namespace that does not exist reads as the empty mapping**, which is
    the honest answer on a first release: nothing is registered yet.

    Implementations MUST exclude the ``aws-ecs-sc.client.<uuid>.<service>``
    bookkeeping entries that ECS creates for every client-only participant.
    Those register no endpoint, nothing can ``uses`` them, and they are not
    resolvable aliases — so returning them would make this method's contract
    false.
    """
    ...

def ecs_running_task_start_times(
    self, cluster: str, service: str,
) -> list[datetime]:
    """``startedAt`` for every RUNNING task of an ECS service.

    The caller takes the minimum: one task older than a registration is
    enough to make the service unable to resolve it.

    Two omissions are deliberate and are part of the contract:

    - **A task with no ``startedAt`` is omitted.** It has not yet read the
      namespace, so it will read it *after* every name the caller is
      comparing against already exists. A not-yet-started task cannot be
      stale.
    - **A service ECS reports as non-existent reads as ``[]``**, not an
      error. A service with no tasks cannot hold a stale one.
    """
    ...
```

`datetime` needs importing (`from datetime import datetime`) — check whether
`client.py` already imports it.

---

## Step 3 — `aws/boto3_client.py`: the adapter

Replace `service_connect_endpoint_names` (`:486-515`) and add the new method
beside it. Module-level constant:

```python
#: ECS creates one of these per client-only Service Connect participant. It is
#: bookkeeping, not an endpoint — see mod 114 and the advance-005 recon.
_SC_CLIENT_ENTRY_PREFIX = "aws-ecs-sc.client."
```

`service_connect_endpoints`: keep the existing namespace lookup verbatim
(including the `namespace_id is None` early return — now `return {}`), then:

```python
out: dict[str, datetime] = {}
svc_paginator = sd.get_paginator("list_services")
for page in svc_paginator.paginate(Filters=[...unchanged...]):
    for svc in page.get("Services", []):
        name = svc.get("Name")
        created = svc.get("CreateDate")
        if not name or created is None:
            continue
        if name.startswith(_SC_CLIENT_ENTRY_PREFIX):
            continue
        out[name] = created
return out
```

`ecs_running_task_start_times`:

```python
def ecs_running_task_start_times(
    self, cluster: str, service: str,
) -> list[datetime]:
    ecs = self._client("ecs")
    arns: list[str] = []
    paginator = ecs.get_paginator("list_tasks")
    try:
        for page in paginator.paginate(
            cluster=cluster, serviceName=service, desiredStatus="RUNNING",
        ):
            arns.extend(page.get("taskArns", []))
    except (
        ecs.exceptions.ServiceNotFoundException,
        ecs.exceptions.ClusterNotFoundException,
    ):
        return []
    out: list[datetime] = []
    # DescribeTasks accepts at most 100 ARNs per call.
    for i in range(0, len(arns), 100):
        resp = ecs.describe_tasks(cluster=cluster, tasks=arns[i:i + 100])
        for task in resp.get("tasks", []):
            if task.get("lastStatus") != "RUNNING":
                continue
            started = task.get("startedAt")
            if started is not None:
                out.append(started)
    return out
```

`ecs ListTasks` is a new AWS API call for `docex` — the only one in this mod.
`ListServices` already returned `CreateDate`; boto3 clients are lazily built and
cached by service name (`:67-78`), so nothing else is needed.

---

## Step 4 — `pipeline/release.py`: the predicate and the step

### 4a. Constants and helper

Beside `_RECONCILE_STABLE_TIMEOUT_S` (`:210-214`, unchanged):

```python
#: Grace added to the registration timestamp before comparing it against a
#: consumer task's start time. Ties are resolved toward redeploying by the
#: ``<=`` in the comparison itself, so this is ZERO — deliberately.
#:
#: WHY zero, and why it must stay zero: the Cloud Map name is created with the
#: ECS *service*, before any of its tasks exist. On a perfectly correct
#: first-ever release the service is created at T0 and its first task starts at
#: T0+30-90s (image pull, health checks). Any non-zero window therefore fires on
#: essentially every consumer on every first release — in exactly the case where
#: the ordering was fine and the task resolved the name on its first attempt.
#: That is a false positive with a predictable trigger, not a safety margin, and
#: it would silently convert this step's emergent no-op property into "always
#: redeploys on a first release". The only real uncertainty is clock skew
#: between two AWS services (ECS and Cloud Map), which is sub-second and is
#: covered by the ``<=``. Advance 005's recon measured an exact relationship,
#: not an approximate one: a task that starts after the name exists resolves it
#: on its FIRST probe cycle.
_RECONCILE_SKEW_MARGIN_S = 0


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes read as UTC.

    boto3 returns aware datetimes, so this never fires in production. It exists
    so that a naive value — from a test double, or a future SDK change — cannot
    raise ``TypeError`` in the middle of a release.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
```

Add `from datetime import datetime, timedelta, timezone` to the imports.

### 4b. `_consumer_reconcile_set` (replaces `:217-261`)

```python
def _consumer_reconcile_set(
    compiled: Any,
    *,
    endpoint_created: dict[str, datetime],
    task_started: Callable[[str], datetime | None],
) -> list[tuple[str, str]]:
    """Consumers that must be redeployed, as ``(consumer, triggering target)``.

    A consumer qualifies when one of its running tasks started **before** the
    Cloud Map ``CreateDate`` of a name it ``uses``. A Service Connect client
    fixes its resolvable endpoint set at task start, so such a task can never
    resolve that target — for the whole life of the task, no matter how long
    the application retries.

    Both operands are durable AWS state read after the apply, which is what
    makes this self-healing: it describes the world rather than this release.
    An interrupted release, a hand-run ``tofu apply``, or a service created out
    of band all leave a state the next release reads correctly. Mod 114
    replaced a pre-apply namespace snapshot, which could not (mod 109).

    ``task_started`` is called lazily — only for a consumer that has at least
    one registered target — so a converged env pays one ``ListServices`` and
    nothing else.
    """
    out: list[tuple[str, str]] = []
    margin = timedelta(seconds=_RECONCILE_SKEW_MARGIN_S)
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        if not svc.is_core or not svc.uses_core:
            continue
        # WHY: a `scheduler` core service emits no `ecs_service`, so there is
        # nothing to redeploy — and `update_service` against a service that
        # does not exist is an error, not a no-op.
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
        if not targets:
            continue

        started = task_started(svc.global_name)
        # No running tasks: nothing can be stale, and whatever starts later
        # reads a namespace that already holds every name above.
        if started is None:
            continue
        started = _as_utc(started)

        for global_name, created in targets:
            if started <= created + margin:
                out.append((svc.global_name, global_name))
                break
    return out
```

### 4c. `_reconcile_service_connect_consumers` (replaces `:264-341`)

Signature drops `endpoints_before`. Body:

```python
def _reconcile_service_connect_consumers(
    ctx: ProjectContext, *, env: str, aws: AWSClient, cluster_name: str,
) -> int:
```

- Docstring: keep the existing explanation of *why the step exists* (the
  start-order race, why ordering cannot fix it given a legal `uses` cycle) and
  replace the "cheap by construction" closing paragraph with: the step reads
  only post-apply state, so it is self-contained and self-healing, and on a
  converged env the comparison finds nothing — the no-op is emergent, not
  special-cased. Reference `cicl.md § Uses Relationships` rather than the stale
  `§ Depends-On Relationships` the current docstring names.
- Body order:
  1. `if ctx.infra is None: return 0` (keep the `# pragma: no cover`).
  2. `endpoint_created = aws.service_connect_endpoints(cluster_name)`; if empty,
     `return 0` — no registration means no comparison to make.
  3. `compile_env(...)` exactly as today.
  4. A memoized `task_started(service_name)` closure over
     `aws.ecs_running_task_start_times(cluster_name, service_name)` returning
     `min(times) if times else None`, caching in a local dict so a consumer is
     never probed twice.
  5. `pairs = _consumer_reconcile_set(compiled, endpoint_created=..., task_started=...)`;
     `if not pairs: return 0`.
- The redeploy loop, the hard-failure `stderr` message and `return 1`, the
  `ecs_wait_services_stable` call, `_RECONCILE_STABLE_TIMEOUT_S`, and the
  warning text are **unchanged in behaviour**. Only the two operator-facing
  strings change, from release-relative to durable phrasing:
  - the info line becomes, in substance: *reconciling Service Connect consumer
    `X` — its oldest running task predates the registration of its `uses` target
    `Y`, and a client cannot resolve an endpoint added after it started.*
  - the error line's middle clause becomes *its `uses` target `Y` was registered
    after `X`'s tasks started*, keeping the rest (the 503 fan-out consequence
    and the re-run advice) verbatim.

### 4d. `_release_elastic`

- **Delete `:452-454`** — the `endpoints_before` comment and assignment.
- Amend the `cluster_name` comment (`:444-448`): it is computed ahead of the
  `skip_migrations` return because the first-release detector and the reconcile
  both need it. Drop the "snapshot" wording.
- Amend the parenthetical at `:493-494` ("mod 109's namespace snapshot needs it
  too") the same way.
- Rollback call site (`:474-479`): drop `endpoints_before=`. Replace the
  preceding comment — a rollback is no longer assumed to be a no-op. New
  reasoning: the check describes the env rather than the release, so the
  rollback path simply runs it; a rollback that deregisters a name and leaves
  consumer tasks that predate a surviving one is repaired here rather than
  discovered by `stagetest`.
- Final call site (`:575-582`): drop `endpoints_before=`; keep the comment about
  running after the final apply on both branches.

---

## Step 5 — `emit/hcl.py`: `wait_for_steady_state`

In `render_ecs_service` (`:693-758`), immediately after the `desired_count`
line:

```python
    # WHY: the release's Service Connect consumer reconcile reads task start
    # times right after this apply. Without this, the apply returns while its
    # own rolling deploy is still draining pre-registration tasks, and the
    # reconcile redeploys consumers on the strength of tasks already on their
    # way out. Also means a service that cannot converge fails the apply rather
    # than letting the release exit 0 over a broken env. Mod 114.
    out.append("  wait_for_steady_state = true")
```

No `timeouts` block: the provider defaults (20 m) stand, consistent with the
deliberate reliance on defaults documented at `:710-714`.

---

## Step 6 — `tests/conftest.py`: `FakeAWSClient`

Replace the `service_connect_endpoints: list[set[str]]` field (`:542`) and its
`service_connect_endpoint_names` method (`:746-756`). **The old field name
collides with the new method name — the field must be renamed.**

Fields:

```python
    # Mod 114: the reconcile reads durable post-apply state, so there is no
    # "before" to script any more — one mapping of endpoint name -> Cloud Map
    # CreateDate, and per-service task start times. Defaults are the inert
    # case: no endpoints registered, no tasks, hence no reconcile.
    service_connect_endpoint_ages: dict[str, datetime] = field(default_factory=dict)
    ecs_task_start_times: dict[str, list[datetime]] = field(default_factory=dict)
```

Methods:

```python
    def service_connect_endpoints(self, namespace_name: str) -> dict[str, datetime]:
        self._record("service_connect_endpoints", namespace_name)
        return dict(self.service_connect_endpoint_ages)

    def ecs_running_task_start_times(
        self, cluster: str, service: str,
    ) -> list[datetime]:
        self._record(
            "ecs_running_task_start_times", cluster=cluster, service=service,
        )
        return list(self.ecs_task_start_times.get(service, []))
```

Note the fake does **not** filter the `aws-ecs-sc.client.` prefix — that is the
adapter's job, and the pipeline-level test (1b) must exercise the *pipeline*
against an unfiltered namespace.

Then fix `tests/unit/test_pipeline_rollback.py:596`, which scripts the old field:
replace with `service_connect_endpoint_ages = {"sample-prod-api-web": <dt>,
"sample-prod-appdb": <dt>}` and leave `ecs_task_start_times` empty. Preserve the
test's intent (its docstring says the script must be *non-empty* so the no-op is
not vacuous) — with no task times the reconcile finds no stale consumer, which
is still the realistic rollback state.

---

## Step 7 — `tests/unit/test_service_connect_reconcile.py`

Rewrite. Keep the module docstring's history (mod 109, the walk's `503`) and add
mod 114's reason: the trigger's operands are now durable, and the aborted-release
re-run is the case the old trigger got wrong.

Helpers: keep `_project`, `_redeployed`, `_waited`, `_run`, `_WORKER`,
`_SCHEDULER`, and the `web_uses_worker` fixture unchanged. Add a small
timestamp helper, e.g. `def _t(minute, second=0)` returning
`datetime(2026, 8, 5, 20, minute, second, tzinfo=timezone.utc)`.

Tests (the first two are step 1's, promoted here):

1. `test_aborted_release_rerun_redeploys_stale_consumer` — **the reason this mod
   exists.** As specified in step 1a. Assert `_redeployed(...) ==
   ["sample-prod-api-web"]`, and add a comment noting that the old snapshot diff
   was empty here.
2. `test_client_bookkeeping_entries_do_not_trigger_a_redeploy` — step 1b.
   Namespace holds `aws-ecs-sc.client.<uuid>.sample-prod-api-web` newer than the
   consumer's tasks; assert `_redeployed(...) == []`.
3. `test_converged_env_is_a_no_op` — every task postdates every endpoint;
   assert no redeploy **and** `_waited(...) == []`. Docstring must say the
   property is emergent, not arranged: nothing special-cases this release as
   cheap.
4. `test_new_target_redeploys_its_consumer` — the walk's original topology: the
   worker's endpoint `CreateDate` postdates `api-web`'s task.
5. `test_uses_cycle_redeploys_both_sides` — `web ↔ worker`, both tasks older
   than both endpoints; assert both are redeployed, no recursion, no error.
6. `test_clock_skew_tie_redeploys` — a consumer task whose `startedAt` is
   **exactly equal** to its target's `CreateDate` must be redeployed. Assert the
   equality case explicitly; this is what pins `<=` against a later "tidy-up" to
   `<`.

Keep, adapted to the new scripting:

- `test_consumer_of_preexisting_target_is_not_redeployed` — its targets predate
  its tasks; an unrelated *newer* endpoint exists. Still no redeploy.
- `test_scheduler_consumer_is_never_redeployed` — unchanged intent (mod 116
  deletes it along with the role).
- `test_slow_rollout_warns_but_does_not_fail_the_release` — unchanged intent.

Delete `test_no_reconcile_when_namespace_unchanged` — "unchanged" is not a
question the step can ask any more; test 3 replaces it.

---

## Step 8 — new `tests/unit/test_aws_service_connect_endpoints.py`

Adapter-level, in the `tests/unit/test_aws_ecr_image_exists.py` style
(`Boto3AWSClient()` + `monkeypatch.setattr(client, "_client", ...)` returning a
`MagicMock`; note the paginator is obtained via `get_paginator(...).paginate()`,
so the mock must supply that shape).

1. `service_connect_endpoints` drops `aws-ecs-sc.client.<uuid>.<svc>` entries and
   keeps real ones, mapping each kept name to its `CreateDate`.
2. An absent namespace returns `{}` (no `list_services` call at all).
3. `ecs_running_task_start_times` returns only `startedAt` of tasks whose
   `lastStatus == "RUNNING"`, omits a RUNNING-desired task that has no
   `startedAt` yet, and chunks `describe_tasks` at 100 ARNs (script 150 ARNs;
   assert two calls).
4. `ecs_running_task_start_times` returns `[]` when ECS raises
   `ServiceNotFoundException`.

---

## Step 9 — HCL emitter test

In `tests/unit/test_hcl_emitter.py`, assert that every emitted
`aws_ecs_service` block carries `wait_for_steady_state = true`. Cite mod 114 and
state the *reason* in the test's docstring — without it, the reconcile reads the
apply's own draining tasks — so a future reader cannot mistake it for cosmetic.

---

## Step 10 — Doctrine

Wording below is **approved verbatim by the operator**. Do not paraphrase, do
not extend, do not "improve" it. If a sentence appears not to fit the file, stop
and report rather than adapting it.

### 10a. `doctrine/infrastructure/specifics/release.md:75`

Replace "…performs three operations in sequence, followed by a conditional
fourth:" with:

> For elastic-foundation projects, `./bin/docex release <env>` performs three
> operations in sequence, followed by a fourth that always runs and is almost
> always a no-op:

### 10b. `release.md:80`

Replace item 4's second sentence, so the item reads:

> 4. **Reconcile Service Connect consumers** — see [§ Service Connect Consumer Reconcile](#service-connect-consumer-reconcile) below. A no-op on any env that is already converged, which is nearly every release.

### 10c. `release.md § Service Connect Consumer Reconcile`

The section's first two paragraphs (the Service Connect freeze, and the
concurrent-`aws_ecs_service` race) are unchanged **up to** "So after the final
apply, `release`:". From there, replace everything down to — but not including
— the "A failed redeploy fails the release" paragraph with:

> So after the final apply, `release` asks one question of current AWS state — **is any running consumer task older than the registration of a name it needs?** — and repairs whatever it finds:
>
> 1. Reads the Cloud Map `CreateDate` of every endpoint name in the env namespace, and the oldest `startedAt` across the running tasks of each core service that declares a core `uses` target.
> 2. Redeploys (`forceNewDeployment`) every core service whose oldest running task started before the `CreateDate` of a name it `uses`.
> 3. Waits, bounded, for those services to reach steady state — so a release that exits 0 means the env actually works, and the following [`stagetest`](../tests.md#staging-tests) is not racing a rollout.
>
> Both operands are durable AWS state read **after** the apply. Nothing is carried across the apply and nothing is remembered between releases: the step describes the world rather than the run. That is what makes it self-healing — an interrupted release, a hand-run `tofu apply`, a service created out of band, and a rollback all leave a state the next `release` reads correctly and repairs. A trigger keyed on *this release's* actions cannot do that: on the re-run of an aborted release every name already exists, and the broken env is set-identical to the healthy one. The only difference is the relative age of one task and one registration, and a set has no time dimension.
>
> Three properties are worth stating:
>
> - **It is a no-op on a converged env, and that is emergent rather than arranged.** Where every consumer task postdates every name it `uses`, the comparison finds nothing and no service is touched. Nothing special-cases an ordinary image-tag release as cheap; it is cheap because it is already correct.
> - **The comparison is per-consumer, not per-namespace.** A consumer whose own targets all predate its tasks is left alone even when some unrelated endpoint is newer than it.
> - **It handles cycles, which ordering cannot.** The `uses` graph may legally contain cycles, and in a cycle some member must be created first — so no creation order exists. Acting *after* everything is registered is the only mechanism that works for `web ↔ worker`.
>
> Three implementation details matter:
>
> - **The read must not see the apply's own draining tasks.** `aws_ecs_service` is emitted with `wait_for_steady_state = true`, so the apply does not return until its rollouts have settled. Without it the step would read tasks that are already on their way out and redeploy for nothing.
> - **Ties break toward redeploying.** Both timestamps are AWS-server-issued, but they come from two different services and small skew is possible, so the comparison carries a small margin that favours acting. A false positive costs one rolling deploy; a false negative costs a permanently broken env that exits 0. Never round toward silence.
> - **Client bookkeeping entries are not endpoints.** A namespace holds one `aws-ecs-sc.client.<uuid>.<service>` entry per client-only participant. They register nothing, nothing can `uses` them, and they are filtered out before the comparison.

### 10d. `release.md:114`

In "**Fixed foundations need none of this.**", replace the trailing phrase "with
no per-task snapshot" with "with no launch-time name freeze". Nothing else in
that paragraph changes.

### 10e. `doctrine/infrastructure/cicl.md:396`

Replace list item 5 with:

> 5. On elastic, it names the endpoints each consumer must be able to resolve, so a release can find and redeploy any consumer whose tasks predate one — see [§ Resilience covers reachability, not resolvability](#resilience-covers-reachability-not-resolvability).

### 10f. `cicl.md:420`

Replace the paragraph beginning "**`docex` closes this at release time**" with:

> **`docex` closes this at release time**, by redeploying, after the apply, any consumer with a running task older than the registration of a name it `uses`. Note carefully that this is *not* the deploy-time ordering emulation rejected above, and the distinction is what makes it sound: an endpoint **registration is durable state**, owned by the service rather than by task liveness, and it survives every task replacement. Holding once is therefore permanently sufficient — after the first registration, every later task (scaling, AZ rebalance, failed health check, platform update) starts into a namespace that already contains the name. A readiness gate decays because liveness changes; a registration does not. Because *both* halves of the comparison are durable — task age as much as registration age — the check describes the env rather than the release that produced it, and any broken env it can read it can also repair. See [release.md § Service Connect Consumer Reconcile](./specifics/release.md#service-connect-consumer-reconcile).

---

## Step 11 — Gates

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
python -m pytest tests/unit -q
python -m pytest -m integration -q
```

Unit baseline was 996; this mod nets several tests added and one deleted, so
expect a modest increase. Integration must be 18/18 — it does not exercise this
path, so any integration failure is unrelated to this mod and must be reported
rather than worked around.

Other suites touch `render_ecs_service` output (`test_hcl_emitter.py`,
`test_replicas.py`, `test_worker_role.py`, `test_service_expansion_emit.py`,
`test_emit_dispatch.py`, `test_opentofu_destroy.py`, `test_scheduler.py`). If a
line-count or exact-block assertion trips on the added line, update that
assertion — do not move the emission to satisfy a test.

Grep gates, all of which must come back empty in `src/` and `tests/`:

```
grep -rn "endpoints_before\|service_connect_endpoint_names" src/ tests/
```

---

## Out of scope — do not do these

- The § Bonus standing invariant (the same comparison as a `check` / `describe`
  assertion). `run_check` takes no `AWSClient`; it needs a new injected
  dependency and a dispatcher change. A later advance owns it.
- Anything scheduler/clock. The `emits ecs_service` guard and the scheduler test
  stay exactly as they are; mods 115–116 delete them.
- Core planning docs (`docex/plans/core/*`), `PRE_CUT_CHECKLIST.md`,
  `doctrine_excerpts/`, the upgrade guide, the changelog, and both smoke
  projects. The driving agent handles core docs; mods 117–118 handle the rest.
- Committing. The driving agent commits, path-scoped.

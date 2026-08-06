# Mod 123 — Service Connect Consumer Reconcile: Deployment Age, Not Task Age

Replace the trigger operand of the elastic release's
[Service Connect Consumer Reconcile](../../../../doctrine/infrastructure/specifics/release.md#service-connect-consumer-reconcile)
for the second time. Mod 114 replaced a pre-apply namespace snapshot with a pair
of durable timestamps; one of those two timestamps measures the wrong event. The
1.7.0 elastic smoke walk proved the step inert on `prod`.

> **Scope.** One docex code path, one AWS-client method added and one deleted,
> the unit suite for the step, four doctrine files, two docex core docs, the
> advance's design record, and three pre-cut-checklist repairs. No
> `cicl_version` implication, no `infra.yml` change, **no emitted-output
> change** — `wait_for_steady_state = true` (mod 114) stays and becomes load
> bearing for a second reason.

---

## 1. What the walk found

On `prod`'s first release, `api-web` could not resolve `api.worker`. The health
fan-out returned 503 for 20+ minutes. **Two subsequent clean `release prod` runs
printed nothing and repaired nothing.** A manual `ecs update-service
--force-new-deployment` fixed it on the first replacement task.

The remedy is right. The trigger is wrong.

## 2. The defect, stated narrowly

Mod 114's predicate is:

```
redeploy C  iff  min(startedAt over C's RUNNING tasks)  <=  T.CloudMap.CreateDate + MARGIN
```

with `MARGIN = 0`.

`CreateDate` is stamped when the **ECS service** is created — before any of its
tasks exist (recon 1, Q2, measured: Cloud Map `CreateDate` 20:47:01 vs. the ECS
service's own `createdAt` 20:47:02). A task of that service necessarily starts
*after* its service was created, and typically 30–90 s after (image pull,
health-check start period).

So whenever a consumer's tasks are (re)started by the **same apply** that creates
the target's name, `startedAt` is unavoidably later than `CreateDate` and the
comparison cannot fire. That is:

- **every first-ever release** (all services created concurrently) — the walk's
  case; and
- **every release in which the consumer's own task definition also changes** (an
  image-tag bump, i.e. essentially every release), which is also the aborted-re-run
  case the whole of mod 114 was built to close.

**The predicate is not dead in general, and the record must not say it is.** It
fires correctly in one real shape: a new target added to a long-lived env with
the consumer entirely untouched by the apply, so its tasks are weeks old. What is
unsatisfiable is **concurrent creation**. That happens to be the walk's case and
the abort case, so the fix is unchanged — but "the check can never fire" is an
overclaim, and overclaims are how the next person mis-scopes a decision.

**The error is a recorded inversion, not an oversight.** The advance's design
record, § "Corrected by measurement", reads the `CreateDate`-before-any-task fact
as *strengthening* `startedAt <= CreateDate` ("`CreateDate` now sits *earlier*
relative to any task, so the comparison is strictly more conservative"). It
inverts it: pushing `CreateDate` earlier makes `startedAt <= CreateDate`
**harder** to satisfy, not easier. That sentence then propagated into
`release.md`'s tie-break bullet, into the `_RECONCILE_SKEW_MARGIN_S` WHY block,
and into `release_flow.md` — three places that now argue *for* the defect.

## 3. An impossible fixture proves nothing

This is the most important finding of the mod, and it is not about Service
Connect.

`tests/unit/test_service_connect_reconcile.py` passes today, with the broken
predicate, because **its fixtures describe a world that cannot exist**. In
`test_aborted_release_rerun_redeploys_stale_consumer`:

```
service_connect_endpoint_ages = {"sample-prod-api-web": 20:46, "sample-prod-api-worker": 20:46}
ecs_task_start_times         = {"sample-prod-api-web": [20:40]}
```

`api-web`'s own Cloud Map name is created at 20:46, which means `api-web`'s ECS
service was created at ~20:46 — yet the fixture has one of its own tasks starting
at 20:40, six minutes *before its own service existed*. AWS cannot produce that
state. Every "fires" assertion in the file rests on the same shape.

So the suite exercised the **code path** and never once tested the **predicate**.
That is how 1006 green tests shipped a check that cannot fire in the case it was
built for.

**This is advance 005's recurring defect wearing new clothes.** The same shape has
now been found five times:

| Instance | What reported success |
| -------- | --------------------- |
| Swallowed HTTP 401 | a request that never succeeded |
| `mark_fail` lost in a subshell | a failure that never propagated |
| Pathspec matching nothing | a command that acted on no files |
| Teardown gate that could not authenticate | a "clean" it could not have observed |
| **This fixture** | a suite that could not have detected the failure |

Every instance is one sentence: **something that could not have detected the
failure reported success.**

The fix here is specific and must be stated so the next person adding a case does
not copy the old fixtures: **every timestamp in this file must belong to one
internally-consistent timeline.** A consumer's own endpoint `CreateDate` and its
own deployment `createdAt` are two views of the same ECS service creation and
cannot contradict each other; a target's `CreateDate` and a consumer's deployment
age must sit in an order AWS could actually produce. A green suite built on an
impossible world is evidence of nothing at all.

The walk regression (§ 7) goes in as the companion: real numbers, from the
failure we shipped, as data.

## 4. The mechanism (recon 2)

**The resolvable name set is frozen at ECS *deployment* creation, not at task
start.**

Every Service Connect Envoy sidecar identifies itself to the ECS control plane's
xDS endpoint by its **task-set ARN** (`…/task-set/…/ecs-svc/0983…`) — which is
the deployment id — and is served a cluster list fixed for that deployment. Tasks
launched later into the same deployment inherit that list; they do not re-read the
namespace.

Measured:

| Observation | Result |
| ----------- | ------ |
| Task stopped and replaced **within the same PRIMARY deployment** (same id, same `createdAt`); probed 47× over 8 min for a name created 5 m 34 s earlier | **Never resolved.** Envoy logged `0 added/updated cluster(s)` |
| Provider created **2.4 s after** a deployment; consumer task started 143 s later | **Invisible** to that task |
| Provider created **11.6 s before** a deployment, `desiredCount: 0`, no instance ever | **Visible** (503 — an Envoy listener with no upstreams) |
| `deployments[].updatedAt` advanced past the name's creation | Changed nothing |

Three consequences:

1. Task `createdAt` / `startedAt` are excluded by two orders of magnitude.
   **Not usable as an operand.**
2. `deployments[].updatedAt` is not the freeze instant. **Not usable.**
3. Instance registration does not govern — a name with zero instances still
   resolves. The reachability/resolvability split in `cicl.md` is unaffected and
   stays.

The freeze instant is bracketed to `(createdAt − 11.6 s, createdAt + 2.4 s]`. The
mechanism says it *is* `createdAt`; the bracket is measurement granularity.

**This also falsifies a doctrine claim unrelated to the trigger.** `cicl.md`
currently argues that holding the ordering once is permanently sufficient because
"every later task (scaling, AZ rebalance, failed health check, platform update)
starts into a namespace that already contains the name." The **conclusion**
survives, but only via deployments: a later task inherits its deployment's set,
and every deployment created after the name contains it. The stated **mechanism**
is false, and it is precisely the false model that produced this bug twice. It
must be corrected, or the next reader rebuilds it a third time.

## 5. The fix

> **Redeploy consumer `C` iff, for any target `T` in `C`'s core-service `uses`
> set:**
> `C.primary_deployment.createdAt <= T.cloudmap.CreateDate + MARGIN`

| Operand | Source |
| ------- | ------ |
| Consumer deployment age | `ecs:DescribeServices` → `services[].deployments[?status=='PRIMARY'].createdAt`. Batched — `DescribeServices` accepts up to 10 services per call |
| Name registration age | `servicediscovery:ListServices` on the env namespace, `CreateDate` per name, `aws-ecs-sc.client.` prefix filtered — **unchanged from today** |

`MARGIN = _RECONCILE_SKEW_MARGIN_S = 60`, and the comparison is `<=` so ties
fire.

**Self-clearing, structurally.** A `forceNewDeployment` mints a new PRIMARY
deployment with a fresh `createdAt`, so a re-run of the same release skips. The
step's idempotency is a property of the operands, not an assertion about the code.

### 5.1 Why the margin is 60 — and what it is not

Sixty seconds is **not** a skew allowance, and the doctrine must not say it is.
The two sources of genuine uncertainty are small: the empirical bracket is ~14 s
wide, and Cloud Map's `CreateDate` precedes the name's appearance in the control
plane's served cluster list by ~0.85 s. Five seconds would cover both.

What 60 s does is **collapse the concurrent-creation window into an
unconditional redeploy**. Within roughly a minute of a consumer's deployment we
stop trying to adjudicate visibility and simply redeploy. Two reasons, and they
are the only two:

1. **That window is precisely where the boundary is unmeasurable.** Recon 2
   bracketed the freeze instant but did not pin it; ECS's internal ordering is
   not exposed; reading the outcome off two timestamps seconds apart is guessing.
   The 11.6 s-before case was measured as **visible** — i.e. fine — and fires
   anyway under a 60 s margin. That is a deliberate false positive, recorded as
   such.
2. **The two errors are not symmetric.** A false negative inside that window is
   **permanent and silent** — a broken env that exits 0, with both sides
   reporting healthy. A false positive is one rolling deploy.

The cost is bounded and lands only where the race is real: one rolling deploy per
consumer on a first release or a shape change. It is free on an ordinary code-only
release, where the gap is days or weeks and the comparison is not close by orders
of magnitude. It also makes first-release behaviour identical to the
unconditional-redeploy fallback, without paying that fallback's cost on every
subsequent release — so if this predicate is going to misfire, it misfires in the
direction the fallback would have gone anyway.

**Why this paragraph exists at all.** Mod 114 shipped an inert check because a
plausible-but-false load-bearing sentence — one that read as careful reasoning
from real measurement — went into the doctrine and then into the code comment
that defends the constant. Writing "it covers skew" here would be the same
mistake in the same place. The reasoning is preserved in the mod docs, not just
the number, for that reason.

### 5.2 Behaviour across release shapes

| Shape | `deployment.createdAt` vs. `CreateDate` | Verdict | Correct? |
| ----- | --------------------------------------- | ------- | -------- |
| First-ever release (all concurrent) | within seconds | **fire** | yes — the race is real |
| Code-only release, converged env | days/weeks later | skip | yes — the free case |
| New target added, consumer untouched | deployment weeks older | **fire** | yes |
| New target added, consumer image also bumped | concurrent | **fire** | yes |
| Aborted release, re-run (apply is a no-op) | consumer deployment still at release N ≈ name | **fire** | yes — the abort hole, genuinely closed |
| Walk regression: deployment 14:06:40, `CreateDate` 14:07:02.391 | −22 s | **fire** | yes — this is the shipped failure |
| Consumer service at `desired_count: 0` | PRIMARY exists, may be old | judged on the same terms | see § 5.3 |
| No PRIMARY deployment reported | — | **fire** | safe direction |

### 5.3 One behavioural change to note

Mod 114 skipped any consumer with **no running tasks** (`started is None →
continue`). Deployment age has no such notion: a service at `desired_count: 0`
still has a PRIMARY deployment, so it is now judged on the same terms and may be
redeployed. `forceNewDeployment` against a zero-count service is accepted and
settles immediately, so the cost is nil.

`test_consumer_with_no_running_tasks_is_not_redeployed` is therefore **removed,
not adapted**: running tasks are no longer an operand, so the test's premise is
gone rather than changed.

## 6. Code changes

All under `docex/src/docex/`.

**`aws/client.py`** — protocol.
- Delete `ecs_running_task_start_times` and its docstring.
- Add `ecs_primary_deployment_times(cluster: str, services: list[str]) -> dict[str, datetime]`, returning `service → PRIMARY deployment createdAt`. Contract: a service with no PRIMARY deployment, or one ECS reports as missing, is **absent from the mapping** — the caller reads absence as "fire", the safe direction. Batching is the implementation's business, not the caller's.
- `service_connect_endpoints` unchanged, including the `aws-ecs-sc.client.` filter requirement.

**`aws/boto3_client.py`** — adapter.
- Delete the `ListTasks`/`DescribeTasks` implementation.
- Implement `ecs_primary_deployment_times` over `ecs.describe_services`, chunked at **10** services per call (the API's hard limit), skipping `failures[]` entries and any service whose `deployments[]` holds no `status == "PRIMARY"` entry.
- No new IAM: `ecs:DescribeServices` is already exercised by the `services_stable` waiter this same step calls.

**`pipeline/release.py`** — the step.
- `_RECONCILE_SKEW_MARGIN_S = 60`, WHY rewritten per § 5.1.
- Split the predicate so the batch read is possible and laziness is preserved:
  - `_reconcile_candidates(compiled, endpoint_created)` — the pure, AWS-free half. Iterates core services with `uses_core`, keeps the `ecs_service`-emission guards on both consumer and target (**including the `DO NOT DELETE THIS AS DEAD` project-local-transfer-table branch, comment intact**), resolves each target's `CreateDate`, drops consumers with no registered targets.
  - `_consumer_reconcile_set(candidates, deployment_created)` — the comparison. Keeps `(consumer, triggering target)` output and the `break` on first triggering target so a consumer appears once.
- `_reconcile_service_connect_consumers` calls `service_connect_endpoints` → `_reconcile_candidates` → **one** batched `ecs_primary_deployment_times` over just the candidate consumers → `_consumer_reconcile_set`. A converged env pays one `ListServices` plus one `DescribeServices` and nothing else.
- Redeploy loop, error handling, `_RECONCILE_STABLE_TIMEOUT_S`, the bounded wait, and both call sites (rollback branch, post-final-apply call) are **unchanged**.
- Operator-facing message changes from "its oldest running task predates…" to "its current deployment predates…".

**`tests/conftest.py`** — `FakeAWSClient`.
- Replace `ecs_task_start_times` with `ecs_deployment_times: dict[str, datetime]`; replace the `ecs_running_task_start_times` recorder with `ecs_primary_deployment_times`, returning only requested services present in the dict — so "absent → fire" is exercisable.

## 7. Tests

`tests/unit/test_service_connect_reconcile.py` is rewritten around deployment
age, under the § 3 rule: **one internally-consistent timeline per fixture**, with
a module docstring saying so.

| Case | Expectation |
| ---- | ----------- |
| Converged env — deployment days after every name | skip; no `ecs_wait_services_stable` call either |
| New target registered concurrently with the consumer's deployment | fire |
| **Aborted release, re-run** — apply is a no-op, consumer deployment still ≈ the name | fire |
| Deployment newer than every name by weeks | skip — the free case, asserted as such |
| Exact tie at `CreateDate + MARGIN` | fire |
| Deployment at `CreateDate + MARGIN + 1 s` | skip — pins the boundary from the other side |
| Client bookkeeping entry (`aws-ecs-sc.client.…`) newer than the deployment | ignored; no redeploy |
| `uses` cycle (`web ↔ worker`), both concurrent | both fire, in one pass |
| Consumer absent from the deployment mapping (no PRIMARY) | fire |
| Slow rollout (`ecs_services_stable = False`) | warns, `rc == 0` — unchanged |
| Clock core service as a consumer | same terms as any other consumer — unchanged intent |
| **Walk regression, real numbers**: consumer deployment `14:06:40`, target `CreateDate` `14:07:02.391` | **fire**, docstring naming it as the shipped failure |

`tests/unit/test_aws_service_connect_endpoints.py` is untouched — the namespace
read does not change. Any adapter-level test of `ecs_running_task_start_times`
goes with the method.

## 8. Doctrine — wording

**Four** doctrine files, not two. The two beyond the trigger are consequences of
the mechanism correction; both currently teach the task-start model that caused
this, and both are ratified as mandatory.

1. **`cicl.md § Resilience covers reachability, not resolvability`** — the
   mechanism paragraph (task start → deployment creation, task-set ARN, inherited
   cluster list) and the `docex` closes this paragraph (trigger clause, plus the
   durability argument: keep the conclusion, replace "every later task starts into
   a namespace that already contains the name" with the deployment-inheritance
   mechanism).
2. **`release.md § Service Connect Consumer Reconcile`** — the opening sentence,
   the question and steps 1–3, the first "property" bullet's supporting clause,
   the `wait_for_steady_state` detail (gains a second reason), the closing
   "launch-time name freeze" phrase, and **the reversal of the tie-break bullet**,
   which today reads as a trap-marker forbidding exactly this change.
3. **`reasoning/elastic_release_pattern.md:18`** — the task-launch model stated
   outright; the file a reader would rebuild it from.
4. **`plans/advances/005_.../service_connect_reconcile_trigger.md`** — § "Corrected
   by measurement" (the inversion), § "The invariant", the operand table,
   implementation detail 2, vocabulary precision 2 (**struck as false**), and a
   new § Recon 2 carrying § 4's mechanism and timestamp table. § Verified's Q1/Q2
   stay — they are correct as measurements.

Verbatim replacement text for all four lives in `implementation.md` Step 8.

Two docex core docs carry the same false claim and are updated in the mod cycle's
**documentation** step, not by the implementor: `plans/core/release_flow.md:64`
and `:138`, and `plans/core/compiler.md:203-204`.

## 9. Pre-cut checklist — three changes

`docex/test_projects/PRE_CUT_CHECKLIST.md`.

**9.1 D.9 and D.11 — record both operands.** A new box in each records the
consumer's PRIMARY `createdAt` and the target's Cloud Map `CreateDate`, with the
verdict stated up front: **fire** on the first `prod` release, **skip** on the
code-only 0.0.21 release. `release` prints one `release: reconciling Service
Connect consumer …` line per consumer it fires on; its presence or absence is the
verdict and must agree with the recorded timestamps. The 1.7.0 walk measured the
wrong timestamp and `force-new-deployment` overwrote the evidence before anyone
knew which one mattered — recording both is what lets a future walk *confirm* the
predicate rather than infer it from a green fan-out.

**9.2 A.2.1 ⊕ C.6/D.8 — mutually exclusive repo states.** A.2.1 demands each inner
repo be on `main`, clean, `v<version>` at HEAD. C.6/D.8's feature-branch
prerequisite demands `main` at the **prior** release with the new version on a
feature branch checked out now. Both cannot hold. A.2.1 gains an ordering
carve-out; C.6 and D.8 each gain a one-line back-reference.

**9.3 B.16 — prose imprecision.** The item claims the `-exec` block carries
`condition: service_healthy` for the codebase's backing-targeted `uses` edges. The
emit (`emit/compose.py:600-610`) gives `service_healthy` only where the target
block declares a `healthcheck:`, `service_started` otherwise — the fixed project's
committed output shows `appdb → service_healthy`, `probe → service_started`,
`events → service_started`. Reworded to state both.

## 10. Verification

- `pytest tests/unit` and `pytest -m integration` green. Expected delta: the
  reconcile unit file is rewritten (case count changes) and one test is **removed**
  rather than adapted (§ 5.3). Any other movement gets explained.
- `grep -rn "startedAt\|ListTasks\|list_tasks\|ecs_running_task_start_times" docex/src docex/tests`
  returns nothing in the reconcile path.
- Rebuild `docex:1.7.0` so the follow-on re-walk runs the fixed code; confirm both
  test projects report `docex 1.7.0`.

## 11. Non-goals

- No change to `service_connect_endpoints`, the `aws-ecs-sc.client.` filter, the
  redeploy loop, `_RECONCILE_STABLE_TIMEOUT_S`, the bounded wait, either call site,
  or any emitted HCL.
- The "standing invariant / `check`-time diagnosis" idea from the design record
  stays unbuilt.
- The unconditional-redeploy fallback is **not** implemented. It remains the escape
  hatch if D.9–D.11 shows this predicate misfiring in either direction; § 5.1 notes
  that a 60 s margin already makes first-release behaviour identical to it.

---

## Design questions — resolved

All four ratified by the C.O. before implementation.

1. **The margin's justification.** Ratified: keep 60 s; state that it collapses the
   concurrent-creation window into an unconditional redeploy, because that window
   is where the boundary is unmeasurable and because the two errors are
   asymmetric — permanent-and-silent versus one rolling deploy. **Do not write "it
   covers skew."** The reasoning, not just the number, is preserved (§ 5.1).
2. **Failure envelope stated narrowly.** Ratified: mod 114's predicate does fire
   when a target is added to a long-lived env with the consumer untouched; only
   concurrent creation is unsatisfiable. The design record and the C.O.'s own brief
   framing are both corrected (§ 2).
3. **Two extra doctrine files.** Approved and mandatory. `cicl.md`'s durability
   paragraph is text approved in mod 114 and refuted by recon 2's 47-probe
   replacement task; keep the conclusion, fix the mechanism, make the vocabulary
   deployment-based in both files (§ 8).
4. **The impossible-fixture finding.** Promoted to its own section (§ 3) and framed
   as advance 005's recurring defect: *something that could not have detected the
   failure reported success.* The internally-consistent-timeline rule is stated in
   the test module itself so the next author does not copy the old fixtures.

Also confirmed without a question: removing
`test_consumer_with_no_running_tasks_is_not_redeployed` outright is correct, and
`desired_count: 0` consumers becoming redeployable is acceptable.

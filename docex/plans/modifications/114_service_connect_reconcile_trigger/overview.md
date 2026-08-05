# Mod 114 — Service Connect reconcile on durable operands

Advance 005, Goal 1. Replaces the *trigger* of the elastic release's
[Service Connect Consumer Reconcile](../../../../doctrine/infrastructure/specifics/release.md#service-connect-consumer-reconcile).
The step stays; one of its two comparison operands is ephemeral and becomes
durable. Design record:
[`service_connect_reconcile_trigger.md`](../../advances/005_process_type_solidification/service_connect_reconcile_trigger.md).

## The defect

`_release_elastic` snapshots the namespace's endpoint names *before any apply*
(`release.py:452-454`) and diffs the post-apply namespace against it
(`release.py:287-290`). The snapshot lives in one process's memory, so an
**interrupted release leaves a permanently broken env and exits 0**: the re-run's
snapshot already contains the new name, the diff is empty, and the consumer's
tasks — which started before that name existed and can therefore never resolve
it — are never replaced. On `stage`, `stagetest`'s 503 catches it. On `prod`
nothing does: the ALB probes only self-`/health`, and the symptom is application
calls failing across the edge with both sides reporting healthy.

The premise underneath the whole step was measured on a scratch Fargate stack on
2026-08-05 and holds (design record § Verified): a client task ran 27 probe
cycles over five minutes after the name existed with byte-identical `UNRESOLVED`
output; its replacement resolved the name on the first cycle.

## The fix

Replace the question. Instead of *"did this endpoint register during this
release?"* ask:

> **Is any running consumer task older than the registration of a name it
> needs?**

Both operands are durable AWS state read **after** the apply:

| Operand | Source |
| ------- | ------ |
| Consumer task age | `ecs ListTasks` + `DescribeTasks` on the consumer's ECS service; **minimum** `startedAt` across running tasks — one stale task is enough |
| Name registration age | `servicediscovery ListServices` on the env namespace; `CreateDate` per discovery name |

Redeploy core service `P` iff `min(startedAt)` across `P`'s running tasks
precedes the `CreateDate` of any name `P` `uses`. Then the same bounded
steady-state wait as today.

The recon corrected the record on one point in a way that *strengthens* this:
the Cloud Map name is created when the **ECS service** is created, before any
task exists — so `CreateDate` sits earlier relative to any task than the record
originally assumed, and `startedAt < CreateDate` is strictly more conservative.

### What this deletes

- `endpoints_before` (`release.py:452-454`) and every cross-step value in
  `_release_elastic`. The step becomes self-contained: **read state, act,
  verify**. Both call sites (`:474-479` rollback path, `:575-582`) lose their
  `endpoints_before=` argument.
- The "before *any* apply" delicacy and its interaction with the first-release
  migrate/apply swap.
- The abort hole. Every failure mode self-heals on the next `release` —
  interrupted run, hand-run `tofu apply`, out-of-band service, rollback —
  because the check describes the world rather than the run. The rollback path
  therefore simply runs the check, with no special reasoning about shape.
- The "no-op unless the shape changed" special case. It becomes **emergent**: in
  a converged env every consumer task postdates every registration, so nothing
  fires.
- The wasted rollouts, since the test is now per-consumer rather than
  per-endpoint.

## Design

### 1. Port surface (`aws/client.py`, `aws/boto3_client.py`)

`service_connect_endpoint_names(namespace) -> set[str]` is **replaced** (not
kept alongside) by a richer read; nothing outside the reconcile calls it.

```python
def service_connect_endpoints(self, namespace_name: str) -> dict[str, datetime]:
    """Endpoint name → Cloud Map ``CreateDate`` for the env's namespace."""

def ecs_running_task_start_times(self, cluster: str, service: str) -> list[datetime]:
    """``startedAt`` for every RUNNING task of an ECS service."""
```

- `service_connect_endpoints` keeps the existing namespace lookup and the
  absent-namespace → empty answer, and **filters the `aws-ecs-sc.client.`
  prefix** (see § Client bookkeeping below).
- `ecs_running_task_start_times` pages `ListTasks(desiredStatus="RUNNING")`,
  chunks `DescribeTasks` at 100 ARNs, and returns `startedAt` for tasks whose
  `lastStatus == "RUNNING"`. Two deliberate omissions, documented on the port:
  - **A task with no `startedAt` is skipped.** It has not yet read the
    namespace, so it will read it *after* every name in this comparison already
    exists. This is not rounding toward silence — a not-yet-started task cannot
    be stale.
  - **A service ECS reports as non-existent reads as no tasks** (`[]`) rather
    than raising. A service with no tasks cannot hold a stale one.
- `ListTasks` is the one genuinely new AWS call. `ListServices` already returns
  `CreateDate`, and boto3 clients are lazily built and cached by service name
  (`boto3_client.py:67-78`), so there is no new plumbing and no IAM surface
  change beyond `ecs:ListTasks`.

### 2. The predicate (`release.py`)

`_consumer_reconcile_set` keeps its name and its `(consumer, triggering target)`
return shape, and changes its operands:

```python
def _consumer_reconcile_set(
    compiled, *, endpoint_created: dict[str, datetime],
    task_started: Callable[[str], datetime | None],
) -> list[tuple[str, str]]
```

- Iteration is unchanged: core services only, skip anything that emits no
  `ecs_service` (a `scheduler` has nothing to redeploy, and `update_service`
  against a non-existent service is an error), skip targets that emit no
  `ecs_service` and therefore register nothing.
- `task_started` is a **lazy** per-consumer lookup, called only for a consumer
  that has at least one core `uses` target present in `endpoint_created`. Cost
  stays at one `ListServices` plus `ListTasks`+`DescribeTasks` per *candidate*
  consumer, and a converged env pays the same as today's no-op.
- `task_started(consumer) is None` (no running tasks) → not stale, skip.
- Comparison, with the tie-break:

```python
_RECONCILE_SKEW_MARGIN_S = 0

stale = min_started <= created + timedelta(seconds=_RECONCILE_SKEW_MARGIN_S)
```

  **The margin is zero and `<=` carries the tie-break** (operator decision — see
  § Design questions 1). Equal timestamps redeploy. A *non-zero* window would be
  a false positive with a predictable trigger rather than a safety margin,
  because the name is created with the **ECS service**, before any task exists:
  on a correct first-ever release the service is created at T0 and its task
  starts at T0 + 30–90 s (image pull, health checks), so any window wider than
  that fires on essentially every consumer on every first release — in exactly
  the case where the ordering was fine. The only genuine uncertainty is
  ECS↔Cloud Map clock skew, which is sub-second, and `<=` covers it. The recon
  measured an exact relationship, not an approximate one: a task that starts
  after the name exists resolves it on its *first* probe cycle. The constant
  stays in code carrying a WHY comment that records **why it is zero**, so it is
  not later "fixed" to 60 for the reason this design originally proposed it.
- All comparisons go through a small `_as_utc()` normalizer so a naive datetime
  (from a fake, or a future SDK change) cannot raise mid-release.

`_reconcile_service_connect_consumers` loses its `endpoints_before` parameter,
reads both operands itself, and keeps the redeploy loop, the hard-failure
message, `_RECONCILE_STABLE_TIMEOUT_S`, and the bounded steady-state wait
**unchanged**. Its console message changes from "registered during this release"
to the durable statement: the consumer's oldest task predates the target's
registration.

### 3. `wait_for_steady_state = true` (`hcl.py:693-758`)

Emitted on every `aws_ecs_service` so the reconcile does not read tasks the
apply's own rollout is already draining and redeploy for nothing.

Consequence worth stating plainly, because it is a real behaviour change beyond
this step: `tofu apply` now blocks until each service stabilizes, so a service
that fails to converge fails the *apply* rather than leaving the release to
discover it later. That is the correct direction — an env that has not converged
is not released — and it costs apply wall-clock on every elastic release.
Timeouts are left at the provider defaults (20 m create / 20 m update); no
`timeouts` block is emitted, matching the existing deliberate reliance on ECS
and provider defaults documented at `hcl.py:710-714`.

### 4. Client bookkeeping entries

`ListServices` returns one `aws-ecs-sc.client.<uuid>.<ecs-service-name>` entry
per client-only participant, even one with an empty `services[]` (observed in
the recon). These are not endpoints and nothing can `uses` them. They are
filtered by prefix in the adapter, so the port's promise — "the names a client
task can resolve" — is true rather than approximately true.

**Honest note on how much the filter carries.** Because the new comparison is
*keyed* on `target.global_name`, a bookkeeping entry can never match a lookup;
the filter is defence in depth rather than the load-bearing fix it would be
under an "is any name newer than this consumer" formulation. It still earns its
place: it keeps the port honest, and the § Bonus standing invariant (out of
scope, below) would read all names. Both the filter and the keyed comparison get
a test, so a future rewrite toward the all-names shape cannot silently reintroduce
the defect.

## Tests

Written against `FakeAWSClient`, whose `service_connect_endpoints` becomes a
`dict[str, datetime]` (one value, not a before/after queue — there is no
"before" any more) plus a per-service `startedAt` script. `test_pipeline_rollback.py:596`
updates to the new fixture shape.

Order matters: **1 and 2 are written first and watched to fail** against the
current predicate.

1. **The aborted-release re-run.** Release N registers a new target and aborts
   before phase 2; the re-run finds the name already present, the consumer's
   tasks older than it, and **must redeploy**. This is the case today's code
   gets wrong and the entire reason the mod exists. Under today's diff the
   before/after sets are identical and nothing fires.
2. **Client bookkeeping filter.** Two tests: (a) at the pipeline level, a
   namespace containing an `aws-ecs-sc.client.*` entry newer than a consumer's
   tasks produces **no** redeploy; (b) at the adapter level, against a
   `MagicMock` boto3 client in the `test_aws_ecr_image_exists.py` style,
   `service_connect_endpoints` drops the prefixed entries and keeps the real
   ones.
3. **Converged env → no redeploy.** The no-op property, now emergent: every task
   postdates every name.
4. **New target → redeploy.** The original walk topology (`api.web` uses
   `api.worker`), web's task older than the worker's registration.
5. **Legal `uses` cycle (`web ↔ worker`)** → both sides handled, no recursion,
   no error.
6. **Clock-skew tie** → a task whose `startedAt` equals (and one that slightly
   postdates) the target's `CreateDate` resolves toward **redeploying**.

Plus the ones already there and still true: a consumer whose targets all predate
its tasks is not redeployed even when an unrelated endpoint is newer; a service
emitting no `ecs_service` is never redeployed; a slow rollout warns and does not
fail the release. Also a `hcl.py` assertion that `wait_for_steady_state = true`
appears on every emitted `aws_ecs_service`.

No integration coverage exists for this step and none is added — the boundary is
real AWS, and the failure mode is proven by the elastic smoke walk (advance plan
§ Close-out 5).

## Doctrine — proposed wording

Substance is mine to own per the advance plan; the wording is escalated before
it lands. Everything below is transcription of the design record except where
flagged **[NEW]**.

### A. `release.md:75` and `:80` (the numbered elastic list)

`:75` — "three operations in sequence, followed by a conditional fourth" →

> For elastic-foundation projects, `./bin/docex release <env>` performs three
> operations in sequence, followed by a fourth that always runs and is almost
> always a no-op:

`:80` — the fourth item's second sentence →

> 4. **Reconcile Service Connect consumers** — see [§ Service Connect Consumer
>    Reconcile](#service-connect-consumer-reconcile) below. A no-op on any env
>    that is already converged, which is nearly every release.

### B. `release.md § Service Connect Consumer Reconcile`

Paragraphs 1–2 (lines 98–100) are unchanged. Steps 1–3 and everything after
them become:

> So after the final apply, `release` asks one question of current AWS state —
> **is any running consumer task older than the registration of a name it
> needs?** — and repairs whatever it finds:
>
> 1. Reads the Cloud Map `CreateDate` of every endpoint name in the env
>    namespace, and the oldest `startedAt` across the running tasks of each core
>    service that declares a core `uses` target.
> 2. Redeploys (`forceNewDeployment`) every core service whose oldest running
>    task started before the `CreateDate` of a name it `uses`.
> 3. Waits, bounded, for those services to reach steady state — so a release
>    that exits 0 means the env actually works, and the following
>    [`stagetest`](../tests.md#staging-tests) is not racing a rollout.
>
> Both operands are durable AWS state read **after** the apply. Nothing is
> carried across the apply and nothing is remembered between releases: the step
> describes the world rather than the run. That is what makes it self-healing —
> an interrupted release, a hand-run `tofu apply`, a service created out of
> band, and a rollback all leave a state the next `release` reads correctly and
> repairs. A trigger keyed on *this release's* actions cannot do that: on the
> re-run of an aborted release every name already exists, and the broken env is
> set-identical to the healthy one. The only difference is the relative age of
> one task and one registration, and a set has no time dimension.
>
> Three properties are worth stating:
>
> - **It is a no-op on a converged env, and that is emergent rather than
>   arranged.** Where every consumer task postdates every name it `uses`, the
>   comparison finds nothing and no service is touched. Nothing special-cases an
>   ordinary image-tag release as cheap; it is cheap because it is already
>   correct.
> - **The comparison is per-consumer, not per-namespace.** A consumer whose own
>   targets all predate its tasks is left alone even when some unrelated
>   endpoint is newer than it.
> - **It handles cycles, which ordering cannot.** The `uses` graph may legally
>   contain cycles, and in a cycle some member must be created first — so no
>   creation order exists. Acting *after* everything is registered is the only
>   mechanism that works for `web ↔ worker`.
>
> Three implementation details matter:
>
> - **The read must not see the apply's own draining tasks.** `aws_ecs_service`
>   is emitted with `wait_for_steady_state = true`, so the apply does not return
>   until its rollouts have settled. Without it the step would read tasks that
>   are already on their way out and redeploy for nothing.
> - **Ties break toward redeploying.** Both timestamps are AWS-server-issued,
>   but they come from two different services and small skew is possible, so the
>   comparison carries a small margin that favours acting. A false positive
>   costs one rolling deploy; a false negative costs a permanently broken env
>   that exits 0. Never round toward silence.
> - **Client bookkeeping entries are not endpoints.** A namespace holds one
>   `aws-ecs-sc.client.<uuid>.<service>` entry per client-only participant.
>   They register nothing, nothing can `uses` them, and they are filtered out
>   before the comparison.

The two closing paragraphs (failed redeploy fails the release; slow settle is a
warning) and **Fixed foundations need none of this** are unchanged — the latter
was already corrected by Mod 112. See design question 2 for one word in it.

### C. `cicl.md:396` (job 5 in the `uses` list)

> 5. On elastic, it names the endpoints each consumer must be able to resolve,
>    so a release can find and redeploy any consumer whose tasks predate one —
>    see [§ Resilience covers reachability, not
>    resolvability](#resilience-covers-reachability-not-resolvability).

### D. `cicl.md:420` (the closing paragraph of § Resilience covers reachability, not resolvability)

First sentence changes; the soundness argument that follows is correct and
stays verbatim. One sentence is appended **[NEW]** — it is the design record's
"the check describes the world rather than the run" stated for this section,
which otherwise still reads as release-relative:

> **`docex` closes this at release time**, by redeploying, after the apply, any
> consumer with a running task older than the registration of a name it `uses`.
> Note carefully that this is *not* the deploy-time ordering emulation rejected
> above, and the distinction is what makes it sound: an endpoint **registration
> is durable state**, owned by the service rather than by task liveness, and it
> survives every task replacement. Holding once is therefore permanently
> sufficient — after the first registration, every later task (scaling, AZ
> rebalance, failed health check, platform update) starts into a namespace that
> already contains the name. A readiness gate decays because liveness changes; a
> registration does not. **[NEW]** Because *both* halves of the comparison are
> durable — task age as much as registration age — the check describes the env
> rather than the release that produced it, and any broken env it can read it
> can also repair. See [release.md § Service Connect Consumer
> Reconcile](./specifics/release.md#service-connect-consumer-reconcile).

## Out of scope

- **The § Bonus standing invariant.** "Every consumer task is younger than its
  targets' endpoints" would read well as a `check` or `describe` assertion, but
  `run_check` takes no `AWSClient` and would need a new injected dependency plus
  a dispatcher change. Logged for a future advance; the predicate is written as
  a pure function of `(compiled, endpoint_created, task_started)` so lifting it
  later is a call-site change, not a rewrite.
- Anything scheduler/clock (Mods 115–116) — the existing scheduler-skip test and
  the `emits ecs_service` guard stay as they are and are Mod 116's to delete.
- The upgrade guide and `PRE_CUT_CHECKLIST.md` (117), `doctrine_excerpts/` (118).

## Documentation impact (mod-cycle step 8, not implementation)

- `docex/plans/core/release_flow.md` — the "four sequences" table and § Elastic
  flow never documented the mod-109 reconcile at all; it gains a row and a
  `Where to look when changing things` entry.
- `docex/plans/core/compiler.md:493` — `uses` job list wording for the elastic
  release read.
- `doctrine_excerpts/service_discovery.md` mentions Service Connect but not the
  reconcile; whether it earns a line is Mod 118's decision, logged rather than
  taken here.

## Design questions — resolved

All three settled by the operator at design review. Design approved.

1. **The skew margin's value — `0`, with `<=` so exact ties redeploy. No blanket
   margin.** The corporal's proposed 60 s was **overruled**, on the recon
   finding: `CreateDate` precedes every task, so a 60 s window evaluates
   `startedAt < CreateDate + 60` → `45 < 60` → redeploy on a normal, correct
   first-ever release, for every consumer. That is a predictable false positive,
   not a safety margin, and it would quietly convert the emergent no-op property
   into "always redeploys on first release". The false negative it was meant to
   cover cannot really occur: the recon measured an exact relationship — a task
   starting after the name exists resolves it on its first probe cycle — leaving
   only sub-second ECS↔Cloud Map skew, which `<=` covers. The constant stays in
   code with a WHY recording why it is **zero**.
2. **Approved.** `release.md:114` becomes "…with no launch-time name freeze".
   After this mod *snapshot* means nothing in that step, and Mod 112 had no way
   to know that when it corrected the sentence.
3. **Approved, including the [NEW] sentence in D.** It is explanatory rather
   than rule-making, and without it that section still reads release-relative —
   a reader would reasonably conclude the old trigger survived. §§ A–C are
   faithful transcription.

Two notes recorded from the same review:

- **`wait_for_steady_state` is not redundant with the existing wait.**
  `ecs_wait_services_stable` (`release.py:327`) runs *inside* the reconcile,
  *after* the redeploy, so it does nothing about the apply's own rollouts still
  draining when the predicate reads. Different moments; neither substitutes for
  the other.
- The design record's status line claims "no emitted-output change", which this
  mod falsifies. **The record is corrected as part of this mod** rather than
  left carrying a false claim.

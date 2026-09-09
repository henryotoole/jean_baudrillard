# Mod 109 — Guarantee the `consumes` fan-out survives a first elastic release

## Motive

On a first-time elastic release the doctrine-mandated `consumes` fan-out
(`/health/<svc>/<proc>`) fails **permanently**, decided by a start-order race
between the consumer and its target. Found by the 1.6.0 pre-cut smoke walk at
`PRE_CUT_CHECKLIST § D.11`.

Cut blocker. Also almost certainly **pre-existing** — `consumes` and the fan-out
predate CICL v2 — surfaced now because D.11 is the first first-time elastic prod
release with a non-`web` consumed process type.

## The mechanism

ECS Service Connect fixes a client task's set of resolvable endpoints **at task
start**. AWS states it plainly:

> You must redeploy existing services before the applications can resolve new
> endpoints. New endpoints that are added to the namespace after the most recent
> deployment won't be added to the task configuration.
>
> — [Amazon ECS Service Connect components](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-connect-concepts-deploy.html)

`docex` emits the consumer's and the consumed's `aws_ecs_service` with no
ordering between them, so tofu creates them concurrently and their tasks start
concurrently. Observed on the walk:

```
api-web    task started 19:40:02   <- consumer won the race
api-worker task started 19:40:17
api-worker task started 19:41:03
```

`api-web`'s Service Connect proxy was configured before the worker's endpoint
existed, so the alias was never installed. Result:
`503 … api.worker unreachable: Name or service not known` — **indefinitely**,
with both worker tasks `HEALTHY` and 2 instances registered in the namespace.
Ten probes over ~3 minutes all failed. `aws ecs update-service
--force-new-deployment` on `api-web` alone returned it to 200 the moment the
replacement task took over, with nothing else changed.

## Why this is a real hole in the doctrine's model

[`cicl.md § Depends-On Relationships`](../../../doctrine/infrastructure/cicl.md#depends-on-relationships)
already reasons about elastic dependency failure and chooses application
resilience over ordering:

> Every service must tolerate its dependencies being absent at any moment — not
> only at startup — because on elastic they will be. Reconnect, back off, and
> fail requests cleanly.

**That remedy cannot fix this.** It presumes *transient* absence. Here the name
does not resolve for the task's entire lifetime — `EAI_NONAME`, not
connection-refused — so no backoff strategy ever converges. The doctrine models
elastic dependency failure as a **reachability** problem; Service Connect adds a
**resolvability** problem, and resolvability is not something application code
can retry its way out of. Nothing currently written acknowledges that second
failure mode.

## Why the doctrine's anti-ordering argument does not apply

The same section rejects elastic ordering for a specific reason:

> even a deploy-time emulation would hold exactly once and then be silently
> violated forever after, as ECS independently replaces tasks for scaling, AZ
> rebalance, failed health checks, and platform updates.

That argument is correct, and it kills **readiness** ordering — but readiness is
not what is needed here. What is needed is *endpoint registration presence*, and
registration is **durable state owned by the `aws_ecs_service`**, not by task
liveness. A Service Connect endpoint stays in the namespace whether or not any
task behind it is running or healthy.

So **holding exactly once is exactly sufficient.** Once the namespace contains
the alias, every subsequent task replacement — scaling, AZ rebalance, failed
health check, platform update, the very events the objection names — starts into
a namespace that already contains it. The decay that invalidates readiness
ordering does not touch this.

Two consequences, both good:

- **No `wait_for_steady_state` is required.** We do not need the target healthy,
  or even running. That keeps applies fast.
- **A one-shot reconcile is a complete fix**, not a papered-over race.

## Why ordering alone is nonetheless insufficient

`consumes` cycles are legal and, per
[`cicl.md § The graph may contain cycles`](../../../doctrine/infrastructure/cicl.md#the-graph-may-contain-cycles),
`web ↔ worker` is "the most common web/worker topology in existence". In a cycle
**someone must be created first**, so no creation order can satisfy both members
— whoever starts first loses. A tofu `depends_on` mapping would additionally be a
hard graph cycle and fail the plan outright.

Ordering is therefore rejected on its own merits, independent of the deadlock
hazard. The mechanism must work *after* everything exists.

## Change

### A post-apply consumer reconcile, keyed on the namespace delta

In `pipeline/release.py::_release_elastic`:

1. **Before** any `tofu apply` for the env, snapshot the set of Service Connect
   endpoint names in the env's namespace (`docex-smoke-elastic-<env>`). A
   missing namespace reads as the empty set.
2. **After** the final apply, re-list.
3. Compute the reconcile set:

   > **{ consumer `C` : `C` declares ≥1 `consumes` target `T` whose endpoint was
   > absent from the namespace before this apply }**

4. For each member, `ecs update-service --force-new-deployment`, then wait
   (bounded) for the service to reach steady state.
5. `log` what was redeployed and why, naming the triggering target. Silence here
   would make a release that quietly redeploys look like one that did not.

Behaviour across the cases that matter:

| Release | Endpoints newly registered | Reconcile set | Cost |
| ------- | -------------------------- | ------------- | ---- |
| First-time (walk's D.11) | all | every consumer with a `consumes` target (`api.web` in the seed) | one extra rolling deploy |
| Steady state, no shape change | none | **empty — no-op** | two `list-services` calls |
| New process type added to a live env (the `upgrade_1.6.0` path for downstream projects) | the new one | consumers of the new target | one rolling deploy |
| Legal `web ↔ worker` cycle, both new | both | both members | one rolling deploy each; correct, because by reconcile time both endpoints exist |
| `rollback` | none — rollback changes no shape | empty — no-op | negligible |

Step 3 deliberately does **not** try to determine whether a given consumer task
actually started before its target registered. That is unknowable from outside
the task, and the conservative answer costs one rolling deploy on a
shape-changing release only.

### Why wait for steady state (step 4)

A release that exits 0 should mean the environment works. Without the wait,
`release` returns while the fan-out is still 503 and the next pipeline step —
`stagetest`, whose whole job is probing a deployed env — races the rollout. The
wait is bounded and only ever runs on a shape-changing release, so steady-state
releases pay nothing. **Flagged as a design question** in case the operator
prefers speed.

### AWS client surface

Two additions to `aws/client.py` (protocol), `aws/boto3_client.py`
(implementation), and the fake in `tests/conftest.py`:

- `service_connect_endpoint_names(namespace_name) -> set[str]` — the Service
  Connect service names registered in the env namespace; empty set when the
  namespace does not exist. (Cloud Map `servicediscovery:ListServices` filtered
  by namespace.)
- `ecs_force_new_deployment(cluster, service)` — `update_service(...,
  forceNewDeployment=True)`.
- A bounded `ecs_wait_services_stable(cluster, services)` for step 4.

### `consumes` gains a release-time reader — and stays emit-free

`consumes` currently does three jobs, all CI/validation. This adds a fourth:
driving the reconcile. Crucially it remains **emit-free** — the reconcile is an
*orchestration action* reading the compiled model at release time, and writes
nothing into `main.tf`. So
`tests/unit/test_process_expansion_emit.py::test_consumes_reaches_no_emitted_artifact`
stays green **and keeps its meaning**; it asserts absence from emitted compose/HCL
output, which is still correct and still worth pinning.

The doctrine wording must nonetheless separate two claims it currently runs
together — "emits nothing" (still true) and "consumed entirely by CI and
validation" (no longer true).

### Tests

1. **The reconcile fires on a newly registered target.** Fake AWS reports an
   endpoint set that grows across the apply; assert `force_new_deployment` is
   called for the consumer and *not* for unrelated process types.
2. **No-op in steady state.** Endpoint set unchanged ⇒ zero
   `force_new_deployment` calls. This is the test that keeps normal releases
   cheap.
3. **Cycle: both members redeploy.** `web ↔ worker`, both endpoints new ⇒ both
   redeployed, no error. The case pure ordering cannot express.
4. **A consumer of an already-registered target is left alone**, even when some
   *other* endpoint is new — the delta is per-target, not per-namespace.
5. **`consumes` is still absent from emitted output** — the existing guard, left
   untouched, re-run.

## Doctrine edits (operator-approved, for review)

1. **`cicl.md § Depends-On Relationships`** — add the resolvability carve-out:
   connection resilience covers reachability but not Service Connect *name
   resolution*; a client that starts before a target registers can never resolve
   it; `docex` closes that with a post-apply reconcile. Worded so it does **not**
   entrench `depends_on` itself (see the separate `depends_on` proposal).
2. **`cicl.md § Consumes Relationships`** — three jobs → four; split "emits
   nothing" from "CI-only" in both the prose and the comparison table's
   `Emitted` row.
3. **`specifics/release.md`** — document the reconcile as a step of the elastic
   release mechanism, including the steady-state no-op.
4. **`contracts.md § Fan-out`** — one sentence: on elastic the fan-out's
   correctness depends on the reconcile, linking to it. The section already ends
   with an elastic-specific note about `port` and Service Connect, which is where
   this belongs.

## Scope boundaries

- **Not a `depends_on` change.** The `depends_on` question the operator raised is
  tracked separately and is not a cut blocker; nothing here presumes its outcome.
- **No transfer-table change.** `consumes` is not a table field.
- **No seed change.** The smoke project already declares the topology that
  exposes this; it needed no modification to reproduce.
- **Fixed foundation untouched.** Compose has real `depends_on` ordering and no
  Service Connect; docker network DNS resolves a sibling whenever it exists. The
  walk confirmed the fan-out working on the fixed-style dev stack.

## Design questions

1. **Wait for steady state, or return immediately?** Recommended: wait, bounded.
   A release exiting 0 should mean the env works, and `stagetest` runs next.
2. **Should `docex check` gate on anything here?** Probably not — this is a
   release-time property, not a repo-time one. Noted so it is a decision.
3. **Does the reconcile belong to `release` only, or also to a standalone
   command?** A `docex reconcile <env>` escape hatch would help an operator whose
   env is already in the broken state without forcing a full release. Recommended
   as a follow-up, not here.

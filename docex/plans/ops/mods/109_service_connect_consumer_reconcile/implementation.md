# Mod 109 — Implementation

Design: [`overview.md`](./overview.md). Operator decided design question 1:
**wait for steady state** (bounded).

## Step 1 — AWS client surface

### `src/docex/aws/client.py` (protocol)

Add three methods to the `AWSClient` protocol, docstrings stating the contract:

- `service_connect_endpoint_names(namespace_name: str) -> set[str]` — the set of
  Service Connect endpoint (Cloud Map service) names registered in the named
  private-DNS namespace. **Returns the empty set when the namespace does not
  exist**, because that is the honest answer on a first release and forcing the
  caller to distinguish "absent" from "empty" buys nothing.
- `ecs_force_new_deployment(cluster: str, service: str) -> None` —
  `update_service(..., forceNewDeployment=True)`.
- `ecs_wait_services_stable(cluster: str, services: list[str], *, timeout_s: int) -> bool`
  — block until every named service reaches steady state; return `False` on
  timeout rather than raising, so the caller decides whether a slow rollout is
  fatal.

### `src/docex/aws/boto3_client.py` (implementation)

- `service_connect_endpoint_names`: `servicediscovery.list_namespaces` to find the
  namespace id by name, then paginate `list_services` filtered by
  `NAMESPACE_ID`. Namespace not found → `set()`.
- `ecs_force_new_deployment`: `ecs.update_service(cluster=…, service=…, forceNewDeployment=True)`.
- `ecs_wait_services_stable`: the `services_stable` waiter, with the delay/attempts
  derived from `timeout_s`; catch `WaiterError` → `False`.

### `tests/conftest.py` (fake)

- `service_connect_endpoints: list[set[str]]` — a **queue** of successive return
  values, popped per call, so a test can script "empty before the apply, one
  endpoint after". Falls back to repeating the last entry once exhausted.
- `ecs_services_stable: bool = True` — what the waiter reports.
- The three methods, each `_record`ing as the existing fakes do.

## Step 2 — `src/docex/pipeline/release.py`

### The reconcile set

Add a module-level helper:

```
_consumer_reconcile_set(compiled, *, new_endpoints) ->
    list[tuple[consumer_global_name, triggering_target_global_name]]
```

For each compiled service that `is_core`, emits an `ecs_service`, and declares
`consumes`: resolve each target through `compiled.services[key]`, and include the
consumer when a target's `global_name` is in `new_endpoints`. Sorted, so output
and test assertions are order-stable.

Three guards, each with a reason in-source:

- **`ecs_service` in `emits["elastic"]`** — a `scheduler` process type has no
  long-running service to redeploy, and `update_service` against a non-existent
  service is an error, not a no-op.
- **Target resolved through `compiled.services`** — an unresolvable key cannot
  happen after validation, but the reconcile must not be the thing that raises if
  it ever does; skip it.
- **Target must itself emit an `ecs_service`** — only those get a Service Connect
  registration, so only those can appear in the namespace.

### Wiring into `_release_elastic`

The namespace name is the ECS cluster name — both are
`apply_policy(f"{project}_{env}", ecs_policy)`, which the first-release detector
already computes. Reuse that value; do not recompute it, and do not introduce a
second naming expression that could drift.

1. **Before** any apply on a non-dry-run, non-`skip_migrations` path:
   `endpoints_before = aws.service_connect_endpoint_names(cluster_name)`.
2. **After** the final apply on **both** branches (first-release and
   steady-state), call `_reconcile_service_connect_consumers(...)`, which
   re-lists, diffs, builds the set, redeploys, and waits.
3. Print per redeployed consumer, naming the triggering target. A release that
   silently redeploys looks like one that did not.

**`skip_migrations` (rollback) deliberately keeps the snapshot+reconcile too.**
A rollback changes no shape, so the diff is empty and the whole thing is two API
calls and a no-op — but wiring it in costs nothing and means a rollback that
*does* somehow change the endpoint set is covered rather than being a second
code path to reason about.

The `dry_run` path returns before the snapshot and is untouched.

### Failure handling

A failed `force_new_deployment` is a **hard release failure** — the fan-out is
doctrine-mandated and an env whose consumers cannot resolve their targets is not
successfully released. A `False` from the waiter is a **warning, not a failure**:
the deployment was accepted and ECS will converge; a slow rollout should not
fail an otherwise-good release. Both messages say what to do next.

## Step 3 — Tests (`tests/unit/test_service_connect_reconcile.py`)

New file; five tests, matching `overview.md § Tests`:

| Test | Asserts |
| ---- | ------- |
| `test_reconcile_redeploys_consumer_of_newly_registered_target` | endpoint set grows by the worker ⇒ `ecs_force_new_deployment` called for `api-web` only |
| `test_no_reconcile_when_namespace_unchanged` | identical before/after ⇒ **zero** redeploys (keeps steady-state releases cheap) |
| `test_reconcile_handles_consumes_cycle` | `web ↔ worker`, both endpoints new ⇒ both redeployed, exit 0 |
| `test_consumer_of_preexisting_target_is_not_redeployed` | target already registered while a *different* endpoint is new ⇒ no redeploy (the diff is per-target, not per-namespace) |
| `test_scheduler_consumer_is_never_redeployed` | a `scheduler` never gets `update_service` — it has no ECS service |

Plus re-run the untouched
`test_process_expansion_emit.py::test_consumes_reaches_no_emitted_artifact`
guard: `consumes` must still reach no emitted output. The reconcile reads the
compiled model at release time and writes nothing into `main.tf`, so that guard
stays green **and keeps its meaning**.

## Step 4 — Doctrine edits

1. **`cicl.md § Depends-On Relationships`** — the resolvability carve-out after
   the "startup ordering is not a substitute for connection resilience" block.
   States: resilience covers *reachability*; Service Connect adds a
   *resolvability* failure a client cannot retry out of; `docex` closes it with a
   post-apply reconcile; and — the part that keeps this consistent with the
   section's own anti-ordering argument — registration is durable, so holding
   once is sufficient. Worded so it does not entrench `depends_on` (see
   [`_advance_retire_depends_on.md`](../_advance_retire_depends_on.md)).
2. **`cicl.md § Consumes Relationships`** — three jobs → four; split "emits
   nothing" (still true) from "consumed entirely by CI and validation" (no longer
   true) in the prose, and update the comparison table's `Emitted` row.
3. **`specifics/release.md`** — the reconcile as a step of the elastic release
   mechanism, including the steady-state no-op.
4. **`contracts.md § Fan-out`** — one sentence in the existing elastic-specific
   closing note, linking to the reconcile.

## Step 5 — Verification

- `pytest tests/unit -q` green.
- Rebuild `docex:1.6.0`.
- **Real-AWS retest of `PRE_CUT_CHECKLIST` D.3 → D.11.** The defect only
  manifests on a *first-time* release, so the retest needs a fresh project tier
  and a fresh prod env tier. The acceptance criterion is
  `https://docex-smoke-elastic.luxrnd.tech/health/api/worker` returning **200 on
  the first probe after `release prod`**, with no manual `force-new-deployment`.
- Then teardown + `verify_clean.sh`.

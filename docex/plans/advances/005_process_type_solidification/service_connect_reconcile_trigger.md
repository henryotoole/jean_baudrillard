# Service Connect Consumer Reconcile — Fix the Trigger's Operand

A design record for replacing the trigger of the elastic release's
[Service Connect Consumer Reconcile](../../../../doctrine/infrastructure/specifics/release.md#service-connect-consumer-reconcile)
step. The step itself is sound and stays; one of its two comparison operands is
ephemeral and must become durable.

> **Status.** **Design settled; the empirical claim is confirmed.** Small and
> additive-in-spirit — no `cicl_version` implication, no `infra.yml` change. One
> emitted-output change: `wait_for_steady_state = true` on `aws_ecs_service`, per
> [implementation detail 1](#three-implementation-details-that-matter), so the
> step does not read the apply's own draining tasks. (This line originally
> claimed *no* emitted-output change; Mod 114 falsified it.) Two doctrine files
> and one docex code path. ECS Service
> Connect's launch-time name freeze — which the entire subsection rests on — was
> observed on a scratch Fargate stack and holds; see [Verified](#verified), which
> also corrects two secondary claims made in passing below.

## Background — the ECS constraint

Recorded here because the current doctrine asserts the behaviour without
explaining the mechanism, and the mechanism is what makes the fix obvious.

ECS Service Connect is a managed mesh over a Cloud Map **HTTP** namespace (no
DNS records). Each ECS service opts in via `serviceConnectConfiguration`;
`services[]` declares the endpoints it *provides*, each entry naming a
`portName` that must reference a **named** port mapping in the task definition.
That is why
[`contracts.md`](../../../../doctrine/infrastructure/contracts.md#health-checks)
requires `port` on a `consumes` target: no port mapping, nothing to register,
cannot be a provider. A service with an empty `services[]` is a client-only
participant and registers nothing.

When a task launches, ECS injects an Envoy sidecar and materializes the
namespace's registered endpoint names into the task's **local** name resolution
(documented mechanism: `/etc/hosts` entries mapping each client alias to a
loopback address, with Envoy listening there). A call therefore goes:

```
app connects to  api-worker:8080
  → local resolution says api-worker = loopback   ← written once, at task launch
  → local Envoy accepts
  → Envoy forwards to a real upstream task IP     ← refreshed continuously
```

Two different lifetimes, and the whole defect lives in the gap:

- **Upstream IPs are dynamic.** Envoy receives endpoint updates from the ECS
  control plane, so scaling and task replacement need no client action. This is
  *reachability* — transient, self-healing, covered by connection resilience.
- **The set of resolvable names is frozen at task launch.** A name registered
  afterward has no local entry. It is a **resolution** failure, not a connection
  failure, so retrying never converges — there is nothing to converge on.

Three vocabulary precisions that the fix depends on:

1. **Registration is per-task; the name is per-service.** A provider's task
   registers as an *instance* under the service's `discoveryName`. The name is
   created **when the ECS service is created — before any task exists** — and
   persists as instances churn beneath it. This is the durable fact
   [`cicl.md`](../../../../doctrine/infrastructure/cicl.md#resilience-covers-reachability-not-resolvability)
   already leans on, and it is correct.

   > **Corrected by measurement.** This paragraph originally read "created once,
   > when the service first brings up a task." [§ Verified](#verified) Q2 refutes
   > that: a service created at `desiredCount: 0` produced a Cloud Map service
   > with a `CreateDate` one second *before* the ECS service's own `createdAt`,
   > with no instances and no task ever launched. The correction **strengthens
   > the fix** — `CreateDate` sits earlier relative to any task than assumed, so
   > `startedAt < CreateDate` is strictly more conservative and biases toward
   > redeploying, which is the direction [implementation detail
   > 2](#three-implementation-details-that-matter) demands.
2. **The read is per-task-launch, not per-deployment.** `forceNewDeployment`
   fixes nothing by itself; it works because a rolling deployment replaces
   tasks and each replacement reads the namespace fresh. Same reason a task
   replaced for any other cause comes up correct with no intervention.
3. **Registrations are unordered relative to each other.** Each provider
   registers whenever its own tasks happen to come up during the concurrent
   `tofu apply`. That is the race.

### The invariant

> **A task resolves exactly the names that existed when it started, so every
> consumer task must be younger than every name it needs.**

Everything below is a consequence of this one line.

## The defect

The step as specified today (`release.md` step 4) takes a **snapshot of the
namespace's endpoint names before any apply in this release**, diffs it against
the post-apply namespace, and redeploys consumers whose targets appear in the
delta.

That snapshot is a record of *what this release found when it started*. It is
ephemeral, lives in one process's memory, and is unreconstructable afterward.
Two consequences:

**1. Step 4 is a bracket around step 3, not a post-apply operation.** It
consumes a value captured before the apply, so `release` must carry state across
the apply. "Before any apply" is load-bearing prose, and more delicate than it
reads: on a first-ever release
[`migrations.md`](../../../../doctrine/infrastructure/specifics/migrations.md#first-time-release-of-an-env)
swaps the migrate/apply ordering, so it must mean *before whichever comes
first*.

**2. An interrupted release leaves a permanently broken env and exits 0.**

- Release N adds `api.worker`. Pre-apply snapshot = `{api-web}`. Apply
  registers `api-worker`. **Abort before phase 2** (expired credentials,
  dropped connection, `Ctrl-C`).
- Re-run. The pre-apply snapshot **now contains** `api-worker`. Apply is a
  no-op. Diff is empty. No redeploy. Exit 0.
- `api-web`'s tasks are still the ones launched before `api-worker` registered.
  They will never resolve it.

This contradicts the idempotency claim made twice — in
[`docex.md`](../../../../doctrine/infrastructure/docex.md#release)
("re-running on an already-converged target is a no-op") and in `release.md`
("re-run any time to reconcile") — and it defeats the purpose of step 4's
bounded steady-state wait, which exists so that exit 0 means the env works. On
`stage`, `stagetest`'s 503 catches it. **On `prod` there is no backstop:** the
ALB probes only self-`/health`, nothing automatically probes the fan-out, and
the symptom is application calls failing across that edge with both sides
reporting healthy.

There is also a minor imprecision: the diff asks whether the *endpoint* is new,
not whether *this consumer's tasks* are too old, so a consumer whose tasks
already postdate registration is redeployed anyway. Harmless, but wasted.

## The fix

Replace the question. Instead of *"did this endpoint register during this
release?"* ask:

> **"Is any running consumer task older than the registration of a name it
> needs?"**

Both operands are durable AWS state, read **after** the apply:

| Operand | Source |
| ------- | ------ |
| Consumer task age | `ListTasks` + `DescribeTasks` on the consumer's ECS service; take the **minimum** `startedAt` across running tasks — one stale task is enough to matter |
| Name registration age | `ListServices` on the Cloud Map namespace; `CreateDate` per discovery name |

Redeploy core service `P` iff some running task of `P` started before the
`CreateDate` of some `consumes` target of `P`. Then the same bounded
steady-state wait as today.

`CreateDate` on the Cloud Map **service** is the correct operand, not instance
registration time: the name's existence in the namespace is what ECS reads when
writing a new task's local resolution. A name with zero healthy instances still
resolves — to an Envoy with no upstreams, which is a *reachability* failure and
recoverable. That is consistent with the doctrine's existing split.

### What this deletes

- The snapshot, the bracket around step 3, and all cross-step state. Step 4
  becomes self-contained: read state, act, verify.
- The "before any apply" delicacy and its first-release migrate/apply-swap
  interaction.
- The abort hole. Every failure mode self-heals on the next `release` —
  interrupted run, a hand-run `tofu apply`, a service created out of band, a
  rollback — because the check describes the world rather than the run.
- The special-cased "no-op unless the shape changed" property, which stops
  being a claim and becomes **emergent**: in a converged env every consumer
  task postdates every registration, so nothing fires.
- The wasted rollouts, since the test is now per-consumer rather than
  per-endpoint.

### Bonus: a standing invariant

Because the check is a pure function of current state, the same comparison reads
as a **diagnosable invariant** rather than only a repair. "Every consumer task
is younger than its targets' endpoints" can be evaluated cold, at any time — a
natural fit for [`check`](../../../../doctrine/infrastructure/cicd.md#check-step)
or a `describe`-style read.

### Three implementation details that matter

1. **Wait for the apply's own rollouts before evaluating.** If step 3's rolling
   deploy is still draining old tasks when step 4 reads, it will see
   pre-registration tasks that are already on their way out and redeploy for
   nothing. Setting `wait_for_steady_state = true` on the `aws_ecs_service`
   resources gets this for free inside step 3.
2. **Break ties toward redeploying.** Both timestamps are AWS-server-issued (no
   client clock), but they come from two different services (ECS and Cloud Map)
   and small skew is possible. Any grace margin must favour acting: a false
   positive costs one unnecessary rolling deploy; a false negative costs a
   permanently broken env that exits 0. Never round toward silence.
3. **Filter the client bookkeeping entries out of `ListServices`.** Every
   client-only participant gets an entry named
   `aws-ecs-sc.client.<uuid>.<ecs-service-name>` in the namespace — observed in
   [§ Verified](#verified) on a service with an empty `services[]`, which
   registers no endpoint at all. These are not endpoints and no consumer can
   `uses` them. Unfiltered, they enter the comparison as names with a
   `CreateDate`, and any consumer task older than an unrelated client's
   bookkeeping entry is redeployed for nothing. Match and drop the
   `aws-ecs-sc.client.` prefix.

## Alternatives, and why they fail

Recorded because the current doctrine argues well for *why step 4 exists* but
says nothing about why its trigger is shaped as it is — which is how the
snapshot got in. Every correct design does one of exactly three things with the
ordering:

- **Enforce it** — unconditional redeploy of all consumers post-apply.
- **Observe it** — task `startedAt` vs. name `CreateDate` (this proposal). The
  only comparison whose operands carry time.
- **Remember it** — a post-success cache; really a one-bit record that the
  ordering was established.

Anything else fails. The failures are instructive:

**Unconditional redeploy** is genuinely convergent and cannot be wrong — no
trigger to evaluate incorrectly, no state — and self-heals the abort case for
free. Rejected only on cost: two sequential rolling deploys every release, each
waiting for steady state, and a zero-change release stops being a no-op (it
churns tasks), so the idempotency claim would have to be reworded from "no-op"
to "converges to the same state". Defensible if minimum docex code is the
overriding goal.

**A post-success cache of the last released shape** converges *if* written only
after phase 2 succeeds — then it records phase-2 completion, and an aborted
release leaves it stale in the safe direction. Rejected because it is a second
source of truth about deployed state, and the registry already holds that fact
authoritatively. It drifts: `rollback` deregisters a name and is exactly the
emergency path where cache maintenance would be forgotten, after which the next
forward release sees no shape change and skips phase 2. Git is the wrong home
(deployed-state truth that git can rewind, branch, and merge — failing
*silently*; compare TTE vars, which live where the deployment lives for exactly
this reason). Moving it to SSM to fix that means doing an AWS read anyway, at
which point reading the registry is strictly better.

**Registry vs. `infra.yml`** dissolves the cache's drift and rollback problems —
nothing to sync, nothing git can rewind — and is a better *shape-change
detector*. But it has no memory of phase 2, only of apply completion, so it
fails the abort case identically: on the re-run both sets contain `api-worker`,
they match, and no redeploy fires.

**Any number of name-set comparisons** are structurally blind, which is the
sharpest result of the whole investigation. In the aborted state, `infra.yml`,
the Cloud Map registry, *and* the set of services with running tasks all agree:
every name exists everywhere, every service is up, every self-`/health` passes.
**The broken env is set-identical to the healthy env.** The only difference is
the relative age of one task versus one registration — an ordering fact, and a
set has no time dimension. Adding a fourth or fifth name-set gains nothing.

**Any trigger keyed on *this release's* actions** fails the same way, including
the tempting cheap variant "did any name's `CreateDate` fall after this release
started?" Release N registers the worker at T1 and aborts; the re-run starts at
T2 > T1; the `CreateDate` is not after T2; diff empty; broken. The registry
operand is not the flaw — the **release-relative** operand is.

**Ordering the creations** cannot work at all. A `consumes` graph may legally
[contain cycles](../../../../doctrine/infrastructure/cicl.md#the-graph-may-contain-cycles),
and in a cycle someone must go first. That argument stands and is sufficient on
its own.

**A two-pass apply at `desiredCount: 0`, then scale up** — rejected on **cost**,
not on impossibility. The original dismissal here ("registration is per-task, so
the scale-up cohort races too") was **refuted by measurement**: names are created
with the ECS service, so a first pass at zero would publish every name before any
task launched and the scale-up cohort would not race. It is a genuinely
convergent design. It is rejected because it makes every release a two-phase
apply that churns every task — the same cost that rules out unconditional
redeploy, paid on every service rather than only on consumers, and it forfeits
the no-op property on a zero-change release. The proposed fix is strictly
cheaper and needs no apply-shape change.

**DNS-based Cloud Map service discovery** (the older `serviceRegistries`,
generation 2) dissolves the problem entirely, since DNS is resolved per call and
a record appearing later is visible to a running task. Rejected: it trades a
clean mechanism for a legacy one, reintroduces app-level DNS caching pitfalls,
loses health-aware endpoint removal, and gives up client-side load balancing
across `replicas: N`.

### Ruled out for the fan-out

Also investigated and closed, recorded so it is not re-proposed: replacing the
[health fan-out](../../../../doctrine/infrastructure/contracts.md#fan-out)'s HTTP
probe with a tick written to a shared store, which would delete the
`web → worker` resolution edge outright. **Rejected on universality.** A shared
store obliges the doctrine to name one, and none is universal — a `worker` need
not have a `cache` (it may poll the database, or consume an external stream), so
the transport would vary with whatever backing services a project happens to
declare. HTTP is the one transport guaranteed present regardless of
backing-service topology, which is the original and correct reason for the
design. Note also that the fan-out is *not* what forces the worker's HTTP
server on its own: the container's self-probe uses the same server over
localhost, so removing the fan-out alone would not delete it.

## Blast radius

Two doctrine files:

1. [`release.md § Service Connect Consumer Reconcile`](../../../../doctrine/infrastructure/specifics/release.md#service-connect-consumer-reconcile)
   — rewrite steps 1–3; the first of the three "properties" (no-op unless the
   shape changed) stops being a stated property and becomes emergent. Add the
   two implementation details.
2. [`cicl.md § Resilience covers reachability, not resolvability`](../../../../doctrine/infrastructure/cicl.md#resilience-covers-reachability-not-resolvability)
   — the closing paragraph, which describes the trigger as "redeploying any
   consumer whose `consumes` target registered during that release". The
   soundness argument above it (registration is durable state) is correct and
   stays.

[`contracts.md`](../../../../doctrine/infrastructure/contracts.md#health-checks)
says only that "`docex` closes that at release time", which remains true and
needs no edit.

One docex code path: the reconcile step. Cost is one `ListServices` plus
`ListTasks`+`DescribeTasks` per consumer, and a comparison.

## Verified

**The premise holds.** Measured on a scratch Fargate stack in `us-east-1`
(2026-08-05), torn down after. A client task launched into a namespace before a
name existed never resolved that name for the rest of its life, and its
replacement resolved it on the first probe cycle.

Setup: an HTTP Cloud Map namespace, a client-only service **A** (`services[]`
empty) running a 15-second loop that prints `/etc/hosts`, `getent hosts`, and
`curl` against two names, and a provider service **B** registering
`sc-probe-target`.

### Q1 — the launch-time freeze

**Before registration.** A's task started 20:45:03 into an empty namespace. No
Service Connect entries in `/etc/hosts`; the failure is `curl (6)`, resolution,
not connection:

```
===== CYCLE 1 20:44:55Z =====
--- /etc/hosts ---
127.0.0.1 localhost
10.20.2.162 ip-10-20-2-162.ec2.internal
--- getent sc-probe-target ---
GETENT_FAIL:sc-probe-target
--- curl sc-probe-target ---
CURL:sc-probe-target curl: (6) Could not resolve host: sc-probe-target
```

**After registration.** `sc-probe-target` was created in the namespace at
20:46:37 and had a healthy provider instance (`10.20.2.157:8080`) by 20:48:08.
A's task ran 27 cycles through 20:51:26 — five minutes after the name existed,
three after it was backed by a healthy instance — with **byte-identical output**.
`/etc/hosts` never changed:

```
===== CYCLE 27 20:51:26Z =====
--- /etc/hosts ---
127.0.0.1 localhost
10.20.2.162 ip-10-20-2-162.ec2.internal
--- getent sc-probe-target ---
GETENT_FAIL:sc-probe-target
--- curl sc-probe-target ---
CURL:sc-probe-target curl: (6) Could not resolve host: sc-probe-target
```

Retrying never converges, exactly as argued: there is nothing to converge on.

**After task replacement.** `forceNewDeployment` at 20:51:44; the replacement
task's *first* cycle already had the entries and a 200:

```
===== CYCLE 1 20:52:29Z =====
--- /etc/hosts ---
127.0.0.1 localhost
10.20.2.229 ip-10-20-2-229.ec2.internal
127.255.0.1 sc-probe-target
2600:f0f0:0:0:0:0:0:1 sc-probe-target
127.255.0.2 sc-probe-zero
2600:f0f0:0:0:0:0:0:2 sc-probe-zero
--- getent sc-probe-target ---
2600:f0f0::1    sc-probe-target
--- curl sc-probe-target ---
CURL:sc-probe-target CURL_OK:sc-probe-target http=200
```

Same service, same task definition, same namespace, same image — only the task
is younger. The failure is the launch-time freeze and nothing else.

The **reachability** half was confirmed in the same run: scaling a provider from
0 to 1 task flipped an already-running client's result for that name from `503`
to `200` with no task replacement. Both halves of the doctrine's split are now
observed — instances under an existing name are dynamic; the set of names is not.

### Q2 — the name set is keyed on the ECS service, not on any task

**The Cloud Map service is created at ECS-service-creation time, before any task
exists.** Service **C** was created with `desiredCount: 0` and a `services[]`
entry for `sc-probe-zero`. The Cloud Map service appeared with `CreateDate`
20:47:01 — one second *before* the ECS service's own `createdAt` of 20:47:02 —
with `ListInstances` returning `[]` and no task ever launched.

A client task launched afterward resolves that name: `sc-probe-zero` appears in
the replacement task's `/etc/hosts` above, and `curl` returns **503** — an Envoy
listener with no upstreams. This is precisely the case the fix already predicts:
*a name with zero healthy instances still resolves, and the failure is
reachability, recoverable.* Confirmed rather than assumed.

Two consequences for the record above:

1. **Vocabulary precision 1 is wrong on one point** and should be corrected: the
   name is created when the **ECS service** is created, not "when the service
   first brings up a task". This does not weaken the fix — it strengthens it.
   `CreateDate` now sits *earlier* relative to any task, so the
   `startedAt < CreateDate` comparison is strictly more conservative, biasing
   toward redeploy, which is the direction
   [the tie-break rule](#three-implementation-details-that-matter) demands.
2. **The `desiredCount: 0` dismissal rests on a false premise.** "Nor does
   creating services at `desiredCount: 0` and scaling up afterward help —
   registration is per-task, so the scale-up cohort races too" is refuted: names
   are established by service creation, so a first pass creating every service
   at zero would publish every name before any task launched, and the scale-up
   cohort would *not* race. The cycle argument against *ordering* creations still
   stands; only this variant is resurrected, and it should be re-rejected on cost
   (a two-pass apply that churns every task every release) rather than on
   impossibility. The proposed fix remains the cheaper design.

### The loopback mapping

The guess was right, and can now be stated: each alias gets its **own sequential
address in `127.255.0.0/16`** — `127.255.0.1`, `127.255.0.2` — so aliases sharing
a port get distinct listeners. One detail was missed: ECS writes a **parallel
IPv6 mapping** in `2600:f0f0::/32` (`2600:f0f0::1`, `2600:f0f0::2`), and glibc
prefers it — `getent hosts` returned the v6 address, and that is the address a
dual-stack client will actually dial.

### One implementation detail for the reconcile step

`ListServices` on the namespace does **not** return only endpoint names. Every
client-only participant also gets a bookkeeping entry named
`aws-ecs-sc.client.<uuid>.<ecs-service-name>`, created when its ECS service is
created — service A produced one despite an empty `services[]`. The reconcile
step must filter the `aws-ecs-sc.client.` prefix, or it will compare consumer
task ages against names that are not endpoints.

# F16 — Slow elastic rollback web ECS task (investigation)

**Status:** investigate-only (mod 053, Cluster 6 / operator decision locked).
No behavior changed in this mod. This note characterizes the cause and
recommends fix-vs-document for a follow-up.

## Symptom

On an elastic `rollback prod`, the **worker** ECS task rolled to the
target version in seconds, but the **web** task sat `PENDING`/in-progress
for ~10–12 min before `RUNNING` and the `/health` endpoint reporting the
rolled-back version. It *did* converge — this is a latency problem, not a
failure.

## What rollback does (recap)

`rollback` recompiles the target version's HCL in an ephemeral worktree
and applies it via the standard elastic release machinery (`tofu apply`,
migrate skipped). `tofu apply` on a changed image/task-def triggers an
**ECS rolling deployment** of each affected service. So the convergence
time is whatever an ECS rolling replacement of that service costs — docex
hands off to ECS here.

## Why web is slow but worker is fast — the asymmetry

The two services differ in exactly the dimensions that drive ECS
rolling-deploy time. Inspecting the emit:

### 1. ALB target-group health gating (web only) — primary suspect

- `render_target_group` (`src/docex/emit/hcl.py`) emits an
  `aws_lb_target_group` + listener rule for web-network services; web has
  one, worker does not.
- The target-group health check comes from the `web` role transfer table
  (`tables/roles/web.yml`): `interval: 30`, `healthy_threshold: 2`,
  `unhealthy_threshold: 3`. A freshly-started task must pass **2 checks
  30 s apart ⇒ ≥ ~60 s** of healthy probing before the ALB shifts traffic
  to it.
- **`deregistration_delay` is not set** anywhere in the emit, so the old
  target drains at the AWS default **300 s (5 min)**. During a rolling
  replace the connection-draining of the *old* target is on the critical
  path before the deployment is considered complete/stable.
- **`deployment_minimum_healthy_percent` / `deployment_maximum_percent`
  are not set** on `aws_ecs_service` (`render_ecs_service`), and
  `desired_count = 1`. AWS replica-service defaults are min 100% / max
  200%: ECS starts the new task, waits for it to be healthy in the target
  group, *then* drains and stops the old one. With a single task and a
  load-balanced service, that "start new → pass ALB health → drain old"
  sequence is inherently minutes-long.

Worker has no target group, no ALB registration, and no draining, so ECS
replaces it with no health-gate/drain wait — seconds.

### 2. `health_check_grace_period_seconds` is not set (web)

Without a grace period on a load-balanced ECS service, ECS begins
counting the task against the target-group health check immediately. If
the app's cold start (image pull + Envoy + app boot) is slower than the
target-group's unhealthy threshold window, ECS can consider the task
unhealthy and **kill + restart it**, adding a full replacement cycle (or
several) to convergence. This is the classic cause of a load-balanced
Fargate task that takes many minutes / appears to loop before settling.

### 3. Service Connect / Envoy injection (both, but additive on web)

Every service gets `service_connect_configuration { enabled = true }`
(`render_ecs_service`), so each task carries an injected Envoy sidecar
that must start and register before the task is fully ready. This adds a
fixed startup increment to *every* task; on web it stacks on top of the
ALB health-gate wait above.

### 4. otelcol sidecar dependsOn — ruled out

The core container `dependsOn` the otelcol sidecar with
`condition: START` (not `HEALTHY`) — `render_task_definition`, mod 024.
`START` does not block on a healthcheck, so the sidecar is **not** the
gate. (A `HEALTHY` condition would have been a real defect — it is not
present.)

### 5. ENI attachment / image pull — AWS-side baseline

Fargate awsvpc tasks attach an ENI and pull the image from ECR on every
new task; this is a fixed AWS-side cost (tens of seconds, NAT-routed
egress for the pull) that applies to both services and is not something
docex controls.

## Root-cause conclusion

The ~10–12 min web convergence is **expected ECS rolling-deployment
latency for a single-task, ALB-fronted, Service-Connect-injected Fargate
service**, dominated by: ALB health-check gating (~60 s to pass) +
default 300 s target deregistration/draining of the old task + Envoy/app
cold start, with a real risk that a missing `health_check_grace_period`
turns a slow cold start into one or more kill/restart cycles that extend
it further. It is **not** an otelcol `HEALTHY` gate and **not** a
docex dependency-ordering bug. Most of the time is AWS-side scheduling and
draining that docex hands off to ECS by design.

## Fix-vs-document recommendation (for the deferred follow-up)

This is **document-as-expected** for the 1.1.0 cut, with two *optional,
low-risk, docex-emitted* tunables worth a follow-up mod if the
convergence time is judged unacceptable:

1. **`health_check_grace_period_seconds`** on `aws_ecs_service` for
   web-network (target-group-bearing) services — e.g. 60–120 s. This is
   the highest-value, lowest-risk change: it prevents premature
   kill/restart of a slow-starting task and is the most likely single
   contributor to the worst-case 12 min. Safe, additive, no behavior
   change for healthy fast-start services.
2. **`deregistration_delay`** on `aws_lb_target_group` — lowering from the
   300 s default to e.g. 30–60 s would cut old-target draining on every
   rollout. Lower risk for the smoke project; for real prod it trades
   graceful-drain time, so it should be a tunable, not a blanket change.

`deployment_minimum_healthy_percent`/`maximum_percent` and `desired_count`
are left alone — single-task replica behavior is correct for the doctrine's
shape; raising max% only helps when `desired_count > 1`.

**Recommendation:** ship 1.1.0 documenting this as expected
rollback-convergence time; open a follow-up mod to add the
`health_check_grace_period_seconds` emit (item 1) and consider a tunable
`deregistration_delay` (item 2). Neither is required for the cut.

## Pointers (for the follow-up implementer)

- `src/docex/emit/hcl.py` — `render_ecs_service` (no grace period / deploy
  percentages today), `render_target_group` (no `deregistration_delay`),
  `render_task_definition` (otelcol `dependsOn: START`).
- `tables/roles/web.yml` — target-group `health_check` interval/thresholds.
- Next elastic re-walk: capture ECS service `events[]` timestamps and the
  task's `pullStartedAt`/`pullStoppedAt`/`startedAt` plus the target
  group's target-health transitions to attribute the minutes precisely
  (start→pull→running vs. ALB-healthy→old-drain). That data set will
  confirm which of items 1/2 above buys the most.

# Mod 128 — `stagetest` reads the orchestrator

Advance 006, phase 2, mod 4 of 9. The advance's only **additive** mod.

`./bin/docex stagetest` gains a foundation-aware liveness/version pre-step that
runs **before** the stage-tester image is built, reads every core service's
health and version **from the orchestrator**, and fails there if anything is
unhealthy, on the wrong version, **or unreadable**.

Rule of record: [`healthchecks.md § Version`](../../../../doctrine/infrastructure/healthchecks.md#version)
(the orchestrator wins), [`cicd.md § Staging Tests`](../../../../doctrine/infrastructure/cicd.md#staging-tests)
step 1, [`tests.md § Staging Tests`](../../../../doctrine/infrastructure/tests.md#staging-tests),
[`docex.md § stagetest`](../../../../doctrine/infrastructure/docex.md).

Closes advance 006 success criterion **2.5**.

---

## Baselines, re-derived

Measured at `d185054` (this branch, clean), not inherited. **The measurement
itself is a finding** — see [Design question 1](#design-question-1--twelve-red-tests-nobody-was-looking-at).

| Invocation | Result |
| --- | --- |
| `pytest tests/unit` | **1052 passed** — matches the figure the advance plan and my brief carry. |
| `pytest tests` (the default suite: everything not marked `integration`) | **1104 passed, 12 FAILED**, 18 deselected |
| `pytest tests -m integration` | **18 passed** (7m50s), run alone. |

A second finding for whoever runs these next: my first integration run reported
**5 failures** — docker DNS failures resolving `sample-dev-appdb`, and an unset
`POSTGRES_PASSWORD`. All five were contamination from other pytest processes I
had running at the same time. `pytest -m integration` brings up real compose
stacks and **must be run alone**; run concurrently it produces failures that look
like real defects in migrate, up/down, and build.

The 1052 figure is `tests/unit` **only**. `tests/integration/test_compile.py`
holds 61 tests of which exactly **one** carries `@pytest.mark.integration`; the
other 60 run in the default suite. Twelve of them are red, and have been since
mods 125/126 (and one since advance 005). Nobody saw it because the baseline was
being measured with a command that could not collect them.

---

## What the pre-step actually asserts

Per core service in the compiled `stage` env — **core services only**; backing
services are an engine concern
([`healthchecks.md § Backing services`](../../../../doctrine/infrastructure/healthchecks.md#backing-services))
and the `-otelcol` sidecar and `-exec` block are not core services:

| Foundation | Liveness | Version |
| --- | --- | --- |
| `fixed` | `docker inspect` `.State.Health.Status == healthy` **and** `.State.Status == running`, read **over SSH** to the deployed host | `.Config.Image`'s tag == `project.yml` version |
| `elastic` | every RUNNING task's `healthStatus == HEALTHY` and `lastStatus == RUNNING` | the task's own task-definition revision's app-container image tag == `project.yml` version |

**Probe output is never parsed.** Liveness is the orchestrator's aggregated
state; version is the deployment record. `healthchecks.md` is explicit that a
probe's stdout is captured by Docker and not by ECS, so it cannot be a
cross-foundation channel.

`stagetest` takes no env argument and is `stage` by construction. The pre-step
uses a module constant rather than growing a CLI flag; `docex stagetest <env>`
is not this mod's business.

---

## Shape

### New module: `src/docex/pipeline/orchestrator_health.py`

A deviation from the brief's file list — an addition, not a substitution.
`stagetest.py` is 117 lines of "build an image, run it"; this is ~200 lines of
"interrogate two orchestrators through two transports." Three reasons to give it
its own file rather than triple the size of `stagetest.py`:

1. It is a distinct doctrine concern with its own rule of record (`healthchecks.md`),
   and it will be the natural home for the same read if another command ever needs it.
2. It is the **only** place in `docex` where the AWS and SSH transports meet in one
   function. Burying that in a build-and-run module hides the fact.
3. It gives the tests one obvious target file instead of appending 25 cases to
   `test_pipeline_stagetest.py`.

Public surface, one function:

```python
def assert_deployed_healthy(
    ctx: ProjectContext, *, env: str,
    aws: AWSClient | None, ssh: SSHClient | None,
) -> None:
```

Raises on any failure; returns `None` and prints a per-service verdict line on
success. **It has no boolean that turns it off** — see
[The gate has no off switch](#the-gate-has-no-off-switch).

Foundation dispatch is **exhaustive**: `fixed`, `elastic`, `else: raise`. A
foundation the pre-step does not recognise must not fall through to "checked
nothing, all good" — that is the silent-skip shape this whole mod is a reaction to.

### Two error types, not one

```python
class DeployedServiceUnhealthy(DocexError)      # the honest answer: it is not healthy / not this version
class OrchestratorStateUnreadable(DocexError)   # docex could not find out
```

Both abort `stagetest` before the tester builds. They are separated because the
operator's next move differs — "the release is bad" vs. "the question was never
answered" — and because the tests for criterion 2.5 need to assert *which* class
fired. A single type would let a can't-answer bug pass a test written for the
honest failure.

### Fixed: `docker inspect` over SSH

On `fixed`, `stage`/`prod` containers **do not run on the operator's machine**.
`_release_fixed` deploys via ansible over SSH to `aggregate._host_for(ctx, env)`
(`<env>.<dns_label(project)>.<apex_domain>`), and `DockerClient` has no
container-inspect method at all — `compose_ps_status` flattens health into a
coarse string and wants a local compose file. So the read goes through
`SSHClient.capture`, following the precedent at `aggregate.py:141`.

One `capture` per container, not one batched call: a batched `docker inspect`
returns partial output plus rc 1 and gives no way to attribute the failure to a
container. N is small (three core services in both seeds).

```
sudo docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}NOHEALTH{{end}}|{{.State.Status}}|{{.Config.Image}}' <container_name>
```

- **`sudo`** for the same reason `aggregate.py` uses it: the playbook runs
  `become: true`, so containers are root-owned, and the `deploy` user has
  passwordless sudo.
- **Deliberately *not* `2>/dev/null || true`.** That is what the precedent I am
  copying does, and copying it here would be the bug. On the TTE read an
  unreadable store must degrade to "empty"; here an unreadable container must
  degrade to **failure**. Called out in a `WHY` comment at the call site so the
  next reader does not "fix" the inconsistency.
- **The `NOHEALTH` sentinel** exists because `{{.State.Health.Status}}` against a
  container whose image declares no healthcheck is a nil-pointer template error.
  An error would fail loudly by accident; the sentinel fails loudly *on purpose*,
  with the right diagnosis ("this image declares no healthcheck — is it a
  pre-1.7.0 image?").

Container names are addressable: `compile.py:1181` sets
`container_name = global_service_name`, and the replica unroll
(`compose.py:485`) suffixes `-<i>` when `effective_replicas > 1`. The pre-step
enumerates replica names via `effective_replicas(svc, env)` rather than assuming
one — on `stage` the prod-only clamp makes it 1, but computing it beats relying
on a clamp that lives in another module.

The deploy key at `infra/deploy_creds/<env>` is required, checked before any
SSH, with the same message shape `_release_fixed` uses.

### Elastic: two new `AWSClient` methods

`AWSClient` has no `describe_tasks`, `list_tasks`, or
`describe_task_definition`. `ecs_wait_for_task` calls `describe_tasks`
*internally* against one known ARN and returns an exit code — nothing reusable.

```python
def ecs_service_tasks(self, cluster: str, service: str) -> list[dict[str, str]]:
    """RUNNING tasks of `service`, each as
    {task_arn, last_status, health_status, task_definition}."""

def ecs_task_definition_images(self, task_definition: str) -> dict[str, str]:
    """container name -> image ref for one task-definition ARN or family:revision."""
```

Implementation: `list_tasks(cluster, serviceName, desiredStatus='RUNNING')` then
`describe_tasks` (chunked at 100, boto3's cap); `describe_task_definition`.
`health_status` normalises a missing key to ECS's own `"UNKNOWN"` rather than `""`,
so the caller's message stays honest.

**The contract that matters, and it is the inverse of the neighbouring method.**
`ecs_primary_deployment_times` *deliberately* swallows `ClusterNotFoundException`
and reports absent services as absent, because there its caller reads absence as
"redeploy" — the safe direction. Here the safe direction is the opposite: an
unreadable cluster, an absent service, or a deregistered revision must **raise**.
Both docstrings will say so and will name each other, because the drift risk is a
future reader copying the swallow into the wrong method.

The ECS service name is `svc.global_name`; the app container inside the task
definition is named `svc.name` (the two-segment compiled identity) — see
`hcl.py:740` and the emitted `name = "api-clock"` in the seeds' `main.tf`.

**Task-level `healthStatus` is the right field**, not per-container: ECS
aggregates it over containers that declare a health check, and after mod 127 the
`-otelcol` sidecar declares none, so the task's status reflects the app container
alone. If *no* container declares one, ECS reports `UNKNOWN` — which is the
elastic twin of `NOHEALTH` and fails for the same reason.

**No `describe_services` call, and why.** The obvious extra check is
`runningCount == desiredCount`. On `stage`, `effective_replicas` clamps every
core service to 1, so the only reachable shortfall is zero tasks — which
`ecs_service_tasks` returning `[]` already catches, loudly. Adding a third AWS
call to detect a state `stage` cannot be in is cost without coverage. Recorded
rather than silently omitted.

### The cluster-name helper

`apply_policy(f"{project}_{env}", naming_policies["ecs"])` appears verbatim at
`release.py:591` and `orchestrate/migrate.py:246`. A third copy is a drift
surface at the worst possible moment, so it is lifted:

```python
# src/docex/naming.py
def ecs_cluster_name(project_name: str, env: str, policies: NamingPolicies) -> str:
```

`naming.py` because both `NamingPolicy` and `NamingPolicies` are already defined
there and `apply_policy` is already its single translation entry point — the
helper adds **zero new imports** and creates no cycle (taking primitives rather
than a `ProjectContext` is what buys that). Both existing call sites are
rewritten to use it. Its docstring carries forward mod 109's load-bearing note
that the env's Service Connect namespace shares this exact name, so that fact
does not stay stranded in a `release.py` comment.

Precedent: `CURRENT_CICL_VERSION`, per `compiler.md`.

### Wiring

`__main__::_cmd_stagetest` threads `aws` and `ssh` exactly as `_cmd_release`
already does — both are cheap, offline constructions.

`run_stagetest` gains keyword-only `aws` and `ssh`. When the pre-step's required
transport is `None` for the dispatched foundation, that is an **internal dispatch
bug** and raises, mirroring `run_release`'s handling. It never degrades to a skip.

---

## The gate has no off switch

`tests/integration/test_stagetest_real.py` runs `stagetest` against a **local dev
stack standing in for a deployed stage env**. The pre-step would try to SSH to
`stage.sample.example.com`, which does not exist.

The tempting fix is `skip_orchestrator_check=True`. **Rejected.** A parameter
whose only function is to disable a health gate is the precise artifact advance
005 found eight times — and once it exists in the signature, the next caller in a
hurry uses it. Instead:

- The integration test injects a scripted `FakeSSHClient` and writes a dummy
  `infra/deploy_creds/stage` file. The pre-step **runs**, against a fake host,
  and the test's real subject (build the tester image, run it over a docker
  network, propagate the exit code) is untouched.
- `FakeSSHClient` gains `capture_results: dict[str, str]` (command-substring →
  stdout) so a test can script per-container answers; `capture_out` stays as the
  uniform fallback, so no existing caller changes.

The SSH path is therefore **not** exercised against a real remote host anywhere
in the suite. That is deliberate and is stated here so it is not mistaken for
coverage: the real exercise is this advance's smoke walk.

---

## Every way this step could fail to be able to answer

Advance 005's standing lesson, from `test_projects.md`: *a verification step's
pass is worthless until the step has been observed failing.* That advance found
**eight** instances of "something that could not answer reported zero, and zero
read as clean" — including a `verify_clean.sh` that printed `OK` on expired
credentials while certifying an account had stopped billing.

This mod is a gate whose entire purpose is to answer "is the deployed thing
healthy?", so it is in exactly that category. Each row below gets a unit test
that asserts the **specific** error type and a message fragment. `U` = the honest
"it is unhealthy / wrong version" answer; everything else is a can't-answer mode.

| # | Mode | Verdict | Reachable? |
| --- | --- | --- | --- |
| **Both foundations** | | | |
| 1 | Compiled `stage` env has **zero core services** | `OrchestratorStateUnreadable` — "nothing was checked" is not "all healthy" | **Yes.** `test_project_tier_task_execution_policy_empty_core_services` compiles exactly such a project. I assumed this was unreachable until the baseline proved otherwise. |
| 2 | Foundation is neither `fixed` nor `elastic` | raise (exhaustive dispatch) | No — `foundation` is schema-validated. Guarded anyway: a fall-through `else` is a silent pass. |
| 3 | Required transport is `None` for the dispatched foundation | raise, "internal dispatch bug" | Only via a wiring regression. That is what it is there to catch. |
| **Elastic** | | | |
| 4 | No AWS credentials | `AWSCredentialsMissing` propagates | Yes — expired SSO session is routine. This is verify_clean.sh's exact failure. |
| 5 | ECS cluster absent | `OrchestratorStateUnreadable` | Yes — wrong profile/region, or an env never released. |
| 6 | ECS service absent from the cluster | `OrchestratorStateUnreadable` | Yes — a service renamed or removed by a compile the release never applied. |
| 7 | Service exists, **zero RUNNING tasks** | `DeployedServiceUnhealthy` | Yes. **The central trap:** an empty result set must never read as "all healthy". |
| 8 | `describe_tasks` returns no record for a listed ARN (or reports it under `failures`) | **one bounded re-read, then** `OrchestratorStateUnreadable`, naming the ARN and saying the set was *still* inconsistent | Yes — a task can stop between `list_tasks` and `describe_tasks`. See [the bounded re-read](#the-bounded-re-read-mode-8). |
| 9 | Task `healthStatus` is `UNKNOWN` / absent | `OrchestratorStateUnreadable`, diagnosed as "no container in this task declares a health check" | Yes — a pre-1.7.0 task definition, i.e. precisely the upgrade this advance ships. |
| 10 | Task `healthStatus: UNHEALTHY` (or anything else), or `lastStatus != RUNNING` | `DeployedServiceUnhealthy` | **U** |
| 11 | `describe_task_definition` raises (revision deregistered, throttled, denied) | `OrchestratorStateUnreadable` | Yes. Must never be read as "assume the version is right". |
| 12 | Revision read, but no container named `svc.name` in it | `OrchestratorStateUnreadable` | No — the emitter always names it `svc.name`. Guarded because "version unreadable" silently becoming "version correct" is the failure this whole mod exists to prevent, and the guard is one line. |
| 13 | Image ref carries no readable tag (digest-pinned, or no `:`) | `OrchestratorStateUnreadable` | No — `_image_ref` never digest-pins a core-service image (only the otelcol sidecar is pinned, and it is not checked). Guarded for the same one-line reason. |
| 14 | Image tag != `project.yml` version | `DeployedServiceUnhealthy` | **U** |
| **Fixed** | | | |
| 15 | `infra/deploy_creds/<env>` missing | `OrchestratorStateUnreadable`, before any SSH | Yes. |
| 16 | SSH rc 255 — host unreachable / auth refused | `OrchestratorStateUnreadable`, "cannot reach host" | Yes. |
| 17 | `docker inspect` rc non-zero — container absent, daemon down, sudo denied | `OrchestratorStateUnreadable`, quoting the remote output | Yes. |
| 18 | rc 0 but stdout empty, or not three `\|`-separated fields | `OrchestratorStateUnreadable` | Yes, if the format string or the remote docker version drifts. **This is the "could not answer, returned nothing, nothing read as clean" case made explicit.** |
| 19 | `NOHEALTH` — `.State.Health` absent | `OrchestratorStateUnreadable`, diagnosed as a pre-probe image | Yes — same upgrade scenario as #9. |
| 20 | Health `starting` | `DeployedServiceUnhealthy`, with its own message | Yes — probing during the start period. |
| 21 | Health is anything else, or `.State.Status != running` | `DeployedServiceUnhealthy` | **U** |
| 22 | Image tag mismatch / unreadable | as #13 / #14 | **U** / no |

**Genuinely unreachable, and guarded anyway:** #2, #12, #13. Each is a one-line
guard whose absence converts an unanswerable question into a green light.

**#1 was reclassified from unreachable to reachable by measurement, not by
reasoning.** I argued it was impossible — `domain_default_service` must name a
core service, so surely one exists — and then a baseline run surfaced
`test_project_tier_task_execution_policy_empty_core_services`, which compiles a
project with zero core services on purpose. The guard stays, and this paragraph
stays with it: a reader who finds a guard on an "impossible" path deserves to know
it was once thought impossible and that running something is what changed the
verdict.

### The bounded re-read (mode #8)

Operator ruling at design review, overriding my no-retry default. When the task
set shrinks between `list_tasks` and `describe_tasks`, the pre-step performs
**one** re-read after a short fixed delay, then fails.

The reasoning that makes this not the off switch I was right to be wary of: what
advance 005 condemned was a check that **reported OK when it could not answer**. A
re-read that exhausts and then *fails, loudly, with a message* does not do that.
What would be forbidden is a loop that concludes "probably fine." And the reason
to spend the re-read at all is that ECS replaces tasks on its own schedule —
scaling, AZ rebalance, platform updates — so a single unlucky replacement during a
read is not evidence about the release. The subject of judgement is the
**service**, not the identity of the tasks we happened to list.

The constraints, each of which is a test:

1. **One re-read, not a poll loop.** Fixed delay, not configurable, no parameter
   on any public function.
2. **The message distinguishes the two failures.** "The task set was still
   inconsistent after a re-read" is `OrchestratorStateUnreadable`; "a service is
   unhealthy" is `DeployedServiceUnhealthy`. The re-read is one more caller of the
   split, not a third category.
3. **The re-read cannot mask an unhealthy service.** An unhealthy service fails on
   *both* reads and is reported as **unhealthy** — never as inconsistent. This is
   the test that keeps the retry honest, and it is the reason the re-read is
   scoped to *a shrinking task set* rather than to "any failure."

Precedent that this race is real here rather than hypothetical:
`ecs_wait_for_task` already carries a 30-second consistency window for the same
class of eventual consistency.

**Not covered, deliberately:** backing-service health (engine concern), the
`-otelcol` sidecar and `-exec` block (not core services), `runningCount` vs.
`desiredCount` (unreachable on `stage`, see above), and public reachability
(that is step 2 of `cicd.md`'s process and the stage tests' own job — container
health and public reachability are different claims).

---

## Tests

- **`tests/unit/test_orchestrator_health.py`** — new. One test per row above,
  each asserting error type + message fragment. Both foundations' happy paths.
- **`tests/unit/test_pipeline_stagetest.py`** — the 7 existing tests all assert
  on `fake_docker.calls` by **positional tuple index** (`run_call[3]`, `[4]`,
  `[5]`) and break on any signature change. Rewritten onto a small
  `_run_one_shot_call(fake_docker) -> dict` helper that names the fields. Plus:
  the pre-step runs **before** `build_image`, and a failing pre-step means
  `build_image` is never called at all.
- **`tests/unit/test_naming.py`** — `ecs_cluster_name` against the real `ecs`
  policy; both former call sites produce the identical string.
- **`tests/conftest.py`** — `FakeAWSClient` gains the two methods with scriptable
  results *and* scriptable raises; `FakeSSHClient` gains `capture_results`.
- **`tests/integration/test_stagetest_real.py`** — scripted `FakeSSHClient` +
  dummy deploy key, per above. No new test requiring real AWS or a real remote
  host.

The implementor is instructed to **run each new red test and confirm it fails for
the intended reason** — a `TypeError` from a mis-built fake also produces a red
test and proves nothing.

---

## Resolved decisions

Both were raised at design review and ruled by the operator. Recorded rather than
deleted, because each rules out an alternative a fresh context would re-propose.

1. **The twelve red tests are fixed in this mod** — as **rule-33 conformance, not
   test suppression.** The ten rule-33 failures are inline `infra.yml` documents
   that predate rule 33 and are now simply invalid CICL; they are corrected to be
   valid. If any of the twelve tempted the fix toward *loosening a rule*, that
   would be the tail wagging the dog and is grounds to stop and escalate.
   The structural root cause outlives the fix and is written up as
   [`007_small_edges/misfiled_compile_tests.md`](../../advances/007_small_edges/misfiled_compile_tests.md).
2. **Mode #8 gets a bounded re-read, fail-closed** — see
   [The bounded re-read](#the-bounded-re-read-mode-8). My default was no retry;
   overridden with reasoning I accept.

**Standing instruction adopted for the rest of advance 006:** the default suite is
`pytest tests`, not `pytest tests/unit`; the expensive suite is
`pytest tests -m integration`, run **alone**.

**Not to be added later under pressure from the walk:** `skip_orchestrator_check`,
or any equivalent. If the walk hurts, the gate is telling us something.

## Design questions

Both are now answered above; the analysis is retained because it is the argument,
not just the verdict.

### Design question 1 — twelve red tests nobody was looking at

**`pytest tests` is red at `d185054`: 12 failures, all in
`tests/integration/test_compile.py`.** Outside my declared territory, so it is
yours to rule on. Causes, all mechanical:

| Count | Cause | Fix |
| --- | --- | --- |
| 10 | Two inline `infra.yml` strings (`_SECRET_INFRA`, `_NAMING_INFRA`) have a `web`-network core service with no `health_check_path` → **mod 125's rule 33**. | add `health_check_path: /health` to each (2 lines) |
| 1 | `test_project_tier_task_execution_policy_empty_core_services` pins `cicl_version: "2"`. | → `"3"` |
| 1 | `test_describe_dag_and_llm` asserts `"depends_on" in out` — **advance 005** retired the field. | retarget the assertion at the surviving `uses` output |

The finding under the finding: **the baseline number in the advance plan, in my
brief, and in mods 125–127's reports is `tests/unit` only**, and
`tests/integration/test_compile.py` puts 60 unmarked tests in the default suite
where that command cannot see them. A green `tests/unit` has been reported as a
green suite three times while twelve tests were red. This is advance 005's own
lesson arriving in the *measurement apparatus* rather than in the code — a
verification step that could not see the thing reported clean.

**My recommendation: fold the four-line fix into this mod**, because (a) it is
mechanical and touches no behavior, (b) I cannot honestly report "suite green"
otherwise, and (c) the alternative is a 128b whose entire content is four lines.
**And separately: every remaining mod in this advance should be told to measure
`pytest tests`, not `pytest tests/unit`.** That instruction is worth more than
the fix.

I have not touched the file. Say the word and it lands here; say otherwise and I
report the 12 as a known pre-existing red and carry on.

### Design question 2 — is a spurious red acceptable on mode #8? (ruled: bounded re-read)

A task that stops between `list_tasks` and `describe_tasks` (ECS eventual
consistency; `ecs_wait_for_task` already carries a 30s tolerance window for
exactly this) makes the pre-step fail on a healthy env. I have chosen to
**fail rather than retry**, on the grounds that this gate's entire value is that
it never reports clean when it cannot answer, and a re-run is cheap.

The alternative is to borrow `ecs_wait_for_task`'s consistency window and retry
for 30s. That is more pleasant and strictly more code, and it introduces the one
thing I would rather not introduce into a can't-answer gate: a loop that can
decide to stop worrying. **Flagging rather than deciding, because "stagetest
occasionally red on a good release" is an operator-experience call and the smoke
walk is where you would feel it.** My default, absent a ruling, is no retry.

---

## Recorded limitations

Neither is a defect to fix here. Both are properties a reader should find written
down rather than discover during an incident.

### `.Config.Image` proves the ref, not the bytes

`docker inspect` on `fixed` reads `.Config.Image` — the image ref as given at
container creation. That is the deployment record in the same sense a
task-definition revision is, and `healthchecks.md § Version` says "the image ref on
`fixed`", so this is faithful. **Accepted as-is by operator ruling; deliberately
not strengthened.**

But it does *not* prove the container is running the bytes that tag currently
points at: `registry/api:0.0.19` could have been re-pushed. Docker's `.Image` (the
resolved digest) would prove that, and nothing in the project records an expected
digest to compare against, so there is no check available to write. This is the
one place the `fixed` and `elastic` answers are not equally strong.

### The SSH path is not exercised against a real host anywhere in the suite

By construction — see [The gate has no off switch](#the-gate-has-no-off-switch).
Every test of the fixed path runs against a scripted `FakeSSHClient`.

**The consequence: the fixed smoke walk's `stagetest` box is this code's first
real execution.** Not "one of many" — the first. It should be watched rather than
assumed, and a failure there is as likely to be in the SSH plumbing or the
`--format` string as in the deployed env. Recorded here and in this mod's report;
the operator is carrying it into the walk plan as well.

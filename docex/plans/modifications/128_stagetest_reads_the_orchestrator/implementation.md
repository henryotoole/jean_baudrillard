# Mod 128 — implementation steps

Design: [`overview.md`](./overview.md). Read it first — in particular
§ *Every way this step could fail to be able to answer* (the 22-row table), which
is the specification for step 6's tests, and § *The bounded re-read (mode #8)*.

Repo: `/home/ubuntu/.claude/jean_baudrillard/docex`. Branch
`006_surfaces_and_health`. Python: use `.venv/bin/python` — there is no bare
`python` on this machine.

**Suite invocations for this mod** (operator standing instruction — do not
substitute `pytest tests/unit`, which has a 60-test blind spot):

```
.venv/bin/python -m pytest tests -q                  # default suite
.venv/bin/python -m pytest tests -m integration -q   # expensive suite — RUN ALONE, nothing else touching docker
```

Baselines at `d185054`: `pytest tests` → **1104 passed, 12 failed**;
`pytest tests -m integration` → **18 passed**. Step 1 makes the 12 green;
everything after must keep them green.

---

## Step 1 — Fix the twelve pre-existing failures

File: `tests/integration/test_compile.py`. **These are conformance fixes, not
suppressions.** If any of them tempts you toward loosening a validation rule or
adding a skip/xfail, **stop and report it** — that would be the tail wagging the
dog, and the operator asked to be told.

1. In the `_SECRET_INFRA` document, the `api.web` core service is on the `web`
   network and declares no `health_check_path`. Mod 125's rule 33 requires it.
   Add `health_check_path: /health` beside its `port: 8080`.
2. In the `_NAMING_INFRA` document, the `web.http` core service has the same
   defect. Add `health_check_path: /health` beside its `port: 8080`.
3. `test_project_tier_task_execution_policy_empty_core_services` builds an inline
   document pinning `cicl_version: "2"`. The current generation is `"3"`. Change
   it to `"3"`. (Do **not** touch `CURRENT_CICL_VERSION` in `src/`.)
4. `test_describe_dag_and_llm` asserts `"depends_on" in out`. That field was
   retired in 1.7.0 (advance 005) — `CompiledService.uses` is the one surviving
   relation. Read what `docex describe` actually emits now (the failure output
   shows it ends with an `uses edges (backing target) — solid:` section) and
   retarget the assertion at the surviving `uses` output. Do not delete the
   assertion — the test exists to prove the DAG description names the edges.

Verify: `.venv/bin/python -m pytest tests/integration/test_compile.py -q` → 61
passed. Then `pytest tests` → **1116 passed, 0 failed**. Record that number; it is
the true pre-mod baseline for everything below.

---

## Step 2 — `src/docex/naming.py`: the cluster-name helper

Add, after `apply_policy`:

```python
def ecs_cluster_name(project_name: str, env: str, policies: NamingPolicies) -> str:
```

Body: `apply_policy(f"{project_name}_{env}", policies.get("ecs"))`.

Docstring must carry these two facts, both currently stranded in comments
elsewhere:

- This is the ECS cluster's name **and** the env's Service Connect namespace name
  — they are deliberately the same string (mod 109), so one expression serves
  both and the two cannot drift apart.
- Lifted from two verbatim copies at `release.py:591` and
  `orchestrate/migrate.py:246` when mod 128 would have made a third. Same reason
  `CURRENT_CICL_VERSION` is a constant (see `plans/core/compiler.md`).

Takes primitives rather than a `ProjectContext` **on purpose**: `naming.py` is a
low-level module and importing `docex.context` would create a cycle. Confirm the
new function adds no `import` line to the file.

Rewrite both existing call sites to call it, deleting their local
`ecs_policy = ...` / `apply_policy(...)` pairs but **keeping** the surrounding
`WHY` comments (release.py's note about computing it ahead of the
`skip_migrations` return is still load-bearing).

Test in `tests/unit/test_naming.py`: `ecs_cluster_name` against the real loaded
`ecs` policy produces the hyphenated `<project>-<env>` form, including for an
underscored project name (`docex_smoke_elastic` → `docex-smoke-elastic-stage`).

---

## Step 3 — `src/docex/errors.py`: two new error types

Add after `StageTesterBuildFailed`:

```python
class DeployedServiceUnhealthy(DocexError):
class OrchestratorStateUnreadable(DocexError):
```

Docstrings must state the split and *why it is two types and not one*: the first
is the orchestrator's honest answer (a service is not healthy, or is not on this
version); the second is docex being unable to obtain an answer at all. The
operator's next move differs, and — the load-bearing reason — keeping them
separate makes "the gate broke" untypeable as "the env is fine." Cross-reference
`healthchecks.md § Version` and this mod.

---

## Step 4 — `src/docex/aws/`: three new methods

### 4a. `src/docex/aws/client.py` — Protocol

Add a new section, `# Mod 128: stagetest's orchestrator liveness/version read.`

```python
def ecs_list_service_task_arns(self, cluster: str, service: str) -> list[str]:
def ecs_describe_tasks(self, cluster: str, task_arns: list[str]) -> list[dict[str, str]]:
def ecs_task_definition_images(self, task_definition: str) -> dict[str, str]:
```

Docstring contracts — these are the important part of this step, because they are
the **inverse** of the neighbouring method's contract:

- `ecs_list_service_task_arns` — task ARNs of `service` with
  `desiredStatus=RUNNING`. **Raises** when the cluster does not exist, when the
  service does not exist, or when credentials are absent. An empty list means the
  service exists and genuinely has no running tasks — a real, checkable fact, not
  an error. **Contrast `ecs_primary_deployment_times`, immediately above, which
  deliberately swallows `ClusterNotFoundException` and reports absent services as
  absent** — there absence means "redeploy", which is that caller's safe
  direction. Here the safe direction is the opposite: an unreadable service must
  never be indistinguishable from a healthy one. Name that method explicitly so
  a future reader cannot copy the swallow into this one by mistake.
- `ecs_describe_tasks` — one dict per task **ECS returned**, with keys
  `task_arn`, `last_status`, `health_status`, `task_definition`. Missing
  `healthStatus` normalises to ECS's own `"UNKNOWN"`, never `""`. Accepts any
  number of ARNs; `DescribeTasks` caps at 100 and chunking is the
  implementation's business. **A task ECS does not return (or reports under
  `failures`) is simply absent from the result, and that is deliberate**: it is
  how the shrinking-task-set race becomes *visible* to the caller. The caller
  MUST compare the returned count against the requested count and treat a
  shortfall as unreadable state — the policy for that lives in
  `orchestrator_health.py`, not here, because the adapter should report what AWS
  said and not decide what it means.
- `ecs_task_definition_images` — container name → image ref, for a task-definition
  ARN or `family:revision`. **Raises** if the revision cannot be read (deregistered,
  throttled, denied). An unreadable revision must never be reported as an empty
  mapping, because an empty mapping would read downstream as "no container to
  check."

### 4b. `src/docex/aws/boto3_client.py` — implementation

- `ecs_list_service_task_arns`: `list_tasks` via paginator (mirror
  `service_connect_endpoints`'s paginator use), `cluster=`, `serviceName=`,
  `desiredStatus="RUNNING"`. Let `ClusterNotFoundException` /
  `ServiceNotFoundException` propagate — do **not** catch them.
- `ecs_describe_tasks`: chunk at 100, `describe_tasks(cluster=..., tasks=chunk)`,
  read `taskArn`, `lastStatus`, `healthStatus` (default `"UNKNOWN"`),
  `taskDefinitionArn`. Return `[]` for an empty input list without calling AWS.
- `ecs_task_definition_images`: `describe_task_definition(taskDefinition=...)`,
  return `{c["name"]: c["image"] for c in ...["containerDefinitions"]}`.

### 4c. `tests/conftest.py` — `FakeAWSClient`

Follow the existing `_record(...)` + scriptable-field pattern exactly (`_record`
already honours `raise_on`, which is how the can't-answer tests script raises).
New fields:

```python
ecs_service_task_arns: dict[str, list[str]] = field(default_factory=dict)   # service -> arns
ecs_task_records: dict[str, dict[str, str]] = field(default_factory=dict)   # arn -> record
ecs_task_definition_images_results: dict[str, dict[str, str]] = field(default_factory=dict)
```

Behaviour:
- `ecs_list_service_task_arns` returns `ecs_service_task_arns.get(service, [])`.
- `ecs_describe_tasks` returns a record for each requested ARN **present in**
  `ecs_task_records`, and silently omits the rest — this is what lets a test model
  the shrinking-task-set race by listing an ARN that has no record.
- `ecs_task_definition_images` returns
  `ecs_task_definition_images_results.get(task_definition, {})`.

Defaults are all empty, i.e. "nothing is deployed" — which every new test must
script its way out of. Do **not** make the defaults a healthy env: a fake whose
default is green is the same defect this mod is about, one layer down.

---

## Step 5 — `src/docex/pipeline/orchestrator_health.py` (new)

Module docstring: what this is, and that it implements `cicd.md § Staging Tests`
step 1 with `healthchecks.md § Version` as the rule of record. State plainly that
**probe output is never parsed** and why (Docker captures healthcheck stdout, ECS
surfaces only a status, so anything read from it would work on one foundation and
silently not on the other).

### Public surface — exactly one function

```python
def assert_deployed_healthy(
    ctx: ProjectContext, *, env: str,
    aws: AWSClient | None, ssh: SSHClient | None,
) -> None:
```

Returns `None` on success; raises `DeployedServiceUnhealthy` or
`OrchestratorStateUnreadable` otherwise. **It takes no flag that disables it and
must never grow one** (overview § *The gate has no off switch*).

### Body

1. `compile_env(ctx.infra, ctx.transfer_tables, env=env, project_name=ctx.project.name, project_version=ctx.project.version)` — same call shape as `release.py:409`.
2. `cores = [s for s in compiled.services.values() if s.is_core]`, sorted by
   `name` for deterministic output.
3. **If `cores` is empty → raise `OrchestratorStateUnreadable`** (table row #1).
   Message: nothing was checked, and an empty check set is not a healthy env.
   *A test in `test_compile.py` compiles exactly such a project, so this is
   reachable, not theoretical — say so in a `WHY` comment.*
4. Dispatch on `compiled.foundation`: `fixed` → `_check_fixed`, `elastic` →
   `_check_elastic`, **`else` → raise** `OrchestratorStateUnreadable`. The
   dispatch must be exhaustive; a fall-through that returns normally is a silent
   pass (row #2).
5. Missing transport for the dispatched foundation (`ssh is None` on fixed,
   `aws is None` on elastic) → raise, worded as an internal dispatch bug, mirroring
   `run_release`'s handling of the same condition (row #3). Never a skip.
6. On success print a summary that names the counts:
   `stagetest: orchestrator pre-step passed — <n> core service(s), <m> instance(s) healthy on version <v>.`
   The counts are there so a zero would be visible in a log even if a guard were
   ever removed — same reasoning as `release.py`'s "every no-fire path says which
   one it was."

### `_check_fixed(compiled, ctx, env, ssh)`

- Deploy key: `ctx.project_root / "infra" / "deploy_creds" / env`. Missing → raise
  `OrchestratorStateUnreadable` with the message shape `_release_fixed` uses
  (relative path + "see credentials.md § Deploy Credentials"). Before any SSH
  (row #15).
- Host: **`compiled.subdomain`**. Do not re-derive it and do not import
  `aggregate._host_for`; `_env_subdomain` produces byte-identical output
  (`<env>.<dns_label(project)>.<apex>`) and `CompiledEnv` already carries it.
- Per core service, per replica: names come from `effective_replicas(svc, env)`
  (import from `docex.cicl.compile`) — a single instance is `svc.global_name`;
  `n > 1` gives `f"{svc.global_name}-{i}"` for `i` in `1..n`, matching
  `compose.py:485`. Compute it; do not assume the prod-only clamp.
- The command, exactly:

```python
_INSPECT_FORMAT = (
    "{{if .State.Health}}{{.State.Health.Status}}{{else}}NOHEALTH{{end}}"
    "|{{.State.Status}}|{{.Config.Image}}"
)
cmd = f"sudo docker inspect --format '{_INSPECT_FORMAT}' {container}"
rc, out = ssh.capture(host, key, cmd)
```

  Two `WHY` comments are mandatory here:
  - **`sudo`**: the playbook runs `become: true`, so containers are root-owned;
    the `deploy` user has passwordless sudo (`release_mechanism.md § Fixed
    Foundation: Ansible`). Same reasoning as `aggregate.py:141`.
  - **No `2>/dev/null || true`** — and this one must be emphatic, because the
    precedent at `aggregate.py:141` *does* carry it and a future reader will want
    to make the two consistent. There, an unreadable TTE store must degrade to
    "empty" or docex re-mints and locks the host out of its own credentials. Here,
    an unreadable container must degrade to **failure**. Masking it is precisely
    the defect this mod exists to prevent.
  - The **`NOHEALTH` sentinel**: `{{.State.Health.Status}}` against a container
    whose image declares no healthcheck is a nil-pointer template error. An error
    would fail loudly by accident; the sentinel fails loudly on purpose, with the
    right diagnosis.
- Verdicts, in this order:
  - `rc == 255` → `OrchestratorStateUnreadable`, "cannot reach host" (row #16).
    Check 255 **before** the generic non-zero branch.
  - `rc != 0` → `OrchestratorStateUnreadable`, quoting the captured output, and
    listing the plausible causes (container absent, docker daemon down, sudo
    denied) (row #17).
  - `out.strip()` empty, or `split("|")` does not yield exactly 3 non-empty
    fields → `OrchestratorStateUnreadable` quoting the raw output (row #18).
    **This is the "could not answer, returned nothing, nothing read as clean"
    case; comment it as such.**
  - `health == "NOHEALTH"` → `OrchestratorStateUnreadable`, diagnosed as an image
    that declares no healthcheck, naming a pre-1.7.0 image as the likely cause
    (row #19).
  - `health == "starting"` → `DeployedServiceUnhealthy`, its own message (still
    inside the start period) (row #20).
  - `health != "healthy"` or `state != "running"` → `DeployedServiceUnhealthy`
    (row #21).
  - version: `_version_from_image_ref(image)` (below) vs `ctx.project.version`.

### `_check_elastic(compiled, ctx, env, aws)`

- `cluster = ecs_cluster_name(ctx.project.name, env, ctx.transfer_tables.naming_policies)`.
- Per core service (ECS service name is `svc.global_name`):
  - `arns = aws.ecs_list_service_task_arns(cluster, svc.global_name)`. Let
    `AWSCredentialsMissing` and the ECS not-found exceptions propagate — they are
    already loud `DocexError`s / boto3 errors and rows #4/#5/#6 are satisfied by
    *not catching them*. Add a comment saying the absence of a `try` here is the
    deliberate implementation of those three rows, so nobody adds one.
  - `arns == []` → `DeployedServiceUnhealthy`: the service exists and has no
    running tasks (row #7). Comment: **this is the central empty-set trap** — an
    empty task list must never read as "all healthy".
  - `records = aws.ecs_describe_tasks(cluster, arns)`.
  - **The bounded re-read (row #8).** If `len(records) < len(arns)`: sleep
    `_TASK_SET_REREAD_DELAY_S` (module constant, `2.0`) and redo **both** calls
    once — `list_tasks` *and* `describe_tasks`, because the truthful question on
    the second pass is "what tasks does this service have *now*", not "where did
    that one ARN go". If the second pass is still short → raise
    `OrchestratorStateUnreadable` naming the missing ARN(s) and stating that the
    task set was **still inconsistent after a re-read**. Constraints, all three of
    which are tested in step 6:
    1. **One re-read, not a loop.** No parameter, not configurable. The constant
       exists so the tests can monkeypatch it to `0` rather than actually sleep.
    2. The message must be distinguishable from the unhealthy-service message.
    3. **The re-read is scoped to a *shrinking task set* only** — never to a task
       that was returned and reported unhealthy. That scoping is what makes it
       structurally unable to mask an unhealthy service, and it is why the retry
       is honest. Write that reasoning into the comment.
  - Per record: `last_status != "RUNNING"` or `health_status == "UNHEALTHY"` (or
    anything other than `"HEALTHY"` that is not `"UNKNOWN"`) →
    `DeployedServiceUnhealthy` (row #10).
  - `health_status == "UNKNOWN"` → `OrchestratorStateUnreadable`, diagnosed as
    "no container in this task declares a health check", naming a pre-1.7.0 task
    definition as the likely cause (row #9). Note this is the elastic twin of
    `NOHEALTH` and cross-reference it.
  - version: `images = aws.ecs_task_definition_images(record["task_definition"])`.
    Let a raise propagate (row #11). `svc.name not in images` →
    `OrchestratorStateUnreadable` (row #12). Then `_version_from_image_ref`.
- **Do not add a `describe_services` call.** The `runningCount` vs `desiredCount`
  check it would enable is unreachable on `stage`, where `effective_replicas`
  clamps every core service to 1 — so the only reachable shortfall is zero tasks,
  already covered. Leave a comment saying this was considered and why it was
  omitted; a silent omission here is indistinguishable from an oversight.

### `_version_from_image_ref(ref: str) -> str`

Shared by both foundations. Returns the tag. Raises
`OrchestratorStateUnreadable` when the ref is digest-pinned (contains `@`) or has
no tag separator after the final `/` (rows #13/#22). Comment that this is
unreachable today — `_image_ref` never digest-pins a core-service image, only the
otelcol sidecar, which is not checked — and guarded anyway because an unreadable
version silently becoming a correct one is the exact failure this mod exists to
prevent.

A mismatch against `ctx.project.version` raises `DeployedServiceUnhealthy` and the
message must quote the **full** ref, not just the tag (row #14).

---

## Step 6 — Tests

### 6a. `tests/unit/test_orchestrator_health.py` (new)

One test per row of the overview's table. Each test asserts **the specific
exception type** and a distinctive message fragment — not merely that *something*
raised. Include both foundations' happy paths.

**Run every new red test and confirm it fails for the intended reason.** A
`TypeError` from a mis-built fake also produces a red test and proves nothing;
that is the trap this mod's whole subject matter is about.

Three tests deserve naming because they are the ones that keep the design honest:

1. `test_empty_task_list_is_not_healthy` — a service with zero tasks fails.
2. `test_no_core_services_fails_rather_than_passing_vacuously` — row #1.
3. `test_rereads_once_then_fails_and_never_masks_an_unhealthy_service` — script an
   *unhealthy* task that is returned on both reads, assert the error is
   `DeployedServiceUnhealthy` (not `OrchestratorStateUnreadable`) and that the
   task set was never re-read at all. Then, separately, script a shrinking set and
   assert exactly two `ecs_list_service_task_arns` calls in `aws.calls` and an
   `OrchestratorStateUnreadable` whose message says "after a re-read".
   Monkeypatch `_TASK_SET_REREAD_DELAY_S` to `0`.

Also assert the fixed path's SSH command shape: exactly one `capture` per
container, the command contains `sudo docker inspect`, and it does **not** contain
`2>/dev/null` or `|| true`. That last assertion is cheap and pins the design
decision against a well-meaning future edit.

### 6b. `tests/unit/test_aws_ecs_stagetest_reads.py` (new)

Boto3-adapter tests for the three new methods, modelled on
`tests/unit/test_aws_service_connect_endpoints.py` (`MagicMock` + `monkeypatch`,
paginator helper). Pin: `desiredStatus="RUNNING"` is actually passed; chunking at
100 in `ecs_describe_tasks`; `healthStatus` absent → `"UNKNOWN"`; a task under
`failures` is omitted from the result; `ClusterNotFoundException` **propagates**
(the inverse of `ecs_primary_deployment_times`'s behaviour — assert both in
adjacent tests so the contrast is visible in the file).

### 6c. `tests/unit/test_pipeline_stagetest.py` (rewrite)

All 7 tests assert on `fake_docker.calls` by positional index (`run_call[3]`,
`[4]`, `[5]`) and break on any signature change. Add a module-level helper that
names the fields:

```python
def _run_one_shot_call(fake_docker) -> dict:
    """(method, image, command, env_items, network, mounts) → a named dict."""
```

Rewrite all 7 onto it. Then add:

- the pre-step runs **before** `build_image`;
- a failing pre-step means `build_image` is **never called** (assert
  `"build_image" not in [c[0] for c in fake_docker.calls]`) — this is the doctrine
  requirement "before the tester image is built", and it is worth its own test
  because an ordering that merely *raises later* would still pass every other
  assertion here.

Every test in this file now needs an `ssh=` (the sample fixture is `fixed`).
Script a healthy `FakeSSHClient` in a local fixture and write the dummy deploy key
into `sample_ctx`'s tree.

### 6d. `tests/conftest.py` — `FakeSSHClient`

Add `capture_results: dict[str, str]` — command-substring → stdout, checked before
falling back to `capture_out`. Keeps every existing caller unchanged.

### 6e. `tests/integration/test_stagetest_real.py`

The pre-step must **run**, against a fake host — there is no skip flag and none
may be added (overview § *The gate has no off switch*).

- Write a dummy `infra/deploy_creds/stage` file into `fresh_project`.
- Pass `ssh=FakeSSHClient(capture_out=f"healthy|running|reg/sample/api:{ctx.project.version}")`.
- Add a comment stating that the SSH path is faked here deliberately, that no test
  in the suite exercises it against a real remote host, and that the fixed smoke
  walk's `stagetest` box is therefore this code's **first** real execution.

---

## Step 7 — `src/docex/pipeline/stagetest.py`

- Signature: `run_stagetest(ctx, docker, *, aws=None, ssh=None, staging_url_override=None, network_override=None) -> int`.
- Update the module docstring's numbered list: the orchestrator pre-step becomes
  step 1 and the existing steps renumber. Reference `cicd.md § Staging Tests`.
- Order in the body: `infra is None` guard → STAGING_URL derivation →
  **`assert_deployed_healthy(...)`** → build → run.
  `cicd.md` numbers the orchestrator read as step 1; the STAGING_URL derivation is
  a pure string computation that touches nothing deployed and builds nothing, so
  the orchestrator read is still the first thing that touches the deployed world,
  and putting it second preserves the better error for a project missing
  `apex_domain`. **Leave a comment saying this, so the order is not flipped by
  someone reading only the doctrine's numbering.**
- Do not catch the two new errors. They are `DocexError`s and the dispatcher's
  `ErrorReporter` renders them, exactly as `StageTesterBuildFailed` is handled.

## Step 8 — `src/docex/__main__.py`

`_cmd_stagetest`: construct `aws = _make_aws_client()` and `ssh = _make_ssh_client()`
and thread both, as `_cmd_release` already does. Both constructions are cheap and
offline. Mirror `_cmd_release`'s comment about the unused-transport-per-foundation
arrangement.

## Step 9 — Contracts

**No contract changes.** This mod adds no surface to any core service and changes
no core service's boundary; it changes what `docex` reads about a deployed one. No
file under any project's `infra/contracts/` is touched.

---

## Step 10 — Verify

1. `.venv/bin/python -m pytest tests -q` → expect **1116 + new tests, 0 failed**.
2. `.venv/bin/python -m pytest tests -m integration -q` → expect **18 passed**.
   **Run it alone** — nothing else may be touching docker. Concurrent pytest
   processes produce five convincing false failures in migrate / up-down / build.
3. `grep -rn "skip_orchestrator_check\|skip_health" src/` → must return nothing.
4. `grep -rn 'apply_policy(f"{project' src/` → must return nothing (both copies
   lifted).
5. `grep -c "2>/dev/null" src/docex/pipeline/orchestrator_health.py` → 0.

Do **not** touch: `test_projects/` (mods 129–130), `tables/`,
`src/docex/pipeline/check.py`, or any file under `doctrine/`. If something in
`doctrine/` looks wrong, report it — the operator takes doctrine edits.

Report: what landed, both measured suite numbers, which table rows you
demonstrated red and the exception type each produced, and anything you had to
decide that this document did not settle.

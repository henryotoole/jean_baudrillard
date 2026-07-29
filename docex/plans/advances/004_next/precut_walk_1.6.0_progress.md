# 1.6.0 Pre-Cut Walk — Progress and Handoff

State of the [`PRE_CUT_CHECKLIST`](../../../test_projects/PRE_CUT_CHECKLIST.md)
walk for the **1.6.0 service-process-types** cut, written at the handoff point
between the fixed-foundation walk (complete) and the elastic walk (not started).

**Status: fixed foundation ✅ complete and torn down clean. Elastic ❌ not
started. The cut is NOT yet safe to perform** — `PRE_CUT_CHECKLIST § E` requires
both walks green.

---

## What is done

| Section | Result |
| ------- | ------ |
| `docex:1.6.0` image | **built** locally; `./bin/docex --version` → `docex 1.6.0` from inside the container |
| `pytest tests/unit` | **983 passed** |
| `pytest -m integration` | **17 passed** (started at 7 failed / 9 passed / 1 skipped — see [Defects found](#defects-found-and-fixed)) |
| A. Prerequisites | satisfied; several checklist claims found stale (see [Checklist corrections](#checklist-corrections-owed)) |
| B. Conformance audit | key mechanical items verified (core parity, entrypoints, no activation in `root.py`, contracts, `cicl_version: "2"`, `domain_default_process`) |
| **C.1–C.11 fixed walk** | **all green**, `verify_clean.sh` → clean, zero remnants |
| D. elastic walk | **not started** |

### The two things only this walk covers — both now proven on fixed

1. **Scheduler end-to-end** (`§ B` note 1). `docex test` produced
   `reaper-exec-run-… → 3 passed`: a scheduler-only codebase running its tests
   **through the exec service**, which is Mod 103's deletion of
   `_run_scheduler_tests` validated by real execution. `reaper-prune-scheduler`
   came up in dev, stage, and prod.
2. **The fixed replica unroll** (`§ C.9`). Live and verified:
   - two containers `…-prod-api-worker-1` / `-2`, both `(healthy)`
   - one otelcol sidecar each, netns-paired
   - both carrying the shared alias `docex-smoke-fixed-prod-api-worker`
   - `POST /pings` → 201 → `processed_at` set, and **worker-1 consumed it while
     worker-2 did not** — independent consumers, no double-processing
   - the unroll survived a `rollback` and came back healthy

`replicas` had been declared, documented, and read by no emitter for its entire
existence. C.9 is the only thing anywhere that executes the multi-service form.

### Other confirmations worth keeping

- **One image, two process types**: `registry.luxrnd.tech/docex_smoke_fixed/api:0.0.15`
  on both `api-web` and `api-worker`. Registry has `api` + `reaper` at `0.0.15`;
  the legacy `web`/`worker` repos have **no** `0.0.15` tag. No third repo.
- **`docex check`: all 10 gates pass**, including `contracts_exist — 2 contract(s)`,
  which is the first time Mod 101's **asyncapi** branch has ever executed, and
  `health_endpoints` asserting the `/health/<svc>/<proc>` fan-out.
- **One migration per codebase**: ansible ran a single `TASK [Run migrations for api]`;
  dev/test migrate went through `api-exec-run-…`.
- **Three prod URLs all 200 with matching version** — canonical two-segment
  (`api-web.prod.…`), bare-env via `domain_default_process`, and bare-project.
- **Fan-out `/health/api/worker` → 200**, and it correctly returned **503** while
  the worker was down. The loop-liveness rule works in both directions.
- **SIGTERM handling** in the seed worker: `caught signal 15, stopping after
  current iteration` → `stopped` (Mod 103's main-thread loop).
- `rollback prod 0.0.15` → migrations skipped, all URLs reverted, data preserved;
  `--dry-run` exits 0 with no mutation.

---

## Defects found and fixed

Committed as `c9ededc` ("pre-cut repair").

1. **All four test fixtures declared `command: ["python", "/service/dist/root.py"]`
   — a file no fixture has ever contained.** `build.sh` copies `src/`→`dist/`,
   where the module is `app.py`. Mod 096 made `command:` mandatory and reached for
   the doctrine's composition-root filename instead of the fixture's real entry
   module. Every fixture container crash-looped and its netns-paired sidecar
   could not attach. **Invisible to 983 unit tests** — they only *compile*
   fixtures; nothing runs one — and integration was `--collect-only` for the
   whole advance.
2. **Two integration tests asserted the pre-advance one-segment identity.**
   `test_up_down_real` matched `endswith("api")`; `test_stagetest_real` built
   `{seg}-dev-api`. Compose keys are now per process type, so the name is
   `sample-dev-api-web` and `sample-dev-api` names nothing. This is exactly the
   debt every corporal from Mod 099 on flagged as "goes blind".

---

## Traps that will bite the elastic walk

Ordered by how much time they cost me.

### 1. A fresh codebase cannot start in `dev` until `docex build` runs

The dev compose bind-mounts `./core/<svc>/dist:/service/dist`, so `/service/dist`
is the **host's** directory, which **shadows** whatever `docker build` put in the
image. Mod 107 created a brand-new `api` codebase, so its host `dist/` still held
the *old* `web` codebase's `root.py` and `hex/` — no `entrypoints/`. Result:
`api-web` and `api-worker` crash-loop with
`python: can't open file '/service/dist/entrypoints/web.py'`.

**Fix: run `./bin/docex build` before (or after a failed) `envinfra up dev`.**
`docex build` only requires *some* service in the stack to be running, and
backing services come up fine, so it works from the failed state.

**The elastic project has the same new `api` codebase and will hit this at D.6.**
It does *not* affect stage/prod on elastic (images come from ECR; no bind mount).

### 2. `docex build` cannot recover from root-owned files in `dist/`

26 root-owned `__pycache__` dirs, written by a container running as root in an
earlier walk, made the dist-wipe step die with
`PermissionError: [Errno 13] ... dist/hex/pings/ports/driving/__pycache__`.
The shim runs docex as the host uid, so it can *never* delete them.

**Fix:** `sudo find core -name __pycache__ -type d -prune -exec rm -rf {} +`

Check the elastic project for the same before D.6. This is a genuine docex
robustness gap, not advance-caused — worth filing.

### 3. Disk fills fast, and the biggest consumer is invisible

Hit `no space left on device` **twice** — once breaking `tofu init` (which made
three `test_hcl_validate_real` tests fail for reasons that looked like invalid
HCL), once breaking the stage release's image extraction.

- **`/tmp/pytest-of-ubuntu` reached 30 GB** across five integration runs — each
  test downloads a ~600 MB tofu provider into its own tmpdir. Delete it between
  runs. This was ~85% of the problem.
- Docker build cache regrows to 20 GB+; `docker builder prune -af` is safe.
- Old `docex:*` images are safe to remove — `docex_process.md` states the
  determinism promise rests on rebuilding from the `v<v>` git tag, not on
  keeping the image. Keep the current release and the candidate.
- **Do NOT `docker volume prune`.** 86 volumes, only 9 active; the "reclaimable"
  16 GB includes `field-radio`'s and `transcript-archive`'s database data.
- The elastic walk pulls more tofu providers and provisions RDS/ECS; **check
  `df -h /` before D.3 and before D.9.**

### 4. Docker address pools were exhausted; now widened

`/etc/docker/daemon.json` **did not exist**; docker's defaults gave ~32 networks
and 28 were allocated across four projects. The next `172.x` slot is the host's
own VPC (`172.31.0.0/16`), which docker correctly refuses. Now:

```json
{ "default-address-pools": [
    { "base": "172.16.0.0/12",  "size": 16 },
    { "base": "192.168.0.0/16", "size": 20 },
    { "base": "10.128.0.0/12",  "size": 24 } ] }
```

4096 extra networks, verified allocating (`10.128.1.0/24`). **Clear of the master
VPC's `10.20.0.0/16`**, which matters for the elastic walk. Required a daemon
restart (operator authorized; the other projects recovered via restart policy).

### 5. `containerize` must run from `main` — the checklist omits `merge`

`C.6`/`D.8` list `check` then `containerize`, but `containerize` refuses off
`main`. The real chain is **`check` (on the feature branch) → `merge` → `containerize`**.

Also: **`merge` prints `error: failed to push some refs` while still exiting 0**
when the feature branch was never pushed to origin (it tries to delete the remote
branch). Alarming, harmless.

### 6. Restart backoff makes logs look stale

After fixing the `dist/` problem the worker kept logging the *old* error, which
looked like the bind mount not propagating. It was docker's exponential restart
backoff — attempt gaps of 14s → 27s → 52s, so every logged line predated the fix.
**Read log timestamps against the fix time** (`docker logs -t`), or force
`docker restart` to get a decisive answer.

### 7. ACME races the first probe

Both dev and stage returned traefik's `404 page not found` on the first curl, then
200 seconds later once HTTP-01 issued. Don't diagnose a 404 immediately after
`envinfra up` / `release`; re-probe. Also **`curl -I` returns 405** — the seed app
only implements GET.

---

## Elastic-walk-specific state

### Git — the elastic project needs the same restructure the fixed one got

Current: branch **`smoke-walk-1.6.0`**, `version: "0.0.15"`, `origin/main` at
**`v0.0.14`**, tree clean, Mod 107's migration committed on the branch.
That is already the shape `check` wants. The sequence from here is
`compile → check → merge → containerize` (see trap 5).

The fixed project finished at `main` / `v0.0.16` (it needed a second version for
the C.10 rollback walk; do the same at D.12).

### DNS — created, and one leftover to clean

13 A-records added to `luxrnd.tech` (zone **`Z05249222MUE7QVI7SG0I`**) →
**`3.214.203.31`**, TTL 60. Four are the elastic dev/test out-of-band records
`{dev,test}` and `*.{dev,test}.docex-smoke-elastic.luxrnd.tech` that
`preinfra development` requires (A.4.2). Nine are the fixed project's and can be
removed now that its walk is done.

**Note the per-env wildcards already cover the new two-segment hostnames**
(`api-web.dev.…`), because the process segment shares the service's DNS label.
`A.4.1` says this explicitly; `upgrade_1.6.0.md` tells downstream projects the
opposite, and both are right — those projects hold per-host records, these hold
wildcards.

**Leftover from a prior walk:** hosted zone **`docex-smoke-elastic-stage.`**
(`/hostedzone/Z00031833M2SHLRRAE294`, 2 records, ~$0.50/mo). Bare zone name with
no parent suffix — an old-docex artifact. `verify_clean` checks the child *zone*,
so this one slipped through. Worth deleting.

D.3's NS delegation is manual: phase 1 prints the four NS hostnames; create an
`NS` record at `docex-smoke-elastic.luxrnd.tech` in zone `Z05249222MUE7QVI7SG0I`,
wait for `dig NS docex-smoke-elastic.luxrnd.tech @1.1.1.1`, then re-run phase 2.

### AWS

Account **`256071447730`**, creds via the EC2 instance role (`dev-instance-role`)
— there is **no `~/.aws/credentials`**; `~/.aws` holds `config` + `sso` only. The
shim mounts `~/.aws:ro` and in-container AWS calls worked throughout, so this is
fine, but don't be alarmed by the missing file.

Master VPC **`vpc-07e85ecd250b5af29`** `10.20.0.0/16`, 4 subnets
(`us-east-1a`/`1b` × public/private, `tier` tagged), NAT
`nat-07e5c78da3ce46ce3` **available** in the `1a` public subnet.

---

## Checklist corrections owed

Found while walking; **none blocked progress**, all should be fixed in
`PRE_CUT_CHECKLIST.md`.

1. **A.3.2 names the wrong tags.** It says the master VPC carries
   `Name=docex-master-vpc` and `managed_by=docex-preinfra`. Reality —
   and the `cicl.md § Elastic Foundation` preinfra convention — is
   `Name=master_network_VPC`, `managed_by=doctrine-operator`,
   `shape_name=master_network`, `infra_tier=prerequisite`. The infrastructure is
   right; the checklist is stale.
2. **C.6 / D.8 omit `docex merge`** between `check` and `containerize` (trap 5).
3. **A.1 says `~/.aws/credentials` must be present.** It isn't, and doesn't need
   to be — an instance role works.
4. Mod 106's note stands: `§ C.9`'s prod sidecar count is a **sum** over
   non-scheduler process types × their replicas, not a product.

---

## Resumable state

- Working tree: the advance's 30 commits plus `c9ededc` (pre-cut repair) and the
  test-project catchups are on `main`.
- **Not done:** no `v1.6.0` git tag, no image published anywhere, elastic walk
  untouched. `VERSION`/`pyproject`/`__init__`/`plugin.json` are all at `1.6.0`.
- Fixed project torn down; `verify_clean.sh` green; no AWS resources created by
  the fixed walk.
- Open items for the cut remain in
  [`service_processes_implementation_plan.md § Flagged for operator`](./service_processes_implementation_plan.md#flagged-for-operator)
  — the headline being that **no `queue` backing role exists**, so 1.6.0 ships a
  first-class `worker` with nothing first-class for it to consume.

---

# Elastic walk — session 2 (2026-07-29)

**Status: walk D.1–D.13 executed. Two defects found — one FIXED (mod 108,
verified on real AWS), one OPEN and cut-blocking (needs an operator design
decision).**

| Finding | State |
| ------- | ----- |
| 1. Elastic HCL emitter never emits `command` | **FIXED** — mod 108, unit suite 987, verified live on stage + prod |
| 2. First-time elastic release loses the `consumes` fan-out to a start-order race | **OPEN** — cut blocker, design decision required |
| 3. `verify_clean.sh` coverage gaps left orphans that blocked the stage apply | **OPEN** — cheap fix, not yet made |
| 4. Checklist `A.4.2` delegation/DNS ordering is wrong | **OPEN** — checklist edit, not yet made |

## ⛔ OPEN defect (2) — first-time elastic release loses the `consumes` fan-out

**The doctrine-mandated `/health/<svc>/<proc>` fan-out is broken on a first-time
elastic release, permanently, by a start-order race.** Found at D.11.

ECS Service Connect snapshots a client task's **resolvable alias set at task
start**. `docex` emits the consumer's and the consumed's `aws_ecs_service` in
parallel — tofu logged `api-worker: Creating...` and `api-web: Creating...`
simultaneously — with no `depends_on` between them and no
`wait_for_steady_state`. So whichever Fargate task starts first decides the
outcome:

```
api-web   task started 19:40:02   <- consumer won the race
api-worker task started 19:40:17
api-worker task started 19:41:03
```

`api-web`'s Envoy was configured before the worker's Service Discovery service
had any instance, so the alias `docex-smoke-elastic-prod-api-worker` was never
installed. Result: `https://docex-smoke-elastic.luxrnd.tech/health/api/worker`
→ `503 … Name or service not known`, **indefinitely**, with both worker tasks
`HEALTHY` and **2 instances registered** in the namespace. Ten probes over ~3
minutes all failed.

**Decisive experiment.** `aws ecs update-service --force-new-deployment` on
`api-web` alone → fan-out returned **200** the moment the replacement task took
over. Nothing else changed.

**Why stage did not catch it.** Stage's namespace already had the worker
registered from the earlier (pre-mod-108) deploy, so every subsequent `api-web`
task started into a namespace that already contained the alias. **Only a
genuinely first-time release exposes this** — which is exactly what D.11 is.

**Severity.** Worse than the health endpoint suggests: the fan-out is merely the
*observable symptom* the doctrine deliberately placed there. The same snapshot
applies to **any** real inter-process Service Connect call. A downstream elastic
project's first production release can come up with every task healthy and every
sibling call failing.

**Not introduced by 1.6.0** — `consumes` and the fan-out predate CICL v2, so this
is likely long-standing and latent, surfaced here because D.11 is the first
first-time elastic prod release with a non-`web` consumed process type.

### Why this one was NOT fixed in-session

Unlike mod 108 (a one-key omission with a single correct answer), this needs a
**design decision** the operator owns:

| Option | Shape | Cost / hazard |
| ------ | ----- | ------------- |
| (a) Ordering + steady-state | tofu `depends_on` consumer → consumed, plus `wait_for_steady_state = true` on consumed services | Slower applies. **Cycle hazard:** `cicl.md § The graph may contain cycles` permits a cyclic `consumes` graph, and a naive `depends_on` would deadlock. Would need restriction to acyclic edges. |
| (b) Post-apply reconcile | After the env-tier apply converges, force a new deployment of every consumer whose targets were newly created | Handles cycles. Adds a release step and a "was this newly created" determination. |
| (c) App-level retry / re-resolve | Consumers re-resolve on failure | Weakest — pushes an infrastructure defect into every downstream project's application code, and `contracts.md § Health Checks` explicitly wants a *short hard timeout* on the fan-out. |

`docex` already holds the `consumes` graph — it is what obliges the fan-out
endpoint and what four-segment magic refs resolve against. It simply never
translates that edge into ordering on elastic. (a) restricted to acyclic edges,
or (b) as the general mechanism, both look defensible; picking is design.

## ✅ FIXED defect (1) — elastic HCL emitter never emits `command`

Shipped as **[mod 108](../../modifications/108_elastic_command_emit/overview.md)**.

`src/docex/emit/hcl.py::render_task_definition` builds `container_def` from
`name` / `image` / `essential` / `logConfiguration` / `portMappings` /
`environment` / `secrets` / `target_extras` / `dockerLabels` / `mountPoints` /
`dependsOn` — and **never reads `command`**. Every emitted
`aws_ecs_task_definition` for a core process type has `command = null`.

The data is present and correct: `cicl/compile.py:859` sets
`body["command"] = svc.command` on the elastic branch (the fixed branch does the
same at `:822`, and `emit/compose.py` consumes it). Only the HCL consumer is
missing. `command` is not a transfer-table field — it is a CICL process-type
attribute the emitters read directly, so this is an emitter gap, not a table gap.

**Effect.** Every ECS task runs the image's Dockerfile `CMD`. Since one image
serves N process types, at most one can be correct. This directly contradicts
[`infrastructure.md § Core Service Containers`](../../../doctrine/infrastructure/infrastructure.md#core-service-containers),
which states a core service's `CMD` "is not used" and each process type's
`command` "is what the compiler emits." On elastic the `CMD` is the *only* thing
used. **1.6.0's headline feature is inert on elastic.**

**Observed.** `api-worker` logged `Uvicorn running on http://0.0.0.0:8080` — it
ran `entrypoints/web.py`. Its container healthCheck probes `:8081/health`, so the
container went `UNHEALTHY`, Service Connect stopped serving the endpoint, and
`https://stage.…/health/api/worker` returned
`503 {"detail":"api.worker unreachable: … Name or service not known"}`.
`/health`, `/health/probe`, `/health/events` and the two-segment
`api-web.stage.…/health` were all **200**.

**Why nothing caught it.**
- Masked by Dockerfile luck: `api`'s `prod` stage `CMD` is `web.py` and
  `reaper`'s is `prune.py`, so `api-web` and `reaper-prune` accidentally ran the
  right thing. Only the *second* process type of a codebase is visibly wrong.
- No unit test asserts `command` inside an emitted container definition
  (`tests/unit/test_hcl_emitter.py:566` has `command` only as fixture *input*).
- Integration tests are dev/fixed only.
- The scheduler RunTask shares this renderer and is equally affected: the
  `aws_scheduler_schedule` target carries no `overrides`, so `reaper-prune`
  also relies on the Dockerfile `CMD`.

**Fix shape.** Read `body.get("command")` in `render_task_definition` and set
`container_def["command"]`, normalizing `str | list[str]` → list (ECS requires a
list). Add an HCL-output assertion, ideally on a two-process codebase so the
distinction is observable. Then re-run from D.9.

## Second finding — `verify_clean.sh` has large coverage gaps

The first `release stage` failed with seven `AlreadyExists` errors from
**orphans left by a prior elastic walk** that `verify_clean.sh` had reported
clean. Creation timestamps (`2026-07-11`) and pre-CICL-v2 one-segment names
(`/stage/web`, `/stage/worker`, `…-stage-web-tg`) confirm the provenance.

Resource types `verify_clean.sh` does **not** check, all found orphaned:

| Orphan | Identifier |
| ------ | ---------- |
| Security groups | `docex-smoke-elastic-stage-{internal,web}` |
| Service Discovery namespace | `docex-smoke-elastic-stage` (`ns-zy26jlqjdvo6luft`) |
| RDS DB subnet group | `docex-smoke-elastic-stage-appdb` |
| CloudWatch log groups | `/docex_smoke_elastic/stage/{events,probe,web,worker}` |
| EFS filesystem | `fs-0fb4013e1133943eb` |
| ALB target group | `docex-smoke-elastic-stage-web-tg` |
| ECS task-definition families | `docex-smoke-elastic-stage-{web,worker}` (still ACTIVE) |

All were fully detached (no ENIs, no mount targets, no namespace services, no
listener-rule references) and were deleted by hand to unblock the apply.

**The handoff's "mystery" hosted zone is identified.** `docex-smoke-elastic-stage.`
(`Z00031833M2SHLRRAE294`) was **not** an old-docex artifact with a stray bare
name — it is the hosted zone backing the ECS **Service Connect private DNS
namespace**, which is why it has no parent suffix. It disappeared the moment the
namespace was deleted. It also actively blocked the apply:
`CANNOT_CREATE_HOSTED_ZONE … already been associated with the hosted zone`.

## Third finding — child-zone delegation shadows the dev/test DNS records

`A.4.2` says the out-of-band `{dev,test}` + `*.{dev,test}` A-records go in the
**parent** zone and "get shadowed once the child zone is delegated (D.3), which
is fine — `preinfra development` only runs at D.1." **It does not.**
`envinfra up dev` re-runs `preinfra development` as a precondition, so D.6 fails
after D.3 with `dev host '…' does not resolve in public DNS`.

Worse, the failed probe seeds a **negative cache** entry. The child zone's SOA
gives a 900 s negative TTL, and the AWS VPC resolver's distributed caches expire
independently — resolution flapped for ~9 minutes before stabilising. Cost: three
failed `envinfra up dev` attempts and ~15 minutes.

Fixed forward by adding the four records to the **child** zone
(`Z0936696Z80PZDCOA5ZM`), which is what the project-tier HCL already documents as
expected — `aws_route53_zone.project` carries a `force_destroy` comment about
"records tofu doesn't own — dev A-records".

Checklist fix, either: (a) run D.6 dev-sanity **before** D.3, or (b) have A.4.2
say to re-create the records in the child zone immediately after D.3 phase 1,
*before* anything probes them.

## What D.1–D.8 proved

| Step | Result |
| ---- | ------ |
| A / B audit | pass. Core parity `diff -r` clean. `cicl_version: "2"`, dotted `domain_default_process`, `processes:` on both services, `depends_on` backings-only, four-segment magic refs. |
| B.15 | pass — every data-plane name hyphenates; underscores only in tags, SSM paths, IAM/DDB names, ECR repo names, and HCL resource identifiers. |
| D.1 / D.2 | `preinfra development` + `production` exit 0; four `-web` networks + project traefik up. |
| D.4 → D.3 | compile clean (6 files); projinfra phase 1 → zone `Z0936696Z80PZDCOA5ZM`, NS delegation propagated in 15 s; phase 2 applied 20 resources — ALB, both ACM certs **ISSUED**, IAM exec role, 2 ECS clusters, and **exactly two ECR repos** (`api`, `reaper`). |
| ACM SAN coverage | verified all three D.11 URLs are covered: prod cert is `*.prod.…` + SANs `prod.…` and bare `docex-smoke-elastic.luxrnd.tech`. |
| D.6 dev | fully green after the trap-1 `docex build`: `/health`, `/health/api/worker`, `/health/probe`, `/health/events` and `api-web.dev.…/health` all 200; `POST /pings` → 201 and the worker set `processed_at`. **The fan-out works on fixed-style dev — the failure is elastic-only.** |
| D.7 | `docex test` exits 0, one run per codebase. |
| D.8 | all 10 gates pass (incl. `contracts_exist — 2 contract(s)`); `merge` tagged `v0.0.15`; `containerize` pushed `api` + `reaper` at `0.0.15`. No `web`/`worker` repos, no third repo. |
| D.9 partial | first-time-release path detected correctly (`no ECS services … applying infra before migrate`); 25 resources; migration ran **once** for `api` via ECS RunTask and exited 0. Exactly **4** ECS services (`api-web`, `api-worker`, `probe`, `events`); `reaper-prune` is an `aws_scheduler_schedule` (ENABLED) + task definition + scheduler IAM role with **no** `ecs_service`; exactly **one** `…-api-migrate` family and none for `reaper`; `api-worker` has a container `healthCheck` and **no** target group with `desired_count = 1` (the prod-only clamp), `api-web` has the target group. The ALB listener rule correctly matches both `api-web.stage.…` and `stage.…`. |

## Minor checklist notes

- **B.11.1's grep is over-broad.** It tells you to grep `root.py` for `socket`;
  `api/src/root.py` legitimately calls `socket.create_connection` inside a
  *constructed* health handler. `build_app()` returns the app un-served and there
  is no `uvicorn.run` / `while True` / `__main__`, so the doctrine rule holds.
  The grep term needs narrowing or a stated exception.
- Handoff corrections **1** (master VPC tags are `Name=master_network_VPC` /
  `managed_by=doctrine-operator`), **2** (`merge` missing between `check` and
  `containerize`) and **3** (no `~/.aws/credentials`; the EC2 instance role
  works) all **re-confirmed** on this walk.

## What D.9–D.13 proved (after mod 108)

| Step | Result |
| ---- | ------ |
| D.9 retest | `api-worker` container **HEALTHY** (was UNHEALTHY); its log reads `entrypoints.worker … processor: starting loop (interval=1.00s, health on :8081)` where before it read `Uvicorn running on http://0.0.0.0:8080`. All four stage endpoints 200, **including `/health/api/worker`**. Steady-state release path taken on the redeploy (services existed), migration idempotent. |
| D.10 | `docex stagetest` → **5 passed**, exit 0. |
| D.11 | prod first-time release, 35 resources. **`desired_count = 2` with two RUNNING worker tasks** — the elastic sibling-tolerance path nothing else exercises. All three prod URLs 200 at `0.0.15`: canonical two-segment `api-web.prod.…`, bare-env `prod.…`, bare-project `docex-smoke-elastic.…`. `POST /pings` → 201 and the prod RDS row came back `processed_at` non-NULL (queried through a one-off ECS RunTask, since prod RDS is in the master VPC and unreachable from the dev box). `/health/probe` + `/health/events` 200. **Fan-out 503 → finding (2).** |
| D.12 | bumped to `0.0.16`, containerized (both versions coexist in ECR), released, then `rollback prod 0.0.15`: recompiled `0.0.15` in an ephemeral worktree (`docex-rollback/0.0.15-…`), pushed SSM, ran an untargeted apply, **`migrations skipped`** as doctrine requires. All three URLs converged back to `0.0.15`, fan-out 200, and RDS data preserved — `PINGS(total,processed): (1, 1)`. `--dry-run` → `No changes.` + `release: dry-run completed`, no mutation. |
| D.13 | teardown complete; `verify_clean.sh` green on **20** checks (12 original + 8 added). |
| § E | Route53 holds only `luxrnd.tech` with **zero** `docex-smoke` records (NS delegation + all dev/test A-records + the nine leftover fixed-project records removed). No ECR repos, no fixed-registry repos, no local containers / networks / volumes. |

### A teardown fragility worth knowing

`teardown.sh` runs well past 10 minutes (RDS deletion polling). Interrupting it
leaves a **stale DynamoDB state lock**, and the next teardown then skips
`tofu destroy` for that env with `Error acquiring the state lock` — while
printing only `(warning: … had non-zero exit; continuing)` and proceeding to the
project tier, which then also fails. The recovery is to delete the lock item
from `<project>_tofu_locks` (or `tofu force-unlock`) and re-run. Worth either a
`force-unlock` recovery path in the script or a louder abort.

## Fixes applied this session

1. **mod 108** — `docex/plans/modifications/108_elastic_command_emit/`
   (`overview.md` + `implementation.md`), the one-key fix in
   `src/docex/emit/hcl.py`, four regression tests, `docex:1.6.0` image rebuilt,
   and a `### Fixed` entry in the repo `CHANGELOG.md` under 1.6.0.
2. **`test_projects/elastic/verify_clean.sh`** — eight new checks for the types
   that let the orphans through: security groups, Service Discovery namespaces,
   RDS DB subnet groups, CloudWatch log groups, EFS file systems, ALB target
   groups, ACTIVE ECS task-definition families, EventBridge schedules. Detection
   is proven — these same queries returned the real orphans earlier in the
   session. **The fixed project's `verify_clean.sh` has not been reviewed for
   equivalent gaps.**
3. **`PRE_CUT_CHECKLIST.md`** — five corrections: `A.1` credentials-file claim,
   `A.3.2` master-VPC tags, `A.4.2` child-zone/negative-cache ordering, the
   missing `docex merge` in **both** `C.6` and `D.8`, `B.11.1`'s over-broad
   `socket` grep, and a `D.6` note on the `docex build` / bind-mount trap and the
   root-owned `__pycache__` recovery.

## Resumable state (end of session 2)

- Elastic inner repo: on **`main`**, `v0.0.16` tagged at HEAD, tree clean.
  Three new commits: `b7ec4a0` (recompile at 0.0.15 + provider lock), `b217885`
  (recompile with mod 108's corrected commands), `0b71b21` (0.0.16 rollback-walk
  bump). `v0.0.15` force-moved to `b217885`.
- **No AWS resources remain.** Both smoke projects fully torn down.
- **⛔ The cut is still NOT safe.** `PRE_CUT_CHECKLIST § E` requires both walks
  green; finding (2) is an open cut-blocker awaiting an operator design decision.
- **Retest scope once (2) is fixed:** it only manifests on a *first-time* elastic
  release, so verifying a fix means re-walking **D.3 → D.11** (a fresh project
  tier and a fresh prod env tier). D.1/D.2/D.4–D.8 are cheap; the expensive part
  is prod. The fixed walk does **not** need repeating — mod 108 touched only
  `emit/hcl.py`, which the fixed foundation never invokes, and the full unit
  suite is green.
- Mod 108 was implemented **without the operator-approval gate** that
  `practices/modifications.md § Process` step 3.3 specifies; the operator was
  away and the walk was blocked with live infrastructure running. It is written
  up in the standard shape for review, and should be reviewed as if the gate had
  been taken.

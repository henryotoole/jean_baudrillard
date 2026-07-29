# Mod 103 — Scheduler as a process type

Phase 3 of the **service process types** advance
([plan](../../advances/004_next/service_processes_implementation_plan.md),
[design record](../../advances/004_next/service_processes_refactor.md)).
The rules of record are the design record's § Vocabulary (*"`scheduler` stops
being its own species of service and becomes a process type whose trigger is
cron"*), § Two corroborating findings item 1, and § Telemetry Identity's
per-process restatement of the sidecar rule.

**No doctrine file is touched.** `specifics/scheduler.md` will read stale after
this mod — its § Caveats `test.sh` carve-out becomes false and its "own image"
framing becomes wrong. That is Mod 106's, and it is planned, not drift.

Baseline verified before design: **950 passed** (`pytest tests/unit`),
**1014 passed / 17 deselected** (`pytest tests/`), **17 collected**
(`pytest -m integration --collect-only`).

## Goal

Three things the advance left standing because Mod 099 had not landed yet:
mod 074's self-contained job image, `docex test`'s scheduler carve-out, and the
service-level phrasing of the sidecar rule. All three exist because a scheduler
used to be its own core service with its own image. It is now a process type on
a shared codebase image, so all three come out.

## What the inherited warning turned out to be

The C.O.'s condition was: **do not delete `_ensure_scheduler_image` or the
`test.py` branch on the strength of the `MOD 103 DELETES THIS BRANCH` comment —
verify the image exists on the `compose run` path first.** Verified empirically
against docker 29.4.1 / compose v5.1.3 (transcripts below are the actual
observed behavior, not inference):

| Question | Answer |
| -------- | ------ |
| Does `compose up --build` build a `profiles:`-gated service? | **No.** Confirmed: the exec image was absent after `up --build`. |
| Does `compose run` build the gated service's image when it is **absent**? | **Yes.** It runs a full build and tags it (`Image proj/api:0.0.1 Built`). |
| Does `compose run` **rebuild** when the image is present but the context changed? | **No.** It reuses the stale image silently. `--build` is required. |
| Is `run --build` safe on a block with no `build:` key (the stage/prod exec shape)? | **Yes**, clean no-op, rc 0. |

So the warning bites in a different place than expected. Image *existence* on
the `compose run` path is fine — item 2's deletion is unblocked. What is **not**
fine is image *freshness*, and that is a real regression if unhandled:
`_run_scheduler_tests` rebuilt the test-stage image on **every** invocation, so
a scheduler-only codebase's `test.sh` was always fresh. Routed through
`compose run` with no `--build`, run #1 builds and every run afterwards tests a
stale image — and for a scheduler-only codebase nothing else ever refreshes that
tag, because `up --build` has no non-gated service of that codebase to build.
See [§ 3](#3-the-test-env-one-off-builds) for the fix.

### And a live regression the verification surfaced — introduced by Mod 099

**Mod 099 shipped this break.** Stated plainly so the advance record shows where
the hazard came from rather than presenting it as pre-existing: mod 074's
job-image tag and Mod 099's exec service collide on one tag, and the collision
did not exist before 099. It is not a criticism of 099 — 099 verified a great
deal — but it is a class of interaction **no unit test could have caught**,
because no integration test covers a scheduler at all
([see below](#integration-tests-that-now-exercise-stale-paths)), and the only
thing that would have surfaced it is the pre-cut walk.

`_ensure_scheduler_image` and Mod 099's exec service are **incompatible**, today,
on `main`:

- Mod 074 builds the Dockerfile **`prod`** stage and tags it the codebase's
  dev-local ref, because an Ofelia job gets no bind mounts.
- Since Mod 096 that ref is **codebase**-keyed, and since Mod 099 the exec
  service — which `docex build` / `migrate` / `test` all run inside — carries
  `build: {target: dev}` against the **same tag**.
- `compose run` only builds when the image is *absent*. For a scheduler-only
  codebase the mod-074 prod-stage image is present, so the exec run reuses it.
  The doctrinal `prod` stage carries no `build.sh` and no `test.sh`
  (`test_projects/fixed/core/reaper/Dockerfile` is the reference case), so
  **`docex build dev` fails for any project with a scheduler-only codebase** —
  `run_build` iterates every codebase, not just long-running ones.

For a *mixed* codebase the same collision resolves the other way and mod 074 is
simply dead work: `up` builds the prod stage at step 1a and `compose up --build`
overwrites that tag with the dev stage at step 1b, so the Ofelia job has been
running the dev-stage image since Mod 096 regardless.

This settles what replaces the branch. **In `dev`, the codebase tag is the
Dockerfile `dev` stage — for every process type, including a cron job.** Any
other answer means two consumers of one tag disagree about what is inside it.

## What lands

### 1. Retire mod 074's self-contained job image

`_ensure_scheduler_image` (`orchestrate/up.py:79-117`) becomes
`_ensure_codebase_image`, with two changes and nothing else:

- **`target="prod"` → `target="dev"`.** Same tag, same `_image_ref` derivation,
  now the same stage every other consumer of that tag expects.
- **Loop scoped from `scheduler_services(ctx)` to
  `scheduler_only_services(ctx)`.** A codebase with a long-running process type
  already has its tag built by `compose up --build`; building it again is a
  redundant cache-hit build. A scheduler-only codebase has **no non-gated
  compose service**, so nothing in the compose graph builds its tag — this is
  the one case that needs docex to do it, and it is why the branch cannot simply
  be deleted.

`scheduler_services()` (`_common.py:110-123`) loses its only consumer and is
**deleted**; its docstring is explicitly mod-074. `scheduler_only_services()`
stays (the dev-build skip and now this).

**Emission needs no change, and this is verify-not-rebuild.** Both halves of the
plan's item 1 are already true, because Mod 096 keyed the image on the codebase:

- `_ofelia_ini`'s `image = svc.body.get("image", "")` — `body["image"]` is set
  from `_image_ref(..., svc_name, ...)` at `compile.py:806`, the *codebase* key,
  with a Mod 096 `WHY` comment saying so. Pinned by
  `test_scheduler.py:87` and `test_process_expansion_emit.py:140-142`.
- The job INI name is `svc.name`, i.e. the two-segment compiled identity
  (`[job-run "nightly_cleanup-nightly_cleanup"]`), as is the Ofelia container
  key `{p}-{e}-{svc.name}-scheduler`. Pinned by `test_scheduler.py:85` and
  `:56`.

What lands on the emitter is therefore **comment-and-test only**: `_ofelia_ini`'s
docstring says `[job-run "<svc>"]`, which now means the two-segment process
identity, and neither the docstring nor the `image` line records that the image
is the codebase's rather than the job's own. Plus the new tests below.

### 2. Delete `_run_scheduler_tests`

`orchestrate/test.py:40-63` and the branch at `:137-153`. A scheduler-only
codebase takes the identical path as every other codebase:
`compose run --rm {codebase}-exec ./test.sh`. `scheduler_only_services` and
`dns_label` drop out of `test.py`'s imports.

The seam Mod 099 promised is intact and pinned:
`test_exec_service.py::test_8_scheduler_only_codebase_gets_an_exec_service`
already asserts the exec service exists in `test` for a scheduler-only codebase,
with its build context and its `service_healthy` edge.

### 3. The `test`-env one-off builds

`compose_run_one_off` gains `build: bool = False`, adding `--build` to the
`docker compose run` argv. Passed **`True` exactly where the env is `test`**:
`run_test`'s two call sites (unconditionally — it *is* the test env),
`run_up`'s post-up migrate and `run_migrate`'s loop as `build=(env == "test")`.

The rule, in one sentence: **in `test` the image *is* the artifact under test, so
a one-off must never run a stale one; in `dev` the source arrives by bind mount
and the `dev` stage exists precisely so `build.sh` can be re-invoked *without*
rebuilding the image** ([`infrastructure.md` § Core Service
Containers](../../../../doctrine/infrastructure/infrastructure.md#core-service-containers)).
Passing `--build` in `dev` would contradict that rationale and would put a real
(non-cached, `RUN ./build.sh`) image rebuild on the hot `docex build` loop —
which is the one command whose entire purpose is to avoid it.

Cost in `test`: one cache-checked build per one-off. For every codebase with a
long-running process type `compose up --build` has already built that exact tag,
so it is a cache hit. For a scheduler-only codebase it is the only thing that
keeps `docex test` honest.

`up`/`migrate` in `test` are the same hazard as `run_test` — one line each, same
justification — so they land here rather than becoming a fourth thing a later
mod has to notice.

### 4. No sidecar for `scheduler` process types — verified, not rebuilt

Already correct per-process, since `compose.py:782` filters on
`s.is_core and s.role != "scheduler"` and `hcl.py` gates on
`"ecs_service" in emits`, both of which are per compiled service. Existing pins:
`test_process_expansion_emit.py::test_27` (a three-process codebase yields
sidecars for `web` and `worker` only), `test_scheduler.py::
test_fixed_no_long_running_block_for_job`, `::test_fixed_other_services_
unaffected`, `::test_elastic_scheduler_task_def_has_no_sidecar`,
`::test_elastic_web_service_still_has_sidecar`.

What this mod adds is one test that states the *per-process* claim the
service-level phrasing could not express — one codebase, `web` +
`nightly_cleanup`, **exactly one** sidecar — and one that pins the elastic
counterpart (`no ecs_service`, no target group, sibling `web` unaffected) at the
same codebase rather than across two.

## Behavior changes worth naming

1. **In `dev`, an Ofelia job runs the codebase's `dev`-stage image.** It gets no
   bind mounts (Ofelia spawns through the Docker API, not Compose), so it
   executes the artifact baked into the image at build time by the `dev` stage's
   `RUN ./build.sh`. `up dev` rebuilds that tag on every invocation, so
   re-running `docex up dev` is what refreshes a job's code. This is not a
   change in *practice* for a mixed codebase (see above — it has behaved this
   way since Mod 096); it is a change for a scheduler-only codebase, which
   previously got the self-contained `prod` stage. See
   [design question 1](#design-questions).
2. **`docex build dev` starts working for scheduler-only codebases** — the
   Mod 099 regression above is fixed here. No test asserts the broken behavior,
   so nothing has to be un-pinned.
3. **`docex test` on a scheduler-only codebase now goes through compose.** It
   gains the codebase's `depends_on` readiness gate and its networks, where the
   bare one-off had neither. The doctrine's advice to keep a job's tests
   self-contained still holds, but a job test that touches the test database is
   no longer structurally impossible.
4. **`test`-env one-offs now build first.** A build failure fails
   `docex test` / `docex up test` / `docex migrate test` where previously a
   stale image would have been used silently.
5. **No `prod`-stage build happens during `docex up dev` any more.** An operator
   watching build output will see one fewer stage built per scheduler codebase.

## Test plan

Minimum set is the C.O.'s four plus what the verification demands.

**Ofelia identity** (`tests/unit/test_scheduler.py`,
`test_process_expansion_emit.py`):
1. Mixed codebase (`web` + scheduler in **one** codebase): the INI's
   `image =` is byte-equal to the sibling `web` service block's `image`, and
   both are the codebase ref — asserted as an equality between the two emitted
   values, not against a literal, so the two can never drift apart silently.
2. The job INI name and the Ofelia container key are both the two-segment
   identity, for a mixed codebase (the existing pins cover only the
   scheduler-only fixture, where codebase and process names coincide and the
   two-segment claim is unfalsifiable).

**Sidecars** (`test_scheduler.py`):
3. One codebase, `web` + `nightly_cleanup`: **exactly one** `-otelcol` service,
   paired to the `web` process. Fixed.
4. Same shape on elastic: the scheduler process type's task def has no sidecar
   container, no `aws_ecs_service`, no `aws_lb_target_group`; the sibling `web`
   has all three.

**`docex test`** (`tests/unit/test_orchestrate_test.py`):
5. Scheduler-only codebase runs `test.sh` via
   `compose_run_one_off("{p}-test-nightly-cleanup-exec", ["./test.sh"])`, and
   `run_test` issues **zero** `build_image` and **zero** `run_one_shot` calls.
6. A failing `test.sh` in the scheduler codebase's exec service returns that
   exit code and still tears down — replaces
   `test_run_test_scheduler_{build_failure_short_circuits,run_failure_returns_code}`,
   whose subject is the deleted helper. Converted, not dropped: the
   failure-propagation coverage moves to the new path.
7. Every `run_test` one-off (migrate **and** test) carries `--build`.

**`docex up` / `migrate`** (`test_orchestrate_up.py`,
`test_orchestrate_migrate.py`):
8. `up dev` builds the scheduler-only codebase's image at
   `target="dev"`, tagged the codebase ref
   (`("build_image", …/core/nightly_cleanup, "dev", "sample/nightly_cleanup:0.1.0")`)
   — replaces `test_up_dev_builds_scheduler_image_from_prod_stage`.
9. **No `build_image` call with `target="prod"` anywhere** in `up dev`. This is
   the deletion pin for mod 074 and it is worth its own assertion: a
   prod-stage build under the dev tag is exactly the state that broke
   `docex build`.
10. A codebase that has a long-running process type gets **no**
    `target="dev"` build from `up` (compose builds it) — the scoping change.
11. `up test` / `migrate test` pass `--build`; `up dev` / `migrate dev` /
    `build dev` do **not**. The dev half is as load-bearing as the test half.

**Deletion pins:**
12. `_run_scheduler_tests` is gone from `docex.orchestrate.test` and
    `scheduler_services` from `docex.orchestrate._common`, so neither grows a
    quiet second consumer.

**Regression floor:** all four fixtures and both `test_projects` still compile;
`pytest -m integration --collect-only` still collects 17.

### Integration tests that now exercise stale paths

Cannot run here (docker/AWS). The important finding is that **no integration
test covers a scheduler at all** — `tests/integration/conftest.py:19` points
every one of them at `sample_project`, which has no scheduler process type. So
`test_test_real.py` is *not* the real exposure for items 1 and 2; the smoke walk
is.

| Test / walk | Why |
| ----------- | --- |
| `test_test_real.py::test_docex_test_passes_and_tears_down` | Exercises the `--build` change on `run_test`'s two one-offs (not the scheduler path — the fixture has none). |
| `test_up_down_real.py::test_up_then_down_dev` | `up dev`'s build sequence changed; no scheduler in the fixture, so this only pins that nothing else moved. |
| `test_build_real.py::test_build_refreshes_dist_after_src_edit` | Passes `service="api"`, so it never hit the `docex build` break; still the closest cover for the exec-run path. |
| `test_check_real.py` (both) | `run_test` under a worktree `project_dir` now passes `--build`; compose must resolve the build context relative to `--project-directory` exactly as `up --build` already does. |
| **`PRE_CUT_CHECKLIST.md` walk, `test_projects/fixed`** | **The only thing that exercises any of this.** `reaper` is a scheduler-only codebase: `docex build dev` (currently broken), `docex test`'s reaper leg, and a real Ofelia fire against the dev-stage image all land here. Mod 107 owns migrating that project; the walk is where items 1-3 are actually proven. |

## Out of scope

`describe` (104) · rollback (105) · **any doctrine file** (106) · any version
artifact (107) · `test_projects/` content (107).

Two things I found and am **not** doing, both flagged rather than fixed:

- `test_projects/fixed/core/reaper/Dockerfile`'s header comment documents mod
  074 (*"`docex up dev` builds this `prod` stage locally (mod 074) so Ofelia can
  launch it in dev"*) and is false after this mod. `test_projects/` is Mod 107's.
- `_ensure_initial_dev_build`'s skip for scheduler-only codebases
  (`up.py:200-212`) reasons that they "aren't bind-mounted", which Mod 099 made
  half-false — their **exec service** is bind-mounted in `dev`, so host `dist/`
  is relevant to `docex build` for them now. Leaving the skip alone: `build.sh`
  populates `dist/` itself, so the pre-populate buys nothing, and the comment is
  Mod 099-adjacent rather than mine.

## Design questions — both settled by the C.O. before implementation

**1. Do not give a `dev` Ofelia job the codebase's bind mounts.** Declined for
the reason given below: a new interpolation contract the design record does not
draw is scope growth, and this mod already carries an unplanned regression fix.
The underlying wart — a dev job runs image-baked code while its sibling process
types run host code, so someone editing a job and seeing no effect will be
surprised — is flagged to the operator rather than fixed here.

**2. Defer the "is the `dev` stage job-runnable" gate.** A new `check` gate is a
new doctrine surface needing both code and a rule of record, and Mod 106 is
doctrine-only. It is also the weaker of the two: a `dev` stage that bakes no
artifact fails at the job's **first fire, visibly**, not silently — a
nice-to-have gate, not a missing guard. Filed as a follow-on.

The original text of both, as raised:

1. **Should a `dev` Ofelia job get the codebase's bind mounts?** (Recommendation:
   not in this mod.) After this mod a dev job runs image-baked code while its
   long-running siblings run host code — a parity gap, and it makes the job
   depend on the `dev` stage baking an artifact, which every doctrinal
   Dockerfile does (`RUN ./build.sh`) but `infrastructure.md` does not actually
   *require*. Ofelia's INI takes repeatable `volume =` lines and we already emit
   one, so the fix is mechanically small — emit `${DOCEX_PROJECT_ROOT}/core/<cb>/
   {src,dist}` mounts in `dev` and have `up` set that variable, exactly the
   mod-075 pattern that solved the same absolute-path problem for the secrets
   file. I am not taking it because it is a new interpolation contract the design
   record does not draw, it changes what code a dev job runs, and it would
   require un-skipping `_ensure_initial_dev_build` for scheduler-only codebases.
   Worth a follow-on mod inside this advance or a `Deferred` entry.

2. **Does anything need to guarantee the `dev` stage is job-runnable?**
   Related but separable. Today nothing checks that a scheduler's command can
   run in the image the trigger names; a missing artifact surfaces as an Ofelia
   log line at 03:00. If question 1 is declined, a `check` gate ("a codebase
   with a `scheduler` process type must produce a runnable `dev` stage") would
   be the alternative — but it is a new gate, which is above this mod's
   authority and probably belongs to `cicd.md` (Mod 106's file) rather than
   here. Flagging, not proposing.

Neither blocked implementation: the mod is written to be correct under the
status quo answer to both, which is what was approved.

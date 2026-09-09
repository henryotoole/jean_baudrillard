# Mod 103 — Implementation steps

Design: [`overview.md`](./overview.md). Read it first — in particular
[§ What the inherited warning turned out to be](./overview.md#what-the-inherited-warning-turned-out-to-be),
which is the evidence base for steps 1 and 3 and was established by running real
docker, not by reading docs.

All paths are relative to `docex/` (i.e. `/home/ubuntu/.claude/jean_baudrillard/docex/`).
Run tests with **`python3 -m pytest`**, never `uv run pytest`.

**Baseline: `python3 -m pytest tests/unit -q` → 950 passed.**
`python3 -m pytest tests/ -q` → 1014 passed, 17 deselected.
`python3 -m pytest -m integration --collect-only -q` → 17 collected.
Finish at **≥ 950 / ≥ 1014** with the same 17 integration tests collected.

**Do not touch:** any file under `doctrine/` (Mod 106 owns the doctrine sweep;
`specifics/scheduler.md` will read stale and that is planned) · `test_projects/`
(Mod 107) · `plans/core/*.md` (the C.O. updates those after review) ·
`CHANGELOG.md` or any version artifact (Mod 107) · `tests/unit/test_pipeline_projinfra.py`
and `uv.lock`, which are dirty in the tree for unrelated reasons.

---

## Step 1 — Retire mod 074's self-contained job image

### 1a. `src/docex/orchestrate/up.py`

Rewrite `_ensure_scheduler_image` (currently `:79-117`) as
`_ensure_codebase_image`. Two behavioral changes, nothing else:

- `docker.build_image(svc_dir, target="prod", tag=str(image_ref))` →
  **`target="dev"`**.
- The `BuildFailed` message stops talking about a "self-contained `prod` stage".

The docstring must carry the invariant sentence verbatim — **"In `dev`, the
codebase tag is the Dockerfile `dev` stage — for every process type, including a
cron job."** — plus the two facts that make it load-bearing, because the next
reader will otherwise re-derive mod 074's reasoning and re-break it:

1. Ofelia spawns the job through the Docker API with **no bind mounts**, so the
   job runs whatever `/service/dist` the image carries. The doctrinal `dev` stage
   bakes it (`RUN ./build.sh`), which is the same assumption
   `_ensure_initial_dev_build` already documents.
2. The tag is **codebase**-keyed (Mod 096) and Mod 099's exec service builds the
   same tag at `target: dev`. `compose run` only builds when the image is
   *absent*, so a `prod`-stage image sitting on that tag is reused by
   `docex build` / `test` / `migrate` — and the doctrinal `prod` stage carries
   no `build.sh` and no `test.sh`. Mod 074's `prod` build therefore **broke
   `docex build dev`** for any project with a scheduler-only codebase. Two
   consumers of one tag must agree on what is inside it.

Then the call site (`:213-216`):

```python
        # Mod 103: a scheduler-only codebase has no non-gated compose service,
        # so nothing in the compose graph builds its image — `up --build` skips
        # the `profiles: [exec]` exec service, and `compose run` builds only when
        # the image is absent. docex builds it here. A codebase that also
        # declares a long-running process type needs nothing: `compose up
        # --build` below builds that same tag, at the same `dev` target.
        for svc in scheduler_only_services(ctx):
            _ensure_codebase_image(ctx, docker, svc)
```

Note the loop source changes from `scheduler_services(ctx)` to
`scheduler_only_services(ctx)`. Drop `scheduler_services` from the import block
at `:20-30`.

Leave `_ensure_initial_dev_build` and its scheduler-only skip (`:200-212`)
alone — see [`overview.md` § Out of scope](./overview.md#out-of-scope). Its
comment at `:207-209` says schedulers "instead need a self-contained job image
built below (mod 074)"; update that sentence only, to name the new function and
drop "self-contained".

### 1b. `src/docex/orchestrate/_common.py`

**Delete `scheduler_services`** (`:110-123`) — it has exactly one consumer and
that consumer just changed. Then fix `scheduler_only_services`'s docstring
(`:126-143`), which opens *"Distinct from :func:`scheduler_services` because the
two call sites want different predicates"* and now dangles. It should say what
the predicate is for: a codebase with no long-running process type is the one
whose image no compose service builds and whose only compose contribution in
`test` is its exec service.

### 1c. `src/docex/emit/compose.py` — comments and docstrings only, no logic

Emission is already correct; **do not change what is emitted.** Verify before
editing, then record:

- `_ofelia_ini`'s docstring (`:352-367`) says `One [job-run "<svc>"] section`.
  Make it say the section name is the **two-segment compiled identity**
  (`api-nightly_cleanup`), and that `image` is the **codebase**'s image ref —
  shared with every sibling process type, which is why mod 074's separate job
  image is gone.
- At `:371` (`image = svc.body.get("image", "")`) add a one-line `WHY` noting
  `body["image"]` is keyed on the codebase (`compile.py:806`), so a job and its
  sibling `web` run one tag.

---

## Step 2 — Delete `_run_scheduler_tests`

`src/docex/orchestrate/test.py`:

- Delete `_run_scheduler_tests` (`:40-63`) entirely.
- In `run_test` step 3 (`:136-153`), delete the `schedulers` set, the
  `MOD 103 DELETES THIS BRANCH` comment block and the `if svc in schedulers`
  branch. Every codebase takes the one path:

```python
        # 3. test.sh for each core service, in the codebase's exec service.
        # Mod 103: no scheduler carve-out. The exec service is emitted for
        # every codebase — scheduler-only ones included — so a codebase with no
        # long-running container in the `test` stack still has somewhere to run
        # test.sh. (Mod 099's `test_8_scheduler_only_codebase_gets_an_exec_service`
        # pins the emission this depends on.)
        for svc in core_services(ctx):
            key = exec_service_key(ctx, _TEST_ENV, svc)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./test.sh"], build=True,
                env_file=env_file, project_dir=project_dir,
                project_name=project_name,
            )
```

- Drop the now-unused imports: `dns_label` (`:24`) and `scheduler_only_services`
  (from the `_common` block). `DockerClient` and `Path` are still used by
  `run_test`'s signature; keep them.
- The module docstring's step 3 (`:9`) says "Run each core service's test.sh,
  collecting exit codes" — still true; leave it.

(`build=True` comes from step 3 below. Write step 3 first if you prefer to keep
the suite green between edits.)

---

## Step 3 — `--build` on `test`-env one-offs

The rule: **in `test` the image *is* the artifact under test, so a one-off must
never run a stale one; in `dev` the source arrives by bind mount and the `dev`
stage exists precisely so `build.sh` can be re-invoked without rebuilding the
image.** Every call site below needs a `WHY` comment pointing at that asymmetry —
without one it reads as an inconsistency to anyone who does not know the bind
mount is doing the work.

Empirically established (see `overview.md`): `compose run` builds a missing image
but **never rebuilds a stale one**; `run --build` on a block with no `build:` key
is a clean rc-0 no-op.

### 3a. `src/docex/docker/client.py`

Add `build: bool = False` to the `compose_run_one_off` protocol signature
(`:81-101`), keyword-only, after `env`. Document it as: adds `--build`;
`compose run` otherwise reuses a stale image (it builds only when the image is
*absent*), which for a codebase with no non-gated compose service means nothing
ever refreshes that tag.

### 3b. `src/docex/docker/subprocess_client.py`

In `compose_run_one_off`, after the existing `["run", "--rm", "-T"]`:

```python
        if build:
            cmd.append("--build")
```

Keep the existing `-T` comment. Add a `WHY` for `--build` referencing the
"builds only when absent" behavior.

### 3c. Call sites

| File | Call | Pass |
| ---- | ---- | ---- |
| `orchestrate/test.py:120-126` | test-env `./migrate.sh` | `build=True` |
| `orchestrate/test.py` step 3 | `./test.sh` | `build=True` |
| `orchestrate/up.py:246-251` | post-up `./migrate.sh` | `build=(env == "test")` |
| `orchestrate/migrate.py:107-112` | dev/test `./migrate.sh` | `build=(env == "test")` |
| `orchestrate/build.py:138-141` | dev `./build.sh` | **nothing** — leave as is |

`run_test` passes `True` unconditionally because it *is* the test env by
construction (`_TEST_ENV`). `build.py` is dev-only and is the hot iteration loop
the asymmetry exists to protect — add a short comment there saying so, so a
future reader does not "fix" the omission.

Do **not** touch `emit/templates/playbook.yml.j2`. Fixed stage/prod migrate runs
`compose run` against an exec service with no `build:` block, pulling an image
that must not be rebuilt on the deploy host.

### 3d. `tests/conftest.py` — fake client

Accept the new kwarg and record it as a **side-call**, matching how
`project_dir` / `project_name` are already recorded, so no existing tuple
assertion changes:

```python
        if build:
            self.calls.append(
                ("compose_run_one_off_build", service, tuple(command))
            )
```

The primary `("compose_run_one_off", file, service, cmd)` key and the
`("exit", "compose_run_one_off", svc, cmd)` override key must stay exactly as
they are — many tests key off both.

---

## Step 4 — Tests

Target: net **+8 or more** unit tests. Nothing is deleted; three existing tests
are rewritten because their subject is deleted code, and one is repurposed.

### 4a. New mixed-codebase fixtures — `tests/unit/test_scheduler.py`

The existing fixtures put the scheduler in its **own** codebase
(`nightly_cleanup.nightly_cleanup`), where codebase and process names coincide,
so the two-segment identity claim is unfalsifiable and "exactly one sidecar" is
unexpressible. Add a module-scoped builder mirroring
`test_process_expansion_emit.py::_three_process_project` (`:64-88`) — copy
`sample_project` / `sample_project_elastic`, add **one** scheduler process type
to the existing `api` codebase, and compile:

```python
_JOB = {
    "role": "scheduler",
    "schedule": "0 3 * * *",
    "command": ["python", "-m", "jobs.cleanup"],
    "networks": ["internal"],
    "depends_on": ["appdb"],          # service-level env refs oblige it (rule 7)
    "resources": {"cpu": 0.25, "memory": "512MB", "disk": "25GB"},
}
```

Give the elastic variant whatever `disk` the elastic fixture's own process types
use, so Fargate tiering does not reject it. Two module-scoped fixtures:
`web_plus_job_fixed`, `web_plus_job_elastic`.

Then:

1. **`test_mixed_codebase_job_image_is_the_siblings_image`** — the INI's
   `image = …` value equals the `sample-dev-api-web` block's `image`, asserted as
   an **equality between the two emitted values**, not against a literal. A
   literal passes even if both drift together; the equality is the invariant.
2. **`test_mixed_codebase_job_identity_is_two_segment`** — the INI section is
   `[job-run "api-nightly_cleanup"]`, the configs key is
   `ofelia_api-nightly_cleanup`, and the Ofelia compose key is
   `sample-dev-api-nightly_cleanup-scheduler`. Here codebase ≠ process, so this
   actually tests the claim.
3. **`test_mixed_codebase_emits_exactly_one_sidecar`** — `dev` compose has
   exactly one key ending `-otelcol`, and it is `sample-dev-api-web-otelcol`.
   This is the per-process restatement of the sidecar rule: one codebase, one
   sidecar for the web process, none for the job — which the old service-level
   phrasing could not express.
4. **`test_mixed_codebase_elastic_job_has_no_service_or_target_group`** — on
   `stage`: no `aws_ecs_service "api-nightly_cleanup"`, no
   `aws_lb_target_group "api-nightly_cleanup"`, no `otelcol` inside the job's
   task definition; and the sibling `api-web` has its `aws_ecs_service` and its
   `api-web-otelcol` container. (Reuse `_slice_td` / `_stage_hcl`.)

### 4b. `tests/unit/test_orchestrate_test.py`

5. **Rewrite `test_run_test_scheduler_uses_one_off`** →
   `test_run_test_scheduler_only_codebase_uses_its_exec_service`. Assert:
   `compose_run_one_off` `./test.sh` services are
   `["sample-test-api-exec", "sample-test-nightly-cleanup-exec"]` (sorted
   codebase order — `core_services` is sorted, so `api` precedes
   `nightly_cleanup`); and `run_test` makes **zero** `build_image` calls and
   **zero** `run_one_shot` calls. Keep a docstring line recording what was
   deleted and why, so `git log -S_run_scheduler_tests` lands somewhere useful.
6. **Rewrite `test_run_test_scheduler_run_failure_returns_code`** to key the
   failure on
   `("exit", "compose_run_one_off", "sample-test-nightly-cleanup-exec", ("./test.sh",))`
   → `rc == 3`, teardown still ran.
7. **Repurpose `test_run_test_scheduler_build_failure_short_circuits`** →
   `test_run_test_short_circuits_before_later_codebase`. Its real subject was
   short-circuit semantics, which survive: fail `api`'s `./test.sh` and assert
   the scheduler codebase's exec service never receives one, plus teardown ran.
8. **New `test_run_test_one_offs_build_first`** — every `compose_run_one_off`
   issued by `run_test` (migrate **and** test) has a matching
   `("compose_run_one_off_build", …)` side-call.

### 4c. `tests/unit/test_orchestrate_up.py`

9. **Rewrite `test_up_dev_builds_scheduler_image_from_prod_stage`** →
   `test_up_dev_builds_scheduler_only_codebase_image_from_dev_stage`: assert
   `("build_image", str(root / "core" / "nightly_cleanup"), "dev",
   "sample/nightly_cleanup:0.1.0")` is in `fake_docker.calls`.
10. **New `test_up_dev_builds_no_prod_stage_image`** — **no** `build_image` call
    anywhere in `up dev` has `target == "prod"`. This is the mod-074 deletion
    pin and deserves its own name: a `prod`-stage image on the dev tag is
    precisely the state that broke `docex build`.
11. **New `test_up_dev_does_not_rebuild_a_long_running_codebases_image`** — the
    `api` codebase (which has a `web` process) gets **no** `target="dev"`
    `build_image` call; compose builds that tag. Pins the scoping change from
    `scheduler_services` to `scheduler_only_services`. (`api` still gets its
    `target="build"` call from `_ensure_initial_dev_build` — assert on
    `target == "dev"` only.)
12. **New `test_up_test_migrate_builds_but_up_dev_does_not`** — `run_up(env="test")`
    produces a `compose_run_one_off_build` side-call and `run_up(env="dev")` does
    not. Use a fixture whose codebase owns a schema (`sample_ctx` /
    `scheduler_ctx` both have `schema_owned_by: api`). The dev half is as
    load-bearing as the test half: it pins that the hot loop was not slowed.

### 4d. `tests/unit/test_orchestrate_migrate.py`

13. **New** — `migrate test` issues the `--build` side-call, `migrate dev` does
    not.

### 4e. Deletion pins — `tests/unit/test_orchestrate_common.py` (or the closest existing home)

14. **New `test_mod_074_and_the_scheduler_test_carveout_are_gone`** —
    `not hasattr(docex.orchestrate.test, "_run_scheduler_tests")` and
    `not hasattr(docex.orchestrate._common, "scheduler_services")`, with a
    docstring naming this mod. Same shape as Mod 099's `primary_process` /
    `compose_service_key` pin; find that test and mirror it.

### 4f. One docstring touch

`tests/unit/test_exec_service.py::test_8_scheduler_only_codebase_gets_an_exec_service`
(`:274-300`) describes the carve-out as still standing ("**This is the seam Mod
103 removes the carve-out against**"). Change that sentence to record that Mod
103 has removed it and that `test_orchestrate_test.py` now exercises the seam.
Do not change any assertion.

---

## Step 5 — Verify

```
python3 -m pytest tests/unit -q                    # expect >= 950
python3 -m pytest tests/ -q                        # expect >= 1014, 17 deselected
python3 -m pytest -m integration --collect-only -q # expect exactly 17
```

Then confirm nothing outside this mod's blast radius moved:

```
git status --porcelain
```

Only these should be modified: `src/docex/orchestrate/{up,test,_common,migrate,build}.py`,
`src/docex/docker/{client,subprocess_client}.py`, `src/docex/emit/compose.py`,
`tests/conftest.py`, `tests/unit/test_{scheduler,orchestrate_test,orchestrate_up,orchestrate_migrate,orchestrate_common,exec_service}.py`,
plus the new files under `docex/plans/modifications/103_scheduler_process_type/`.
The pre-existing dirty entries (staged `campaigns/` → `advances/` renames,
`tests/unit/test_pipeline_projinfra.py`, `uv.lock`, and everything under
`doctrine/`) must be untouched.

**Do not commit.** The C.O. reviews for drift, updates `plans/core/*.md`, and
commits.

## If something does not hold

Two places where a surprise means *stop and report*, not improvise:

- **A test asserts mod-074 behavior that step 1 breaks and is not in the list
  above.** The list was built by grep; if there is a fourth, it may encode a
  reason the design missed.
- **`build=True` changes an existing test's recorded call sequence in a way the
  side-call shape does not absorb.** That would mean a test keys on the fake's
  call *ordering* rather than its contents, and the fix is a design question
  about the fake, not a quick edit.

# Mod 157 — Implementation steps

Bug fix + coverage for the container-vessel entrypoint doubling. Work entirely
inside `/home/ubuntu/.claude/jean_baudrillard/docex/`. All paths below are
relative to that docex project root.

**Do NOT touch** `plans/advances/009_test_overhaul/report.md` (it belongs to the
coordinator; leave it untracked and unstaged).

Background (already diagnosed and validated): the vessel builds
`command = ["docex", "__run-job", run_id]` and the cloned image has
`ENTRYPOINT ["docex"]`, so the effective argv is `docex docex __run-job <id>` →
`unknown command 'docex'` → exit 64, and the job body never runs. The fix makes
the entrypoint explicit at the `run_detached` boundary so the argv is fully
determined in one place.

---

## Step 1 — `run_detached` gains an explicit `entrypoint` (concrete client)

File: `src/docex/docker/subprocess_client.py`, method `run_detached` (~L496).

1. Add a keyword-only parameter `entrypoint: str | None = None` to the signature
   (place it after `group_add`).
2. When `entrypoint` is not None, emit `--entrypoint <entrypoint>` on the
   `docker run` command line **before the image**. The `docker run` flag order
   is: `run -d --name <name>` … existing flags … then (new) `--entrypoint` …
   then `image`, then `command`. Concretely, insert the emission right before
   `cmd.append(image)`:

   ```python
   if entrypoint is not None:
       cmd.extend(["--entrypoint", entrypoint])
   cmd.append(image)
   cmd.extend(command)
   ```

Keep the docstring accurate: note that `entrypoint`, when given, overrides the
image's `ENTRYPOINT` so the effective argv is exactly `<entrypoint> <command...>`.

## Step 2 — abstract signature (interface)

File: `src/docex/docker/client.py`, abstract `run_detached` (~L303).

Add the same `entrypoint: str | None = None` keyword-only parameter to the
abstract signature, and add one sentence to the docstring: when `entrypoint` is
provided it is passed as `docker run --entrypoint`, overriding the image's
`ENTRYPOINT`, so the effective argv is `<entrypoint> <command...>`.

## Step 3 — the vessel passes the explicit entrypoint (THE FIX)

File: `src/docex/jobs/vessel.py`, method `ContainerVessel.launch` (~L54-73).

1. Change line 62 from:
   ```python
   command = ["docex", "__run-job", run_id]
   ```
   to:
   ```python
   # The image's ENTRYPOINT is ["docex"] (see Dockerfile). We set the
   # entrypoint EXPLICITLY here rather than relying on that, and pass only the
   # args after it, so the effective container argv is exactly
   # `docex __run-job <run_id>` regardless of the cloned image's ENTRYPOINT —
   # this is what prevents the entrypoint doubling (`docex docex __run-job …`
   # → "unknown command 'docex'", exit 64) that mod 157 fixed.
   command = ["__run-job", run_id]
   ```
2. In the `run_detached(...)` call immediately below, add `entrypoint="docex"`
   as a keyword argument.
3. Update the `launch` docstring's first line if it says "running
   `docex __run-job <run_id>`" — that description stays correct; just make sure
   nothing still claims the command list begins with `"docex"`.

## Step 4 — add the `noop` diagnostic job body

File: `src/docex/jobs/commands.py`.

1. Add a tiny body function near the other `_run_*_body` functions:
   ```python
   def _run_noop_body(ctx, docker, params) -> int:  # ctx/docker/params unused
       """A do-nothing job body: a minimal substrate-liveness / diagnostic no-op.

       Exists so the vessel substrate can be exercised end-to-end (real docex
       image → detached vessel → `run_in_vessel` → authoritative `exit` file)
       with a body that returns 0 in well under a second, without standing up a
       real test/check/merge. It performs no I/O and cannot affect any stack —
       see tests/integration/test_vessel_real_image.py.
       """
       return 0
   ```
2. Register it in `_JOB_BODIES`:
   ```python
   _JOB_BODIES = {
       "test": _run_test_body,
       "check": _run_check_body,
       "merge": _run_merge_body,
       "noop": _run_noop_body,
   }
   ```

No reaper change is needed: `reaper._teardown_leaked_resources` already routes
any kind that is not `test`/`check`/`merge` to its safe no-op branch.

## Step 5 — FakeDockerClient records the `entrypoint` kwarg

File: `tests/conftest.py`, `FakeDockerClient.run_detached` (~L259-269).

1. Add `entrypoint=None` to the signature (keyword, after `group_add`).
2. Record it on the primary call tuple so unit tests can assert it. Change the
   primary append to include the entrypoint:
   ```python
   self.calls.append(
       ("run_detached", name, image, tuple(command), entrypoint)
   )
   ```
   Leave the `run_detached_spec` tuple unchanged.

Because this widens the primary `run_detached` tuple from 4 to 5 elements, check
every unit test that unpacks it and fix the unpacking (see Step 6; also grep:
`grep -rn 'run_detached' tests/unit`). Known consumers to verify/adjust:
`tests/unit/test_jobs_vessel.py`, `tests/unit/test_jobs_commands.py`,
`tests/unit/test_jobs_check_merge.py`. Any that unpack
`_, name, image, command = detached[0]` must become
`_, name, image, command, entrypoint = detached[0]` (or index explicitly). Any
that only index `detached[0][2]` (image) are unaffected.

## Step 6 — correct the unit test that currently ENCODES the bug

File: `tests/unit/test_jobs_vessel.py`.

1. In `test_launch_issues_one_run_detached_with_the_job_command`, the current
   assertions unpack `_, name, image, command = detached[0]` and assert
   `command == ("docex", "__run-job", "…")`. Change to:
   - unpack the widened tuple: `_, name, image, command, entrypoint = detached[0]`
   - assert `command == ("__run-job", "20260824T000000Z-abc123")`
   - assert `entrypoint == "docex"`
   - add a comment tying the invariant to the Dockerfile: the image's
     `ENTRYPOINT ["docex"]` means the vessel must pass only the args after it and
     set the entrypoint explicitly, so the effective argv is
     `docex __run-job <id>` and never doubles.
2. Fix any other unpacking of the primary tuple in this file that Step 5 widened
   (e.g. the `detached = [...][0]` lines in
   `test_launch_clones_the_inspected_spec_and_filters_env` and
   `test_launch_falls_back_to_reconstruct_on_introspection_failure` index
   `detached[2]` for the image — those are fine as-is, but re-run the file to be
   sure).

## Step 7 — NEW real-image end-to-end vessel test

Create `tests/integration/test_vessel_real_image.py`.

Requirements it must satisfy:
- Marked `@pytest.mark.integration` (so it runs only in the stack-backed lane and
  auto-skips when docker is unreachable, per `tests/integration/conftest.py`).
- A **session-scoped fixture** builds the docex image fresh from the repo
  Dockerfile into the dedicated tag `docex:jobs-vessel-itest`. Build with
  `docker build -t docex:jobs-vessel-itest <repo_root>` where `repo_root` is the
  docex project root (`Path(__file__).resolve().parents[2]`). Do **not** reuse
  any existing `docex:<version>` tag. Fail the test loudly if the build fails.
- The test itself:
  1. Uses `tmp_path` as the project root; write a minimal `project.yml`:
     ```
     name: sample
     version: "0.1.0"
     docex_version: "jobs-vessel-itest"
     ```
  2. Create a real run record of `kind="noop"` via `docex.jobs.record`:
     `record.new_run_id()`, then `record.create_record(tmp_path, record.RunMeta(
     id=run_id, kind="noop", scope="itest/vessel-real", slot=1,
     vessel_kind="container", vessel_name=f"docex-vessel-real-{run_id}",
     created_at=record.now_iso(), docex_version="jobs-vessel-itest", params={}))`.
     (Pass a `Path`, not a str.)
  3. Build a `ctx` with `types.SimpleNamespace`:
     `ctx = SimpleNamespace(project_root=tmp_path,
     project=SimpleNamespace(name="sample", docex_version="jobs-vessel-itest"))`.
     On the host, `inspect_self` raises, so `ContainerVessel.launch` takes the
     `_reconstruct_spec` path, which resolves the image to
     `docex:jobs-vessel-itest`, mounts the docker socket + the project root, and
     runs as the host uid:gid — exactly the real launch path.
  4. `docker = SubprocessDockerClient()`;
     `res = ContainerVessel(docker, vessel_name).launch(ctx, run_id)`.
     Assert `res.name_conflict is False` and `res.rc == 0` (the detached
     `docker run` create succeeded).
  5. Block on the authoritative exit file:
     `assert commands.run_job_wait(ctx, docker, run_id, timeout=120) == 0` and
     `assert record.read_exit(tmp_path, run_id) == 0`.
     - This is the fail-on-bug / pass-on-fix property: with the pre-fix command
       the vessel exits 64 and writes **no** exit file, so `run_job_wait` times
       out and returns `WAIT_TIMEOUT_EXIT` (75) → the `== 0` assertion FAILS.
       With the fix, `run_in_vessel` runs the `noop` body and writes `exit` = 0.
  6. After it exits (the vessel is not `--rm`), assert
     `docker.container_running(vessel_name) is False` and
     `record.classify(tmp_path, run_id, docker) is record.Outcome.TERMINAL`.
  7. `finally`: `subprocess.run(["docker", "rm", "-f", vessel_name], ...,
     check=False)` to reap the stopped vessel. (The integration conftest's
     `_reclaim_root_owned_residue` fixture returns any root-owned tmp residue to
     the host uid automatically.)

Model the structure on the existing `tests/integration/test_job_vessel_real.py`
(imports, `@pytest.mark.integration`, the `try/finally` docker-rm), but drive the
**real `ContainerVessel.launch` through the real image** rather than calling
`docker_client.run_detached` with alpine directly.

Add a module docstring explaining this is the coverage the 1388-green suite was
missing: no prior test drove the real docex image as a vessel, so the entrypoint
doubling could not surface.

## Step 8 — prove fail-on-bug / pass-on-fix, then run the full suite

1. **Prove the new test FAILS on the bug.** Temporarily revert only the vessel
   change (Step 3): set `command = ["docex", "__run-job", run_id]` and drop the
   `entrypoint="docex"` kwarg, then run:
   `python -m pytest tests/integration/test_vessel_real_image.py -m integration -v`
   Confirm it FAILS (the `run_job_wait(...) == 0` assertion fails because no exit
   file appears). Record the observed failure.
2. **Restore the fix** (Step 3 as written) and re-run the same command; confirm
   it PASSES. Record that.
   - NOTE: the unit test in Step 6 asserts the *fixed* argv, so with the bug
     re-applied that unit test would also fail — that is expected. Do the
     bug-revert proof by running only the integration file (as above) so the
     proof is isolated to the real-image test.
3. **Full green:** run the entire suite in the FOREGROUND (background runs have
   died silently this session), with a generous timeout:
   `python -m pytest tests` (do not background it). Ensure it is fully green and
   record the new total (it should be the prior total + at least the one new
   integration test; the `noop` body adds no new test count by itself).

## Notes / out of scope

- Do **not** edit core planning docs or CHANGELOG here — the coordinating
  corporal handles the documentation step separately.
- No `infra.yml` or contract changes are required for this mod.
- Report back: the vessel/`run_detached`/`commands` diffs, the new test file, the
  explicit fail-on-bug and pass-on-fix observations from Step 8.1/8.2, and the
  final `python -m pytest tests` summary line with the new total.

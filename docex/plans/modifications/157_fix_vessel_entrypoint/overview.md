# Mod 157 — Fix the vessel entrypoint doubling (and close the coverage gap)

## Problem

The flagship durable-job / container-vessel surface is broken end-to-end through
the real `docex` image. Every vessel path dies on launch with
`error: unknown command 'docex'` (exit 64), so the job body never runs.

### Root cause (confirmed, not re-derived)

- `src/docex/jobs/vessel.py:62` builds `command = ["docex", "__run-job", run_id]`.
- The vessel clones the foreground container's image, whose Dockerfile last line
  is `ENTRYPOINT ["docex"]`. `SubprocessDockerClient.run_detached`
  (`src/docex/docker/subprocess_client.py:496`) appends the command **after** the
  image and does **not** override the entrypoint.
- Effective container argv = `docex docex __run-job <id>`. `docex` reads the
  first arg `docex` as its subcommand → "unknown command 'docex'" → exit 64.
  `run_in_vessel` (the `__run-job` handler) never executes, so no authoritative
  `exit` file is ever written.

Confirmed against a **freshly built** image (`docker build .`, ~4 s cached):

| argv | result |
| ---- | ------ |
| `docex docex __run-job <id>` (current/bug) | `unknown command 'docex'`, exit 64, **no `exit` file** |
| `docex __run-job <id>` (entrypoint supplies `docex`) | reaches `run_in_vessel`, **writes the `exit` file** |

Full manual end-to-end (fresh image + socket + project bind-mounted + a real
`kind=noop` run record) confirmed: the fix argv drives `run_in_vessel` to
completion and writes an authoritative `exit` file; the bug argv writes nothing.

### Why the 1388-green suite missed it

No test drives the **real docex image** as a vessel:

- `tests/integration/test_job_vessel_real.py` and `test_check_job_vessel_real.py`
  launch **`alpine:latest`** with a shell one-liner ("so no docex image is
  needed"). alpine has no `docex` entrypoint, so the doubling cannot surface.
- `tests/integration/test_slots_real.py` calls `run_test(...)` **in-process**,
  bypassing the vessel / detach path entirely.
- `tests/unit/test_jobs_vessel.py:30` actively **encodes the bug**: it asserts
  `command == ("docex", "__run-job", ...)`. A green unit test froze the defect.

## Blast radius

Every vessel path: `docex test` (foreground and `--detach`), `docex test
integration`, `docex test --slots N`, and — via the same `_launch_durable_job`
substrate — `docex check` / `docex merge` (foreground and `--detach`). Only the
synchronous in-process `docex test unit` lane escapes (it never uses the vessel).

## Deliverable 1 — the fix (chosen form + justification)

**Chosen form: make the entrypoint explicit at the `run_detached` boundary**, not
merely drop the leading `"docex"`.

- Add an optional `entrypoint: str | None = None` parameter to `run_detached`
  (abstract `docker/client.py` + concrete `docker/subprocess_client.py`). When
  set, emit `--entrypoint <value>` before the image.
- In `vessel.py`, launch with `entrypoint="docex"` and
  `command = ["__run-job", run_id]`.

**Why this over the minimal "just drop `docex`" (leaving the entrypoint
implicit):** both forms fix today's symptom, but the minimal form keeps the
effective argv **split across two files** — the vessel supplies the args, the
Dockerfile supplies the `docex` half — and silently re-breaks if the image's
`ENTRYPOINT` ever changes (a wrapper script, an added default subcommand,
removal). The explicit form makes the vessel's argv **fully determined in one
place**: `docker run --entrypoint docex <image> __run-job <id>` yields exactly
`docex __run-job <id>` regardless of what the cloned image's `ENTRYPOINT`
happens to be. That is precisely the class of assumption-vs-reality mismatch
that produced this bug; the explicit form deletes the assumption rather than
re-stating it. The `docex` console script is on `PATH` in the image, so the
override is safe. Cost is one optional, backward-compatible parameter.

`entrypoint=None` is the default, so the two alpine-based integration tests and
every other `run_detached` caller are byte-unchanged.

## Deliverable 2 — close the coverage gap (the crux)

### New real-image end-to-end test

Add `tests/integration/test_vessel_real_image.py` (marked
`@pytest.mark.integration`) that drives the **real docex image** as a vessel and
asserts it **runs the job body and writes the authoritative `exit` file** — not
that it dies on entrypoint doubling.

Flow:
1. A **session-scoped fixture builds the docex image fresh** from the repo
   Dockerfile into a dedicated tag `docex:jobs-vessel-itest`.
2. The test creates a temp project (minimal `project.yml`) and a real
   `kind=noop` run record via `docex.jobs.record`.
3. It constructs a `ctx` whose `project.docex_version` equals the built tag and
   calls `ContainerVessel(SubprocessDockerClient(), name).launch(ctx, run_id)`.
   On the host, `inspect_self` raises (host is not a container), so the launch
   takes the real `_reconstruct_spec` path — which mounts the docker socket and
   the project and resolves the image to `docex:jobs-vessel-itest`. This
   exercises the **actual `vessel.py` command construction** through the real
   image.
4. It blocks on the authoritative `exit` file via `commands.run_job_wait(...)`
   and asserts the run's real code, plus `record.read_exit(...)`.

**Fail-on-bug / pass-on-fix** (already proven manually, to be re-proven in
execution): with the buggy command the vessel exits 64 and writes **no** `exit`
file, so `run_job_wait` times out (returns `WAIT_TIMEOUT_EXIT = 75`) and the
assertion fails. With the fix, `run_in_vessel` runs the `noop` body and writes
`exit` = 0, so the assertion passes.

### Affordability

- The image is **built once per session** (session-scoped fixture); with docker
  layer cache the rebuild is ~4 s (only the source-copy layers change). The job
  body is a **trivial `noop`**, not a real suite — the container runs for
  well under a second.
- The fixture **always builds fresh from the current tree into a dedicated
  tag**; it deliberately does **not** reuse an existing `docex:<version>` tag.
  Reusing a possibly-stale image is exactly how this class of bug hides (the
  operator's local `docex:2.1.0` is currently stale and predates `__run-job`
  registration — reusing it would give a false result). The dedicated tag also
  never clobbers the operator's real `docex:<version>` images.

### Cheap unit assertion (addition, not a substitute)

Update `tests/unit/test_jobs_vessel.py` so it asserts the **fixed** argv: the
`run_detached` command is `("__run-job", run_id)` and the call carries
`entrypoint == "docex"`, with a comment tying the invariant to the Dockerfile
`ENTRYPOINT ["docex"]`. The FakeDockerClient in `tests/conftest.py` is extended
to accept and record the `entrypoint` kwarg.

### Small production-surface addition (flagged)

To give the real-image test a genuinely trivial body that returns 0, a built-in
`noop` job kind is added to `_JOB_BODIES` in `src/docex/jobs/commands.py` (a
3-line body returning 0). This is a legitimate substrate self-test primitive:
`noop` is already referenced as a `kind` by the existing vessel integration
tests, and it turns "does the vessel run a body end-to-end" into something an
operator (and this test) can exercise cheaply. The reaper needs **no** wiring —
`_teardown_leaked_resources` already routes unknown kinds to its safe no-op
branch (`reaper.py:103-105`).

## Files touched (planned)

- `src/docex/jobs/vessel.py` — explicit `entrypoint="docex"`, command drops the
  leading `"docex"`; comment ties it to the Dockerfile `ENTRYPOINT`.
- `src/docex/docker/subprocess_client.py` — `run_detached` gains
  `entrypoint` param, emits `--entrypoint`.
- `src/docex/docker/client.py` — abstract `run_detached` signature + docstring.
- `src/docex/jobs/commands.py` — add the `noop` job body to `_JOB_BODIES`.
- `tests/conftest.py` — FakeDockerClient records the `entrypoint` kwarg.
- `tests/unit/test_jobs_vessel.py` — assert the fixed argv + entrypoint.
- `tests/integration/test_vessel_real_image.py` — **new** real-image E2E test.

No `infra.yml` / contract / doctrine-spec change (pure bug fix). Docs +
CHANGELOG handled at the documentation step (a `test_projects.md` /
docex-core note on the real-image vessel test + the entrypoint invariant, and a
mod-157 `Fixed` changelog entry).

## Design questions

None blocking. Two decisions made within authority, flagged for awareness:
1. **Fix form** = explicit `--entrypoint docex` (justified above) rather than the
   minimal implicit-entrypoint drop.
2. **`noop` job body** added to production `_JOB_BODIES` to make the real-image
   test's body trivial and its assertion unambiguous (`exit == 0`). If you'd
   rather keep zero production surface, the fallback is a `kind=noop` record
   with **no** registered body: `run_in_vessel` still runs and writes `exit == 1`
   (the "no body" path), which still catches the bug — the assertion just keys
   on `1` instead of `0`. I chose the body because it more honestly realizes
   "the vessel runs the job body."

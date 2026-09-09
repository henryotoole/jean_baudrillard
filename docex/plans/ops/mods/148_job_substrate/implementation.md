# Mod 148 — Implementation steps

Fresh-context implementation of the **`job` substrate + `docex test` as its first
(container) vessel**. Design and rationale live in [`overview.md`](./overview.md);
`sarge`'s rulings on the five design questions are folded in below. Build to this
file; where it says "see overview" the reasoning is there.

**Scope reminder (do NOT exceed):** container vessel for `test` only; no
host-process vessel (Mod 149), no slot axis / `--slots` (Wave 3), no scoped runs /
no-stack lane (Mod 151/Mod 6), no `.docex/checks/` (Mod 150). `docex test` still
runs BOTH shims in the stack, totally, exactly as Mod 147 left it — you are
wrapping that body in durable-job machinery, not changing what it runs.

**Do NOT edit doctrine prose, docex core planning docs, or the CHANGELOG** — those
are the coordinator's documentation step. This file covers **code + tests +
`docex/.gitignore`** only.

Test invocation is `python -m pytest tests` (canonical) — never bare `pytest`;
`-m integration` must run **alone** (see `plans/core/docex_process.md § Running the
automated tests`).

---

## 0. Orientation (read before writing)

- `src/docex/orchestrate/test.py` — `run_test(ctx, docker, *, project_dir=None,
  env_file_override=None, project_name=None) -> int`. **This is the "job body" for
  kind=test. Leave it unchanged.** It does compose up → migrate → both shims →
  `finally` compose down, returns an exit code.
- `src/docex/orchestrate/_common.py` — `env_compose_project(ctx, env)`
  (`<dns_label>-<env>`), `compose_file_for`, `env_file_for` (pure; None if absent),
  `aggregate` is in `orchestrate/aggregate.py`.
- `src/docex/naming.py` — `dns_label(name)`.
- `src/docex/docker/{client.py,subprocess_client.py}` — the `DockerClient`
  protocol + its only-place-`subprocess`-is-imported implementation. You ADD
  methods here.
- `src/docex/__main__.py` — argparse dispatcher: `_HELP_TEXT`, `_GROUPS`,
  `_cmd_*`, `_build_handler_table`, `main`.
- `src/docex/pipeline/check.py` — calls `run_test(...)` directly. **Must remain
  untouched and green** (it does NOT use the vessel).
- `tests/conftest.py` — defines `sample_ctx`, `fake_docker`, `multi_ctx` fixtures.
  Read the `fake_docker` recording client before extending it.

---

## 1. New package `src/docex/jobs/` (ruling Q1: top-level, cross-cutting)

Create `src/docex/jobs/__init__.py` (empty or re-exporting the public verbs) and
the four modules below.

### 1a. `src/docex/jobs/record.py` — the on-disk handle

Constants and types:

```python
RUNS_RELDIR = ".docex/runs"
ORPHAN_EXIT_CODE = 137          # ruling Q5: 128+9 (SIGKILL) — reads as "killed"

class Outcome(enum.Enum):
    TERMINAL = "terminal"        # exit file present
    LIVE = "live"                # no exit file, vessel running
    ORPHAN = "orphan"            # no exit file, vessel dead/absent
```

`@dataclass RunMeta`: `id, kind, scope, slot, vessel_kind, vessel_name,
created_at, docex_version, params: dict`. `to_json()/from_json()`.

`@dataclass RunStatus`: `state, started_at, updated_at, finished_at, exit_code`.
`state ∈ {"launching","running","succeeded","failed","orphaned"}`.

Functions (all take `project_root: Path`):

- `runs_dir(project_root) -> Path` → `project_root / ".docex" / "runs"`.
- `new_run_id() -> str` → `f"{utcnow:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"`
  (sortable; collision-free within a second). Use `datetime.now(timezone.utc)`.
- `run_dir(project_root, run_id) -> Path`.
- `create_record(project_root, meta: RunMeta) -> Path` — `mkdir(parents=True)`,
  write `meta.json`, write `status.json` with `state="launching"`. Return the dir.
- `read_meta / read_status(project_root, run_id) -> …|None` — return None on
  missing/unreadable (degrade-safe, never raise).
- `write_status(project_root, run_id, status: RunStatus)` — overwrite `status.json`
  (also bump `updated_at`).
- `exit_path / log_path(project_root, run_id) -> Path`.
- `read_exit(project_root, run_id) -> int | None` — parse the `exit` file; None if
  absent/unparseable.
- `write_exit_atomic(project_root, run_id, code: int)` — write to a temp file in
  the same dir, `os.replace()` onto `exit`. **Atomic** — this is the authoritative
  terminal signal (D3).
- `list_run_ids(project_root) -> list[str]` — dir names under `runs_dir`, **sorted
  descending** (most recent first). Missing dir → `[]`.
- `classify(project_root, run_id, docker) -> Outcome` — the **shared primitive**
  (overview § 5): `read_exit is not None → TERMINAL`; else
  `docker.container_running(meta.vessel_name)` — `True → LIVE`, else `→ ORPHAN`.
  A record with no readable meta classifies `ORPHAN`.

### 1b. `src/docex/jobs/vessel.py` — the container vessel (ruling Q3)

```python
class VesselIntrospectionError(RuntimeError): ...

@dataclass
class LaunchResult:
    rc: int
    name_conflict: bool          # True iff docker refused on an existing --name
```

`class ContainerVessel:`
- `__init__(self, docker, vessel_name: str)`.
- `is_running(self) -> bool | None` → `docker.container_running(self.vessel_name)`.
- `remove(self) -> int` → `docker.container_rm(self.vessel_name)` (never `-f`;
  callers only rm a **non-running** container).
- `launch(self, ctx, run_id) -> LaunchResult`:
  1. `spec = self._resolve_spec(ctx)` (a plain dict — see below).
  2. `command = ["docex", "__run-job", run_id]`.
  3. Return `docker.run_detached(name=self.vessel_name, image=spec["image"],
     command=command, binds=spec["binds"], user=spec["user"], env=spec["env"],
     workdir=spec["workdir"], group_add=spec["group_add"])` mapped to
     `LaunchResult`. **The vessel is NOT `--rm`** (name must persist for
     classify/reap — ruling Q3).
- `_resolve_spec(self, ctx) -> dict`:
  - `try: raw = docker.inspect_self()` — clone the foreground container (ruling Q3,
    guards a & c). On `VesselIntrospectionError` (including `$HOSTNAME` not
    resolving to a container) **log a warning to stderr and fall back** to
    `self._reconstruct_spec(ctx)` — never mislaunch silently.
  - **Env filtering (guard b):** from the inspected env, carry **only `HOME`**
    (the one var the shim adds that the vessel needs). Do **not** propagate `TERM`
    or any `DOCEX_*` (e.g. `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` — irrelevant to
    `test` and behavior-changing). The image's own `ENV` applies automatically at
    `docker run`, so nothing else needs copying.
  - Carry faithfully: `image` (`.Config.Image`), `binds`
    (`.HostConfig.Binds` — the `src:dst[:mode]` strings), `user` (`.Config.User`),
    `workdir` (`.Config.WorkingDir`), `group_add` (`.HostConfig.GroupAdd`).
- `_reconstruct_spec(self, ctx) -> dict` — **defensive fallback** (ruling Q3a; keep
  this knowledge): reconstruct the documented shim mount contract from
  `ctx.project` — image `f"docex:{ctx.project.docex_version}"` (matches the shim's
  `docex:$DOCEX_VERSION`, local store, no registry prefix), binds for
  `PROJECT_ROOT:PROJECT_ROOT`, `/etc/passwd:ro`, `/etc/group:ro`,
  `/var/run/docker.sock`, `$HOME/.docker`, user `f"{os.getuid()}:{os.getgid()}"`,
  env `[f"HOME={os.environ['HOME']}"]`, workdir `str(ctx.project_root)`, group_add
  from the docker socket gid best-effort. This path is only reached if
  self-inspection fails; a warning already told the operator.

### 1c. `src/docex/jobs/reaper.py` — single-run self-heal (F4)

```python
@dataclass
class PreflightResult:
    proceed: bool
    reason: str                  # populated on refusal
```

`preflight(ctx, docker, *, scope: str, vessel_name: str) -> PreflightResult`:
- `running = docker.container_running(vessel_name)`.
- `running is True` → **REFUSE**: `PreflightResult(False, "a run is already in
  progress for scope <scope> (vessel <vessel_name>); wait for it (docex job wait
  <id>) or let it finish")`. Do not touch it.
- `running is False` → a dead same-named container exists (completed OR orphaned):
  - Find the record for this vessel: the newest run id whose `meta.vessel_name ==
    vessel_name` (walk `list_run_ids` + `read_meta`).
  - If that record exists and `read_exit(...) is None` → **ORPHAN self-heal**
    (overview § 5): `write_exit_atomic(ORPHAN_EXIT_CODE)`,
    `write_status(state="orphaned", finished_at=now, exit_code=ORPHAN_EXIT_CODE)`,
    then **tear down the leaked stack**: `compose_down` with
    `compose_file_for(ctx,"test")`, `project_name=env_compose_project(ctx,"test")`,
    `env_file=env_file_for(ctx,"test")` (best-effort; may be None),
    `preserve_volumes=False`. (A TERMINAL record — exit file already present — is a
    cleanly-completed prior run; no synth, no teardown.)
  - `docker.container_rm(vessel_name)` to free the name.
  - `PreflightResult(True, "")`.
- `running is None` (absent) → nothing to reap → `PreflightResult(True, "")`.

### 1d. `src/docex/jobs/commands.py` — the verbs + the in-vessel entrypoint

Module constants: `LOCK_HELD_EXIT = 75` (EX_TEMPFAIL — "busy, retry"; used for a
refusal). `_JOB_BODIES = {"test": lambda ctx, docker: run_test(ctx, docker)}`
(import `run_test` lazily inside the function to avoid import cost / cycles).

`run_test_job(ctx, docker, *, detach: bool) -> int` — the `docex test` handler:
1. `scope = f"{dns_label(ctx.project.name)}/test"`;
   `vessel_name = f"{dns_label(ctx.project.name)}-test-runner"`; `slot = 1`.
2. `pf = reaper.preflight(ctx, docker, scope=scope, vessel_name=vessel_name)`;
   if not `pf.proceed`: `print(pf.reason, file=sys.stderr); return LOCK_HELD_EXIT`.
3. `run_id = record.new_run_id()`; build `RunMeta(kind="test", scope=scope, slot=1,
   vessel_kind="container", vessel_name=vessel_name,
   docex_version=ctx.project.docex_version, params={})`;
   `record.create_record(...)`.
4. `res = ContainerVessel(docker, vessel_name).launch(ctx, run_id)`.
   - `res.name_conflict` → a concurrent run won the create race (D5):
     `write_status(state="failed")`; print a refusal naming the scope;
     `return LOCK_HELD_EXIT`.
   - `res.rc != 0` → launch failed: `write_status(state="failed",
     exit_code=res.rc)`; `write_exit_atomic(res.rc)`; print error; `return res.rc`.
5. `record.write_status(state="running", started_at=now)`.
6. If `detach`: `print(run_id)`; `return 0`.
7. Else: `return _attach(ctx, run_id)`.

`_attach(ctx, run_id) -> int` — blocking monitor (durable underneath):
- Tail `log_path` (print new bytes as they appear) while polling
  `read_exit(run_id)` on a short interval (e.g. 0.5 s). When the exit file appears,
  flush the remaining log and `return` that code. **A `KeyboardInterrupt`/kill here
  does NOT touch the vessel** — the run stays re-attachable via `job wait`.

`run_job_ls(ctx, docker) -> int` — for each id in `list_run_ids`, render a row:
`id  kind  scope  state  started  exit`. `state` uses `classify` reconciled with
`status.json` (TERMINAL→ the recorded succeeded/failed; LIVE→`running`;
ORPHAN→`orphaned`). Empty → a friendly "no runs" line. Return 0.

`run_job_status(ctx, docker, handle) -> int` — resolve `handle` (see resolver
below); print `status.json` fields + the reconciled `classify` outcome + vessel
liveness. Unknown handle → error listing available ids, return 1.

`run_job_wait(ctx, docker, handle, *, timeout: float | None) -> int` — poll
`read_exit` until present (or `timeout` → print "still running", return a distinct
code e.g. 75). When present → `return` that code. This is the re-attach path.

`run_job_logs(ctx, handle, *, follow: bool) -> int` — print `log`; with `follow`,
tail until the exit file appears. Missing → error, return 1.

`run_job_result(ctx, handle) -> int` — `code = read_exit(handle)`; None → "run not
finished", return a distinct non-zero; else `print(code); return code`.

`_resolve_handle(project_root, handle) -> str | None` — accept an exact run id, or
a unique **prefix** of one, or the literal `"latest"` (newest id). Ambiguous/absent
→ None (caller errors with the id list).

`run_in_vessel(ctx, docker, run_id) -> int` — the **`__run-job` entrypoint (runs
inside the vessel only)**:
1. `meta = record.read_meta(...)`; if None → write `exit`=1 and return 1.
2. `record.write_status(state="running", started_at=now)`.
3. **OS-level redirect** so child processes (docker compose) are captured:
   open `log_path` for append, `os.dup2(logfd, 1)` and `os.dup2(logfd, 2)`.
4. `body = _JOB_BODIES.get(meta.kind)`; `try: rc = body(ctx, docker)` — for
   kind=test this is `run_test(ctx, docker)` (default env/name — the real `test`
   stack). `except Exception:` log traceback, `rc = 1`.
5. `record.write_status(state=("succeeded" if rc==0 else "failed"),
   finished_at=now, exit_code=rc)`; then `record.write_exit_atomic(rc)` **last**
   (the exit file is the terminal signal; write it after status so a reader that
   sees `exit` also sees a consistent status).
6. `return rc`.

---

## 2. DockerClient protocol additions

Add to **both** `src/docex/docker/client.py` (the `Protocol`, with docstrings) and
`src/docex/docker/subprocess_client.py` (the impl). Keep `subprocess` confined to
the subprocess client (its module-docstring chokepoint rule).

- `run_detached(self, *, name, image, command: list[str], binds: list[str], user:
  str, env: list[str], workdir: str, group_add: list[str]) -> tuple[int, bool]`:
  build `docker run -d --name <name> [--user <user>] [-w <workdir>] [--group-add
  <g> …] [-e <e> …] [-v <bind> …] <image> <command…>`. **Capture stderr**
  (`capture_output=True`). Return `(rc, name_conflict)` where `name_conflict` is
  `rc != 0 and ("is already in use" in stderr.lower() or "conflict" in
  stderr.lower())` — the atomic-lock signal (D5). On success, still print/emit the
  container id line so the launch is visible. `FileNotFoundError → (127, False)`.
- `inspect_self(self) -> dict`: run `docker inspect <hostname> --format
  '{{json .}}'` where `hostname = socket.gethostname()`. Parse and return
  `{"image": .Config.Image, "binds": .HostConfig.Binds or [], "user": .Config.User
  or "", "env": .Config.Env or [], "workdir": .Config.WorkingDir or "",
  "group_add": .HostConfig.GroupAdd or []}`. **Raise `VesselIntrospectionError`**
  (import from `docex.jobs.vessel`, or define the exception in `errors.py` to avoid
  a docker→jobs import — prefer `errors.py`) on non-zero exit, empty output, JSON
  error, or missing `.Config.Image`. Guard (c): a non-container `$HOSTNAME` yields
  a docker error → raises → caller falls back.
- `container_running(self, name) -> bool | None`: `docker inspect -f
  '{{.State.Running}}' <name>`; stdout `"true"→True`, `"false"→False`; **non-zero
  exit (no such container) → None**. `FileNotFoundError → None`.
- `container_rm(self, name) -> int`: `docker rm <name>` (no `-f`). Return rc;
  capture output (probe-style, don't spam). `FileNotFoundError → 127`.

**Import direction note:** to keep `docker/` free of a `jobs/` import, define
`VesselIntrospectionError` in `src/docex/errors.py` and import it into
`jobs/vessel.py` and `docker/subprocess_client.py` from there.

---

## 3. Dispatcher wiring (`src/docex/__main__.py`)

- **`_cmd_test`**: add `parser.add_argument("--detach", action="store_true", help=
  "launch the run detached and print its handle instead of blocking")`. Replace the
  body's `return run_test(ctx, docker)` with
  `from docex.jobs.commands import run_test_job; return run_test_job(ctx, docker,
  detach=ns.detach)`.
- **New `_cmd_job(args)`**: an argparse with subparsers `ls` / `status <h>` /
  `wait <h> [--timeout S]` / `logs <h> [-f/--follow]` / `result <h>`. Load ctx +
  `_require_docker()` (all verbs may need docker for liveness except pure-file
  ones; thread it uniformly). Dispatch to the `run_job_*` functions.
- **New hidden `_cmd_run_job(args)`**: positional `run_id`. Loads ctx +
  `_require_docker()`, calls `run_in_vessel(ctx, docker, ns.run_id)`. **This is the
  in-vessel entrypoint** — reachable in the handler table but NOT listed in
  `_HELP_TEXT` or `_GROUPS` (so it never shows in usage).
- **`_HELP_TEXT`**: add `"job": "Operate on durable run handles (ls/status/wait/
  logs/result)."`. Update `"test"` help to mention `--detach`.
- **`_GROUPS`**: add a new group `("Jobs", ("job",))` after `Development` (keeps
  `test`/`build`/`migrate` where they are). Do **not** add `__run-job`.
- **`_build_handler_table`**: add `"job": _cmd_job` and `"__run-job":
  _cmd_run_job`.

---

## 4. `docex/.gitignore` (ruling Q4b)

Add, near the existing caches block:

```
# docex machine-local run state
.docex/
```

(Ruling Q4a: **no** `docex_install.sh` change — the installer stays
scaffolding-free; the pre-056 downstream case is handled by the post-advance
project-upgrade guide, tracked by the coordinator.)

---

## 5. Tests (must be fully green under `python -m pytest tests`)

Extend `tests/conftest.py`'s `fake_docker` to record and script the four new
methods: `run_detached` (default `(0, False)`; scriptable to `(rc, True)` for the
conflict case), `inspect_self` (returns a canned dict; scriptable to raise
`VesselIntrospectionError`), `container_running` (scriptable per name →
`True/False/None`, default `None`), `container_rm` (record, return 0). Keep the
existing recording shape so current tests stay green.

New unit test files:

- **`tests/unit/test_jobs_record.py`** — id sortability/uniqueness; `create_record`
  writes meta+status; atomic `write_exit_atomic` (+ `read_exit` round-trip);
  `write/read_status`; `list_run_ids` descending + empty-dir → `[]`; `classify` for
  all three outcomes (exit present → TERMINAL; running fake → LIVE; dead/absent
  fake → ORPHAN; unreadable meta → ORPHAN).
- **`tests/unit/test_jobs_vessel.py`** — `launch` issues one `run_detached` with
  the cloned spec and command `["docex","__run-job",<id>]`, NOT `--rm`; env
  filtering keeps `HOME`, drops `TERM`/`DOCEX_*`; `inspect_self` raising →
  `_reconstruct_spec` fallback used (image `docex:<version>`), with a stderr
  warning; `name_conflict` surfaces in `LaunchResult`.
- **`tests/unit/test_jobs_reaper.py`** — running vessel → refuse (no rm, no
  teardown); dead vessel + record with no exit → orphan self-heal (synth
  `exit`=137, status `orphaned`, one `compose_down` preserve_volumes=False, then
  `container_rm`), proceed; dead vessel + record WITH exit (terminal) → rm only, no
  synth/teardown, proceed; absent vessel → proceed, no rm.
- **`tests/unit/test_jobs_commands.py`** — the headline criteria:
  - `--detach` returns 0 fast, prints the id, issues exactly one `run_detached`,
    does NOT poll for exit.
  - lock refusal: preflight sees a running vessel → `run_test_job` returns
    `LOCK_HELD_EXIT`, launches nothing. Second case: `run_detached` returns
    `name_conflict=True` → refusal, `LOCK_HELD_EXIT`.
  - **killed-monitor re-attach (no real suite):** create a record with a "running"
    fake vessel and no exit → `run_job_ls` lists it as running / `job status` LIVE;
    then `write_exit_atomic(0)` (simulating the vessel finishing after the monitor
    died) → `run_job_wait` returns 0 and `run_job_result` prints/returns 0. Prove a
    non-zero code path too.
  - orphan reaping end-to-end via `run_test_job`: seed a dead vessel + no-exit
    record for the scope, script the fresh `run_detached` to succeed → assert the
    reaper synthesized the orphan exit on the OLD record, and the new run launched.
  - `run_in_vessel` records: monkeypatch `_JOB_BODIES["test"]` (or patch
    `run_test`) to return rc ∈ {0, 7} → assert terminal status + atomic exit == rc
    + log written. Assert `exit` is written **after** status.
- **`tests/unit/test_dispatcher.py`** (extend) — `docex test --detach` parses;
  `job` subcommands parse and route; `__run-job` is reachable in the handler table
  but ABSENT from `_format_usage()` output.
- **check/merge unchanged:** confirm `tests/unit/test_orchestrate_test.py`,
  `test_pipeline_check.py`, `test_pipeline_merge.py` pass **unmodified** (do not
  edit them; `run_test`'s signature/behavior is untouched).

One integration test:

- **`tests/integration/test_job_vessel_real.py`** (`@pytest.mark.integration`) — a
  **trivial short-lived job body**, NOT the real suite. Options, pick the simplest
  that crosses the real docker boundary: register a temporary `_JOB_BODIES` entry
  (e.g. `"noop"`) whose body sleeps ~1 s and returns 0, launch a real detached
  container that runs `docex __run-job <id>` against a tiny fixture project, then
  assert the real `exit` file appears and `run_job_wait` reads `0`. If wiring a
  custom kind through the real image is heavy, instead launch a real
  `docker run -d --name <n> <small-image> sh -c 'sleep 1; exit 0'` via
  `run_detached`, assert `container_running` transitions True→None and the
  self-heal/`classify` path behaves against real docker. Keep it ~seconds. Reap the
  container in a `finally`.

---

## 6. Definition of done

- `python -m pytest tests -q` fully green; `python -m pytest tests -q -m
  integration` green **run alone** (the new integration test included). The
  `tests/unit/test_collection_partition.py` guard still passes.
- `docex test` blocks + attaches + exits with the run's code (durable underneath);
  `docex test --detach` returns a handle fast; `docex job ls|status|wait|logs|
  result` operate on handles; a second concurrent run on the same scope refuses; an
  orphaned run is reaped on the next preflight leaving an authoritative `exit`.
- `check`/`merge` untouched and green; `orchestrate/test.py` unchanged.
- `docex/.gitignore` ignores `.docex/`.
- No doctrine/core-doc/CHANGELOG edits (coordinator's step).

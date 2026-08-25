# Mod 149 — Implementation Steps

Convert `docex check` and `docex merge` into durable jobs on the Mod 148 substrate,
generalize the reaper's orphan teardown to key off `meta.kind`, and add a fail-fast
guard for `merge --detach` under brokered git-credential passthrough.

**Design of record:** [`overview.md`](./overview.md) (approved at the design gate,
including the amended **D2** vessel taxonomy — *one container vessel for every
durable job; body + reaper-teardown vary by `meta.kind`; no second `Vessel`
class*). Read it before starting.

**Scope guardrails (do NOT violate):**
- **Do NOT change what `check`/`merge` DO.** `run_check` / `run_merge` bodies stay
  behaviorally unchanged. You are wrapping them, not editing their gate/build/test
  logic, `merge`'s `ls-remote` preflight, or its defensive `check`.
- **Do NOT touch `orchestrate/test.py`, `pipeline/check.py`, `pipeline/merge.py`
  logic** (except that `commands.py` calls into them). Their existing tests must
  stay green **unchanged**.
- **Do NOT edit doctrine files or `plans/core/*` docs** — those are handled
  separately by the mod-driver's documentation step. This file is code + tests only.
- **Do NOT add a slot suffix / `--slots` / provenance record** — later mods.
- Run tests with `python -m pytest tests` (canonical) — never bare `pytest`;
  `-m integration` **alone** (see `docex_process.md § Running the automated tests`).

All paths are relative to the docex project root
(`~/.claude/jean_baudrillard/docex`).

---

## Step 1 — `jobs/commands.py`: register check/merge job bodies

In `src/docex/jobs/commands.py`, beside the existing `_run_test_body` and
`_JOB_BODIES`, add two body wrappers that construct their own git client (the
`_JOB_BODIES` registry signature is `body(ctx, docker)`, so git is built inside —
mirroring how `_run_test_body` lazily imports `run_test`):

```python
def _run_check_body(ctx, docker) -> int:
    from docex.git import SubprocessGitClient
    from docex.pipeline.check import run_check
    return run_check(ctx, docker, SubprocessGitClient())


def _run_merge_body(ctx, docker) -> int:
    from docex.git import SubprocessGitClient
    from docex.pipeline.merge import run_merge
    return run_merge(ctx, docker, SubprocessGitClient())
```

Register both in `_JOB_BODIES`:

```python
_JOB_BODIES = {
    "test": _run_test_body,
    "check": _run_check_body,
    "merge": _run_merge_body,
}
```

Confirm `from docex.git import SubprocessGitClient` is the correct import (it is
what `__main__._require_git` uses).

---

## Step 2 — `jobs/commands.py`: extract a shared durable-job launcher

Factor the preflight → create-record → launch-vessel → attach/detach flow out of
the existing `run_test_job` into a private helper, then have all three wrappers
delegate to it. **`run_test_job`'s observable behavior (exact stderr messages,
return codes, record writes) MUST stay identical** — `tests/unit/test_jobs_commands.py`
asserts on `"already in progress"`, the scope appearing in the name-conflict error,
`LOCK_HELD_EXIT`, and the `running`/`failed` states. Keep every message
scope-parametrized exactly as it is today.

Add:

```python
def _launch_durable_job(
    ctx, docker, *, kind: str, scope: str, vessel_name: str,
    params: dict, detach: bool,
) -> int:
    """Preflight the scope lock, create the run record, launch the container
    vessel, and (unless detach) attach to block on the exit file.

    Shared by run_test_job / run_check_job / run_merge_job — the only per-command
    variation is (kind, scope, vessel_name, params). The body is dispatched inside
    the vessel by meta.kind (_JOB_BODIES), so it is not a parameter here.
    """
    pf = reaper.preflight(ctx, docker, scope=scope, vessel_name=vessel_name)
    if not pf.proceed:
        print(pf.reason, file=sys.stderr)
        return LOCK_HELD_EXIT

    run_id = record.new_run_id()
    meta = record.RunMeta(
        id=run_id,
        kind=kind,
        scope=scope,
        slot=1,
        vessel_kind="container",
        vessel_name=vessel_name,
        created_at=record.now_iso(),
        docex_version=ctx.project.docex_version,
        params=params,
    )
    record.create_record(ctx.project_root, meta)

    res = ContainerVessel(docker, vessel_name).launch(ctx, run_id)
    if res.name_conflict:
        record.write_status(
            ctx.project_root, run_id,
            record.RunStatus(state="failed", finished_at=record.now_iso()),
        )
        print(
            f"error: another run won the launch race for scope {scope} "
            f"(vessel {vessel_name}); refusing. Wait for it "
            f"(docex job wait <id>) or let it finish.",
            file=sys.stderr,
        )
        return LOCK_HELD_EXIT
    if res.rc != 0:
        record.write_status(
            ctx.project_root, run_id,
            record.RunStatus(
                state="failed", finished_at=record.now_iso(), exit_code=res.rc
            ),
        )
        record.write_exit_atomic(ctx.project_root, run_id, res.rc)
        print(f"error: launching the {kind} vessel exited {res.rc}.",
              file=sys.stderr)
        return res.rc

    record.write_status(
        ctx.project_root, run_id,
        record.RunStatus(state="running", started_at=record.now_iso()),
    )

    if detach:
        print(run_id)
        return 0
    return _attach(ctx, run_id)
```

Rewrite `run_test_job` to delegate (behavior identical):

```python
def run_test_job(ctx, docker, *, detach: bool) -> int:
    label = dns_label(ctx.project.name)
    return _launch_durable_job(
        ctx, docker,
        kind="test",
        scope=f"{label}/test",
        vessel_name=f"{label}-test-runner",
        params={},
        detach=detach,
    )
```

**Note the one message change this introduces:** the launch-failure line becomes
`"error: launching the {kind} vessel exited {res.rc}."` (was `"...the test
vessel..."`). Verify no test pins that exact substring; if one does, keep it green
(the token `test` still appears via `{kind}` for the test path). The refusal /
name-conflict / "already in progress" messages are unchanged.

---

## Step 3 — `jobs/commands.py`: the check / merge wrappers

Add `run_check_job` and `run_merge_job`. Both take `git` (the foreground computes
`short_sha` for the teardown identities the reaper will use). Both compute the
deterministic worktree slug + throwaway compose-project name that `run_check`
independently recomputes inside the vessel, and record them in `meta.params`.

```python
def _check_teardown_params(ctx, git) -> dict:
    """Deterministic identities the reaper reclaims for a hard-killed
    check/merge vessel. run_check recomputes these identically inside the
    vessel from the same inputs (feature HEAD short sha + dns label), so no
    plumbing threads through run_check's signature.
    """
    label = dns_label(ctx.project.name)
    short_sha = git.head_sha(ctx.project_root, short=True)
    slug = f"check-{short_sha}"
    return {
        "worktree_slug": slug,
        "compose_project": f"{label}-{slug}",
    }


def run_check_job(ctx, docker, git, *, detach: bool) -> int:
    label = dns_label(ctx.project.name)
    return _launch_durable_job(
        ctx, docker,
        kind="check",
        scope=f"{label}/check",
        vessel_name=f"{label}-check-runner",
        params=_check_teardown_params(ctx, git),
        detach=detach,
    )


def run_merge_job(ctx, docker, git, *, detach: bool) -> int:
    label = dns_label(ctx.project.name)
    # Fail-fast guard: brokered git-credential passthrough (shim-staged, tied to
    # the foreground call) does NOT survive a detached merge — the host-side
    # responder dies with the foreground shim invocation, so the vessel's later
    # push cannot re-broker. Refuse up front rather than doing all the work and
    # dying at push. Blocking merge is fine (the responder stays alive), and
    # static credentials (ssh key / gitconfig / file token) are cloned into the
    # vessel and survive. See overview § 4.
    if detach and _brokered_passthrough_active():
        print(
            "error: 'docex merge --detach' is refused while brokered git-"
            "credential passthrough (DOCEX_GIT_CREDENTIAL_PASSTHROUGH) is "
            "active: the host-side credential responder is scoped to the "
            "foreground call and would not survive into the detached vessel, so "
            "the merge's push would fail. Run 'docex merge' attached "
            "(blocking), or use a static credential (SSH key / gitconfig / "
            "file-based token), which is cloned into the vessel and does "
            "survive.",
            file=sys.stderr,
        )
        return _MERGE_DETACH_PASSTHROUGH_EXIT  # define = 64 (EX_USAGE)
    return _launch_durable_job(
        ctx, docker,
        kind="merge",
        scope=f"{label}/merge",
        vessel_name=f"{label}-merge-runner",
        params=_check_teardown_params(ctx, git),  # merge's defensive check owns
                                                   # the same worktree/stack
        detach=detach,
    )
```

Add the passthrough detector. The `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` env var is
**not** forwarded into the container; the shim instead injects git config env vars
whose `credential.helper` value points at its `forward.py`. Detect that signal:

```python
def _brokered_passthrough_active() -> bool:
    """True iff the shim staged brokered git-credential passthrough for this
    invocation. The shim sets GIT_CONFIG_VALUE_<n>=!python3 .../forward.py <sock>
    as git's credential.helper (bin/docex ~line 234); the presence of a
    GIT_CONFIG_VALUE_* naming forward.py is the in-container signal.
    """
    for key, val in os.environ.items():
        if key.startswith("GIT_CONFIG_VALUE_") and "forward.py" in val:
            return True
    return False
```

Add the exit-code constant near `LOCK_HELD_EXIT`:

```python
# `merge --detach` refused because brokered credential passthrough is active —
# a usage error, distinct from a lock refusal.
_MERGE_DETACH_PASSTHROUGH_EXIT = 64  # EX_USAGE
```

`os` is already imported in `commands.py`. Confirm `dns_label` import is present
(it is).

---

## Step 4 — `jobs/reaper.py`: generalize teardown to key off `meta.kind`

Currently `preflight` unconditionally calls `_teardown_leaked_stack(ctx, docker)`
(hardcoded `test` compose stack). Generalize so the orphan branch reads the found
record's `meta` and dispatches teardown by `meta.kind`.

In `preflight`, the orphan branch (where `running is False` and the record has no
`exit`) currently does:

```python
            record.write_exit_atomic(project_root, run_id, record.ORPHAN_EXIT_CODE)
            status = ...  # mark orphaned
            record.write_status(project_root, run_id, status)
            _teardown_leaked_stack(ctx, docker)
```

Change the last line to read the record's meta and dispatch:

```python
            meta = record.read_meta(project_root, run_id)
            _teardown_leaked_resources(ctx, docker, meta)
```

Replace `_teardown_leaked_stack` with a kind-dispatching pair. **Keep the `test`
branch byte-for-byte equivalent** to today (`test_jobs_commands.py::...reaps...`
asserts exactly one `compose_down` with `preserve_volumes=False`):

```python
def _teardown_leaked_resources(ctx, docker, meta) -> None:
    """Reclaim whatever a hard-killed vessel of this kind leaked, keyed off
    meta (D2: the vessel is one container kind; the owned resource varies by
    job kind). test -> its compose stack; check/merge -> the ephemeral worktree
    + the throwaway build/test stack the defensive check brought up.
    """
    kind = meta.kind if meta is not None else "test"
    if kind == "test":
        _teardown_test_stack(ctx, docker)
    elif kind in ("check", "merge"):
        _teardown_worktree_job(ctx, docker, meta)
    # An unknown kind leaks nothing we can safely reclaim; do nothing rather
    # than guess (the synthetic exit + rm already freed the name).


def _teardown_test_stack(ctx, docker) -> None:
    """`compose down -v` the scope's leaked `test` stack (unchanged behavior)."""
    docker.compose_down(
        compose_file_for(ctx, "test"),
        preserve_volumes=False,
        env_file=env_file_for(ctx, "test"),
        project_name=env_compose_project(ctx, "test"),
    )


def _teardown_worktree_job(ctx, docker, meta) -> None:
    """Reclaim a hard-killed check/merge vessel's ephemeral resources.

    1. `compose down -v` the throwaway build/test stack by its recorded project
       name (run_test inside the vessel named it `<label>-check-<sha>`).
    2. Remove the ephemeral worktree dir + `git worktree prune`.
    3. Best-effort sweep of leaked `docex-check/*` / `docex-merge/*` temp
       branches.

    Never unwinds merge's real git mutations (an interrupted rebase / partial
    ff+tag) — merge's own contract leaves those for the operator. This reclaims
    only docex-owned ephemeral scratch. Degrades safely: missing/absent
    meta.params falls back to a namespace sweep of `.docex/worktrees/`.
    """
    from docex.git import SubprocessGitClient
    from docex.pipeline._worktree import worktree_path_for

    project_root = ctx.project_root
    params = (meta.params if meta is not None else {}) or {}
    git = SubprocessGitClient()

    # 1. Throwaway compose stack (test env compose file, worktree-unique name).
    compose_project = params.get("compose_project")
    if compose_project:
        docker.compose_down(
            compose_file_for(ctx, "test"),
            preserve_volumes=False,
            project_name=compose_project,
        )

    # 2. Worktree dir(s).
    slug = params.get("worktree_slug")
    if slug:
        _remove_worktree(project_root, worktree_path_for(project_root, slug), git)
    else:
        # Fallback: reclaim every ephemeral worktree under .docex/worktrees/.
        wt_root = project_root / ".docex" / "worktrees"
        if wt_root.is_dir():
            for entry in sorted(wt_root.iterdir()):
                if entry.is_dir():
                    _remove_worktree(project_root, entry, git)
    git.worktree_prune(project_root)

    # 3. Best-effort temp-branch sweep.
    for pattern in ("docex-check/*", "docex-merge/*"):
        for br in git.list_branches(project_root, pattern=pattern):
            git.delete_branch(project_root, br, remote=False)


def _remove_worktree(project_root, worktree, git) -> None:
    import shutil
    if not worktree.exists():
        return
    rc = git.worktree_remove(project_root, worktree, force=True)
    if rc != 0 and worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
```

**Before writing this, verify the GitClient protocol** (`src/docex/git/client.py`)
has: `worktree_remove(project_root, worktree, *, force)`, `worktree_prune(project_root)`,
`delete_branch(project_root, name, *, remote)`, and a branch-listing method
(`list_branches(project_root, *, pattern=...)` or similar — `check.py` uses
`git.list_tags(..., pattern=...)`, so a parallel `list_branches` likely exists;
**if it does not, do NOT invent a protocol method** — instead drop step 3's exact
sweep and rely on `worktree_prune` + the worktree removal alone, and leave a
`# WHY` note that stale `docex-check/*` branches are harmless leftovers the next
check's timestamped temp branch never collides with). Prefer reusing
`pipeline._worktree.cleanup_worktree` if its shape fits; otherwise the inline
helper above is fine. **Confirm the imports don't create a cycle**: `jobs/reaper.py`
importing `docex.pipeline._worktree` and `docex.git` at function scope (lazy) is
safe — `pipeline.check` reaches `jobs` only through `jobs.commands` at call time.

Keep the existing module docstring accurate: update the bullet that says the
orphan branch tears down "the leaked compose stack" to note it now reclaims
"whatever the orphaned run's kind owns (test stack, or check/merge worktree +
throwaway stack)."

---

## Step 5 — `__main__.py`: wire `--detach` into check / merge

In `src/docex/__main__.py`:

**`_cmd_check`** — add `--detach`, route through `run_check_job`:

```python
def _cmd_check(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex check", add_help=True)
    parser.add_argument(
        "--detach", action="store_true",
        help="launch the run detached and print its handle instead of blocking",
    )
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.jobs.commands import run_check_job

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    git = _require_git()
    return run_check_job(ctx, docker, git, detach=ns.detach)
```

**`_cmd_merge`** — same shape, `run_merge_job`:

```python
def _cmd_merge(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex merge", add_help=True)
    parser.add_argument(
        "--detach", action="store_true",
        help="launch the run detached and print its handle instead of blocking",
    )
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.jobs.commands import run_merge_job

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    git = _require_git()
    return run_merge_job(ctx, docker, git, detach=ns.detach)
```

Update `_HELP_TEXT` for both to note durability (mirror the `test` row's style):

```python
    "check": "Run CI gate checks in an ephemeral worktree (durable job; --detach for a handle).",
    "merge": "Rebase + fast-forward + tag + push (durable job; --detach for a handle).",
```

Do **not** touch the `__run-job` dispatch — `run_in_vessel` already dispatches on
`meta.kind`, so `check`/`merge` bodies route automatically once registered
(Step 1).

---

## Step 6 — Tests (all must pass; no real 30-min check run)

Add to `tests/unit/test_jobs_commands.py` (or a sibling `test_jobs_check_merge.py`),
reusing the `sample_ctx`, `fake_docker`, and `FakeGitClient` fixtures from
`tests/conftest.py`. Follow the existing patterns in `test_jobs_commands.py`.

1. **`--detach` returns a handle, launches once — check AND merge.** Call
   `run_check_job(sample_ctx, fake_docker, fake_git, detach=True)` (and the merge
   variant): assert rc 0, one printed handle, exactly one `run_detached` call, the
   record exists with `kind == "check"` / `"merge"`, `state == "running"`, no
   `exit` yet.

2. **Lock refusal for check and merge.** With `container_running_results[
   "<label>-check-runner"] = True` → `run_check_job` returns `LOCK_HELD_EXIT`,
   `"already in progress"` in stderr, no `run_detached`. Repeat for merge with its
   runner name. Also the `run_detached_result = (0, True)` name-conflict path →
   `LOCK_HELD_EXIT`, scope in stderr, status `failed`.

3. **Killed-monitor re-attach for kind=check** (headline, no real suite): seed a
   `kind="check"` record with a running fake vessel and no `exit`; assert
   `run_job_ls` shows it `running` and `classify` == LIVE; then
   `record.write_exit_atomic(..., 0)`; assert `run_job_wait`/`run_job_result`
   return 0. (Proves re-attachability across kinds.)

4. **Generalized reaper — three cases:**
   - **test orphan unchanged:** the existing reaper test must still pass (one
     `compose_down`, `preserve_volumes=False`, test stack). Do not weaken it.
   - **check orphan with params:** seed a `kind="check"` record with
     `params={"worktree_slug": "check-abc123", "compose_project": "<label>-check-abc123"}`,
     no `exit`, `container_running -> False`; create a dummy
     `.docex/worktrees/check-abc123/` dir. Run the preflight (via `run_check_job`
     launching, or call `reaper.preflight` directly). Assert: synthetic
     `ORPHAN_EXIT_CODE` written; a `compose_down` issued with
     `project_name == "<label>-check-abc123"`; the worktree dir removed; then the
     fresh launch proceeds. Use a `FakeGitClient` that records `worktree_remove`/
     `worktree_prune`/`delete_branch` calls (extend the fake if needed — additive).
   - **check orphan without params (fallback sweep):** same but `params={}` and two
     dummy worktree dirs under `.docex/worktrees/`; assert both removed + prune
     issued, no crash.

5. **Body wiring:** monkeypatch `docex.pipeline.check.run_check` (and
   `.merge.run_merge`) to a recording stub; call `commands._run_check_body(ctx,
   docker)` / `_run_merge_body(...)`; assert the stub received
   `(ctx, docker, <a GitClient instance>)` and its rc propagates.

6. **`__run-job` dispatches check/merge:** register a fake body for `kind="check"`
   in `_JOB_BODIES` via `monkeypatch.setitem`, drive `run_in_vessel` with a
   `kind="check"` record returning rc ∈ {0, k}; assert terminal `status` + atomic
   `exit` written, log populated. (Parametrize alongside the existing test-kind
   case if convenient.)

7. **merge `--detach` passthrough guard:** with `monkeypatch.setenv(
   "GIT_CONFIG_VALUE_1", "!python3 /tmp/x/forward.py /tmp/x/sock")`, call
   `run_merge_job(..., detach=True)` → returns `_MERGE_DETACH_PASSTHROUGH_EXIT`,
   a clear stderr message, **no `run_detached`**. Then the same with
   `detach=False` (blocking) → the guard does NOT fire (it proceeds to launch;
   assert a `run_detached` happens or, if you stub the vessel, that the guard
   returned control past itself). Also assert with the env var absent + `detach=
   True` the guard does not fire.

8. **Existing suites stay green unchanged:** `test_pipeline_check.py`,
   `test_pipeline_merge.py`, `test_orchestrate_test.py`, and the whole
   `test_jobs_*.py` set. This is the mod's verification gate — the gate/build/test
   logic of check/merge still passes as jobs.

### Integration test (real docker, `-m integration`)

Add `tests/integration/test_check_job_vessel_real.py` (mirror
`tests/integration/test_job_vessel_real.py`'s **trivial-body** approach — do NOT
run a real check). Register a trivial ~1 s no-op body under a `kind="check"`-like
record and prove the real detached-container → atomic `exit` file → `job wait`
path works for a second job kind across the docker boundary. Mark it `@pytest.mark.integration`.
Look at `test_job_vessel_real.py` for the exact fixture/skip-if-no-docker pattern
and reuse it.

---

## Step 7 — Run the suite

```sh
python -m pytest tests            # full default suite — must be green
python -m pytest tests -m integration   # ALONE — real-docker tests
```

Both must pass. If the integration test can't reach docker in this environment,
report that (do not silently skip-as-pass); the unit suite must be green
regardless. Re-derive collection counts per `docex_process.md` if anything looks
off (`test_collection_partition.py` must stay green — the two buckets partition).

---

## Step 8 — Report back

Report: files changed, the final `_JOB_BODIES` / wrapper shapes, the reaper
generalization, whether `list_branches` existed (and if not, how step 4.3 was
handled), the passthrough-guard exit code, and the full `python -m pytest tests`
result (pass counts). Flag any drift from this plan. **Do not** edit doctrine or
`plans/core/*` — those are the mod-driver's documentation step.

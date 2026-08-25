# Mod 154 — Implementation Steps

`docex test --slots N` orchestration + shard injection + fleet reaper. Design and
rationale: [`overview.md`](./overview.md) (read it first). This document is the
executable step list; it assumes a fresh context.

**Scope of THIS mod (sarge-ratified):** CLI `--slots N` + the N-slot orchestration
loop + `DOCEX_TEST_SLOT`/`DOCEX_TEST_SLOTS` injection + the reference fixture shims
+ the fleet reaper + the three slot-aware seams + the tests. **NOT in this mod:**
check/merge slot-adoption / the SC4 `--project-name` collision closure — that is a
follow-on **Mod 155**. Do **not** touch `pipeline/check.py` or `pipeline/merge.py`,
do **not** add a `CHECK_SLOT`/`MERGE_SLOT`/`MAX_TEST_SLOTS` constant, and do **not**
claim the collision is closed anywhere.

**Do NOT edit doctrine files or docex core planning docs** (`doctrine/**`,
`plans/core/**`, `CHANGELOG.md`). Those are the corporal's documentation step. This
mod touches code, the two fixture test-projects, and tests only.

**Verified precondition (do not re-litigate):** a slot compose file at
`.docex/slots/test/<k>/docker-compose.yml` resolves its `./core/...` build contexts
to the project root, because `subprocess_client._resolve_project_dir(compose_file,
project_dir=None)` walks up to the nearest `project.yml`. So every sharded compose
call passes `project_dir=None` (the default). Only `check` ever passes a worktree
`project_dir`, and `check` is out of scope here.

---

## Orientation — the call graph you are modifying

```
_cmd_test (__main__.py)  --slots N-->  run_test_job(..., slots=N)   [jobs/commands.py, FOREGROUND]
   -> preflight lock (jobs/reaper.py)  -> launch vessel -> (in vessel) run_in_vessel
        -> _run_test_body(params)  -> run_test(..., slots=N)        [orchestrate/test.py, IN VESSEL]
             slots==1 -> existing single-stack path (UNTOUCHED)
             slots>=2 -> unit-once + N concurrent integration slots
```

The vessel lock is unchanged (per-`(project,test)`); slots are internal
parallelism. All new orchestration runs *inside* the vessel.

---

## Step A — slot-aware seams in `src/docex/orchestrate/_common.py`

### A1. `env_compose_project` — add a `slot` param

Current (~line 29):
```python
def env_compose_project(ctx: ProjectContext, env: str) -> str:
    return f"{dns_label(ctx.project.name)}-{env}"
```
Change to:
```python
def env_compose_project(ctx: ProjectContext, env: str, *, slot: int = 1) -> str:
    seg = "" if slot == 1 else f"-s{slot}"
    return f"{dns_label(ctx.project.name)}-{env}{seg}"
```
Update the docstring to note the slot segment (`-s{k}` for k>1; slot 1 unchanged,
byte-identical). **All existing callers pass no `slot`** → default 1 → identical
output. WHY this is a necessary third seam (beyond the two the mod named): compose
`--project-name` groups a stack; two slots must carry distinct project names or
`up`/`down` for one adopts/tears down the other's resources.

### A2. New helper `slot_compose_file`

Add near `compose_file_for` (~line 57):
```python
def slot_compose_file(ctx: ProjectContext, env: str, slot: int) -> Path:
    """The compiled compose file for ``env`` at ``slot``.

    slot 1 -> infra/output/<env>/docker-compose.yml (unchanged).
    slot k -> .docex/slots/<env>/<k>/docker-compose.yml (Mod 152 layout).
    Mirrors ``cicl.compile.compile_slot``'s output-dir rule so the orchestrator
    and the reaper resolve the same file the compiler wrote.
    """
    if slot == 1:
        return compose_file_for(ctx, env)
    return (
        ctx.project_root / ".docex" / "slots" / env / str(slot)
        / "docker-compose.yml"
    )
```

### A3. `exec_service_key` — add a `slot` param

Current signature (~line 193): `def exec_service_key(ctx, env, codebase) -> str:`.
Change to `def exec_service_key(ctx, env, codebase, *, slot: int = 1) -> str:` and:

1. Thread the slot into the derived key:
   `key = f"{codebase_global_name(ctx.project.name, env, codebase, policy, slot=slot)}-exec"`
   (`codebase_global_name` already accepts `slot` — Mod 152.)
2. Verify against the **slot's** compose file, not always slot 1:
   replace `compose_path = compose_file_for(ctx, env)` with
   `compose_path = slot_compose_file(ctx, env, slot)`.

Default `slot=1` keeps every current caller byte-identical.

---

## Step B — `_migration_task_family` slot-aware (forward-consistency)

`src/docex/orchestrate/migrate.py` (~line 338). Add `slot: int = 1` to the
keyword-only signature and thread it:
```python
def _migration_task_family(ctx, *, project, env, svc, slot: int = 1) -> str:
    ...
    policy = _codebase_naming_policy(ctx, svc, foundation="elastic")
    if policy is None:
        return f"{project}-{env}-{svc}-migrate"
    return f"{codebase_global_name(project, env, svc, policy, slot=slot)}-migrate"
```
No caller passes `slot` this mod (the fixed `test` loop migrates via the inline
exec path, not `migrate.py`); this only completes the primitive so a future
slot-aware `docex migrate` cannot drift. Update the docstring's Mod-152-seam note
to say the seam is now threaded. Do **not** add a slot param to `migrate.run`.

---

## Step C — the sharded orchestration in `src/docex/orchestrate/test.py`

### C1. `run_test` grows a `slots` parameter; default path untouched

Add `slots: int = 1` to `run_test`'s keyword-only params. At the **top of the body**,
before the existing single-stack logic, branch:
```python
    if slots >= 2:
        return _run_test_sharded(
            ctx, docker, tiers=tiers, selector=selector, slots=slots,
        )
    # ... EXISTING single-stack body unchanged below ...
```
The existing body (compile → up → migrate → unit+integration in one stack →
finally teardown) stays **exactly as is** for `slots == 1`. This is what preserves
the byte-identical / behavior-identical default (SC2) — no new compile call, no
`SLOT` injection on the default path. Shape `slots` as keyword-only so Mod 155 can
later call `run_test(..., slot=<reserved>)` — note that is a *different* param
(single reserved slot) than `slots` (shard count); do not conflate them, and do not
add `slot=` in this mod.

### C2. `_run_test_sharded` — unit once, integration across N slots

Add this function. It runs **inside the vessel**.
```python
def _run_test_sharded(
    ctx, docker, *, tiers, selector, slots: int,
) -> int:
    """The --slots N>=2 path: unit runs ONCE (no-stack), the integration tier
    is sharded across N isolated slot stacks brought up concurrently. Each
    physical name carries _s{k} (Mod 152) and the web bridge is per-slot
    (Mod 153), so the N stacks coexist on one host with no collision.
    """
    ensure_compiled(ctx)
    env_file = aggregate(ctx, env=_TEST_ENV)  # per-env, shared by all slots

    # 1. Unit tier ONCE (fail-fast gate) — no stack, standard slot-1 project.
    if "unit" in tiers:
        rc = run_test_unit(ctx, docker, selector=selector)
        if rc != 0:
            return rc

    if "integration" not in tiers:
        return 0

    # 2. Compile every slot serially (cheap, deterministic), then run the N
    #    integration slots concurrently.
    from docex.cicl.compile import compile_slot
    for k in range(1, slots + 1):
        compile_slot(ctx, _TEST_ENV, k)

    import concurrent.futures as _f
    results: dict[int, int] = {}
    with _f.ThreadPoolExecutor(max_workers=slots) as pool:
        futs = {
            pool.submit(
                _run_one_slot, ctx, docker,
                slot=k, slots=slots, env_file=env_file, selector=selector,
            ): k
            for k in range(1, slots + 1)
        }
        for fut in _f.as_completed(futs):
            k = futs[fut]
            results[k] = fut.result()

    # first non-zero, lowest slot first (deterministic report)
    for k in sorted(results):
        if results[k] != 0:
            return results[k]
    return 0
```

### C3. `_run_one_slot` — one slot's up → migrate → integration → conditional teardown

```python
def _run_one_slot(
    ctx, docker, *, slot: int, slots: int, env_file, selector,
) -> int:
    """Bring up slot ``slot``, migrate, run the integration shim sharded, then
    tear down IFF it passed (a failed slot is LEFT UP for debugging — reaped by
    the next invocation's preflight). Returns the slot's exit code.
    """
    compose_file = slot_compose_file(ctx, _TEST_ENV, slot)
    project_name = env_compose_project(ctx, _TEST_ENV, slot=slot)

    # Pre-up clean slate: reap any leftover same-numbered slot stack (a failed
    # slot left up by a prior run, or an orphan). Idempotent; ignores absence.
    docker.compose_down(
        compose_file, preserve_volumes=False,
        env_file=env_file, project_name=project_name,
    )

    slot_env = {"DOCEX_TEST_SLOT": str(slot), "DOCEX_TEST_SLOTS": str(slots)}
    if selector:
        slot_env["DOCEX_TEST_SELECTOR"] = selector

    rc = 0
    try:
        rc = docker.compose_up(
            compose_file, build=True, detach=True,
            env_file=env_file, project_name=project_name,
        )
        if rc != 0:
            print(f"error: 'compose up' for test slot {slot} exited {rc}.",
                  file=sys.stderr)
            return rc

        for cb in codebases_with_schema(ctx):
            key = exec_service_key(ctx, _TEST_ENV, cb, slot=slot)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./migrate.sh"], build=True,
                env_file=env_file, project_name=project_name,
            )
            if rc != 0:
                print(f"error: migrate.sh for {cb!r} in slot {slot} exited {rc}.",
                      file=sys.stderr)
                return rc

        for svc in codebases(ctx):
            key = exec_service_key(ctx, _TEST_ENV, svc, slot=slot)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./test_integration.sh"], build=True,
                env=slot_env, env_file=env_file, project_name=project_name,
            )
            if rc != 0:
                print(f"error: ./test_integration.sh for {svc!r} slot {slot} "
                      f"exited {rc}.", file=sys.stderr)
                return rc
        return 0
    finally:
        # Keep-failed-slot-up-for-debug: only tear down a slot that PASSED.
        if rc == 0:
            td = docker.compose_down(
                compose_file, preserve_volumes=False,
                env_file=env_file, project_name=project_name,
            )
            if td != 0:
                print(f"warning: slot {slot} teardown exited {td}.",
                      file=sys.stderr)
```

Notes:
- `sys` and the `_common` imports (`codebases`, `codebases_with_schema`,
  `exec_service_key`, `env_compose_project`) are already imported at the top of
  `test.py`; add `slot_compose_file` to that import block.
- `compose_run_one_off`/`compose_up`/`compose_down` already accept `env`,
  `env_file`, `project_name`; leave `project_dir` unset (default None) so
  `--project-directory` resolves to the project root (verified precondition).
- `DockerClient` is stateless per call (each method shells one argv), so the
  thread pool is safe. Do not share mutable state between workers; `results` is
  written only after each future completes.

---

## Step D — thread `slots` through `src/docex/jobs/commands.py`

### D1. `run_test_job` — accept `slots`, record it in params

Add `slots: int = 1` to `run_test_job`'s signature. In the `params` dict passed to
`_launch_durable_job`, add `"slots": slots`:
```python
        params={"tiers": list(tiers), "selector": selector, "slots": slots},
```
(The record's `RunMeta.params` already round-trips arbitrary keys; `meta.slot`
stays 1 — that field is the *record's* slot notion and is unrelated to the shard
count, which lives in params. Do not repurpose `meta.slot`.)

### D2. `_run_test_body` — pass `slots` into `run_test`

```python
def _run_test_body(ctx, docker, params) -> int:
    from docex.orchestrate.test import run_test
    tiers = tuple(params.get("tiers") or ("unit", "integration"))
    selector = params.get("selector")
    slots = int(params.get("slots") or 1)
    return run_test(ctx, docker, tiers=tiers, selector=selector, slots=slots)
```

---

## Step E — the fleet reaper in `src/docex/jobs/reaper.py`

Generalize the orphaned-vessel teardown to N slot stacks. Replace
`_teardown_test_stack(ctx, docker)` so it reads the recorded slot count and tears
down every slot the hard-killed vessel leaked:

```python
def _teardown_test_stack(ctx, docker, meta=None) -> None:
    """Tear down every leaked ``test`` slot stack a hard-killed vessel owned.

    The vessel's `finally` (which tears down each slot) never ran, so slots
    1..N leak. N is recorded in meta.params['slots'] at launch; default 1
    (a pre-slots record, or a non-sharded run). Each slot's compose file is at
    the Mod 152 layout, written by the vessel before it brought the slot up.
    preserve_volumes=False — a reaped orphan's half-migrated DB must not survive.
    """
    from docex.orchestrate._common import slot_compose_file
    params = (meta.params if meta is not None else {}) or {}
    slots = int(params.get("slots") or 1)
    for k in range(1, slots + 1):
        docker.compose_down(
            slot_compose_file(ctx, "test", k),
            preserve_volumes=False,
            env_file=env_file_for(ctx, "test"),
            project_name=env_compose_project(ctx, "test", slot=k),
        )
```

Update the one caller in `_teardown_leaked_resources` (the `kind == "test"`
branch) to pass `meta`:
```python
    if kind == "test":
        _teardown_test_stack(ctx, docker, meta)
```
Leave the `check`/`merge` (`_teardown_worktree_job`) branch untouched. The
docstring at the top of the file should note the test-kind teardown is now the
**fleet** (multi-slot) reaper: it reclaims all N deterministic slot stacks; a
**failed** slot deliberately left up by a completed run is reclaimed by the next
run's per-slot pre-up down (Step C3), or persists across a smaller-N run until an
N≥k run touches slot k — the accepted residual edge (overview § 5, ruling Q3).

---

## Step F — CLI `--slots N` in `src/docex/__main__.py::_cmd_test`

Add the argument (after `--detach`):
```python
    parser.add_argument(
        "--slots", type=int, default=1, metavar="N",
        help="shard the integration tier across N isolated test stacks on this "
             "host (unit runs once). N=1 (default) is byte-identical to today. "
             "Only for 'test'/'test integration'; not valid for the 'unit' lane.",
    )
```
After parsing, validate and route:
```python
    if ns.slots < 1:
        print("error: --slots must be >= 1.", file=sys.stderr)
        return 64  # EX_USAGE

    if ns.tier == "unit":
        if ns.detach:
            ...  # existing rejection unchanged
        if ns.slots != 1:
            print(
                "error: 'docex test unit' is a no-stack synchronous run; "
                "--slots does not apply (sharding needs a stack).",
                file=sys.stderr,
            )
            return 64
        from docex.orchestrate.test import run_test_unit
        return run_test_unit(ctx, docker, selector=ns.subset)

    from docex.jobs.commands import run_test_job
    if ns.tier == "integration":
        return run_test_job(
            ctx, docker, detach=ns.detach,
            tiers=("integration",), selector=ns.subset, slots=ns.slots,
        )
    # No tier -> full durable job.
    return run_test_job(ctx, docker, detach=ns.detach, slots=ns.slots)
```
Keep the existing `unit`+`--detach` rejection exactly as it is; just add the
`--slots` guard beside it. Do **not** add a `MAX_TEST_SLOTS` ceiling (that is Mod
155's, tied to the reserved check/merge slots).

---

## Step G — reference fixture shims (both test-projects)

Make the fixtures a correct exemplar of the shard contract and keep the suite
green. Edit **both**:
- `test_projects/fixed/core/api/test_integration.sh`
- `test_projects/elastic/core/api/test_integration.sh`

They are code-identical (the seeds share `core/`); apply the same edit to both.
The block must be **additive**: `DOCEX_TEST_SLOTS` unset or `1` ⇒ today's exact
behavior (whole tier); `> 1` ⇒ run only this slot's `1/N` share, sharded
deterministically over collected node-ids so the union of N shards = the whole
tier.

Read each shim first to match its existing structure (it already honors
`DOCEX_TEST_SELECTOR`). Add, after the selector handling, a shard gate of this
shape (adapt to the shim's actual pytest invocation and `set -euo pipefail` style):

```sh
# --- Reference shard split (Mod 154): DOCEX_TEST_SLOT / DOCEX_TEST_SLOTS ---
# A REFERENCE only — the doctrine recommends but does not mandate this pattern
# (tests.md § Injected environment). Unset/1 slots => whole tier (unchanged).
# k of N => this slot's deterministic 1/N share of collected node-ids.
SHARD_ARGS=""
if [ "${DOCEX_TEST_SLOTS:-1}" -gt 1 ]; then
  # Collect node-ids for this tier (respecting any DOCEX_TEST_SELECTOR already
  # spliced into the pytest args), then keep index % SLOTS == (SLOT-1).
  NODES="$(python -m pytest tests/integration $SELECTOR_ARGS --collect-only -q \
             | grep '::' || true)"
  SHARD_ARGS="$(printf '%s\n' "$NODES" \
             | awk -v s="$DOCEX_TEST_SLOT" -v n="$DOCEX_TEST_SLOTS" \
                   'NR % n == (s-1) % n')"
  # If this shard collected nothing (more slots than tests), pass cleanly.
  if [ -z "$SHARD_ARGS" ]; then
    echo "slot $DOCEX_TEST_SLOT/$DOCEX_TEST_SLOTS: no tests in this shard"
    exit 0
  fi
fi
python -m pytest tests/integration $SELECTOR_ARGS $SHARD_ARGS
```

Adjust variable names to the shim's existing ones (e.g. however it already holds
the selector fragment). Keep it POSIX-`sh` compatible with the shim's shebang.
Verify with a dry run: `DOCEX_TEST_SLOTS=2 DOCEX_TEST_SLOT=1` and `=2` between them
must cover every collected integration node exactly once.

**Git for the fixtures (per `test_projects.md` § Commit cadence):** these live in
nested inner git repos. Commit the shim change in **each inner repo first** with a
project-shaped message (e.g. `test_integration.sh: reference DOCEX_TEST_SLOT shard
split`). Do **not** move the `v<version>` tag (no project version change — the shim
edit is not a release boundary). The outer-repo snapshot is picked up by the
corporal's completion commit. If unsure, leave the inner-repo commit to the
corporal and just make the file edits — but note in your report that the inner
repos are dirty.

---

## Step H — tests

Add/adjust under `tests/`. Follow `docex_process.md` § Running the automated tests:
the full suite is `python -m pytest tests`; integration-marked tests run **alone**
via `python -m pytest tests -m integration`. Unit tests go under `tests/unit/`.

### H1. Seam identity tests (`tests/unit/`)
- `env_compose_project(ctx, "test", slot=2)` == `"<label>-test-s2"`; `slot=1`
  == `"<label>-test"` (identical to the no-kw call).
- `exec_service_key(ctx, "test", cb, slot=2)` contains `-test-s2-` and ends
  `-exec`, and matches the slotted `codebase_global_name(..., slot=2)` + `-exec`.
  With `slot=1`, identical to the current no-kw result. (Use the fixed test
  project or an existing compile fixture; ensure the slot-2 compose file exists —
  compile it via `compile_slot` into `.docex/slots/` in a tmp copy, or assert the
  derivation path that does not require the verify file by pointing at a compiled
  slot-2 dir.)
- `_migration_task_family(ctx, project=..., env="test", svc=cb, slot=2)` contains
  `-test-s2-` and ends `-migrate`; `slot=1` unchanged.

### H2. Sharded orchestration with a fake docker (`tests/unit/`)
Build a fake `DockerClient` recording every `compose_up`/`compose_run_one_off`/
`compose_down` call (compose_file, project_name, argv, env). Drive
`_run_test_sharded(ctx, fake, tiers=("unit","integration"), selector=None,
slots=3)` (stub `run_test_unit`/`compile_slot`/`aggregate` as needed) and assert:
- `run_test_unit` is called **exactly once**.
- three integration slots run; each `test_integration.sh` one-off carries
  `DOCEX_TEST_SLOT=k` and `DOCEX_TEST_SLOTS=3`; with a selector set, it also
  carries `DOCEX_TEST_SELECTOR`.
- each slot uses `env_compose_project(slot=k)` as project name and
  `slot_compose_file(slot=k)` as compose file.
- a slot whose integration one-off returns non-zero is **not** torn down
  (no `compose_down` after its failure); passing slots **are** torn down.
- overall rc is the lowest-numbered failing slot's code; all-pass → 0.
- `tiers=("integration",)` skips the unit-once call.

### H3. Fleet reaper (`tests/unit/`)
- A `RunMeta` with `params={"slots": 3, ...}` and a dead vessel → `preflight`
  synthesizes the orphan `exit`, and `_teardown_test_stack` issues a
  `compose_down` for each of slots 1/2/3 with the right per-slot project name +
  slot compose file. A `params` without `slots` (or `{"slots":1}`) → exactly one
  teardown at slot 1 (backward-compatible with pre-slots records).
- `classify` still reconciles a slotted test record correctly (unchanged path).

### H4. Byte-identical default (`tests/unit/`)
- Assert `run_test(..., slots=1)` takes the existing single-stack path (e.g. via
  the fake docker: no `slot_compose_file(k>1)` is ever used, no `DOCEX_TEST_SLOT`
  is injected). The Mod 152 golden gate (`tests/unit/test_slot_golden.py`) and
  `git diff infra/output` must stay clean — do not regenerate any golden.

### H5. Cheap real-docker 2-slot test (`tests/integration/`, `-m integration`)
Ruling Q5 — include it, keep it minimal. Mirror the trivial-body pattern used by
`tests/integration/test_test_real.py`. Against the fixed fixture (tiny 2-file
integration tier), run the sharded path at **slots=2** (call
`_run_test_sharded`/`run_test(..., slots=2)` directly, or `docex test --slots 2`
through the vessel if the existing real-docker harness does):
- assert both slot stacks come up with `_s2`-isolated names (slot 1 unslotted,
  slot 2 carries `-s2-`); e.g. inspect for the two distinct `-exec`/container
  names and the two distinct postgres volumes.
- assert the injection reaches the shim (the shard ran its share — e.g. the run
  is green and both slots' stacks existed concurrently).
- assert both stacks are torn down on success (no leftover `-test`/`-test-s2`
  containers or volumes).
- Do **NOT** run a real multi-slot full suite; the fixture tier is tiny by design.
- Mark it `@pytest.mark.integration`. If it cannot be kept reasonably cheap/stable,
  drop it and rely on H2 (fake-docker) + the existing Mod 153 single-slot real gate
  (`test_test_real.py`) — and say so in the report.

---

## Step I — run the suite

1. `python -m pytest tests` — full suite green.
2. `python -m pytest tests -m integration` — **run alone**; green (includes H5 if
   added). Confirm the deselect/collect counts agree per `docex_process.md`.
3. Byte-identical gate: recompile each fixture in place and confirm
   `git -C test_projects/<f> diff --exit-code infra/output` is clean (the default
   `docex compile` path is slot 1; nothing under `infra/output` should change).

Report: files changed, the suite result (both invocations), the byte-identical
gate result, and whether H5 was included or fell back. Leave doctrine files, docex
core planning docs, and `CHANGELOG.md` untouched (corporal's step).

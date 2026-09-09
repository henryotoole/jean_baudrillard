# Mod 155 — Implementation Steps

Close Goal 4 SC4: make `check`/`merge`'s defensive test stacks adopt **reserved
slots above the `test` band**, so their compiled `test`-env physical names (esp.
the DB volume `name:`) are deterministically name-disjoint from any `docex test`
run and from each other. Design + rationale: `overview.md` (ratified). This file is
**code + tests only** — doctrine (`docex.md`/`cicd.md`) and docex core-planning-doc
prose (`masterplan.md`/`compiler.md`) + `CHANGELOG` are handled in the mod cycle's
documentation step, NOT here. No contract changes.

All paths are under `/home/ubuntu/.claude/jean_baudrillard/docex/`.

Ratified constants: `MAX_TEST_SLOTS = 8`, `CHECK_SLOT = 9`, `MERGE_SLOT = 10`
(derived as ceiling+1/+2), living in `src/docex/orchestrate/_common.py`.

---

## Step 1 — Reserved-slot constants (`src/docex/orchestrate/_common.py`)

Add module-level constants near the top (after the `_ALL_ENVS` line, before
`env_compose_project`):

```python
# Mod 155 — the reserved-slot band. `docex test --slots N` uses slots
# 1..MAX_TEST_SLOTS; check/merge run their defensive test/check at a reserved
# slot ABOVE that band, so their compiled `test`-env physical names (esp. the DB
# volume `name:`) are name-disjoint from any `test` run and from each other. This
# is what closes the `--project-name` DB-volume collision (compose's
# --project-name does NOT namespace explicit container_name:/volume name:; the
# Mod 152 slot segment does). CHECK_SLOT/MERGE_SLOT are DERIVED from the ceiling
# so they stay disjoint by construction if MAX_TEST_SLOTS is ever retuned (a
# beefier host may bump it). They are ephemeral per-run slot indices, never a
# persisted identity, so deriving them carries no cross-version-stability duty.
MAX_TEST_SLOTS = 8
CHECK_SLOT = MAX_TEST_SLOTS + 1   # 9
MERGE_SLOT = MAX_TEST_SLOTS + 2   # 10
```

Do NOT change `env_compose_project`, `slot_compose_file`, or `exec_service_key` —
they already take `slot` (Mod 152/154). No import direction issues: `pipeline/*`
and `__main__` import these from `orchestrate/_common` (pipeline is the
higher-level caller).

---

## Step 2 — `run_test` gains a single-stack `slot` param (`src/docex/orchestrate/test.py`)

Add a keyword-only `slot: int = 1` to `run_test`, **distinct** from the shard-count
`slots`. `slot` pins the *single-stack* path to one slot index (check/merge use
it); `slots` shards the *integration* tier (unchanged). They never combine —
check/merge pass `slot=`, never `slots=`.

1. **Signature** — add `slot: int = 1` after `slots: int = 1`:

```python
def run_test(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    project_dir: "Path | None" = None,
    env_file_override: "Path | None" = None,
    project_name: "str | None" = None,
    tiers: "tuple[str, ...]" = ("unit", "integration"),
    selector: "str | None" = None,
    slots: int = 1,
    slot: int = 1,
) -> int:
```

2. **Docstring** — add a paragraph documenting `slot`: the single-stack path pinned
   to slot index `slot` (`slot != 1` used only by `check`/`merge`, which compile +
   run the `test` env at a reserved slot above the `--slots` band to close the
   `--project-name` DB-volume collision); `slot=1` is byte/behavior-identical to
   today. Note `slot` and `slots` are mutually exclusive (check/merge never shard).

3. **Slot-aware compile + compose-file selection.** After the `if slots >= 2:`
   dispatch, replace the current `ensure_compiled(ctx)` + `compose_file =
   compose_file_for(ctx, _TEST_ENV)` with a slot branch:

```python
    if slots >= 2:
        return _run_test_sharded(
            ctx, docker, tiers=tiers, selector=selector, slots=slots,
        )
    if slot == 1:
        ensure_compiled(ctx)
        compose_file = compose_file_for(ctx, _TEST_ENV)
    else:
        # Reserved-slot single-stack path (check/merge). Compile defensively at
        # `slot` — same "always re-compile" philosophy as ensure_compiled — into
        # the gitignored .docex/slots/<env>/<slot>/ tree, leaving slot-1
        # infra/output/ untouched (byte-identical default preserved).
        from docex.cicl.compile import compile_slot
        compile_slot(ctx, _TEST_ENV, slot)
        compose_file = slot_compose_file(ctx, _TEST_ENV, slot)
```

4. **Project name** — thread `slot` into the default:

```python
    if project_name is None:
        project_name = env_compose_project(ctx, _TEST_ENV, slot=slot)
```

   (Callers passing an explicit `project_name` override still win; check will pass
   the slot-derived name explicitly per Step 3, which equals this default.)

5. **Exec keys** — thread `slot=slot` into BOTH `exec_service_key` calls (the
   migrate loop and the tier loop):

```python
            key = exec_service_key(ctx, _TEST_ENV, cb, slot=slot)
            ...
                key = exec_service_key(ctx, _TEST_ENV, svc, slot=slot)
```

6. **Pre-up clean-slate reap (slot != 1 only).** Immediately inside the `try:`,
   before the `compose up`, add a guarded pre-up teardown mirroring
   `_run_one_slot` — clears a stack leaked by a hard-killed check/merge vessel
   (with the correct `_s{slot}` volume name, since we just compiled it), so a
   fresh run never reuses a stale DB volume. Gated `slot != 1` so the default
   `docex test` path stays byte/behavior-identical:

```python
    try:
        # Mod 155: reserved-slot (check/merge) runs reap any leftover
        # same-slot stack before bringing up a clean one. Idempotent; ignores
        # absence. Gated slot!=1 so the default `docex test` path is unchanged.
        if slot != 1:
            docker.compose_down(
                compose_file, preserve_volumes=False,
                env_file=env_file, project_dir=project_dir,
                project_name=project_name,
            )
        # 1. compose up --build -d
        rc = docker.compose_up(
            ...
```

   `env_file` is already resolved above this block (the existing
   `env_file_override`-or-`aggregate` line). Keep that line where it is (before the
   `if project_name is None:` block), unchanged.

Everything else in `run_test` (the migrate loop, tier loop, `finally` teardown)
already reads `compose_file` / `env_file` / `project_name` and now works for any
slot with no further change.

---

## Step 3 — `run_check` compiles/runs its defensive stack at a reserved slot (`src/docex/pipeline/check.py`)

1. **Import the constant.** In the existing `from docex.orchestrate._common import
   ...` line (currently `codebases, codebases_with_schema`), add `CHECK_SLOT` and
   the two slot helpers used below:

```python
from docex.orchestrate._common import (
    CHECK_SLOT,
    codebases,
    codebases_with_schema,
    env_compose_project,
    slot_compose_file,
)
```

2. **Signature** — add a keyword-only `slot`:

```python
def run_check(
    ctx: ProjectContext,
    docker: DockerClient,
    git: GitClient,
    *,
    slot: int = CHECK_SLOT,
) -> int:
```

   Update the docstring to note the defensive build+test compile/run the
   worktree's `test` env at `slot` (default `CHECK_SLOT`), above the `test` band,
   which closes the `--project-name` DB-volume collision; `merge` passes
   `MERGE_SLOT`.

3. **Build step — compile + build at `slot`.** In the "6. Build everything" block:
   - Keep the compile-succeeds **gate** `rc = run_compile(worktree_ctx)` exactly as
     is (it still writes the worktree's slot-1 `infra/output/test`, thrown away
     with the worktree — this is the "compile succeeds for all envs" gate).
   - Replace the compose-file + project-name derivation and add the slot compile.
     The current lines:

     ```python
     compose_path = compose_file_for(worktree_ctx, "test")
     check_project_name = f"{dns_label(worktree_ctx.project.name)}-{worktree.name}"
     ```

     become:

     ```python
     # Mod 155: compile + run the defensive stack at the reserved slot so its
     # physical names (esp. the DB volume name:) are disjoint from any `docex
     # test` run and from merge's MERGE_SLOT stack — closing the
     # `--project-name` DB-volume collision. Slotted output lands in the
     # gitignored .docex/slots/test/<slot>/ (worktree tree), thrown away with
     # the worktree; slot-1 infra/output stays untouched.
     from docex.cicl.compile import compile_slot
     compile_slot(worktree_ctx, "test", slot)
     compose_path = slot_compose_file(worktree_ctx, "test", slot)
     check_project_name = env_compose_project(worktree_ctx, "test", slot=slot)
     ```

   - The `dns_label` import may become unused — remove it from the imports if so
     (check with a grep; leave it if still referenced).

4. **`run_test` call** — pass `slot=slot`:

```python
        rc = run_test(
            worktree_ctx, docker,
            project_dir=worktree,
            env_file_override=env_file,
            project_name=check_project_name,
            slot=slot,
        )
```

   (`_compose_build` already receives `compose_path`/`check_project_name`; with the
   Step-3.3 change those are now the slotted forms — no other `_compose_build`
   change needed.)

Leave the provenance-record block, the gate checks, and the empty-origin path
unchanged.

---

## Step 4 — `run_merge` passes `MERGE_SLOT` (`src/docex/pipeline/merge.py`)

1. Import the constant:

```python
from docex.orchestrate._common import MERGE_SLOT
```

2. The defensive recheck call (currently `rc = run_check(ctx, docker, git)`)
   becomes:

```python
        rc = run_check(ctx, docker, git, slot=MERGE_SLOT)
```

   Add a short `# WHY` comment: merge's defensive check is an in-process call (it
   does NOT take the check-runner lock), so it can co-occur with a standalone
   `docex check` at `CHECK_SLOT`; running at `MERGE_SLOT` keeps the two
   name-disjoint. No other merge change.

---

## Step 5 — CLI `MAX_TEST_SLOTS` ceiling (`src/docex/__main__.py`, `_cmd_test`)

Add the ceiling enforcement Mod 154 did not, beside the existing `ns.slots < 1`
guard (~line 461). Import the constant at the point of use:

```python
    if ns.slots < 1:
        print("error: --slots must be >= 1.", file=sys.stderr)
        return 64  # EX_USAGE
    from docex.orchestrate._common import MAX_TEST_SLOTS
    if ns.slots > MAX_TEST_SLOTS:
        print(
            f"error: --slots {ns.slots} exceeds MAX_TEST_SLOTS "
            f"({MAX_TEST_SLOTS}); the test slot band is 1..{MAX_TEST_SLOTS}.",
            file=sys.stderr,
        )
        return 64  # EX_USAGE
```

Also update the `--slots` help text to mention the cap: append
`" (1..MAX_TEST_SLOTS)."` or similar so `docex test -h` states the range.

---

## Step 6 — Reaper identities become slot-aware (`src/docex/jobs/commands.py`)

The reaper **body** (`jobs/reaper.py::_teardown_worktree_job`) needs **no change** —
it already tears down `params["compose_project"]` by label. We only make the
recorded name match the slot-derived name `run_check` now uses, per kind.

1. `_check_teardown_params` — add a keyword `slot` and derive `compose_project`
   from it via `env_compose_project` (record the slot too, for provenance):

```python
def _check_teardown_params(ctx, git, *, slot: int) -> dict:
    """Deterministic identities the reaper reclaims for a hard-killed
    check/merge vessel.

    ``run_check`` recomputes the same project name inside the vessel:
    ``env_compose_project(ctx, "test", slot=slot)`` (the reserved-slot stack,
    Mod 155). The worktree dir is still ``check-<short_sha>`` (run_check names it
    that regardless of which command drove it). Recording these here lets the
    reaper reclaim the leak by label without threading anything through
    ``run_check``'s signature.
    """
    from docex.orchestrate._common import env_compose_project

    short_sha = git.head_sha(ctx.project_root, short=True)
    return {
        "worktree_slug": f"check-{short_sha}",
        "compose_project": env_compose_project(ctx, "test", slot=slot),
        "slot": slot,
    }
```

   (Drop the now-unused `label = dns_label(...)` line if nothing else uses it in
   the function; keep the `dns_label` import — other functions use it.)

2. `run_check_job` — pass `slot=CHECK_SLOT`:

```python
    from docex.orchestrate._common import CHECK_SLOT
    ...
        params=_check_teardown_params(ctx, git, slot=CHECK_SLOT),
```

3. `run_merge_job` — pass `slot=MERGE_SLOT`:

```python
    from docex.orchestrate._common import MERGE_SLOT
    ...
        params=_check_teardown_params(ctx, git, slot=MERGE_SLOT),
```

   (Import the two constants at module top instead of inline if you prefer — either
   is fine; keep it consistent with the file's existing import style.)

`_run_check_body`/`_run_merge_body` are unchanged: `_run_check_body` calls
`run_check(...)` (default `CHECK_SLOT`); `_run_merge_body` calls `run_merge(...)`,
which internally calls `run_check(..., slot=MERGE_SLOT)`.

---

## Step 7 — Update existing tests coupled to the old name

### 7a. `tests/unit/test_jobs_check_merge.py`

- `test_detach_returns_handle_launches_once` (parametrized check+merge, ~line 59):
  the assertion `meta.params["compose_project"] == "sample-check-abc1234"` must
  become **per-kind**. Add the expected value to the parametrize and assert it:
  - check → `"sample-test-s9"`
  - merge → `"sample-test-s10"`
  `worktree_slug` stays `"check-abc1234"` for both. Also assert
  `meta.params["slot"]` == 9 (check) / 10 (merge).
  (The fixture project's `dns_label` is `sample`; confirm from the fixture — if the
  label differs, use the actual `env_compose_project(sample_ctx, "test", slot=k)`
  value.)
- `test_reaper_check_orphan_with_params` (~line 141): this seeds its OWN `params`
  dict and asserts the reaper tears that name down — the reaper body is unchanged,
  so it passes as-is. Optionally update the seeded `compose_project` to
  `"sample-test-s9"` for realism; not required.

### 7b. `tests/unit/test_pipeline_check.py`

- In `_stub_expensive_steps`, add `compile_slot` to the stubs so any test that
  reaches the build step is insulated exactly as `run_compile` / `_compose_build` /
  `run_test` already are:

```python
    import docex.cicl.compile as cicl_compile
    monkeypatch.setattr(cicl_compile, "compile_slot", lambda *a, **kw: None)
```

  Put it beside the existing `run_compile` stub. Leave `test_check_reaches_compile_
  when_a_surface_is_skipped` alone — it fails at the real `run_compile` gate before
  the build step's `compile_slot`, so it is unaffected.
- If any check happy-path test asserts the old `check_project_name`
  (`<label>-<worktree.name>`) reached compose, update the expected name to
  `env_compose_project(worktree_ctx, "test", slot=CHECK_SLOT)` (grep for
  `worktree.name` / `check-` in this file). Most gate tests assert an early gate
  failure and never reach the build step.

### 7c. `tests/unit/test_pipeline_merge.py`

- If any test asserts `run_check` was called with no slot / a specific project
  name, update it to expect `slot=MERGE_SLOT`. Grep for `run_check` in the file;
  the common pattern stubs `run_check` to a lambda, which accepts the new kwarg
  unchanged.

Run `python -m pytest tests/unit/test_jobs_check_merge.py
tests/unit/test_pipeline_check.py tests/unit/test_pipeline_merge.py -q` and fix any
remaining name-coupled assertions the same way (name form changed; guarantee
preserved).

---

## Step 8 — New SC4 proof tests (`tests/unit/test_reserved_slots.py`)

Create a new unit file. Model the compiled-name assertions on
`tests/unit/test_slot_primitive.py::test_slot2_emitted_compose_isolates_names`
(same `_ctx` / `compile_slot` helpers, fixed test project). Cover:

1. **Band constants** — `CHECK_SLOT > MAX_TEST_SLOTS`, `MERGE_SLOT > MAX_TEST_SLOTS`,
   `CHECK_SLOT != MERGE_SLOT` (import from `docex.orchestrate._common`).

2. **Compiled DB-volume disjointness (the core SC4 proof).** For the fixed fixture,
   `compile_slot(ctx, "test", k)` for `k in {1, 2, CHECK_SLOT, MERGE_SLOT}`, read
   each `docker-compose.yml`, and assert the DB volume `name:` segments are present
   and **pairwise disjoint**:
   - slot 1 → contains `-test-appdb_data`, and NOT `-test-s`
   - slot 2 → `-test-s2-appdb_data`
   - CHECK_SLOT → `-test-s9-appdb_data`
   - MERGE_SLOT → `-test-s10-appdb_data`
   Assert the four volume names are all distinct (a `set` of the four extracted
   names has length 4), and that the CHECK/MERGE names appear in neither the slot-1
   nor slot-2 compose text. (Use the `docex-smoke-fixed` project label the fixture
   emits — confirm from `test_slot_primitive.py`.) The same disjointness holds for
   `container_name:` — assert at least the `-exec` container name carries the right
   segment per slot, as `test_slot_primitive` does.

3. **Derivation identities** — `env_compose_project(ctx, "test", slot=CHECK_SLOT)`
   == `<label>-test-s9`, `slot=MERGE_SLOT` == `<label>-test-s10`, both disjoint
   from `slot=1` (`<label>-test`) and `slot=2` (`<label>-test-s2`); `slot=1` equals
   the no-slot call.

4. **check threads CHECK_SLOT / merge threads MERGE_SLOT** — mirror
   `tests/unit/test_slot_orchestration.py`'s fake-docker approach (a recording fake
   `DockerClient`). Drive `run_check` (default slot) and assert the recorded
   `compose_up`/`compose_run_one_off` calls carry `project_name` == `<label>-test-s9`
   and CHECK_SLOT exec keys; drive `run_merge`'s in-process `run_check` (or call
   `run_check(..., slot=MERGE_SLOT)` directly) and assert `<label>-test-s10`.
   Reuse whatever worktree/fake-git harness `test_pipeline_check.py` /
   `test_slot_orchestration.py` already provide rather than inventing a new one; if
   a full `run_check` drive is heavy, a focused test that asserts
   `run_check(..., slot=MERGE_SLOT)` reaches `run_test` with `slot=MERGE_SLOT`
   (monkeypatch `run_test` to record its `slot` kwarg) is an acceptable lighter
   proof — pair it with the compiled-name disjointness (item 2), which is the
   airtight half.

5. **CLI ceiling** — call `_cmd_test(["--slots", "9"])` (== `MAX_TEST_SLOTS + 1`)
   and assert it returns 64 without launching a job (mirror how
   `__main__`/`_cmd_test` usage-error tests are written elsewhere; if `_cmd_test`
   is awkward to call directly, assert via the same harness existing `--slots`
   usage tests use). Assert `--slots 8` (== `MAX_TEST_SLOTS`) is accepted (does not
   return 64 at the guard — stub the job launch so the test stays a unit).

Keep every test in this file a pure unit (no real docker); the SC4 collision proof
is a property of the compiled names, which items 1–3 pin exactly.

---

## Step 9 — Verify

From the docex root:

```sh
python -m pytest tests -q            # full default suite — must be green
git -C . diff --stat infra/output    # MUST be empty: the default path is unchanged
python -m pytest tests -q -m integration   # run ALONE — confirm still green/partition
```

- **Byte-identical default gate:** `docex test` (slot 1) is unchanged — no new
  compile call, no pre-up `compose down`, no injection. `check` now compiles at
  slot 9 into the gitignored `.docex/slots/test/9/`, so `docex compile`'s slot-1
  `infra/output/` and `test_slot_golden.py` are untouched. Confirm
  `test_slot_golden.py` is green and `git diff infra/output` is empty.
- Do NOT edit any file under `plans/core/`, any doctrine `.md`, or `CHANGELOG.md` —
  those are the documentation step, handled by the coordinator after review.
- Follow `docex_process.md` § Running the automated tests: `python -m pytest`
  (never bare `pytest`), default suite is `tests`, `-m integration` runs alone.

## Out of scope / do not touch

- The `docex test --slots N` sharded path (`_run_test_sharded` / `_run_one_slot`)
  beyond the CLI ceiling (Step 5) and the shared `run_test` head (Step 2).
- Any other command's CLI — `slot` is an internal param, never argparse-exposed.
- No dynamic slot allocator; the reserved constants are the whole mechanism.

# Mod 174 — Implementation steps

Add `--slots N` to `docex check` and `docex merge` so the gate's defensive test
run can shard, mirroring `docex test --slots N`. This is **plumbing + arithmetic**
(design validated by spike; see `overview.md`). Code + tests only — the six-artifact
documentation alignment is handled in the mod's **documentation step**, NOT here.

Paths below are relative to the docex project root `~/.claude/jean_baudrillard/docex`.

## Invariants to preserve (read first)

- **`--slots 1` / omitted must be byte-identical to today** for both check and
  merge, *except* merge's single-stack reserved index renumbers `10 → 17` (an
  internal ephemeral `_s{k}` segment; only `test_reserved_slots.py` observes it).
- **Physical slot vs. logical shard index are different numbers.** The physical
  slot (`9..16` for check, `17..24` for merge) names compose resources; the
  **logical shard index `1..N`** is what the project's `test.sh` reads from
  `DOCEX_TEST_SLOT` to pick its `1/N` share. Band-offset shards MUST inject
  `DOCEX_TEST_SLOT = physical_slot - base_slot + 1` (i.e. `1..N`), never the
  physical slot. Getting this wrong makes a sharded gate run the wrong/empty
  subset while still going green — the highest-risk bug in this mod.
- **Bands are fixed width `MAX_TEST_SLOTS`** and disjoint by construction:
  test `1..8`, check `9..16`, merge `17..24`.
- The sharded runner's mutual-exclusion rule stands: `slot=` (single reserved
  stack) and `slots=`/`base_slot` (fan-out) never mix in one call.

---

## Step 1 — Band constants (`src/docex/orchestrate/_common.py`)

Replace the single reserved constants (currently lines ~29–41):

```python
MAX_TEST_SLOTS = 8
CHECK_SLOT = MAX_TEST_SLOTS + 1   # 9
MERGE_SLOT = MAX_TEST_SLOTS + 2   # 10
```

with the band model:

```python
MAX_TEST_SLOTS = 8
# Reserved bands, each MAX_TEST_SLOTS wide, derived from the ceiling so they stay
# disjoint by construction if MAX_TEST_SLOTS is retuned: test 1..8, check 9..16,
# merge 17..24. A gate's BASE doubles as its single-stack (`--slots 1`) slot.
CHECK_BASE = MAX_TEST_SLOTS + 1        # 9
MERGE_BASE = 2 * MAX_TEST_SLOTS + 1    # 17
CHECK_SLOT = CHECK_BASE                 # 9  (single-stack default; unchanged)
MERGE_SLOT = MERGE_BASE                 # 17 (was 10 — deliberate renumber)
```

Add a small helper next to them (reused by the orchestrator and the reaper):

```python
def band_slots(base: int, slots: int) -> list[int]:
    """The physical slot indices for a `slots`-wide fan-out based at `base`."""
    return list(range(base, base + slots))
```

Update the surrounding comment block to describe bands rather than "ceiling+1/+2".

## Step 2 — Sharded runner: worktree overrides + base offset + logical index (`src/docex/orchestrate/test.py`)

### 2a. `_run_one_slot` — add `project_dir` and a logical `shard_index`

Current signature takes `slot`, `slots`, `env_file`, `selector`. Change to also
accept `project_dir: "Path | None" = None` and `shard_index: int | None = None`.

- Thread `project_dir=project_dir` into **every** `docker.compose_*` call in this
  function (`compose_up`, each `compose_run_one_off`, and the `finally`
  `compose_down`) so the shards resolve build contexts/bind-mounts against the
  worktree when check drives them. (`compose_file`, `project_name`, and
  `exec_service_key` stay keyed on the **physical** `slot`.)
- The injected env becomes the **logical** index:
  ```python
  logical = shard_index if shard_index is not None else slot
  slot_env = {"DOCEX_TEST_SLOT": str(logical), "DOCEX_TEST_SLOTS": str(slots)}
  ```
  (Default `shard_index=None ⇒ logical==slot` keeps the standalone base-1 path
  byte-identical.)

### 2b. `_run_test_sharded` — `project_dir`, `env_file_override`, `base_slot`

Change signature to add `project_dir=None`, `env_file_override=None`,
`base_slot: int = 1`. Body changes:

- Env file + compile:
  ```python
  if base_slot == 1 and env_file_override is None:
      ensure_compiled(ctx)              # standalone path: unchanged
  env_file = env_file_override if env_file_override is not None else aggregate(ctx, env=_TEST_ENV)
  for k in band_slots(base_slot, slots):
      compile_slot(ctx, _TEST_ENV, k)
  ```
  (For the check/merge worktree path `base_slot != 1` and an override is given, so
  `ensure_compiled` is skipped — the caller already compiled+validated the tree;
  each band slot is compiled explicitly. Mirrors the reserved-slot single-stack
  path, which also skips `ensure_compiled`.)
- Submit per physical slot, passing the logical index and `project_dir`:
  ```python
  for k in band_slots(base_slot, slots):
      pool.submit(
          _run_one_slot, ctx, docker,
          slot=k, shard_index=k - base_slot + 1, slots=slots,
          env_file=env_file, selector=selector, project_dir=project_dir,
      )
  ```
  Keep the existing "first non-zero, lowest slot first" result reduction (iterate
  the same `band_slots` order).

### 2c. `run_test` — forward the new params

`run_test` already declares `project_dir` / `env_file_override`. Add
`base_slot: int = 1`. In the `slots >= 2` branch, forward all three:

```python
if slots >= 2:
    return _run_test_sharded(
        ctx, docker, selector=selector, slots=slots,
        project_dir=project_dir, env_file_override=env_file_override,
        base_slot=base_slot,
    )
```

The single-stack (`slots == 1`) path is unchanged.

## Step 3 — `run_check` gains `slots` + `base_slot` (collapse `slot` → `base_slot`) (`src/docex/pipeline/check.py`)

**Rename `run_check`'s `slot` param to `base_slot`** (default `CHECK_BASE`) and add
`slots: int = 1`. Rationale: a gate has ONE band whose base doubles as its
single-stack slot (`CHECK_SLOT == CHECK_BASE`, `MERGE_SLOT == MERGE_BASE`), so a
separate `slot` param would be two always-equal values inviting inconsistency.

- Update the import: `CHECK_SLOT` → also import `CHECK_BASE` (keep `CHECK_SLOT`
  only if still referenced; prefer `CHECK_BASE`).
- Signature: `def run_check(ctx, docker, git, *, base_slot: int = CHECK_BASE, slots: int = 1) -> int:`
- In the test-run section (the block that today does
  `compile_slot(worktree_ctx, "test", slot)` → `_compose_build` →
  `run_test(..., slot=slot)`):
  - **`slots >= 2`** (new, DQ1(a) — no separate build gate; each shard builds):
    ```python
    rc = run_test(
        worktree_ctx, docker,
        project_dir=worktree, env_file_override=env_file,
        slots=slots, base_slot=base_slot,
    )
    if rc != 0:
        print(f"error: sharded 'docex test' against worktree exited {rc}.", file=sys.stderr)
        return rc
    ```
  - **`slots == 1`** (unchanged): keep today's `compile_slot(worktree_ctx, "test", base_slot)`
    + `_compose_build(...)` + `run_test(worktree_ctx, ..., slot=base_slot)` path
    verbatim (just `slot` → `base_slot` at these call sites and for
    `check_project_name = env_compose_project(worktree_ctx, "test", slot=base_slot)`).
- Provenance record write (`.docex/checks/`) is unchanged — a sharded check still
  runs the whole suite (union of shards) and records the same green.

## Step 4 — `run_merge` gains `slots`; drives the merge band (`src/docex/pipeline/merge.py`)

- Signature: `def run_merge(ctx, docker, git, *, slots: int = 1) -> int:`
- Import `MERGE_BASE` (keep `MERGE_SLOT` only if still needed).
- The defensive-recheck call (currently `run_check(ctx, docker, git, slot=MERGE_SLOT)`):
  ```python
  rc = run_check(ctx, docker, git, base_slot=MERGE_BASE, slots=slots)
  ```
  This runs merge's in-process defensive check single-stack at slot 17 when
  `slots == 1`, or sharded across `17..17+N-1` when `slots >= 2` — always in the
  merge band, disjoint from a concurrent standalone `check` at the check band.
  Update the `WHY slot=MERGE_SLOT` comment to `WHY base_slot=MERGE_BASE`.

## Step 5 — CLI: `--slots` on check + merge (`src/docex/__main__.py`)

- Factor the test-command's slot guard into a shared helper (avoids triplicating
  it):
  ```python
  def _validate_slots(n: int) -> int | None:
      """Return an EX_USAGE code if n is out of the 1..MAX_TEST_SLOTS band, else None."""
      from docex.orchestrate._common import MAX_TEST_SLOTS
      if n < 1:
          print("error: --slots must be >= 1.", file=sys.stderr); return 64
      if n > MAX_TEST_SLOTS:
          print(f"error: --slots {n} exceeds MAX_TEST_SLOTS ({MAX_TEST_SLOTS}); "
                f"the slot band is 1..{MAX_TEST_SLOTS}.", file=sys.stderr); return 64
      return None
  ```
  Refactor `_cmd_test` to use it (behavior identical: still returns 64).
- In `_cmd_check` and `_cmd_merge`, add:
  ```python
  parser.add_argument(
      "--slots", type=int, default=1, metavar="N",
      help="shard the gate's defensive test run across N isolated stacks on this "
           "host (check band 9..16 / merge band 17..24). N=1 (default) is "
           "single-stack, byte-identical to today. Capped at MAX_TEST_SLOTS.",
  )
  ```
  then after parsing: `rc = _validate_slots(ns.slots)` → `if rc is not None: return rc`.
- Thread `slots=ns.slots` into `run_check_job(...)` / `run_merge_job(...)`.

## Step 6 — Durable-job launch/body/teardown params (`src/docex/jobs/commands.py`)

- `run_check_job(ctx, docker, git, *, detach: bool, slots: int = 1)` and
  `run_merge_job(..., slots: int = 1)`.
- `_run_check_body` / `_run_merge_body` currently ignore `params`. Read the count
  and pass it through:
  ```python
  def _run_check_body(ctx, docker, params) -> int:
      from docex.pipeline.check import run_check
      slots = int((params or {}).get("slots") or 1)
      return run_check(ctx, docker, SubprocessGitClient(), slots=slots)   # base_slot defaults CHECK_BASE
  def _run_merge_body(ctx, docker, params) -> int:
      from docex.pipeline.merge import run_merge
      slots = int((params or {}).get("slots") or 1)
      return run_merge(ctx, docker, SubprocessGitClient(), slots=slots)
  ```
- Generalize `_check_teardown_params` to the band:
  ```python
  def _check_teardown_params(ctx, git, *, base_slot: int, slots: int) -> dict:
      from docex.orchestrate._common import env_compose_project, band_slots
      short_sha = git.head_sha(ctx.project_root, short=True)
      return {
          "worktree_slug": f"check-{short_sha}",
          "compose_projects": [env_compose_project(ctx, "test", slot=k)
                               for k in band_slots(base_slot, slots)],
          "base_slot": base_slot,
          "slots": slots,
      }
  ```
  (`slots` here doubles as the body's shard count — one key serves both.)
- `run_check_job` → `params=_check_teardown_params(ctx, git, base_slot=CHECK_BASE, slots=slots)`
  (import `CHECK_BASE`); `run_merge_job` → `base_slot=MERGE_BASE`.

## Step 7 — Reaper reclaims the whole band (`src/docex/jobs/reaper.py`)

Only `_teardown_worktree_job` changes (the `test`-kind `_teardown_test_stack`
already loops `range(1, slots+1)` at base 1 and is unaffected — `test` is always
base 1).

In `_teardown_worktree_job`, replace the single `compose_project` down with a loop
over the recorded band, keeping the exact existing call shape (main test compose
file + per-band project name, `preserve_volumes=False`):

```python
projects = params.get("compose_projects")
if not projects:
    legacy = params.get("compose_project")   # pre-mod-174 record
    projects = [legacy] if legacy else []
for cp in projects:
    docker.compose_down(
        compose_file_for(ctx, "test"),
        preserve_volumes=False,
        project_name=cp,
    )
# (If projects is empty, the existing namespace-sweep fallback still applies.)
```

Worktree-dir removal (step 2 of that function) is unchanged. Update the docstring
to say it reclaims **N** band stacks, not one.

## Step 8 — Tests

Run only the tests touching these modules (`docex test` selector, e.g. the
`test_reserved_slots` + reaper + sharding files).

### 8a. `tests/unit/test_reserved_slots.py` (update)
- Constants: assert `CHECK_BASE == MAX_TEST_SLOTS + 1`, `MERGE_BASE == 2*MAX_TEST_SLOTS + 1`,
  `CHECK_SLOT == CHECK_BASE`, `MERGE_SLOT == MERGE_BASE`. Remove the old
  `MERGE_SLOT == MAX_TEST_SLOTS + 2` assertion.
- Update every hardcoded merge name `…-s10…` → `…-s17…` (volume-name and
  project-name assertions for `MERGE_SLOT`).
- `run_check` signature test: the param is now `base_slot` (default `CHECK_BASE`),
  not `slot`; add a `slots` param (default 1). Update the merge-threads-slot spy
  to `def spy(ctx, docker, git, *, base_slot=CHECK_BASE, slots=1)` and assert merge
  threads `base_slot == MERGE_BASE`.
- **New — band disjointness:** `band_slots(1, MAX)`, `band_slots(CHECK_BASE, MAX)`,
  `band_slots(MERGE_BASE, MAX)` are pairwise disjoint and max index `== 3*MAX`.
- **New — CLI guard on check/merge:** `_cmd_check(["--slots", str(MAX+1)]) == 64`
  and `_cmd_merge([...]) == 64`; `--slots MAX` accepted (spy `run_check_job`/
  `run_merge_job` to assert `slots` is forwarded).

### 8b. New unit test — logical vs physical index (critical)
With a fake `DockerClient` capturing per-call `project_name` + injected `env`,
drive `_run_test_sharded(..., slots=3, base_slot=CHECK_BASE, project_dir=<tmp>,
env_file_override=<tmp>)` (stub `compile_slot`/`aggregate`) and assert: physical
project names are `…-s9/-s10/-s11`, while injected `DOCEX_TEST_SLOT` values are
`1/2/3` and `DOCEX_TEST_SLOTS == 3`. This guards the highest-risk bug.

### 8c. New unit test — sharded check wiring
Spy `orchestrate.test.run_test`; call `run_check(ctx, docker, git, slots=2)` (stub
the worktree/git plumbing as the existing check tests do) and assert `run_test`
was called with `project_dir` = the worktree, `env_file_override` set, `slots=2`,
`base_slot=CHECK_BASE`, and that the standalone `_compose_build` gate was **not**
invoked on the `slots>=2` path.

### 8d. New unit test — reaper band teardown
Build a `meta` with `kind="check"` and `compose_projects=[p9, p10]`; call
`_teardown_worktree_job` with a fake DockerClient and assert `compose_down` was
called once per band project name. Add a legacy-record case (`compose_project`
only) that still downs the single stack.

## Step 9 — Regression smoke (implementor, quick)
- `docex test --slots 2` against `test_projects/fixed` still green (proves the
  logical-index refactor didn't disturb the standalone base-1 path).
- The sharded-worktree behavior itself is already spike-validated; a full
  `docex check --slots 2` live run is optional and heavy — leave it to the mod's
  manual-test step unless quick.

## Contracts
None — docex has no `infra.yml`/surfaces, so there are no service contracts to
update.

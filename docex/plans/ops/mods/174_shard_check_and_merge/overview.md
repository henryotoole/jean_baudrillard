# Mod 174 — `--slots N` for `check` and `merge` (shard the gate's test run)

## Problem

`docex test` can shard its suite across `N` isolated slot stacks (`--slots N`,
mods 152/154), but the **gate** cannot. `docex check` and `docex merge` run their
defensive `test` suite in a **single, unsharded** stack — `check` at `CHECK_SLOT`
(9), `merge`'s in-process recheck at `MERGE_SLOT` (10). On a project with a large
suite, the gate — the heaviest and most-run pipeline step — is stuck at 1× while
a standalone `docex test` gets `N×`. There is no way to bring sharded parallelism
to the one step that most needs it.

The wall is structural, in two places:

1. **The sharded runner is walled off from the worktree.** `run_test`'s
   single-stack path accepts the `project_dir` / `env_file_override` overrides
   that let `check` run against an ephemeral worktree; `_run_test_sharded` /
   `_run_one_slot` accept **none** of them and hardcode the slot range `1..N`
   (`orchestrate/test.py`). So the sharded path can only run against the main
   project tree at the test band — never a worktree at a reserved band.
2. **The reserved slots are single indices, not bands.** `CHECK_SLOT` /
   `MERGE_SLOT` are one slot each (`MAX_TEST_SLOTS + 1` / `+ 2`), sized for a
   single-stack defensive run. A sharded gate needs `N` disjoint slots that also
   stay clear of a concurrent standalone `docex test --slots M`.

### Feasibility already validated (spike)

Before committing, a throwaway spike (`test_projects/fixed` + a temp git worktree,
zero shipped code touched) exercised the one genuinely-new risk — **N concurrent
slot stacks against a single ephemeral worktree tree at band-offset slots**:

- **Naming disjointness** — 2 slots compiled at the check band (9, 10) against the
  worktree: 13 stack-scoped names/slot, **0 shared**, project-names disjoint,
  including the DB volume `name:` (`…-s9-appdb_data` vs `…-s10-appdb_data`) the
  whole slot mechanism exists to separate. Band-offset slots namespace exactly as
  `1..8` do (the segment is pure `_s{k}` interpolation).
- **Build race** — 2 **concurrent** `docker compose build` of the codebase's
  **shared** image tag (`…/api:0.0.23`, not per-slot) from one worktree context:
  both green in 24.5s, no cache corruption, no tag clobber.

Conclusion: this mod is **plumbing + arithmetic**, not a structural change. The
up/migrate/run half of a shard is byte-identical to the shipped standalone
`--slots` path — only `project_dir` and the slot base differ.

## The change

### 1. Reserved *bands* instead of reserved *slots* (`orchestrate/_common.py`)

Generalize the two reserved constants into two reserved bands, each
`MAX_TEST_SLOTS` wide, derived from the ceiling so they stay disjoint by
construction if `MAX_TEST_SLOTS` is ever retuned:

```
MAX_TEST_SLOTS = 8
CHECK_BASE = MAX_TEST_SLOTS + 1        # 9    check --slots N → slots 9 .. 9+N-1
MERGE_BASE = 2 * MAX_TEST_SLOTS + 1    # 17   merge --slots N → slots 17 .. 17+N-1
CHECK_SLOT = CHECK_BASE                 # 9    (--slots 1 default; unchanged)
MERGE_SLOT = MERGE_BASE                 # 17   (was 10 — deliberate renumber)
```

- Fixed-width bands (always `MAX_TEST_SLOTS`, regardless of the `N` a given run
  actually uses) keep `test`(`1..8`) + `check`(`9..16`) + `merge`(`17..24`)
  disjoint **by construction** — the exact three-way co-occurrence the vessel
  locks already permit (≤1 test, ≤1 check, ≤1 merge). Highest possible slot 24.
- `--slots 1` stays single-stack at the band base. `check` is byte-identical to
  today (base is still 9). `merge`'s single-slot index **renumbers 10 → 17**; it
  is an internal, ephemeral `_s{k}` name segment that nothing persists, so the
  renumber is safe (see Design Question 2).

### 2. `--slots N` on `check` and `merge` (`__main__.py`, `pipeline/*`)

- Add `--slots N` (default 1) to the `check` and `merge` argparsers, validated
  `1..MAX_TEST_SLOTS` exactly like `test` (reuse the same ceiling guard / exit
  64). `--slots 1` / omitted is the current behavior.
- Thread it as `run_check(..., slots=N)` and `run_merge(..., slots=N)`.
- `merge` runs `check` in-process; a `--slots N` on `merge` flows into that
  in-process `run_check` **at the merge band** (base `MERGE_BASE`), preserving
  the "merge's defensive stack is name-disjoint from a standalone check" property.

### 3. Teach the sharded runner worktree overrides + a base offset (`orchestrate/test.py`)

`_run_test_sharded` / `_run_one_slot` gain what the single-stack path already has,
plus a base:

- `project_dir` and `env_file_override` — so the shards build/run against the
  worktree tree and its pre-built aggregate (identical to how the single-stack
  check path uses them).
- `base_slot` — the shard loop becomes `range(base_slot, base_slot + slots)`
  instead of `range(1, slots + 1)`. Each shard's per-slot `project_name` is still
  **derived** (`env_compose_project(ctx, "test", slot=base+k)`), not passed in —
  it is already worktree-safe because slot names derive from the project-scoped
  `global_name`, not from any path (spike-confirmed). So no `project_name`
  override is needed on the sharded path.
- `run_test` threads these through; `slot=` (single reserved slot) and `slots=`
  (shard count) remain mutually exclusive as today, with `base_slot` meaningful
  only on the `slots>=2` path.

### 4. `check` drives the sharded path when `slots>=2` (`pipeline/check.py`)

Today `check` compiles + `_compose_build`s one slot, then `run_test(..., slot=slot)`.
With `slots>=2` it instead drives the sharded path against the worktree at
`CHECK_BASE`: `run_test(worktree_ctx, ..., project_dir=worktree,
env_file_override=env_file, slots=N, base_slot=CHECK_BASE)`. The separate pre-build
gate is the subject of **Design Question 1**.

### 5. Fleet reaper reclaims the whole band (`jobs/reaper.py`, `jobs/commands.py`)

A hard-killed **sharded** check/merge vessel now leaks `N` slot stacks in its
band, not one. Today:
- the `test` fleet reaper reads `meta.params['slots']` and loops `range(1, N+1)`
  (base 1 hardcoded);
- `check`/`merge` teardown params record a **single** `slot` (`_check_teardown_params(..., slot=CHECK_SLOT/MERGE_SLOT)`).

Change: check/merge launch records `slots` **and the band base** in `meta.params`,
and the fleet teardown loops `range(base, base + slots)`. `--slots 1` records the
single base slot exactly as today (a pre-slots record still defaults to 1 stack).
A shard left up on failure is still reclaimed by the next run that touches that
slot number, unchanged.

## Scope

**Code**
- `src/docex/orchestrate/_common.py` — band constants (`CHECK_BASE`/`MERGE_BASE`;
  `CHECK_SLOT`/`MERGE_SLOT` become the bases; `MERGE_SLOT` 10→17). Optional
  `check_band(n)` / `merge_band(n)` helpers returning the slot list.
- `src/docex/orchestrate/test.py` — `project_dir` / `env_file_override` /
  `base_slot` on `_run_test_sharded` + `_run_one_slot`; `run_test` threads them;
  offset slot loop.
- `src/docex/pipeline/check.py` — `run_check(..., slots=N)`; `slots>=2` drives the
  sharded worktree path at `CHECK_BASE`; build-gate handling per DQ1.
- `src/docex/pipeline/merge.py` — `run_merge(..., slots=N)`; in-process
  `run_check` at the merge band.
- `src/docex/__main__.py` — `--slots` on the `check` + `merge` subparsers; shared
  ceiling guard; thread to `run_check`/`run_merge`.
- `src/docex/jobs/commands.py` + `src/docex/jobs/reaper.py` — record `slots`+base
  in check/merge `meta.params`; band-aware fleet teardown (`range(base, base+N)`).

**Tests**
- `tests/unit/test_reserved_slots.py` — update for the band model and the
  `MERGE_SLOT` 10→17 renumber (this file hardcodes `-s10-` volume names for
  merge). Add: band disjointness (`test`∪`check`∪`merge` slot sets are pairwise
  disjoint at full width), `--slots` accepted on check/merge and capped, the
  offset slot loop.
- New/extended: sharded-check worktree wiring (the sharded path receives
  `project_dir`/`env_file_override`/`base_slot`); reaper reclaims a check/merge
  **band** on orphan.
- Relevant slice runnable via `docex test <subset>`; the implementor runs only
  tests touching these modules.

**Docs (documentation step — six-artifact alignment, NOT the implementation step)**
- `doctrine/infrastructure/docex.md` — `check` / `merge` entries gain `[--slots N]`
  and a cross-ref to `test`'s sharding.
- `doctrine/infrastructure/tests.md` — note the gate can shard too.
- `doctrine/infrastructure/specifics/detachable.md` — `check` / `merge` sections:
  reserved **bands** (not single slots), fleet reaper over the band, the
  `MERGE_SLOT` renumber.
- `docex/plans/design/specifics/subcommand_surface.md` — the durable-jobs / slot
  paragraph (the "reserved slot above the band" / three-disjoint-bands prose).
- `docex/plans/design/specifics/compiler.md` — the `compile_slot` callers list
  (check/merge now shard, not just single-slot).
- `docex/plans/design/lexicon.md` — the `Slot` entry.
- `doctrine_excerpts/` — check if any `docex why` excerpt names the check/merge
  reserved slots.

## Out of scope / non-goals

- No change to the `test` slot band, `MAX_TEST_SLOTS`, or the reference `test.sh`
  shard split. Sharding remains a project responsibility via
  `DOCEX_TEST_SLOT`/`DOCEX_TEST_SLOTS`; a project whose `test.sh` ignores them
  gets no speedup (it runs the whole suite in each shard) but stays correct.
- No dynamic slot allocator — bands stay deterministic reserved constants.
- The green-check provenance record (`.docex/checks/`) and merge's trust-forward
  are unaffected: a sharded check still runs the whole suite (union of shards) and
  writes the same record.

## Design questions (resolved)

1. **Build-gate separation in a sharded `check` → RESOLVED: (a) fold the build
   into the shards.** No separate `_compose_build` phase on the sharded path; each
   shard's `compose_up(build=True)` performs the (same, containerized) build, and a
   build break surfaces as a shard failure. The spike confirmed concurrent
   same-tag builds are safe. Note this settles only the *diagnostic phasing* — the
   build is containerized either way and cannot be a non-containerized host step:
   the build's output *is* the image the tests run inside, and the build toolchain
   lives in the Dockerfile `build` stage, not on the vessel/merge host (which
   carries only docker/tofu/ansible/aws/git/jq). A host-native `build.sh` would
   produce a `dist/` the tests never use and break the doctrine's "test the exact
   artifact a prod release ships" guarantee (cicd.md build-test model). *(The
   single-stack `--slots 1` check path keeps its existing `_compose_build` gate
   unchanged — this only concerns the new `slots>=2` fan-out.)*

2. **`MERGE_SLOT` 10 → 17 → RESOLVED: renumber.** One consistent
   `MERGE_BASE = 2*MAX_TEST_SLOTS + 1`. Only `test_reserved_slots.py` hardcodes the
   old value (updated here); nothing persists the index across runs.

3. **Default stays `--slots 1` → RESOLVED: yes, explicit `--slots` only.** No
   auto-shard, no `project.yml` default; the default is single-stack and
   byte-identical to today.

4. **Fixed band width vs. sized-to-N → RESOLVED: fixed.** Each band is always
   `MAX_TEST_SLOTS` wide, so `test`∪`check`∪`merge` are disjoint by construction.

5. **Resource ceiling → RESOLVED: document the caution, no separate cap.** A
   `merge --slots 8` beside a standalone `test --slots 8` is 16 full `test` stacks
   on one host — the operator's per-host call, exactly as `test --slots 8` is
   today. Documented as a caution in `doctrine/infrastructure/docex.md`; no gate
   cap below `MAX_TEST_SLOTS`.

# Mod 155 — `check`/`merge` adopt reserved slots (Goal 4 SC4: close the `--project-name` DB-volume collision)

**Advance 009 (Test Overhaul), Wave 3 — the LAST code mod.** Mod 154 shipped
`docex test --slots N` (Goal 4 SC1/SC2/SC3) and *deliberately withheld* the SC4
work; this mod closes SC4 and thereby completes Goal 4. It makes `check`'s and
`merge`'s defensive test stacks adopt **reserved slots above the `test` band**, so
their compiled `test`-env physical names (esp. the DB volume `name:`) are
deterministically name-disjoint from any `docex test` run and from each other.

Design intent is the reserved-slot band ratified in
[`../154_slots_orchestration/overview.md` § 9](../154_slots_orchestration/overview.md);
this overview turns it into a concrete change against the *current* code and drafts
the doctrine amendments for sarge's sign-off. It does not restate the pre_plan.

---

## 1. The collision, precisely (why the mechanism Mod 152 built is the fix)

Compose's `--project-name` namespaces the resources Compose *tracks by label*
(containers without an explicit name, Compose-created networks, anonymous volumes).
It does **not** rewrite explicit `container_name:` or top-level volume `name:`
fields — the compiler emits those, and they are global on the docker host. So two
stacks that both compile the `test` env **at slot 1** collide on the DB volume
`name:` (`<project>_test_appdb_data`) and on `container_name:`s, *regardless of a
distinct `--project-name`*. The three-way co-occurrence the vessel locks permit
(§ 3) makes this reachable: a standalone `docex check` + a `docex test`, or a
`check` + a `merge`'s in-process defensive check.

Mod 152 built the fix: the slot segment (`_s{k}`) is woven into
`_global_service_name` / `codebase_global_name` / `_network_name` / the volume
names when `slot ≠ 1`, so **every** physical name a slot-`k` stack emits is
disjoint from slot 1 and from any slot `j ≠ k`. Mod 152's own comment names this:
"slotting it here is what closes what `--project-name` cannot." This mod simply
makes `check` and `merge` *use* reserved slots so that segment is present.

---

## 2. The reserved-slot band (finalized constants)

One home for three constants — `src/docex/orchestrate/_common.py`, already the home
of every other slot helper (`env_compose_project`, `slot_compose_file`,
`exec_service_key`):

```python
MAX_TEST_SLOTS = 8              # documented ceiling on `docex test --slots N`
CHECK_SLOT = MAX_TEST_SLOTS + 1  # 9  — check's defensive test stack
MERGE_SLOT = MAX_TEST_SLOTS + 2  # 10 — merge's defensive check stack
```

- **`test` uses slots `1..MAX_TEST_SLOTS`** (1..8). `CHECK_SLOT`/`MERGE_SLOT`
  are **derived** as ceiling+1/+2 rather than free-standing magic numbers, so they
  are disjoint from the whole `test` band *by construction* and stay disjoint if
  `MAX_TEST_SLOTS` is ever retuned. They are ephemeral per-run slot indices (like
  every test slot), never a persisted identity, so deriving them from the ceiling
  carries no cross-version-stability obligation.
- **Value choice.** `8` is a generous ceiling — each slot is a full isolated
  `test` stack (compose up + build + migrate), so >8 concurrent stacks is already
  past what one dev host absorbs. The exact number is a documented cap, not a hard
  limit on anything but this one CLI flag.

---

## 3. The concurrency matrix — verified against current code (it holds)

The post-Mod-149 vessel locks are the deterministic vessel **name** as the lock,
scoped per command (`masterplan.md` § Durable jobs; `jobs/reaper.py::preflight`;
`docex.md` § Command Lifecycle). Verified in the code as it stands today:

- **≤1 `docex test`** at a time — vessel `<label>-test-runner`
  (`run_test_job`, `commands.py:174`). Uses slots `1..N` (`N ≤ MAX_TEST_SLOTS`).
- **≤1 `docex check`** at a time — vessel `<label>-check-runner`
  (`run_check_job`, `commands.py:235`). Uses `CHECK_SLOT`.
- **≤1 `docex merge`** at a time — vessel `<label>-merge-runner`
  (`run_merge_job`, `commands.py:273`). Uses `MERGE_SLOT`.
- **Distinct commands do NOT block each other** — a `check` alongside a `merge`
  alongside a `test` is explicitly allowed (three independent lock scopes).

**The load-bearing subtlety, confirmed in the code:** `merge`'s defensive check is
an **in-process** call — `merge.py:96` calls `run_check(ctx, docker, git)`
directly; it does **not** launch a nested `check` vessel and so does **not** take
the `check-runner` lock. Therefore a standalone `docex check` (holding the check
lock, at `CHECK_SLOT`) **can** run concurrently with a `docex merge` whose
in-process defensive check also wants a `test` stack. This is *exactly why*
`merge` needs its own `MERGE_SLOT` rather than reusing `CHECK_SLOT` — otherwise the
two would collide on the DB volume, which is the very defect SC4 closes.

So the only three-way co-occurrence the locks permit is `test`(`1..N`) +
`check`(`CHECK_SLOT`) + `merge`(`MERGE_SLOT`) — three disjoint bands, one per lock
scope. A single `CHECK_SLOT` never self-collides (≤1 check); a single `MERGE_SLOT`
never self-collides (≤1 merge; one merge = one in-process defensive check at a
time). **The matrix holds; no dynamic allocator is needed** (consistent with D5's
deterministic-name philosophy).

---

## 4. The mechanism (how `check`/`merge` thread the reserved slot)

A **new keyword `slot: int` distinct from the shard-count `slots`** — anticipated
verbatim by Mod 154's `run_test` docstring ("so Mod 155 can later add a *distinct*
`slot=` param … without conflating it with this shard count"). `slots` shards the
*integration* tier across N stacks; `slot` runs the *single-stack* path pinned to
one slot index. They never combine (check/merge never shard).

**`run_test(..., slot: int = 1)`** — single-stack path becomes slot-aware:

| | `slot == 1` (default / all existing callers) | `slot != 1` (check/merge only) |
|---|---|---|
| compile | `ensure_compiled(ctx)` (unchanged) | `compile_slot(ctx, "test", slot)` |
| compose file | `compose_file_for(ctx, "test")` | `slot_compose_file(ctx, "test", slot)` |
| project name | `env_compose_project(ctx, "test")` unless override | `env_compose_project(ctx, "test", slot=slot)` unless override |
| exec key | `exec_service_key(ctx, "test", cb)` | `exec_service_key(ctx, "test", cb, slot=slot)` |
| pre-up reap | none (byte-identical to today) | one `compose down` clean-slate, mirroring `_run_one_slot` |

The `slot == 1` column is **byte- and behavior-identical to today** — no new
compile call, no new `compose down`, no injection — which keeps SC2's golden gate
(`test_slot_golden.py`) and the today-exact `docex test` runtime intact. `slots ≥ 2`
still dispatches `_run_test_sharded` before any of this. `slot` and `slots` are
mutually exclusive by construction (check/merge pass `slot=`, never `slots=`).

**`run_check(ctx, docker, git, *, slot: int = CHECK_SLOT)`** — the defensive build +
test compile/run the worktree's `test` env at `slot`:
- the compile-succeeds gate (`run_compile(worktree_ctx)`) is unchanged (it still
  writes the worktree's slot-1 `infra/output/test`, thrown away with the worktree);
- the **defensive build** (`_compose_build`) and **defensive test** (`run_test`)
  switch to the slotted stack: `compile_slot(worktree_ctx, "test", slot)`, build
  against `slot_compose_file(worktree_ctx, "test", slot)`, and the project name
  becomes `env_compose_project(worktree_ctx, "test", slot=slot)`
  (`<label>-test-s{slot}`), replacing the old worktree-unique `<label>-<slug>`
  name. `run_test(..., slot=slot)` does the rest.

**`run_merge` → `run_check(ctx, docker, git, slot=MERGE_SLOT)`** (merge.py:96). That
one-argument change is the whole of merge's adoption: its in-process defensive
check now compiles/runs at `MERGE_SLOT`.

**`__main__.py::_cmd_test`** — add the ceiling enforcement Mod 154 did not:
`ns.slots > MAX_TEST_SLOTS` → usage error (exit 64, EX_USAGE), beside the existing
`ns.slots < 1` guard.

**`jobs/commands.py` (reaper identities)** — `_check_teardown_params` becomes
slot-aware: it records `compose_project = env_compose_project(ctx, "test",
slot=reserved_slot)` (matching the name `run_check` now uses) plus the `slot`
itself; `run_check_job` passes `CHECK_SLOT`, `run_merge_job` passes `MERGE_SLOT`.
The reaper body `_teardown_worktree_job` needs **no change** — it already reads
`params["compose_project"]` and tears that project down by label; recording the
slot-derived name there is sufficient for the container/network reclaim. The leaked
**volume** (a hard-killed check/merge is the only way a stack leaks — `run_test`
always tears down in `finally` on the gate path) is reclaimed by the next
check/merge's slot!=1 pre-up `compose down`, which runs against the freshly
compiled slot file with the correct `_s{slot}` volume name. This keeps the reaper
change minimal and coherent; it does not re-open the crashed-slot half of SC4 that
Mod 154 already delivered.

### Why the project name switches to the slot-derived form

The old worktree-unique `<label>-check-<sha>` name existed "so concurrent checks
don't clash" — but the check vessel lock already guarantees ≤1 check, so the sha
was belt-and-suspenders. The slot-derived `<label>-test-s{CHECK_SLOT}` is
deterministic, symmetric with the `test`/`merge` bands, and lets the reaper derive
the exact project name from the recorded slot. The worktree **directory** slug
(`check-<short_sha>`) is unchanged (still recorded as `worktree_slug`).

---

## 5. SC4 success criterion — how this mod proves it

> The latent `check --project-name` DB-volume collision is **closed**: a `check`
> and a concurrent `docex test` (and a `check` + a `merge`) no longer share DB
> volumes.

Proven by **name-derivation unit assertions** (the manual-test step is waived;
close-out step 13 exercises it live):

1. **Compiled-name disjointness (the core proof).** Compile the fixture `test` env
   at slot 1, at a representative `test` slot (2), at `CHECK_SLOT`, and at
   `MERGE_SLOT`; assert the DB volume `name:` (and `container_name:`s) carry the
   expected segment and are **pairwise disjoint** — `…-test-appdb_data` (slot 1),
   `…-test-s2-appdb_data`, `…-test-s9-appdb_data` (CHECK), `…-test-s10-appdb_data`
   (MERGE). Mirrors `test_slot_primitive.py::test_slot2_emitted_compose_isolates_names`.
2. **Band constants.** `CHECK_SLOT > MAX_TEST_SLOTS`, `MERGE_SLOT > MAX_TEST_SLOTS`,
   `CHECK_SLOT != MERGE_SLOT`.
3. **Derivation identities** — `env_compose_project` / `exec_service_key` at
   `CHECK_SLOT` / `MERGE_SLOT` produce `-s{slot}` forms disjoint from slots `1..N`
   and from each other; `slot=1` is byte-identical to the no-slot call.
4. **check/merge thread the slot** — with a fake docker recording calls (mirroring
   `test_slot_orchestration.py`): `run_check` compiles/brings up the CHECK_SLOT
   stack (project `<label>-test-s9`, CHECK_SLOT exec keys); `run_merge`'s in-process
   `run_check` uses `MERGE_SLOT`.
5. **CLI ceiling** — `docex test --slots 9` (`> MAX_TEST_SLOTS`) returns 64; `--slots 8`
   is accepted.
6. **Byte-identical default** — `run_test` slot=1 unchanged; the Mod 152 golden
   gate and `git diff infra/output` stay clean.

**Cheap real-docker isolation test (optional, § kept only if trivially fast):** a
`check` running concurrently with a slot-1 `docex test` against the tiny fixture,
asserting both DB volumes exist under disjoint names and neither run disturbs the
other. If it cannot be kept cheap, rely on the name-derivation units above +
Mod 153/154's existing single-slot real gates. **Recommendation: rely on the units;**
the disjointness is a pure function of the compiled names, which the unit assertions
pin exactly.

---

## 6. Doctrine-text amendments (land in this mod; drafted for sign-off)

Per `docex_process.md`, doctrine changes first and require operator sign-off. This
is where the **collision-closed claim** finally lands (Mod 154 withheld it). Radius:

### A. `doctrine/infrastructure/docex.md`

- **§ `test`** (the `--slots N` paragraph, ~line 198): add that `N` is capped at
  **`MAX_TEST_SLOTS`** and `docex test --slots N` with `N > MAX_TEST_SLOTS` is a
  **usage error** — the `test` band is slots `1..MAX_TEST_SLOTS`.
- **§ `check`** (~line 227): add a sentence — check's defensive build+test compile
  and run the worktree's `test` env at a **reserved slot (`CHECK_SLOT`) above the
  `test` band**, so its compiled physical names (esp. the DB volume `name:`) are
  disjoint from any `docex test` run; **this closes the `--project-name` DB-volume
  collision** (Compose's `--project-name` does not namespace explicit
  `container_name:`/volume `name:`).
- **§ `merge`** (~line 232): merge's in-process defensive check runs at
  **`MERGE_SLOT`** (distinct from `CHECK_SLOT`), so a `merge` and a concurrent
  standalone `check` are name-disjoint too.
- **§ Command Lifecycle** (~line 45–47): note the reserved band — `test` uses
  `1..MAX_TEST_SLOTS`, `check`/`merge` each a reserved slot above it — so the three
  co-occurring lock scopes are name-disjoint by construction.

### B. `doctrine/infrastructure/cicd.md` — § Check Step and § Merge

Parallel one-line notes: the defensive test/check runs at a reserved slot above the
`test` band, closing the `--project-name` collision.

*(Exact wording drafted in `implementation.md`; the operator's sign-off on this
overview authorizes the edits, per `docex_process.md`.)*

### Docex core-planning-doc impact (documentation step / step 8 — NOT `implementation.md`)

- **`masterplan.md`** — § Durable jobs currently ends: "`check`/`merge`
  slot-adoption (the `check --project-name` collision closure) is the follow-on mod
  155." **Supersede** it with the delivered statement: check/merge run their
  defensive test at reserved slots (`CHECK_SLOT`/`MERGE_SLOT`) above the
  `MAX_TEST_SLOTS` `test` band, closing the `--project-name` DB-volume collision.
  Add the collision-closed claim + the reserved-slot band.
- **`compiler.md`** — if it carries a "check/merge still compile at slot 1" note,
  update to the reserved-slot adoption. (Confirm during the doc step.)

---

## 7. Contracts

**None.** No surface changes; the reserved slots alter no core service's contract.

---

## 8. Boundaries honored

- The `docex test --slots N` sharded path (Mod 154) is untouched **except** for the
  `MAX_TEST_SLOTS` ceiling enforcement, as the task directs.
- No slot flag is exposed on any other command's CLI — `slot` is an internal
  parameter check/merge pass; it never reaches argparse.
- No dynamic allocator; deterministic reserved constants only.

---

## Open design questions (for the design gate)

1. **Constants (§ 2).** Ratify `MAX_TEST_SLOTS = 8`, `CHECK_SLOT = 9`,
   `MERGE_SLOT = 10` (derived as ceiling+1/+2), living in
   `orchestrate/_common.py`. Any preference for a different ceiling or a different
   home?
2. **Reaper minimalism (§ 4).** I keep the reaper change to just recording the
   slot-derived `compose_project` (+ the slot) in `meta.params`, relying on the
   next-run pre-up `compose down` for the leaked volume rather than compiling a
   slot file inside the reaper. This matches "the crashed-slot half was delivered
   by Mod 154; you need only the collision closure." Confirm you're happy with that
   boundary, or ask for the reaper to fully recompile+reap the reserved slot.
3. **Real-docker isolation test (§ 5).** Rely on the name-derivation unit
   assertions (recommended), or require the cheap concurrent check-vs-test real
   gate too?
4. **Doctrine wording (§ 6).** Sign off the `docex.md`/`cicd.md` radius and the
   collision-closed claim (operator sign-off required before I edit doctrine).

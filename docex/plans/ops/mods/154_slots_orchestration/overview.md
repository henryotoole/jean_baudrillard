# Mod 154 — `docex test --slots N` orchestration + shard injection + fleet reaper

**Advance 009 (Test Overhaul), Wave 3, Mod 9 — the final code mod, closing
Goal 4 / F7.** Turns the Mod 152 slot primitive + the Mod 153 per-slot `test`
web bridge into real parallel sharding. Skills loaded: `docex-edit`,
`infra-compile`, `testing`.

Design rationale lives in
[`../../advances/009_test_overhaul/pre_plan.md` § SC2/SC1/SC3](../../advances/009_test_overhaul/pre_plan.md)
and [`advance_plan.md` Wave 3 / Goal 4](../../advances/009_test_overhaul/advance_plan.md).
This overview does not restate it; it turns it into a concrete change and drafts
the doctrine amendments — and it **recommends a scope split** (§ 9) that sarge
must ratify before `implementation.md` is written.

---

## 1. What already exists (the ground this builds on)

- **Mod 148** — the `job` substrate: `docex test` is a durable job on a single
  `<label>-test-runner` **container vessel**; `jobs/record.py::classify()` is the
  reconcile primitive `job ls` and the single-run reaper share;
  `RunMeta` already carries a `slot: int` field and a free-form `params` dict.
- **Mod 151** — `docex test unit [subset]` (no-stack synchronous) /
  `docex test integration [subset]` (durable job); the **`DOCEX_TEST_SELECTOR`**
  one-way injection contract, honored by every fixture shim.
- **Mod 152** — the compiler slot primitive: `compile_env(..., slot=k)`,
  `compile_slot(ctx, env, k)` (slot 1 → `infra/output/<env>/`; k>1 →
  `.docex/slots/<env>/<k>/`), the `_s{k}` segment on every physical name when
  `slot≠1` (slot 1 byte-identical), `CompiledEnv.slot`. **Left two re-derivers at
  `slot=1` as an inherited seam for this mod:** `orchestrate/_common.py::exec_service_key`
  and `orchestrate/migrate.py::_migration_task_family`.
- **Mod 153** — `test`'s web network is an env-tier, per-slot, non-external
  bridge (`${project}-test${slot_seg}-web`); `test` needs no projinfra. A per-slot
  `test` stack is now fully name-isolated across **all** physical resources.

So the isolation mechanism is complete; this mod builds the **orchestration** that
drives N of them.

---

## 2. The orchestration-loop shape

`docex test` is a durable job: foreground `run_test_job` → preflight the lock →
launch the one `<label>-test-runner` vessel → inside the vessel
`run_in_vessel` → `_run_test_body` → `run_test(...)`. **The N-slot loop lives
inside `run_test` (i.e. inside the vessel)** — the vessel is the durable job; the
N slot *stacks* are sibling compose stacks it brings up over DooD. The vessel
**lock is unchanged**: still per-`(project, test)`; slots are internal
parallelism, not extra lock scopes. Two `docex test` invocations (any N) still
refuse each other.

### `run_test(ctx, docker, *, tiers, selector, slots=1, ...)`

- **`slots == 1` (default / omitted) → the existing single-stack path, byte- and
  behavior-identical to today.** Untouched: one stack, unit then integration in
  it, **no** `DOCEX_TEST_SLOT` injection, compiles to `infra/output/test`. This is
  what preserves SC2 (the Mod 152 golden gate stays green — no new compile call on
  the default path) and the today-exact runtime behavior.

- **`slots >= 2` → the new sharded path:**
  1. **Unit runs ONCE** (if `"unit" in tiers`): no-stack, via the existing
     `run_test_unit` mechanism (`--no-deps` throwaway exec container, standard
     slot-1 compose project), honoring `selector`. Fail-fast — a red unit tier
     gates the expensive integration fan-out, exactly as the cheap tier gates the
     expensive one today. **Sharding unit is pointless (no stack); it is not
     sharded and receives neither `SLOT` nor `SLOTS`.**
  2. **Integration shards across N slots** (if `"integration" in tiers`): compile
     slots `1..N` serially (`compile_slot(ctx, "test", k)` — cheap, deterministic,
     keeps the concurrent section pure docker), then run the N slots
     **concurrently** via `concurrent.futures.ThreadPoolExecutor(max_workers=N)`.
     Each slot worker `_run_one_slot(k, N)`:
     - **pre-up `compose down`** of the slot's project (idempotent clean slate —
       this is where "a crashed/failed slot is reaped on the next invocation"
       lands for the same-numbered slot; see § 5).
     - `compose up --build -d` against the slot's compose file, project name
       `<label>-test-s{k}` (k=1 → `<label>-test`), shared agg env-file.
     - migrate every schema-owning codebase: `exec_service_key(ctx, "test", cb,
       slot=k)` + `compose_run_one_off(["./migrate.sh"])`.
     - integration shim per codebase: `exec_service_key(slot=k)` +
       `compose_run_one_off(["./test_integration.sh"], env={…SLOT/SLOTS/SELECTOR…})`.
     - `finally`: **if the slot passed → tear its stack down; if it failed → leave
       it UP for debugging** (reaped by the next preflight, § 5).
  3. **Overall rc** = the first non-zero across the unit-once run and all slots
     (unit failure short-circuits the fan-out).

Every slot stack is fully isolated: all physical names carry `_s{k}` (Mod 152)
and the web bridge is per-slot (Mod 153), so N stacks coexist on one host with no
collision. `DockerClient` is stateless per call (each method shells one argv), so
the thread pool is safe; the implementation will confirm this.

The shared aggregate (`aggregate(ctx, env="test")` → `.docex/agg/test.env`) is
built **once** before the pool and read by every slot — per Mod 152's
`configurable.md` amendment, configurable values are per-env, not per-slot.

---

## 3. The exact `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS` injection

Injected into the **integration** shim's one-off container **only**, on the same
one-way, stable footing as `DOCEX_TEST_SELECTOR` (Mod 151), composing cleanly with
it:

```
env = {"DOCEX_TEST_SLOT": str(k), "DOCEX_TEST_SLOTS": str(N)}
if selector: env["DOCEX_TEST_SELECTOR"] = selector
```

- **`DOCEX_TEST_SLOT`** — this shard's index, **1-based** (`1..N`).
- **`DOCEX_TEST_SLOTS`** — the total shard count `N`.
- Injected **only on the sharded path** (`slots≥2`). The default `docex test`
  (and `--slots 1`) injects neither — byte/behavior-identical to today, and a
  shim seeing no `SLOTS` runs the whole tier.
- The **unit** shim never receives either (unit runs once, unsharded).

**Reference shim sharding (fixtures, kept a correct exemplar & the suite green).**
`test_projects/{fixed,elastic}/core/api/test_integration.sh` gains an **additive**
block: when `DOCEX_TEST_SLOTS > 1`, deterministically slice the collected
integration node-ids by `index % SLOTS == (SLOT-1)` and run only that shard; when
`SLOTS` is unset/1, run the whole tier exactly as today. Union of the N shards =
the whole tier, so the suite stays green whether run at 1 slot or N. This is a
**reference** — the doctrine **recommends but does not mandate** it (a project may
shard however it likes; docex fixes only the injected vars + their meaning).

---

## 4. The two (→ three) inherited seams become slot-aware

- **`exec_service_key(ctx, env, codebase, *, slot=1)`** — thread `slot` into
  `codebase_global_name(..., slot=slot)` **and** verify against the slot's compose
  file (not always the slot-1 one). This is the **real** consumer: the sharded
  loop's migrate + integration steps target the right per-slot exec container.
- **`env_compose_project(ctx, env, *, slot=1)`** — **NEW slot param** →
  `<label>-{env}-s{k}` for k≥2, `<label>-{env}` for k=1. **A necessary third seam
  beyond the two the task named:** the compose `--project-name` groups a stack, and
  two slots must carry **distinct** project names or `compose up`/`down` for one
  would adopt or tear down the other's resources. Flagged explicitly.
- **`_migration_task_family(ctx, *, project, env, svc, slot=1)`** — thread `slot`
  into `codebase_global_name(..., slot=slot)` for **forward-consistency** (this is
  the elastic `docex migrate` ECS task-family name). The fixed `test` loop migrates
  via the inline exec path, **not** `migrate.py`, so this seam has no consumer this
  mod; threading it (default `slot=1`, all current behavior preserved) completes
  the primitive per Mod 152's flagged seam, so a future slot-aware `docex migrate`
  cannot drift.
- **New helper `slot_compose_file(ctx, env, slot)`** (in `_common.py`) resolving
  the slot's compose-file path (`infra/output/test` for k=1, `.docex/slots/test/k/`
  for k≥2), used by both the sharded loop and the reaper.

---

## 5. The fleet (deterministic-slot) reaper

Generalizes Mod 148's single-run/single-slot reaper to N deterministic slots —
the multi-slot generalization the pre_plan explicitly deferred from Mod 148 to
here. Two mechanisms, together covering the crash/leave-up matrix:

1. **Orphaned-vessel reap (foreground preflight, `jobs/reaper.py`).** When the
   `<label>-test-runner` vessel is hard-killed, its `finally` never runs and **all
   N slot stacks leak**. `_teardown_test_stack` generalizes: read
   `meta.params.get("slots", 1)` and tear down each slot `k in 1..N` by its
   deterministic project name (`<label>-test-s{k}`) + `slot_compose_file(...,k)` +
   the shared agg env-file. (The crashed vessel got far enough to compile any slot
   it brought up, so each `.docex/slots/test/k/docker-compose.yml` exists on the
   shared mount.)
2. **Per-slot pre-up reap (inside the sharded loop).** Each slot worker
   `compose down`s its own project before bringing it up — clearing a
   **failed-left-up** stack from a prior *completed* run (the debug window is
   "until the next run", exactly as the task specifies), or any leftover
   same-numbered slot.

Because `job ls` and both reap paths classify via `record.classify`, they can
never disagree. Different slots never collide (distinct `_s{k}` names) — the F7
payoff. The `slots=N` count is recorded in `meta.params` by the foreground at
launch (beside `tiers`/`selector`), which is what the orphan reaper reads.

> **Residual edge (design note, not a blocker).** A leftover *higher-numbered*
> slot from a **cleanly-completed larger-N** prior run (e.g. run A `--slots 5`
> left `s5` up; run B `--slots 2`) is not swept by run B's per-slot pre-up (B only
> touches `s1`/`s2`). Options: **(a)** accept it — test slots are fungible and the
> operator normally uses a consistent N; the leftover is harmless and reaped the
> next time an N≥5 run touches `s5`; **(b)** record a project-wide "max slots ever"
> and sweep up to it at preflight; **(c)** add a `DockerClient` "list `test`
> compose projects by label" enumeration and sweep all. **I recommend (a)** for
> this mod (simplest, and consistent with the whole design's deterministic-name /
> no-dynamic-allocator philosophy, D5), noting (b)/(c) as a cheap future refinement.

---

## 6. The CLI: `docex test --slots N`

Add `--slots N` (int, default 1) to `_cmd_test`. Exposed **only for `test`**
(SC3 — the compiler primitive is env-agnostic, the CLI is test-scoped):

- `docex test --slots N` → unit once + integration sharded N ways.
- `docex test integration --slots N` → integration sharded N (no unit).
- `docex test unit --slots N` → **error** (unit is no-stack; sharding is
  meaningless), same shape as the existing `test unit --detach` rejection.
- `--slots 1` / omitted → today's exact path.
- `--slots N` with `N < 1` → usage error.

`--slots` threads: `_cmd_test` → `run_test_job(..., slots=N)` (records `slots=N`
in `meta.params`) → `_run_test_body` reads `params["slots"]` → `run_test(...,
slots=N)`.

---

## 7. SC2 — the byte-identical default gate stays green

The sharded path is gated `slots≥2`; `--slots 1`/omitted dispatches the
**untouched** existing `run_test`, adds **no** compile call and **no** env
injection on the default path. So:
- Compiled output: unchanged — the Mod 152 golden gate
  (`tests/unit/test_slot_golden.py`) and `git diff infra/output` stay clean.
- Runtime: `docex test` behaves exactly as today.

Confirmed in the `COMPLETE` report after implementation.

---

## 8. Automated coverage (proving as much as possible WITHOUT a real N-slot run)

Per the manual-test waiver + the close-out step-13 note (the live `--slots 2`
sharded+reaped exercise happens at advance close-out; automated coverage must
prove the rest cheaply):

- **Unit — seam identities:** `env_compose_project(slot=k)`,
  `exec_service_key(slot=k)`, `_migration_task_family(slot=k)` produce the `_s{k}`
  forms matching the compiler's slotted `codebase_global_name`; slot=1 is
  identical to the no-slot call.
- **Unit — sharded orchestration with a fake docker** (records calls): unit runs
  **once**; each of N integration slots gets `DOCEX_TEST_SLOT=k` /
  `DOCEX_TEST_SLOTS=N` (+ selector composes); each slot uses its slot compose file
  and `<label>-test-s{k}` project; a **failed** slot is left up while **passed**
  slots are torn down; overall rc is the first failure.
- **Unit — fleet reaper:** a `meta.params={"slots":N}` record → `_teardown_test_stack`
  tears down N slot stacks by deterministic name; `classify` reconciles multiple
  slot records.
- **Unit — byte-identical default:** `slots=1` dispatches the existing path with
  no `SLOT`/`SLOTS` injection; golden gate green.
- **Integration (cheap, real docker) — only if kept trivial:** a `docex test
  --slots 2` against the existing fixture (whose integration tier is tiny — 2
  files) mirroring the trivial-body pattern: assert both slot stacks come up with
  `_s2` isolation, the injection reaches the shim, both torn down. **No** 26-min
  suite. If it can't be kept cheap, fall back to the fake-docker unit path plus
  Mod 153's existing single-slot real gate.

---

## 9. SIZE — recommended scope split (needs sarge's ratification)

The task flagged this as the largest F7 mod and invited a split. Full scope = CLI
+ orchestration loop + shard injection + fixture shims + fleet reaper + three
seams + doctrine **+ check/merge slot-adoption (SC4)**. I **recommend peeling
check/merge slot-adoption (the SC4 `--project-name` collision closure) into a
follow-on Mod 155**, delivering in **154**: everything else (a fully working
`docex test --slots N`, sharded + reaped + injected, with green fixtures and the
`tests.md`/`docex.md` amendments).

**Why peel SC4, not something else:**
- **Distinct territory** — it edits `pipeline/check.py` + `pipeline/merge.py`, not
  `orchestrate/` + `jobs/`; keeping 154 to the orchestrator/vessel territory keeps
  the diff coherent and under the context ceiling the advance plan itself flagged.
- **Distinct reasoning** — SC4 needs the check/merge/test slot-disjointness matrix
  worked out (below), which is its own design surface.
- **154 is independently coherent and testable** — it closes SC1/SC2/SC3 of Goal 4
  in full; only SC4 moves to 155. (Peeling the fixture shims instead would leave
  154 unable to demonstrate the very injection it adds, so the shims stay.)

**Consequence:** Goal 4's *code* work would then span **154 + 155**; the advance's
"final code mod" becomes 155. The task explicitly authorized "add a mod rather
than compact mid-implementation."

### The SC4 design I would carry into Mod 155 (or into 154 if you keep it here)

**Reserved-slot band — no dynamic allocator.** `docex test --slots N` uses slots
`1..N` under a documented ceiling `MAX_TEST_SLOTS`. check's defensive test adopts a
reserved constant `CHECK_SLOT` and merge's defensive test a reserved `MERGE_SLOT`,
both **above** the ceiling, so they are deterministically disjoint from any test
run **and** from each other. This exactly fits the real concurrency matrix, which
the post-Mod-149 vessel locks make small:

- ≤1 `docex test` job at a time (test vessel lock) — using `1..N`.
- ≤1 `check` at a time (check vessel lock) — using `CHECK_SLOT`.
- ≤1 `merge` at a time (merge vessel lock) — using `MERGE_SLOT`.
- A `check` + a `merge` + a `test` **can** co-occur (three distinct locks) — three
  disjoint reserved bands cover precisely that.

`run_test` already grows a `slot=` parameter for the sharded path, so check/merge
simply pass their reserved slot (compiling the worktree at that slot and using the
slotted compose file/project/exec-key). No allocator, consistent with D5's
deterministic-name-is-the-lock philosophy. **This is my recommendation whether SC4
lands in 154 or 155;** the only decision is *which mod*.

> **Design question (SC4).** Ratify **(i)** the split — SC4/check-slot into a
> follow-on Mod 155, 154 ships the rest — or tell me to keep SC4 in 154; and
> **(ii)** the reserved-slot-band scheme above (`CHECK_SLOT`/`MERGE_SLOT` above a
> `MAX_TEST_SLOTS` ceiling), or steer me to an alternative (a dynamic next-free
> allocator, or a distinct non-numeric check/merge segment).

---

## 10. Doctrine-text amendments (land in this mod; drafted here for sign-off)

Upstream doctrine **spec** (not docex's own core planning docs). Radius named by
the task: `tests.md`, `docex.md`.

### A. `tests.md` § Injected environment — extend the codebase-shim table

The section already **anticipates** this ("adding to it (as parallel test sharding
later will, with its own `DOCEX_TEST_*` variables) is a doctrine change"). Add two
rows and adjust the anticipatory sentence to present tense:

> | `DOCEX_TEST_SLOT` | the current shard index under `docex test --slots N` | The **1-based** index (`1..N`) of this shard. Injected into the **integration** shim only, and only when sharding (`N ≥ 2`). **Unset ⇒ not sharding ⇒ run the whole tier.** |
> | `DOCEX_TEST_SLOTS` | the shard count `N` from `docex test --slots N` | The total number of shards. With `DOCEX_TEST_SLOT`, tells the shim to run only its `1/N` share of the integration tier. |

Plus a short paragraph: the pair composes cleanly with `DOCEX_TEST_SELECTOR`
(a shim may be both subset-narrowed and sharded); docex **recommends but does not
mandate** a sharding pattern — it fixes only the two variables and their meaning,
and a project shards however is idiomatic to its runner (the fixture shims ship a
reference modulo-split over collected node-ids). One-way and stable, like every
other injection.

### B. `docex.md` § `test` — add the `--slots N` surface

- Add the usage line `./bin/docex test --slots N`.
- A paragraph: `--slots N` brings up **N fully-isolated** `test` stacks (every
  physical name carries the slot segment; the web bridge is per-slot) and runs the
  **integration** tier **sharded** via the injected `DOCEX_TEST_SLOT` /
  `DOCEX_TEST_SLOTS`; the **unit tier runs once** (no-stack — sharding it is
  pointless). `--slots 1` / omitted is **byte-identical** to today. Slots are a
  general compiler primitive but the CLI exposes them **only for `test`**.

### C. `docex.md` § Command Lifecycle — the fleet note

- The vessel lock stays per-`(project, test)` — **slots are internal parallelism,
  not additional lock scopes**; two `docex test` invocations (any N) still refuse
  each other.
- The preflight reaper generalizes to the **fleet / deterministic-slot** reaper:
  a hard-killed run's **N** leaked slot stacks are reclaimed on the next
  invocation's preflight (reading the recorded slot count); a **failed** slot is
  deliberately **left up** for debugging and reaped the next preflight.

*(If sarge keeps SC4 in 154, a small `docex.md`/`cicd.md` note on check/merge's
reserved slot lands too; if peeled, it lands in Mod 155.)*

### Docex core-planning-doc impact (documentation step, step 8 — not `implementation.md`)

Recorded for the doc step, per the mod process (implementation.md must **not**
edit core planning docs):
- **`masterplan.md`** — the `test` command-surface row gains `--slots N`; the
  *Durable jobs* § line that currently reads "The *fleet* / multi-slot reaper and
  the slot axis itself are deferred" must be updated to describe the delivered
  fleet reaper.
- **`compiler.md`** — the Mod-152 "two out-of-compiler re-derivers must become
  slot-aware in Mod 154" seam note is now **done** (exec_service_key /
  _migration_task_family + the new env_compose_project seam).
- **`test_projects.md`** — the seeds now ship the reference shard split in
  `test_integration.sh`.

---

## 11. Contracts

**None.** No surface changes; sharding and network isolation alter no core
service's contract.

---

## Open design questions (for the design gate)

1. **The scope split (§ 9-i)** — ratify peeling SC4/check-slot into Mod 155 (154
   ships CLI + orchestration + injection + fixtures + fleet reaper + seams +
   doctrine), or direct me to keep SC4 in 154.
2. **The SC4 slot scheme (§ 9-ii)** — the reserved-slot band
   (`CHECK_SLOT`/`MERGE_SLOT` above `MAX_TEST_SLOTS`), or an alternative.
3. **Fleet-reaper residual edge (§ 5)** — accept option (a) (recommended), or
   require (b)/(c) now.
4. **Doctrine amendments (§ 10)** — sign off the `tests.md` + `docex.md` drafts
   (docex_process requires operator sign-off before doctrine edits).
5. **Cheap real-docker 2-slot test (§ 8)** — include it (recommended, if trivially
   fast), or rely on fake-docker unit coverage + Mod 153's single-slot gate.

# Mod 151 — Scoped Runs + Two Honest Modes (F5)

**Advance:** 009 Test Overhaul — Wave 2, Mod 6 (last of Wave 2). Realizes **F5**
under **SC1**. Reports to `sarge`. Completes **Advance Goal 2** (a blessed fast
inner loop for iterating on tests).

Builds directly on:
- **Mod 147** — the two-shim contract (`test_unit.sh` no-infra / `test_integration.sh`
  stack-backed incl. contract); `orchestrate/test.py` runs both, phased by tier.
- **Mod 148** — `docex test` is a durable job on a container vessel
  (`.docex/runs/`, deterministic-name lock, preflight reaper).
- **Mods 149/150** — check/merge on the same substrate; recheck-skip. *Untouched
  by this mod* (hard boundary).

## Goal

Bless a subset mechanism and two honest **execution modes**, using the doctrine's
own tier vocabulary (`unit` / `integration`) rather than raw framework paths as
the primary interface. Concretely deliver three surfaces:

1. **`docex test unit [subset]`** — runs ONLY the no-infra unit tier in a
   throwaway container with **no compose stack brought up** (verified: zero stack
   containers created). The fast lane.
2. **`docex test integration [subset]`** — runs the stack-backed integration
   tier; a `[subset]` narrows the run to the named tests, not the whole tier.
3. **`docex test`** (no arg) — unchanged: both tiers, fresh throwaway stack, the
   durable job Mod 148 made it. The formal isolation-guarantee mode.

Plus the **injected subset/coordination contract** (SC1 owns this dimension),
designed to compose cleanly with F7's future `DOCEX_TEST_SLOT` / `_SLOTS` (Wave
3) without inventing them here.

## What this mod deliberately does NOT do (hard boundaries)

- **No persistent warm-stack lifecycle.** No kept-hot `test` stack across
  invocations, no keep-up flag, no warm-stack reaping. (See Q(warm-stack) below —
  deferred, not silently dropped.)
- **No slot axis / `--slots N` / sharding.** Wave 3 (Mods 152–154). The two modes
  here are *execution modes* (no-stack vs stack-backed), not parallelism.
- **No change** to the recheck-skip, the check/merge jobs, or the tier
  *classification* (Mod 147 set the tiers; this mod adds how to invoke a subset
  of them).
- **No `DOCEX_TEST_SLOT` / `_SLOTS`.** F7. The injection contract is *designed to
  compose* with them; it does not introduce them.

## Design

### Resolved design questions

#### Q(warm-stack) — RESOLVED: defer the persistent warm-stack lifecycle

F5's prose names the two modes as "fast iteration (no-stack unit lane / **warm
stack**)" vs "formal fresh-throwaway isolation." I resolve this by **delivering
the real fast-loop win — the no-stack unit lane — and deferring the persistent
warm-stack lifecycle** (kept-hot stack, keep-up flag, warm reaping).

Rationale, and why this does **not** change the mod's size (so it is not escalated
as a scope change, only flagged for confirmation):

- The concrete Mod-6 deliverable mandates only: unit = no-stack, integration =
  stack-backed, subset works. All three are met without a warm-stack lifecycle.
- A persistent warm stack is a *lifecycle* feature (ownership, staleness, reaping
  policy) antithetical to the test env's "fungible, aggressively reaped" model
  (pre_plan SC2 § Slots as parallel-dev groundwork calls the warm/kept-hot lane a
  *disqualifying difference* — it is genuinely its own concern). Building it here
  would breach the context ceiling and entangle this mod with the slot lifecycle
  work Wave 3 owns.
- `docex test integration [subset]` therefore brings up a **fresh throwaway
  stack** (exactly as `docex test`'s integration phase does today), runs the
  subset, and tears down. No warm reuse. This is coherent and honest: the fast
  iteration win is the unit lane; integration subsetting is the *scope* win, both
  independent of warm reuse.

**Confirm at gate:** that deferring persistent warm-stack reuse to a future mod is
acceptable, and that "integration subset = fresh throwaway stack" satisfies F5's
integration-mode intent for this advance.

#### Q(fast-lane-is-a-job?) — RESOLVED: the unit lane is a plain synchronous run, NOT a durable job

`docex test unit [subset]` is a **plain synchronous throwaway-container run** — no
vessel, no run record, no lock, `--detach` is N/A (rejected with a usage error).
Reasoning:

1. **It is seconds.** Durability (survive a killed monitor) is the job substrate's
   entire purpose and buys nothing for a seconds-long run.
2. **No shared infra ⇒ no lock.** The vessel-name-as-lock exists because runs
   contend over the shared `test` stack. The unit lane brings up **no stack**, so
   two concurrent `docex test unit` runs cannot contend. The lock machinery is
   pointless here.
3. **Cleanest proof of the no-stack property.** Never entering the job/vessel path
   (which is oriented around stack teardown + orphan reaping) makes "no compose up
   issued" trivially true and trivially testable.
4. **The fast lane must be fast and simple** to actually get used; fewer moving
   parts is the point.

`docex test integration [subset]` **stays a durable job** on the existing
substrate — it is stack-backed and can be minutes (the very reason the substrate
exists), and a killed monitor during a 10-minute integration subset run should
survive. It **shares `docex test`'s lock scope** (`<label>/test`, vessel
`<label>-test-runner`) because it contends over the same `test` stack: a
`docex test` and a `docex test integration` correctly refuse each other. `--detach`
is supported for it.

**Confirm at gate.**

### The three surfaces, mechanically

CLI (`__main__.py::_cmd_test`): `docex test [unit|integration] [subset] [--detach]`.

| Invocation | Path | Stack? | Lock/vessel? | `--detach` |
| --- | --- | --- | --- | --- |
| `docex test` | durable job (kind=test), body runs both tiers | fresh throwaway | yes (`<label>-test-runner`) | yes |
| `docex test integration [subset]` | durable job (kind=test), body runs integration only + selector | fresh throwaway | yes (same scope as above) | yes |
| `docex test unit [subset]` | **synchronous** `run_test_unit` | **none** | no | rejected (EX_USAGE 64) |

- **Unit lane (`orchestrate/test.py::run_test_unit`, new).** For each codebase,
  one `compose_run_one_off(..., ["./test_unit.sh"], build=True, no_deps=True,
  env={"DOCEX_TEST_SELECTOR": subset} if subset else None)`. It issues **no
  `compose_up`**, **no migrate** (unit tier is no-infra), and **no `compose_down`**
  — it uses the standard `test` compose project name so the exec image is shared
  with the full test env (keeps the lane fast: no distinct-project image rebuild),
  and the only artifact it can create is the one-off `--rm` exec container plus
  compose's default network (not a "stack container"). Fail-fast on the first
  non-zero, returning that code.
  - **Why `--no-deps` is load-bearing:** the emitted exec service `depends_on` its
    backing services (`emit/compose.py:599`), so a bare `compose run` would start
    postgres et al. `--no-deps` is precisely what makes the lane no-stack.
- **Integration lane.** `run_test` is parametrized with `tiers` and `selector`;
  `tiers=("integration",)` brings up the fresh stack, migrates, runs **only**
  `test_integration.sh` (with `DOCEX_TEST_SELECTOR` injected when a subset is
  given), and tears down — the existing try/finally teardown is retained.
- **Full `docex test`.** `run_test` with `tiers=("unit","integration")`,
  `selector=None` — byte-for-byte today's behavior (both shims, whole tier, no
  injection).

Job-body threading: `run_in_vessel` already reads `meta`; the three `_JOB_BODIES`
bodies change signature to `body(ctx, docker, params)` (check/merge ignore
`params`), and `_run_test_body` reads `params` → `run_test(tiers=..., selector=...)`.
`run_test_job` records `params={"tiers": [...], "selector": ...}`; a thin
integration entry sets `tiers=["integration"]`.

### The injected subset contract (SC1 — the exact wording)

**One env var, forwarded by the shim to its runner. No argv pass-through.**

- **`DOCEX_TEST_SELECTOR`** — an opaque, runner-native selector string docex
  injects into the exec container (via the exec service's `-e`, the same channel
  `compose_run_one_off(env=…)` already uses). **Unset/empty ⇒ run the whole tier**
  (today's behavior, unchanged). **Set ⇒ the shim narrows the run to the subset**
  by forwarding the value to its test runner.
- The **tier** is chosen by the subcommand (`unit` / `integration`) — that is the
  doctrine's own vocabulary and the *primary* selector. `DOCEX_TEST_SELECTOR` is
  the *secondary* within-tier refinement (a path and/or marker). This is why the
  primary interface is not raw pytest paths: you pick a tier first, then
  optionally refine.
- **Why an env var, not argv:** it matches the existing one-way stagetest
  injection model (`STAGING_URL` / `PROJECT_VERSION` in `tests.md § Injected
  environment`), keeps the shim's `./test_unit.sh` invocation argument-free, and
  sits in the **same `DOCEX_TEST_*` namespace** F7 will populate with
  `DOCEX_TEST_SLOT` / `_SLOTS` — so a future sharded *and* subset run injects both
  vars through one mechanism with zero contract redesign. Argv pass-through was
  considered and rejected: two mechanisms is more surface, and argv does not
  compose with the injection model the way a namespaced env var does.
- **Exemplar shim idiom** (docex's own fixtures, the reference implementation):

  ```sh
  #!/bin/sh
  set -eu
  if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
      # shellcheck disable=SC2086 — selector is intentionally word-split into args
      exec pytest -q $DOCEX_TEST_SELECTOR
  else
      exec pytest -q /service/tests/unit
  fi
  ```

  When set, the selector *replaces* the default tier-folder target, so the agent
  passes e.g. `tests/unit/domain/test_calendar.py::test_leap` or
  `tests/unit -m slow`. A Go/other-runner shim forwards it in whatever way is
  idiomatic — the contract fixes only the *variable and its meaning*, never the
  runner. This is the one-way, stable docex↔project boundary SC1 owns; adding to
  it (as F7 will) is a doctrine change.

- **Reflected in docex's own fixture shims** so they stay a correct exemplar and
  the suite stays green: `test_projects/{fixed,elastic}/core/api/{test_unit,test_integration}.sh`
  and `tests/fixtures/sample_project/core/api/{test_unit,test_integration}.sh`.

### Automated coverage (manual-test step is WAIVED — must be proven by the suite)

New unit tests in `tests/unit/` (extending `test_orchestrate_test.py` + a CLI
parse test), against the `FakeDockerClient` (extended to record `env` and accept
`no_deps`):

1. **No-stack property:** `run_test_unit` issues **zero `compose_up`**, zero
   migrate, and calls `compose_run_one_off(no_deps=True)` for each codebase's
   `./test_unit.sh`.
2. **Selector injection:** a subset passes `DOCEX_TEST_SELECTOR=<subset>` in the
   one-off env; absent ⇒ no such env key.
3. **Integration lane:** brings up the stack, migrates, runs **only**
   `test_integration.sh` (never `test_unit.sh`), injects the selector, tears down.
4. **Full run unchanged:** existing `test_orchestrate_test.py` assertions stay
   green (both shims, no injection).
5. **CLI parse:** `docex test unit foo` → synchronous unit path, selector `foo`;
   `docex test unit --detach` → EX_USAGE error; `docex test integration foo` →
   integration job with selector.

### Doctrine amendments (require C.O. sign-off — see docex_process step 1)

Named radius, kept additive:

1. **`doctrine/infrastructure/tests.md`** — under § Codebase Tests, add a short
   **"Two execution modes"** subsection: the no-stack `docex test unit` fast lane
   vs the fresh-throwaway `docex test` isolation mode; and a **codebase-test
   injected-variable** note documenting `DOCEX_TEST_SELECTOR` (opaque, one-way,
   stable; unset ⇒ whole tier), mirroring the existing § Injected environment
   framing for stagetest. This completes the "two modes + injected contract"
   wording Mod 147 deliberately left partial.
2. **`skills/testing/SKILL.md`** — one Thread bullet: the two execution modes and
   the `DOCEX_TEST_SELECTOR` subset contract, routing to the new `tests.md`
   sections (router style, no duplicated prose). Description line lightly extended
   to name the fast lane so the skill triggers on "run one failing test" intent.
3. **`doctrine/infrastructure/docex.md`** — `### test` gains the
   `unit` / `integration [subset]` sub-surface (the two modes, the no-stack
   property, `--detach` N/A for unit); the Provided-Tools `test` row and Usage
   examples updated. Command Lifecycle note: the unit lane is deliberately **not**
   a durable job (synchronous, no lock).

`cicd.md § Build-Test-Step` is **not** in the named radius and is left unchanged
(the full-suite build-test contract is unaffected; the fast lane is a dev-iteration
surface, not a pipeline step).

### docex core-planning-doc diff (Documentation step 8 / for sarge's project map)

Not in `implementation.md` (mod-process rule 4.i). To reconcile at close-out:
- `masterplan.md` — Subcommand Surface `test` row (add the two modes + the
  no-stack unit lane), the `### Durable jobs` section (note the unit lane is
  synchronous, not a vessel job), and the `Filesystem Surface` is unaffected.
- No `test_projects.md` / `compiler.md` / `release_flow.md` change.
- No core-service **contract** change (docex declares no doctrine surfaces; the
  test-project contracts are unaffected).

## Open design questions

None blocking. Two resolutions above (Q(warm-stack), Q(fast-lane-is-a-job)) are
within a corporal's authority and are surfaced for **confirmation**, not
decision. The one genuine C.O.-authority item is **sign-off on the doctrine
amendments** (docex_process step 1 requires approval before doctrine edits).

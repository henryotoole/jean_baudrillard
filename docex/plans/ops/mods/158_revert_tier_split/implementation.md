# Mod 158 — Implementation Steps

Reverses the two-shim tier split back to one flat `test.sh` / `docex test`, while
**keeping** the subset selector, the slot axis, and the durable-job substrate.
Written for a fresh-context executor.

## Orientation & method

Load the **`docex-edit`** skill (this is docex-source work) and the **`testing`**
skill (the contract being reverted).

**The four source commits are your revert-to reference.** Read each with
`git show <sha> -- <path>`; the `-` side of a hunk is the pre-split prose to
restore. Where a *kept* mod later re-touched the same passage, reconcile by hand
(the interleaved files in §A2/§A3 give exact target text so you never blind-revert).

| Mod | commit | role |
| --- | --- | --- |
| 147 tier split | `7ddeda9` | primary revert-to source (prose + gate + fixtures) |
| 151 two modes | `160d514` | tier subcommands / no-stack lane / `DOCEX_TEST_SELECTOR` |
| 154 slots | `37b4634` | slot loop assuming "unit once, integration shards" |
| 156 policy | `59486ae` | test-close wording in agents/skill/practices |

**Scope guards — do NOT touch:** the job substrate (`jobs/*` except the unit
carve-out named in §B3), recheck-skip, the slot primitive (`compile.py`,
`orchestrate/_common.py`, `jobs/reaper.py`), the test-web-network retier
(`emit/compose.py` slot/network logic), reserved check/merge slots. **Do NOT edit
`VERSION` or `.claude-plugin/plugin.json`** (release-cut concern). **Do NOT edit
docex's own core planning docs** (`docex/plans/core/*`) — those are reconciled in
the driver's doc step at close-out.

Target end state, in one line: **one `test.sh` per codebase; `docex test`
[`subset`] [`--detach`] [`--slots N`], always a durable job, always stack-backed;
slots shard the whole suite; no tier concept anywhere.**

---

## A. Doctrine prose

### A1. Straight reverts (restore the mod-147 `-` side)

For each, apply the reverse of the mod-147 hunk (`git show 7ddeda9 -- <file>`):

1. **`doctrine/hexagonal_architecture/hex_overview.md`** — delete the added
   "**The five conceptual tiers map onto two execution classes.**" block (two
   bullets naming `test_unit.sh` / `test_integration.sh`). The `§ Tests` intro
   returns to describing the five tiers as documentary only.
2. **`doctrine/infrastructure/cicd.md`** — (a) codebase-checks list item back to
   "All codebases contain `build.sh`, `test.sh`, `health.sh`, and `migrate.sh` if
   it is required."; (b) build-test-step paragraph back to the single-`test.sh`
   wording; (c) process step 3 back to "Run each codebase's `test.sh`." Also apply
   the mod-156 cicd hunk reverse (`git show 59486ae -- doctrine/infrastructure/cicd.md`).
3. **`doctrine/infrastructure/infrastructure.md`** — repo-structure tree: two
   shim lines back to one `test.sh`; the codebase-root bullet list: `test_unit.sh`
   + `test_integration.sh` bullets back to the single `test.sh` bullet; "`tests` -
   contains all the tests that the two test shims will run" → "…that `test.sh`
   will run." **Leave the slot-axis section (mod 152) untouched.**
4. **`doctrine/infrastructure/specifics/exec_service.md`** — every `build.sh`,
   `test.sh`, and `migrate.sh` enumeration back to including `test.sh` (not the
   two shims); the "Running the suite in `test`" block back to a single
   `run --rm --build … ./test.sh`.
5. **`doctrine/infrastructure/specifics/migrations.md`** — "before any codebase's
   test shims run" → "before any codebase's `test.sh` runs."
6. **`doctrine/practices/inception.md`** — PART III scaffold list and PART IV
   first-draft list back to `build.sh`, `test.sh`, `health.sh` (drop the "ships as
   two shims" sentence and the two-shim enumerations).
7. **`doctrine/practices/advance.md`** — the scaffold-frontend mod bullet back to
   `build.sh`/`test.sh`/`health.sh`; then apply the mod-156 advance hunk reverse
   (`git show 59486ae -- doctrine/practices/advance.md`) — the test-close policy
   returns to a tier-free "close on the full run; scoped runs allowed while
   iterating."
8. **`doctrine/practices/modifications.md`** — apply the mod-156 hunk reverse: the
   test-step close line drops "full `unit` + relevant `integration`" for
   tier-free "closes on a full run (scoped runs allowed while iterating)."

### A2. `doctrine/infrastructure/healthchecks.md` — restore, don't search-replace

Restore the pre-147 shim-comparison paragraph verbatim (the `-` side of
`git show 7ddeda9 -- doctrine/infrastructure/healthchecks.md`):

- The shim list becomes "`build.sh`, `test.sh`, and `migrate.sh`".
- The asymmetry sentence becomes "this is the one asymmetry against the other
  **three** shims. `build.sh`, `test.sh`, and `migrate.sh` are properties of the
  *source tree*…".
- **Delete wholesale** the added final sentence beginning "The test tier splits
  the *other* way — into `test_unit.sh` and `test_integration.sh`…". No
  replacement.

### A3. `doctrine/infrastructure/tests.md` — remove tier framing, keep subset+slots

Target text for each region (current line numbers approximate):

1. **"Codebase Tests" opening paragraph** — restore the one-`test.sh` wording:
   "…its `tests/` tree, run by its `test.sh` inside its test-stage container… so
   one `test.sh` per codebase covers every core service that codebase declares."
2. **The execution-classes paragraph** (currently "The five conceptual tiers map
   onto **two execution classes**, one shim each…") → restore to the single line:
   "Unit, integration, and contract tests should all be run by the [standard test
   script](./cicd.md#build-test-step)."
3. **Delete the entire `### Two execution modes` section** (the three
   `docex test` / `docex test unit` / `docex test integration` bullets and the
   surrounding prose). Replace with nothing — the "folder structure … described
   here" pointer that followed it stays.
4. **Contract-tests paragraphs** — "run by the two shims, in one container" →
   "one `test.sh`, and one container"; both "Invoked by the codebase's
   `test_integration.sh` (contract tests need a container)." bullets → "Invoked by
   the codebase's `test.sh`."
5. **`### Injected environment` — the codebase-shim table.** KEEP the table, with
   these rows (drop all tier language):
   - `DOCEX_TEST_SELECTOR` — source "the `[subset]` argument to `docex test`";
     purpose unchanged (opaque runner-native selector; **unset ⇒ whole suite**).
   - `DOCEX_TEST_SLOT` — "**1-based** index of this shard… Injected only when
     sharding (`N ≥ 2`). **Unset ⇒ not sharding ⇒ run the whole suite.**"
   - `DOCEX_TEST_SLOTS` — "the total shard count `N`… its `1/N` share of **the
     suite**."
   Reword the surrounding prose: the shim forwards `DOCEX_TEST_SELECTOR` to its
   runner; sharding splits **the whole suite** (not "the integration tier"); drop
   the "Sharding the no-infra unit tier is pointless / unit runs once" sentence
   entirely. Keep the "one-way and stable" closing note.

### A4. `doctrine/infrastructure/docex.md`

1. **`### test` command entry** (currently ~L175–211) — replace the whole entry
   with the flat form:
   - Synopsis lines: `./bin/docex test`, `./bin/docex test [subset]`,
     `./bin/docex test --detach`, `./bin/docex test --slots N`.
   - Body: brings up a fresh `test` stack, migrates, runs each codebase's
     `test.sh` in its test-stage container, tears down; exits 0 iff all pass. A
     **durable job** (the `--detach` / re-attach / lock / reaper paragraph is
     retained, minus any unit exception). `[subset]` → `DOCEX_TEST_SELECTOR`
     (unset ⇒ whole suite). `--slots N` shards the **whole suite** across N
     isolated stacks; `--slots 1` byte-identical to plain `docex test`; N capped
     at `MAX_TEST_SLOTS`. Keep the "slot is a general compiler primitive; CLI
     exposes it only for `test`" sentence.
   - **Delete** the "`test` has two **execution modes** beyond the full run…"
     paragraph and the "`docex test unit` … synchronous run … `--detach` does not
     apply" text.
2. **Command-Lifecycle section (~L47)** — delete the final sentence of the
   durable-job paragraph carving out `docex test unit` as "a plain synchronous run
   — no vessel, no lock, no run record — not a durable job." Reword any "under
   `--slots N` … the unit tier runs once" phrasing to "shards the whole suite."
   The `test`/`check`/`merge` are-durable-jobs framing stays.
3. **`### test` one-liner in the Provided-Tools table (~L64)** — back to: "Run
   build-time tests (unit, integration, contract) in a fresh `test` environment. A
   [durable job](#command-lifecycle); `--detach` returns a handle. `test [subset]`
   narrows the run; `--slots N` shards it."

---

## B. docex source

### B1. `pipeline/check.py` — the shim gate

- Change the required-set tuple (L705) from
  `("build.sh", "test_unit.sh", "test_integration.sh", "health.sh")` to
  `("build.sh", "test.sh", "health.sh")`.
- Update `_gate_codebase_scripts` docstring (L687–693) and the success message
  (L725) to name `build.sh`/`test.sh`/`health.sh`.

### B2. `__main__.py` — the `test` CLI handler

Rewrite `_cmd_test` to the flat grammar:
- **Remove** the `tier` positional argument entirely.
- Keep `subset` (nargs="?"), `--detach`, `--slots N` and the `--slots` range /
  `MAX_TEST_SLOTS` checks.
- Update help text: `subset` help drops "within-tier"; `--detach` drops "not
  valid for the synchronous 'unit' lane"; `--slots` drops "integration tier / unit
  runs once / not valid for the 'unit' lane" → "shard the whole suite across N
  isolated test stacks; N=1 (default) byte-identical to plain `docex test`."
- **Delete** the entire `if ns.tier == "unit":` block (and its `run_test_unit`
  import) and the `if ns.tier == "integration":` branch. The body collapses to:
  ```python
  from docex.jobs.commands import run_test_job
  return run_test_job(ctx, docker, detach=ns.detach,
                      selector=ns.subset, slots=ns.slots)
  ```
- Update the top-of-file `test` command description string (L37–39) to the flat
  wording (no "'test unit [sel]' = no-stack fast lane").

### B3. `jobs/commands.py` — drop the tier plumbing

- `run_test_job` currently accepts `tiers=` (and a `selector`). Remove the
  `tiers` parameter and any tier-conditional; the job always runs the whole suite
  (`test.sh`) per codebase. Keep `detach`, `selector`, `slots`.
- Remove any special handling that existed for the synchronous unit lane.

### B4. `orchestrate/test.py` — the hard file

Reconcile 147 (phased two-shim loop) + 151 (two modes, `run_test_unit`) + 154
(slot loop). Target:
- **Delete `run_test_unit`** (and any no-stack/stackless helper it alone used).
- The suite runner invokes `["./test.sh"]` once per codebase (drop the
  unit-phase-then-integration-phase loop).
- **Slot loop shards the whole suite:** each of the N stacks runs `test.sh` with
  `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS` injected. Remove the branch that ran the
  unit tier once outside the slot loop. Keep per-slot compile+up+migrate+run,
  `finally` teardown, keep-failed-slot-up-for-debug, and the reaper hand-offs.
- Keep bring-up / migrate / teardown / `preserve_volumes=False` / `build=True`.

### B5. `docker/client.py` & `docker/subprocess_client.py`

151 added a stackless container-run capability for the no-stack lane. **Inspect
call sites** (`grep -rn` the new method across `docex/src`): if the no-stack lane
was its only consumer, remove it from both the protocol (`client.py`) and the impl
(`subprocess_client.py`); if a kept path uses it, leave it. Record the decision in
the mod's review notes.

### B6. `emit/compose.py`

147 touched one line here (the exec-service shim reference or a test-shim mention).
Apply only the mod-147 reverse for that line; **do not** touch the slot/network
logic mods 152/153 added.

---

## C. docex's own test suite

Update these to assert the flat contract and stay green (use `git show <sha> --
<testfile>` to see what each split mod added; reverse the tier assertions, keep
slot/job assertions):

- `docex/tests/unit/test_pipeline_check.py` — gate now requires `test.sh`; a
  codebase missing `test.sh` fails; drop two-shim assertions.
- `docex/tests/unit/test_orchestrate_test.py` — flat single-`test.sh` invocation;
  whole-suite sharding; remove `run_test_unit` / phased-loop tests.
- `docex/tests/unit/test_dispatcher.py` — `test` grammar has no `tier`; `test
  <subset>` / `--slots` / `--detach` parse; remove `test unit`/`test integration`
  dispatch tests.
- `docex/tests/unit/test_slot_orchestration.py` — sharding covers the whole
  suite, not just integration.
- `docex/tests/unit/test_subprocess_docker_client.py` — drop the stackless-run
  tests if §B5 removed the helper.
- `docex/tests/unit/test_exec_service.py`, `test_jobs_check_merge.py`,
  `test_jobs_commands.py`, `docex/tests/conftest.py` — reconcile any two-shim /
  tier references to flat.
- `docex/tests/integration/test_slots_real.py` — whole-suite shard expectation.

---

## D. Fixtures & docex test projects — un-split to one `test.sh`

For **each** of the three codebases — `docex/test_projects/fixed/core/api`,
`docex/test_projects/elastic/core/api`, `docex/tests/fixtures/sample_project/core/api`:

1. **Merge shims → one `test.sh`.** Create `test.sh` (executable, `#!/bin/sh`)
   that runs the whole suite and honors `DOCEX_TEST_SELECTOR` +
   `DOCEX_TEST_SLOT`/`DOCEX_TEST_SLOTS` (the reference pattern: forward the
   selector as a pytest args fragment; when slots set, apply the modulo split over
   collected node-ids across the **whole** suite). Base it on the union of the
   current `test_unit.sh` + `test_integration.sh`. Then `git rm` both split shims.
2. **Restore the flat `tests/` layout.** Move `tests/unit/*` and
   `tests/integration/*` back to `tests/`; `git rm` the now-empty `unit/` and
   `integration/` dirs and their `__init__.py`. (For `sample_project`: restore
   `tests/test_smoke.py`; remove `tests/unit/test_unit_smoke.py` +
   `tests/integration/test_integration_smoke.py`.) Reference: reverse of the
   mod-147 file renames under each `tests/` tree.
3. **Dockerfiles** — the mod-147 hunk changed COPY/exec references to the two
   shims; reverse to `test.sh`.
4. **`sample_project` supporting refs:** `README.md`, the
   `infra/contracts/api.web.rest.openapi.yml` note, and
   `sample_project_multi_fixed/infra/infra.yml` comment — revert the two-shim
   mentions to `test.sh` (reverse of the mod-147 hunks).

---

## E. Skill, agents, eval

1. **`skills/testing/SKILL.md`** — substantial rewrite. Reverse the mod-147/151/156
   hunks (`git show <sha> -- skills/testing/SKILL.md`). Reframe from "two execution
   classes / two shims / two modes" to: one `test.sh`; flat `docex test`; optional
   `[subset]` (`DOCEX_TEST_SELECTOR`) and `--slots N` (whole-suite shard); durable
   jobs. Keep the durable-job and slot guidance. The description line must drop the
   "two execution shims (no-infra `test_unit.sh` vs stack-backed
   `test_integration.sh`)" framing.
2. **`skill_iter/eval/outcome/testing/evals.json`** — update expected-outcome
   assertions to the flat model (any prompt/expected pair asserting the two-shim or
   tier-mode answer now expects the flat `test.sh` / `docex test [subset]` /
   `--slots` answer).
3. **`agents/corporal/mod-developer.md`** & **`agents/sergeant/doctrine-advance.md`**
   — reverse the mod-156 hunks: the test-close instruction drops "full `unit` +
   relevant `integration`" for "close on the full run (scoped runs allowed while
   iterating)."

---

## F. Release artifacts

1. **Rename** `upgrades/upgrade_3.0.0.md` → `upgrades/upgrade_2.2.0.md`
   (`git mv`). Frontmatter: `version: "2.2.0"`, `severity: minor` (was `major`),
   `kind: incremental` (unchanged), `scope` unchanged.
2. **Gut the migration.** Remove the "Split `test.sh` → `test_unit.sh` +
   `test_integration.sh`" section and the "one breaking, load-bearing migration"
   framing. The Summary becomes: advance 009 ships durable re-attachable jobs,
   scoped test runs (`docex test [subset]`), slot sharding (`docex test
   --slots N`), and a faster `merge` — **all additive, no per-project migration**.
   Project upgrade reduces to: **repin `docex_version` → 2.2.0 + recompile**;
   re-run the suite. Keep the machine-sync section (the `testing` skill still
   changed).
3. **`CHANGELOG.md` (repo root)** — the `[Unreleased]` advance-009 entry: describe
   it as the **2.2.0 minor**; remove the two-shim/`test.sh`-split item from the
   breaking/changed narrative; the surviving items (jobs, subset, slots, merge
   QoL) are Added/Changed. (Leave final version stamping to the release cut, but
   the entry must no longer describe a breaking shim split.) Mirror in
   `docex/CHANGELOG.md` if it carries the same entry.

---

## G. Verification (executor runs before handing back)

From `docex/`:
1. `grep -rIn --exclude-dir=plans -e test_unit.sh -e test_integration.sh -e 'DOCEX_TEST_TIER' -e 'docex test unit' -e 'docex test integration' -e 'two execution' -e 'fast lane' src/ ../doctrine ../skills ../agents ../upgrades ../CHANGELOG.md`
   → **no hits** (plans/ excluded — mod docs legitimately narrate the split).
2. `python -m pytest docex/tests/unit -q` → green.
3. Stack-backed sanity (if the environment allows): `./bin/docex check` shim-gate
   passes a one-`test.sh` fixture and fails a fixture with `test.sh` removed.
4. Leave the full stack-backed `docex test` / `--slots 2` live-verification to the
   driver's close-out (needs Docker + real backing services).

Report back: the §B5 decision (helper kept/removed), any file where the revert-to
prose had to be reconstructed rather than lifted from a diff, and the pytest
result.
</content>

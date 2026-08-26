# Mod 158 — Revert the Two-Shim Tier Split (back to flat `test.sh` / `docex test`)

**Advance:** 009 Test Overhaul — post-close-out correction, landed on the
`advance_009_test_overhaul` branch **before** the release cut. Reverses the
operative decision of **SC1** (the two-shim contract) and the tier-mode surface of
**F5**, while preserving every other advance deliverable. Reports to the operator.

## Why

SC1 made the unit/integration split *operational* by shipping it as two
per-codebase shims (`test_unit.sh` / `test_integration.sh`) and two `docex test`
subcommands (`test unit` / `test integration`). On reflection this was a mistake,
for two reasons the operator raised and I concur with:

1. **The reward is thin.** The no-stack fast lane's only saving over a
   stack-backed subset run is the backing-service readiness wait + migrate +
   teardown — because the exec/test container boots either way and containers boot
   in parallel. On a light project that is seconds. The genuine inner loop for a
   pure-unit test is "run the test runner directly" (no docex, no stack at all),
   which is faster still and needs no doctrine surface.
2. **The cost is a load-bearing boundary contract.** Unlike the `[subset]` and
   `--slots` axes — which are *ignore-and-still-correct* (a project that never
   honors them still has a fully correct `docex test`) — the tier signal is
   **mandatory for correctness**: if a project's shim doesn't honor it, `docex
   test unit` runs DB-touching tests against no stack and fails. docex would ship
   a first-class command that is silently wrong for any project that treated an
   "optional-looking" convention as optional. There is no middle design: make the
   tier signal non-load-bearing (always boot the stack) and the fast lane provides
   no stack-skip, collapsing into a redundant alias of `[subset]`.

The doctrine's position becomes: **the unit inner loop is "run your test runner
directly"; `docex test` is the fresh-throwaway-stack formal run.** The tier
taxonomy stays exactly as rich as before — it is once again *documentary* (how you
reason about coverage), not *operational* (determining invocation/environment).

## Scope: a surgical reversal, not an advance revert

Everything the advance shipped **except** the tier split is kept. The reversal
touches four of the twelve advance mods:

| Mod | What it introduced | This mod |
| --- | --- | --- |
| **147** `unit_integration_tier_split` | `test.sh` → two shims; `check` asserts both; `test` runs both phased; fixtures moved to `tests/{unit,integration}/` | **Revert fully** |
| **151** `scoped_runs_two_modes` | `docex test unit`/`integration` subcommands; no-stack fast lane; unit-as-synchronous-non-job carve-out; `DOCEX_TEST_SELECTOR` | **Revert the tier parts; keep the subset selector** |
| **154** `slots_orchestration` | `--slots N` + `DOCEX_TEST_SLOT`/`_SLOTS`, built on "unit runs once, integration shards" | **Keep slots; re-derive to shard the whole suite** |
| **156** `test_selection_policy` | "close on full unit + relevant integration" wording in agents/skill/practices | **Reword to tier-free "full run"** |

**Kept untouched:** durable jobs (148/149), recheck-skip (150), the slot
primitive (152), the test-web-network retier (153), the reserved check/merge
slots (155).

## What the reversed contract looks like

- **One shim per codebase: `test.sh`.** Exit-code-only, exactly as before the
  advance. Joins `build.sh` / `health.sh` / `migrate.sh` as a codebase-scoped
  source-tree property. `docex check` asserts `test.sh` (not two files).
- **One flat command: `docex test`.** Brings up a fresh `test` stack, migrates,
  runs each codebase's `test.sh`, tears down. A durable job (jobs are kept), so
  `--detach` / re-attach / the lock / the reaper all still apply — with **no**
  synchronous-unit carve-out: *every* `docex test` run is a durable job again.
- **`docex test [subset]`** — the first positional is the optional within-suite
  selector, forwarded to `test.sh` as `DOCEX_TEST_SELECTOR` (unset ⇒ whole
  suite). Kept. Optional, ignore-and-still-correct.
- **`docex test --slots N`** — shards the **whole suite** across N isolated
  stacks via `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS`; `--slots 1` byte-identical to
  plain `docex test`. Kept. Optional, ignore-and-still-correct.

All new complexity now lives behind optional injected `DOCEX_TEST_*` variables
that default to "run everything." Nothing mandatory was added to the boundary.

## Design

### 1. The shim contract (doctrine + `check`)

Restore `test.sh` as the single test shim everywhere the doctrine names it, and
change `docex check`'s per-codebase required set from
`("build.sh", "test_unit.sh", "test_integration.sh", "health.sh")` back to
`("build.sh", "test.sh", "health.sh")` (conditional `migrate.sh` unchanged).
The revert-to prose is the `-` side of mod 147's diff; where a later mod re-touched
the same passage (see §3), reconcile by hand rather than blind-restore.

### 2. `docex test` orchestration (`orchestrate/test.py`) — the hard file

147 (phased two-shim loop) + 151 (two modes, no-stack lane) + 154 (slot loop) all
layered here. Target end state:

- One suite invocation per codebase: `["./test.sh"]` (drop the unit-then-
  integration phasing).
- Remove the no-stack fast-lane branch and the `tier` parameter entirely; there
  is no stackless path — `docex test` always brings up the stack.
- **Slots shard the whole suite.** The 154 loop that ran the unit tier once and
  sharded only integration collapses: each of the N stacks runs `test.sh` with
  `DOCEX_TEST_SLOT`/`_SLOTS` injected; the reference shim's modulo split over
  collected node-ids partitions the entire suite, so the union of shards is the
  whole suite exactly once. Unit tests ride along in whichever slot they land in —
  no extra stacks, no separate once-run.
- Keep bring-up / migrate / `finally` teardown / `preserve_volumes=False` /
  `build=True` freshness / keep-failed-slot-up-for-debug, all unchanged.

### 3. Interleaved prose (`tests.md`, `docex.md`)

Remove tier framing, keep subset+slots+jobs framing:

- **tests.md** — restore the "Codebase Tests" and contract paragraphs to their
  one-`test.sh` wording (147 `-` side). Delete the "Two execution modes" section
  (151). In the "Injected environment" table **keep** the `DOCEX_TEST_SELECTOR`,
  `DOCEX_TEST_SLOT`, `DOCEX_TEST_SLOTS` rows; drop tier language around them and
  reword the sharding note from "shards the integration tier / unit runs once" to
  "shards the whole suite."
- **docex.md** — rewrite the `test` command entry to the flat form (subset +
  slots + durable job). Delete the "two execution modes" paragraph. In the
  Command-Lifecycle section remove the sentence carving out `docex test unit` as
  the synchronous no-vessel exception (now *all* `docex test` runs are durable
  jobs); adjust the slots-and-locks prose that says "unit runs once."

### 4. `healthchecks.md` — restore, don't just search-replace

147 rewrote the shim-comparison paragraph and *added* a justification ("The test
tier splits the *other* way — into `test_unit.sh` and `test_integration.sh` —
because its two tiers differ by invocation environment…"). Restore the original
"`build.sh`, `test.sh`, and `migrate.sh` … the one asymmetry against the other
three shims" wording and delete the added split-justification wholesale.

### 5. The subtle, filename-free references

The git-diff already surfaced two the marker-grep missed — reconcile both:
- **migrations.md** — "before any codebase's test shims run" → "before any
  codebase's `test.sh` runs."
- **healthchecks.md** — see §4.
The implementation step re-runs the mod-147/151/154/156 diffs file-by-file to
guarantee no reworded reference is left behind.

### 6. CLI grammar (`__main__.py`)

Drop the `tier` positional (`choices=["unit","integration"]`); keep `subset` as
the sole optional positional, plus `--detach` and `--slots N`. Update the command
help text (it currently reads "'test unit [sel]' = no-stack fast lane; …"). Remove
the "not valid for the synchronous 'unit' lane" guards on `--detach`/`--slots`.

### 7. `jobs/commands.py`, `docker/{client,subprocess_client}.py`

151 added the synchronous no-stack path (unit-as-non-job) and a stackless
container-run capability. Remove the unit-synchronous branch so all `docex test`
runs route through the durable-job vessel. The stackless docker-run helper: remove
if it has no other consumer; leave if a kept path (jobs/reaper) uses it — decided
at implementation time by call-site inspection.

### 8. Fixtures & docex test projects

Un-split back to one `test.sh` per codebase and restore the flat `tests/` layout:
- `docex/test_projects/{fixed,elastic}/core/api/`: merge `test_unit.sh` +
  `test_integration.sh` → `test.sh`; move `tests/{unit,integration}/*` back to
  `tests/`; drop the now-empty subdirs and their `__init__.py`; fix the Dockerfile
  shim references.
- `docex/tests/fixtures/sample_project/core/api/`: same merge; restore
  `tests/test_smoke.py`; fix Dockerfile, README, the `api.web.rest.openapi.yml`
  contract note, and the `sample_project_multi_fixed/infra/infra.yml` comment.

### 9. docex's own test suite

Update the docex unit/integration tests that assert the two-shim behavior:
`test_orchestrate_test.py`, `test_pipeline_check.py`, `test_dispatcher.py`,
`test_slot_orchestration.py`, `test_subprocess_docker_client.py`,
`test_exec_service.py`, `test_jobs_check_merge.py`, `test_jobs_commands.py`,
`conftest.py`, `test_slots_real.py`. They must assert the flat contract (`test.sh`,
whole-suite sharding, no tier subcommands) and stay green.

### 10. docex core planning docs

Reconcile `docex/plans/core/{masterplan,compiler,test_projects}.md` to the flat
model. (These are also swept by `project-cohere` at close-out; edit them in the
doc step, let the pass verify.)

### 11. Skill + agents + practices

- `skills/testing/SKILL.md` — substantial rewrite: it is currently organized
  around the two execution classes. Reframe to one `test.sh`, flat `docex test`,
  optional subset + slots. Keep the durable-job and slot content.
- `skills/testing`'s outcome eval `evals.json` — update expected outcomes to the
  flat model so the eval still measures the doctrine-correct answer.
- `agents/corporal/mod-developer.md`, `agents/sergeant/doctrine-advance.md`,
  `doctrine/practices/{modifications,advance}.md` — reword the test-close policy
  from "full `unit` + relevant `integration`" to a tier-free "close on the full
  run (scoped runs allowed while iterating)."
- `doctrine/practices/{advance,inception}.md` — restore `test.sh` in the scaffold
  / shim lists (147 `-` side).

### 12. Release artifacts → this becomes a MINOR, not a MAJOR

The two-shim split was the advance's *only* breaking, project-migration-requiring
change; removing it makes the whole advance backward-compatible (durable jobs,
slots, faster merge are all additive). Therefore:
- Rename `upgrades/upgrade_3.0.0.md` → `upgrades/upgrade_2.2.0.md`; frontmatter
  `severity: major` → `minor`; gut the "split every shim" migration so the guide
  reads **repin + recompile** (no per-codebase migration).
- The `[Unreleased]` CHANGELOG entry describes advance 009 as a 2.2.0 minor and
  drops the shim-split from the breaking-changes narrative.
- **No `VERSION` / `plugin.json` edit in this mod.** They still read `2.1.0`; the
  bump to `2.2.0` is applied at the release cut per `RELEASING.md`, not here. This
  mod only ensures the release *will* be 2.2.0.

## What this mod deliberately does NOT do

- **Does not remove subset or slots.** Both are kept as optional injected-var
  axes.
- **Does not touch the job substrate, recheck-skip, slot primitive, web-network
  retier, or reserved check/merge slots.**
- **Does not cut the release.** It leaves the branch releasable as 2.2.0; the cut
  is a separate operator-driven step.

## Verification (close-out)

1. `docex check`'s codebase-shim gate passes against a one-`test.sh` fixture and
   fails a codebase missing `test.sh`.
2. `docex test` runs the flat suite in a fresh stack (durable job; `--detach` +
   `job wait` re-attach still work).
3. `docex test <subset>` forwards `DOCEX_TEST_SELECTOR`; omitting it runs the
   whole suite.
4. `docex test --slots 2` shards the **whole** suite across two isolated stacks
   and reaps; `--slots 1` output byte-identical to plain `docex test`.
5. docex's own full suite green.
6. `cohere` (doctrine coherency: no dangling `test_unit.sh`/`test_integration.sh`
   references, no orphaned "two modes" links) + `project-cohere` (docex core docs)
   passes.

## Design questions

1. **`docker/subprocess_client.py` stackless-run helper** — keep or remove?
   Resolved at implementation time by call-site inspection (§7); flagged here
   only because it is the one "is it still used?" judgment in the diff.
2. **Sharding a suite with no tier boundary** — the reference shim now applies its
   modulo split over the *entire* collected node-id set rather than the
   integration subset. This is a behavior refinement to the reference sharding
   pattern (still "recommend, not mandate"); no contract change. Noted, not a
   blocker.
</content>
</invoke>

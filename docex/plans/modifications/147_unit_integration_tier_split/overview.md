# Mod 147 — Unit/Integration Tier Split (the two-shim contract)

**Advance:** 009 Test Overhaul — Wave 1, Mod 2. Realizes **SC1** (make the
unit/integration split *operational*, not just documentary). Reports to `sarge`.

## Goal

Split the single per-codebase `test.sh` contract into **two shims** —
`test_unit.sh` (the no-infra tier) and `test_integration.sh` (the stack-backed
tier) — and fold `contract` tests into the integration side. This is the
foundational vocabulary that the later fast-lane (F5, docex mod ~151) and slot
sharding (F7) build on; it is established once, here, early.

The **only execution distinction is needs-infra vs not**. Contract tests spin a
provider server / mock inside a container, so they are on the needs-infra
(integration) side. There is no third execution class.

## What this mod deliberately does NOT do (later mods)

- **No no-stack fast lane.** In this mod `docex test` still brings up the fresh
  `test` stack and runs **both** shims sequentially inside it. Unit tests run
  against the (already-up) stack, exactly as coarse as today. The no-stack `docex
  test unit` lane is F5 (later mod).
- **No subset scoping, no `unit`/`integration` argv on `docex test`, no "two
  modes".** (F5.)
- **No slot axis / `--slots N`.** (F7, Wave 3.)
- **No `job` substrate / `--detach`.** (F3, Wave 2.)

The intermediate state after this mod is deliberately coherent without any of the
above: the contract is two files; docex runs both, in one stack, totally.

## Design

### 1. The two-shim contract (definition)

Every codebase ships two executable shims at its codebase root, replacing the one
`test.sh`:

| Shim | Execution class | Tiers it runs (hex 5-tier taxonomy) |
| --- | --- | --- |
| `test_unit.sh` | no-infra (no stack needed) | domain, alogic, adapter-**unit** (driving-adapter translation with the port mocked) |
| `test_integration.sh` | stack-backed (real backing services) | adapter-**integration** (driven adapters vs real infra), module-integration, codebase-flow, **and contract** |

Each shim exits `0` iff its tier passes — the same exit-code-only contract the
other codebase shims (`build.sh`, `health.sh`, `migrate.sh`) already obey. Two
separate files, **not** one shim taking a tier argv — settled in `pre_plan.md`
(two files are clearer than four branches of a `case`; and unlike `health.sh`'s
per-core-service argv, the two tiers differ by *invocation environment*, which is
exactly what a later mod acts on).

### 2. `docex check` asserts BOTH shims exist (`pipeline/check.py`)

`_gate_codebase_scripts` currently asserts `build.sh`, `test.sh`, `health.sh` per
codebase (+ conditional `migrate.sh`). Change the per-codebase required set from
`("build.sh", "test.sh", "health.sh")` to
`("build.sh", "test_unit.sh", "test_integration.sh", "health.sh")`. `build.sh` /
`health.sh` gates and the conditional `migrate.sh` gate are unchanged. The
success-message string is updated to name the new set.

### 3. `docex test` invokes both shims (`orchestrate/test.py`)

Step 3 of `run_test` loops codebases running `["./test.sh"]`. Replace with a
**phased** run: for the unit shim across all codebases, then the integration shim
across all codebases — first non-zero exit short-circuits and returns (fail-fast,
as today). Everything else (bring-up, migrate, `finally` teardown,
`preserve_volumes=False`, `build=True` freshness rule) is unchanged.

- Phased-by-tier (all `test_unit.sh`, then all `test_integration.sh`) rather than
  per-codebase (unit→integration→unit→integration) because it (a) fails fast on
  the cheap tier before paying for any integration test, and (b) factors cleanly
  for F5, which will later run just the unit phase with no stack. This is a minor
  behavior refinement (which test "fails first" when several would fail); the
  contract — non-zero on any failure, teardown always — is unchanged. **Within
  corporal authority; noted, not escalated.**

### 4. Migrate docex's own test projects & fixtures

Three codebases ship `test.sh` today and must be migrated to the two-shim form so
docex's own suite and smoke path stay green:

1. `test_projects/fixed/core/api/` (smoke walk)
2. `test_projects/elastic/core/api/` (smoke walk)
3. `tests/fixtures/sample_project/core/api/` (docex's own check/orchestrate/real
   fixtures)

**Partition mechanism: `tests/unit/` + `tests/integration/` subfolders**, each
shim globbing its own folder (`exec pytest -q /service/tests/unit` /
`/service/tests/integration`). Chosen over pytest markers because these fixtures
carry no pytest config file, subfolders need none, and a two-folder layout is the
clearest copyable exemplar (it also matches docex's *own* repo layout, which
already uses `tests/unit/` + `tests/integration/`). Each codebase's `Dockerfile`
`dev` and `test` stages must `COPY`/`chmod` the two shims instead of `test.sh`.

Honest classification of the `test_projects` fixtures (verified by reading each —
stub-backed / no-DB / no-`root` ⇒ unit; live-postgres / TestClient-against-stack
⇒ integration), so the future no-stack unit lane won't inherit a stack-needing
test:

- **unit/**: `test_jobs_alogic.py`, `test_processor_smoke.py`,
  `test_clock_smoke.py`, `test_jobs_drain.py`
- **integration/**: `test_smoke.py`, `test_jobs_smoke.py`,
  `test_jobs_concurrency.py`

`sample_project` has one trivial smoke test; it must end with **both** subfolders
non-empty (see gotcha) — the existing smoke goes to `integration/`, plus a
trivial `unit/` test.

**Gotcha (load-bearing):** `pytest` exits **5** ("no tests collected") when a
folder is empty — a non-zero exit that would fail the shim. So (a) every migrated
codebase must have **both** subfolders non-empty, and (b) the *inception stub*
form of each shim stays `#!/bin/sh` + `exit 0` (a runnable trivially-passing
stub, per `inception.md`), never an empty pytest glob.

### 5. docex's own suite: tests to add / update

- **Gate (`tests/unit/test_pipeline_check.py`):** add
  `test_check_requires_test_unit_sh` + `_executable` and
  `test_check_requires_test_integration_sh` + `_executable` (mirroring the
  existing `health.sh` gate tests); update any test that removes/asserts a plain
  `test.sh`.
- **Orchestrator (`tests/unit/test_orchestrate_test.py`):** update assertions
  from `("./test.sh",)` to expect `("./test_unit.sh",)` then
  `("./test_integration.sh",)`, in phased order; update the "every codebase runs
  exactly one way" and first-failure short-circuit tests accordingly.
- **`tests/unit/test_subprocess_docker_client.py`:** update the `./test.sh`
  example invocation to the new shim name.
- **Real-docker integration tests** (`test_test_real.py`, `test_check_real.py`)
  need no code change but rely on the migrated `sample_project` fixture shipping
  both passing shims.
- docex's own `tests/unit/` vs `tests/integration/` layout and `-m integration`
  convention (its `pyproject.toml addopts`) are **out of scope** — docex is the
  executor, it has no `test.sh`; only the *fixtures* it compiles get the split.

`python -m pytest tests` must be fully green in review.

## Proposed doctrine-text amendments (SC1 blast radius) — for `sarge` sign-off

The doctrine is docex's upstream spec; SC1's amendments land in this mod. Exact
one-liners below. **Named blast radius** (per the task) I intend to make;
**flagged adjacents** are mechanically-implied references I recommend fixing now
for consistency but want you to rule on.

### Named blast radius (will amend)

- **`tests.md`**
  - L11: "…run by its `test.sh` inside its test-stage container… one `test.sh`
    per codebase…" → "…run by its **`test_unit.sh` and `test_integration.sh`**
    inside its test-stage container… two shims per codebase…"
  - L17 (the load-bearing line) "Unit, integration, and contract tests should all
    be run by the standard test script" → replace with: *"The five conceptual
    tiers map onto **two execution classes**, one shim each: `test_unit.sh` runs
    the no-infra tiers (domain, alogic, adapter-unit); `test_integration.sh` runs
    the stack-backed tiers (adapter-integration, module-integration, flow) **and
    contract tests**. The only distinction is needs-infra vs not; contract folds
    into integration."*
  - L44 "…two contract files but one test suite, one `test.sh`, and one
    container." → "…one test suite run by two shims, and one container."
  - L59, L66 "Invoked by the codebase's test.sh." → "Invoked by the codebase's
    `test_integration.sh` (contract tests need a container)."
- **`hex_overview.md` §Tests** — keep the 5 conceptual tiers; add, before
  "Entrypoints are not a test tier", a short paragraph: *the five tiers map onto
  two execution classes docex invokes as two shims — **unit** (`test_unit.sh`, no
  stack: domain / alogic / adapter-unit) and **integration**
  (`test_integration.sh`, stack-backed: adapter-integration / module-integration
  / codebase-flow / contract).*
- **`cicd.md`**
  - L57 (Check Step 3.1) "All codebases contain `build.sh`, `test.sh`,
    `health.sh`, and `migrate.sh` if required." → "…contain `build.sh`,
    **`test_unit.sh`, `test_integration.sh`**, `health.sh`, and `migrate.sh` if
    required."
  - L138 (Build Test Step) "each codebase will need a `test.sh` script…" →
    reword to "two shims, `test_unit.sh` and `test_integration.sh`," each a
    small shim exiting 0 on pass; name the unit=no-infra / integration=stack
    split.
  - L145 "Run each codebase's `test.sh`." → "Run each codebase's `test_unit.sh`,
    then each codebase's `test_integration.sh`."
- **`docex.md`**
  - L159 (`test` surface) "runs each codebase's `test.sh`… Covers unit,
    integration, and contract tests" → "runs each codebase's `test_unit.sh` then
    `test_integration.sh`… Covers the unit tier (no-infra) and the integration
    tier (stack-backed, including contract tests)."
  - `check` surface (L163) inherits via cicd.md; touch only if wording names
    `test.sh` (it does not).
- **`infrastructure.md`** (repo-structure listing)
  - Tree L143 `│   │   ├── test.sh` → two lines `test_unit.sh` /
    `test_integration.sh`.
  - L194 "`tests` — contains all the tests that `test.sh` will run." → "…that the
    two test shims will run."
  - L197 "`test.sh` — the test script." → two bullets: `test_unit.sh` (no-infra
    tier) / `test_integration.sh` (stack-backed tier, incl. contract).
  - The "Codebase Containers" prose ("expects to find the codebase's scripts like
    `migrate.sh`") needs no change (example is `migrate.sh`).
- **`testing` skill** (`skills/testing/SKILL.md`) — description + body L16/L23
  reference "the `test.sh` … shim" / "under the single `test.sh`". Update to the
  two-shim contract; state contract folds into integration. (Partial SC4: this
  mod documents the shim split; the fuller "two modes + injected shard contract"
  wording is completed by F5/F7 later mods.)

### Flagged adjacents (mechanically implied — recommend now; `sarge` to rule)

- **`exec_service.md`** L9/L21/L51 — lists `build.sh`, `test.sh`, `migrate.sh` as
  what runs inside the exec service; L51 shows `run --rm --build … ./test.sh`.
  Both shims run in the exec service, so this wants the rename (→ `test_unit.sh` /
  `test_integration.sh`). Recommend fixing.
- **`inception.md`** L76/L77/L98 — the first-time shim stubs and "write
  `build.sh` and `test.sh`". Inception must now scaffold **two** test stubs
  (`exit 0` form). Recommend fixing.
- **`advance.md`** L49 — "`build.sh`/`test.sh`/`health.sh`" standard-stages
  mention. Recommend fixing.
- **`migrations.md`** L32 — "before any codebase's `test.sh` runs" → "before any
  codebase's test shims run". Recommend fixing.
- **`sample_project_multi_fixed/infra/infra.yml`** L10 — a prose *comment*
  ("`migrate.sh` / `test.sh` iterating codebase-by-codebase") in a docex fixture.
  Low priority; will fix for consistency.

## Design questions for `sarge`

1. **Adjacent doctrine files.** Do you want the five **flagged adjacents**
   (`exec_service.md`, `inception.md`, `advance.md`, `migrations.md`, the fixture
   `infra.yml` comment) amended **in this mod**, or left for the close-out
   `cohere` pass to sweep? They're all mechanical single-shim→two-shim renames; I
   recommend doing them now to avoid leaving dangling single-shim prose, but
   they're outside the task's *named* blast radius so I'm asking.

2. **`healthchecks.md` L34 — the genuine judgment call.** That line argues health
   stays **one** file (argv-dispatched) and uses `test.sh` as a foil: *"`build.sh`
   / `test.sh` / `migrate.sh` are properties of the source tree and so
   codebase-scoped… One file still, because four files to hold four branches of a
   `case` is worse."* Now that `test` becomes **two** files, the foil weakens and
   could read as self-contradictory. The distinction is real (health splits by
   *core service* via argv — same invocation; test splits by *execution class* —
   different invocation environment). Do you want me to (a) add a one-clause
   reconciliation to L34 in this mod, or (b) leave it for `cohere` to reconcile
   holistically? I lean (a) but it's a wording judgment above a clean one-liner,
   so I'm surfacing it.

3. **Partition mechanism confirmation.** I'm using **`tests/unit/` +
   `tests/integration/` subfolders** (each shim globs its folder) for the migrated
   fixtures, not pytest markers. Reasonable? (It's a fixture-implementation
   choice inside my authority; I flag it only because these fixtures are
   reference material downstream projects copy, so the exemplar matters.)

Nothing here changes the shim contract *beyond* the two-file split SC1 specifies,
and migrating the test projects surfaced no structural problem — so no escalation
beyond these questions.

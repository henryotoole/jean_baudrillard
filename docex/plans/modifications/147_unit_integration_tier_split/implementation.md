# Mod 147 — Implementation Steps

Realizes **SC1**: replace the single per-codebase `test.sh` with **two shims**
(`test_unit.sh` = no-infra tier; `test_integration.sh` = stack-backed tier, incl.
contract). See `overview.md` for design + rationale. This file is code + fixtures
+ docex's own test-suite only.

**Scope guardrails — do NOT:**
- build any fast/no-stack lane, subset scoping, `docex test unit|integration`
  argv, "modes", the `job`/`--detach` substrate, or slots (`--slots`). Those are
  later mods (F5/F7/F3).
- edit any file under `doctrine/` or `skills/`, or docex's own core planning docs
  under `docex/plans/core/`. The doctrine amendments + core-doc updates + CHANGELOG
  are the corporal's documentation step, done after this executes.
- change docex's OWN `tests/` layout or its `pyproject.toml` `-m integration`
  convention. docex is the executor; only the *fixtures it compiles* get the split.

All paths below are relative to the docex project root
`/home/ubuntu/.claude/jean_baudrillard/docex/`.

---

## A. docex source

### A1. `src/docex/pipeline/check.py` — assert BOTH shims exist

In `_gate_codebase_scripts` (around L696–718):

- Change the per-codebase required-script tuple from
  `("build.sh", "test.sh", "health.sh")` to
  `("build.sh", "test_unit.sh", "test_integration.sh", "health.sh")`.
- Update the success-message string (currently
  `f"build.sh/test.sh/health.sh present for {len(all_codebases)} codebase(s)"`)
  to `f"build.sh/test_unit.sh/test_integration.sh/health.sh present for "
  f"{len(all_codebases)} codebase(s)"`.
- Update the docstring's `build.sh`/`test.sh`/`migrate.sh` mentions to name the
  two test shims (the "properties of the source tree" point is unchanged — both
  shims are source-tree properties).

`migrate.sh` (schema-owner-conditional) and the `health.sh` handling are
unchanged.

### A2. `src/docex/orchestrate/test.py` — invoke both shims, phased by tier

Replace step 3 (the `for svc in codebases(ctx):` loop running `["./test.sh"]`,
around L117–136) with a **phased** run — the unit shim across all codebases,
then the integration shim across all codebases, fail-fast on the first non-zero:

```python
        # 3. Both test shims for each codebase, phased by tier: test_unit.sh
        # (no-infra) across all codebases first, then test_integration.sh
        # (stack-backed, incl. contract). Fail-fast on the first non-zero, so
        # the cheap tier gates the expensive one. Each runs as a one-off in the
        # codebase's exec service; the stack is already up (unit tests are
        # harmless against it — the no-stack lane is a later mod).
        #
        # WHY build=True: see step 2 above — same `test`-env freshness rule.
        for shim in ("./test_unit.sh", "./test_integration.sh"):
            for svc in codebases(ctx):
                key = exec_service_key(ctx, _TEST_ENV, svc)
                rc = docker.compose_run_one_off(
                    compose_file, key, [shim], build=True,
                    env_file=env_file, project_dir=project_dir,
                    project_name=project_name,
                )
                if rc != 0:
                    print(f"error: {shim} for {svc!r} exited {rc}.",
                          file=sys.stderr)
                    first_failure = rc
                    return rc
```

Also update the module docstring (L9 "Run each codebase's test.sh…" and the L117
comment) to describe the two-shim phased run. Bring-up, migrate loop, `finally`
teardown (`preserve_volumes=False`), and the `build=True` rule are unchanged.

---

## B. Migrate the three fixture codebases to the two-shim form

Codebases (confirm with `grep -rl 'test\.sh' <root>/test_projects <root>/tests/fixtures`
that these are the only ones — a fixture shipping a `build.sh` alongside a
`test.sh` is a codebase):

1. `test_projects/fixed/core/api/`
2. `test_projects/elastic/core/api/`
3. `tests/fixtures/sample_project/core/api/`

### B1. `test_projects/{fixed,elastic}/core/api/` (identical treatment for both)

These run real `pytest` in the smoke walk, so partition honestly.

**Shims** — delete `test.sh`; create two executable (`chmod +x`) shims at the
codebase root:

`test_unit.sh`:
```sh
#!/bin/sh
# test_unit.sh — no-infra test tier for the `api` codebase.
# Domain / alogic / adapter-unit tests under tests/unit/ (stub-backed: no
# postgres, no live stack). Globs the folder; the folder is the authority.
set -eu
exec pytest -q /service/tests/unit
```

`test_integration.sh`:
```sh
#!/bin/sh
# test_integration.sh — stack-backed test tier for the `api` codebase.
# Module-integration / flow / contract tests under tests/integration/, run
# against the live test-env stack (real postgres, sibling core services).
# Globs the folder; the folder is the authority.
set -eu
exec pytest -q /service/tests/integration
```

**Reorganize `tests/`** — create `tests/unit/` and `tests/integration/`, each
with an empty `__init__.py` (the parent `tests/__init__.py` stays; both fixtures
package their tests, so the subfolders must be packages too). `git mv` the seven
existing test files into:

- `tests/unit/`: `test_jobs_alogic.py`, `test_processor_smoke.py`,
  `test_clock_smoke.py`, `test_jobs_drain.py`
- `tests/integration/`: `test_smoke.py`, `test_jobs_smoke.py`,
  `test_jobs_concurrency.py`

(Classification is by whether the test touches the live stack — verified in
`overview.md §4`. The four unit files are stub-backed / no-DB / no-`root`; the
three integration files hit real postgres or drive the live stack via
`TestClient`.) The test files' bodies need no change — each already does its own
`sys.path.insert(0, "/service/dist")`, and none imports a sibling test module.
Both subfolders end up non-empty (4 and 3), avoiding pytest's exit-5.

**Dockerfile** (`test_projects/{fixed,elastic}/core/api/Dockerfile`):
- `dev` stage: `COPY build.sh migrate.sh test.sh health.sh /service/` →
  `COPY build.sh migrate.sh test_unit.sh test_integration.sh health.sh /service/`
  (the dev `RUN chmod +x /service/*.sh` already covers both new shims).
- `test` stage: `COPY test.sh /service/test.sh` →
  `COPY test_unit.sh test_integration.sh /service/`; and
  `RUN chmod +x /service/test.sh` →
  `RUN chmod +x /service/test_unit.sh /service/test_integration.sh`.
  (`COPY tests/ /service/tests/` already carries the new subfolders.)
- Update the `test`-stage comment ("test.sh runs every core service's tests") to
  reflect the two shims.

### B2. `tests/fixtures/sample_project/core/api/`

This fixture backs docex's own `check`/orchestrate/real tests; its tests never
assert app behavior (they "exercise the shim, not the app"). Keep it minimal but
give **both** subfolders a passing test (exit-5 guard).

- Delete `tests/test_smoke.py`. Create (no `__init__.py` — this fixture's `tests/`
  is not a package today):
  - `tests/unit/test_unit_smoke.py` → `def test_passes() -> None:\n    assert True`
  - `tests/integration/test_integration_smoke.py` → same trivial body.
- Delete `test.sh`; create the same two shims as B1 (globbing `tests/unit` /
  `tests/integration`), `chmod +x`.
- Dockerfile (`tests/fixtures/sample_project/core/api/Dockerfile`):
  - `dev` stage: replace `COPY test.sh /service/test.sh` with
    `COPY test_unit.sh /service/test_unit.sh` and
    `COPY test_integration.sh /service/test_integration.sh`
    (dev `RUN chmod +x /service/*.sh` covers both).
  - `test` stage: `COPY test.sh /service/test.sh` →
    `COPY test_unit.sh test_integration.sh /service/`; and
    `RUN chmod +x /service/test.sh` →
    `RUN chmod +x /service/test_unit.sh /service/test_integration.sh`.

---

## C. Update docex's own test suite

### C1. `tests/unit/test_pipeline_check.py` — new gate tests

After the existing `test_check_requires_health_sh` / `_executable` pair (around
L314–336), add four tests mirroring them exactly, for each new shim:

- `test_check_requires_test_unit_sh` — `unlink()` `core/api/test_unit.sh`,
  assert `rc == 1` and `"codebase_scripts" in out`.
- `test_check_requires_test_unit_sh_executable` — `chmod(0o644)` it, same asserts.
- `test_check_requires_test_integration_sh` — `unlink()`
  `core/api/test_integration.sh`, same asserts.
- `test_check_requires_test_integration_sh_executable` — `chmod(0o644)`, same.

Use the same fixtures (`worktree_setup, fake_docker, stub_test_and_compile,
capsys`) as the `health.sh` gate tests. (The `worktree_setup` fixture derives
from the `sample_project` fixture migrated in B2, so both shims exist there.)
Search the file for any test that creates/asserts a bare `test.sh` and repoint it.

### C2. `tests/unit/test_orchestrate_test.py` — phased two-shim order

The new invocation order for the single-codebase `sample_ctx` is:
`migrate.sh`, then `test_unit.sh`, then `test_integration.sh`. For the
two-codebase `multi_ctx` (`api` before `reporter`, sorted): migrate(schema
owners), then **unit phase** `test_unit.sh`@api, `test_unit.sh`@reporter, then
**integration phase** `test_integration.sh`@api, `test_integration.sh`@reporter.

Update each test:
- `test_test_runs_migrate_then_test_then_teardown`: assert both
  `("./test_unit.sh",)` and `("./test_integration.sh",)` are in `run_cmds`, and
  `index(migrate) < index(test_unit) < index(test_integration)`.
- `test_test_teardown_still_runs_after_test_failure`: set the failing exit_code
  key to `("exit","compose_run_one_off","sample-test-api-exec",("./test_integration.sh",))`;
  assert `rc == 1` and teardown ran.
- `test_test_teardown_still_runs_on_python_exception`: change `_raising_run`'s
  guard `command[0] == "./test.sh"` → `command[0] == "./test_integration.sh"`.
- `test_test_short_circuits_on_migration_failure`: assert neither
  `("./test_unit.sh",)` nor `("./test_integration.sh",)` in `run_cmds`.
- `test_run_test_every_codebase_uses_its_own_exec_service`: assert the
  `test_unit.sh` services == `["sample-test-api-exec","sample-test-reporter-exec"]`
  and the `test_integration.sh` services == the same, and that the whole unit
  phase precedes the whole integration phase.
- `test_run_test_short_circuits_before_later_codebase`: set `api`'s
  `test_unit.sh` → 9; assert only `sample-test-api-exec` ran the unit shim and
  **no** `test_integration.sh` ran at all (fail-fast in the unit phase).
- `test_run_test_second_codebase_failure_returns_its_code`: set `reporter`'s
  `test_unit.sh` → 3; assert `rc == 3`, teardown ran.
- `test_run_test_one_offs_build_first`: expected built-cmd set becomes
  `{("./migrate.sh",), ("./test_unit.sh",), ("./test_integration.sh",)}`.

### C3. `tests/unit/test_subprocess_docker_client.py`

`test_compose_run_one_off_build_flag_is_a_run_option` uses `["./test.sh"]` as a
placeholder command; rename it to `["./test_integration.sh"]` (and the expected
argv's trailing `"./test.sh"` → `"./test_integration.sh"`) so no stale `test.sh`
lingers. Purely cosmetic — this test pins docker-client argv mechanics.

### C4. Sweep for stragglers

`grep -rn 'test\.sh' tests/ src/` (excluding `.venv`, `stage_test.sh`,
`test_projects` already handled). Repoint any remaining docstring/comment/assert
that names a bare codebase `test.sh` to the two-shim form. Do NOT touch
`stage_test.sh` (staging shim — unrelated).

---

## D. Verification

1. `python -m pytest tests` (docex's default unit suite) is fully green.
   `test_collection_partition.py` must still pass (new gate tests live in
   `tests/unit/`, unmarked → unit bucket).
2. Spot-check each migrated Dockerfile actually `COPY`s and `chmod +x`s **both**
   shims in the `test` stage (and dev), and that `tests/unit` + `tests/integration`
   are both non-empty in every migrated codebase.
3. `git status` — confirm `test.sh` is gone and both shims exist in all three
   codebases; the seven `test_projects` test files moved (not duplicated).

Report what changed, any deviation from these steps, and the pytest result.
Integration tests (`-m integration`, real docker) are NOT part of this run — the
corporal handles the fuller verification.

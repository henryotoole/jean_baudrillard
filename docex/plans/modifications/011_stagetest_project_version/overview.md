# Mod 011 — `PROJECT_VERSION` doctrine-injected on core services and stage tester

## Problem

The maptrack smoke release surfaced this: `stage_test.sh` contained `EXPECTED_VERSION=0.0.1` hardcoded next to the assertion that `/health` returns the expected version. Bumping `project.yml`'s version did not also bump `EXPECTED_VERSION` — different layers, no link, must be hand-synced. Maptrack didn't: `project.yml` advanced to `0.0.2`; the stage tester kept asserting `0.0.1`; stage tests failed against a correctly-deployed build.

The original framing was narrow: inject `PROJECT_VERSION` into the stage tester container so projects don't have to hand-maintain it. Investigation surfaced a deeper structural twin: the deployed core service *itself* has no canonical way to know its own version. The smoke project's `web/src/root.py` reads `APP_VERSION` from env with a hardcoded `"0.0.1"` fallback, and `APP_VERSION` is never set by any compiled infra — so the deployed service always reports `0.0.1` regardless of `project.yml`. Two different env var names (`APP_VERSION` vs `PROJECT_VERSION`) for one logical concept ("the current project version"), with no plumbing between either and the source of truth.

Mod 011 unifies the picture: **`PROJECT_VERSION` is doctrine-injected on every core service container *and* on the stage tester**. One name, one source (`project.yml` `version:`), no drift possible. `APP_VERSION` disappears.

## Design

### Two injection sites, one name

1. **Stage tester (`./bin/docex stagetest`).** Already injects `STAGING_URL`. Now also injects `PROJECT_VERSION` from `ctx.project.version`.
2. **Every core service container (compile time).** New per-core-service foundation invariant per the doctrine edit in `transfer_tables.md § Per-core-service env`. Compose `environment:` on fixed; ECS task-def `environment[]` on elastic. Same value on both: `project.yml`'s `version:`.

Backing services do not get the variable. They run third-party software with no application code that would consume it; the doctrine notes this explicitly.

### Why a per-core-service invariant, not a CICL substitution variable

Considered: expose `${project_version}` as a CICL compile-time variable, then have projects opt in by writing `PROJECT_VERSION: ${project_version}` under `core_services.<svc>.env` in `infra.yml`. Rejected for v1:

- **Auto-injection is the same shape as the existing per-container invariants.** The doctrine already mandates `container_name`, `logging`, `restart`, `networks` on every compose service — no project opt-in. `PROJECT_VERSION` joins that set with the same logic: deterministic, doctrine-stable, zero project boilerplate.
- **One canonical name avoids the question.** If `${project_version}` substitution existed, two projects could wire it as `APP_VERSION: ${project_version}` and `MY_VERSION: ${project_version}` — same value, different names, confusion. The auto-injected name removes the choice.
- **`${project_version}` is a separable future mod if a use case appears.** Image tag interpolation, label values, etc. — none of those are motivated today. The doctrine notes "adding new injected variables is a doctrine change, not a project change" (tests.md). Same gate applies to new CICL substitution variables.

### `APP_VERSION` removal

The smoke projects' `web/src/root.py` (fixed + elastic, src + dist — 4 files total) currently reads:

```python
VERSION = os.environ.get("APP_VERSION", "0.0.1")
```

Replace with:

```python
VERSION = os.environ["PROJECT_VERSION"]
```

No fallback. If the env var is missing, the service fails loudly at startup — that's the right failure mode for a doctrine-injected variable. No silent default hiding misconfiguration.

The smoke `worker` services don't currently read any version env var (their `/health` is provided by `web`, not themselves). No `worker` changes needed.

### Stage-test assertion

With `PROJECT_VERSION` now reaching the deployed core service too, the smoke project stage tests can assert end-to-end version coherence:

```python
PROJECT_VERSION = os.environ["PROJECT_VERSION"]
...
def test_health_endpoint() -> None:
    response = httpx.get(f"{STAGING_URL}/health", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == PROJECT_VERSION
```

This works because the same env var (`PROJECT_VERSION`) holds the same value (`project.yml.version`) on both sides of the comparison: in the running web container (compiled in by docex) and in the stage tester (injected by `docex stagetest`).

### Stagetest Dockerfile comment

Both smoke `infra/stage/Dockerfile` comment headers currently mention only `$STAGING_URL`. Extend to list `$PROJECT_VERSION` alongside. One-line documentation parity.

### Doctrine edit

The doctrine landed:

- `cicd.md § Staging Tests` step 3 — `PROJECT_VERSION` listed alongside `STAGING_URL` (already in the campaign doctrine commit).
- `tests.md § Staging Tests § Injected environment` — table documenting both injected vars (already in the campaign doctrine commit).
- `transfer_tables.md § Per-core-service env (both foundations)` — **new section** added today, describing `PROJECT_VERSION` as a doctrine-injected per-core-service env var. Notes: not project-declared; emitted on both foundations; backing services don't receive it; the name matches what `stagetest` injects so introspection and assertion use the same handle.

Mod 011's source-side work implements all three doctrine touchpoints.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `transfer_tables.md` gets a new "Per-core-service env" subsection (new this morning); `cicd.md` and `tests.md` updates already landed with the campaign doctrine commit. No further edits in this mod. |
| `docex/plans/core/*.md` | No change — the per-core-service env invariant lives in `transfer_tables.md` (data) and `compile.py`'s invariant helpers (code); `compiler.md`'s "Per-foundation invariants" section already points at where to look. |
| `tables/*.yml` | No change. `PROJECT_VERSION` is a foundation invariant emitted from docex code, not a per-engine declaration. |
| `src/docex/**` | `pipeline/stagetest.py` — add `PROJECT_VERSION` to the tester's env dict. `cicl/compile.py` — extend `_apply_fixed_invariants` and `_apply_elastic_invariants` (the per-foundation invariant helpers around lines 565+) to emit `PROJECT_VERSION` on core services. |
| `tests/**` | Unit tests: (a) `test_pipeline_stagetest.py` — assert `PROJECT_VERSION` is in env_items and matches `ctx.project.version`. (b) `test_compose_emitter.py` / wherever the fixed-invariant emission is tested — assert every core service's compose `environment` block carries `PROJECT_VERSION: <version>`, and backing services do NOT. (c) `test_hcl_emitter.py` — same assertions on elastic for ECS task definition `environment[]`. |

Smoke project adoption:

| File | Change |
| ---- | ------ |
| `test_projects/{fixed,elastic}/core/web/src/root.py` | `APP_VERSION` → `PROJECT_VERSION`. No fallback. |
| `test_projects/{fixed,elastic}/core/web/dist/root.py` | Same — `dist/` mirrors `src/`. |
| `test_projects/{fixed,elastic}/infra/stage/tests/test_smoke.py` | Read `PROJECT_VERSION`, assert against `body["version"]` in `test_health_endpoint`. |
| `test_projects/{fixed,elastic}/infra/stage/Dockerfile` | Comment header lists both `$STAGING_URL` and `$PROJECT_VERSION`. |

## Validation

1. `python3 -m pytest tests/unit/` — green, including all new tests.
2. `python3 -m pytest tests/integration/` — green (no integration tests expected to change semantics).
3. Manual `./bin/docex stagetest` walk against a real deployed stack — covered by the campaign-end PRE_CUT_CHECKLIST, not this mod.

## Decisions captured

1. **One canonical env var name: `PROJECT_VERSION`.** Used identically by docex-injected stage tester and by docex-injected core service containers. `APP_VERSION` removed entirely.
2. **Auto-injection, not opt-in via `${project_version}` CICL variable.** Matches the existing foundation-invariant pattern (`container_name`, `logging`, etc.). Zero project boilerplate. The CICL variable idea is a separable future mod if a non-env-var use case (image tags, labels) ever motivates it.
3. **Core services only.** Backing services run third-party software and have no application code that would consume the var. Doctrine notes the asymmetry explicitly.
4. **No fallback in the smoke `root.py`.** `os.environ["PROJECT_VERSION"]` raises if unset. Doctrine-injected variables should be hard-required; silent defaults hide misconfiguration.
5. **Not an SSM secret on elastic.** The version is not sensitive. Plain `environment[]` entry on the ECS task definition, same shape as a project's own non-secret env vars.

## Open questions

(None expected. Operator confirmed the design direction; doctrine edit landed; implementation is mechanical.)

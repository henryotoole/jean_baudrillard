# Mod 102 — Implementation Steps

Telemetry identity. Two resource attributes added, and one inherited leak closed.
Design rationale: [`overview.md`](./overview.md) — read § 2 before touching
`compile.py`, because the *reason* for the shortcut removal in Step 2 is the part
a later reader will want to undo.

Everything is in `docex/`. Paths below are relative to `/home/ubuntu/.claude/jean_baudrillard/docex`
unless stated otherwise. Use `python3 -m pytest`, **never** `uv run pytest`.

## Ground rules

- **Do not touch any file under `doctrine/`.** `telemetry.md` and
  `specifics/telemetry_infra.md` will read stale after this mod. That is planned
  and belongs to Mod 106.
- **Do not touch `test_projects/`.** Both smoke projects are still
  `cicl_version: "1"` and their committed `infra/output/` is pre-advance; Mod 107
  migrates them. Do not regenerate compiled output there.
- **Do not touch** `docex/tests/unit/test_pipeline_projinfra.py`, `docex/uv.lock`,
  or anything under `doctrine/` — all are pre-existing uncommitted work by others.
- Do not update `plans/core/*.md` or `CHANGELOG.md`. Documentation is a later
  step of the mod cycle, performed outside this implementation.
- Do not commit. The mod cycle commits after review.

## Step 1 — the two new attributes

In `src/docex/cicl/compile.py`, the OTel tail of `_build_env_surface` currently
reads (around `:912-925`):

```python
            out["OTEL_SERVICE_NAME"] = name
            out["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
            out["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
            out["OTEL_RESOURCE_ATTRIBUTES"] = (
                f"service.namespace={project_name},"
                f"service.version={project_version},"
                f"deployment.environment.name={env}"
            )
```

Append `docex.core_service` and `docex.process_type` **after** the existing
three, in that order. The existing triple's keys, values, and order do not
change. Build the attribute string from a list joined on `","` rather than
extending the f-string concatenation, because the last attribute is conditional
(Step 2).

Values:

- `docex.core_service` — the **codebase** authoring name, i.e. the `svc_name`
  loop variable (not `name`, which is the two-segment compiled identity, and not
  a DNS-labeled form).
- `docex.process_type` — the **process** authoring name, i.e. `proc_name`.

`_build_env_surface` is only ever called when `is_core` is true, so `svc_name`
and `proc_name` are both non-`None` there.

Carry a comment recording *why* two attributes exist when `service.name` already
fuses both segments: both axes must be queryable, and a hyphenated
`service.name` does not decompose because `_SERVICE_NAME_RE`
(`src/docex/cicl/model.py:24`) admits `-` in both segments. Note the `docex.`
prefix follows the `docex.project` docker-label precedent
(`src/docex/emit/compose.py:67-79`).

## Step 2 — de-qualify the codebase env surface

This is the inherited Mod 099 leak. `OTEL_SERVICE_NAME` is stamped inside the
shared tail, so it reaches `service_env` — the **codebase**-scoped surface
consumed by the exec service (`src/docex/emit/compose.py:696`) and the elastic
migrate task definition (`src/docex/emit/hcl.py:562`) — carrying a process
segment that names a process type neither artifact is.

### 2a — parameterize the identity

Change the helper's signature from

```python
        def _build_env_surface(source: dict[str, Any]) -> dict[str, Any]:
```

to take the telemetry identity explicitly, keyword-only:

```python
        def _build_env_surface(
            source: dict[str, Any],
            *,
            otel_service_name: str,
            otel_process: str | None,
        ) -> dict[str, Any]:
```

`out["OTEL_SERVICE_NAME"]` becomes `otel_service_name`. `docex.process_type` is
appended **only when `otel_process is not None`**; `docex.core_service` is
emitted unconditionally (it is `svc_name` on both surfaces).

The comment on that conditional must state the invariant, not merely the
mechanism:

> `docex.process_type` is present **iff** the emitter is a declared process
> type. Its absence is the signal that this is a per-codebase artifact (the exec
> container, the migrate task definition) — not an omission to be filled in.

That sentence is load-bearing: a future reader who finds a missing attribute will
otherwise "fix" it.

### 2b — call it twice, unconditionally

Replace the two-surface block (around `:928-939`):

```python
        env_block: dict[str, Any] = {}
        service_env: dict[str, Any] = {}
        if is_core:
            effective_env = {**(core_svc.env or {}), **(svc.env or {})}
            env_block = _build_env_surface(effective_env)
            # Identical by construction when the process declares no `env:`
            # overlay — copied rather than aliased so a later mutation of one
            # cannot silently reach the other.
            service_env = (
                dict(env_block) if not svc.env
                else _build_env_surface(dict(core_svc.env or {}))
            )
```

with a form that builds both surfaces through the helper, always:

- `env_block` — `effective_env`, `otel_service_name=name`,
  `otel_process=proc_name`.
- `service_env` — `dict(core_svc.env or {})`, `otel_service_name=svc_name`,
  `otel_process=None`.

**The `dict(env_block)` shortcut is deleted deliberately, and the comment must
say so.** It existed because the two surfaces were identical whenever a process
declared no `env:` overlay. That is exactly the premise this mod falsifies: the
surfaces now differ in `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` even
with no overlay. Write the reason into the code, not just here — a shortcut whose
justification has evaporated is precisely what a later "optimization" pass
restores.

Double-resolving the service-level block is harmless and is not a new code path:
it already happens today whenever a process declares an overlay.
`MagicRefResolver.deps` is append-only with no consumer
(`src/docex/cicl/magic_refs.py:243`), and the cycle guard is discarded in a
`finally` (`:253-257`).

### 2c — the comment that becomes true

`src/docex/emit/compose.py:692-695` asserts that `service_env` "is identical
across a codebase's process types by construction … so reading it off `procs[0]`
picks nothing — there is nothing to pick." That was false for exactly one key
before this step. Leave the claim, and add a short clause noting that the
telemetry identity on this surface is codebase-scoped for the same reason — so a
reader who checks the claim finds it holds for every key.

Do **not** change what either emitter reads. Both keep reading
`head.service_env`; the fix is in what the compiler puts there.

## Step 3 — tests

All unit. Nothing here crosses docker, AWS, or git, so no integration test is
warranted.

### 3a — `tests/unit/test_telemetry.py`

1. `test_otel_resource_attributes_format` (`:375`) asserts the attribute string
   by **exact equality**. Extend it to all five attributes, triple first and in
   order. This is the pin on "the existing triple unchanged" — keep it an
   exact-equality assertion; do not weaken it to substring checks.
2. `test_otel_env_vars_injected_on_every_core_service_fixed` and
   `..._elastic` (~`:240` and `:265`): add assertions that
   `docex.core_service` and `docex.process_type` are present with the correct
   authoring-name values for each service. Note the existing fixture
   `_multi_core_fixed_doc` has two *codebases* (`api`, `worker`) each with a
   process named `web`, which is a useful case — `docex.process_type=web` on
   both, `docex.core_service` differing.
3. New test: a **multi-process** codebase gets distinct `OTEL_SERVICE_NAME`
   (`api-web` vs `api-worker`) and *identical* `docex.core_service=api`, with
   `docex.process_type` differing. This is the pair of assertions that proves
   both axes are independently queryable — the whole point of Step 1.
4. New test: no compiled env surface on either foundation contains
   `service.instance.id`. Assert against both `.env` and `.service_env` of every
   compiled service, so the claim cannot rot in either surface.
5. Extend the process-level reserved-key coverage:
   `tests/unit/test_process_nesting.py::test_21_process_env_cannot_shadow_otel_service_name`
   covers only `OTEL_SERVICE_NAME`. Parametrize it over all five reserved keys
   (`PROJECT_VERSION` plus the OTel quartet — the list is
   `_RESERVED_CORE_ENV_KEYS` at `src/docex/cicl/validate.py:86`), keeping the
   existing `where`-suffix assertion so the diagnostic still points at the
   process.

### 3b — the exec container's identity (`tests/unit/test_exec_service.py`)

Add a test using the existing module-scoped `fixed_root` fixture (its
`_multi_process_project` helper plants a `worker` process type alongside `web`,
so the codebase genuinely has two):

- `exec_env["OTEL_SERVICE_NAME"] == "api"` — no process segment.
- `"docex.core_service=api"` in `exec_env["OTEL_RESOURCE_ATTRIBUTES"]`.
- `"docex.process_type"` **not in** `exec_env["OTEL_RESOURCE_ATTRIBUTES"]`.
- Guard against a vacuous pass at the other end, in the same test: the sibling
  app containers `sample-{env}-api-web` and `sample-{env}-api-worker` do report
  `api-web` / `api-worker` and do carry `docex.process_type`. Without this a
  future change that drops the OTel keys from every surface would pass.

Run it across all four envs, matching the module's existing convention.

### 3c — the migrate task definition's identity

The elastic fixture `tests/fixtures/sample_project_elastic` has a single-process
`api`, which would pin the value but not demonstrate de-qualification. Build a
multi-process elastic project the way `test_exec_service.py::_multi_process_project`
does — copy the fixture to `tmp_path`, drop `infra/output/`, plant a `worker`
process type onto `api`, `run_compile`. Put it wherever the migrate task
definition is already exercised (`tests/unit/test_hcl_emitter.py` has
`_block(tf, 'resource "aws_ecs_task_definition" "api_migrate"')` at `:535` and a
`compiled_elastic_project` fixture; a module-local multi-process fixture is
fine).

Assert on the `api_migrate` task-definition block:

- the `OTEL_SERVICE_NAME` environment entry's value is `api`, not `api-web`;
- its `OTEL_RESOURCE_ATTRIBUTES` carries `docex.core_service=api` and **no**
  `docex.process_type`;
- the sibling `api-web` app task definition still reports `api-web` and does
  carry `docex.process_type=web` (the same anti-vacuity guard as 3b).

## Step 4 — verify, do not re-implement

Three properties are already true (Mod 096) and are only being confirmed. If any
check below fails, **stop and report it** rather than implementing the missing
behavior — a failure here means the mod's premise is wrong and its C.O. needs to
know.

1. `OTEL_SERVICE_NAME` is the two-segment compiled identity —
   `src/docex/cicl/compile.py:918` assigns `name`.
2. Reserved-key enforcement spans both env levels —
   `src/docex/cicl/validate.py:1224-1284` builds `sources` from the
   service-level `env`/`secrets`/`config` **and** each process type's own `env:`.
3. One sidecar per long-running process type, none for `scheduler` — fixed:
   `src/docex/emit/compose.py:632-660` iterates compiled services and `continue`s
   on `role == "scheduler"`; elastic: the sidecar container is only added to task
   definitions that emit `ecs_service`, which a scheduler does not
   (`src/docex/emit/hcl.py:420`).

## Step 5 — suites

Run both and report both numbers:

```
python3 -m pytest tests/unit -q
python3 -m pytest tests/ -q
```

Gate: unit **≥ 942 passed** (the pre-mod baseline, verified), full suite
**≥ 1006 passed / 17 deselected**. Tests added by this mod raise both.

Do not delete or skip a test to make the gate. If an existing test fails and the
correct fix is not obviously an expectation update caused by the two new
attributes or the de-qualified codebase surface, stop and report.

Expected-to-change existing tests, for reference — if a test outside this list
fails, treat it as a finding:

- `tests/unit/test_telemetry.py::test_otel_resource_attributes_format` (exact
  attribute string).
- Any test asserting an exact `OTEL_RESOURCE_ATTRIBUTES` value; a substring
  assertion on the triple is unaffected.

## Not in scope

No contract file changes: `docex` publishes no core-service contract, and this
mod changes no service boundary. No version artifact (`VERSION`,
`docex/pyproject.toml`, `src/docex/__init__.py`, `CHANGELOG.md`) — Mod 107 owns
the cut. No `cicl.md` or `contracts.md` rule change is required.

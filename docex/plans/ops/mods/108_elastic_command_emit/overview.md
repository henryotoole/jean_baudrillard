# Mod 108 — Elastic task definitions must emit the process type's `command`

## Motive

The elastic HCL emitter never emits a process type's `command` into the ECS
container definition. Every `aws_ecs_task_definition` for a core process type
ships `command = null`, so every ECS task runs whatever the image's Dockerfile
`CMD` happens to be.

Found by the 1.6.0 pre-cut smoke walk at `PRE_CUT_CHECKLIST § D.9`. This is a
**cut blocker**: 1.6.0's headline feature is process types, and on elastic the
feature is inert — a codebase's N process types all run the same command.

## Doctrine position — already correct, no change needed

[`infrastructure.md § Core Service Containers`](../../../../doctrine/infrastructure/infrastructure.md#core-service-containers)
already states the rule plainly:

> A core service's Dockerfile `CMD` is not used. Every process type declares its
> own `command` in `infra.yml`, which is what the compiler emits — so with
> several process types sharing one image, no `CMD` could be correct for all of
> them, and the ambiguity is deleted rather than answered.

Doctrine says the ambiguity is deleted. On elastic, `docex` answered it with the
`CMD` instead. So this mod touches **only** the `src` and `tests` layers of the
five-artifact alignment; `doctrine/`, `plans/core/`, and `tables/` are already
right and stay untouched.

`command` is deliberately **not** a transfer-table field — it is a CICL
process-type attribute the emitters read directly. This is an emitter gap, not a
table gap.

## Root cause

The two emitters obtain the compiled body differently:

| Emitter | Mechanism | Result |
| ------- | --------- | ------ |
| `emit/compose.py::_service_block` | `block = dict(svc.body)` — whole-body pass-through | `command` flows automatically; fixed foundation correct |
| `emit/hcl.py::render_task_definition` | builds `container_def` key-by-key (`name`, `image`, `essential`, `logConfiguration`, `portMappings`, `environment`, `secrets`, `target_extras`, `dockerLabels`, `mountPoints`, `dependsOn`) | `command` is never read; elastic foundation broken |

The data is present and correct on both branches — `cicl/compile.py` sets
`body["command"] = svc.command` at `:822` (fixed) and `:859` (elastic). Only the
HCL consumer is missing.

Because `render_task_definition` is shared, the defect covers **every** elastic
core task definition: long-running `ecs_service` process types *and* the
scheduler RunTask. The `aws_scheduler_schedule` target carries no
`overrides`/`containerOverrides`, so a scheduled job has no second chance to
supply the command either.

The per-codebase `_migrate` task definition is **not** affected —
`render_migration_task_definitions` hard-codes
`"command": ["/service/migrate.sh"]`, which is why migrations worked on the walk.

## Observed failure

On the smoke walk's `stage` env:

- `api-worker`'s container logged `Uvicorn running on http://0.0.0.0:8080` — it
  ran `entrypoints/web.py`, because `api`'s Dockerfile `prod` stage declares
  `CMD ["python", "/service/dist/entrypoints/web.py"]`.
- Its container `healthCheck` probes `:8081/health` (nothing listening) →
  container `UNHEALTHY`.
- ECS Service Connect stopped serving the unhealthy endpoint, so the sibling
  fan-out `https://stage.…/health/api/worker` returned
  `503 {"detail":"api.worker unreachable: … Name or service not known"}`.

`/health`, `/health/probe`, `/health/events` and `api-web.stage.…/health` were
all 200 — the failure is confined to the second process type of the codebase.

## Why no test caught it

1. **Masked by Dockerfile luck.** The seed's `api` `CMD` is `web.py` and
   `reaper`'s is `prune.py`, so `api-web` and `reaper-prune` accidentally ran the
   correct command. Only a codebase's *second* process type is visibly wrong —
   and until CICL v2 there were no multi-process codebases.
2. **No HCL output assertion.** `command` appears in `tests/unit/test_hcl_emitter.py`
   only as fixture *input* (`_MIGRATE_WORKER`, line 566). Nothing asserts it in
   rendered output.
3. **Integration tests are dev/fixed only** — `tests/integration/conftest.py`
   points at the fixed path, which is the working one.

## Change

### `src/docex/emit/hcl.py::render_task_definition`

Read `command` off the compiled body and set it on the app container
definition, normalizing to the list form ECS requires:

- `list` → emitted as-is.
- `str` → `shlex.split`, matching how `compose.py::_wrapped_job_command` already
  treats the same `str | list[str]` union so the two foundations interpret one
  `infra.yml` declaration identically.
- absent/empty → key omitted (backing services carry no `command` of their own
  beyond what their transfer-table body supplies, and an empty `command: []` is
  rejected by ECS).

Position it with the compiler-owned invariants, i.e. **after**
`container_def.update(svc.target_extras[...])`, so a transfer table cannot
override the process type's declared entry point. `command` is the one field
that decides *which process type this container is*; letting a table win over it
would reintroduce exactly the ambiguity the doctrine deletes.

Backing services reach this renderer too. Their bodies may legitimately carry a
table-supplied `command` (e.g. `object_store.yml`'s minio `command`, today
`fixed`-only). Reading `body["command"]` uniformly is therefore correct and
strictly widens correctness rather than special-casing `svc.is_core`.

### `tests/unit/test_hcl_emitter.py`

Add assertions that fail before the fix:

1. **Two process types, two commands.** Using the existing
   `multi_process_elastic_tf` fixture (which plants a second process type on
   `api`), assert `api-web`'s and `api-worker`'s rendered container definitions
   carry *different*, correct `command` values. This is the anti-vacuity core:
   it is exactly the case the Dockerfile `CMD` cannot satisfy.
2. **Scheduler RunTask.** Assert the `reaper-prune`-shaped scheduler task
   definition emits its `command`, since the schedule target supplies no
   override.
3. **String form normalizes.** A `command: "python -m foo"` declaration renders
   as a JSON list, not a bare string.
4. **Migrate task definition unchanged** — still `["/service/migrate.sh"]`,
   guarding against the fix bleeding into the per-codebase path.

## Scope boundaries

- **No doctrine edit.** The rule is already stated correctly; this is docex
  catching up to it.
- **No transfer-table edit.** `command` is not a table field.
- **No seed Dockerfile edit.** Whether the test-project Dockerfiles should keep
  a `CMD` at all is a separate question — a `CMD` is what masked this bug, and
  doctrine says it is unused. Removing it would turn this class of bug from
  "silently runs the wrong process" into "container fails to start", which is
  strictly better. Deliberately **out of scope** here so the fix can be verified
  against the seed exactly as the walk found it; flagged for the operator.
- **No `verify_clean.sh` change.** The walk found separate coverage gaps there;
  they are not this mod.

## Design questions

1. **Should the seed Dockerfiles drop their `CMD`?** Recommended (it converts a
   silent-wrong-process failure into a loud one), but it would also remove the
   only evidence of the masking, so it is left to the operator and a follow-up
   mod.
2. **Should `docex check` gate on `CMD`-vs-`command` divergence?** A gate that
   fails when a core Dockerfile declares a `CMD` would make the doctrine rule
   mechanically enforced instead of merely stated. Out of scope; worth a mod.

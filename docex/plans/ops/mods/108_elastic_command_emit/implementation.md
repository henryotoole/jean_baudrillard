# Mod 108 — Implementation

Design: [`overview.md`](./overview.md).

Written after the fact — the mod was designed, implemented, and verified in one
pass because it unblocked a live pre-cut smoke walk with `stage` infrastructure
already provisioned in AWS. Recorded here in the standard shape so the change is
reviewable as a normal mod.

## Step 1 — `src/docex/emit/hcl.py`

Add `import shlex` to the module imports.

In `render_task_definition`, immediately **after** the
`container_def.update(svc.target_extras.get("container_definition", {}))` line
and **before** the Mod 070 `dockerLabels` branch:

```python
command = body.get("command")
if command:
    container_def["command"] = (
        list(command) if isinstance(command, list) else shlex.split(command)
    )
```

Three properties of that placement and shape are load-bearing, and each carries
a comment in the source:

1. **After `target_extras`.** `command` joins the compiler-owned invariants
   (`dockerLabels`, `mountPoints`, `dependsOn`) that win over anything a
   transfer table supplies. A table that could override `command` could change
   which process type a container *is*, reintroducing the ambiguity
   `infrastructure.md § Core Service Containers` deletes.
2. **`if command:` (truthy, not `is not None`).** Skips both absent and empty.
   `ProcessType` already rejects an empty `command` at validation, but backing
   services reach this renderer with no `command` at all, and ECS rejects
   `command: []`.
3. **No `svc.is_core` gate.** Backing services may carry a table-supplied
   `command` (`object_store.yml`'s minio entry). Reading it unconditionally
   widens correctness instead of special-casing.

## Step 2 — `tests/unit/test_hcl_emitter.py`

Append a Mod 108 section with two helpers and four tests.

### `_container_objects(block)`

Splits a task definition's `container_definitions = jsonencode([...])` payload
into top-level container objects by **brace balancing**.

This helper exists because the obvious approach is wrong: container keys render
alphabetically, so `command` sorts *before* `name`, with `logConfiguration`'s
nested braces in between. Walking backwards from `name = "<x>"` to the nearest
`{` lands inside the nested object and silently reports "no command" even when
one is present. The first draft of this test did exactly that and produced a
false failure on the migrate task definition.

### `_container_command(block, container_name)`

Finds the named container among those objects and returns its `command` as a
list of strings, asserting with a diagnostic if the key is absent.

### The four tests

| Test | Asserts | Pre-fix |
| ---- | ------- | ------- |
| `test_mod108_each_process_type_emits_its_own_command` | On the existing `multi_process_elastic_tf` fixture (two process types on the `api` codebase), `api-web` → `["python", "/service/dist/app.py"]`, `api-worker` → `["python", "-m", "entrypoints.worker"]`, and the two differ | FAIL |
| `test_mod108_scheduler_run_task_emits_its_command` | A scheduler process type planted on `api` emits its `command`; the `aws_scheduler_schedule` target has no containerOverrides, so the task definition is the only place it can come from | FAIL |
| `test_mod108_string_command_normalizes_to_list` | `command: "python -m entrypoints.worker --verbose"` renders as a 4-element JSON list | FAIL |
| `test_mod108_migrate_task_definition_command_unchanged` | The per-codebase migrate task definition still emits `["/service/migrate.sh"]` | PASS (guard) |

The first three failing and the fourth passing before the fix is the intended
signal: the defect is confined to the per-process renderer, and the guard proves
the fix does not bleed into `render_migration_task_definitions`.

**Anti-vacuity.** Every assertion runs against a codebase with **two** process
types. A single-process codebase cannot detect this defect at all — its one
Dockerfile `CMD` is trivially correct, which is precisely why the bug survived
to a smoke walk.

## Step 3 — Verification performed

- `pytest tests/unit -q` → **987 passed** (983 before, +4).
- Fix stashed → the three process-type tests fail, the migrate guard passes.
- Rebuild `docex:1.6.0` and re-run the smoke walk from
  `PRE_CUT_CHECKLIST § D.9`.

## Not changed

- **`doctrine/`** — the rule was already stated correctly. This mod is docex
  catching up to it, not a doctrine change.
- **`tables/roles/*.yml`** — `command` is a CICL process-type attribute, not a
  transfer-table field.
- **`plans/core/compiler.md`** — describes `ProcessType`'s attribute list
  (including `command`) accurately already; no drift introduced.
- **The seed Dockerfiles** — see `overview.md § Design questions`. Their `CMD`
  is what masked the defect; removing it is a recommended follow-up, held out of
  scope so the fix could be verified against the tree exactly as the walk found
  it.

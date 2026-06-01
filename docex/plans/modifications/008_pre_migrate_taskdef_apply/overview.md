# Mod 008 — Targeted task-def apply before steady-state migrate

## Problem

`docex release stage` (steady-state path) currently runs:

1. Push secrets to SSM.
2. **Migrate** — `RunTask` against the migration task definition family (LATEST revision).
3. **Tofu apply** — push updated task definitions, roll the ECS services.

The migration in step 2 uses the LATEST registered task-definition revision, which (by definition) is whatever was pushed by the *previous* release. Any change introduced in the current release — new image tag, new env-var values, new SSM secret references, anything in the task-def body — isn't visible to migrate until step 3 happens.

That broke us hard during the elastic D.7 walk. The mod-007 fix flipped `aws_db_instance.<svc>.endpoint` (host:port) to `.address` (host only) — a task-def env-var change. We re-released; SSM secrets pushed fine; migrate ran against the stale task-def (still pointing at `.endpoint`); migration failed with double-port DNS lookup; release aborted before tofu apply could push the corrected task-def. The walk only completed once we manually ran `tofu apply` between release attempts.

The doctrine in `release_mechanism.md § Elastic-foundation mechanism` already describes the right behavior:

> 1. Push secrets to SSM (existing step).
> 2. **Update the migration task definition image tag to the new version via the AWS API (`RegisterTaskDefinition`).** This does not affect any running services.
> 3. `RunTask` the migration task definition for each service with a schema.
> ...
> 5. `tofu apply` to update the application's main task definition, triggering the ECS rolling deploy of the new application code.

Step 2 isn't implemented in `pipeline/release.py`. Mod 008 implements it.

## Design

### Implementation choice: targeted `tofu apply`, not direct boto3 RegisterTaskDefinition

Two ways to push a new migration-task-def revision before the migrate step:

1. **Direct boto3** — `aws.ecs_register_task_definition(...)` with a body docex composes from the compiled HCL. Matches the doctrine wording literally.
2. **Targeted tofu apply** — `tofu apply -target=aws_ecs_task_definition.<svc>_migrate` for each schema-owning service. Tofu reads the emitted HCL, registers the new revision, updates tofu state.

We pick **option 2** because:

- Tofu remains the source of truth for the task-def body. Docex doesn't have to re-translate the emitted HCL into the boto3 `RegisterTaskDefinition` payload shape.
- Tofu state stays consistent with AWS state. A direct boto3 call would create a revision tofu didn't know about, complicating the subsequent full apply.
- It's exactly the precedent set by `docex bootstrap` phase 1, which uses `tofu_apply(..., targets=[_ZONE_RESOURCE_ADDR])` to push one resource ahead of the rest.
- The outcome is identical from AWS's POV: a new task-def revision exists, RunTask picks it up.

The doctrine's wording ("via the AWS API (`RegisterTaskDefinition`)") describes the AWS-facing operation. Whether docex invokes it through boto3 or through tofu's provider is an implementation detail. The doctrine prose doesn't need to change.

### Where the fix lives

`src/docex/pipeline/release.py`'s `_release_elastic` function, in the `else` branch (the steady-state path after `first_release` is `False`). Insert a targeted-apply step before `_do_migrate()`:

```python
else:
    # Targeted apply of every migration task definition. This bumps
    # each revision to match the latest emitted HCL (new image tag,
    # env-var changes, secrets[] references) so the subsequent RunTask
    # picks up the current release's content rather than the previous
    # release's. Main service task defs are intentionally NOT touched
    # here — the rolling deploy of the new application code happens
    # only after migrations succeed (per release_mechanism.md). The
    # in-flight web/worker tasks continue serving the old code against
    # the about-to-be-migrated database during this window.
    schema_owners = services_with_schema(ctx)
    if schema_owners:
        rc_init = tofu_init(out_dir)
        if rc_init != 0:
            raise TofuApplyFailed(...)
        targets = [f"aws_ecs_task_definition.{svc}_migrate" for svc in schema_owners]
        rc_targeted = tofu_apply(out_dir, auto_approve=True, targets=targets)
        if rc_targeted != 0:
            raise TofuApplyFailed(
                f"targeted apply of migration task definitions for env "
                f"{env!r} exited {rc_targeted}; aborting release before migrate."
            )

    rc_mig = _do_migrate()
    if rc_mig != 0:
        ...
    _do_apply()
```

The targeted-apply step is a no-op when `schema_owners` is empty (project with no relational databases). Same as the existing migrate step.

### First-release path: unchanged

The first-release branch already runs a full `_do_apply()` before `_do_migrate()`, which creates the migration task-def at the current state. No fix needed there.

### Note about resource-address naming

The HCL emitter (`src/docex/emit/hcl.py:render_core`, around line 348) emits the migration task definition as:

```hcl
resource "aws_ecs_task_definition" "<svc>_migrate" { ... }
```

where `<svc>` is the bare service name from `infra.yml` (no naming-policy translation — this is the Terraform local resource address, not the AWS-side identifier). So the target list is `[f"aws_ecs_task_definition.{svc}_migrate" for svc in schema_owners]`. The `svc` value comes from `services_with_schema(ctx)`, which returns bare service names.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | No change. `release_mechanism.md` already describes the intended step 2; mod 008 implements it. |
| `docex/plans/core/*.md` | No change. |
| `tables/*.yml` | No change. |
| `src/docex/**` | `pipeline/release.py` — targeted task-def apply before migrate in the steady-state branch. Add `services_with_schema` import from `docex.orchestrate._common`. |
| `tests/**` | Unit test: a steady-state release with a schema-owning service calls `tofu_apply` once with `targets=[aws_ecs_task_definition.<svc>_migrate]` BEFORE `run_migrate`, then once with no targets AFTER. Both succeed. Verify call order. |

## Validation

1. `python3 -m pytest tests/` — green.
2. Real-AWS check (operator post-cut, on the existing stage env):
   - Edit a benign field in `test_projects/elastic/infra/infra.yml` (e.g., add a noop env var to web). Recompile, bump project version, containerize.
   - `docex release stage` — should now succeed end-to-end with no manual `tofu apply` in between. The targeted apply runs in the foreground before migrate; migrate uses the bumped revision; full apply at the end is a near-no-op.

## Decisions captured

1. **Targeted tofu apply, not direct boto3 RegisterTaskDefinition.** Keeps tofu as the source of truth; matches the bootstrap-phase-1 precedent; avoids re-translating HCL into boto3 payload shape.
2. **Steady-state branch only.** First-release path already runs full apply before migrate; nothing to fix.
3. **Migration task-defs only — not main service task-defs.** The doctrine intent is for main services to keep serving old code during the migration; only the migration task-def gets a fresh revision pre-migrate. Full apply at the end rolls the main services.
4. **No doctrine prose change.** `release_mechanism.md § Elastic step 2` already describes this behavior; we're implementing what was already prescribed.

## Open questions

(None. Implementation is mechanical from the doctrine.)

# Mod 008 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

One narrow fix in `src/docex/pipeline/release.py`: in the steady-state release branch, run a targeted `tofu apply` to bump each migration task-definition revision before running the migrate step. Doctrine intent per `release_mechanism.md § Elastic-foundation mechanism` step 2; just wasn't implemented.

## Step 1 — Add the imports in `release.py`

File: `src/docex/pipeline/release.py`.

The function `_release_elastic` already imports `tofu_apply` and `tofu_init` from `docex.opentofu.subprocess_runner` (used by `_do_apply`). Confirm those imports are present at module top. Add one more import from `_common`:

```python
from docex.orchestrate._common import services_with_schema
```

Group it with the other docex imports already in the file. Match the existing import sort/style.

## Step 2 — Targeted apply in the steady-state branch

In `_release_elastic`, find the `else:` branch (around lines 255-265 in the current file). It currently looks like:

```python
else:
    # migrate → apply (doctrine order)
    rc_mig = _do_migrate()
    if rc_mig != 0:
        print(
            f"error: migration phase exited {rc_mig}; aborting release "
            f"before tofu apply.",
            file=sys.stderr,
        )
        return rc_mig
    _do_apply()
```

Replace with:

```python
else:
    # Steady-state: bump migration task-def revisions, migrate, then full apply.
    # The pre-migrate targeted apply pushes each migration task-def to
    # the latest emitted HCL (new image tag, env-var changes, secret
    # refs). RunTask in _do_migrate() then picks up the new revision
    # rather than the previous release's. Main service task defs are
    # intentionally NOT in the target set — the rolling deploy of the
    # new application code happens only after migrations succeed.
    # See release_mechanism.md § Elastic-foundation mechanism step 2.
    schema_owners = services_with_schema(ctx)
    if schema_owners:
        rc_init = tofu_init(out_dir)
        if rc_init != 0:
            raise TofuApplyFailed(
                f"'tofu init' for env {env!r} exited {rc_init}"
            )
        targets = [
            f"aws_ecs_task_definition.{svc}_migrate"
            for svc in schema_owners
        ]
        rc_pre = tofu_apply(out_dir, auto_approve=True, targets=targets)
        if rc_pre != 0:
            raise TofuApplyFailed(
                f"pre-migrate targeted 'tofu apply' for env {env!r} "
                f"exited {rc_pre}; aborting release before migrate."
            )

    rc_mig = _do_migrate()
    if rc_mig != 0:
        print(
            f"error: migration phase exited {rc_mig}; aborting release "
            f"before tofu apply.",
            file=sys.stderr,
        )
        return rc_mig
    _do_apply()
```

Notes:
- `_do_apply()` (existing helper) already does `tofu_init` + full `tofu_apply` itself. So the second `tofu_init` inside it is idempotent — no extra cost worth worrying about. Keeping the explicit `tofu_init` inside the targeted-apply block makes it self-contained for readability.
- The `schema_owners` empty-list case skips the targeted apply entirely. Same as `_do_migrate`, which is itself a no-op for projects without schema-owning services.

## Step 3 — Tests

Find `tests/unit/test_pipeline_release.py`. Existing tests likely mock `tofu_apply`, `tofu_init`, `run_migrate`, and the AWS client. Add a test for the new pre-migrate apply ordering:

```python
def test_steady_state_pre_migrate_targeted_apply(...):
    """Steady-state release runs a targeted tofu_apply against migration
    task-defs BEFORE run_migrate, then a full apply AFTER."""
    # Set up mocks. Make ecs_cluster_exists return True so we hit the
    # steady-state branch. Make the fixture project have a schema-owning
    # service (e.g. 'web' owning 'db').
    # Capture the order of (tofu_apply, run_migrate, tofu_apply) calls
    # and the targets= argument on each.

    ...

    assert call_order == [
        ("tofu_apply", {"targets": ["aws_ecs_task_definition.web_migrate"]}),
        ("run_migrate", ...),
        ("tofu_apply", {"targets": None}),  # or no targets kwarg
    ]
```

Adapt to the existing test file's patching conventions and fixture project.

Also add a test for the no-schema-owners case: targeted apply is skipped entirely.

## Step 4 — Run the suite

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/
python3 -m pytest tests/
```

All must pass. If any existing test exercises the steady-state path and was previously asserting a `[run_migrate, tofu_apply]` call order, update it to `[tofu_apply(targets=...), run_migrate, tofu_apply]` after confirming the new order matches mod 008's intent.

## Step 5 — Leave uncommitted

Per the mod process, the design-context LLM reviews before commit.

## Hand-off report

In ≤150 words:
- Files changed.
- Test pass counts and any fixture updates.
- Any decisions beyond impl.md.
- Drift concerns.

## Out of scope

- Doctrine prose changes — `release_mechanism.md § Elastic step 2` already prescribes this; we're implementing.
- The first-release branch — already runs full apply before migrate.
- Bumping main service task-defs pre-migrate — doctrine intent is that those roll only after migrate succeeds.
- Migration tooling itself — unchanged.

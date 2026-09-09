# Mod 144 — Implementation steps

Executor context: repo root `/home/ubuntu/.claude/jean_baudrillard`. Python
interpreter is `docex/.venv/bin/python` (`python` is NOT on PATH); run pytest
from inside `docex/`. Touch ONLY the paths named below. Do NOT run any
release/walk or anything against real infrastructure.

## Step 1 — Edit the playbook template

File: `docex/src/docex/emit/templates/playbook.yml.j2`

Replace the "Pull all images" task. Current block:

```yaml
    - name: Pull all images
      community.docker.docker_compose_v2:
        project_src: "{{ '{{' }} deploy_root {{ '}}' }}"
        project_name: "{{ compose_project_name }}"
        pull: always
        state: present
```

New block (module is a pure pull; no `state:`, so it starts nothing):

```yaml
    - name: Pull all images
      community.docker.docker_compose_v2_pull:
        project_src: "{{ '{{' }} deploy_root {{ '}}' }}"
        project_name: "{{ compose_project_name }}"
        policy: always
```

Leave the rest of the template unchanged. Do NOT touch the per-codebase "Run
migrations for ..." loop or the "Bring up the stack" task — the latter keeps
`state: present` and must remain the ONLY task that starts the stack, and it
already sits after the migrate loop. The resulting emitted task order must be:
render tasks → **Pull all images (pull-only)** → **Run migrations** (per schema
owner) → **Bring up the stack** (`state: present`).

`docex/src/docex/emit/ansible.py` needs NO change — it only builds the
`migrations` list passed to the template.

## Step 2 — Update the existing project-scoping test

File: `docex/tests/unit/test_ansible_emitter.py`, function
`test_playbook_compose_tasks_are_project_scoped`.

The pull task's module key changed, so its `project_name` now lives under
`community.docker.docker_compose_v2_pull`. Change the pull assertion:

```python
        pull = _find_task(root, env, "Pull all images")
        assert pull["community.docker.docker_compose_v2"]["project_name"] == scoped, pull
```

to:

```python
        pull = _find_task(root, env, "Pull all images")
        assert pull["community.docker.docker_compose_v2_pull"]["project_name"] == scoped, pull
```

Leave the "Bring up the stack" (`docker_compose_v2`) and migrate assertions in
that function unchanged.

## Step 3 — Add the new pull-starts-nothing test

File: `docex/tests/unit/test_ansible_emitter.py`. Add a new test function (place
it after `test_playbook_compose_tasks_are_project_scoped`). It must assert the
pull task is a pure pull AND that the up task starts the stack strictly after the
migrate task in task order:

```python
def test_playbook_pull_task_starts_nothing(tmp_path: Path):
    """Mod 144: the fixed release must pull images WITHOUT starting the stack, so
    the per-codebase migration runs while the OLD containers still serve — and a
    failed migration aborts before any new code goes live. The bug was a
    `community.docker.docker_compose_v2` pull task carrying `state: present`,
    which converges the stack to running. A valid-YAML/green playbook cannot
    catch that; the defect lives in the meaning of one module argument, so assert
    on the module + args directly.

    Guarantees:
      - "Pull all images" uses the pure-pull module and carries NO
        service-starting `state:`.
      - "Bring up the stack" still carries `state: present` (it is the one task
        that starts the stack) and comes AFTER the migrate task in task order.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    for env in ("stage", "prod"):
        doc = _playbook_doc(root, env)
        tasks = doc[0]["tasks"]
        names = [t.get("name") for t in tasks]

        pull = _find_task(root, env, "Pull all images")
        # A pure pull: the pull-only module, and never the up module.
        assert "community.docker.docker_compose_v2_pull" in pull, pull
        assert "community.docker.docker_compose_v2" not in pull, pull
        # No service-starting `state:` anywhere in the pull task's args.
        assert "state" not in pull["community.docker.docker_compose_v2_pull"], pull

        # The stack comes up only at the up task, which keeps `state: present`.
        up = _find_task(root, env, "Bring up the stack")
        assert up["community.docker.docker_compose_v2"]["state"] == "present", up

        # Ordering: pull -> migrate -> up. The up task must follow the migrate
        # task; otherwise new code would serve against an unmigrated schema.
        pull_i = names.index("Pull all images")
        migrate_i = names.index("Run migrations for api")
        up_i = names.index("Bring up the stack")
        assert pull_i < migrate_i < up_i, names
```

Note: the sample fixture's schema-owning codebase is `api` (the existing
`_find_migration_task(root, env, "api")` calls confirm the "Run migrations for
api" task name). If the fixture changes, adjust the migrate task name.

## Step 4 — Update the doctrine known-divergence note

File: `doctrine/infrastructure/specifics/migrations.md`, § Stage and Prod on
Fixed Foundation, the blockquote that currently begins
`> **⚠ Known divergence — the emitted playbook does not currently do this.**`.

Replace that entire blockquote with a note recording that mod 144 fixed the
emitter and that real-machine verification is still pending. Do NOT delete it;
soften it. Keep the link to
`008_housekeeping/references/fixed_release_migrates_after_up.md`. New text:

```markdown
> **✔ Fixed by mod 144 — pending walk verification.** The emitter previously
> pulled images with a compose module argument that also *started* the stack, so
> the real fixed ordering was **up → migrate** and the abort guarantee above did
> not hold (found by advance 006's fixed smoke walk). Mod 144 changed the "Pull
> all images" task to a pure pull (`community.docker.docker_compose_v2_pull`), so
> the stack now comes up only after migration, at the "Bring up the stack" task —
> the ordering this section describes. Real-machine verification is still
> **pending** an operator-supervised fixed smoke walk (compare container
> `StartedAt` against migration completion; confirm the clock's first fire on a
> first release raises no `UndefinedTable`); a green playbook exit code does not
> prove the ordering. See [`fixed_release_migrates_after_up.md`](../../../docex/plans/advances/008_housekeeping/references/fixed_release_migrates_after_up.md).
```

## Step 5 — Run the suites (foreground, synchronous)

From `docex/`:

1. `.venv/bin/python -m pytest tests -q`
   Expect the default count to rise by 1 over the post-143 baseline
   (`1253 passed, 21 deselected` → `1254 passed, 21 deselected`). Nothing red.
2. `.venv/bin/python -m pytest tests -q -m integration`
   Expect `21 passed, 1253 deselected` (unchanged; this mod touches only the
   ansible emitter template + unit test).

Both must be green before returning.

## Step 6 — Linkcheck

From repo root, run the doctrine linkcheck. Confirm green. Any broken-file
reports scoped to operator WIP (`RELEASING.md`, `docex/plans/advances/floating_todo/`,
`docex/plans/advances/009_test_overhaul/`) are pre-existing and NOT to be touched —
report them, do not fix them.

## Out of scope / do NOT do

- Do NOT run `docex release`, any smoke walk, or anything against real infra.
- Do NOT touch `RELEASING.md`, `floating_todo/`, or `009_test_overhaul/`.
- Do NOT update core planning docs (that is the mod cycle's later documentation
  step, done by the C.O., not the implementor).
- Do NOT commit (the C.O. handles commits).

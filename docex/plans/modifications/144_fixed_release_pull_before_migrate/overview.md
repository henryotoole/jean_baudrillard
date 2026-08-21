# Mod 144 — Fixed release must pull-without-starting before migrating

## Goal

Make the emitted fixed-foundation release playbook honor the ordering the
doctrine promises: **pull (no start) → migrate (old containers still serving) →
up**. Today the "Pull all images" task starts the whole stack, so the real order
is **up → migrate** and the documented abort guarantee (a failed migration
aborts before the new code goes live) is void.

## Problem

`docex/src/docex/emit/templates/playbook.yml.j2` renders the "Pull all images"
task as:

```yaml
- name: Pull all images
  community.docker.docker_compose_v2:
    project_src: "{{ deploy_root }}"
    project_name: "{{ compose_project_name }}"
    pull: always
    state: present          # <-- brings the whole stack UP
```

`state: present` on `docker_compose_v2` converges the stack to running — it does
not merely pull. Because this task precedes the per-codebase migrate task, the
new code is live against the unmigrated schema before `migrate.sh` runs, and the
later "Bring up the stack" task is a no-op. A failed migration therefore leaves
the new code up against a schema that never moved — the exact scenario the
ordering exists to prevent.

Design record: `docex/plans/advances/008_housekeeping/references/fixed_release_migrates_after_up.md`.

## Design

### 1. Pull without starting

Replace the `docker_compose_v2` (`state: present`) pull task with
`community.docker.docker_compose_v2_pull`, a module that pulls images and starts
nothing. It is available in the pinned collection (`community.docker==3.10.4` in
`docex/Dockerfile`; `docker_compose_v2_pull` was added in 3.6.0), so this is the
cleaner of the two options in the brief (the alternative was `docker compose
pull` via `ansible.builtin.command`). It keeps the same `project_src` /
`project_name` and adds `policy: always` (the pull-always intent the old `pull:
always` carried).

The stack then comes up **only** at the existing "Bring up the stack" task
(`docker_compose_v2`, `state: present`), which runs after the migrate task. Final
emitted task order:

1. Ensure deploy directory
2. Render docker-compose.yml
3. Render TTE store
4. Render .env
5. **Pull all images** (`docker_compose_v2_pull` — no start)
6. **Run migrations for `<codebase>`** (per schema owner)
7. **Bring up the stack** (`docker_compose_v2`, `state: present`)

### 2. Tests

- **New** `test_playbook_pull_task_starts_nothing`: assert the "Pull all images"
  task uses `community.docker.docker_compose_v2_pull` (a pure pull) and carries
  **no** service-starting `state:` — i.e. it is not a `docker_compose_v2` with
  `state: present`. Also assert the "Bring up the stack" task still carries
  `state: present` and that its index in the task list is **after** the migrate
  task's index. This is the assertion the brief calls for: a green/valid-YAML
  playbook proves nothing; the defect lived entirely in the meaning of one module
  argument.
- **Update** the existing `test_playbook_compose_tasks_are_project_scoped`: it
  currently reads the pull task's `project_name` under the
  `community.docker.docker_compose_v2` key, which the module change moves to
  `community.docker.docker_compose_v2_pull`. Repoint that one assertion so the
  suite stays green (the mod 090 project-scoping guarantee is preserved on the
  new module).

### 3. Doctrine note

`doctrine/infrastructure/specifics/migrations.md § Stage and Prod on Fixed
Foundation` carries a ⚠ Known-divergence note stating the emitted playbook does
**not** do this and that a fixed stage/prod release is "not protected." This mod
makes that premise false. Soften the note (do not delete it) to record that mod
144 fixed the emitter and that real-machine verification is **pending** an
operator-supervised fixed smoke walk. The link to
`008_housekeeping/references/fixed_release_migrates_after_up.md` stays.

## The deferred gate (PENDING)

This mod lands the emitter edit + unit test only. Its real-machine GATE is a
fixed smoke walk, operator-supervised and **deferred** — NOT run in this cycle.
Verification method (unchanged from the design record): compare each container's
`StartedAt` against the migration's completion time (order must be
migrate-before-up), and assert the clock's first fire on a first release raises
no `UndefinedTable`. A green playbook exit code proves nothing here; the ordering
is only visible in timestamps. Nothing in this cycle runs against real infra.

## Drift check

- Doctrine: `migrations.md` note — softened (above).
- `docex/plans/core/release_flow.md`: its fixed-flow prose (§ Fixed-foundation
  flow) and "four sequences" table already describe fixed as pull → render →
  migrate → up (the intended order) and never imply the pull task starts the
  stack. After this fix the template matches the doc — confirmed consistent, no
  edit. `masterplan.md` does not describe the playbook task order — no edit.
- Transfer tables: none. src: `emit/templates/playbook.yml.j2` (task assembled in
  the template; `emit/ansible.py` builds the `migrations` list only, no change).
  tests: `tests/unit/test_ansible_emitter.py`.
- `doctrine_excerpts/index.yml`: playbook/migrations are not excerpted resources —
  confirmed no resource change.
- Skill `cicd-pipeline`: routes to `migrations.md` (§ heading unchanged by the
  note edit) — pointer still resolves; not edited.

## Design questions

None. The brief fully specifies intent and scope; the one open choice
(`docker_compose_v2_pull` vs `command: docker compose pull`) resolves cleanly to
the module because the pinned collection carries it.

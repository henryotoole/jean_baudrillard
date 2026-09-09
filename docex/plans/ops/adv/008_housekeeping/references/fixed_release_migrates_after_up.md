# The fixed release playbook starts the stack before migrating

`migrations.md § Stage and Prod on Fixed Foundation` promises the ordering
render configs → **migrate (old containers still serving)** → start the new
stack, and the guarantee that a failed migration aborts *before*
`docker compose up -d`, leaving the old containers serving.

The emitted playbook does the opposite. In `emit/templates/playbook.yml.j2` the
task named "Pull all images" is a `community.docker.docker_compose_v2` call with
**`state: present`**, which brings the whole stack **up** — and it runs before
the migration task. So the real ordering is **up → migrate**: the new code is
live against the old, unmigrated schema, and the later "Bring up the stack" task
is a no-op. The documented abort guarantee is void — a failed migration leaves
the new code up and serving against a schema that never moved, the exact scenario
the ordering exists to prevent, and a direction the
`§ Backward Compatibility Requirement` does not cover (it obliges migrations to
be compatible with the *previous* app version, not new code against an unmoved
schema).

`migrations.md` carries a known-divergence note (`§ Stage and Prod on Fixed
Foundation`) pointing here; retire it when this is fixed.

## Changes to make

1. Make the "Pull all images" task a real pull that does **not** start services —
   `community.docker.docker_compose_v2_pull`, or `docker compose pull` via
   `ansible.builtin.command`. The stack then comes up only at the existing "Bring
   up the stack" task, after migration.
2. Add a test asserting the pull task carries no service-starting `state:`.
   `tests/unit/test_ansible_emitter.py` currently asserts only `project_name` on
   those tasks — the defect lives entirely in the meaning of one module argument,
   so a valid-YAML/green-playbook check proves nothing.

## Verify with the walk, not the playbook exit code

The fix and its smoke walk must land together — a green playbook proves nothing
here; the ordering is only visible in timestamps. Verify by the method that found
it: compare `StartedAt` across the stack against the migration's completion time,
and assert the clock's first fire on a first release does **not** raise
`UndefinedTable`.

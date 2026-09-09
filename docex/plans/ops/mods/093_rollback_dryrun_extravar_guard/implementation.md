# Mod 093 — Implementation

## Step 1 — Guard the render tasks (`src/docex/emit/templates/playbook.yml.j2`)

Add a `when` guard to each extra-var-dependent render task.

- "Render TTE store onto host" (copy `src: "{{ tte_store_file }}"`): add
  `when: tte_store_file is defined`.
- "Render .env onto host" (copy `src: "{{ agg_env_file }}"`): add
  `when: agg_env_file is defined`.

Write the `when:` line as literal YAML in the template (no docex-Jinja braces —
`tte_store_file` / `agg_env_file` are ansible runtime vars, resolved at play
time, so they render verbatim like the existing `changed_when: true`).

No change to `emit/ansible.py` (no new compile-time context var).

## Step 2 — Regression test (`tests/unit/test_ansible_emitter.py`)

Add `test_playbook_env_render_tasks_guarded_for_dryrun`: compile the fixture,
load the stage playbook, find "Render TTE store onto host" and "Render .env onto
host" via the existing `_find_task` helper, and assert each carries
`when == "<var> is defined"`. This proves a dry-run (`--check` with no extra-vars)
skips them instead of failing on an undefined variable.

## Step 3 — Verify

- `pytest tests/unit/test_ansible_emitter.py` green.
- Full `pytest` (unit) green — no other test asserts the tasks are unguarded.
- Rebuild `docex:1.5.0`, repin the fixed smoke project, and confirm
  `docex rollback prod <prior> --dry-run` exits 0 with
  `release: prod dry-run completed (ansible --check).`, and that a real
  `docex rollback` still succeeds (render tasks still run).

## Changelog

Add a bullet under the 1.5.0 `### Fixed` section naming the regression and the
`when`-guard fix (surfaced by the pre-cut fixed smoke walk).

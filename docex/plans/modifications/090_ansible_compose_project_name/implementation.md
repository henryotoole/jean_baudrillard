# Mod 090 — Implementation steps

Docex root: `~/.claude/jean_baudrillard/docex`. Repo root: `~/.claude/jean_baudrillard`.

## 1. Emit the scoped name

`src/docex/emit/ansible.py`, in `emit_ansible`'s `playbook_tpl.render(...)` call,
add:

```python
compose_project_name=f"{compiled.project_dns_label}-{compiled.env}",
```

(`CompiledEnv.project_dns_label` already exists — compile.py:464.)

## 2. Template

`src/docex/emit/templates/playbook.yml.j2`:

- "Pull all images" `docker_compose_v2`: add `project_name: "{{ compose_project_name }}"`.
- "Bring up the stack" `docker_compose_v2`: add `project_name: "{{ compose_project_name }}"`.
- "Run migrations" command: change to
  `cmd: docker compose -p {{ compose_project_name }} run --rm {{ svc.global_name }} /service/migrate.sh`

`compose_project_name` is a compile-time jinja value → plain `{{ compose_project_name }}`
(not the `{{ '{{' }}` ansible-runtime escaping).

## 3. Unit test

`tests/unit/test_ansible_emitter.py`: add/extend a test asserting the emitted
`playbook.yml` (for a fixed stage or prod env, project e.g. `sample`) contains:
- `project_name: sample-<env>` (or `"sample-<env>"`) on the compose tasks, and
- `docker compose -p sample-<env> run --rm` on the migrate task.
Assert the unscoped bare `project_name: <env>` does NOT appear.

## 4. Upgrade guide

`upgrades/upgrade_1.5.0.md`: add a short section (before or after Rollback) —
"Fixed stage/prod Compose stack rename (mod 090)": on the first 1.5.0 release of
an existing fixed deployment, the stage/prod Compose project is renamed from
`<env>` to `<dns_label>-<env>`; because container names are explicit, the new
`up` collides with the old-named stack. One-time fix before the first 1.5.0
release per env: `docker compose -p <env> -f /opt/<project>/<env>/docker-compose.yml down`
(keeps named volumes). New/greenfield deployments need nothing.

## 5. Verify

From `~/.claude/jean_baudrillard/docex`:
```
python3 -m pytest tests/unit/test_ansible_emitter.py -q
python3 -m pytest -q     # full unit suite green; not -m integration
```
Driver additionally does a live fixed stage re-verify (compose project label ==
`docex-smoke-fixed-stage`), then tears down.

Do NOT touch version artifacts or CHANGELOG (driver handles at re-roll).

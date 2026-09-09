# Mod 095 — Implementation Steps

Executes the design in [`overview.md`](./overview.md). Read that first; it carries
the *why*. This file is the *what*, written to be handed to a fresh context.

All paths are relative to the repo root `/home/ubuntu/.claude/jean_baudrillard`.
The `docex` package root is `docex/`.

**Scope discipline.** This mod is purely additive. Do **not** build anything
`processes:`-shaped, do not touch `replicas`, do not touch any version artifact
(`VERSION`, `CHANGELOG.md`, `docex/pyproject.toml`, `docex/src/docex/__init__.py`),
and do not edit `doctrine/infrastructure/specifics/transfer_tables.md` — the
`worker` role and the `container_definition` destination are documented there by
Mod 106, deliberately deferred until the code exists.

**Working tree.** The tree is dirty with a pre-existing, already-staged
`campaigns/` → `advances/` rename that is not part of this mod. Do not commit,
revert, stage, unstage, or otherwise disturb it.

---

## Step 1 — Doctrine: `cicl.md` validation rule 28

**Already applied during design.** Verify it is present and do not re-apply.

`doctrine/infrastructure/cicl.md`, § Validation Rules, immediately after rule 27:

```
28. Every process type that declares `health_check_path` also declares a `port`. The path is only meaningful against a port — the probe is issued at `http://localhost:<port><path>` — and no role fixes a default health port, deliberately: an implicit one would silently oblige the application to bind it. Without this rule the omission emits a malformed probe and surfaces as a container that never becomes healthy, rather than as a compile error.
```

This is the **only** doctrine edit in this mod. It is phrased in process-type
terms even though Step 5's code enforces it on flat services, because the
doctrine has described process types since Mod 094; Mod 096 re-scopes it onto the
process type along with rules 10/12/14/15/16.

---

## Step 2 — New role table: `docex/tables/roles/worker.yml`

Create the file with exactly this content.

```yaml
# Role: worker
#
# Core service process type — long-running, event-driven, never publicly
# routed. Canonically a queue consumer; a stream processor or polling loop
# fits the same shape. Shares its codebase and image with sibling process
# types.
#
#   - fixed:   one compose service on the codebase's image with the process
#              type's `command`.
#   - elastic: task_definition + ecs_service. NO target_group — a worker is
#              not an ingress target.
#
# `image:`, `cpu:`, `memory:`, `tmpfs:` are derived per-process by the
# compiler, exactly as for `web`.

roles:
  worker:
    description: "Core service process — long-running, event-driven, not publicly routed."
    container:
      foundation: both
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service, container_definition]
      defaults:
        fixed: {}
        elastic:
          launch_type: FARGATE
          network_mode: awsvpc
      fields:
        health_check_path:
          fixed:
            healthcheck:
              test: ["CMD", "curl", "-f", "http://localhost:${port}${field_value}"]
              interval: 30s
              timeout: 5s
              retries: 3
          elastic:
            # NOT target_group — a worker has none. Routes to the ECS
            # container-level healthCheck, so a wedged consume loop gets the
            # task killed and replaced by the service.
            target: container_definition
            healthCheck:
              command: ["CMD-SHELL", "curl -f http://localhost:${port}${field_value} || exit 1"]
              interval: 30
              timeout: 5
              retries: 3
              startPeriod: 10
      provides:
        # A worker that declares a `port` registers as Service-Connect-
        # discoverable on elastic (shape.md § service_discovery), which is what
        # lets a sibling `web` process reach its /health one hop away.
        host:
          fixed: "${global_service_name}"
          elastic: "${global_service_name}"
        port:
          fixed: "${port}"
          elastic: "${port}"
      env: {}
      naming: ecs
```

Properties that are load-bearing and must not drift:

- Engine key is `container`, matching `web.yml` and `scheduler.yml`.
  `compile.py:513-520` picks the first foundation-supporting engine of the role.
- `task_definition` is **first** in `emits.elastic`, which makes it the engine's
  default target (`EngineEntry.default_target`, `transfer.py:179-194`), so
  `defaults.elastic` lands there — same as `web`.
- **No `target_group`.**
- **No `default_port`.** Do not add one.
- The fixed `health_check_path` translation declares no `target:`, so it routes
  to the default target (`compose_service`) and deep-merges into the compose
  service body, exactly as `web`'s does.

---

## Step 3 — `container_definition` as an emit destination

`docex/src/docex/cicl/transfer.py`, `EMIT_DESTINATIONS` at `:83-95`. Add the
destination to the `elastic` set:

```python
        "scheduled_task",  # Mod 055
        # Mod 095: not a resource of its own — a *merge target*. The
        # translation body is merged into the app container's JSON inside
        # `render_task_definition`. See emit/hcl.py.
        "container_definition",
```

Leave the block comment above `EMIT_DESTINATIONS` as it is; Steps 4 and 5 are
exactly the routing-layer growth it demands.

---

## Step 4 — `emit/hcl.py`: the no-op renderer and the merge

All in `docex/src/docex/emit/hcl.py`.

### 4a. The merge into `container_def`

`render_task_definition` (`:311-540`). Insert **after** the
`environment`/`secrets` assignments (currently `:348-351`) and **before** the
`dockerLabels` block that begins with the `# Mod 070:` comment (currently `:353`):

```python
    # Mod 095: transfer-table fields routed to the `container_definition`
    # destination land here — today that is the `worker` role's
    # health_check_path -> ECS container-level `healthCheck`. Mirrors how
    # render_target_group reads target_extras["target_group"].
    #
    # WHY this position: it sits after `environment`/`secrets` but ahead of
    # the dockerLabels / mountPoints / dependsOn whole-key assignments below,
    # which therefore win over anything a table supplies. That precedence is
    # intended — traefik labels, EFS mounts, and the sidecar dependsOn are
    # compiler-owned invariants, not table-overridable.
    container_def.update(svc.target_extras.get("container_definition", {}))
```

Use `.update()`, not a deep merge: the destination's contract is whole-key
replacement, matching `render_target_group`'s `tg_extras.get("health_check")`
read at `:631`.

**Do not** apply the extras to the migration container built at `:503-538`. It
runs `/service/migrate.sh` and exits without ever binding the health port; it is
`essential: true`, so an ECS healthCheck against a dead port would turn every
elastic migration into a kill loop. This matches the container's existing,
deliberate omission of every long-running-only key (`portMappings`,
`dockerLabels`, `mountPoints`, `dependsOn`, the paired sidecar — see the comment
at `:396-408`).

### 4b. Register the no-op renderer

Add above `_DESTINATION_RENDERERS` (`:927-936`):

```python
def render_container_definition(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit nothing. `container_definition` is a MERGE TARGET, not a resource.

    Mod 095. Fields routing to this destination modify the app container's
    JSON inside `render_task_definition` (which reads
    `svc.target_extras["container_definition"]`); there is no HCL block of
    its own to emit. It is registered here anyway because
    `_DESTINATION_RENDERERS` is the dispatch loop's lookup table — an
    unregistered destination falls into `render_service`'s defensive branch
    and writes a `# unknown destination` comment into the output. Registering
    it also satisfies transfer-table validation rule 12 (a field's `target:`
    must appear in the engine's `emits.<foundation>`) without a second
    resource appearing in the plan.
    """
    return ""
```

and the table entry:

```python
    "scheduled_task": render_scheduled_task,  # Mod 055
    "container_definition": render_container_definition,  # Mod 095 (merge target)
```

### 4c. Skip empty renderer output

In `render_service` (`:962-993`), the dispatch loop currently appends the
renderer's result and a blank line unconditionally. Make it skip an empty
result:

```python
        rendered = renderer(svc_view, ctx)
        if not rendered.strip():
            # A merge-target destination (Mod 095's container_definition)
            # emits no resource of its own — don't leave a blank gap in the
            # output for it.
            continue
        parts.append(rendered)
        parts.append("")
```

Harmless today only because `container_definition` sits last in the worker's
emits list; the output should not depend on that ordering.

**Do not** add `container_definition` to `_destination_applicable` (`:939-959`).
That function answers "is this destination *conditionally* emittable for this
service" — `container_definition` is never independently emittable, which is a
property of the destination rather than of the service.

**Do not** add `container_definition` to `_BODY_TAG_DESCRIPTOR`
(`compile.py:858-863`). Its absence is correct: the descriptor picker at
`compile.py:882-886` walks `elastic_dests` in order and finds `ecs_service`
first, yielding `ecs-svc` for a worker, exactly as for `web`.

---

## Step 5 — `cicl/validate.py`: rule 28

`docex/src/docex/cicl/validate.py`.

Add a validator near `_validate_web_service_ports` (rule 15's, around `:455-470`)
or at the end alongside the other per-rule functions — placement is free, but
keep the section comment style of its neighbours:

```python
def _validate_health_check_path_port(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 28 (Mod 095): declaring ``health_check_path`` obliges a ``port``.

    The path is only meaningful against a port — every role's translation
    probes ``http://localhost:${port}${field_value}``. No role declares a
    ``default_port`` (deliberately: an implicit health port would silently
    oblige the application to bind it), so an omitted ``port`` substitutes
    to the empty string and emits a malformed probe that surfaces as a
    container which never becomes healthy instead of as a compile error.

    Role-agnostic on purpose. It is vacuous for ``web``, whose port is
    already required by rule 15 for any web-network service, and it must
    stay that way rather than being special-cased per role.
    """
    issues: list[ValidationIssue] = []
    for name, svc in sorted(doc.core_services.items()):
        if (svc.model_extra or {}).get("health_check_path") is None:
            continue
        if svc.port is None:
            issues.append(ValidationIssue(
                rule="rule_28_health_check_path_needs_port",
                message=(
                    f"core service {name!r} declares `health_check_path` but "
                    f"no `port`. The health probe is issued at "
                    f"http://localhost:<port><path>, so the path is "
                    f"meaningless without one, and no role supplies a default "
                    f"health port. See cicl.md § Validation Rules rule 28."
                ),
                where=f"core_services.{name}.port",
            ))
    return issues
```

Register it in `validate_document` (`:65-93`), appended after
`_validate_scheduler_services(doc)`:

```python
    issues.extend(_validate_health_check_path_port(doc))
```

Notes:

- Core services only. `health_check_path` is a core-service role field, and the
  doctrine rule is phrased about process types.
- Read the field off `svc.model_extra` — it is a role-specific field, not a
  declared model attribute. `_validate_scheduler_services` (`:880-923`) reads
  `schedule` the same way.
- Do **not** widen this to backing services, and do **not** add a role filter.

---

## Step 6 — Tests

### 6a. Delete the dead file

`git rm docex/tests/unit/test_roles.py` — it is 0 bytes and reads as "roles are
tested" to anyone grepping. (Use an explicit path; do not touch other files.)

### 6b. New file: `docex/tests/unit/test_worker_role.py`

Unit tests only — nothing here crosses docker, AWS, or git, so no
`@pytest.mark.integration`.

**Fixtures are not modified.** Copy `docex/tests/fixtures/sample_project` (fixed)
and `sample_project_elastic` into `tmp_path` and inject a `worker` core service
into the copy's `infra/infra.yml` before compiling. Rationale: adding a permanent
service to the shared fixtures would churn unrelated emitter tests, and Mod 096
rewrites all four fixtures anyway.

Model the copy/compile helpers on `docex/tests/unit/test_scheduler.py:27-38`:

```python
def _copy(fixture: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest
```

Then a helper that injects the worker and compiles:

```python
_WORKER = {
    "role": "worker",
    "command": ["python", "-m", "entrypoints.worker"],
    "port": 8090,
    "networks": ["internal"],
    "health_check_path": "/health",
    "depends_on": ["appdb"],
    "resources": {"cpu": 0.5, "memory": "1GB", "disk": 25},
}
```

- Write it under `core_services.worker` in the copied `infra.yml` via
  `yaml.safe_load` → mutate → `yaml.safe_dump`.
- Give the elastic copy a `disk` that satisfies the Fargate ephemeral-storage
  minimum; the elastic fixture's own `api` uses `25GB`, so mirror that form
  (`"25GB"`). Drop `disk` entirely on the fixed copy if it is simpler — it is
  optional there.
- Create the codebase folder the compose `build:` context points at:
  `mkdir -p <dest>/core/worker` with a trivial `Dockerfile`, mirroring
  `core/api/`. Copy `core/api/Dockerfile` if that is easiest.
- Compile with `run_compile(load_project_context(root))`.

Required tests:

| # | Name (suggested) | Asserts |
| - | ---------------- | ------- |
| 1 | `test_worker_role_table_shape` | `load_transfer_tables(project_root=None)` exposes role `worker`, engine `container`; `emits["fixed"] == ["compose_service"]`; `emits["elastic"] == ["task_definition", "ecs_service", "container_definition"]`; `"target_group" not in emits["elastic"]`; `default_port is None`; `set(provides) == {"host", "port"}`; `naming == "ecs"`; `foundation == "both"` |
| 2 | `test_worker_fixed_compose_healthcheck` | dev `docker-compose.yml` has the worker's compose service; its `healthcheck.test` is the substituted `["CMD", "curl", "-f", "http://localhost:8090/health"]`; `interval == "30s"`, `retries == 3`; the service carries the project image and the declared `command` |
| 3 | `test_worker_fixed_no_traefik_labels` | the worker's compose `labels` carry no `traefik.*` key (it is not on the `web` network) |
| 4 | `test_worker_elastic_container_healthcheck` | stage HCL contains `aws_ecs_task_definition "worker"` and `aws_ecs_service "worker"`; the **app** container's JSON carries `healthCheck` with the substituted `curl -f http://localhost:8090/health \|\| exit 1`, `interval` 30, `timeout` 5, `retries` 3, `startPeriod` 10 |
| 5 | `test_worker_elastic_no_target_group` | no `aws_lb_target_group "worker"` and no `aws_lb_listener_rule "worker"` in the stage HCL (the `api` service's own target group must still be there — assert its presence too, so the test cannot pass by the HCL being empty) |
| 6 | `test_worker_elastic_sidecar_has_no_healthcheck` | the paired `worker-otelcol` container definition carries no `healthCheck` key — the merge must land on the app container only |
| 7 | `test_container_definition_emits_no_resource` | the stage HCL contains no `# unknown destination` comment, and no resource block whose type is `container_definition`-derived; a simple form is to assert `"unknown destination" not in hcl` |
| 8 | `test_field_target_container_definition_undeclared_rejected` | a role whose field declares `target: container_definition` while its `emits.elastic` omits it yields a `FIELD_TARGET_UNDECLARED` issue from `validate_document`. Mirror the existing pattern at `docex/tests/unit/test_validate.py:394-423` |
| 9 | `test_health_check_path_without_port_rejected` | a core service declaring `health_check_path` and no `port` yields `rule_28_health_check_path_needs_port` |
| 10 | `test_health_check_path_with_port_passes` | the same doc with `port:` present yields no rule-28 issue |
| 11 | `test_web_service_unaffected_by_rule_28` | the unmodified `sample_project` fixture document produces no `rule_28_health_check_path_needs_port` issue (rule 28 stays vacuous for existing projects) |

For tests 8-11, build documents inline with
`CICLDocument.model_validate(yaml.safe_load(src))` and call
`validate_document(doc, tables)` — the pattern at
`docex/tests/unit/test_scheduler.py:287-337`. That avoids a fixture round-trip
for pure validation checks.

### 6c. Run the suite

```
cd docex && python -m pytest tests/unit -q
```

Must be **green**. Report the actual result — pass/fail counts — honestly. Do not
mark integration tests; do not run `pytest -m integration` (that is step 3 of
`docex_process.md`, outside this mod).

---

## Step 7 — Do not commit

Leave the working tree dirty. The mod driver handles both commits with an
explicit pathspec so the pre-existing staged `campaigns/` → `advances/` rename is
never swept in. Report what you changed and the test result.

---

## Acceptance checklist

- [ ] `cicl.md` rule 28 present; no other doctrine file touched.
- [ ] `docex/tables/roles/worker.yml` created, no `target_group`, no `default_port`.
- [ ] `container_definition` in `EMIT_DESTINATIONS["elastic"]`.
- [ ] `render_container_definition` registered, returns `""`, docstring explains why.
- [ ] `render_service` skips empty renderer output.
- [ ] `container_def.update(...)` placed between the `secrets` assignment and the `dockerLabels` block; migrate container untouched.
- [ ] `_validate_health_check_path_port` added and registered in `validate_document`.
- [ ] `docex/tests/unit/test_roles.py` deleted.
- [ ] `docex/tests/unit/test_worker_role.py` added with all 11 tests.
- [ ] Shared fixtures under `docex/tests/fixtures/` unmodified.
- [ ] Full unit suite green.
- [ ] No version artifact touched; `transfer_tables.md` untouched; nothing `processes:`-shaped built.

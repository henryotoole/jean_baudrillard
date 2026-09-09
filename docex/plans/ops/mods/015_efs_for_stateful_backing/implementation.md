# Mod 015 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Implement EFS support for stateful container-backing services on Fargate. Five surfaces touch:

1. `_ALLOWED_ENGINE_KEYS` gains `persistent_storage`.
2. `EMIT_DESTINATIONS["elastic"]` gains `efs_file_system`.
3. `EngineEntry` and `CompiledService` carry a `persistent_storage` field through to the emitter.
4. New per-destination renderer `render_efs_file_system` (emits `aws_efs_file_system` + `aws_efs_mount_target` per private subnet; conditionally `aws_efs_backup_policy` when `backups: true`).
5. `render_task_definition` extends its emitted task-def with `volume` + `mountPoints` when the service declares `persistent_storage`.

Plus bidirectional validation: `persistent_storage` ↔ `efs_file_system` must agree. Either declared without the other is a load-time error.

The doctrine edits for this mod are already landed in `transfer_tables.md` (new "Persistent storage on Fargate" section + field-reference entry). No further doctrine edits.

## Step 1 — Extend schema constants

File: `src/docex/cicl/transfer.py`.

Add `efs_file_system` to `EMIT_DESTINATIONS["elastic"]`:

```python
EMIT_DESTINATIONS: dict[str, frozenset[str]] = {
    "fixed": frozenset({"compose_service"}),
    "elastic": frozenset({
        "task_definition",
        "ecs_service",
        "target_group",
        "rds_instance",
        "elasticache_cluster",
        "s3_bucket",
        "efs_file_system",  # Mod 015
    }),
}
```

Add `persistent_storage` to `_ALLOWED_ENGINE_KEYS`:

```python
_ALLOWED_ENGINE_KEYS: frozenset[str] = frozenset({
    "foundation",
    "default_port",
    "emits",
    "defaults",
    "fields",
    "provides",
    "env",
    "naming",
    "reserved_names",
    "persistent_storage",  # Mod 015
})
```

## Step 2 — Add `persistent_storage` to `EngineEntry`

Same file. Add the field to the `EngineEntry` dataclass (near `reserved_names`/`emits`):

```python
# Optional declaration that this engine needs a durable data directory.
# Shape: ``{"mount_path": "/var/lib/clickhouse"}``. When set, the engine
# MUST also include ``efs_file_system`` in ``emits.elastic`` (the
# loader enforces this bidirectional invariant). On elastic, the
# compiler emits the EFS plumbing; on fixed, the field is
# informational — engines declare their docker volume in
# ``defaults.fixed.volumes`` themselves. Mod 015.
persistent_storage: dict[str, Any] | None = None
```

In `_parse_entry`, pass it through to the constructor:

```python
return EngineEntry(
    ...
    persistent_storage=raw.get("persistent_storage"),
)
```

## Step 3 — Bidirectional validation

In `_validate_engine_entry`, after the existing checks, add:

```python
# Bidirectional invariant: persistent_storage <-> efs_file_system in
# emits.elastic. Either declared alone is a load-time error. Mod 015.
has_persistent_storage = "persistent_storage" in raw
elastic_emits = raw.get("emits", {}).get("elastic", [])
has_efs_destination = isinstance(elastic_emits, list) and "efs_file_system" in elastic_emits

if has_persistent_storage and not has_efs_destination:
    raise TransferTableError(
        f"{display_path}: roles.{role}.{engine}: declares "
        f"`persistent_storage` but `emits.elastic` does not include "
        f"`efs_file_system`. Stateful container-backing engines must "
        f"declare both."
    )
if has_efs_destination and not has_persistent_storage:
    raise TransferTableError(
        f"{display_path}: roles.{role}.{engine}: declares "
        f"`emits.elastic: [..., efs_file_system]` but no "
        f"`persistent_storage` field. The EFS destination needs a "
        f"`persistent_storage.mount_path` to mount the filesystem into "
        f"the container."
    )

# Per-file validation of persistent_storage shape (when present).
if has_persistent_storage:
    ps = raw["persistent_storage"]
    if not isinstance(ps, dict):
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}.persistent_storage: "
            f"must be a mapping"
        )
    if "mount_path" not in ps or not isinstance(ps["mount_path"], str) or not ps["mount_path"]:
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}.persistent_storage: "
            f"requires a non-empty `mount_path` (got {ps.get('mount_path')!r})"
        )
```

## Step 4 — Plumb through `CompiledService`

File: `src/docex/cicl/compile.py`.

Add the field to `CompiledService` (near `emits` or `target_extras`):

```python
# Engine-declared persistent storage spec (e.g.
# ``{"mount_path": "/var/lib/clickhouse"}``). None when the engine
# doesn't declare it. Mod 015.
persistent_storage: dict[str, Any] | None = None
```

In the `CompiledService(...)` construction loop in `compile_env`, pass `persistent_storage=engine.persistent_storage`. Source the engine the same way `emits=dict(engine.emits)` was added in Mod 013.

## Step 5 — `render_efs_file_system`

File: `src/docex/emit/hcl.py`. Add a new per-destination renderer alongside the others (after `render_s3_bucket`, before `_DESTINATION_RENDERERS`):

```python
def render_efs_file_system(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_efs_file_system`` + per-private-subnet
    ``aws_efs_mount_target`` for a stateful container-backing service.
    Emits ``aws_efs_backup_policy`` only when the service's
    ``target_extras["efs_file_system"]["enabled"]`` is truthy
    (project-opt-in via ``backups: true`` in infra.yml). Mod 015.
    """
    # Mount targets attach to the service's non-`web` SGs. The
    # `internal` SG's self-ingress rule already covers NFS port 2049
    # for tasks on that SG. We never put EFS on the public `web` plane.
    sg_nets = [n for n in sorted(svc.networks) if n != "web"]
    sg_refs = ", ".join(f"aws_security_group.{n}.id" for n in sg_nets)

    out: list[str] = []
    out.append(f'resource "aws_efs_file_system" "{svc.name}" {{')
    out.append(f'  creation_token   = "{svc.global_name}"')
    out.append( '  encrypted        = true')
    out.append( '  performance_mode = "generalPurpose"')
    out.append( '  throughput_mode  = "bursting"')
    project_tag = svc.body.get("tags", {}).get("project", "")
    env_tag = svc.body.get("tags", {}).get("env", "")
    out.append(
        f'  tags = {{ project = "{project_tag}", env = "{env_tag}", '
        f'service = "{svc.name}", role = "{svc.role}", '
        f'managed_by = "doctrine" }}'
    )
    out.append("}")

    # AWS Backup default plan — project-opt-in via the `backups` field.
    backups_extras = svc.target_extras.get("efs_file_system", {})
    if backups_extras.get("enabled"):
        out.append("")
        out.append(f'resource "aws_efs_backup_policy" "{svc.name}" {{')
        out.append(f'  file_system_id = aws_efs_file_system.{svc.name}.id')
        out.append("  backup_policy {")
        out.append('    status = "ENABLED"')
        out.append("  }")
        out.append("}")

    # One mount target per private subnet so tasks in any AZ can mount.
    out.append("")
    out.append(f'resource "aws_efs_mount_target" "{svc.name}" {{')
    out.append( '  count           = length(data.terraform_remote_state.project.outputs.private_subnet_ids)')
    out.append(f'  file_system_id  = aws_efs_file_system.{svc.name}.id')
    out.append( '  subnet_id       = data.terraform_remote_state.project.outputs.private_subnet_ids[count.index]')
    out.append(f'  security_groups = [{sg_refs}]')
    out.append("}")
    return "\n".join(out)
```

## Step 6 — Register in dispatch table

In `_DESTINATION_RENDERERS`:

```python
_DESTINATION_RENDERERS: dict[str, Callable[[CompiledService, _RenderCtx], str]] = {
    "task_definition": render_task_definition,
    "ecs_service": render_ecs_service,
    "target_group": render_target_group,
    "rds_instance": render_rds_instance,
    "elasticache_cluster": render_elasticache_cluster,
    "s3_bucket": render_s3_bucket,
    "efs_file_system": render_efs_file_system,  # Mod 015
}
```

No new entry in `_destination_applicable` — `efs_file_system` is always applicable when an engine emits to it (the bidirectional validation ensures `persistent_storage` is set whenever `efs_file_system` is in emits).

## Step 7 — Extend `render_task_definition` for volumes + mountPoints

Same file. Inside `render_task_definition`, after the `container_def` is built but before constructing the task-definition `out` list, add the volume/mountPoint wiring when `svc.persistent_storage` is set:

```python
# Mod 015: persistent storage wiring. When the engine declares
# `persistent_storage`, mount the per-service EFS at the declared path
# inside the container. Volume name is the doctrine-fixed handle "data".
task_volumes: list[dict[str, Any]] = []
if svc.persistent_storage:
    mount_path = svc.persistent_storage["mount_path"]
    container_def["mountPoints"] = [{
        "sourceVolume": "data",
        "containerPath": mount_path,
        "readOnly": False,
    }]
    task_volumes.append({
        "name": "data",
        "file_system_id": HCLLiteral(f"aws_efs_file_system.{svc.name}.id"),
        "transit_encryption": "ENABLED",
    })
```

Then, in the `out` list construction (after `execution_role_arn`, before `container_definitions`), emit the `volume` block(s) when `task_volumes` is non-empty:

```python
for vol in task_volumes:
    out.append("  volume {")
    out.append(f'    name = "{vol["name"]}"')
    out.append("    efs_volume_configuration {")
    fs_id = vol["file_system_id"]
    # fs_id is an HCLLiteral — emit unquoted.
    out.append(f'      file_system_id     = {fs_id}')
    out.append(f'      transit_encryption = "{vol["transit_encryption"]}"')
    out.append("    }")
    out.append("  }")
```

The migration task definition's container (sub-emission later in `render_task_definition` for schema-owning core services) does NOT get mountPoints — schema-owning core services don't have `persistent_storage` (they have backing databases). If a future engine somehow declares both, the migration variant could pick up volumes by symmetry — but for now skip to keep the diff small.

## Step 8 — Unit tests for the dispatch + emission

File: `tests/unit/test_emit_dispatch.py` (extend the file created in Mod 013).

Add tests:

```python
def test_efs_file_system_in_emit_destinations():
    """Mod 015: efs_file_system is a registered emit destination."""
    from docex.cicl.transfer import EMIT_DESTINATIONS
    assert "efs_file_system" in EMIT_DESTINATIONS["elastic"]
    # Not on fixed — EFS is an elastic-only concept.
    assert "efs_file_system" not in EMIT_DESTINATIONS["fixed"]


def test_efs_destination_dispatched_to_renderer():
    """Mod 015: render_efs_file_system is registered in the dispatch table."""
    from docex.emit.hcl import _DESTINATION_RENDERERS, render_efs_file_system
    assert _DESTINATION_RENDERERS["efs_file_system"] is render_efs_file_system


def test_render_efs_emits_filesystem_and_mount_target():
    """Mod 015: a stateful svc emits aws_efs_file_system + aws_efs_mount_target."""
    svc = _svc(
        name="clickdb",
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    from docex.emit.hcl import render_efs_file_system
    rendered = render_efs_file_system(svc, _ctx())
    assert 'resource "aws_efs_file_system" "clickdb"' in rendered
    assert 'creation_token   = "proj_stage_clickdb"' in rendered
    assert 'encrypted        = true' in rendered
    assert 'resource "aws_efs_mount_target" "clickdb"' in rendered
    assert 'count           = length(data.terraform_remote_state.project.outputs.private_subnet_ids)' in rendered
    # No backup policy by default — project-opt-in.
    assert "aws_efs_backup_policy" not in rendered


def test_render_efs_emits_backup_policy_when_enabled():
    """Mod 015: backups: true in infra.yml emits aws_efs_backup_policy."""
    svc = _svc(
        name="clickdb",
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    svc.target_extras = {"efs_file_system": {"enabled": True}}
    from docex.emit.hcl import render_efs_file_system
    rendered = render_efs_file_system(svc, _ctx())
    assert 'resource "aws_efs_backup_policy" "clickdb"' in rendered
    assert 'status = "ENABLED"' in rendered


def test_render_efs_mount_target_attaches_to_non_web_sgs():
    """Mod 015: EFS mount targets don't get the public web SG, only internal-class ones."""
    svc = _svc(
        name="clickdb",
        networks=["internal", "web"],  # contrived — sidecar normally only on internal
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    from docex.emit.hcl import render_efs_file_system
    rendered = render_efs_file_system(svc, _ctx())
    # internal SG present, web SG absent.
    assert "aws_security_group.internal.id" in rendered
    # The substring `aws_security_group.web.id` must NOT appear inside
    # the mount target's security_groups list.
    assert "aws_security_group.web.id" not in rendered


def test_task_definition_emits_volume_and_mountpoints_when_stateful():
    """Mod 015: render_task_definition emits volume + mountPoints when persistent_storage is set."""
    svc = _svc(
        name="clickdb",
        emits={"elastic": ["task_definition", "ecs_service", "efs_file_system"]},
    )
    svc.persistent_storage = {"mount_path": "/var/lib/clickhouse"}
    from docex.emit.hcl import render_task_definition
    rendered = render_task_definition(svc, _ctx())
    assert "volume {" in rendered
    assert 'name = "data"' in rendered
    assert "efs_volume_configuration {" in rendered
    assert "file_system_id     = aws_efs_file_system.clickdb.id" in rendered
    assert 'transit_encryption = "ENABLED"' in rendered
    # mountPoints appears inside the container_def JSON.
    assert '"sourceVolume": "data"' in rendered
    assert '"containerPath": "/var/lib/clickhouse"' in rendered


def test_task_definition_without_persistent_storage_has_no_volumes():
    """Stateless services don't get a volume block."""
    svc = _svc()  # no persistent_storage
    from docex.emit.hcl import render_task_definition
    rendered = render_task_definition(svc, _ctx())
    assert "volume {" not in rendered
    assert "efs_volume_configuration" not in rendered
    assert "mountPoints" not in rendered
```

## Step 9 — Unit tests for validation

File: `tests/unit/test_transfer_validation.py` (extend the file created in Mod 012).

```python
def test_persistent_storage_without_efs_destination_fails(tmp_path: Path) -> None:
    """Mod 015: declaring persistent_storage without efs_file_system in emits fails at load."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  analytics_db:\n"
        "    clickhouse:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        "        elastic: [task_definition, ecs_service]\n"  # missing efs_file_system
        "      defaults:\n"
        "        fixed: {image: 'clickhouse/clickhouse-server:24'}\n"
        "        elastic: {image: 'clickhouse/clickhouse-server:24', cpu: '512', memory: '2048'}\n"
        "      persistent_storage:\n"
        "        mount_path: /var/lib/clickhouse\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "persistent_storage" in msg
    assert "efs_file_system" in msg


def test_efs_destination_without_persistent_storage_fails(tmp_path: Path) -> None:
    """Mod 015: declaring efs_file_system in emits without persistent_storage fails at load."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  analytics_db:\n"
        "    clickhouse:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        "        elastic: [task_definition, ecs_service, efs_file_system]\n"  # has destination but no persistent_storage
        "      defaults:\n"
        "        fixed: {image: 'clickhouse/clickhouse-server:24'}\n"
        "        elastic: {image: 'clickhouse/clickhouse-server:24', cpu: '512', memory: '2048'}\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "efs_file_system" in msg
    assert "persistent_storage" in msg


def test_persistent_storage_requires_mount_path(tmp_path: Path) -> None:
    """Mod 015: persistent_storage missing mount_path fails at load."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  analytics_db:\n"
        "    clickhouse:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        "        elastic: [task_definition, ecs_service, efs_file_system]\n"
        "      defaults:\n"
        "        fixed: {image: 'foo'}\n"
        "        elastic: {image: 'foo'}\n"
        "      persistent_storage: {}\n",  # empty
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "mount_path" in msg
```

## Step 10 — Sanity-compile a stateful fixture

If a fixture exists in `tests/fixtures/` for a project with a stateful container-backing engine, compile it and verify the emitted `main.tf`. If no fixture exists, hand-compose one in a unit test (write the YAML to `tmp_path`, run `load_transfer_tables` + `compile_env` + `emit_hcl`, assert on the rendered `main.tf`).

A minimal end-to-end fixture exercising the whole stack would compile something like:

```yaml
# infra.yml fragment
backing_services:
  clickdb:
    role: analytics_db
    engine: clickhouse
    networks: [internal]
    backups: true   # project opts in
```

And confirm the emitted HCL contains:
- One `aws_efs_file_system.clickdb`
- One `aws_efs_backup_policy.clickdb` (because `backups: true`)
- One `aws_efs_mount_target.clickdb` (with `count`)
- The `clickdb` task definition's `volume` block referencing `aws_efs_file_system.clickdb.id`
- The container_def `mountPoints` referencing `"data"` → `/var/lib/clickhouse`

If creating a fixture is heavy, do this as a unit test in `test_emit_dispatch.py` that mocks the inputs.

## Step 11 — Run the suite

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/ -q
python3 -m pytest tests/integration/test_compile.py -q
```

All must pass.

## Step 12 — Leave everything uncommitted

No git commits. Design-context LLM reviews before commit.

## Hand-off report

In ≤250 words:

- Files changed (group: transfer.py, compile.py, hcl.py, test files).
- Test pass counts.
- Any pre-existing test that needed adjusting (likely none — this mod adds capability, doesn't change existing behavior).
- Any decision beyond implementation.md, especially around:
  - Whether the bidirectional validation message naming matched the doctrine prose closely enough.
  - The exact position of the volume block in `render_task_definition`'s output (relative to ephemeral_storage, container_definitions, etc.).
  - Test-fixture conventions for mocking `svc.persistent_storage` and `svc.target_extras["efs_file_system"]["enabled"]`.
- Anything that smelled off.

## Out of scope

- EFS access points.
- EFS lifecycle policies.
- EFS throughput tuning.
- Auto-propagation of `persistent_storage.mount_path` to `defaults.fixed.volumes`. Fixed-side storage stays engine-explicit.
- Stateful migration task defs. Schema-owning core services don't have persistent_storage today; if a future engine declares both, the migration variant would need volume wiring too — out of scope here.
- Operator notice about EFS storage cost in the doctrine. Future resource-sizing doctrine note.

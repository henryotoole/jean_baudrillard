# Mod 015 — EFS for stateful container-backing services on Fargate

## Problem

Mod 013 made stateless container-backing services (sidecars, OTel collectors, anything that doesn't write durable state) renderable on elastic. ClickHouse — the advance's primary motivator — is stateful: it writes to `/var/lib/clickhouse` and expects that data to survive task restarts. Fargate tasks have no persistent disk; `ephemeral_storage` is wiped on every task restart. Without a way to mount durable storage, ClickHouse-on-elastic is structurally non-viable.

The doctrine's elastic shape has no story for persistent container storage today. On fixed, postgres uses docker named volumes; on elastic, postgres uses RDS (a managed AWS service, not a container). The pattern that's missing: a stateful container backing service on Fargate that needs its own data directory to persist.

AWS's mechanism for persistent storage on Fargate is EFS — a regional network filesystem that tasks mount via NFS. The doctrine just needs to wire it up.

## Design

### `persistent_storage` engine field

A new optional engine-level field in transfer tables:

```yml
persistent_storage:
  mount_path: /var/lib/clickhouse
```

The semantics:

- **Declares this engine needs a durable data directory** that survives task restarts.
- **`mount_path`** — the container-side path where the durable storage is mounted (e.g., `/var/lib/clickhouse` for ClickHouse, `/data` for Redis-as-storage).
- **On fixed**: the field is informational only. Engine authors still declare `defaults.fixed.volumes` themselves with the docker named volume (the existing pattern). The doctrine doesn't try to auto-propagate `mount_path` to `defaults.fixed.volumes`; the duplication is small and the explicit declaration keeps the fixed-side reading direct.
- **On elastic**: the compiler reads `persistent_storage.mount_path` and emits the EFS plumbing — the filesystem, mount targets, task-definition `volumes` block, and container `mountPoints` block.

Engines without `persistent_storage` get no EFS emission. Engines with it MUST also declare `efs_file_system` in `emits.elastic` (the dispatch model is explicit, not implicit).

### New emit destination: `efs_file_system`

Add `efs_file_system` to `EMIT_DESTINATIONS["elastic"]`. An engine that wants EFS emits to it:

```yml
roles:
  analytics_db:
    clickhouse:
      foundation: both
      emits:
        fixed: [compose_service]
        elastic: [task_definition, ecs_service, efs_file_system]
      defaults:
        fixed:
          image: clickhouse/clickhouse-server:24
          volumes:
            - ${global_service_name}_data:/var/lib/clickhouse
        elastic:
          image: clickhouse/clickhouse-server:24
          cpu: "512"
          memory: "2048"
      persistent_storage:
        mount_path: /var/lib/clickhouse
      fields:
        # Per-service opt-in for AWS Backup. Default disabled — only the
        # project knows whether the data is replaceable cache or
        # irreplaceable user state.
        backups:
          elastic:
            target: efs_file_system
            enabled: ${field_value}
      provides:
        host:
          fixed: "${global_service_name}"
          elastic: "${global_service_name}"
        port:
          fixed: "${port}"
          elastic: "${port}"
      env: {}
      naming: ecs
```

The `efs_file_system` destination is realized by a new `render_efs_file_system` per-destination renderer.

### What `render_efs_file_system` emits

For one stateful container-backing service:

1. **`aws_efs_file_system`** — the regional filesystem, encrypted at rest using the AWS-managed KMS key.
   ```hcl
   resource "aws_efs_file_system" "<svc.name>" {
     creation_token   = "<svc.global_name>"
     encrypted        = true
     performance_mode = "generalPurpose"
     throughput_mode  = "bursting"
     tags = { project, env, service, role, managed_by = "doctrine" }
   }
   ```

2. **`aws_efs_backup_policy`** — emitted **only when the project explicitly opts in** via `backups: true` on the backing service in `infra.yml`. Default disabled.
   ```hcl
   resource "aws_efs_backup_policy" "<svc.name>" {
     file_system_id = aws_efs_file_system.<svc.name>.id
     backup_policy { status = "ENABLED" }
   }
   ```

3. **`aws_efs_mount_target`** — one per private subnet (so tasks in any AZ can mount). The mount target attaches to the service's SGs (minus `web` — EFS shouldn't be on the public plane).
   ```hcl
   resource "aws_efs_mount_target" "<svc.name>" {
     count           = length(data.terraform_remote_state.project.outputs.private_subnet_ids)
     file_system_id  = aws_efs_file_system.<svc.name>.id
     subnet_id       = data.terraform_remote_state.project.outputs.private_subnet_ids[count.index]
     security_groups = [aws_security_group.internal.id, ...]  # service's non-web SGs
   }
   ```

The SG attachment leverages the existing `internal` SG's self-ingress rule (all ports, all protocols, ingress from self). The Fargate task is on `internal`; the mount target is on `internal`; NFS port 2049 is covered by the self-ingress. No new SG rule needed.

### Task-definition extension

`render_task_definition` needs to emit two new things when `svc.persistent_storage` is set:

1. **A `volumes` block on the task definition** referencing the EFS:
   ```hcl
   volume {
     name = "data"
     efs_volume_configuration {
       file_system_id     = aws_efs_file_system.<svc.name>.id
       transit_encryption = "ENABLED"
     }
   }
   ```

2. **A `mountPoints` entry on the container definition**:
   ```jsonc
   "mountPoints": [{
     "sourceVolume": "data",
     "containerPath": "<persistent_storage.mount_path>",
     "readOnly": false
   }]
   ```

The volume name (`"data"`) is a doctrine-fixed handle — one EFS per stateful service, mounted at one path. No need for parameterization.

### Carrying `persistent_storage` through compile

`CompiledService` grows a new field:

```python
persistent_storage: dict[str, Any] | None = None
```

Populated in `compile.py` from `engine.persistent_storage` when the engine declares it. The renderers read `svc.persistent_storage` directly.

### Why not auto-emit `efs_file_system` based on `persistent_storage`?

Asymmetric: it would make `emits.elastic` non-authoritative — the dispatcher would emit destinations not in the list. The doctrine's `emits:` model is explicit — engines declare what they emit, the compiler dispatches against the declaration. Keeping it explicit means:
- A glance at an engine's `emits.elastic` tells you everything it produces on elastic.
- Validation (already added in Mod 012 for unknown destinations) keeps working uniformly.
- Future destinations are added to the closed set with the same pattern.

So engines that need EFS must declare both `persistent_storage` AND `emits.elastic: [..., efs_file_system]`. A validator catches the inconsistency: declaring one without the other is a compile error.

### Validation

Two new validation rules:

1. **`persistent_storage` requires `efs_file_system` in `emits.elastic`.** An engine that declares `persistent_storage` but omits `efs_file_system` from its elastic emits is malformed. Hard error at load time.
2. **`efs_file_system` requires `persistent_storage`.** Conversely, declaring `efs_file_system` in `emits.elastic` without `persistent_storage` (with a `mount_path`) is also malformed.

Both fail the doctrine's strict-load contract (Mod 012). Add to `_validate_engine_entry`.

### What this mod does NOT do

- Does not add EFS access points (per-application root paths, POSIX permissions). Sensible default: mount the EFS root. Multiple stateful services each get their own EFS, so there's no shared-namespace collision.
- Does not add lifecycle policies (transition-to-IA, transition-to-Archive). Sensible default: keep files in Standard storage.
- Does not add EFS throughput tuning. Default `throughput_mode = "bursting"` is fine for v1; provisioned throughput is a future tuning concern.
- Does not auto-propagate `persistent_storage.mount_path` to `defaults.fixed.volumes`. Fixed-side storage stays explicit at the engine level.
- Does not introduce a `cicl.md`-level `resources:` block for backing services to tune EFS storage capacity. EFS storage capacity is pay-as-you-grow; there's no allocation step.
- Does not address EFS cost in the doctrine's resource-sizing prose. EFS Standard is ~$0.30/GB-month + IO; operators should know. Defer to a future doctrine note alongside the Envoy sidecar overhead from Mod 014.

## Proposed doctrine edits

Three edits, all to `transfer_tables.md`:

1. **New subsection "Persistent storage on Fargate"** after the "Container-backing services on elastic" section (Mod 013's section). Roughly:

   ````markdown
   ## Persistent storage on Fargate

   A container-backing service whose engine declares `persistent_storage` gets a per-service EFS filesystem mounted into the task at the declared `mount_path`. This is the doctrine's mechanism for stateful container backings on elastic — ClickHouse, real Redis-as-storage, anything that needs a durable data directory.

   ```yml
   roles:
     analytics_db:
       clickhouse:
         emits:
           elastic: [task_definition, ecs_service, efs_file_system]
         persistent_storage:
           mount_path: /var/lib/clickhouse
         ...
   ```

   The compiler emits, per such service:

   - `aws_efs_file_system` — encrypted at rest.
   - `aws_efs_mount_target` per private subnet — so tasks in any AZ can mount the filesystem. Mount targets attach to the service's non-`web` security groups, leveraging the existing `internal` SG's self-ingress for NFS port 2049.
   - A `volume` block on the `aws_ecs_task_definition` referencing the EFS by ID, with `transit_encryption = "ENABLED"`.
   - A `mountPoints` entry on the container definition linking the volume to the declared `mount_path`.
   - **Backups are project-opt-in.** Engines that emit `efs_file_system` may declare a `backups` field with `target: efs_file_system` (using Mod 010's field-routing mechanism); the project sets `backups: true` on the backing service in `infra.yml` to enable. When enabled, an `aws_efs_backup_policy` resource ties the filesystem to the AWS Backup default plan. Default disabled — only the project knows whether the stateful data is replaceable cache or irreplaceable user state.

   The volume name inside the task definition is the doctrine-fixed handle `"data"` — one EFS per stateful service, mounted at one path. EFS access points and lifecycle policies are out of scope for v1; engines that need them can override emit via project-local transfer-table extensions.

   On fixed, `persistent_storage` is informational only. Engine authors declare their docker named volume in `defaults.fixed.volumes` themselves (the existing pattern). The fixed and elastic sides agree on `mount_path` because the engine declares both.

   Validation: an engine declaring `persistent_storage` must also declare `efs_file_system` in `emits.elastic`, and vice-versa. The two halves go together.
   ````

2. **Add `persistent_storage` to the "Field reference"** subsection of "Anatomy of a Role Definition" so the engine schema enumerates it alongside `default_port`, `emits`, etc. Single sentence — points at the new section above for detail.

3. **A small mention in the "Container-backing services on elastic" section** added in Mod 013, noting that stateful ones additionally need `persistent_storage` — links forward to "Persistent storage on Fargate". (Already foreshadowed there as "added in a follow-on mod"; this mod fills it in.)

No changes to `cicl.md`, `shape.md`, or `infrastructure.md`. EFS is a doctrine-internal mechanism; consumers see only the `mount_path` declaration and the persistent behavior. The shape table can stay unchanged — EFS is implicit infrastructure under "backing_service" on elastic.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `transfer_tables.md`: new "Persistent storage on Fargate" subsection + field-reference entry + forward link from "Container-backing services on elastic". |
| `docex/plans/core/*.md` | `compiler.md`: add `efs_file_system` to the "Where to look when changing things" table; brief mention in the structural-vs-engine emit section that EFS is engine-driven, not structural. |
| `tables/*.yml` | No change to bundled tables. The canonical bundled engines don't need stateful container backing — postgres is RDS, redis is ElastiCache, s3 is S3, web/container is the project's own code (no persistent_storage). Project-local tables are where stateful container engines (like clickhouse) will live. |
| `src/docex/**` | `cicl/transfer.py`: add `efs_file_system` to `EMIT_DESTINATIONS["elastic"]`, add `persistent_storage` to `_ALLOWED_ENGINE_KEYS`, add `persistent_storage` field to `EngineEntry`, add cross-validation in `_validate_engine_entry` (efs↔persistent_storage). `cicl/compile.py`: add `persistent_storage` field to `CompiledService`, populate from engine. `emit/hcl.py`: add `render_efs_file_system` + register in `_DESTINATION_RENDERERS` + extend `render_task_definition` to emit volumes + mountPoints when `persistent_storage` is set. |
| `tests/**` | Unit tests: (a) `render_efs_file_system` emits aws_efs_file_system + backup_policy + mount_target × N; (b) task definition gains volumes + mountPoints when `persistent_storage` is set; (c) container without `persistent_storage` doesn't get volume blocks; (d) validation: persistent_storage without efs_file_system fails load; (e) validation: efs_file_system without persistent_storage fails load; (f) the new field flows through compile correctly. |

## Validation

1. `python3 -m pytest tests/unit/ -q` — all green.
2. `python3 -m pytest tests/integration/test_compile.py -q` — green.
3. Compile a fixture or test case with a project-local stateful engine (clickhouse-shaped). Inspect emitted `main.tf`: confirm one EFS filesystem, backup policy, two mount targets, task def has the `volume` block, container def has `mountPoints`.

Real-AWS smoke verification happens at Step 4 of the advance.

## Decisions captured

1. **`persistent_storage` as a top-level engine field**, not embedded inside `defaults.elastic`. Symmetric placement with `default_port`, `emits`, `naming`; makes the engine's stateful nature scannable at a glance.
2. **Explicit `efs_file_system` emit destination**, not auto-emitted when `persistent_storage` is declared. Keeps `emits` authoritative.
3. **Bidirectional validation**: persistent_storage ↔ efs_file_system must agree. Compile error if either is declared alone.
4. **One EFS per stateful service**, mounted at the engine's `mount_path`. No access points, no shared filesystems.
5. **EFS backups are project-opt-in, default disabled.** Engines that emit `efs_file_system` declare a `backups` field with `target: efs_file_system` (Mod 010's field-routing mechanism); the project sets `backups: true` on the backing service in `infra.yml` to enable. Default behavior (field omitted, or set to `false`) emits no `aws_efs_backup_policy`. The doctrine doesn't presume to know whether a project's stateful data is replaceable cache or irreplaceable user data; opt-in is the safer default. Engines can document the trade-off in their `description:`.
6. **Mount target SG attachment** is the service's non-`web` SG set. Leverages `internal`'s self-ingress for NFS port 2049 — no new SG rule.
7. **Volume name is fixed as `"data"`**. One EFS per service, no need for parameterization.
8. **`encrypted = true` and `transit_encryption = "ENABLED"`** — default for any production workload, no operator opt-in.
9. **Fixed-side `persistent_storage` is informational only**. Engine authors continue to declare `defaults.fixed.volumes`. Small duplication, large clarity.

## Open questions

1. **EFS storage cost in the doctrine's resource-sizing prose.** EFS Standard is ~$0.30/GB-month + IO; could surprise operators sizing ClickHouse for production. A future doctrine note covering both EFS cost and the Envoy sidecar overhead from Mod 014 makes sense. Not blocking.

2. **`efs_file_system` cleanup discipline.** EFS isn't auto-destroyed by `tofu destroy` if the filesystem has data (depending on AWS settings). The `aws_efs_file_system` resource itself destroys cleanly, but if a project's `teardown.sh` runs `tofu destroy` on a stateful env, the EFS goes away with the env. That's the doctrine intent (envs are reproducible), but operators should know to back up before destroying. Note for a future doctrine extension on "tearing down stateful envs"; not blocking v1.

Neither blocks this mod.

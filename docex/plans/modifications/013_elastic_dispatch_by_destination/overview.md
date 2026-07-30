# Mod 013 — Elastic dispatch by emit destinations; container-backing services renderable

## Problem

`docex` Phase 4's elastic emit was designed for the doctrine-bundled engine set: postgres on RDS, redis on ElastiCache, s3 on its own bucket, web/container on ECS. Each path was hand-written for its specific engine. The shape works today only because that exact engine set is the one in the bundled tables.

Two structural problems block project-local backing engines (the advance's whole motivation: ClickHouse, OTel collector, sidecars):

1. **Elastic dispatch is keyed on engine name, not on emit destination.** `src/docex/emit/hcl.py:109-114` defines a hardcoded map:
   ```python
   _ENGINE_TO_RESOURCE = {
       "postgres": "aws_db_instance",
       "redis": "aws_elasticache_cluster",
       "s3": "aws_s3_bucket",
   }
   ```
   `render_backing` (line 158) calls `_ENGINE_TO_RESOURCE.get(svc.engine)`. Any backing-service engine outside that closed set returns `None` and emits a `# unknown engine 'nginx' for service 'sidecar'; no HCL emitted` comment. The doctrine's promise (per `transfer_tables.md` § Where Transfer Tables Live) that projects may add new engines via project-local tables is **structurally undeliverable for backing services on elastic**.

2. **`render_core` and `render_backing` split on `is_core`, not on what the engine emits.** `emit_hcl` (hcl.py:534-535) builds two lists: `backing = [s for s in services if not s.is_core]` and `core = [s for s in services if s.is_core]`. Each list goes to its own renderer. But the same emit destination (`task_definition`, for instance) is what BOTH a core web service AND a container-backing service want to land on. The split forces the same logic to live in two places — or, in our case, it forces the core path to be unreachable for backing services that legitimately want to use it.

The doctrine's emit-destinations machinery (mod 010's `emits:` + `target:`) already declares that *the engine's emit list governs what the compiler produces*. The implementation just never caught up — dispatch still walks engine names and `is_core` flags.

Mod 013 makes the implementation match the doctrine: **dispatch by emit destination**, not by engine name and not by `is_core`. After this mod, a project can declare a new backing-service engine in `infra/transfer_tables/` with `emits.elastic: [task_definition, ecs_service]` and the compiler renders it as an ECS Fargate task — the same way it renders a core service.

## Design

### Per-destination renderers

Replace `render_backing` (engine-name dispatch, three resource types) and `render_core` (one big function doing task_def + ecs_service + target_group) with six per-destination renderers, one per entry in `EMIT_DESTINATIONS["elastic"]`:

| Destination | Renderer | Emits | Conditions |
| ----------- | -------- | ----- | ---------- |
| `task_definition` | `render_task_definition` | `aws_ecs_task_definition` (+ migration variant for schema-owning core services) | none |
| `ecs_service` | `render_ecs_service` | `aws_ecs_service` (with load_balancer ref if target_group also emitted) | none |
| `target_group` | `render_target_group` | `aws_lb_target_group` + `aws_lb_listener_rule` | service has `web` in `networks` |
| `rds_instance` | `render_rds_instance` | `aws_db_instance` + `aws_db_subnet_group` (with SG attachment) | none |
| `elasticache_cluster` | `render_elasticache_cluster` | `aws_elasticache_cluster` + `aws_elasticache_subnet_group` | none |
| `s3_bucket` | `render_s3_bucket` | `aws_s3_bucket` | none |

The `_ENGINE_TO_RESOURCE` map disappears. Dispatch lookup becomes:

```python
_DESTINATION_RENDERERS: dict[str, Renderer] = {
    "task_definition": render_task_definition,
    "ecs_service": render_ecs_service,
    "target_group": render_target_group,
    "rds_instance": render_rds_instance,
    "elasticache_cluster": render_elasticache_cluster,
    "s3_bucket": render_s3_bucket,
}
```

### One service iteration, destination-driven

Replace the `backing`/`core` split with a single ordering — backing services first (alphabetical), then core services (alphabetical) — for readable diffs in `main.tf`. The split is purely cosmetic; both kinds of services walk through the same dispatch:

```python
for svc in ordered_services:
    for dest in svc.emits_for("elastic"):
        if _destination_applicable(dest, svc):
            block = _DESTINATION_RENDERERS[dest](svc, ctx)
            blocks.append(block)
```

`_destination_applicable(dest, svc)` enforces conditions like `target_group requires "web" in svc.networks`. Currently the only conditional destination is `target_group`; the doctrine already prescribes this via mod 010's `target:` validation.

### Shared logic between core and backing

The task-definition renderer is shared between core services (the existing path) and container-backing services (the new path). A few `is_core`-gated behaviors stay inside the renderer:

- **`PROJECT_VERSION` env var.** Doctrine-injected only on core services (per `transfer_tables.md` § Per-core-service env). Already wired in `compile.py`'s env-block construction; the renderer sees it in `svc.env` and emits it like any other env entry. Backing services have `svc.env == {}` (compile.py only fills env for `CoreService`), so the renderer naturally skips this.
- **Migration task definition.** Emitted only if `svc.is_core and svc.schema_owned_by_db`. Sub-emission of `render_task_definition` — same shape, different `command` and `family`.
- **Image source.** Already handled in `compile.py` — core services get `_image_ref(...)` derived; backing services keep whatever their engine declared in `defaults.elastic.image`. The renderer just reads `body["image"]` regardless of `is_core`.
- **CPU/memory source.** Core services get cpu/memory from `_resources_to_elastic(svc.resources)`. Container-backing engines bake `cpu`/`memory` directly into `defaults.elastic`. Either way, the renderer reads `body["cpu"]` and `body["memory"]`.

So the renderer is fully shared; `is_core` is only consulted for the two genuinely-core-specific concerns (migration variant + nothing else inside the renderer body).

### SSM substitution applies to both

`render_backing`'s existing `maybe_ssm_substitute` walk (hcl.py:174-191) translates `$[VAR]` tokens inside the body into `data.aws_ssm_parameter` references — used by postgres to source `username`/`password` from SSM. The same logic applies to any backing service whose engine bakes a `$[VAR]` token into `defaults.elastic`. Container-backing engines (nginx, OTel) don't currently use this, but if they did (e.g., a clickhouse engine declaring `password: $[CLICKHOUSE_PASSWORD]`), the same substitution would work. The behavior moves into `render_task_definition` so it covers both render paths.

### Resources-on-backing-services question

Backing services don't carry a `resources:` block in `infra.yml` (per `cicl.md` § Resources, current doctrine). For container-backing services on elastic, the engine bakes `cpu`/`memory` into `defaults.elastic`. The doctrine question — "should the project be able to tune cpu/memory per container-backing service in `infra.yml`?" — is **deferred to a future mod**. Mod 013 stays narrow: container-backing on elastic works, sizing comes from engine defaults, project-local overrides come from project-local transfer tables (the existing extension surface).

Justification for the deferral: stateless backing services (sidecar, OTel collector) rarely need per-project sizing — defaults are fine. Stateful backing services (ClickHouse) might need tuning, but Mod 015's `persistent_storage:` engine field already opens the door to extending the schema for stateful concerns. Bundle resource sizing into that or a follow-on mod.

### What this mod does NOT do

- Does not add ECS Service Connect / Cloud Map. Container-backing services will be renderable but not yet *resolvable by name* from peer services. Mod 014 adds that.
- Does not add EFS support for stateful storage. Mod 015 adds that.
- Does not change the fixed-side emit. Compose's dispatch is already engine-agnostic (per the survey); container-backing on fixed works today.
- Does not extend the doctrine's `resources:` block to backing services. Deferred.
- Does not add new emit destinations. The set in `EMIT_DESTINATIONS` is unchanged; only the dispatch path changes.

## Proposed doctrine edit

A single new section in `doctrine/infrastructure/specifics/transfer_tables.md`, inserted between "## Failure-mode contract" (added in Mod 012) and "## Foundation Invariants". Roughly:

````markdown
## Container-backing services on elastic

A backing service whose engine declares `emits.elastic: [task_definition, ecs_service]` is rendered as an ECS Fargate task on elastic — identical to how a core service is rendered there. The compiler dispatches by the engine's declared destinations, not by whether the service is core or backing.

This is what makes containerized backing services (sidecars, OTel collectors, ClickHouse, anything that runs as a container but isn't bespoke project code) first-class on elastic. The engine declares its image and per-foundation defaults in the transfer table; the compiler routes to the same `task_definition` + `ecs_service` resources the core path uses.

Container-backing engines must bake `cpu` and `memory` (Fargate units, integer strings) directly into `defaults.elastic`. Backing services don't carry a `resources:` block in `infra.yml` — the engine controls sizing. Projects that need to tune sizing override the engine's defaults via a project-local transfer table entry.

Stateful container-backing services (ClickHouse, real Redis with persistence) additionally need persistent storage. EFS attachment on Fargate is covered separately — see [§ Persistent storage on Fargate](./transfer_tables.md) (added in a follow-on mod).
````

Plus a small clarification in the existing `## Anatomy of a Role Definition` § `emits` paragraph (line 231) noting that "the set of recognized destinations is closed in docex source; the dispatch chooses the per-destination renderer by name."

No edits to `cicl.md`, `infrastructure.md`, or `shape.md`. The change is at the engine-emission semantics layer, not at the cross-foundation shape layer.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `transfer_tables.md`: new "Container-backing services on elastic" section + a clarifying sentence in the `emits` paragraph. |
| `docex/plans/core/*.md` | `compiler.md`: "Structural vs engine emit" subsection updated to reflect destination-driven dispatch (replaces the engine-name dispatch language). |
| `tables/*.yml` | No change. Bundled engines (postgres, redis, s3, web/container) already declare correct `emits:` lists; the new dispatch is what reads them. |
| `src/docex/**` | `cicl/transfer.py`: rename internal helpers if any; the public surface (`EMIT_DESTINATIONS`, `EngineEntry.default_target`) is unchanged. `emit/hcl.py`: replace `render_core` + `render_backing` with the six per-destination renderers + `_DESTINATION_RENDERERS` dispatch + a refactored `emit_hcl`. `emit/templates/main.tf.j2`: replace the two `{% for backing %}` / `{% for core %}` loops with a single loop calling `render_service`. `cicl/compile.py`: minor — backing services may need their `emits` carried through to `CompiledService` (verify; might already be there). |
| `tests/**` | New unit tests: (a) a project-local sidecar engine with `emits.elastic: [task_definition, ecs_service]` produces valid HCL; (b) `aws_ecs_task_definition.sidecar` is emitted; (c) `aws_ecs_service.sidecar` is emitted with the right SG; (d) `target_group` skip on backing/internal-network case. Refactor existing tests against `render_core` / `render_backing` to call the new per-destination renderers directly (likely 5-10 existing tests to update). |

## Validation

1. `python3 -m pytest tests/unit/ -q` — all green.
2. `python3 -m pytest tests/integration/test_compile.py -q` — green.
3. `python3 -m pytest tests/integration/test_hcl_render.py` (if exists) — green; bundled engines produce the same HCL they did before (or HCL equivalent up to ordering).
4. Hand-author a `tests/fixtures/` project with a project-local sidecar engine declaration, run `docex compile`, inspect the emitted `main.tf` for the expected ECS resources.

A nice-to-have: a `tofu validate` smoke test on the emitted `main.tf` for a project with a sidecar engine. Defer to integration if it requires AWS provider download — keep the unit-test layer dependency-free.

## Decisions captured

1. **Dispatch by emit destination, not engine name or `is_core`.** Aligns implementation with doctrine. The engine's `emits.elastic` list is the source of truth for what HCL gets emitted.
2. **`render_task_definition` shared between core and backing.** The two paths needed almost-identical logic; carrying both was the bug. `is_core` is now consulted only for the two genuinely-core-only concerns (`PROJECT_VERSION` is handled via `svc.env`; migration variant is a conditional sub-emission).
3. **Sizing for container-backing services comes from engine defaults, not `infra.yml`.** Defers the `resources:`-on-backing-services question. Stateless cases don't need per-project tuning; stateful cases get covered by Mod 015's `persistent_storage:` extension or a follow-on.
4. **Single service iteration in the Jinja template.** Removes the `{% for backing %}` / `{% for core %}` split. Ordering — backing first, then core, alphabetical within — preserved by the iteration order in Python before handing to the template.
5. **`_DESTINATION_RENDERERS` is a closed dict.** Mirrors `EMIT_DESTINATIONS` — adding a destination requires growing both. That's the point: new destinations are doctrine knowledge, not project-extensible.

## Open questions

1. **Migration task definition: separate destination or sub-emission of `task_definition`?** Current proposal: sub-emission inside `render_task_definition`, gated on `svc.is_core and svc.schema_owned_by_db`. Alternative: a separate `migration_task_definition` destination in `EMIT_DESTINATIONS`. The current proposal is cleaner because schema ownership is a `cicl.md`-level concern, not an engine-level emit choice — backing services never own schemas (the doctrine forbids it), so there's no engine that would ever declare `emits.elastic: [migration_task_definition]`.

2. **What about `web`-network container-backing services?** Per the doctrine, any `web`-network service gets routed (Traefik on fixed, ALB target group on elastic). For a hypothetical `web`-network container-backing service, the dispatcher would emit `target_group` (since it's in `emits.elastic` of the engine that includes it). The doctrine doesn't currently anticipate this case but doesn't forbid it. Sidecar/OTel/ClickHouse are all `internal`-only, so this is theoretical for now. The dispatch handles it correctly via the conditional check.

Neither blocks the mod. Both are noted for future doctrine clarification if real cases arise.

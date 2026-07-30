# Mod 010 — `emits:` + `target:` for cross-resource field routing

## Problem

Discovered during the maptrack smoke release: `health_check_path: /health` in `infra.yml` (a valid field per `./bin/docex role web`) doesn't reach the compiled HCL's ALB target group. The ALB falls back to checking `/`, the backend doesn't serve `/`, and the ECS rollout cycles tasks indefinitely on 404s.

Mechanism of the bug, traced through the source:

1. `tables/roles/web.yml` defines `fields.health_check_path.elastic.target_group_health_check: { path: ${field_value}, ... }`.
2. `src/docex/cicl/compile.py:397-416` builds `body` by deep-merging engine `defaults` + each field's per-foundation translation. `body` represents the engine's *default primary resource* — the ECS task definition for `web`/`container` on elastic.
3. The deep-merge produces an ECS task definition body with a stray `target_group_health_check:` key.
4. The HCL emitter walks `body` to render `aws_ecs_task_definition` — the stray key is meaningless to ECS and is silently dropped.
5. The ALB target group emission (`emit/hcl.py:386-394`) emits `aws_lb_target_group` with hardcoded `name` / `port` / `protocol` / `target_type` / `vpc_id` — no consumption of any contributed health-check fields.

The field is structurally undeliverable: its translation has no path from the engine table to the resource it's meant to configure.

Mod 010 introduces the routing machinery the doctrine now describes (per `transfer_tables.md`'s post-mod-design schema): engines declare `emits:` listing their valid destinations; a field's per-foundation translation may declare `target:` naming one of those destinations; compile splits translations by destination; the emit layer reads the routed bodies into their respective resources.

## Audit findings

Every `fields:` entry across every engine in the doctrine-shipped tables, and where its translation should land:

| Engine | Field | Fixed → | Elastic → | Status |
|--------|-------|---------|-----------|--------|
| postgres (relational_db) | `version` | `compose_service` (default) | `aws_db_instance` (default) | works today |
| redis (cache) | `version` | `compose_service` (default) | `aws_elasticache_cluster` (default) | works today |
| minio (object_store) | `versioning` | `compose_service` (default) | n/a | works today |
| s3 (object_store) | `versioning` | n/a | `aws_s3_bucket` (default) | works today |
| container (web) | `health_check_path` | `compose_service` (default) | **`target_group`** (non-default) | **broken** |

Four of five field-translation pairs route to the engine's default primary resource and work today by accident — there *is* no other destination they could land on within their engine's scope. Only `health_check_path.elastic` is structurally cross-resource, and it's the one the bug surfaced on.

The narrow fix is to make `health_check_path` work. The audit shows the right fix is the broader doctrine machinery: every field's translation gets an explicit (default) target, and the engine declares which non-default targets exist. That makes the cross-resource case first-class and means the next time someone adds a field that needs to land on the ECS service resource (`deployment_minimum_healthy_percent`, etc.) or the ALB listener rule (`priority_offset`), the routing slot is already there.

## Design

### Schema (per the doctrine edits in `transfer_tables.md`)

Each engine grows an `emits:` block — a per-foundation ordered list of destination names. First entry in each list is the default target. Each `fields.<f>.<foundation>` may declare `target: <name>` from that list; when omitted, the translation lands on the default.

Doctrine-recognized destination names (closed set, lives in docex code):

| Foundation | Destination | Maps to emitted resource |
|------------|-------------|--------------------------|
| fixed | `compose_service` | The docker-compose service block |
| elastic | `task_definition` | `aws_ecs_task_definition` (the `container_definitions[0]` body) |
| elastic | `ecs_service` | `aws_ecs_service` (rolling-deploy settings, etc.) |
| elastic | `target_group` | `aws_lb_target_group` (health check, deregistration delay, etc.) |
| elastic | `rds_instance` | `aws_db_instance` |
| elastic | `elasticache_cluster` | `aws_elasticache_cluster` |
| elastic | `s3_bucket` | `aws_s3_bucket` |

For v1 the set is closed and known to the compiler. If a new emit destination is ever needed, it requires a docex source change (compiler grows a routing case for it) and a doctrine update listing it — that's the right friction.

`emits:` declaration for each existing engine:

| Engine | Foundation | `emits:` |
|--------|------------|----------|
| postgres | fixed | `[compose_service]` |
| postgres | elastic | `[rds_instance]` |
| redis | fixed | `[compose_service]` |
| redis | elastic | `[elasticache_cluster]` |
| minio | fixed | `[compose_service]` |
| s3 | elastic | `[s3_bucket]` |
| container | fixed | `[compose_service]` |
| container | elastic | `[task_definition, ecs_service, target_group]` |
| traefik | fixed | `[compose_service]` |

`container.emits.elastic` lists three destinations even though only `target_group` is non-default. `ecs_service` is there to claim the namespace for future fields. Not a problem to declare destinations no field currently uses.

### Code touch points

1. **`src/docex/cicl/transfer.py` — `EngineEntry` model.**
   - Add `emits: dict[str, list[str]]` (foundation → ordered list of destinations).
   - Update `_parse_entry` to populate `emits` from raw YAML.
   - Add `EngineEntry.default_target(foundation)` returning `emits[foundation][0]` (or error if not declared).
   - Modify `EngineEntry.field_translation(field_name, foundation)` to return a `(target_name, body_dict)` tuple — or add a sibling method `field_translation_with_target` to keep the old one stable for callers that don't need routing.

2. **`src/docex/cicl/compile.py` — compile loop.**
   - Replace `body: dict[str, Any]` with two structures: `default_body: dict[str, Any]` (engine defaults + every field whose target is the default) and `target_extras: dict[str, dict[str, Any]]` (`destination_name -> body fragment` for non-default targets).
   - Each field-translation merge inspects the field's resolved target. If it's the default, merge into `default_body`; otherwise merge into `target_extras[target_name]`.
   - Substitution applies to both stages.

3. **`src/docex/cicl/model.py` — `CompiledService`.**
   - Add `target_extras: dict[str, dict[str, Any]]` to `CompiledService` (defaults to empty dict for backwards-friendly construction).
   - `body` remains the default-target body for callers that don't care about routed extras.

4. **`src/docex/emit/hcl.py` — target group emission.**
   - Lines 386-394 currently emit `aws_lb_target_group` with hardcoded fields only. Extend to consume `svc.target_extras.get("target_group", {})` and render any present sub-blocks (`health_check`, `deregistration_delay`, etc.). For v1 only `health_check` is known to appear; render it as a nested HCL block when present.
   - No changes to `aws_ecs_task_definition` emission — that consumes `svc.body` (the default target) unchanged.
   - No changes to `aws_ecs_service` emission — `target_extras["ecs_service"]` is reserved-but-empty for v1.

5. **`src/docex/emit/compose.py` — fixed emission.**
   - Likely no changes. Every fixed-side translation routes to `compose_service` (the default), which means `default_body` already contains everything compose needs. Confirm during implementation; if a fixed-side non-default destination exists or gets added later, this section grows.

6. **`src/docex/cicl/validate.py` — new validation rules.**
   - Every engine declares non-empty `emits.fixed` (and `emits.elastic` if the engine supports elastic).
   - Every destination name in `emits.<foundation>` is in the doctrine-recognized closed set.
   - Every `fields.<f>.<foundation>.target:` (when set) names a destination in the engine's `emits.<foundation>`.
   - Conditional-target check: if a field declares `target: target_group` and the service isn't on the `web` network, fail with a hint. (The compiler already knows which services are on `web`; this is a service-level check at compile time, not just a table-level check at load time.)

7. **`tables/roles/*.yml` — add `emits:` to every engine.**
   - Five files, nine engines (postgres, redis, minio, s3, container, traefik). Per the table above.
   - Restructure `web.yml`'s `health_check_path.elastic` translation: drop the `target_group_health_check:` wrapper, add `target: target_group`, the inner keys (`path`, `healthy_threshold`, etc.) become the actual body the target-group emitter consumes.

### What "minimal-disruption" means here

Engines with no non-default field destinations get `emits: [<default>]` and never use `target:` — their existing fields continue to work, just with an explicit declaration of where they land. The only data change with actual semantic effect is `health_check_path`'s restructuring.

If the implementer can't get every existing engine's `emits:` declared without breaking tests, the path of least resistance is to make `EngineEntry.default_target` tolerant of missing `emits:` (return the doctrine-default-for-foundation: `compose_service` on fixed, the engine's primary HCL resource on elastic — derivable from `naming:` policy in most cases, but not all). I prefer the strict path — every engine declares its `emits:` explicitly. That's what the doctrine validation rules now require.

### What's deliberately NOT in this mod

- Generalizing the destination set as a `structural_resources:` declarative table (deferred per `compiler.md` § Structural vs engine emit). The closed-set-in-docex-code approach is right for v1.
- Adding new fields that target `ecs_service` or `s3_bucket`. The routing slots exist after this mod; new fields can opportunistically use them later.
- Backporting the fix to past `docex` versions. Smoke projects pinned to `0.7.0` will continue to silently drop `health_check_path` until repinned to the new cut.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | Already changed: `transfer_tables.md` schema, walking examples (postgres + web/container), field-reference bullets, validation rules 11+12. No further edits in this mod. |
| `docex/plans/core/*.md` | `compiler.md` — the "Structural vs engine emit" section already anticipates a `structural_resources:` future. Worth a short paragraph (or just a bullet) acknowledging that `emits:` is now declared on engines but `structural_resources:` is still deferred. Optional; not blocking. |
| `tables/*.yml` | All five role tables gain `emits:` declarations. `web.yml` additionally restructures `health_check_path.elastic`. |
| `src/docex/**` | `cicl/transfer.py`, `cicl/compile.py`, `cicl/model.py`, `cicl/validate.py`, `emit/hcl.py`. Source change is real and load-bearing here — unlike mod 009. |
| `tests/**` | Unit tests for: (a) `emits:` parsing on `EngineEntry`; (b) `default_target` correctness; (c) field translation routing — default and non-default; (d) validation errors for bad `target:` refs; (e) HCL emission of the target-group `health_check` block from a `health_check_path` field. Integration test: compile the elastic smoke project and grep the output for `health_check { path = "/health" }` on `aws_lb_target_group.web`. |

## Validation

1. `python3 -m pytest tests/unit/` — green, including all new tests.
2. `python3 -m pytest tests/integration/` — green; the existing tests for elastic compile must continue to pass.
3. Manual grep on the recompiled elastic smoke project output (Step 6 of `implementation.md` — deferred to advance-end):
   - `infra/output/stage/main.tf` contains an `aws_lb_target_group.web` block with a nested `health_check { path = "/health" ... }`.
   - The same file's `aws_ecs_task_definition.web` block does NOT contain a stray `target_group_health_check` entry.

## Decisions captured

1. **Closed set of destination names in docex code, not in transfer tables.** Adding new destinations is a docex source change. v1 keeps the structural-resources side declarative (state buckets, ECR, IAM) but engine-emit destinations stay coded. If both surfaces grow, mod NNN promotes both to a unified `structural_resources:` table.
2. **`emits:` lists all destinations; first entry is default.** Simpler than an explicit `default: true` flag; the doctrine prose already says this.
3. **`target:` is optional on field translations; default is the engine's primary.** Matches the schema in `transfer_tables.md`.
4. **`container.emits.elastic` declares `[task_definition, ecs_service, target_group]` even though no field currently routes to `ecs_service`.** Future-proofing the routing slots that obviously should exist; the cost is one extra line per engine.
5. **`web/container.health_check_path.elastic` drops the `target_group_health_check:` wrapper.** With `target: target_group` declaring the destination, the inner keys are the body. The old wrapper key was a hack.
6. **Compose emit is untouched.** Every fixed-side translation routes to `compose_service` (the default). Mod is symmetric in design but asymmetric in code surface — elastic gets the real plumbing.

## Open questions

1. **Conditional targets validation.** The doctrine says `target: target_group` is invalid on a service that isn't on the `web` network. Should the validator catch this at compile time (require `health_check_path` only on web-network services) or at the routing step (silently drop the translation if no target group exists)? I lean *catch it loudly* — the project intended the field to do something; silent drop is the failure mode mod 010 exists to eliminate.
2. **Backwards compatibility for callers of `field_translation`.** The current method returns `dict[str, Any] | None`. Should we change its signature (breaks any consumer that exists) or add a parallel method (cleaner; old method stays for non-routing callers)? I lean parallel method — the routing concern is genuinely new and the old method is fine for callers that don't care.
3. **`target_extras` on `CompiledService` — empty dict or `None`?** Lean empty dict; lets emit code do `svc.target_extras.get("target_group", {})` without a None check.

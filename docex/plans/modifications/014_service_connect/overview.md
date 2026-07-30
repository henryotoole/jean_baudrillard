# Mod 014 — ECS Service Connect for intra-env service discovery

## Problem

The doctrine's elastic-foundation shape table (`shape.md`) claims:

> service_discovery | environment | AWS Cloud Map and ECS Service Connect | Provides DNS-based name resolution for [service]s within an env, so they can reach each other by name.

The code doesn't implement it. `grep -rn "service_connect\|cloud_map\|namespace" src/docex/emit/` returns nothing. No `aws_service_discovery_*` resources are emitted. The current intra-env reachability that works at all on elastic is *only* the core-to-RDS path — and that works because postgres exposes `host` via `@aws_db_instance.appdb.address` (a real AWS endpoint), not through any service-discovery name.

Mod 013 made container-backing services renderable on Fargate. But a `web` service that magic-refs a peer container backing (`SIDECAR_HOST: ${backing_services.sidecar.host}`) gets `proj_stage_sidecar` as the value — which doesn't resolve to anything on elastic. The peer's IP exists (the sidecar's ECS task has an ENI), but there's no name-to-IP path.

Service discovery is what closes the loop. With it, `web` resolves `proj_stage_sidecar` to the sidecar's tasks. Without it, the doctrine's `provides:` model is structurally undeliverable on elastic for any consumer-of-container-backing path.

## Design

### Service Connect, not raw Cloud Map

AWS offers two paths for ECS-to-ECS service discovery:

1. **Cloud Map DNS namespace** + `aws_service_discovery_service` per ECS service. Sets up a private DNS zone tied to the VPC; services register A records; consumers resolve names via VPC DNS. Traffic flows directly between tasks.
2. **ECS Service Connect** + Cloud Map HTTP namespace. ECS injects an Envoy sidecar proxy into each task. Consumers reach peers by name through the sidecar; Service Connect handles registration, health-aware routing, and (optionally) traffic-level concerns like retries.

Both work. Service Connect is AWS's modern recommendation, requires less per-service HCL, and aligns with how production ECS deployments are increasingly built. **Mod 014 implements Service Connect.**

The doctrine's "DNS-based" phrasing in `shape.md` is slightly inaccurate for Service Connect (which uses an HTTP namespace, not DNS records — though it appears name-based to apps). A small doctrine clarification updates this.

### One namespace per env

Each env (`stage`, `prod`) gets one Cloud Map HTTP namespace named `<project>_<env>` (e.g., `docex_smoke_elastic_stage`). It lives at the env tier — declared in `infra/output/<env>/main.tf` — alongside the ALB, ECS cluster, and SGs. The namespace doesn't need a DNS zone or any operator action; it's pure metadata that Service Connect uses.

### Per-ECS-service `service_connect_configuration`

Every `aws_ecs_service` gets a `service_connect_configuration` block:

```hcl
service_connect_configuration {
  enabled   = true
  namespace = aws_service_discovery_http_namespace.env.arn

  # When the service exposes a port, register it as discoverable.
  service {
    port_name      = "<short_service_name>"
    discovery_name = "<svc.global_name>"

    client_alias {
      port     = <svc.port>
      dns_name = "<svc.global_name>"
    }
  }
}
```

- **`enabled = true`** is required for any task to participate (as client, server, or both). Services without a port still get `enabled = true` (so they can resolve peers) but skip the `service {}` block.
- **`port_name`** references a named entry in the container's `portMappings`. The task definition's port mapping grows a `name = "<short_service_name>"` field.
- **`discovery_name`** is what peers use to reach this service. We use `svc.global_name` (e.g., `proj_stage_sidecar`) — symmetric with the bundled `provides.host` template which already says `${global_service_name}` for both fixed and elastic. No doctrine-table change to engine `provides:` blocks needed.
- **`client_alias.port`** = the listening port; `client_alias.dns_name` = the global name. The alias is what Envoy uses to route traffic.

### Symmetry with fixed

On fixed, `provides.host.elastic: "${global_service_name}"` resolves to `proj_dev_sidecar` — the docker container name, reachable on the project's docker network by docker DNS. After Mod 014, the same value `proj_stage_sidecar` resolves on elastic via Service Connect. Identical magic-ref output on both foundations; identical app-side env var; only the underlying resolution mechanism differs. Parts-only symmetry preserved.

### Task definition port-mapping `name` field

To support `port_name` referencing, every container `portMappings` entry needs a `name` field. Currently emitted:

```jsonc
"portMappings": [{"containerPort": 8080, "protocol": "tcp"}]
```

becomes:

```jsonc
"portMappings": [{"containerPort": 8080, "protocol": "tcp", "name": "web"}]
```

The name = the short service name (`svc.name`). Required by AWS for Service Connect referencing.

### Cross-network concerns

A Service Connect namespace is env-wide, but actual reachability still depends on SG rules. A service on `internal` registers in the namespace; another service on `internal` can resolve AND reach it. A service on `web`-only would register, but `internal`-only peers couldn't reach it (no SG path). This matches the doctrine's existing network-isolation model — Service Connect doesn't bypass it.

For sidecar (internal-only) + web (internal + web): both register, both can resolve each other, the internal SG's self-ingress rule lets traffic flow. Worker (internal-only, no port): no service block (no port to discover), but `enabled = true` lets it resolve peers.

### What this mod does NOT do

- Does not change anything on fixed. Docker network DNS already resolves names; no work needed.
- Does not change `provides.host.elastic` templates in any bundled engine. The existing `${global_service_name}` value continues to mean the same thing — it's now actually resolvable.
- Does not add traffic-level features (retries, timeouts, mTLS). Service Connect supports them; they're out of scope for v1.
- Does not change how the ALB reaches `web`-network services. ALB → ECS via target group is unchanged.
- Does not introduce per-task overhead awareness in the doctrine (the Envoy sidecar consumes ~256 MiB and small CPU). Worth a doctrine note but minor.

## Proposed doctrine edits

Two small edits to `shape.md`:

1. In the **Elastic-Foundation** table (line 59 area), update the `service_discovery` row:

   Old:
   > | service_discovery | environment | AWS Cloud Map and ECS Service Connect | Provides DNS-based name resolution for [service]s within an env, so they can reach each other by name. |

   New:
   > | service_discovery | environment | ECS Service Connect over a Cloud Map HTTP namespace | Each ECS task carries an injected Envoy sidecar that resolves peer services by name. The namespace is named `<project>_<env>` and lives at the env tier. Services with a declared port register as discoverable; services without (e.g. `worker`) participate as clients only. Reachability remains gated by SG rules — Service Connect provides resolution, not authorization. |

2. A small note in the **Elastic-Foundation Runtime Shape** paragraph: ".. [service]s communicate over shared environment [network]s, which on elastic are AWS security groups within the project [vpc]. [service_discovery] (ECS Service Connect) allows [service]s to find each other by name; reachability remains gated by SG rules."

No edits to `cicl.md`, `transfer_tables.md`, or `infrastructure.md`. The engine `provides:` schema is unchanged.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `shape.md`: two clarifications described above. |
| `docex/plans/core/*.md` | `compiler.md`: small mention in the "env-tier HCL" lookup table or in the Worked Example section, noting Service Connect emission. |
| `tables/*.yml` | No change. |
| `src/docex/**` | `emit/templates/main.tf.j2`: add `aws_service_discovery_http_namespace.env` resource. `emit/hcl.py`: extend `render_task_definition` to add `name` to port mappings; extend `render_ecs_service` to emit `service_connect_configuration`. |
| `tests/**` | New unit tests: (a) `aws_service_discovery_http_namespace.env` appears in env-tier HCL; (b) every `aws_ecs_service` block contains `service_connect_configuration` with `enabled = true`; (c) services with a port get the `service {}` block; (d) services without a port don't; (e) `portMappings` entries have a `name` field. |

## Validation

1. `python3 -m pytest tests/unit/ -q` — all green.
2. `python3 -m pytest tests/integration/test_compile.py -q` — green.
3. Inspect the emitted `main.tf` for a multi-service project: confirm the namespace resource exists once, each ECS service has Service Connect config, and the discovery names match the global names.

Real-AWS smoke verification happens at Step 4 of the advance (the final test-project walks). No real apply during this mod.

## Decisions captured

1. **Service Connect, not raw Cloud Map.** AWS recommendation; less HCL per service; aligns with current best-practice ECS deployments.
2. **One namespace per env, not per project.** Service Connect namespaces are flat — a single per-env namespace simplifies the resolution model and matches the env-isolation principle.
3. **Discovery name = global name.** Preserves the existing `provides.host.elastic: "${global_service_name}"` semantics — no transfer-table changes needed.
4. **Every service gets `enabled = true`.** Required for client-side resolution. Services without a port skip the `service {}` block but still participate.
5. **`port_name` = short service name** (e.g., `sidecar`). Internal handle for the port mapping; doesn't appear in any consumer-facing value.
6. **No mTLS / retries / advanced traffic features in v1.** Pure name resolution. Future mods can layer on the policy features.

## Open questions

1. **Envoy sidecar resource overhead.** Service Connect injects an Envoy proxy into each task — ~256 MiB memory + small CPU. Worth a doctrine note in a future mod (e.g., a `cicl.md § Resources` aside) so operators sizing core services account for the implicit overhead. Not blocking for v1.

2. **Service Connect timeouts.** Default Envoy connection timeouts may be inappropriate for some workloads. Defer to a future "Service Connect tuning" mod or a project-local transfer table extension.

Neither blocks this mod.

# Mod 043 — Service Connect: Private DNS Namespace

Fourteenth mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Flips the Service Connect namespace resource type from HTTP to Cloud Map private DNS, enabling VPC-wide DNS resolution that mod 044's EC2-traefik variant will rely on.

## The Doctrine Change

From [`shape.md § Elastic-Foundation`](../../../../doctrine/infrastructure/shape.md#elastic-foundation):

> `service_discovery` | environment | ECS Service Connect over a Cloud Map **private DNS** namespace | Each ECS task carries an injected Envoy sidecar that resolves peer services by name. The namespace is named `${project}-${env}`, associated with the master VPC, and lives at the env tier. From inside the namespace (ECS tasks with Service Connect injected), services resolve by discoveryName alone (e.g. `myproject-prod-api`); from elsewhere in the master VPC (e.g. the EC2-traefik instance), they resolve as `<discoveryName>.<namespace>` (e.g. `myproject-prod-api.myproject-prod`) via the namespace's auto-created private hosted zone.

The shift: HTTP-namespace → private-DNS-namespace. The HTTP namespace requires the Envoy sidecar for resolution and is invisible to non-ECS-task consumers. The private DNS namespace creates an auto-managed Route53 private hosted zone associated with the master VPC, making service names resolvable from anywhere in the VPC (including the EC2-traefik instance arriving in mod 044).

## The change

**Single resource type swap, plus one reference update.**

### `src/docex/emit/templates/main.tf.j2:114`

Replace:

```hcl
resource "aws_service_discovery_http_namespace" "env" {
  name        = "{{ project }}-{{ env }}"
  description = "ECS Service Connect namespace for {{ project }} {{ env }}"
  tags = { ... }
}
```

with:

```hcl
resource "aws_service_discovery_private_dns_namespace" "env" {
  name        = "{{ project }}-{{ env }}"
  vpc         = data.terraform_remote_state.project.outputs.vpc_id
  description = "ECS Service Connect namespace for {{ project }} {{ env }}"
  tags = { ... }
}
```

Two new things:
1. **Resource type** flips from `aws_service_discovery_http_namespace` to `aws_service_discovery_private_dns_namespace`.
2. **`vpc` field** added — the private DNS namespace must be associated with a VPC. Reference the master VPC via the project-tier remote-state output (set up in mod 041).

The `name` is already `${project}-${env}` (hyphenated, mod 030). No change there.

Update the leading comment block: "Service discovery — ECS Service Connect over a Cloud Map **private DNS** namespace. Per shape.md § Elastic-Foundation, one namespace per env, associated with the master VPC. Resolvable VPC-wide so EC2-traefik (mod 044) and other non-ECS consumers can reach services by name."

### `src/docex/emit/hcl.py:460`

Update the ECS service `service_connect_configuration.namespace` reference:

```python
out.append("    namespace = aws_service_discovery_http_namespace.env.arn")
```

→

```python
out.append("    namespace = aws_service_discovery_private_dns_namespace.env.arn")
```

The ARN field is named `arn` on both resource types — clean swap.

### What stays the same

- Per-service `service_connect_configuration` blocks on `aws_ecs_service` resources: same shape. ECS handles registration the same way against either namespace type.
- `provides.host.elastic` template in `tables/roles/web.yml`: stays `${global_service_name}`. ECS tasks resolve by discoveryName from inside the namespace (Envoy sidecar handles it for both types). Mod 044's EC2-traefik (outside ECS netns) will construct the FQDN form `<discoveryName>.<namespace>` directly in its config emission, not via this provides ref.
- The namespace **name** `${project}-${env}` already matches doctrine (mod 030 fixed it).
- Tests verifying service registration happens via Service Connect.

## Ramifications

### Operational implication

After mod 043, every elastic stage/prod environment gets a Route53 private hosted zone auto-created and associated with the master VPC. The zone name is `${project}-${env}` (a single label, internal-only). This costs ~$0.50/month per hosted zone in Route53 pricing.

### Cross-namespace conflicts

Each env gets its own namespace, and the namespace name is unique per `(project, env)`. There's no cross-project naming collision because each project has its own `${project}-${env}` namespace.

### EC2-traefik dependency

Mod 044's EC2-traefik instance lives in the master VPC outside any ECS task netns. It needs to resolve service names via DNS (no Envoy sidecar). The private DNS namespace's auto-managed Route53 hosted zone makes this work — VPC DNS resolves `<svc>.${project}-${env}` to the running ECS task IPs.

Without mod 043's switch, mod 044 couldn't function. This is the reason for the ordering in the campaign.

### Test-projects compiled output

Same as prior mods: the test-projects' committed `infra/output/<env>/main.tf` will diff. Per campaign-wide deferral, not regenerated in this mod.

## Concrete file surface

- `src/docex/emit/templates/main.tf.j2:114` — resource type swap + new `vpc` field + comment update.
- `src/docex/emit/hcl.py:460` — namespace ARN reference type swap.

Two source files, three substantive lines plus a comment refresh.

### Tests

`tests/integration/test_compile.py`: any assertion on `aws_service_discovery_http_namespace.env` needs to flip to `aws_service_discovery_private_dns_namespace.env`. The `vpc` field reference should also be asserted as present and referencing the master VPC remote-state output.

`tests/unit/test_hcl_emitter.py`: the per-service `service_connect_configuration.namespace` assertion needs to reference the new resource type.

## Out of scope

- **No EC2-traefik changes** — that's mod 044, which is the next mod and depends on mod 043.
- **No `provides.host.elastic` changes** — current value works for ECS-side consumers; EC2-traefik will construct FQDN form directly in mod 044.
- **No HTTP-namespace fallback** — the doctrine commits to private DNS.
- **No `test_projects/{fixed,elastic}/` edits.**

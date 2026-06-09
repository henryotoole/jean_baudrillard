# Mod 041 — Elastic Master VPC as Preinfra

Twelfth mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Replaces the per-project VPC stack in `project.tf.j2` with data-source lookups against a shared master VPC managed as preinfra. Plus enforces the doctrine's single-AZ commitment for ECS workloads.

## The Doctrine Change

From [`shape2.md § Elastic-Foundation`](../../../../doctrine/infrastructure/shape2.md#elastic-foundation) and [`preinfra/elastic_master_network.md`](../../../../doctrine/infrastructure/preinfra/elastic_master_network.md):

> Master VPC: A master VPC shared by all projects. Contains centralized IGW, NAT, and four subnets: a public-private pair in the default AZ and a redundant public-private pair in a secondary AZ. The redundant pair is included only to satisfy the two-AZ requirement.

The master VPC is **prerequisite infrastructure** — operator-set-up out of docex's scope, verified by `docex preinfra production` (mod 042). docex consumes it via data-source lookups.

From [`cicl.md § Simplifications`](../../../../doctrine/infrastructure/cicl.md#simplifications):

> 1. `elastic` foundations only use AWS as a provider and only use one region: "us-east-1".
> 2. `elastic` foundations use "us-east-1a" as the primary AZ. We sometimes include a second AZ if required by AWS (e.g. for ALB's), but we avoid placing service containers in it.

## Concrete file surface

### `project.tf.j2` — delete per-project VPC stack

Delete these resource blocks (lines ~57–164):

- `aws_vpc.project`
- `aws_internet_gateway.project`
- `aws_subnet.public` (count 2)
- `aws_subnet.private` (count 2)
- `aws_eip.nat` (count 2)
- `aws_nat_gateway.project` (count 2)
- `aws_route_table.public`
- `aws_route_table.private` (count 2)
- `aws_route_table_association.public` (count 2)
- `aws_route_table_association.private` (count 2)

This block accounts for roughly 100 lines of the template. Delete cleanly.

### `project.tf.j2` — add data lookups

Replace with:

```hcl
# Master VPC + subnets are preinfra (operator-managed; see
# preinfra/elastic_master_network.md). Discovered by doctrine-prescribed
# tags. docex consumes via data sources only.
data "aws_vpc" "master" {
  tags = {
    managed_by = "docex-preinfra"
    Name       = "docex-master-vpc"
  }
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.master.id]
  }
  tags = {
    tier = "public"
  }
}

data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.master.id]
  }
  tags = {
    tier = "private"
  }
}

# Primary-AZ private subnet — single-AZ commitment per cicl.md §
# Simplifications. ECS workloads place here; only ALB and RDS subnet
# groups need both AZs.
data "aws_subnet" "primary_private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.master.id]
  }
  tags = {
    tier             = "private"
    availability_zone_hint = "us-east-1a"
  }
}
```

Notes:
- The `Name` and `managed_by` tags on the master VPC are doctrine-prescribed. The operator's preinfra setup (out of docex's scope) tags accordingly. Document the tag scheme in the docex-preinfra skill.
- `aws_subnets` (plural) returns IDs; `aws_subnet` (singular) returns full attributes. We need IDs (for `subnets = [...]` on ALB) and the primary private subnet's full ID (for single-AZ ECS placement).
- The `availability_zone_hint` tag is a docex convention because `aws_subnet` data sources can't filter on `availability_zone` directly via tags + AZ. Alternative: scope by literal AZ ID via `availability_zone` field. The implementer should pick whichever is simpler. *(Open question below.)*

### `project.tf.j2` — update intra-template references

After the data lookups:
- Line ~260 ALB SG `vpc_id = aws_vpc.project.id` → `data.aws_vpc.master.id`
- Line ~291 ALB `subnets = aws_subnet.public[*].id` → `data.aws_subnets.public.ids` (and remove the `# mod 041 will replace this` comment added in mod 038)

### `project.tf.j2` — update outputs

Outputs change from resource-backed to data-source-backed:

```hcl
output "vpc_id" {
  value = data.aws_vpc.master.id
}

output "public_subnet_ids" {
  value = data.aws_subnets.public.ids
}

output "private_subnet_ids" {
  value = data.aws_subnets.private.ids
}

# New: the primary-AZ private subnet for single-AZ workloads.
output "primary_private_subnet_id" {
  value = data.aws_subnet.primary_private.id
}
```

The output *names* stay the same so env-tier remote-state consumers continue to work without changes. New output `primary_private_subnet_id` for single-AZ ECS placement (next bullet).

### Env-tier single-AZ ECS placement

`src/docex/emit/hcl.py:666–668` currently places ECS services across all private subnets:

```python
out.append('  count           = length(data.terraform_remote_state.project.outputs.private_subnet_ids)')
out.append('  subnet_id       = data.terraform_remote_state.project.outputs.private_subnet_ids[count.index]')
```

(That's actually inside a different context — possibly aws_route53_record or similar. Let me confirm by reading lines 660–680.)

If those lines are emitting per-AZ ECS service instances or per-AZ resources, update to single-AZ:

```python
out.append('  subnet_id = data.terraform_remote_state.project.outputs.primary_private_subnet_id')
```

The `count` variation drops or becomes 1.

Similar for hcl.py:563 and :597 — `subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids` is what ECS service network_configuration takes; that should stay (ECS service auto-selects within the subnet list, and ECS itself can be told to prefer a single AZ via the subnet_ids list being a single-element array):

```python
out.append("  subnet_ids = [data.terraform_remote_state.project.outputs.primary_private_subnet_id]")
```

(The ECS service network_configuration.subnets is a list; with one entry, single-AZ placement is forced.)

The RDS subnet group (hcl.py somewhere) stays multi-AZ — AWS requires it.

Implementer should walk each `private_subnet_ids` use site and decide: single-AZ (`[primary_private_subnet_id]`) or multi-AZ (`private_subnet_ids`) based on the doctrine's "single-AZ for workloads, multi-AZ only for ALB+RDS" rule.

### Tests

`tests/integration/test_compile.py` — substantial updates:

- **Absent**: `aws_vpc.project`, `aws_internet_gateway.project`, `aws_subnet`, `aws_nat_gateway.project`, `aws_eip.nat`, `aws_route_table*`.
- **Present**: `data "aws_vpc" "master"`, `data "aws_subnets" "public"`, `data "aws_subnets" "private"`, `data "aws_subnet" "primary_private"`.
- **Outputs**: still present with same names; values reference data sources.
- **New output**: `primary_private_subnet_id` present.
- **Env-tier**: ECS service `subnet_ids` references `[primary_private_subnet_id]` (single-AZ).

## Ramifications

### Operator-side preinfra requirement

After this mod, an elastic project's `docex projinfra up production` requires the master VPC to already exist in the AWS account with the doctrine-prescribed tags. The `docex-preinfra` skill should document the master VPC setup (it's a TODO in the doctrine per the campaign brief).

For the operator's smoke-test work at end of campaign: the operator will need to bring up a master VPC by hand (or via a future preinfra automation tool) before re-incepting the elastic smoke project. That's accepted scope for the major-version cut.

### `vpc_id` output behavior

The `vpc_id` output still exists, but its value changes from a project-specific VPC ID to the shared master VPC ID. Env-tier consumers (security groups via remote state) reference `vpc_id` to attach SGs to the master VPC instead of per-project. This is the desired behavior — env-tier SGs live in the master VPC and govern cross-project isolation at the SG layer.

### Subnet cardinality

Currently the per-project VPC has exactly 2 public + 2 private subnets (one per AZ). After mod 041 the data source returns "however many subnets in master VPC carry the right tags." Doctrine spec: 4 total (2 public + 2 private). If the operator's master VPC happens to have more (e.g. for compatibility with other tooling), `data.aws_subnets.public.ids` returns all of them. For ALB this is OK (just spans more subnets). For RDS subnet group it's also OK. For ECS single-AZ placement (mod 041's single-AZ enforcement), the `primary_private_subnet_id` data source filters to one.

If the operator's VPC has fewer than 2 subnets per tier, data lookups fail — that's a real preinfra error, surfaced at apply time.

## Operator Decisions

1. **Tag scheme** — master VPC carries `Name = "docex-master-vpc"` + `managed_by = "docex-preinfra"`. Subnets carry `tier = "public"` or `tier = "private"`. The `docex-preinfra` skill documents this convention.
2. **Primary-AZ subnet lookup** — uses the data source's `availability_zone` field filter (not a tag). The primary-private data source filters by `vpc-id`, `tier = private` tag, AND `availability_zone = us-east-1a`.
3. **ECS single-AZ commit** — `network_configuration.subnets = [primary_private_subnet_id]`. ALB and RDS subnet group stay multi-AZ (both AWS-required).

## What This Mod Is NOT

- **No preinfra-implementation code** — mod 041 just consumes; mod 042's `preinfra <side>` does the existence check. Master VPC setup itself is operator-side via the docex-preinfra skill.
- **No EC2-traefik changes** — mod 044.
- **No RDS subnet group changes** — multi-AZ stays per AWS requirement.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No state migration logic** — if an operator has an existing project with a per-project VPC, the next tofu apply destroys it. Per operator decision, no in-flight consumers to worry about.

This is the largest pure-deletion mod of the campaign — the per-project VPC stack is ~100 lines coming out. Care needed to keep intra-template references consistent after the deletion.

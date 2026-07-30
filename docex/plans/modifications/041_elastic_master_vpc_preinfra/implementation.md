# Implementation — Mod 041 — Elastic Master VPC as Preinfra

## Context for fresh-context implementer

You are executing mod 041 of a 16-mod docex advance. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`shape.md § Elastic-Foundation`](../../../../doctrine/infrastructure/shape.md#elastic-foundation) — master VPC as preinfra.
- [`cicl.md § Simplifications`](../../../../doctrine/infrastructure/cicl.md#simplifications) — single-AZ commit rationale.
- [`preinfra/elastic_master_network.md`](../../../../doctrine/infrastructure/preinfra/elastic_master_network.md) — preinfra side (sparse; this mod sets the tag convention).

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- Master VPC tag scheme: `Name = "docex-master-vpc"` + `managed_by = "docex-preinfra"`. Subnets carry `tier = "public" | "private"`.
- Primary-AZ subnet via `availability_zone` field filter (not tag).
- ECS workloads pin to the primary-AZ private subnet via `subnet_ids = [primary_private_subnet_id]`. ALB and RDS stay multi-AZ.

## Step-by-step plan

### Step 1 — Delete per-project VPC stack from `project.tf.j2`

Edit `src/docex/emit/templates/project.tf.j2`. Delete these resource blocks (approximate lines 57–164):

- `aws_vpc.project`
- `aws_internet_gateway.project`
- `aws_subnet.public` (with `count = 2`)
- `aws_subnet.private` (with `count = 2`)
- `aws_eip.nat` (with `count = 2`)
- `aws_nat_gateway.project` (with `count = 2`)
- `aws_route_table.public`
- `aws_route_table.private` (with `count = 2`)
- `aws_route_table_association.public` (with `count = 2`)
- `aws_route_table_association.private` (with `count = 2`)

Roughly 100 lines deleted in one contiguous block. Also drop the leading section comment that names "VPC + IGW + public/private subnets across two AZs + NAT gateways" (it's stale).

Confirm by inspection that `data "aws_availability_zones" "available"` is no longer needed (it was used for AZ selection during subnet creation). If unused after the deletion, drop it too.

### Step 2 — Add data lookups for the master VPC

In the place where the deleted block lived:

```hcl
# ---------------------------------------------------------------------------
# Master VPC — preinfra. Operator brings it up out-of-band; docex consumes
# via tag-based data sources. See preinfra/elastic_master_network.md.
# ---------------------------------------------------------------------------
data "aws_vpc" "master" {
  tags = {
    Name       = "docex-master-vpc"
    managed_by = "docex-preinfra"
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

# Primary-AZ private subnet — single-AZ commit per cicl.md.
data "aws_subnet" "primary_private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.master.id]
  }
  filter {
    name   = "availability-zone"
    values = ["us-east-1a"]
  }
  tags = {
    tier = "private"
  }
}
```

### Step 3 — Update intra-`project.tf.j2` references

Search the rest of the template for any remaining `aws_vpc.project` / `aws_subnet.public` / `aws_subnet.private` references:

- ALB SG `vpc_id = aws_vpc.project.id` → `data.aws_vpc.master.id` (around line 260).
- ALB `subnets = aws_subnet.public[*].id` → `data.aws_subnets.public.ids` (around line 291). Remove the `# mod 041 will replace this` comment that mod 038 added.

There may be additional refs after the deletion shifts line numbers. Sweep:

```bash
grep -n 'aws_vpc\.project\|aws_subnet\.public\|aws_subnet\.private' src/docex/emit/templates/project.tf.j2
```

Should return zero after this step.

### Step 4 — Update outputs

Replace the existing outputs:

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

# Mod 041: primary-AZ private subnet for single-AZ ECS placement.
output "primary_private_subnet_id" {
  value = data.aws_subnet.primary_private.id
}
```

Output names preserved for backward compat with env-tier remote-state consumers; only the values' source switches.

### Step 5 — Switch env-tier ECS to single-AZ

Edit `src/docex/emit/hcl.py`. Find every use of `private_subnet_ids` (search):

```bash
grep -n 'private_subnet_ids' src/docex/emit/hcl.py
```

Per the doctrine's single-AZ for ECS workloads + multi-AZ for ALB/RDS subnet group:

- **ECS service network_configuration** (likely `hcl.py:563` and `:597`): change `subnet_ids = data.terraform_remote_state.project.outputs.private_subnet_ids` → `subnet_ids = [data.terraform_remote_state.project.outputs.primary_private_subnet_id]`. One-element list pins single-AZ.
- **RDS-related** (subnet group): KEEP `private_subnet_ids` (multi-AZ required by AWS for `aws_db_subnet_group`). Find the relevant site; verify it stays.
- **`hcl.py:666` `count = length(...private_subnet_ids)`**: if this is iterating over private subnets (e.g. EFS mount targets), evaluate per-resource. EFS needs one mount target per AZ → keep `private_subnet_ids`. ECS task placement → use primary single-AZ. The implementer must decide per use site; report which path each took.

Each `private_subnet_ids` site has a doctrine intent — workload (single-AZ) vs. AWS-required-multi-AZ. The implementer should make the call per site and document in the report.

### Step 6 — Tests

`tests/integration/test_compile.py` updates:

- **Absent in project main.tf**: `aws_vpc "project"`, `aws_internet_gateway "project"`, `aws_subnet "public"`, `aws_subnet "private"`, `aws_eip "nat"`, `aws_nat_gateway "project"`, `aws_route_table "public"`, `aws_route_table "private"`, `aws_route_table_association`.
- **Present in project main.tf**: `data "aws_vpc" "master"` with the prescribed tags, `data "aws_subnets" "public"`/`"private"` with the prescribed filters+tags, `data "aws_subnet" "primary_private"` with the AZ filter.
- **Outputs**: `vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `primary_private_subnet_id` all present; vpc_id references `data.aws_vpc.master.id`.
- **Env main.tf**: ECS service `subnet_ids` is a one-element list referencing `primary_private_subnet_id`; backing services (RDS) keep multi-AZ `private_subnet_ids`.

Adjust existing tests that asserted on per-project VPC/subnet resources.

### Step 7 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 8 — Sanity sweeps

```bash
# Per-project VPC stack gone
grep -rn 'aws_vpc "project"\|aws_subnet "public"\|aws_subnet "private"\|aws_nat_gateway "project"\|aws_eip "nat"\|aws_route_table "public"\|aws_route_table "private"' src/

# Master VPC data sources present
grep -rn 'data "aws_vpc" "master"\|data "aws_subnets" "public"\|data "aws_subnets" "private"\|data "aws_subnet" "primary_private"' src/

# Single-AZ ECS placement in env-tier
grep -n 'primary_private_subnet_id' src/docex/emit/hcl.py src/docex/emit/templates/main.tf.j2
```

First sweep: zero hits (in src/). Second: hits only in the project template. Third: hits in the ECS service emit site(s).

## Out of scope

- **No `docex preinfra` real checks** — mod 042 (next mod) implements the master VPC existence check.
- **No EC2-traefik variant** — mod 044.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No state-migration scripting** — operator decision: no in-flight consumers.
- **No docex-preinfra skill update** — that's a separate skill, not in mod 041's scope. The implementer should note the tag scheme in the mod's implementation report so the operator can update the skill.

## Done criteria

- [ ] Per-project VPC stack deleted from `project.tf.j2` (~100 lines).
- [ ] Master VPC + subnets data sources added with the operator-decided tags + AZ filter.
- [ ] Intra-template refs updated (ALB SG vpc_id, ALB subnets).
- [ ] Outputs preserved with same names; new `primary_private_subnet_id` output.
- [ ] Env-tier ECS uses single-AZ `[primary_private_subnet_id]`; RDS/EFS stay multi-AZ.
- [ ] Tests cover absent old resources, present new data sources, updated outputs, env-tier single-AZ ECS.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.
- [ ] Sanity sweeps clean.

Working tree dirty when finished. Do not commit.

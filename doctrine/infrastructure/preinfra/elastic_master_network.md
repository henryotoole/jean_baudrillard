---
stratum: conditional
---

# Elastic Master Network

On elastic, we use the "centralized egress" model for AWS. There will also be one "master" VPC which all projects, the NAT gateway, and the main IGW live within.

## Design

The elastic master network takes the form of one big VPC which contains all projects, an IGW, NAT for egress, and four standard subnets.

Note that two AZs are required per AWS mandate for ALBs and RDS deploys. The below structure has two subnets per AZ, and two AZ's, but the secondary AZ is effectively unused. See [this](../reasoning/ingress_and_egress.md#elastic-azs) for reasoning.

1. Master VPC
	1. IGW
	2. "public" Subnet (AZ 1), routes 0.0.0.0/0 to IGW
		1. NAT
		2. Per-project ALB (or EC2 self-hosting traefik)
	3. "private" Subnet (AZ 1), routes 0.0.0.0/0 to NAT in public subnet AZ 1
		1. SG for `web`
			1. `web`-network services
		2. SG for `internal`
			1. `internal`-network services.
	4. "public" subnet (AZ 2), routes 0.0.0.0/0 to IGW
		- Nothing in here
	5. "private" subnet (AZ 2), routes 0.0.0.0/0 to NAT in public subnet AZ 1
		- Nothing in here

NOTE: SG's live at the VPC level; the diagram shows where the *services* attached to those SGs run.

EGRESS: We'll have one IGW and NAT. Outbound signals get address translated in NAT, and pass to the internet through the IGW.

INGRESS: Will not be centralized. Instead, signals will be routed via Route53 down to the relevant "reverse proxy". There will be one reverse proxy / load balancer / TLS terminator per project, which will either be an ALB or EC2 instance performing the same role (more on that later).

## Resources

The master network is composed of the following AWS resources. They all carry the **preinfra** tag block from [`cicl.md § Naming and Tagging`](../cicl.md#naming-and-tagging) — `managed_by=doctrine-operator`, `infra_tier=prerequisite`, `shape_name`, `descriptor`, and `Name=${shape_name}_${descriptor}`. The VPC/IGW/route-table/subnet resources share `shape_name=master_network`; the NAT EIP and NAT gateway use `shape_name=nat_gateway`. Subnets additionally carry the resource-local, load-bearing `tier=public|private` tag (used by the subnet data-source lookups in `docex/src/docex/pipeline/preinfra.py` and the project-tier HCL emit at `templates/project.tf.j2`):

| Resource | Count | shape_name / descriptor / tags | Notes |
| -------- | ----- | ------------------------------ | ----- |
| VPC | 1 | `shape_name = master_network`, `descriptor = VPC` | The container for everything below. Single VPC per AWS account. The VPC's `shape_name`+`managed_by`+`infra_tier` are the load-bearing identity filter (see below). |
| Internet Gateway | 1 | `shape_name = master_network`, `descriptor = IGW` | Attached to the VPC; provides the egress path for public-subnet traffic and the ingress path for ALB/EC2-traefik. |
| Elastic IP | 1 | `shape_name = nat_gateway`, `descriptor = EIP` | Allocated for the NAT gateway. Counts against the per-region EIP quota (default 5; common to need an increase). |
| NAT Gateway | 1 | `shape_name = nat_gateway`, `descriptor = NAT` | In the primary-AZ public subnet. Single NAT shared across all projects' private subnets. |
| Public Subnet (primary AZ) | 1 | `shape_name = master_network`, `descriptor = public-az1`, `tier = public` | Hosts the NAT, plus every project's ALB or EC2-traefik. AZ `us-east-1a`. |
| Public Subnet (secondary AZ) | 1 | `shape_name = master_network`, `descriptor = public-az2`, `tier = public` | Empty in steady state — exists only to satisfy AWS's two-AZ requirement for ALBs. AZ `us-east-1b` (or any other us-east-1 AZ). |
| Private Subnet (primary AZ) | 1 | `shape_name = master_network`, `descriptor = private-az1`, `tier = private` | Where every project's ECS workloads run (single-AZ commitment; `availability-zone = us-east-1a`). |
| Private Subnet (secondary AZ) | 1 | `shape_name = master_network`, `descriptor = private-az2`, `tier = private` | Empty in steady state — exists for RDS subnet groups and EFS mount targets that AWS requires to span two AZs. AZ `us-east-1b`. |
| Public Route Table | 1 | `shape_name = master_network`, `descriptor = public-rt` | Default route 0.0.0.0/0 → IGW. Associated with both public subnets. |
| Private Route Table | 1 | `shape_name = master_network`, `descriptor = private-rt` | Default route 0.0.0.0/0 → NAT gateway. Associated with both private subnets. |

**Region:** `us-east-1` (doctrine-pinned per [`cicl.md § Simplifications`](../cicl.md#simplifications)).

**CIDR conventions** (suggested; the doctrine doesn't require these specific blocks, only that they be non-overlapping with the operator's other VPCs):

| Resource | CIDR | Capacity |
| -------- | ---- | -------- |
| VPC | `10.20.0.0/16` | 65 534 hosts |
| Public AZ1 | `10.20.0.0/24` | 251 hosts |
| Public AZ2 | `10.20.1.0/24` | 251 hosts |
| Private AZ1 | `10.20.2.0/24` | 251 hosts |
| Private AZ2 | `10.20.3.0/24` | 251 hosts |

The `/24` subnets give ample room for ECS-task ENIs and project-tier ALBs without crowding. The VPC `/16` leaves the upper half (`10.20.128.0/17`) free for future expansion (additional AZs, additional tiers).

### Why these exact tags

The `data "aws_vpc" "master"` lookup in [`docex/src/docex/emit/templates/project.tf.j2`](../../../docex/src/docex/emit/templates/project.tf.j2) and the precondition check in [`docex/src/docex/pipeline/preinfra.py`](../../../docex/src/docex/pipeline/preinfra.py) both filter the master VPC on the **semantic identity tags** — `managed_by=doctrine-operator` **AND** `infra_tier=prerequisite` **AND** `shape_name=master_network`. They do **not** filter on the redundant console-only `Name`. The subnet lookups additionally filter on the resource-local `tier=public|private`. Any deviation in these specific tag values breaks `docex projinfra up production` and `docex preinfra production` — neither command takes a tag override; the tags are the contract.

### Migration from earlier docex

Master networks stood up under earlier docex were tagged `managed_by=docex-preinfra` and `Name=docex-master-*` (no `infra_tier`/`shape_name`), and the VPC lookup matched on `Name=docex-master-vpc`+`managed_by=docex-preinfra`. The current docex filters on the semantic tags above instead, so an existing master network **must be re-tagged** before this docex version can find it. Re-tag the VPC (and, for consistency, every master-network resource) with `aws ec2 create-tags`, e.g. for the VPC:

```bash
aws ec2 create-tags --region us-east-1 --resources "$VPC_ID" \
    --tags Key=managed_by,Value=doctrine-operator \
           Key=infra_tier,Value=prerequisite \
           Key=shape_name,Value=master_network \
           Key=descriptor,Value=VPC \
           Key=Name,Value=master_network_VPC
```

Apply the analogous re-tag to the IGW, route tables, NAT EIP/gateway (`shape_name=nat_gateway`), and the four subnets (keeping each subnet's `tier=public|private`). The old `managed_by=docex-preinfra` and `Name=docex-master-*` tags can be removed (`aws ec2 delete-tags`) once the new set is in place. Until the VPC carries the three semantic identity tags, `preinfra`/`projinfra` will report the master VPC as missing.

## Implementation

The doctrine does **not** ship an OpenTofu module or Ansible playbook for the master network — it is prerequisite infrastructure, sized once per AWS account, with cadence so low that automation is overkill. The operator brings it up by hand once per AWS account (via the AWS CLI, the AWS console, or a bespoke OpenTofu module they choose to maintain outside the doctrine).

`docex projinfra up production` reads the master VPC's existence via tag-filtered data sources; it does not create or own any of the resources above.

## Setup Instructions

### Prerequisites

- AWS CLI configured (`~/.aws/credentials`) with permissions to create VPC, subnet, IGW, NAT, EIP, and route-table resources in `us-east-1`.
- Sufficient EIP quota in `us-east-1` for the NAT gateway (1 EIP). Check current usage with `aws ec2 describe-addresses --query 'length(Addresses)'` and the quota with `aws service-quotas get-service-quota --service-code ec2 --quota-code L-0263D0A3`. Request an increase if needed (default is 5).
- No existing VPC in the account tagged `managed_by=doctrine-operator`+`infra_tier=prerequisite`+`shape_name=master_network` (idempotency is by lookup; duplicate masters would confuse the data sources).

### Stand-up via AWS CLI

The commands below stand up the full resource set in `us-east-1`. Run them in order; each captures the resource ID it created for the next step. Replace the CIDR blocks below if the suggested defaults conflict with your account's existing VPCs.

```bash
REGION=us-east-1
PRIMARY_AZ=us-east-1a
SECONDARY_AZ=us-east-1b
VPC_CIDR=10.20.0.0/16
PUB_AZ1_CIDR=10.20.0.0/24
PUB_AZ2_CIDR=10.20.1.0/24
PRIV_AZ1_CIDR=10.20.2.0/24
PRIV_AZ2_CIDR=10.20.3.0/24

# Common preinfra identity tags (cicl.md § Naming and Tagging). Every
# resource adds its own shape_name / descriptor / Name on top of these.
BASE="{Key=managed_by,Value=doctrine-operator},{Key=infra_tier,Value=prerequisite}"

# 1. VPC
VPC_ID=$(aws ec2 create-vpc \
    --cidr-block "$VPC_CIDR" \
    --tag-specifications "ResourceType=vpc,Tags=[$BASE,{Key=shape_name,Value=master_network},{Key=descriptor,Value=VPC},{Key=Name,Value=master_network_VPC}]" \
    --region "$REGION" \
    --query 'Vpc.VpcId' --output text)
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames --region "$REGION"
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support --region "$REGION"
echo "VPC: $VPC_ID"

# 2. Internet Gateway
IGW_ID=$(aws ec2 create-internet-gateway \
    --tag-specifications "ResourceType=internet-gateway,Tags=[$BASE,{Key=shape_name,Value=master_network},{Key=descriptor,Value=IGW},{Key=Name,Value=master_network_IGW}]" \
    --region "$REGION" \
    --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --vpc-id "$VPC_ID" --internet-gateway-id "$IGW_ID" --region "$REGION"
echo "IGW: $IGW_ID"

# 3. Subnets (4). `descriptor` differentiates them; `tier` is the
# resource-local load-bearing tag the subnet data sources filter on.
create_subnet() {
    local descriptor="$1" cidr="$2" az="$3" tier="$4"
    aws ec2 create-subnet \
        --vpc-id "$VPC_ID" --cidr-block "$cidr" --availability-zone "$az" \
        --tag-specifications "ResourceType=subnet,Tags=[$BASE,{Key=shape_name,Value=master_network},{Key=descriptor,Value=$descriptor},{Key=tier,Value=$tier},{Key=Name,Value=master_network_$descriptor}]" \
        --region "$REGION" \
        --query 'Subnet.SubnetId' --output text
}
PUB_AZ1=$(create_subnet public-az1  "$PUB_AZ1_CIDR"  "$PRIMARY_AZ"   public)
PUB_AZ2=$(create_subnet public-az2  "$PUB_AZ2_CIDR"  "$SECONDARY_AZ" public)
PRIV_AZ1=$(create_subnet private-az1 "$PRIV_AZ1_CIDR" "$PRIMARY_AZ"   private)
PRIV_AZ2=$(create_subnet private-az2 "$PRIV_AZ2_CIDR" "$SECONDARY_AZ" private)
echo "Subnets: pub_az1=$PUB_AZ1 pub_az2=$PUB_AZ2 priv_az1=$PRIV_AZ1 priv_az2=$PRIV_AZ2"

# 4. EIP for the NAT gateway
EIP_ALLOC=$(aws ec2 allocate-address \
    --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[$BASE,{Key=shape_name,Value=nat_gateway},{Key=descriptor,Value=EIP},{Key=Name,Value=nat_gateway_EIP}]" \
    --region "$REGION" \
    --query 'AllocationId' --output text)
echo "EIP: $EIP_ALLOC"

# 5. NAT Gateway (in the primary-AZ public subnet)
NAT_ID=$(aws ec2 create-nat-gateway \
    --subnet-id "$PUB_AZ1" --allocation-id "$EIP_ALLOC" \
    --tag-specifications "ResourceType=natgateway,Tags=[$BASE,{Key=shape_name,Value=nat_gateway},{Key=descriptor,Value=NAT},{Key=Name,Value=nat_gateway_NAT}]" \
    --region "$REGION" \
    --query 'NatGateway.NatGatewayId' --output text)
echo "NAT: $NAT_ID (waiting for available...)"
aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_ID" --region "$REGION"

# 6. Public route table
PUB_RT=$(aws ec2 create-route-table \
    --vpc-id "$VPC_ID" \
    --tag-specifications "ResourceType=route-table,Tags=[$BASE,{Key=shape_name,Value=master_network},{Key=descriptor,Value=public-rt},{Key=Name,Value=master_network_public-rt}]" \
    --region "$REGION" \
    --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id "$PUB_RT" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID" --region "$REGION" >/dev/null
aws ec2 associate-route-table --route-table-id "$PUB_RT" --subnet-id "$PUB_AZ1" --region "$REGION" >/dev/null
aws ec2 associate-route-table --route-table-id "$PUB_RT" --subnet-id "$PUB_AZ2" --region "$REGION" >/dev/null
echo "Public RT: $PUB_RT"

# 7. Private route table
PRIV_RT=$(aws ec2 create-route-table \
    --vpc-id "$VPC_ID" \
    --tag-specifications "ResourceType=route-table,Tags=[$BASE,{Key=shape_name,Value=master_network},{Key=descriptor,Value=private-rt},{Key=Name,Value=master_network_private-rt}]" \
    --region "$REGION" \
    --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id "$PRIV_RT" --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_ID" --region "$REGION" >/dev/null
aws ec2 associate-route-table --route-table-id "$PRIV_RT" --subnet-id "$PRIV_AZ1" --region "$REGION" >/dev/null
aws ec2 associate-route-table --route-table-id "$PRIV_RT" --subnet-id "$PRIV_AZ2" --region "$REGION" >/dev/null
echo "Private RT: $PRIV_RT"

echo "Master network up. Verify with: docex preinfra production (from any elastic project root)."
```

The script above is intentionally a sequence of CLI calls rather than a CloudFormation template or Terraform module — the master network gets stood up once per AWS account and lives for years, so deterministic re-application isn't the value it would be for project-tier infra.

> TODO: refine after first stand-up. CIDR conventions, AZ choices, and any AWS-side quirks the operator hits should land here as concrete notes.

### Verification

From any project root with docex installed:

```bash
./bin/docex preinfra production
```

Exits 0 when the VPC, both public subnets (tagged `tier=public`), both private subnets (tagged `tier=private`), and a primary-AZ private subnet (in `us-east-1a`) are all present. Each missing resource is enumerated as a separate failure in a single pass — fix them all, then re-run.

`docex preinfra` does **not** probe IGW, NAT, EIP, or route tables. The data-source lookups in project-tier HCL probe the VPC + subnets only; the routing path is exercised by every `tofu apply` against the env tier (an ECS task that can't reach SSM/ECR via the NAT fails the deploy loudly).

### Coexistence with other workloads in the same AWS account

There is one master network per AWS account, and multiple projects coexist within the same master VPC — each project's projinfra creates its own ALB / EC2-traefik, ECR repos, Route53 zone, and security groups, scoped by the `${project}` prefix. The master network itself doesn't carry project identity.

If the AWS account is already hosting non-doctrine workloads (legacy VPCs, sandbox EC2 instances), the master VPC sits alongside them — pick a non-overlapping CIDR block and run the stand-up commands above. `docex preinfra production` tag-filters so it ignores anything tagged differently.

## Teardown

Master-network teardown is rare — the resources have low ongoing cost (~$33/mo for the NAT gateway plus the EIP) and tearing it down breaks every elastic project in the account simultaneously. The teardown sequence (reverse of stand-up) is:

1. Confirm no projects in the account have running env-tier resources (run `verify_clean.sh` for each project, expect green).
2. `aws ec2 disassociate-route-table` + `delete-route-table` for both route tables.
3. `aws ec2 delete-nat-gateway` then wait for deletion (~1–2 min).
4. `aws ec2 release-address --allocation-id "$EIP_ALLOC"`.
5. `aws ec2 detach-internet-gateway` + `delete-internet-gateway`.
6. `aws ec2 delete-subnet` × 4.
7. `aws ec2 delete-vpc`.

Do **not** tear down the master network just to "rebuild it cleanly" — re-running the stand-up commands against a partially-torn-down state will fail in surprising ways. Either keep the network up indefinitely (recommended) or commit to a full teardown + re-stand-up.

## EIP quota caveat

The NAT gateway requires one EIP. AWS's default EIP quota per region is 5 (per [EC2 service quotas, `L-0263D0A3`](https://us-east-1.console.aws.amazon.com/servicequotas/home/services/ec2/quotas/L-0263D0A3)), shared across:

- The master-network NAT (this file: 1 EIP).
- Per-project EC2-traefik instances with `reverse_proxy: ec2_traefik_eip` (1 EIP each).
- Any other operator workloads in the same region.

Accounts running multiple elastic projects on the EC2-traefik EIP variant **will hit this quota fast.** Either:

- Request a quota increase from AWS (the cleanest fix).
- Use `reverse_proxy: ec2_traefik_pip` (Public IP, no EIP) for projects that can tolerate IP changes on instance restart.
- Use `reverse_proxy: alb` (default; no EIP).

> TODO: refine after first stand-up. If the operator hits a real quota error during initial stand-up, document the resolution path here (typically a quota-increase request via the console, granted in minutes).

# Mod 060 — Resource tagging standard

Final mod of the `001_skill_update` advance. Implements the cross-infrastructure
tagging standard the operator authored in
[`cicl.md § Naming and Tagging`](../../../../doctrine/infrastructure/cicl.md#naming-and-tagging),
bringing every elastic resource docex emits (and every tag-based lookup) into
line with it. The current tagging is ad-hoc per the inventory below; this mod
makes it uniform.

## The standard (authored in cicl.md)

Three tag blocks, by tier. Every elastic resource gets exactly one block plus any
resource-local load-bearing tags.

- **preinfra**: `managed_by=doctrine-operator`, `infra_tier=prerequisite`,
  `shape_name`, `descriptor`, `Name=${shape_name}_${descriptor}`.
- **projinfra**: `managed_by=doctrine`, `infra_tier=project`, `shape_name`,
  `descriptor`, `project`, `Name=${project}_${shape_name}_${descriptor}`.
- **envinfra**: `managed_by=doctrine`, `infra_tier=environment`, `shape_name`,
  `descriptor`, `project`, `env`, `service`, `role`,
  `Name=${project}_${env}_${service}`.

`shape_name` comes from [`shape.md § Elastic-Foundation`](../../../../doctrine/infrastructure/shape.md#elastic-foundation);
`etc` when no shape applies. `descriptor` is a loose differentiator (AWS abbrev
where natural). `Name` is redundant (AWS-console ergonomics only).

## Decisions (from design discussion)

1. **Env-scoped resources** (ECS cluster, Service Connect namespace, network SGs)
   have no single service/role, but the operator chose to keep all tag KEYS
   present everywhere: such resources get `service=etc`, `role=etc`.
2. **`Name` collision fix** (flagged for review): with `service=etc`, the
   authored `Name=${project}_${env}_${service}` would make every env-scoped
   resource `${project}_${env}_etc` (duplicate). Since `Name` is console-only,
   the helper falls back to the **descriptor** for env-scoped Names
   (`${project}_${env}_${descriptor}`), keeping them unique. Per-service Names are
   unchanged (`${project}_${env}_${service}`).
3. **Master-network filter migration** (breaking for existing elastic deploys):
   docex's VPC data-source/precondition lookups move OFF the old
   `Name=docex-master-vpc` + `managed_by=docex-preinfra` and ONTO the semantic
   tags `managed_by=doctrine-operator` + `infra_tier=prerequisite` +
   `shape_name=master_network` (not the redundant `Name`). Subnet lookups keep
   `tier=public|private` (resource-local load-bearing, unchanged). Existing
   master networks must be re-tagged; a migration note is added to
   `elastic_master_network.md`.

## shape_name / descriptor map

**Preinfra** (operator-applied; docex only reads via filters):

| Resource | shape_name | descriptor | resource-local |
| --- | --- | --- | --- |
| VPC | master_network | VPC | |
| IGW | master_network | IGW | |
| Public RT / Private RT | master_network | public-rt / private-rt | |
| Public subnet az1/az2 | master_network | public-az1 / public-az2 | `tier=public` |
| Private subnet az1/az2 | master_network | private-az1 / private-az2 | `tier=private` |
| NAT EIP | nat_gateway | EIP | |
| NAT Gateway | nat_gateway | NAT | |
| Observability EC2 / EBS | observability_backend | EC2 / EBS | |

**Projinfra** (docex-emitted, `project.tf.j2` + `bootstrap.py`):

| Resource | shape_name | descriptor | resource-local |
| --- | --- | --- | --- |
| Route53 zone | dns | zone | |
| ACM stage / prod cert | cert_manager | stage-cert / prod-cert | |
| ALB / ALB SG | reverse_proxy | ALB / ALB-SG | |
| EC2-traefik instance | reverse_proxy | EC2 | |
| traefik SG | reverse_proxy | SG | (drop old `purpose=ec2_traefik`) |
| traefik IAM role | reverse_proxy | iam-role | |
| traefik log group | reverse_proxy | logs | |
| traefik SSM config | reverse_proxy | config | |
| traefik ACME EBS | reverse_proxy | acme-ebs | **keep `purpose=ec2_traefik_acme`** |
| traefik EIP | reverse_proxy | EIP | |
| ECR repo (per svc) | container_registry | `<service>` | |
| task-exec IAM role | etc | exec-role | |
| tofu state S3 bucket | etc | tofu-state | (tagged via bootstrap API) |
| tofu lock DDB table | etc | tofu-locks | (tagged via bootstrap API) |

**Envinfra** (docex-emitted, `main.tf.j2` + `hcl.py`):

Per-service (`service=${name}`, `role=${role}`):

| Resource | shape_name | descriptor |
| --- | --- | --- |
| task definition | core_service / backing_service | task-def |
| _migrate task def | core_service | migrate-task-def |
| ECS service | core_service | ecs-svc |
| RDS instance | backing_service | RDS |
| ElastiCache | backing_service | cache |
| S3 bucket (object_store) | backing_service | S3 |
| EFS filesystem | backing_service | EFS |
| CloudWatch log group | core_service | logs |
| scheduler invocation role | core_service | scheduler-role |

Env-scoped (`service=etc`, `role=etc`):

| Resource | shape_name | descriptor |
| --- | --- | --- |
| ECS cluster | etc | ecs-cluster |
| Service Connect namespace | service_discovery | namespace |
| network SG | network | `<web\|internal\|…>` (the network short name) |

`core_service` vs `backing_service` for the per-service `shape_name` is chosen by
`svc.is_core`.

## Mechanism

A single source of truth: `src/docex/emit/tags.py` with `standard_tags(...)`
returning the correct ordered dict per tier (and the `Name`/`service=etc`
rules baked in), plus a render helper for HCL and a Jinja global so
`project.tf.j2` / `main.tf.j2` call it instead of hand-writing `tags = {…}`.
`bootstrap.py` uses the same function to build the API tag set for the S3 bucket
and DDB table. This kills the ~25-site drift and makes the next resource's tags a
one-liner.

## Doctrine touched (aligned to the operator's cicl.md standard)

- `specifics/transfer_tables.md § Per-resource (elastic)` — replace the old
  5-tag block with the envinfra block + pointer to cicl.md for the full
  three-block standard.
- `preinfra/elastic_master_network.md` — resource-table tags, the `create-tags`
  CLI, the "Why these exact tags" data-source contract, and a **migration note**
  for re-tagging existing master networks.
- `preinfra/telemetry_preinfra.md` — observability-backend tags → preinfra block
  (`shape_name=observability_backend`); repoint the duplicate-instance guard.
- `specifics/projinfra/{elastic_route53_zone,elastic_alb,elastic_acm_certs,elastic_ecr,elastic_iam,elastic_state_backend,ec2_traefik}.md`
  — update each tag reference to point at cicl.md's projinfra block (Route53 and
  the old 5-tag pattern drop `env`/`service`/`role`).

## Risk

The master-network filter migration is the load-bearing hazard: get the new
filter wrong (or forget the smoke network's re-tag) and `preinfra production` /
`projinfra up production` can't find the VPC. The compile is offline-pure so unit
tests catch emit shape; the filter change is validated against the smoke walk
(operator) — which must re-tag its master network first.

## Artifacts

- `doctrine/**` — above.
- `src/docex/emit/tags.py` (new), `emit/hcl.py`, `emit/templates/{project,main}.tf.j2`,
  `pipeline/preinfra.py` (filter), `pipeline/bootstrap.py` (S3/DDB tags),
  `aws/*` only if the filter API needs a multi-tag VPC lookup.
- `tests/**` — helper unit tests + per-tier emit assertions + the new VPC filter.

# Elastic Bootstrap

This file describes the one-shot setup required to make an elastic-foundation project usable. As with other specifics, this is documentation for the implementer of `docex` and the curious developer; it is not meant to be loaded as general doctrine context.

## Purpose

Two pieces of project-tier infrastructure must exist before any elastic environment can be released:

1. **An OpenTofu state backend** — a place to store the mapping between HCL resources and the real-world AWS resources they manage. Without it, OpenTofu has no memory of what it has created and cannot compute meaningful diffs between desired and actual state. See [release_mechanism.md](./release_mechanism.md#elastic-foundation-opentofu) for the role state plays in releases.
2. **The project-tier infrastructure itself** — the VPC, Route53 hosted zone, ACM certificate, subnets, and ECR repositories shared across every elastic environment of the project. Per [shape2.md](../shape2.md#description-of-shape), this tier is shared across stage and prod; each env-tier `main.tf` consumes its outputs via `data "terraform_remote_state" "project"`.

The bootstrap creates the state backend directly (via the AWS API, since OpenTofu itself can't yet run), and then applies the project-tier HCL emitted by [`./bin/docex compile`](../docex.md#compile) at `infra/output/project/main.tf`. Once both are in place, each env's `release` is just an env-tier `tofu apply` against a backend that already has every cross-environment dependency available.

## What the Bootstrap Creates

### State backend

Two AWS resources, both at the project tier, both shared across all elastic environments of the project. The description below is the source of truth; the `./bin/docex bootstrap` command is a faithful automation of it, and an operator can reproduce the same setup by hand in the AWS console (or via `aws` CLI) if needed. OpenTofu does not care how the resources came into existence — only that they exist with the right configuration when it tries to use them.

#### S3 bucket for state

- **Name:** derived from the project name by applying the `s3` naming policy (see [transfer_tables.md § Naming Policies](./transfer_tables.md#naming-policies)) to `<project>_tofu_state`. For a project named `docex_smoke_elastic`, the rendered bucket name is `docex-smoke-elastic-tofu-state` — S3 requires lowercase and rejects underscores.
- **Versioning:** enabled — so a corrupted or mistakenly-edited state file can be rolled back
- **Server-side encryption:** enabled (AES256 / SSE-S3)
- **Public access:** all four block-public-access settings enabled
- **Region:** the project's elastic region (per CICL simplifications, currently always `us-east-1`)

#### DynamoDB table for locking

- **Name:** derived from the project name by applying the `ddb` naming policy to `<project>_tofu_locks`. DynamoDB accepts both underscores and hyphens; the doctrine preserves underscores. For `docex_smoke_elastic`, the rendered table name is `docex_smoke_elastic_tofu_locks`.
- **Primary key:** attribute `LockID` of type `String` — this is the schema OpenTofu's S3 backend expects
- **Billing mode:** on-demand (pay-per-request) — cheap for the low write volume of state locks
- **Region:** same as the state bucket

OpenTofu's S3 backend writes a lock record to this table when `tofu apply` starts and removes it when finished. Concurrent applies see the lock and either wait or fail loudly, preventing two operators from corrupting state simultaneously.

### Project-tier infrastructure

Applied by OpenTofu against `infra/output/project/main.tf`, with its own state file at `key = "project/terraform.tfstate"` in the bucket above. Each resource appears once per project and is referenced by every env's `main.tf`.

All resource identifiers are formed by applying the matching naming policy from [transfer_tables.md § Naming Policies](./transfer_tables.md#naming-policies): S3 → `s3`, RDS → `rds`, ALB → `alb`, ECS → `ecs`, ECR repo → `ecr_repo`, IAM → `iam`, SSM path → `ssm_path`. This is the single place name translation happens, so projects with underscore-bearing names compile consistently across every emit site.

- **Route53 hosted zone** for the project's `domain:` (e.g. `<project>.<parent>.<tld>`). `docex` creates the zone; the operator NS-delegates from the parent (registrar or parent Route53 zone). Zone outputs include the name servers the operator must use for the delegation.
- **ACM certificate** covering `*.<domain>` plus per-env wildcards (`*.dev.<domain>`, `*.test.<domain>`, `*.stage.<domain>`, `*.www.<domain>`), with DNS validation records emitted into the project zone.
- **VPC** (`10.0.0.0/16`), one IGW, two NAT gateways, two public subnets and two private subnets across two AZs. Public subnets carry `tier=public` tags; private subnets `tier=private`. Route tables wire egress through the NAT gateways for private subnets and through the IGW for public ones.
- **ECR repositories** — one per core service (`<project>/<svc>`), with `MUTABLE` tag-immutability. Created here rather than ad-hoc by `./bin/docex containerize` so the registry surface is part of project state.
- **Outputs** — `vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `zone_id`, `zone_name_servers`, `certificate_arn`, `ecr_repository_<svc>_url` for each core service. Each env's `main.tf` reads these via `data "terraform_remote_state" "project"`.

## `./bin/docex bootstrap`

`./bin/docex bootstrap` is the convenience command that creates the resources described above. It is **idempotent** at every step:

1. **State backend.** If the S3 bucket and DynamoDB lock table exist and match the expected configuration, the command verifies them and continues. If either is missing, it is created. If either has drifted (e.g., versioning was disabled by hand), the command reconciles it to the expected state and reports what it changed.
2. **Project-tier apply.** The command runs `tofu init` against `infra/output/project/main.tf` (which the operator must have produced via `./bin/docex compile`), then proceeds in one of two phases described below. Once both phases have run successfully, every subsequent `bootstrap` invocation re-runs the full apply and is a no-op when state is in sync.

Re-running is always safe and produces no changes when state is correct. This makes the command suitable as a periodic sanity check.

### Two-phase project-tier apply

ACM DNS validation requires the project's Route53 zone to be reachable via the public DNS chain — which it only is once the operator has NS-delegated from the parent (registrar or parent hosted zone). To avoid hanging the apply on a delegation the operator has yet to perform, `./bin/docex bootstrap` splits the project-tier apply into two phases:

1. **Phase 1 — zone only.** If `aws_route53_zone.project` is not yet in state, the bootstrap runs `tofu apply -target=aws_route53_zone.project`, then reads the zone's NS records and prints them along with the next-step instructions. The bootstrap exits 0; the rest of the project-tier resources have not been created yet.
2. **Phase 2 — full apply.** Once the operator has NS-delegated the project domain (records take a few minutes to propagate), they re-run `./bin/docex bootstrap`. This time the zone is already in state, so the bootstrap runs an untargeted `tofu apply`. The ACM certificate validates against the now-reachable zone, the VPC and subnets come up, and the ECR repositories appear. If the delegation hasn't propagated, ACM cert validation fails the apply — the bootstrap surfaces a hint pointing at the delegation requirement.

Phase detection is observed from `tofu state list`, not stored separately. The operator's mental model is single-command: `./bin/docex bootstrap`, do the delegation work it asks for, `./bin/docex bootstrap` again, done.

## When to Run It

For an elastic-foundation project, after `./bin/docex compile` and before the first `./bin/docex release` for `stage` or `prod`. Concretely:

1. Author `project.yml` and `infra/infra.yml` with `foundation: elastic`.
2. `./bin/docex compile` — emits the project-tier `main.tf` along with the env-tier ones.
3. `./bin/docex bootstrap` — creates the state backend and runs phase 1 of the project-tier apply.
4. NS-delegate the project domain to the printed name servers at the parent.
5. `./bin/docex bootstrap` — runs phase 2; project-tier infrastructure complete.

After this, releases (`./bin/docex release stage` / `./bin/docex release prod`) only need to apply env-tier HCL.

For fixed-foundation projects, `./bin/docex bootstrap` is a no-op.

## Out of Scope

The bootstrap does *not* create:
- The AWS account itself — prerequisite infrastructure.
- IAM roles for deployment — managed by OpenTofu in subsequent applies.
- The NS delegation from the parent registrar or parent hosted zone — the operator must do this between the two bootstrap phases.
- Env-tier resources (ALB, RDS, ECS services, etc.) — those are emitted by `compile` into each env's `main.tf` and applied by `./bin/docex release`.
- SSM Parameter Store entries for secrets — these are populated by `./bin/docex release` from the project's `.env` files on every deploy; see [release_mechanism.md](./release_mechanism.md#secrets) for the secrets flow.
- Anything for fixed-foundation projects.

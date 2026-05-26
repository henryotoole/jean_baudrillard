# Elastic Bootstrap

This file describes the one-shot setup required to make an elastic-foundation project usable. As with other specifics, this is documentation for the implementer of `docex` and the curious developer; it is not meant to be loaded as general doctrine context.

## Purpose

OpenTofu requires a persistent **state backend** — a place to store the mapping between HCL resources and the real-world AWS resources they manage. Without it, OpenTofu has no memory of what it has created and cannot compute meaningful diffs between desired and actual state. See [release_mechanism.md](./release_mechanism.md#elastic-foundation-opentofu) for the role state plays in releases.

The bootstrap creates only the state backend itself. Every other project-level and environment-level resource (VPC, ECR, subnets, ALB, RDS, etc.) is managed by OpenTofu in subsequent `docex compile` and `docex release` cycles, using the state backend the bootstrap created.

## What the Bootstrap Creates

Two AWS resources, both at the project tier, both shared across all elastic environments of the project. The description below is the source of truth; the `docex bootstrap` command is a faithful automation of it, and an operator can reproduce the same setup by hand in the AWS console (or via `aws` CLI) if needed. OpenTofu does not care how the resources came into existence — only that they exist with the right configuration when it tries to use them.

### S3 bucket for state

- **Name:** `<project>-tofu-state` (deterministic from the project name in `project.yml`)
- **Versioning:** enabled — so a corrupted or mistakenly-edited state file can be rolled back
- **Server-side encryption:** enabled (AES256 / SSE-S3)
- **Public access:** all four block-public-access settings enabled
- **Region:** the project's elastic region (per CICL simplifications, currently always `us-east-1`)

### DynamoDB table for locking

- **Name:** `<project>-tofu-locks` (deterministic from the project name)
- **Primary key:** attribute `LockID` of type `String` — this is the schema OpenTofu's S3 backend expects
- **Billing mode:** on-demand (pay-per-request) — cheap for the low write volume of state locks
- **Region:** same as the state bucket

OpenTofu's S3 backend writes a lock record to this table when `tofu apply` starts and removes it when finished. Concurrent applies see the lock and either wait or fail loudly, preventing two operators from corrupting state simultaneously.

## `docex bootstrap`

`docex bootstrap` is the convenience command that creates the resources described above. It is **idempotent**:

1. If both resources exist and match the expected configuration, the command verifies them and exits success.
2. If either resource is missing, the command creates it.
3. If either exists but configuration has drifted (e.g., versioning was disabled by hand), the command reconciles to the expected state and reports what it changed.

Re-running is always safe and produces no changes when state is correct. This makes the command suitable as a periodic sanity check.

## When to Run It

Once per project, at the point an elastic foundation is first introduced — typically right after `project.yml` is created, and before the first `docex compile` for `stage` or `prod`. The bootstrap is *not* environment-specific; the same state backend serves stage, prod, and any other elastic environment the project might define.

For fixed-foundation projects, `docex bootstrap` is a no-op.

## Out of Scope

The bootstrap does *not* create:
- The AWS account itself — this is prerequisite infrastructure
- IAM roles for deployment — these are managed by OpenTofu in subsequent applies
- VPC, ECR, Route53 zones, ACM certs, or anything else listed under elastic project infrastructure in [shape2.md](../shape2.md) — all managed by OpenTofu once state works
- SSM Parameter Store entries for secrets — these are populated by `docex release` from the project's `.env` files on every deploy; see [release_mechanism.md](./release_mechanism.md#secrets) for the secrets flow
- Anything for fixed-foundation projects

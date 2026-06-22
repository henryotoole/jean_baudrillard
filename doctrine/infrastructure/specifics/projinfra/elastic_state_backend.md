---
stratum: conditional
---

# Elastic State Backend

This file describes the OpenTofu state backend — the S3 bucket and DynamoDB lock table — that every elastic-foundation project requires. It is a project-tier resource (one backend per project, shared across stage and prod) but its existence is a precondition for any other project-tier or env-tier Tofu apply, so `./bin/docex projinfra up production` provisions it directly via the AWS API before any `tofu init` can run.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Why It Exists

OpenTofu needs a place to store the mapping between HCL resources and the real-world AWS resources they manage. Without it, OpenTofu has no memory of what it has created and cannot compute meaningful diffs between desired and actual state. The doctrine puts that state in S3 (with DynamoDB-based locking) so it survives the operator's machine and can be consumed concurrently by any operator with project credentials.

The state backend is the **only** project-tier resource not created by `tofu apply` itself — `tofu` can't create the very thing it needs to track resources in. `./bin/docex projinfra up production` therefore creates it directly via the AWS API, idempotently. Once it exists, every subsequent `tofu init` (project-tier or env-tier) attaches to it and uses it transparently.

## Resources

### S3 bucket

- **Name:** derived from the project name by applying the `s3` naming policy (see [transfer_tables.md § Naming Policies](../transfer_tables.md#naming-policies)) to `<project>_tofu_state`. For a project named `docex_smoke_elastic`, the rendered bucket name is `docex-smoke-elastic-tofu-state` — S3 requires lowercase and rejects underscores.
- **Versioning:** enabled — so a corrupted or mistakenly-edited state file can be rolled back.
- **Server-side encryption:** enabled (AES256 / SSE-S3).
- **Public access:** all four block-public-access settings enabled.
- **Region:** the project's elastic region (per CICL simplifications, currently always `us-east-1`).

Within the bucket, state files are organized by tier:

- `project/terraform.tfstate` — project-tier state (everything described in [projinfra.md § Elastic × Production](./projinfra.md#elastic--production)).
- `stage/terraform.tfstate` — stage env-tier state.
- `prod/terraform.tfstate` — prod env-tier state.

Each env's `main.tf` declares its own backend key; the project-tier `main.tf` uses `key = "project/terraform.tfstate"`. Env-tier files read project-tier outputs via `data "terraform_remote_state" "project"`.

### DynamoDB lock table

- **Name:** derived from the project name by applying the `ddb` naming policy to `<project>_tofu_locks`. DynamoDB accepts both underscores and hyphens; the doctrine preserves underscores. For `docex_smoke_elastic`, the rendered table name is `docex_smoke_elastic_tofu_locks`.
- **Primary key:** attribute `LockID` of type `String` — this is the schema OpenTofu's S3 backend expects.
- **Billing mode:** on-demand (pay-per-request) — cheap for the low write volume of state locks.
- **Region:** same as the state bucket.

OpenTofu's S3 backend writes a lock record to this table when `tofu apply` starts and removes it when finished. Concurrent applies see the lock and either wait or fail loudly, preventing two operators from corrupting state simultaneously.

## How `projinfra` Provisions It

`./bin/docex projinfra up production` checks for the backend's existence as its first step:

1. **S3 bucket.** `HeadBucket` against the rendered name. If absent, create it with the configuration above. If present but drifted (e.g., versioning was disabled by hand), reconcile it to the expected state and report what changed.
2. **DynamoDB table.** `DescribeTable` against the rendered name. If absent, create it. If present but drifted, reconcile.
3. **Subsequent steps proceed.** Once both resources match expected configuration, the command continues to project-tier `tofu init` against the now-available backend.

The description above is the source of truth. The `projinfra` command is a faithful automation of it; an operator can reproduce the same setup by hand in the AWS console (or via `aws` CLI) if needed. OpenTofu does not care how the resources came into existence — only that they exist with the right configuration when it tries to use them.

## What Reads The Backend

Every Tofu apply against this project — project-tier and env-tier alike — uses the backend:

- `./bin/docex projinfra up production` — applies the project-tier `main.tf` (with `key = "project/terraform.tfstate"`).
- `./bin/docex release stage` — applies the stage env-tier `main.tf` (with `key = "stage/terraform.tfstate"`); reads project-tier outputs via remote state.
- `./bin/docex release prod` — applies the prod env-tier `main.tf` (with `key = "prod/terraform.tfstate"`); reads project-tier outputs via remote state.
- `./bin/docex projinfra down production` — destroys project-tier resources, removing them from state.
- `./bin/docex rollback <env> <version>` — recompiles an older version and applies it against the env's existing state key.

## What Doesn't Go in It

- **Fixed-foundation projects.** No state backend is needed; nothing on the fixed side uses OpenTofu. `./bin/docex projinfra up production` on a fixed project skips this step entirely.
- **The development side of an elastic project.** The dev-side projinfra is fixed-style (docker-compose) and doesn't use OpenTofu either.
- **Secrets.** Secrets live in SSM Parameter Store, populated at release time. The state backend is metadata only.

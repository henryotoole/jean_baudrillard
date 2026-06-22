---
stratum: conditional
---

# Elastic IAM

This file describes the IAM resources created on the production side of every elastic-foundation project. The doctrine keeps the IAM surface deliberately minimal: one task-execution role per project, shared across stage and prod ECS services, with a small set of resource-scoped permissions.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Resources

| Resource | HCL | Name (rendered) |
| -------- | --- | --------------- |
| Task-execution role | `aws_iam_role.task_execution` | `<project>_task_execution` |
| Inline policy on that role | (embedded in the role) | — |

The role uses the `iam` naming policy (underscore-separated, case-preserving, max length 64) from [transfer_tables.md § Naming Policies](../transfer_tables.md#naming-policies). For a project named `myproject`, the role is `myproject_task_execution`.

The role's trust policy allows the ECS tasks service (`ecs-tasks.amazonaws.com`) to assume it. No other principals — no operator users, no cross-account access, no inline `aws sts assume-role` paths.

## What ECS Uses the Role For

ECS uses the task-execution role at **task launch time** (before the task's containers start) to perform three operations:

1. **Pull the container image from ECR.** Requires `ecr:GetAuthorizationToken` (on `*`, which is how the ECR auth-token API is shaped), plus `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` scoped to the project's repository ARNs from [`elastic_ecr.md`](./elastic_ecr.md).
2. **Resolve secrets from SSM Parameter Store.** Requires `ssm:GetParameters` scoped to `/${project}/${env}/*` (covering stage and prod). The corresponding KMS decrypt permission (`kms:Decrypt` on the `aws/ssm` KMS alias) is *not* needed because SSM parameters are encrypted with the AWS-managed `aws/ssm` key, which all account principals can decrypt without an explicit grant.
3. **Write log streams to CloudWatch.** Requires `logs:CreateLogStream` and `logs:PutLogEvents` scoped to `arn:aws:logs:<region>:<account>:log-group:/<project>/<env>/*`. The env-tier HCL emits a per-env `aws_cloudwatch_log_group` for each service (see [telemetry_infra.md § Container stdout/stderr](../telemetry_infra.md#container-stdoutstderr-class-2-diagnostics)); the role's permissions are scoped to those `/<project>/<env>/*` prefixes. **`logs:CreateLogGroup` is intentionally omitted** — tofu owns group creation, so the task-execution role never needs it (and `awslogs-create-group` is never used).

This is intentionally *only* what ECS itself needs for task launch — the application code running inside the task container does not get this role. Applications that need AWS API access (e.g., to read from S3) declare a separate **task role** (not the execution role) in their env-tier compiled output. The doctrine handles this on a per-service basis as part of env-tier emission; the task-execution role here is shared across all services.

## Inline Policy Shape

The inline policy attached to the role (illustrative; actual emit lives in `src/docex/emit/elastic/iam.py`):

```hcl
resource "aws_iam_role_policy" "task_execution" {
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR auth token (must be on *)
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      # Per-service ECR image pulls
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = [
          # one entry per core service
          aws_ecr_repository.<svc1>.arn,
          aws_ecr_repository.<svc2>.arn,
          ...
        ]
      },
      # SSM secrets (stage + prod)
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameters"
        Resource = "arn:aws:ssm:<region>:<account>:parameter/<project>/stage/*"
      },
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameters"
        Resource = "arn:aws:ssm:<region>:<account>:parameter/<project>/prod/*"
      },
      # CloudWatch logs (stage + prod)
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = [
          "arn:aws:logs:<region>:<account>:log-group:/<project>/stage/*",
          "arn:aws:logs:<region>:<account>:log-group:/<project>/prod/*",
        ]
      },
    ]
  })
}
```

The policy is **scoped to project resources only**. A task running under this role cannot pull from other projects' ECR repos, read other projects' SSM secrets, or write to other projects' log groups. Cross-project isolation in a shared AWS account is enforced primarily at this IAM layer plus the SG layer (see [networks.md](../networks.md)).

## Why One Role for Both Stage and Prod

Per [shape2.md § Elastic-Foundation](../../shape2.md#elastic-foundation), each project gets one task-execution role used by both stage and prod. Splitting the role into two (`myproject_stage_task_execution` and `myproject_prod_task_execution`) was considered and rejected:

- The role doesn't carry env-distinguishing permissions — it can read any `/<project>/<env>/*` SSM path and write to any `/<project>/<env>/*` log group regardless of env. The permissions are scoped per-project, not per-env.
- A stage task can't accidentally read prod's secrets through this role because *the task definition* references a specific SSM path. The role gates whether reading is allowed; the task definition specifies what's read. Misconfiguration at the task-definition layer is what would cause cross-env reads, not the role's permissions.
- One role keeps the IAM surface smaller and the diff between projects simpler.

Projects with stricter compliance requirements (real prod/stage isolation at the IAM layer) can extend via project-local doctrine to split the role; the default keeps things minimal.

## Outputs Consumed Downstream

The project's `main.tf` declares:

| Output | Used by |
| ------ | ------- |
| `task_execution_role_arn` | Every env-tier `aws_ecs_task_definition` resource (the `execution_role_arn` field) |

The role ARN flows through `data "terraform_remote_state" "project"` into both `stage` and `prod` `main.tf` files.

## Lifecycle

The role comes up with `./bin/docex projinfra up production` and is updated on every projinfra-apply that changes the project's ECR repositories or core-service set (the inline policy lists ECR repo ARNs explicitly). Adding a new core service to `infra.yml` and running `projinfra up production` causes:

1. The new `aws_ecr_repository.<newsvc>` to be created.
2. The role's inline policy to be updated to add the new repo's ARN to the resource list.

Removing a service is the inverse, plus the operator must manually empty the repo first per [`elastic_ecr.md`](./elastic_ecr.md).

`./bin/docex projinfra down production` destroys the role along with everything else. ECS will fail to launch any task without it, so down-ing project-tier infra while env-tier services still exist would orphan them — projinfra refuses that case.

## Out of Scope

- **Per-service task roles.** Handled at the env tier; the doctrine's env-tier compiled output emits a per-service `aws_iam_role.<svc>_task` when the service declares it needs AWS API access. Not described here.
- **Cross-account access.** No `sts:AssumeRole` paths are emitted. Projects that need them attach extra trust policies out-of-band.
- **MFA-gated role usage.** Not in v1. The role is assumed by ECS only; no human principals.

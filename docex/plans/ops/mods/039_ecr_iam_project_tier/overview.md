# Mod 039 — ECR + IAM Move to Project-Tier

Tenth mod of the [doctrine-shape-and-tier advance](../../advances/shape_overhaul_mod_list.md). Scope shrinks substantially: ECR repos and the task-execution IAM role are **already** project-tier in the current code (probably moved in earlier work). What this mod actually does: tighten the IAM policy to the doctrine spec, replacing the broad AWS-managed policy with an explicit project-scoped inline policy.

## The Doctrine Change

From [`projinfra/elastic_ecr.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_ecr.md) and [`projinfra/elastic_iam.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_iam.md):

- **ECR**: one `aws_ecr_repository.<svc>` per core service at project tier, named `<project>/<svc>`. ✓ Already implemented.
- **IAM**: one `aws_iam_role.task_execution` per project at project tier, with an inline policy scoped explicitly to project resources — ECR auth, per-repo image pull, SSM under `/<project>/{stage,prod}/*`, CloudWatch logs under `/<project>/{stage,prod}/*`.

## What's already done

Survey of current code:
- `project.tf.j2` already emits `aws_ecr_repository.<svc>` per service with structural naming (`<project>/<svc>`).
- `project.tf.j2` already emits `aws_iam_role.task_execution` and project-tier outputs `task_execution_role_arn`, `ecr_repository_<svc>_url`.
- Env-tier task definitions already consume the role ARN via `data.terraform_remote_state.project.outputs.task_execution_role_arn`.
- Env-tier image refs already consume ECR repo URLs from project-tier outputs.

So the *tier moves* are done. What remains is **policy correctness**.

## The IAM policy gap

Current implementation (`project.tf.j2:386–400+`):

```hcl
# AWS-managed policy: covers ECR pulls + CloudWatch Logs writes.
resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Inline policy: lets Fargate decrypt SecureString parameters from this
# project's SSM prefix.
resource "aws_iam_role_policy" "task_execution_ssm" {
  ...
  Statement = [
    {
      Effect = "Allow"
      Action = ["ssm:GetParameters", "ssm:GetParameter", "ssm:GetParametersByPath"]
      Resource = "arn:aws:ssm:{{ region }}:${data.aws_caller_identity.current.account_id}:parameter/{{ ssm_path_project }}/*"
    },
    {
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = "*"
    },
  ]
}
```

Doctrine target (`projinfra/elastic_iam.md`):

```hcl
resource "aws_iam_role_policy" "task_execution" {
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR auth token (must be on *).
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      # Per-service ECR image pulls.
      {
        Effect = "Allow",
        Action = ["ecr:BatchCheckLayerAvailability",
                  "ecr:BatchGetImage",
                  "ecr:GetDownloadUrlForLayer"],
        Resource = [aws_ecr_repository.<svc1>.arn, aws_ecr_repository.<svc2>.arn, ...]
      },
      # SSM secrets (stage + prod).
      {
        Effect = "Allow",
        Action = "ssm:GetParameters",
        Resource = "arn:aws:ssm:<region>:<account>:parameter/<project>/stage/*"
      },
      {
        Effect = "Allow",
        Action = "ssm:GetParameters",
        Resource = "arn:aws:ssm:<region>:<account>:parameter/<project>/prod/*"
      },
      # CloudWatch logs (stage + prod).
      {
        Effect = "Allow",
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = [
          "arn:aws:logs:<region>:<account>:log-group:/<project>/stage/*",
          "arn:aws:logs:<region>:<account>:log-group:/<project>/prod/*",
        ]
      },
    ]
  })
}
```

The differences:
1. **AWS-managed policy attachment goes away.** Replaced by explicit inline statements. This removes the broad ECR-pull-from-any-repo permission that the AWS-managed policy carries.
2. **ECR auth-token statement** added explicitly (must be on `*` per AWS API requirement).
3. **Per-repo ECR pull statement** added, listing each project ECR repo ARN as a resource.
4. **SSM scoping** narrows from `/<project>/*` to two explicit statements for `/<project>/stage/*` and `/<project>/prod/*`. Functionally `<project>/*` already covers both, but the doctrine wants two separate statements (likely for auditability / cleaner separation in IAM logs).
5. **CloudWatch logs statement** added scoped to `/<project>/{stage,prod}/*` log group ARNs.
6. **KMS decrypt statement removed.** Per [`projinfra/elastic_iam.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_iam.md):
   > The corresponding KMS decrypt permission (`kms:Decrypt` on the `aws/ssm` KMS alias) is **not** needed because SSM parameters are encrypted with the AWS-managed `aws/ssm` key, which all account principals can decrypt without an explicit grant.
7. **Single policy resource** instead of one attachment + one inline. Combine into one inline policy resource (`aws_iam_role_policy.task_execution`).

## Concrete file surface

### `src/docex/emit/templates/project.tf.j2`

Delete:
- `aws_iam_role_policy_attachment.task_execution_managed`
- `aws_iam_role_policy.task_execution_ssm`

Add a single new resource:
- `aws_iam_role_policy.task_execution` — inline policy with the five statements above.

The ECR repo ARNs need to be enumerated in the policy. Use a Jinja loop:

```hcl
Resource = [
  {% for svc in core_service_names %}
  aws_ecr_repository.{{ svc.hcl_id }}.arn{{ "," if not loop.last }}
  {% endfor %}
]
```

The empty-project edge case (no core services): `Resource = []` is a valid HCL/JSON list. AWS may reject it as "policy must have at least one resource" — implementer should verify, and if needed wrap the per-repo statement in `{% if core_service_names %}` so the whole statement is omitted when there are no repos.

### `emit_hcl_project` in `src/docex/emit/hcl.py`

Currently computes `task_execution_ssm_policy_name`. After mod 039 there's no separate `task_execution_ssm` resource — just the unified `task_execution` policy. Either:
- Delete the computation (and the template variable), OR
- Rename to `task_execution_policy_name` and use it for the new single policy resource name.

I'd suggest the rename: keep the policy resource named explicitly via the `iam` naming policy, matching the existing pattern. The resource name in HCL is `task_execution` but the AWS-side `name` field on `aws_iam_role_policy` is the policy's "logical" name, computed via the policy.

### Tests

`tests/integration/test_compile.py` — assertions on the IAM policy content:

- Assert the AWS-managed policy attachment is **absent**.
- Assert the new `aws_iam_role_policy.task_execution` is present.
- Assert the policy JSON contains:
  - `ecr:GetAuthorizationToken` on `Resource = "*"`.
  - `ecr:BatchGetImage` / `BatchCheckLayerAvailability` / `GetDownloadUrlForLayer` referencing each `aws_ecr_repository.<svc>.arn`.
  - `ssm:GetParameters` scoped to `parameter/<project>/stage/*` AND `parameter/<project>/prod/*` (two separate statements).
  - `logs:CreateLogStream` / `PutLogEvents` scoped to `/<project>/stage/*` AND `/<project>/prod/*`.
- Assert `kms:Decrypt` is absent.

The integration tests likely render the template, so substring assertions on the rendered HCL are sufficient.

## Ramifications

### Behavioral change for elastic deployments

A project upgrading past mod 039 sees a tofu plan that:
- Removes `aws_iam_role_policy_attachment.task_execution_managed`.
- Removes `aws_iam_role_policy.task_execution_ssm`.
- Creates `aws_iam_role_policy.task_execution` (new combined policy).

For the next ECS task to launch successfully:
- The new policy must be in place before any task spawns referencing the role.
- AWS IAM is eventually consistent, so a slight delay is possible between `tofu apply` finishing and the role's new policy taking effect. Tasks launched immediately after apply could see brief permission errors.

In practice, `tofu apply` waits for IAM consistency before returning. The doctrine's narrow-window deployments accept the residual risk.

Per operator decision (advance-wide), no in-flight projects need migration help.

### No env-tier impact

Env-tier task definitions already reference `task_execution_role_arn` via remote state. The policy change is transparent to env-tier consumers.

### Doctrine compliance for cross-project isolation

The AWS-managed policy was the doctrine's stated isolation hole:

> The policy is **scoped to project resources only**. A task running under this role cannot pull from other projects' ECR repos, read other projects' SSM secrets, or write to other projects' log groups.

Mod 039 closes that hole.

## Operator Decisions

1. **Empty-project edge case** — gate the per-repo ECR statement on `{% if core_service_names %}`.
2. **Single policy resource** `aws_iam_role_policy.task_execution`. AWS-side `name` rendered via `iam` naming policy.
3. **SSM split into two statements** — one for `/<project>/stage/*`, one for `/<project>/prod/*`. Matches the doctrine literally.

## What This Mod Is NOT

- **No ECR repo schema changes.** The repos themselves are already correctly emitted.
- **No new project-tier outputs.** Existing outputs cover all consumers.
- **No env-tier changes.** Task definitions already consume the project-tier role ARN.
- **No master VPC switchover** — mod 041.
- **No EC2-traefik variant** — mod 044.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No `kms:Decrypt`-via-CMK changes.** AWS-managed `aws/ssm` key remains the SSM encryption choice (no project-controlled CMK).

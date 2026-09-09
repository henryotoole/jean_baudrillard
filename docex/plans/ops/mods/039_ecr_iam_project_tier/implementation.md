# Implementation — Mod 039 — ECR + IAM Project-Tier (Policy Tightening)

## Context for fresh-context implementer

You are executing mod 039. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`projinfra/elastic_iam.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_iam.md) — exact policy shape, including the comment about why `kms:Decrypt` is not needed.
- [`projinfra/elastic_ecr.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_ecr.md) — confirms ECR is project-tier (no code change required).

## Operator decisions binding on this implementation

- Gate per-repo ECR statement on `{% if core_service_names %}`.
- Single policy resource `aws_iam_role_policy.task_execution`; AWS-side name via `iam` naming policy.
- SSM scoping split into two explicit statements for `/<project>/stage/*` and `/<project>/prod/*`.

## Step-by-step plan

### Step 1 — Confirm ECR and IAM are already project-tier

Spot-check `src/docex/emit/templates/project.tf.j2`:
- `aws_ecr_repository.<svc>` blocks present, per-service.
- `aws_iam_role.task_execution` resource present.
- Outputs `task_execution_role_arn` and `ecr_repository_<svc>_url` present.

Confirm `src/docex/emit/templates/main.tf.j2` and `src/docex/emit/hcl.py` consume the role ARN via `data.terraform_remote_state.project.outputs.task_execution_role_arn` (already verified during mod 039 survey).

No source changes if all of the above hold. If anything doesn't hold (e.g. there's still an env-tier IAM role definition), STOP and report — that's a scope expansion this mod's overview didn't account for.

### Step 2 — Delete the existing IAM policy resources in `project.tf.j2`

Delete:
- `aws_iam_role_policy_attachment.task_execution_managed` block (the AWS-managed policy attachment).
- `aws_iam_role_policy.task_execution_ssm` block (the existing inline policy).

Both live in the same template region; their delete is bounded.

### Step 3 — Add the new combined IAM policy

Insert in their place a single `aws_iam_role_policy.task_execution` resource. The doctrine target HCL (with Jinja templating):

```hcl
# Inline policy scoped to project resources only. Replaces the
# AWS-managed AmazonECSTaskExecutionRolePolicy with explicit grants so
# cross-project isolation is enforced at the IAM layer
# (projinfra/elastic_iam.md). KMS Decrypt is intentionally absent —
# AWS-managed `aws/ssm` key decryption requires no explicit grant.
resource "aws_iam_role_policy" "task_execution" {
  name = "{{ task_execution_policy_name }}"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {%- if core_service_names %}
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = [
          {%- for svc in core_service_names %}
          aws_ecr_repository.{{ svc.hcl_id }}.arn,
          {%- endfor %}
        ]
      },
      {%- endif %}
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameters"
        Resource = "arn:aws:ssm:{{ region }}:${data.aws_caller_identity.current.account_id}:parameter/{{ ssm_path_project }}/stage/*"
      },
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameters"
        Resource = "arn:aws:ssm:{{ region }}:${data.aws_caller_identity.current.account_id}:parameter/{{ ssm_path_project }}/prod/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "arn:aws:logs:{{ region }}:${data.aws_caller_identity.current.account_id}:log-group:/{{ ssm_path_project }}/stage/*",
          "arn:aws:logs:{{ region }}:${data.aws_caller_identity.current.account_id}:log-group:/{{ ssm_path_project }}/prod/*",
        ]
      },
    ]
  })
}
```

Notes:
- `ssm_path_project` is the project-name segment as rendered by the `ssm_path` naming policy (underscores preserved). For `docex_smoke_elastic` it produces `docex_smoke_elastic`. The log-group ARN path uses the same segment for consistency.
- `{% if core_service_names %}` gates the per-repo statement so empty-project compiles still work.
- `data.aws_caller_identity.current` already exists in the template (line ~268). Keep it.
- The new resource's AWS-side `name` field uses a new template input `task_execution_policy_name`.

### Step 4 — Update `emit_hcl_project` in `src/docex/emit/hcl.py`

Currently computes `task_execution_ssm_policy_name`. Rename + repurpose to `task_execution_policy_name`:

```python
task_execution_policy_name=apply_policy(
    f"{project}_task_execution", iam_p
),
```

(The new policy name uses the role's name verbatim — `{project}_task_execution` — since the role and its single policy are paired 1:1. Drop the `_ssm` suffix.)

Pass the renamed value to the template.

### Step 5 — Tests

#### `tests/integration/test_compile.py`

Find the existing test(s) that exercise the IAM policy emission:

```bash
grep -n 'task_execution\|AmazonECSTaskExecutionRolePolicy' tests/
```

For each:

- **Absent**: `AmazonECSTaskExecutionRolePolicy` (the AWS-managed policy ARN) should not appear in compiled project main.tf.
- **Absent**: `aws_iam_role_policy_attachment.task_execution_managed` resource.
- **Absent**: `aws_iam_role_policy.task_execution_ssm` resource.
- **Absent**: `kms:Decrypt` action.
- **Present**: single `aws_iam_role_policy.task_execution` resource.
- **Present**: `ecr:GetAuthorizationToken` action with `Resource = "*"`.
- **Present**: ECR pull statement with all of the project's repo ARNs in the resource list.
- **Present**: two separate SSM statements with stage and prod paths.
- **Present**: CloudWatch logs statement with both stage and prod log-group ARNs.

If the existing test asserts the AWS-managed policy attachment, flip the polarity (assert absent).

#### Empty-project test

Add or extend a test that compiles a project with zero core services and verifies the policy emits without crashing — and that the per-repo ECR statement is omitted entirely (not emitted with an empty list).

### Step 6 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 7 — Sanity sweeps

```bash
# AWS-managed policy gone
grep -rn 'AmazonECSTaskExecutionRolePolicy\|task_execution_managed\|task_execution_ssm' src/ tests/

# New policy in place
grep -rn 'aws_iam_role_policy "task_execution"\|aws_iam_role_policy\.task_execution\b' src/

# kms:Decrypt absent from project template
grep -n 'kms:Decrypt' src/docex/emit/templates/project.tf.j2
```

First sweep: zero hits in `src/`. Test hits are fine if they're asserting absence; otherwise update.

Second sweep: hits only in the project template and any test asserting its presence.

Third sweep: zero hits.

## Out of scope

- **No ECR repo schema changes** — already correct.
- **No env-tier task definition changes** — already references the role ARN via remote state.
- **No new outputs** — `task_execution_role_arn` already exists.
- **No project-controlled CMK for SSM** — AWS-managed `aws/ssm` stays.
- **No master VPC switchover** — mod 041.
- **No `test_projects/{fixed,elastic}/` edits.**

## Done criteria

- [ ] `aws_iam_role_policy_attachment.task_execution_managed` and `aws_iam_role_policy.task_execution_ssm` deleted.
- [ ] Single `aws_iam_role_policy.task_execution` resource added with the five-statement inline policy.
- [ ] Per-repo ECR statement gated on `{% if core_service_names %}`.
- [ ] Two SSM statements (stage + prod).
- [ ] Two log-group resource ARNs (stage + prod).
- [ ] `kms:Decrypt` absent.
- [ ] `emit_hcl_project` passes `task_execution_policy_name` (renamed from `task_execution_ssm_policy_name`).
- [ ] Tests verify absent old policy attachment, present new combined policy, all five statements, empty-project case.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.

Working tree dirty when finished. Do not commit.

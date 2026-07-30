# Mod 044 — EC2-Traefik Reverse-Proxy Variant (EIP + PIP)

Fifteenth and largest mod of the [doctrine-shape-and-tier advance](../../campaifns/shape_overhaul_mod_list.md). Adds the doctrine's `ec2_traefik_eip` and `ec2_traefik_pip` reverse-proxy variants — a low-cost alternative to the default ALB. Project-tier emission branches on `reverse_proxy`; env-tier consumers adjust their remote-state references accordingly.

## The Doctrine Change

From [`projinfra/ec2_traefik.md`](../../../../doctrine/infrastructure/specifics/projinfra/ec2_traefik.md):

> The `ec2_traefik` option replaces the project ALB with a single, doctrine-managed EC2 instance running Traefik as a project-scoped reverse proxy + TLS terminator + load balancer. It serves the same role as the ALB — terminating TLS for `web`-network services and routing inbound HTTP/HTTPS to the right ECS service — at substantially lower cost (~$4–8/month all-in, depending on variant).

Two variants:
- `ec2_traefik_eip` — EIP-backed, stable public IP across instance lifecycle, costs 1 EIP from the regional quota.
- `ec2_traefik_pip` — auto-assigned public IP, no EIP quota cost, IP changes on stop/start (boot-time DNS update unit handles this).

## What gets emitted per `reverse_proxy` value

| `reverse_proxy` | Project-tier resources |
| --------------- | ---------------------- |
| `alb` (default) | ALB set from mod 038: SG, LB, HTTPS listener + stage SNI cert, HTTP redirect listener |
| `ec2_traefik_eip` | EC2 instance + EIP + EBS volume + IAM + SG + SSM Param + CloudWatch LG + 5 Route53 A-records |
| `ec2_traefik_pip` | Same as eip variant, minus EIP, plus boot-time DNS update systemd unit |

The two paths are **mutually exclusive at the project tier**. A project using `ec2_traefik_*` gets no ALB + no ACM certs; a project using `alb` gets no traefik EC2.

Env-tier resources (env SG, ECS, etc.) are foundation-invariant; only their *references* to project-tier outputs shift.

## Concrete resource breakdown (`ec2_traefik_*` branch)

Per [`projinfra/ec2_traefik.md`](../../../../doctrine/infrastructure/specifics/projinfra/ec2_traefik.md):

### Always emitted (both variants)

- `data "aws_ami" "ubuntu"` — Canonical's latest Ubuntu 24.04 LTS (owner `099720109477`, name pattern pinned).
- `aws_security_group.project_traefik` — ingress 80/443 from `0.0.0.0/0`, egress all. Tagged `purpose = ec2_traefik`.
- `aws_iam_role.project_traefik` (assume by `ec2.amazonaws.com`) + `aws_iam_instance_profile.project_traefik`.
- `aws_iam_role_policy.project_traefik` — four scoped statement groups:
  - `route53:ChangeResourceRecordSets`, `GetChange` on the project's hosted zone only (for LE DNS-01 challenges + PIP boot DNS update).
  - `ssm:GetParameter`, `GetParameters` on `/<project>/ec2_traefik/*`.
  - `logs:CreateLogStream`, `PutLogEvents` on the project's `/<project>/ec2_traefik` log group.
  - `ec2:AttachVolume`, `DescribeVolumes` on volumes tagged `purpose = ec2_traefik_acme` + matching project.
- `aws_cloudwatch_log_group.project_traefik` — `/<project>/ec2_traefik`, retention 30 days.
- `aws_ssm_parameter.project_traefik_config` — `/<project>/ec2_traefik/config.yml`, type `SecureString`, initial value is an empty stub (env-tier release rerenders).
- `aws_ebs_volume.project_traefik_acme` — 8 GB gp3, in `us-east-1a`, tagged `purpose = ec2_traefik_acme` for discovery. `delete_on_termination = false`.
- `aws_instance.project_traefik` — `t3.nano`, Ubuntu AMI, master VPC public-az-1 subnet, instance profile attached, user_data script (below).
- Five `aws_route53_record` A-records in the project's hosted zone:
  - `<project>.<apex>` (bare project)
  - `*.prod.<project>.<apex>`
  - `prod.<project>.<apex>`
  - `*.stage.<project>.<apex>`
  - `stage.<project>.<apex>`

### EIP variant adds

- `aws_eip.project_traefik` + `aws_eip_association.project_traefik` linking the EIP to the instance.
- Route53 A-records point at `aws_eip.project_traefik.public_ip`.

### PIP variant differs

- No EIP resources.
- Route53 A-records initialize pointing at `aws_instance.project_traefik.public_ip` (Tofu reads it post-create). The boot-time DNS-update unit replaces them on subsequent stop/start.
- A-record TTL set to 60s (vs default longer) so propagation is fast when the IP changes.

### user_data script

Renders into the instance's `user_data` field. Doctrine-required steps:

1. Install dependencies: `unzip`, the AWS CLI, the CloudWatch Logs agent.
2. Mount the EBS volume at `/etc/traefik/acme/` (via `aws ec2 describe-volumes` + `aws ec2 attach-volume` lookup by tag).
3. Install Traefik binary (specific version pinned in user_data).
4. Write static traefik config to `/etc/traefik/traefik.yml` (entrypoints, ACME resolver named `doctrine` configured for Let's Encrypt DNS-01 via Route53).
5. Install systemd unit + timer `docex-traefik-config.timer` (fires every 30s; service calls `aws ssm get-parameter --name /<project>/ec2_traefik/config.yml`, writes to `/etc/traefik/dynamic.yml` if changed).
6. **PIP only**: install systemd oneshot unit `docex-traefik-dns-update.service` (run-once-per-boot; reads IMDS, batches `route53:ChangeResourceRecordSets` against the 5 records).
7. Configure CloudWatch Logs agent to ship traefik logs to `/<project>/ec2_traefik`.
8. Start traefik via systemd.

This is the longest user_data in the codebase — ~80–120 lines of bash inside a Jinja-templated HCL string. Suggest emitting it via a separate template file (`templates/ec2_traefik_user_data.sh.j2`) and `include`-ing in `project.tf.j2`.

## Project-tier outputs (variant-aware)

To keep env-tier emission foundation-invariant, expose **polymorphic outputs**:

```hcl
# Both variants emit this; ALB binds project_alb SG, EC2-traefik binds project_traefik SG.
output "reverse_proxy_security_group_id" {
  value = {{ "aws_security_group.project_alb.id" if reverse_proxy == "alb" else "aws_security_group.project_traefik.id" }}
}
```

Same idea for HTTP ingress target (ALB DNS+zone for alb; EC2 public IP for ec2_traefik) — but the env-tier Route53 alias records are ALB-tier-only; for EC2-traefik those records become project-tier instead (mod's overview). So the env-tier alias emission gates on variant.

Concrete output surface:

| Output | `alb` variant | `ec2_traefik_*` variant |
| ------ | ------------- | ----------------------- |
| `reverse_proxy_security_group_id` | `project_alb.id` | `project_traefik.id` |
| `alb_arn` | `project.arn` | omitted |
| `alb_dns_name` | `project.dns_name` | omitted |
| `alb_zone_id` | `project.zone_id` | omitted |
| `alb_https_listener_arn` | `project_https.arn` | omitted |
| `alb_http_listener_arn` | `project_http.arn` | omitted |
| `alb_security_group_id` | `project_alb.id` | omitted (legacy; mod 045 cleanup could drop it once env-tier flips to the polymorphic output) |
| `stage_cert_arn` / `prod_cert_arn` | from ACM | omitted |
| `zone_id` / `zone_name_servers` | (unchanged) | (unchanged) |
| `ecr_repository_*_url` | (unchanged) | (unchanged) |
| `task_execution_role_arn` | (unchanged) | (unchanged) |
| `vpc_id` / `*_subnet_ids` / `primary_private_subnet_id` | (unchanged) | (unchanged) |

The variant-aware outputs let env-tier consumers treat the reverse proxy uniformly: per-network SG ingress source = `reverse_proxy_security_group_id`. The env-tier Route53 alias for the ALB path stays for `alb` variant; for `ec2_traefik_*` the records are already at project tier so env-tier skips.

## Env-tier impact

`src/docex/emit/templates/main.tf.j2`:

- Line ~80 `source_security_group_id`: switch from `outputs.alb_security_group_id` to `outputs.reverse_proxy_security_group_id`.
- Lines ~141–164 Route53 alias records: gate the entire block on `{% if reverse_proxy == "alb" %}` — when `ec2_traefik_*`, the records live at project tier (already emitted above).

`src/docex/emit/hcl.py`:

- `_emit_listener_rule` (around line 510): currently emits `aws_lb_listener_rule` referencing `outputs.alb_https_listener_arn`. For `ec2_traefik_*` variants, **no listener rules emit env-tier** — routing is handled by the SSM-parameter-driven traefik dynamic config, which env-tier release rerenders.

The env-tier emission needs `reverse_proxy` in its context. Verify `CompiledEnv` carries it (mod 031 added it to `CICLDocument`).

### Env-tier release SSM rerender

This is the trickiest part. On every `docex release stage` or `docex release prod`, when `reverse_proxy == "ec2_traefik_*"`, the release flow must:

1. Compute the current set of routing rules for stage + prod combined (since both share the one traefik instance).
2. Render them as a YAML config matching the traefik dynamic-config schema (HTTP routers + services + middlewares).
3. Push to SSM as `/<project>/ec2_traefik/config.yml` via `ssm:PutParameter Overwrite=true`.
4. Wait for the instance's systemd timer to pick it up (≤30s).

This means a new code path in `pipeline/release.py` that's distinct from the existing SSM-secrets-push and tofu-apply flow. It runs IN ADDITION to those steps.

For mod 044 scope-wise: emit a stub config (e.g. empty `http: { routers: {}, services: {} }`) initially; have the release flow push the real rendered config. Or: have `tofu apply` push an initial-fresh config on each release. Implementer's discretion.

## Operator Decisions

1. **Both variants in one mod.** EIP + PIP share ~90% of resources; the differences are gated by Jinja conditionals.
2. **Polymorphic `reverse_proxy_security_group_id` output.** Same-named output, value selected by `reverse_proxy` value; env-tier consumes it generically.
3. **user_data as a separate template file**, `templates/ec2_traefik_user_data.sh.j2`, included into `project.tf.j2` via Jinja `include`.
4. **Initial SSM config: empty stub.** Project-tier `tofu apply` sets a minimal `http: { routers: {}, services: {} }` placeholder; env-tier release rerenders.
5. **SSM release rerender stubbed in mod 044.** Mod 044 emits the SSM Parameter resource with the stub initial value; the env-tier-release SSM-push-with-rendered-routing is a follow-up (post-advance). Operators using EC2-traefik on v1 manage the SSM config manually until that follow-up lands. Documented in mod 044's `What This Mod Is NOT`.

## What This Mod Is NOT

- **No ALB removal.** ALB stays the default; this mod adds an alternative.
- **No new fixed-foundation changes.** EC2-traefik is elastic-only.
- **No HTTP-01 fallback config** — DNS-01 is the only supported path for EC2-traefik.
- **No multi-region** — single region.
- **No env-tier release SSM-push-with-rendered-routing.** Per operator decision: mod 044 emits the SSM Parameter with a stub config; operators using EC2-traefik manage the dynamic config manually until a follow-up mod adds the per-release SSM-push flow. Documented as a known v1 gap; doesn't block ALB users.
- **No `test_projects/{fixed,elastic}/` edits.**

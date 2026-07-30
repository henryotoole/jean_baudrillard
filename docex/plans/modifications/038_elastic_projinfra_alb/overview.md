# Mod 038 — Elastic Projinfra: ALB (default variant) + Project-Tier Outputs

Ninth mod of the [doctrine-shape-and-tier advance](../../advances/shape_overhaul_mod_list.md). Moves the project ALB from env-tier to project-tier per [`projinfra/elastic_alb.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_alb.md). One ALB serves both stage and prod via SNI; listener rules stay env-tier.

## The Doctrine Change

From [`projinfra/elastic_alb.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_alb.md):

> One ALB per ALB-using project, in the master VPC's public subnets. It is the public entry point for the project's `stage` and `prod` envs.
>
> The ALB is **project-tier**: one ALB serves both stage and prod, and stays up across deploys. Env-tier `release` adds, removes, and rolls listener rules and target groups against the existing ALB.

Per the file, the project-tier ALB set comprises:

| Resource | HCL | Note |
| -------- | --- | ---- |
| ALB | `aws_lb.project` | application LB, internet-facing |
| ALB security group | `aws_security_group.project_alb` | ingress 80/443 from `0.0.0.0/0`; egress allow-all |
| HTTPS listener (443) | `aws_lb_listener.project_https` | both ACM certs as SNI bindings; default 404 action |
| HTTP listener (80) | `aws_lb_listener.project_http` | 301 redirect to 443 |

**Listener rules and target groups stay env-tier** — they're 1:1 with env-tier ECS services, with deterministic per-env priorities.

## Where the ALB currently lives (and the move)

The current code emits the ALB **at the env tier** (one ALB per env): `src/docex/emit/templates/main.tf.j2:128` defines `aws_lb.alb`. Mod 038 moves the whole ALB set into `project.tf.j2` as one shared resource set.

### Env-tier sites that reference the ALB

Searching the env-tier templates and code for ALB references identifies these consumers:

| Site | Reference | After mod 038 |
| ---- | --------- | ------------- |
| `main.tf.j2:80` `source_security_group_id` for per-network ingress | `aws_security_group.alb.id` | `data.terraform_remote_state.project.outputs.alb_security_group_id` |
| `main.tf.j2:128` ALB resource | (defined here) | **deleted** |
| `main.tf.j2:141` HTTPS listener | (defined here) | **deleted** |
| `main.tf.j2:161` HTTP redirect listener | (defined here) | **deleted** |
| `main.tf.j2:221-237` Route53 alias records | `aws_lb.alb.dns_name` / `.zone_id` | `data...outputs.alb_dns_name` / `.alb_zone_id` |
| `hcl.py:510` listener-rule (per-web-service) | `aws_lb_listener.alb_https.arn` | `data...outputs.alb_https_listener_arn` |
| `main.tf.j2:96` `aws_security_group "alb"` | (defined here) | **deleted** |

After the move, env-tier `main.tf` references the ALB exclusively through the `data "terraform_remote_state" "project"` block.

## Concrete file surface

### Add to `project.tf.j2` (project-tier ALB set)

Place after the ACM cert block (so the cert ARNs the listener references already exist in HCL graph order). The set:

```hcl
# ---------------------------------------------------------------------------
# Project-tier ALB. One per project, serves stage and prod via SNI
# listener-cert bindings + env-tier listener rules. See
# projinfra/elastic_alb.md.
# ---------------------------------------------------------------------------
resource "aws_security_group" "project_alb" {
  name        = "{{ alb_sg_name }}"   # e.g. {{ project }}-alb-sg
  description = "Project ALB ingress (80/443 from internet); egress all."
  vpc_id      = aws_vpc.project.id
  ingress {
    from_port = 80
    to_port   = 80
    protocol  = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port = 443
    to_port   = 443
    protocol  = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { project = "{{ project }}", managed_by = "doctrine" }
}

resource "aws_lb" "project" {
  name               = "{{ alb_name }}"   # e.g. {{ project }}-alb
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.project_alb.id]
  subnets            = aws_subnet.public[*].id
  tags = { project = "{{ project }}", managed_by = "doctrine" }
}

resource "aws_lb_listener" "project_https" {
  load_balancer_arn = aws_lb.project.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  # Prod cert is the listener default; stage cert is attached as an
  # additional SNI cert below. SNI behavior selects whichever cert's
  # SAN matches the incoming Host header.
  certificate_arn   = aws_acm_certificate_validation.prod.certificate_arn
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      status_code  = "404"
      message_body = "not found"
    }
  }
}

resource "aws_lb_listener_certificate" "project_stage" {
  listener_arn    = aws_lb_listener.project_https.arn
  certificate_arn = aws_acm_certificate_validation.stage.certificate_arn
}

resource "aws_lb_listener" "project_http" {
  load_balancer_arn = aws_lb.project.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
```

Outputs to add:

```hcl
output "alb_arn"                  { value = aws_lb.project.arn }
output "alb_dns_name"             { value = aws_lb.project.dns_name }
output "alb_zone_id"              { value = aws_lb.project.zone_id }
output "alb_https_listener_arn"   { value = aws_lb_listener.project_https.arn }
output "alb_http_listener_arn"    { value = aws_lb_listener.project_http.arn }
output "alb_security_group_id"    { value = aws_security_group.project_alb.id }
```

### Naming inputs to template

`emit_hcl_project` in `src/docex/emit/hcl.py` computes the structural names it passes into `project.tf.j2`. Add:

- `alb_name = apply_policy(f"{project}_alb", alb_policy)` → `${project}-alb`
- `alb_sg_name = apply_policy(f"{project}_alb_sg", alb_policy)` → `${project}-alb-sg`

The `alb` naming policy is hyphen + case-any + max 32. For `docex_smoke_elastic_alb` that's 25 chars — fits. For `docex_smoke_elastic_alb_sg` that's 28 chars — fits.

### Remove from `main.tf.j2`

Delete the env-tier:
- `aws_security_group "alb"` block (line ~96–105)
- `aws_lb "alb"` block (line ~128–139)
- `aws_lb_listener "alb_https"` block (line ~141–159)
- `aws_lb_listener "alb_http_redirect"` block (line ~161–175)

Update remaining env-tier references:
- `main.tf.j2:74-80` per-network SG ingress source: change `aws_security_group.alb.id` → `data.terraform_remote_state.project.outputs.alb_security_group_id`.
- `main.tf.j2:221-237` Route53 alias records: change `aws_lb.alb.dns_name` → `data...outputs.alb_dns_name`; same for `zone_id`.

### Update `hcl.py` listener-rule emission

`src/docex/emit/hcl.py:510` builds an `aws_lb_listener_rule` referencing `aws_lb_listener.alb_https.arn`. Change to:

```python
out.append('  listener_arn = data.terraform_remote_state.project.outputs.alb_https_listener_arn')
```

### Tests

- `tests/integration/test_compile.py`: assertions on env-tier `aws_lb.alb` need to flip to absence (resource is gone from env main.tf) and to presence in project main.tf as `aws_lb.project`. Same for listeners and ALB SG.
- New assertions: project outputs `alb_arn`, `alb_dns_name`, `alb_zone_id`, `alb_https_listener_arn`, `alb_http_listener_arn`, `alb_security_group_id`.
- New assertion: env-tier listener-rule `listener_arn` references `data.terraform_remote_state.project.outputs.alb_https_listener_arn`.
- New assertion: project ALB SG references the cert ARNs via `aws_acm_certificate_validation.{stage,prod}.certificate_arn`.
- `tests/unit/test_hcl_emitter.py` for the listener-rule emit: assert the new remote-state reference.

## Ramifications

### Single ALB shared between stage and prod

The doctrine intent: one ALB hosts traffic for both stage and prod, distinguishing by SNI (cert binding matches incoming Host header) and listener rule (host_header condition routes to per-service target group). This:

- Halves the ALB cost vs. per-env ALBs.
- Means a stage misconfiguration *could* affect prod listener-rule priorities — the priority allocator must namespace per env. The current hcl.py priority computation gives each service a per-service priority; with the move, those priorities now need to be per-(env, service). Implementer should check the priority logic and ensure no collision between stage and prod rules.

### `release` workflow unchanged

The release flow continues to drive env-tier `tofu apply` against env main.tf. With listener rules and target groups still env-tier, releases add/remove rules against the long-lived project ALB. This matches `projinfra/elastic_alb.md`'s lifecycle description.

### First-release ordering

On the very first elastic env release, the project ALB must exist (via `projinfra up production`) before env-tier listener rules can reference it. This precondition was already implicit in `projinfra up production` running before `release stage|prod`; mod 038 doesn't change the precondition shape.

## Operator Decisions

1. **Listener-rule priority namespacing**: stage gets `1000–4999`, prod gets `5000–9999`. Each service within an env gets a sub-priority within its range. Collisions impossible by construction.
2. **Prod cert is the listener default**; stage cert attaches via `aws_lb_listener_certificate.project_stage`. SNI selects on Host header; default cert is the conservative fallback.
3. **Keep `subnets = aws_subnet.public[*].id`** for now. Mod 041 swaps to master VPC data sources. Add a `# mod 041 will replace this` comment at the reference site.

## What This Mod Is NOT

- **No listener rule or target group refactor** — those stay env-tier; mod 040 may do further refactors around them.
- **No master VPC switchover** — mod 041.
- **No ECR/IAM moves** — mod 039.
- **No EC2-traefik variant** — mod 044.
- **No `test_projects/{fixed,elastic}/` edits.**

## Key files

- `src/docex/emit/templates/project.tf.j2` (add ALB set + outputs)
- `src/docex/emit/templates/main.tf.j2` (delete ALB resources; refactor refs to remote state)
- `src/docex/emit/hcl.py` (`emit_hcl_project` adds naming inputs; listener-rule emit switches to remote state)
- Tests for both sides

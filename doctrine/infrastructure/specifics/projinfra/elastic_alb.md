---
stratum: conditional
---

# Elastic ALB

This file describes the project ALB — the default reverse-proxy variant on elastic-foundation production sides (`reverse_proxy: alb` in `infra.yml`, the default). Projects that opt into the alternative [`ec2_traefik_eip` / `ec2_traefik_pip`](./ec2_traefik.md) variants do *not* get this resource; the two paths are mutually exclusive at the project tier.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Role

One ALB per ALB-using project, in the [master VPC](../../preinfra/elastic_master_network.md)'s public subnets. It is the public entry point for the project's `stage` and `prod` envs, performing three roles:

1. **TLS terminator.** Inbound 443 traffic is decrypted using the project ACM certs (see [`elastic_acm_certs.md`](./elastic_acm_certs.md)) attached as SNI bindings.
2. **Reverse proxy.** Decrypted requests are routed by host header (and optional path) to env-tier target groups via host-based listener rules. Env-tier `main.tf` files emit those listener rules and target groups; the ALB itself just provides the listener.
3. **Load balancer.** When a `prod` env has multiple replicas of the same ECS service, the ALB balances across the registered target IPs.

The ALB is **project-tier**: one ALB serves both stage and prod, and stays up across deploys. Env-tier `release` adds, removes, and rolls listener rules and target groups against the existing ALB.

## Resources

A complete ALB projinfra set consists of:

| Resource | HCL | Note |
| -------- | --- | ---- |
| ALB | `aws_lb.project` | `load_balancer_type = "application"`, internet-facing, in the master VPC |
| ALB security group | `aws_security_group.project_alb` | Ingress 80/443 from `0.0.0.0/0`; egress allow-all |
| Listener (443) | `aws_lb_listener.project_https` | Terminates TLS with stage + prod ACM certs as SNI bindings; default action is a fixed-response 404 |
| Listener (80) | `aws_lb_listener.project_http` | Redirects to 443 with a 301 |

The ALB SG (`aws_security_group.project_alb`) is referenced by env-tier `${project}-${env}-web` SGs as their ingress source — that's how env-tier services accept ALB-originated traffic and only ALB-originated traffic.

## Naming

The ALB and its SG follow the doctrine's general naming pattern from [transfer_tables.md § Naming Policies](../transfer_tables.md#naming-policies):

| Resource | Policy | Rendered example |
| -------- | ------ | ---------------- |
| ALB | `alb` | `myproject-alb` |
| ALB SG | `alb` | `myproject-alb-sg` |
| Listeners | (not separately named; identified by attached ALB ARN) | — |

The `alb` policy is hyphen-separated, case-preserving, max length 32.

## Subnet Placement

The ALB attaches to the master VPC's two public subnets (one in the primary AZ, one in the secondary). The secondary-AZ subnet is included only because AWS requires ALBs to span at least two AZs — the doctrine's elastic projects are otherwise single-AZ per [cicl.md § Simplifications](../../cicl.md#simplifications). The redundant subnet is present, available to receive traffic if AWS routes any to it, and accepted as overhead in exchange for ALB-as-a-service.

Both subnets are looked up via data sources from the master-VPC preinfra; the ALB does not create or own them. See [preinfra/elastic_master_network.md](../../preinfra/elastic_master_network.md).

## Listener Rules: What's Project-Tier vs. Env-Tier

The ALB itself (and its listeners) is project-tier. The listener *rules* — the things that match `Host: api.prod.myproject.example.com` and forward to a specific target group — are **env-tier**, emitted by `./bin/docex compile` into each env's `main.tf`. Two reasons:

1. Listener rules are 1:1 with env-tier ECS services. Adding a new service to `stage` adds a rule; removing a service removes one. Coupling rule lifecycle to env-tier release is the natural fit.
2. Rule priorities are scoped per-listener but otherwise unstructured. The compiler assigns deterministic priorities at compile time per env, so env-A's rules don't collide with env-B's.

Each env-tier listener rule references the project ALB by ARN, which the env's `main.tf` reads via (this example assumes `api` is the project's `domain_default_service` per [cicl.md § Domain](../../cicl.md#domain), which is why the `values` list carries the bare-prod-env and bare-project alternates; services that are not the default get only the full `<service>.<env>.<project>.<apex>` host):

```hcl
data "terraform_remote_state" "project" {
  backend = "s3"
  config = {
    bucket = "..."
    key    = "project/terraform.tfstate"
    ...
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = data.terraform_remote_state.project.outputs.alb_https_listener_arn
  priority     = <doctrine-computed>
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    host_header {
      values = [
        "api.prod.myproject.example.com",
        "prod.myproject.example.com",
        "myproject.example.com",
      ]
    }
  }
}
```

The doctrine commits to host-header matching as the default. Path-based routing (`/api/*` to one service, `/admin/*` to another) is a future extension — currently each service gets its own subdomain.

## Outputs Consumed Downstream

The project's `main.tf` declares:

| Output | Used by |
| ------ | ------- |
| `alb_arn` | (Mostly internal — referenced by listener resources in the same file) |
| `alb_dns_name` | The env-tier Route53 A-records (alias targets) emitted by `release`; see [release.md](../release.md) |
| `alb_zone_id` | Route53 A-record alias config (alias targets need both DNS name and zone ID) |
| `alb_https_listener_arn` | Env-tier listener rules |
| `alb_http_listener_arn` | (Rarely needed; redirect-only) |
| `alb_security_group_id` | Env-tier `${project}-${env}-web` SG ingress rules — see [networks.md](../networks.md) |

## Cost Profile

An ALB costs roughly $16–$25/month in `us-east-1` at low traffic (LCU base + ~zero per-LCU on minimal traffic). This is the dominant cost of the elastic reverse-proxy path; projects whose monthly bill is dominated by the ALB should consider the [`ec2_traefik`](./ec2_traefik.md) alternative, which runs at ~$4–8/month at the cost of more operational surface area.

The doctrine is **neutral** about which variant a project picks. ALB and EC2-traefik present different cost / management / quota trade-offs; the right choice depends on project specifics the doctrine has no way to know.

## Lifecycle

The ALB comes up with `./bin/docex projinfra up production`, stays up across env-tier deploys, and goes down only with `./bin/docex projinfra down production`. `release` never recreates the ALB — it only adds, modifies, or removes listener rules and target groups against the existing ARN.

When the operator changes the `reverse_proxy:` field in `infra.yml` (e.g., from `alb` to `ec2_traefik_eip`), `./bin/docex projinfra up production` will:
1. Detect the change at compile time, surface it as a warning before running.
2. On apply, tofu will destroy the ALB and its SG (the old resources are no longer in the rendered HCL) and create the EC2-traefik resources.
3. The DNS A-records (env-tier) re-aim at the new IP automatically on the next `release`.

This is a brief-downtime operation, not a zero-downtime one — the ALB destroys, then the EC2 instance creates, with a window in between where the project's domain has no target. The doctrine accepts this as a deliberate reconfigure; it is not a path projects take routinely.

## Out of Scope

- **Path-based routing.** Currently subdomain-only.
- **WAF integration.** No `aws_wafv2_web_acl_association` is emitted. Projects that need WAF can attach one out-of-band.
- **Cross-region failover.** The doctrine is single-region; multi-region ALB is deferred.

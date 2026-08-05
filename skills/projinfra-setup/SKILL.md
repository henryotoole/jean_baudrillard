---
name: projinfra-setup
description: Doctrine for setting up and debugging project-tier infrastructure — the reverse proxy (ALB, EC2-traefik, or project traefik), TLS certs, ECR, the IAM exec role, the Route53 zone, and the tofu state backend. Use this whenever you are bringing project infra up or down, or compiling or debugging the project tier, even if the word "projinfra" is never used.
metadata:
  type: thread
---

# projinfra-setup

Project-tier infrastructure is shared across a project's environments and split by side and foundation; read the orientation and the matrix first, then descend into the per-resource file for what you are provisioning.

## General Information

What the project tier is and which resources apply. **Read this now.**

[`projinfra.md`](../../doctrine/infrastructure/specifics/projinfra/projinfra.md) — the project tier explained: the side duplication, the foundation × side matrix, and how projinfra relates to preinfra, envinfra, and release; routes to the per-resource files.

## Specific Information

The per-resource detail. **Read the one(s) you are provisioning** — note the fixed/elastic split and the reverse-proxy choice.

[`fixed_reverse_proxy.md`](../../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md) — the per-project traefik plus four `-web` networks (all fixed sides, and the elastic dev side).

[`elastic_alb.md`](../../doctrine/infrastructure/specifics/projinfra/elastic_alb.md) — the default elastic reverse proxy (ALB).

[`ec2_traefik.md`](../../doctrine/infrastructure/specifics/projinfra/ec2_traefik.md) — the low-cost EC2-plus-traefik reverse-proxy variant (mutually exclusive with the ALB).

[`elastic_acm_certs.md`](../../doctrine/infrastructure/specifics/projinfra/elastic_acm_certs.md) — the two ACM wildcard certs (ALB path only).

[`elastic_route53_zone.md`](../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md) — the per-project hosted zone and the NS-delegation step.

[`elastic_ecr.md`](../../doctrine/infrastructure/specifics/projinfra/elastic_ecr.md) — the per-codebase ECR repositories.

[`elastic_iam.md`](../../doctrine/infrastructure/specifics/projinfra/elastic_iam.md) — the per-project ECS task-execution role.

[`elastic_state_backend.md`](../../doctrine/infrastructure/specifics/projinfra/elastic_state_backend.md) — the S3-plus-DynamoDB OpenTofu state backend (a bootstrap precondition).

## Thread

- The project tier requires preinfra in place first (`preinfra-setup`); bring environments and releases up afterward via `cicd-pipeline`.
- The reverse-proxy choice (`reverse_proxy:` → ALB vs. EC2-traefik) is authored in `infra.yml` (`infra-compile`) and reasoned about in `network-design`.
- Driven by `./bin/docex projinfra <direction> <side>` — the command reference is [`docex.md`](../../doctrine/infrastructure/docex.md).

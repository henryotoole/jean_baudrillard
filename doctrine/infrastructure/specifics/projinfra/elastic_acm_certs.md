---
stratum: conditional
---

# Elastic ACM Certs

This file describes the ACM certificates created on the production side of every elastic-foundation project that uses the default `reverse_proxy: alb` variant. Projects using `ec2_traefik_eip` or `ec2_traefik_pip` skip ACM entirely — their certs are issued by traefik's built-in Let's Encrypt client; see [`ec2_traefik.md`](./ec2_traefik.md).

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Resources

Two ACM certificates per ALB-using elastic project, both in the project's elastic region (currently `us-east-1`):

1. **Stage cert** — covers:
   - `*.stage.<project>.<apex_domain>` — the stage-env wildcard.
   - `stage.<project>.<apex_domain>` — the stage ergonomic domain.
2. **Prod cert** — covers:
   - `*.prod.<project>.<apex_domain>` — the prod-env wildcard.
   - `prod.<project>.<apex_domain>` — the prod ergonomic domain.
   - `<project>.<apex_domain>` — the bare-project host, routing to prod's `domain_default_service`.

Both certs are attached to the project's ALB as SNI certs by [`elastic_alb.md`](./elastic_alb.md) at projinfra-apply time. The ALB selects the right cert at TLS handshake based on the SNI host of the incoming request.

## Why Two Certs

ACM issues the two wildcard certs from [cicl.md § Elastic TLS](../../cicl.md#elastic-tls); dev/test are not ACM certs at all:

| Env | Cert(s) | Live on |
| --- | ------- | ------- |
| `dev` + `test` | Per-host certs (one per `web`-service hostname under `dev.`/`test.`) — HTTP-01, **not** wildcards | The dev-side per-project traefik (LE-issued); see [`fixed_reverse_proxy.md`](./fixed_reverse_proxy.md) |
| `stage` | Stage cert (wildcard, DNS-01) | This file |
| `prod` | Prod cert (wildcard, DNS-01) | This file |

Dev/test certs aren't emitted by ACM because those envs are always fixed-style per [shape2.md § Shape and Environment](../../shape2.md#shape-and-environment) — they never reach the AWS ALB. The traefik that handles them issues per-host HTTP-01 certs per [Fixed TLS](../../cicl.md#fixed-tls); there is no single wildcard "development cert".

## DNS-01 Validation

The certs use DNS-01 validation against the project's Route53 zone (see [`elastic_route53_zone.md`](./elastic_route53_zone.md)). DNS-01 is mandatory because the certs include wildcards (`*.stage.<project>...`, `*.prod.<project>...`), which ACM only issues via DNS-01 — HTTP-01 doesn't support wildcards.

`docex` emits ACM cert validation records as Route53 `aws_route53_record` resources in the project's `main.tf`. The validation records are CNAMEs of the form `_<token>.<domain>` pointing at ACM-provided validation hosts; ACM polls them to verify the operator controls the zone, and once verified, issues the cert.

The validation records live in the project's hosted zone, not the parent. This is why the [zone's NS delegation](./elastic_route53_zone.md#ns-delegation) must be in place before the certs can be issued — until delegation propagates, public resolvers (including ACM's) can't see the validation records.

This is also why `./bin/docex projinfra up production` splits the apply into two phases: phase 1 creates only the zone (so the operator can NS-delegate); phase 2 creates the certs along with everything else.

## Renewal

ACM auto-renews certs within their final 60 days, refreshing the validation records as needed. No operator action required. As long as the project's Route53 zone keeps its delegation, renewal is fully managed by AWS.

If delegation lapses — e.g., the operator changes the parent zone's NS records away from the project's zone — ACM cannot validate and renewal fails. ACM emails the AWS-account contact 45/30/7/1 days before expiry. The doctrine doesn't add a separate monitoring layer for this; the failure mode is rare and AWS's existing channels are sufficient.

## Outputs Consumed Downstream

The project's `main.tf` declares:

| Output | Used by |
| ------ | ------- |
| `stage_cert_arn` | The ALB's listener (for the stage SNI binding); see [`elastic_alb.md`](./elastic_alb.md) |
| `prod_cert_arn` | The ALB's listener (for the prod SNI binding) |

The ALB itself is also project-tier and lives in the same `main.tf`, so these outputs are mostly used by the local resources in the file rather than by env-tier remote-state lookups.

## Out of Scope

- **Multi-region certs.** The doctrine pins to `us-east-1`. If a future doctrine adds regional flexibility, this file will need a note on per-region cert provisioning.
- **Customer-supplied certs.** Projects with pre-existing wildcard certs from a third party would have to skip ACM entirely. Out of scope; ACM-issued is the only supported path.
- **HTTP-01 fallback.** Not supported by ACM with wildcards. Projects that genuinely need HTTP-01 should use `ec2_traefik_*` instead.

---
stratum: conditional
---

# EC2-with-Traefik Reverse Proxy

This file describes the elastic-foundation `ec2_traefik` reverse-proxy option — the project-tier alternative to the default [`elastic_alb.md`](./elastic_alb.md). It is one of two mutually-exclusive choices for an elastic project's production-side reverse proxy, selected via `reverse_proxy:` in `infra.yml`.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Purpose

The doctrine's default elastic reverse proxy is the project ALB. ALBs are reliable, fully managed by AWS, and don't burden the operator with patching or instance lifecycle. They are also relatively expensive. For projects with low traffic and limited budget, that cost can dominate the project's bill.

The `ec2_traefik` option replaces the project ALB with a single, doctrine-managed EC2 instance running [Traefik](https://traefik.io/traefik/) as a project-scoped reverse proxy + TLS terminator + load balancer. It serves the same role as the ALB — terminating TLS for `web`-network services and routing inbound HTTP/HTTPS to the right ECS service — at substantially lower cost (~$4–8/month all-in, depending on variant).

The choice is project-level, set in `infra.yml`:

```yml
reverse_proxy: alb               # default
# reverse_proxy: ec2_traefik_eip
# reverse_proxy: ec2_traefik_pip
```

The doctrine is **neutral** about which variant to choose. ALB and EC2-traefik present different cost / management / quota trade-offs; the right choice depends on project specifics the doctrine has no way to know.

## The Two Variants

`ec2_traefik` has two variants distinguished by how the instance gets its public IP:

| Variant | Public IP Source | Quota Impact | IP Stable Across Stop/Start? |
| ------- | ---------------- | ------------ | ---------------------------- |
| `ec2_traefik_eip` | Elastic IP allocation | 1 EIP / project against the 5-EIP regional default (soft-raisable) | Yes |
| `ec2_traefik_pip` | AWS-assigned public IPv4 | None — auto-assigned addresses are not quota-limited | No — changes on instance stop/start |

Both variants incur the AWS public-IPv4 hourly charge ($0.005/hour ≈ $3.60/month) introduced in Feb 2024. Cost is identical between the two variants; the difference is only the EIP quota and IP stability behavior.

The `eip` variant suits projects where DNS stability across instance lifecycle events matters more than EIP-quota headroom. The `pip` variant suits projects where EIP quota is the binding constraint and brief DNS update windows after AWS-initiated instance retirements are acceptable.

## Instance Shape

The doctrine prescribes a uniform instance shape across both variants. The transfer table allows project-local overrides for sizing if needed.

| Attribute | Default | Note |
| --------- | ------- | ---- |
| Instance type | `t3.nano` (0.5 GB RAM, 2 vCPU burstable) | Sufficient for low single-digit RPS. Override via project-local transfer table. |
| AMI | Latest Ubuntu 24.04 LTS published by Canonical | Looked up at apply time via `data "aws_ami"` with `owner = "099720109477"` (Canonical's AWS account) and a name pattern pinned at the docex-version level. |
| Subnet | Master VPC's primary-AZ public subnet (`public-az-1`) | Public subnet because the instance needs an inbound-reachable public IP. Same AZ as the ECS services it routes to, to avoid cross-AZ data transfer to backends. |
| Root volume | 20 GB gp3 | Plenty for the OS + traefik + transient logs. |

## Routing Discovery

Traefik on the instance learns about backend services via the same model the ALB uses — declarative routing rules paired with runtime backend address resolution.

**Routing rules** are emitted by `./bin/docex compile` into the project's env-tier HCL as SSM Parameter contents (see [Config Delivery](#config-delivery) below). Each `web`-network service in stage and prod gets a rule of roughly the form (this example assumes `api` is the project's `domain_default_service` per [cicl.md § Domain](../../cicl.md#domain), which is why prod's rule carries the bare-project and bare-env alternates and stage's rule carries the bare-stage-env alternate; services that are not the default get only the full `<service>.<env>.<project>.<apex>` host):

```yaml
http:
  routers:
    api-prod:
      rule: "Host(`api.prod.myproject.example.com`) || Host(`prod.myproject.example.com`) || Host(`myproject.example.com`)"
      service: api-prod
      tls:
        certResolver: doctrine
    api-stage:
      rule: "Host(`api.stage.myproject.example.com`) || Host(`stage.myproject.example.com`)"
      service: api-stage
      tls:
        certResolver: doctrine
  services:
    api-prod:
      loadBalancer:
        servers:
          - url: "http://myproject-prod-api.myproject-prod:8080"
    api-stage:
      loadBalancer:
        servers:
          - url: "http://myproject-stage-api.myproject-stage:8080"
```

**Backend addresses** are resolved at runtime via the Cloud Map private DNS namespace each env registers with Service Connect — see [shape.md § Elastic-Foundation](../../shape.md#elastic-foundation). The right-hand-side host has the form `<discoveryName>.<namespace>`, where `discoveryName = ${global_service_name}` (the same flat name `provides.host.elastic` emits to app env vars — e.g. `myproject-prod-api`) and `namespace = ${project}-${env}` (e.g. `myproject-prod`). From inside an ECS task the discoveryName alone resolves via the Envoy sidecar, but the EC2-traefik instance lives outside any task netns, so it must use the fully-qualified form — VPC DNS doesn't auto-search the Cloud Map namespace as a default search domain. ECS rotates the underlying task IPs behind the name as services roll. Traefik does not need AWS SDK access for this — only DNS resolution, which the instance has by default in any VPC subnet.

This parallels how the ALB option works (ALB listener rules + ECS-managed target group membership) and reuses doctrine machinery — Service Connect — that already exists for inter-service discovery. No traefik ECS-provider plugin, no ECS API polling, no IAM-mediated traefik discovery.

## Config Delivery

The traefik config — both static settings (TLS, LE) and dynamic routing rules — lives in an SSM Parameter at `/<project>/ec2_traefik/config.yml` as a `SecureString` (the LE config can reference IAM-scoped secrets indirectly; encrypting at rest is consistent with other SSM use in the doctrine).

The instance runs a small systemd timer (`docex-traefik-config.timer`, fires every 30s) that calls `aws ssm get-parameter`, compares to the on-disk version, writes the new value to `/etc/traefik/dynamic.yml` if changed, and exits. Traefik's file provider watches that path and reloads on change — no restart, no dropped connections.

Release flow:

1. `./bin/docex release stage` (or `prod`) re-renders the config from the merged stage+prod state.
2. The new content is pushed to the SSM Parameter via `ssm:PutParameter` with `Overwrite=True`.
3. Within 30 seconds, the systemd timer on the instance picks up the change. Traefik reloads. New routes are live.

This delivery model:

- Uses no SSH (no port 22 exposure, no key management).
- Survives instance replacement transparently — the new instance fetches config from SSM on boot.
- Decouples config changes from instance lifecycle. Most releases don't require instance replacement; only docex-version bumps that change the AMI or user_data do.

The static portion of the traefik config (entrypoints, LE resolver config, cert paths) is rendered into the user_data at instance creation time. Changes to the static config require instance replacement; see [Lifecycle](#lifecycle-recovery-and-updates) below.

## TLS and Cert Handling

EC2-traefik uses Traefik's built-in Let's Encrypt client instead of the ALB option's ACM certificates. This is a fundamental architectural difference — the doctrine commits to it for the EC2-traefik path.

**Challenge type:** DNS-01 via Route53, always. Project-tier IAM role grants the instance `route53:ChangeResourceRecordSets` scoped to the project's Route53 zone, which is sufficient for traefik's LE client to complete DNS-01 challenges. HTTP-01 is not used on elastic — DNS-01 is always available (Route53 is part of the doctrine's elastic prereq) and supports wildcards.

**Cert SAN set:** The two-cert layout defined [here](../../cicl.md#elastic-tls) — i.e. the same two certs that ACM would issue for the ALB path. Identical SAN structure to the ACM certs in [`elastic_acm_certs.md`](./elastic_acm_certs.md); only the issuance mechanism differs (LE in traefik vs. ACM-managed). The dev/test certs are still issued via HTTP-01 by the dev-side per-project traefik per [fixed_reverse_proxy.md](./fixed_reverse_proxy.md), so the split is the same on both elastic reverse-proxy paths.

**Cert persistence across instance replacement:** an EBS volume (8 GB gp3, in `public-az-1`) is attached to the instance at `/etc/traefik/acme/`. The volume holds traefik's `acme.json` (cert material + LE account key). It is:

- Created by `./bin/docex projinfra up production` *only when* the project opts into EC2-traefik (not for ALB projects).
- Tagged with doctrine tags (`managed_by = "doctrine"`, `project = "<project>"`, `purpose = "ec2_traefik_acme"`) so the instance's boot script can discover and attach it.
- Configured with `delete_on_termination = false` so it survives `tofu destroy` of the EC2 instance.

When the instance is replaced (AMI bump, user_data change, manual termination), the new instance's boot script attaches the same EBS volume. Traefik finds the existing `acme.json` and skips reissuance — no LE rate-limit pressure on replacement events. The LE 5-duplicate-certs-per-week limit only bites if the volume itself is destroyed and reissuance happens from scratch within a week.

## DNS Update on Boot (PIP Variant Only)

The `pip` variant needs DNS-record updates whenever the instance's public IP changes (on stop/start events). The mechanism:

A doctrine-provided systemd unit (`docex-traefik-dns-update.service`) runs once per boot. It:

1. Reads the current public IPv4 from EC2 instance metadata (IMDS): `curl -s http://169.254.169.254/latest/meta-data/public-ipv4`.
2. Calls `route53:ChangeResourceRecordSets` to update all five project A-records to the current IP:
    - `<project>.<apex_domain>` (bare project)
    - `*.prod.<project>.<apex_domain>` (prod wildcard)
    - `prod.<project>.<apex_domain>` (prod ergonomic)
    - `*.stage.<project>.<apex_domain>` (stage wildcard)
    - `stage.<project>.<apex_domain>` (stage ergonomic)
3. Submits all five record updates as a single `ChangeResourceRecordSets` batch — atomic from Route53's perspective. If submission fails, the unit exits non-zero and journald logs the error; systemd's restart-on-failure brings it back up.
4. Polls `route53:GetChange` until propagation completes (or a 3-minute timeout), then exits cleanly.

DNS TTLs on these records are set to 60 seconds at projinfra-apply time, so propagation to clients is fast even when the instance changes IPs.

The `eip` variant skips this entirely. EIP is assigned at instance launch via Tofu; the five Route53 records point at the EIP and never need updating during the instance lifecycle.

## Networking and Security Groups

When a project opts into EC2-traefik, projinfra creates a project-tier security group `<project>-traefik` in the master VPC. The SG has:

- **Ingress:** `tcp/80` and `tcp/443` from `0.0.0.0/0` (the instance is the public entry point for the project).
- **Egress:** allow-all (matches the doctrine's default per-SG egress rule).

The env-tier `<project>-<env>-web` security groups (created at env-tier release time) accept ingress from `<project>-traefik` on each `web`-network service's declared port — the analog of "ALB SG → web SG" rules for projects on the ALB path. The two rule shapes mirror each other:

| Reverse proxy choice | Ingress source on env-tier `web` SG |
| -------------------- | ----------------------------------- |
| `alb` | The project's ALB SG (created at projinfra-apply) |
| `ec2_traefik_*` | The project's `<project>-traefik` SG (created at projinfra-apply) |

ALB projects do not get a `<project>-traefik` SG. EC2-traefik projects do not get a project ALB SG. The two paths are mutually exclusive at the project tier; switching between them requires a projinfra-side reconfigure.

## IAM Role

The EC2-traefik instance assumes a project-tier IAM instance profile (`<project>_traefik_role`, created by projinfra only when the project opts into EC2-traefik). This is *distinct* from the ECS task-execution role described in [`elastic_iam.md`](./elastic_iam.md) — different principal (`ec2.amazonaws.com` vs. `ecs-tasks.amazonaws.com`), different permissions. Permissions:

| Permission | Scope | Why |
| ---------- | ----- | --- |
| `route53:ChangeResourceRecordSets`, `route53:GetChange` | The project's Route53 zone only | DNS-01 LE challenge + (PIP variant) boot-time DNS update |
| `ssm:GetParameter`, `ssm:GetParameters` | `/<project>/ec2_traefik/*` | Config fetch |
| `logs:CreateLogStream`, `logs:PutLogEvents` | The project's `/<project>/ec2_traefik` CloudWatch Log Group | Traefik log shipping |
| `ec2:AttachVolume`, `ec2:DescribeVolumes` | EBS volume tagged `purpose=ec2_traefik_acme` and the matching project | EBS cert volume attach at boot |

The Route53 scoping is the most permission-sensitive — the IAM policy restricts changes to the project's hosted zone ID, not the apex zone. A compromised EC2-traefik instance cannot manipulate DNS for other projects on the same apex.

## Logging

Traefik logs (access logs + error logs) ship to CloudWatch Logs via the [AWS CloudWatch Logs agent](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/AgentReference.html) running on the instance. The doctrine emits one log group per project: `/<project>/ec2_traefik`. Retention is doctrine-prescribed (30 days at v1).

The cost is modest — a few cents per month per project for typical traffic. The benefit is parity with ECS task logs, queryability in the AWS console, and a log audit trail that survives instance replacement.

journald is also available on the instance via SSM Session Manager for live debugging (`aws ssm start-session --target i-...`); the SSM agent ships preinstalled on Ubuntu AMIs.

## Lifecycle: Recovery and Updates

Three lifecycle events worth being explicit about:

**Crash + auto-recovery.** A CloudWatch alarm + EC2 Auto Recovery is configured at instance creation to reboot the instance in place on system-status-check failures. IP is preserved (both variants). EBS volume is re-attached. Boot scripts run; DNS update (PIP variant) is a no-op because the IP hasn't changed. Traefik comes back up and resumes serving. Total downtime: typically 2–5 minutes.

**AWS-initiated retirement.** AWS schedules the instance for hardware retirement. The operator stops + starts the instance during the retirement window. PIP variant: new IP, boot-time DNS update propagates within ~60 seconds. EIP variant: same IP, no DNS update needed. EBS volume re-attaches; certs preserved. Total user-visible downtime: 60 seconds (PIP) or near-zero (EIP).

**docex-version bump that changes AMI or static config.** Operator runs `./bin/docex projinfra up production` (typically as part of a docex upgrade). Tofu detects an AMI ID change or user_data change and triggers instance replacement. The new instance launches with the new AMI/user_data; the EBS cert volume re-attaches; certs preserved; SSM Parameter config is fetched fresh. PIP variant updates DNS on boot. Downtime is bounded by instance launch time, typically 30–90 seconds.

The replacement-with-EBS-preservation model is what makes docex-version bumps acceptable on the EC2-traefik path. Without it, every AMI bump would cost an LE cert reissuance and potentially hit rate limits.

## Failure Modes

| Symptom | Probable cause | Where to look |
| ------- | -------------- | ------------- |
| 502/504 from clients, traefik logs show "no available servers" | Service Connect name resolution failing — ECS service not registered or task not healthy | ECS console for the service; `aws servicediscovery list-services` for the Cloud Map namespace |
| Cert renewal fails | Route53 IAM permission revoked, or hosted zone deleted | CloudWatch Logs for traefik; `aws route53 get-hosted-zone` to confirm zone exists |
| New routes not appearing on instance | SSM Parameter not updated, or systemd timer not running | `systemctl status docex-traefik-config.timer` on the instance via SSM Session Manager; `aws ssm get-parameter --name /<project>/ec2_traefik/config.yml` to check current value |
| DNS records stale after stop/start (PIP variant) | Boot-time DNS update unit failed | `journalctl -u docex-traefik-dns-update.service` on the instance |
| Instance comes up but cert material missing | EBS volume attach failed | `journalctl -b` boot logs on the instance; `aws ec2 describe-volumes --filters Name=tag:purpose,Values=ec2_traefik_acme` |
| LE rate limit hit | EBS volume was destroyed and recreated multiple times in a week | Check EBS volume creation history; the doctrine should not normally destroy this volume — investigate why it happened |

## What's Projinfra-Created vs. Envinfra-Created

For an EC2-traefik project, the project-tier vs env-tier emission split is:

**Projinfra (`infra/output/project/production/main.tf`):**
- The EC2 instance itself, its user_data (with static traefik config), and its EIP if applicable
- The `<project>-traefik` security group
- The EBS volume for cert persistence, tagged for discovery
- The IAM instance profile and role with the four scoped permissions
- The CloudWatch Log Group `/<project>/ec2_traefik`
- The five Route53 A-records (EIP variant pre-populates them; PIP variant initializes them at first boot)

**Envinfra / Release (`infra/output/<env>/main.tf`):**
- Per-service Service Connect registration on the env's ECS services (already happens for inter-service comms)
- SSM Parameter `/<project>/ec2_traefik/config.yml` content updates (re-rendered on each release to reflect current service set and routing rules)
- Env-tier `<project>-<env>-web` SG ingress rule allowing the project's traefik SG

The split mirrors the ALB option: the reverse-proxy resource itself is project-tier; per-service routing config is env-tier.

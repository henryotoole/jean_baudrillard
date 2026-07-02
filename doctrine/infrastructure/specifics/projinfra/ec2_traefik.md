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

Traefik on the instance discovers backend services through its built-in **ECS provider** (`providers.ecs`). This is the elastic analog of how the fixed-foundation project traefik uses its **docker provider** (see [`fixed_reverse_proxy.md`](./fixed_reverse_proxy.md) and [`release.md`](../release.md)): in both cases traefik reads routing intent from labels on the workloads themselves and rebuilds its routing table automatically as workloads come and go. Nothing is pushed to traefik at release time on either foundation.

**How it works.** The ECS provider polls the ECS/EC2 control plane every `refreshSeconds` (doctrine default: 15s) for the project's `stage` and `prod` clusters. For each `RUNNING` Fargate task it reads the task ENI's private IPv4 directly from the task description and builds routers and services from the container's `dockerLabels`. The instance therefore needs scoped ECS/EC2 read access (see [IAM Role](#iam-role)) — it does not resolve backends by DNS.

**Why the provider and not DNS.** ECS Service Connect — the mechanism that gives *in-mesh* services name resolution — resolves only inside the mesh, via the Envoy sidecar injected into each task. Its Cloud Map private DNS namespace carries no per-service A-records, so a client *outside* the mesh (the EC2-traefik instance lives in the master VPC but in no task's network namespace) cannot resolve services by name at all. Beyond that, the provider gives what a DNS approach structurally cannot: traefik load-balances across *all* of a service's running task IPs and drops a task from the pool as soon as it leaves `RUNNING` on the next refresh — real balancing and health-gating rather than DNS round-robin against a possibly-stale record.

**Labels.** `./bin/docex compile` emits the traefik labels onto each `web`-network service's container definition in the env-tier HCL. `exposedByDefault` is `false`, so only services carrying `traefik.enable=true` are routed; port-less workers and backing services are never exposed. Router names encode the env (`<service>-<env>`) so the single instance's `stage` and `prod` views don't collide. Each `web`-network service in stage and prod gets labels of roughly the form (this example assumes `api` is the project's `domain_default_service` per [cicl.md § Domain](../../cicl.md#domain), which is why prod's rule carries the bare-project and bare-env alternates and stage's rule carries the bare-stage-env alternate; services that are not the default get only the full `<service>.<env>.<project>.<apex>` host):

```
traefik.enable=true
traefik.http.routers.api-prod.rule=Host(`api.prod.myproject.example.com`) || Host(`prod.myproject.example.com`) || Host(`myproject.example.com`)
traefik.http.routers.api-prod.tls.certresolver=doctrine
traefik.http.services.api-prod.loadbalancer.server.port=8080
```

The provider fills in the backend server IPs from the running tasks it discovers; the label only declares the container port. ECS rotates task IPs as services roll; the next poll (≤ `refreshSeconds`) reconciles traefik's routing table to the live set. The host-rule logic (including the bare-project / bare-env alternates for the `domain_default_service`) is identical to the ALB path's listener-rule matching, so the two reverse-proxy options route the same hosts to the same services.

## Config Delivery

Traefik's config splits into two halves that are delivered differently:

- **Static config** (entrypoints, the Let's Encrypt cert resolver, cert paths, and the **ECS provider** block — cluster list, region, `refreshSeconds`, `exposedByDefault=false`) is rendered into the instance's user_data at creation time. Changes to it require instance replacement; see [Lifecycle](#lifecycle-recovery-and-updates) below.
- **Dynamic routing** (routers, services, rules) is *not delivered to traefik at all* — it is discovered by the ECS provider from the running tasks' `dockerLabels` (see [Routing Discovery](#routing-discovery)). The routing intent is emitted onto the task definitions by `./bin/docex compile` and reaches AWS through the normal env-tier `tofu apply` during `release`; traefik then picks it up on its next poll.

**Release does not touch traefik.** `./bin/docex release <env>` converges the env's ECS services (new image, new labels) exactly as it always does; within one `refreshSeconds` window the provider reconciles traefik's routing table to the new task set. There is no SSM routing parameter, no `ssm:PutParameter` step in release, and no on-instance config-sync timer. This mirrors the fixed foundation, where release likewise never touches the project traefik — the docker provider picks up joining containers automatically.

This delivery model:

- Uses no SSH (no port 22 exposure, no key management).
- Survives instance replacement transparently — the new instance re-discovers the full routing table from live ECS tasks on boot, with no config to re-fetch.
- Decouples routing changes from instance lifecycle. Most releases don't require instance replacement; only docex-version bumps that change the AMI or static config (user_data) do.

## TLS and Cert Handling

EC2-traefik uses Traefik's built-in Let's Encrypt client instead of the ALB option's ACM certificates. This is a fundamental architectural difference — the doctrine commits to it for the EC2-traefik path.

**Challenge type:** DNS-01 via Route53, always. Project-tier IAM role grants the instance `route53:ChangeResourceRecordSets` scoped to the project's Route53 zone, which is sufficient for traefik's LE client to complete DNS-01 challenges. HTTP-01 is not used on elastic — DNS-01 is always available (Route53 is part of the doctrine's elastic prereq) and supports wildcards.

**Cert SAN set:** The two-cert layout defined [here](../../cicl.md#elastic-tls) — i.e. the same two certs that ACM would issue for the ALB path. Identical SAN structure to the ACM certs in [`elastic_acm_certs.md`](./elastic_acm_certs.md); only the issuance mechanism differs (LE in traefik vs. ACM-managed). The dev/test certs are still issued via HTTP-01 by the dev-side per-project traefik per [fixed_reverse_proxy.md](./fixed_reverse_proxy.md), so the split is the same on both elastic reverse-proxy paths.

**Cert persistence across instance replacement:** an EBS volume (8 GB gp3, in `public-az-1`) is attached to the instance at `/etc/traefik/acme/`. The volume holds traefik's `acme.json` (cert material + LE account key). It is:

- Created by `./bin/docex projinfra up production` *only when* the project opts into EC2-traefik (not for ALB projects).
- Tagged with the **projinfra** tag block from [cicl.md § Naming and Tagging](../../cicl.md#naming-and-tagging) (`shape_name=reverse_proxy`, `descriptor=acme-ebs`, plus the standard `managed_by=doctrine`/`infra_tier=project`/`project`/`Name` keys), **and additionally** the load-bearing resource-local tag `purpose = "ec2_traefik_acme"`. The instance's boot script and the IAM `AttachVolume` grant both match on `purpose=ec2_traefik_acme` + `project`, so that extra tag persists on top of the standard block. The other EC2-traefik resources (instance, SG, IAM role, log group, SSM config, EIP) all carry the same `shape_name=reverse_proxy` projinfra block, differentiated by `descriptor` (EC2 / SG / iam-role / logs / config / EIP); the old bespoke `purpose=ec2_traefik` tag on the SG is dropped (its descriptor now identifies it).
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
| `ecs:ListClusters`, `ecs:DescribeClusters`, `ecs:ListTasks`, `ecs:DescribeTasks`, `ecs:DescribeContainerInstances`, `ecs:DescribeTaskDefinition`, `ec2:DescribeInstances` | The project's `stage` and `prod` ECS clusters (via an `ecs:cluster` condition where the API supports resource-level scoping; the `Describe*`/`List*` actions that AWS only permits at `*` are granted at `*` but read-only) | Backend discovery by the traefik ECS provider |
| `logs:CreateLogStream`, `logs:PutLogEvents` | The project's `/<project>/ec2_traefik` CloudWatch Log Group | Traefik log shipping |
| `ec2:AttachVolume`, `ec2:DescribeVolumes` | EBS volume tagged `purpose=ec2_traefik_acme` and the matching project | EBS cert volume attach at boot |

The Route53 scoping is the most permission-sensitive — the IAM policy restricts changes to the project's hosted zone ID, not the apex zone. A compromised EC2-traefik instance cannot manipulate DNS for other projects on the same apex.

The ECS/EC2 discovery grant is **read-only** and, where AWS supports resource-level conditions, scoped to the project's own clusters — a compromised instance can enumerate the project's tasks but cannot mutate ECS or reach another project's clusters. This is the deliberate cost of the ECS-provider discovery model: it trades a narrow read grant for real load-balancing and health-aware routing that a DNS-only approach cannot provide. The SSM config-fetch grant that earlier revisions carried is gone — routing is no longer delivered via SSM (see [Config Delivery](#config-delivery)).

## Logging

Traefik logs (access logs + error logs) ship to CloudWatch Logs via the [AWS CloudWatch Logs agent](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/AgentReference.html) running on the instance. The doctrine emits one log group per project: `/<project>/ec2_traefik`. Retention is doctrine-prescribed (30 days at v1).

The cost is modest — a few cents per month per project for typical traffic. The benefit is parity with ECS task logs, queryability in the AWS console, and a log audit trail that survives instance replacement.

For deeper live debugging, the instance's `journald` is reachable via SSM Session Manager (`aws ssm start-session --target i-...`) *only* when the environment permits it — the traefik IAM role does not carry `AmazonSSMManagedInstanceCore` by default, and some AWS orgs deny `ssm:StartSession`/`SendCommand` via an SCP. When SSM is unavailable, boot-time diagnostics still land in CloudWatch (the user_data ships its bring-up log to the `/<project>/ec2_traefik` group on exit); a temporary SSH ingress can be added to the traefik SG for hands-on debugging and removed afterward.

## Lifecycle: Recovery and Updates

Three lifecycle events worth being explicit about:

**Crash + auto-recovery.** A CloudWatch alarm + EC2 Auto Recovery is configured at instance creation to reboot the instance in place on system-status-check failures. IP is preserved (both variants). EBS volume is re-attached. Boot scripts run; DNS update (PIP variant) is a no-op because the IP hasn't changed. Traefik comes back up and resumes serving. Total downtime: typically 2–5 minutes.

**AWS-initiated retirement.** AWS schedules the instance for hardware retirement. The operator stops + starts the instance during the retirement window. PIP variant: new IP, boot-time DNS update propagates within ~60 seconds. EIP variant: same IP, no DNS update needed. EBS volume re-attaches; certs preserved. Total user-visible downtime: 60 seconds (PIP) or near-zero (EIP).

**docex-version bump that changes AMI or static config.** Operator runs `./bin/docex projinfra up production` (typically as part of a docex upgrade). Tofu detects an AMI ID change or user_data change and triggers instance replacement. The new instance launches with the new AMI/user_data; the EBS cert volume re-attaches; certs preserved; the ECS provider re-discovers the full routing table from live tasks on its first poll. PIP variant updates DNS on boot. Downtime is bounded by instance launch time, typically 30–90 seconds.

The replacement-with-EBS-preservation model is what makes docex-version bumps acceptable on the EC2-traefik path. Without it, every AMI bump would cost an LE cert reissuance and potentially hit rate limits.

## Failure Modes

| Symptom | Probable cause | Where to look |
| ------- | -------------- | ------------- |
| 502/504 from clients, traefik logs show "no available servers" | No `RUNNING` task discovered for the service — task unhealthy/crash-looping, or the ECS-read IAM grant is missing so the provider sees no tasks | ECS console for the service (task health); traefik logs for provider errors; confirm the instance's IAM role carries the ECS/EC2 discovery grant |
| Cert renewal fails | Route53 IAM permission revoked, or hosted zone deleted | CloudWatch Logs for traefik; `aws route53 get-hosted-zone` to confirm zone exists |
| New routes not appearing on instance | Service's task definition missing the `traefik.*` labels, or the ECS provider not polling | inspect the deployed task definition's `dockerLabels`; traefik logs for `providers.ecs` poll activity; confirm `refreshSeconds` has elapsed |
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
- Per-service Service Connect registration on the env's ECS services (already happens for inter-service comms; unaffected by the reverse-proxy choice)
- The `traefik.*` `dockerLabels` on each `web`-network service's container definition (the routing intent the ECS provider discovers)
- Env-tier `<project>-<env>-web` SG ingress rule allowing the project's traefik SG

The split mirrors the ALB option: the reverse-proxy resource itself is project-tier; per-service routing config is env-tier — carried as ALB listener rules on the ALB path, as task-definition labels on the EC2-traefik path.

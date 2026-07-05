---
stratum: conditional
---

# Projinfra Overview

This folder describes **project-tier infrastructure**: the resources shared by every environment of a project, controlled at the project scope. It mirrors the per-resource layout of [`preinfra/`](../../preinfra/preinfra.md) — one file per resource, foundation-split where the foundations genuinely diverge — and exists for the same reason: an operator setting up, debugging, or extending the project tier benefits from per-resource pages they can land on directly, not a single monolithic file.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context. The doctrine-prose entry points are [infrastructure.md § Infrastructure Tiers](../../infrastructure.md#infrastructure-tiers) and [shape.md](../../shape.md); this folder is what those documents point *to*.

## What "Project Tier" Means

The infrastructure tier of a resource is defined by **what scope controls it**, not by where it physically runs or how many environments touch it. [infrastructure.md § Infrastructure Tiers](../../infrastructure.md#infrastructure-tiers) defines three tiers:

1. **Prerequisite tier** — controlled outside any project. Master networks, the development machine itself, the AWS account, the observability backend. See [`preinfra/`](../../preinfra/preinfra.md).
2. **Project tier** — controlled by the project as a whole, shared across every environment of the project. The reverse proxy, the project's web-network surface, the Route53 zone, the ACM certs, the ECR repositories — all live here.
3. **Environment tier** — controlled per-environment, duplicated across environments. Per-env compose files, per-env security groups, per-env ECS services, per-env RDS instances.

Project-tier resources exist *once per project* (or once per side — see below) and are referenced by every env's compiled output. They must exist *before* any env can come up.

## Sides: Why Project Infra Is Sometimes Duplicated

Some project-tier resources are physically duplicated across two distinct **sides**:

- **Development side** — the development machine, where the `dev` and `test` environments run as docker stacks.
- **Production side** — where `stage` and `prod` run. For a `fixed`-foundation project this is a discrete production host (or the same machine as the development side if the project is single-machine); for an `elastic`-foundation project this is AWS.

The duplication exists because both sides need their own routing surface to deliver traffic to the env-tier services living there. Specifically:

- Every machine that hosts any project env needs the project's **`-web` docker networks** (one per env: `${project}-dev-web`, `${project}-test-web`, `${project}-stage-web`, `${project}-prod-web`) and a **project traefik container** to terminate TLS and forward requests onto the right `-web` network.
- An elastic production side replaces the docker traefik with AWS-native equivalents (an ALB or an EC2-traefik instance, plus ACM certs, plus a Route53 zone, plus ECR repositories).

This produces three distinct topologies in practice:

1. **Single-machine fixed.** One machine hosts every env. Dev side and prod side are the same physical thing. `projinfra up development` and `projinfra up production` converge on the same docker-resource set; running either is idempotent with the other.
2. **Split-machine fixed.** Dev/test run on the operator's local machine; stage/prod run on a remote prod host. The two sides are distinct machines and must be set up separately — `projinfra up development` operates against local docker; `projinfra up production` SSHes to the prod host via Ansible.
3. **Elastic.** Dev/test run on the operator's local machine (always fixed-style per [shape.md § Shape and Environment](../../shape.md#shape-and-environment)); stage/prod run in AWS. `projinfra up development` operates against local docker; `projinfra up production` runs `tofu apply` against AWS.

### Why all four `-web` networks live on every side

A project's compiled output emits **all four** `-web` networks (`${project}-dev-web`, `${project}-test-web`, `${project}-stage-web`, `${project}-prod-web`) on *every* side, regardless of which envs that side actually hosts. The dev machine of an elastic project gets `${project}-stage-web` and `${project}-prod-web` even though it will never run stage or prod envs; the remote prod host of a split-machine fixed project gets `${project}-dev-web` and `${project}-test-web` even though it will never run dev or test envs.

Docker networks are free; precise per-side tailoring would require the compiler to model side-vs-env attachment as a first-class concept just to save a few unused bridge networks. The doctrine pays the small cost of unused networks to keep the compiled output and the project traefik's network attachments uniform across every side.

Non-`web` networks (`internal`, and any other project-defined non-`web` name) are *not* project-tier. They exist per-env, are declared inside each env's `compose.yml`, and are torn up and down with the env. See [networks.md](../networks.md).

## The Four-Cell Matrix

The operator's central question — *"I'm setting up the X side of a Y project — what gets created, in what order, what do I need first?"* — answered:

### Fixed × Development

| Aspect | Detail |
| ------ | ------ |
| What gets created | Four `-web` external docker networks; one project traefik container on `docex-ingress` + all four `-web` networks |
| Resource file | [`fixed_reverse_proxy.md`](./fixed_reverse_proxy.md) |
| Preinfra it depends on | The [fixed master network](../../preinfra/fixed_master_network.md) (`docex-ingress` bridge + machine-wide HAProxy web demux) |
| Compiled output | `infra/output/project/development/docker-compose.yml` |
| `docex` command | `./bin/docex projinfra up development` — `docker compose up -d` against the local docker daemon |

### Fixed × Production

| Aspect | Detail |
| ------ | ------ |
| What gets created | Same as fixed development side, but on the production host (or same host if single-machine) |
| Resource file | [`fixed_reverse_proxy.md`](./fixed_reverse_proxy.md) |
| Preinfra it depends on | The [fixed master network](../../preinfra/fixed_master_network.md) on the *production* host |
| Compiled output | `infra/output/project/production/docker-compose.yml` + `playbook.yml` + `inventory.yml` |
| `docex` command | `./bin/docex projinfra up production` — Ansible playbook against the prod host (or local docker if dev and prod share a machine) |

### Elastic × Development

| Aspect | Detail |
| ------ | ------ |
| What gets created | Four `-web` external docker networks; one project traefik container (same shape as the fixed dev side) |
| Resource file | [`fixed_reverse_proxy.md`](./fixed_reverse_proxy.md) — the dev side of an elastic project is mechanically identical to a fixed dev side |
| Preinfra it depends on | The [fixed master network](../../preinfra/fixed_master_network.md) on the dev machine |
| Compiled output | `infra/output/project/development/docker-compose.yml` |
| `docex` command | `./bin/docex projinfra up development` — `docker compose up -d` against the local docker daemon |

### Elastic × Production

| Aspect | Detail |
| ------ | ------ |
| What gets created | OpenTofu state backend (S3 + DynamoDB); Route53 hosted zone; two ACM certs; the project reverse proxy (ALB *or* EC2-traefik depending on `reverse_proxy:`); one ECR repository per core service; the task-execution IAM role; the two production-side ECS clusters (`${project}-stage`, `${project}-prod`), created empty so they exist before any env release attaches services (see [shape.md § ecs_cluster](../../shape.md#elastic-foundation)) |
| Resource files | [`elastic_state_backend.md`](./elastic_state_backend.md), [`elastic_route53_zone.md`](./elastic_route53_zone.md), [`elastic_acm_certs.md`](./elastic_acm_certs.md), [`elastic_alb.md`](./elastic_alb.md) *or* [`ec2_traefik.md`](./ec2_traefik.md), [`elastic_ecr.md`](./elastic_ecr.md), [`elastic_iam.md`](./elastic_iam.md) |
| Preinfra it depends on | The [elastic master network](../../preinfra/elastic_master_network.md) (master VPC, IGW, NAT, subnets) |
| Compiled output | `infra/output/project/production/main.tf` |
| `docex` command | `./bin/docex projinfra up production` — `tofu apply` against AWS. Runs in two phases on first-ever invocation; see [§ Two-Phase Production-Side Apply (Elastic)](#two-phase-production-side-apply-elastic) below |

## `./bin/docex projinfra <direction> <side>`

The command that brings these resources up and down. Detailed surface in [docex.md § projinfra](../../docex.md#projinfra); the doctrinal behavior:

- **`direction`** is `up` or `down`. `up` reconciles to the declared state (creating what's missing, repairing what's drifted); `down` removes the project's project-tier resources. Both are idempotent — re-running with no changes is a no-op.
- **`side`** is `development` or `production`. The command selects the appropriate mechanism for the `(foundation, side)` cell from the matrix above. For single-machine fixed projects where dev and prod live on the same machine, the two sides converge — `up development` and `up production` end up touching the same docker resources, and running either after the other is idempotent.
- The command refuses to run with `direction=up` if `./bin/docex preinfra <side>` fails. Preinfra must exist before project-tier resources can attach to it.
- The command refuses to run with `direction=down` if any of the project's env-tier infra is still up — `envinfra down <env>` (and `release` rollbacks where applicable) must run first. Project-tier resources are the foundation env-tier resources sit on; tearing them down with envs still using them would orphan running services.

### Two-Phase Production-Side Apply (Elastic)

Elastic production-side projinfra has a hard mid-apply pause for NS delegation. The Route53 zone for `<project>.<apex_domain>` (created by `projinfra`) is unreachable from the public DNS chain until the operator NS-delegates from the parent registrar. ACM cert validation requires that delegation. To avoid hanging the apply on a delegation the operator has yet to perform:

1. **Phase 1 — zone only.** If `aws_route53_zone.project` is not in state, `projinfra up production` runs `tofu apply -target=aws_route53_zone.project`, prints the zone's NS records and the next-step instructions, and exits cleanly. No other project-tier resources are created.
2. **Phase 2 — full apply.** Once the operator has NS-delegated, they re-run `./bin/docex projinfra up production`. The zone is already in state, so the command runs an untargeted `tofu apply`. The ACM certs validate against the now-reachable zone; the rest of the project-tier resources come up.

Phase detection is observed from `tofu state list`, not stored separately. The operator's mental model is single-command: run, do the delegation work it asks for, run again, done.

This rationale lives in [`elastic_route53_zone.md`](./elastic_route53_zone.md) in detail, since that's the resource whose delegation drives the split.

Teardown is symmetric. `projinfra down production` `tofu destroy`s the zone — emitted with `force_destroy` so out-of-band records (e.g. the dev `A`-records the delegation forces into the child zone) can't block the delete with `HostedZoneNotEmpty` — and, once the destroy succeeds, prints a reminder to remove the parent-zone NS delegation the operator added on `up`. Detail in [`elastic_route53_zone.md § Teardown`](./elastic_route53_zone.md#teardown).

### State backend on first-ever invocation

For an elastic project, the OpenTofu state backend (S3 bucket + DynamoDB table) must exist before any `tofu init` can run against the project-tier HCL. The command checks for the backend, creates it directly via the AWS API if missing, then proceeds to the project-tier apply. See [`elastic_state_backend.md`](./elastic_state_backend.md).

## How Projinfra Relates to Other Doctrine Pieces

- **Preinfra is the foundation.** [`preinfra/`](../../preinfra/preinfra.md) covers the master networks, the dev machine itself, the AWS account, the container registry on fixed, and the observability backend. Projinfra resources attach to preinfra resources via data sources (elastic) or by joining preinfra docker networks (fixed). `./bin/docex preinfra <side>` is a precondition for `projinfra up <side>`.
- **Envinfra and release sit on top of projinfra.** [envinfra](../../docex.md#envinfra) brings `dev`/`test` environments up against the dev-side project resources. [release](../release.md) deploys `stage`/`prod` against the production-side project resources. Both fail if the relevant projinfra hasn't been brought up.
- **Compiled output is split by side, not just by env.** `./bin/docex compile` emits `infra/output/project/development/...` and `infra/output/project/production/...` in addition to the per-env directories. See [cicl.md § Compiler Output](../../cicl.md#compiler-output).
- **`release` consumes projinfra outputs.** On elastic, each env's `main.tf` reads project-tier outputs (zone id, cert ARNs, ALB ARN, ECR repository URLs, task-execution role ARN, the env's ECS cluster ARN) via `data "terraform_remote_state" "project"`. On fixed, each env's compose file joins the project-tier `-web` networks declared `external: true`. See [`release.md`](../release.md).

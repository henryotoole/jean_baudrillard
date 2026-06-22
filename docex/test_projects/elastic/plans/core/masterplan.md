# docex_smoke_elastic — Masterplan

## Purpose

This is one of two **doctrine smoke-test projects** that ship inside the `docex/` tree. It is *not* a real product — it exists so that, before cutting a minor or major `docex` version, the operator can drive a real `elastic`-foundation project end-to-end through `projinfra → envinfra → check → merge → containerize → release stage → stagetest → release prod → teardown` and surface the bugs that only appear against real infrastructure.

The companion project at `docex/test_projects/fixed/` exercises the `fixed`-foundation path. Together they cover the two foundations the doctrine commits to.

The architectural shape, services, and flows are **deliberately identical** to the fixed-foundation companion — same two cores, same one schema-owning backing service, same two project-local container backings, same `Ping` domain, same `/health` endpoint, same composition root layout. The only intended differences are:

1. `foundation: elastic` in `infra.yml` (and the AWS-resource shape that compiles from it).
2. `reverse_proxy: alb` declared explicitly (the doctrine default, also the operator-chosen smoke variant — see mod 044's neutral-on-ALB-vs-EC2-traefik stance).
3. `dev` and `test` still compile to fixed compose stacks (per `shape.md § Shape and Environment`), but `stage` and `prod` compile to AWS HCL — RDS for `appdb`, ECS Fargate for `web`/`worker`/`probe`/`events`, ALB at project tier, ECR for images, EFS-backed persistent storage for ClickHouse (`events`).

That this project's *application code* is identical to the fixed companion's is intentional. Any inter-foundation divergence in source code would mean the parts-only secret-and-env model is leaking — that itself is a doctrine bug. The PRE_CUT_CHECKLIST's audit step diffs the two `core/` trees and fails on real divergence.

## Objectives

1. **Exercise the elastic-foundation release path end-to-end** — master VPC preinfra discovery, project-tier `tofu apply` (with two-phase NS-delegation pause), state backend bootstrap, Route53 zone, ACM cert validation, ALB SNI cert binding, ECR auth, IAM execution-role inline policy, SSM secret push, ECS task definitions, the first-time-release migration ordering swap.
2. **Stay doctrine-faithful** — same as fixed companion. Inception ambiguities surface here and get fixed in doctrine.
3. **Stay cost-bounded** — `teardown.sh` + `verify_clean.sh` are first-class deliverables, not afterthoughts. RDS `deletion_protection` and ECR `force_delete` overrides at retirement time per the smoke-project safety pattern from `docex_process.md`.

## Terms

Identical to fixed companion. `Ping` and `Smoke test` carry the same meanings.

## Architecture

### Foundation

`elastic`. `dev` and `test` run as local docker stacks on the dev machine (always fixed-style per shape.md); `stage` and `prod` run as AWS infrastructure in the shared master VPC (region `us-east-1`).

### Domain

`apex_domain: luxrnd.tech` — the bare apex. Project segment derives from `project.yml`'s `name` field DNS-labeled, yielding `docex-smoke-elastic.luxrnd.tech` as the project subdomain. A Route53 hosted zone for `docex-smoke-elastic.luxrnd.tech` is provisioned by `docex projinfra up production`; the operator NS-delegates from the parent `luxrnd.tech` zone (also in Route53, same account) between projinfra's two-phase apply.

Per-env hosts compile to:
- `<service>.dev.docex-smoke-elastic.luxrnd.tech` (local, served by the dev-side per-project Traefik)
- `<service>.test.docex-smoke-elastic.luxrnd.tech` (local, same)
- `<service>.stage.docex-smoke-elastic.luxrnd.tech` (project ALB, stage cert)
- `<service>.prod.docex-smoke-elastic.luxrnd.tech` (project ALB, prod cert)

Plus the bare-env and bare-project forms per `cicl.md § Domain`. ACM issues two certs (stage + prod) with the doctrine-spec SANs.

### Backing Services

| Service | Role | Engine | Engine on elastic | Purpose |
| ------- | ---- | ------ | ----------------- | ------- |
| `appdb` | `relational_db` | postgres 15 | RDS | Stores `pings` rows. `schema_owned_by: web`. |
| `probe` | `sidecar` (project-local) | nginx | ECS Fargate task | Stateless reachability target. |
| `events` | `analytics_db` (project-local) | clickhouse | ECS Fargate task + EFS | Stateful OLAP backing; EFS mount per AZ; opt-in AWS Backup. |

The two project-local backings are declared in `infra/transfer_tables/{sidecar,clickhouse}.yml`. ClickHouse exercises the doctrine's `persistent_storage` machinery: an `aws_efs_file_system` per service, mount targets in each private subnet, a `volume`+`mountPoints` entry on the ECS task definition with `transit_encryption: ENABLED`. With `backups: true` declared, the compiler also emits `aws_efs_backup_policy.events`.

### Core Services

Same two services as the fixed companion: `web` and `worker`. Same hex modules (`pings` and `processor`), same domain types, same ports/adapters/alogic. The code is intended to be **literally the same source tree** at the `core/<service>/` level — see "Code duplication between fixed and elastic test projects" below.

#### `web`

- **Networks**: `web`, `internal`
- **Role**: `web` (the single network-neutral core-service-container role)
- **Contract**: `web.openapi.yml` (same as fixed)
- On elastic: a Fargate task in `web` + `internal` security groups; ALB target group registered with a listener rule matching its per-env hosts.

#### `worker`

- **Networks**: `internal` only
- **Role**: `web` (same network-neutral role; routing is network-driven, so this internal-only worker gets no ALB exposure)
- **Contract**: none.
- On elastic: a Fargate task in the `internal` security group only — not reachable from the ALB.

### Code duplication between fixed and elastic test projects

Per the kickoff brief: "Two separate projects, one per foundation. Cleaner than a single toggleable project, even if it means some duplication." The two projects each carry their own `core/web/src/`, `core/worker/src/`, etc. — full copies. This is doctrine-faithful ("core services never share code"; each project has one project root) and accepts duplication as the cost.

**Smoke-test side benefit:** drift between the two source trees becomes a signal. The PRE_CUT_CHECKLIST's audit step (`diff -r test_projects/fixed/core test_projects/elastic/core`) should produce no output. Differences would mean the parts-only env model is leaking foundation specifics into application code — itself a doctrine bug.

## Flows

Identical to the fixed companion — Ping creation, Ping processing, Health (`/health`, `/health/probe`, `/health/events`). On elastic they exercise RDS (postgres), Service Connect (peer resolution between core services and the nginx sidecar), and a TCP connection to ClickHouse on its native port through the EFS-backed Fargate task.

## Hard Boundaries

Same as fixed companion, plus:

- This project does **not** use any AWS resource outside what the elastic transfer tables prescribe. If a real elastic project would need (say) SQS or SNS, that's beyond the smoke test's scope.
- This project does **not** carry IAM roles outside what `docex projinfra up production` provisions at the project tier. If a service-specific *task* role is needed, that's a doctrine gap or a docex bug — flag it.
- This project does **not** opt into the `ec2_traefik_*` reverse-proxy variants. ALB is the doctrine default and the operator-chosen smoke variant. Walking EC2-traefik is a future smoke-walk variant covered by a different setup.

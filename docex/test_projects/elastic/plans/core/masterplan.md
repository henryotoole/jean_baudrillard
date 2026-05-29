# docex_smoke_elastic — Masterplan

## Purpose

This is one of two **doctrine smoke-test projects** that ship inside the `docex/` tree. It is *not* a real product — it exists so that, before cutting a minor or major `docex` version, the operator can drive a real `elastic`-foundation project end-to-end through `bootstrap → compile → containerize → release stage → stagetest → release prod → teardown` and surface the bugs that only appear against real infrastructure.

The companion project at `docex/test_projects/fixed/` exercises the `fixed`-foundation path. Together they cover the two foundations the doctrine commits to.

The architectural shape, services, and flows are **deliberately identical** to the fixed-foundation companion — same two cores, same one backing service, same `Ping` domain, same `/health` endpoint, same composition root layout. The only intended differences are:

1. `foundation: elastic` in `infra.yml` (and the AWS-resource shape that compiles from it).
2. `domain: doctrine-elastic.luxrnd.tech` (a separate Route53 zone, NS-delegated from the parent `luxrnd.tech`).
3. `dev` and `test` still compile to fixed compose stacks (per `shape2.md § Shape and Environment`), but `stage` and `prod` compile to AWS HCL — RDS for `db`, ECS Fargate for `web` and `worker`, an ALB per env, ECR for images.

That this project's *application code* should be identical to the fixed companion's is intentional. Any inter-foundation divergence in source code would mean the parts-only secret-and-env model is leaking — that itself is a doctrine bug.

## Objectives

1. **Exercise the elastic-foundation release path end-to-end** — AWS bootstrap, project-tier `tofu apply`, the two-phase NS-delegation handoff, SSM secret push, ECS task definitions, ALB routing, RDS provisioning, ECR image push, the first-time-release migration ordering swap.
2. **Stay doctrine-faithful** — same as fixed companion. Inception ambiguities surface here and get fixed in doctrine.
3. **Stay cost-bounded** — `teardown.sh` + `verify_clean.sh` are first-class deliverables, not afterthoughts. Every resource carries `managed_by = doctrine_test_docex_smoke_elastic`. The operator's wallet depends on tag discipline.

## Terms

Identical to fixed companion. `Ping`, `Smoke test` carry the same meanings.

## Architecture

### Foundation

`elastic`. `dev` and `test` still run as local docker containers on the dev machine; `stage` and `prod` run as AWS infrastructure (single AWS account, region `us-east-1` per doctrine).

### Domain

`doctrine-elastic.luxrnd.tech`. A separate Route53 zone provisioned by `docex bootstrap` (project-tier). The operator NS-delegates from the parent `luxrnd.tech` zone (also in Route53, same account) between bootstrap phase 1 and phase 2.

Per-env subdomains compile to `dev.doctrine-elastic.luxrnd.tech` (local), `test.doctrine-elastic.luxrnd.tech` (local), `stage.doctrine-elastic.luxrnd.tech` (an ALB in AWS), `www.doctrine-elastic.luxrnd.tech` (a separate ALB in AWS). ACM provides the multi-SAN cert covering all required wildcards per doctrine.

### Backing Services

| Service | Role | Engine | Engine on elastic | Purpose |
| ------- | ---- | ------ | ----------------- | ------- |
| `db` | `relational_db` | postgres 15 | RDS | Stores `pings` rows. `schema_owned_by: web`. |

Same shape as the fixed companion — only the engine's elastic-side resource differs (RDS instead of a postgres container).

### Core Services

Same two services as the fixed companion: `web` and `worker`. Same hex modules (`pings` and `processor`), same domain types, same ports/adapters/alogic. The code is intended to be **literally the same source tree** at the `core/<service>/` level — see "Code-sharing" below.

#### `web`

- **Networks**: `web`, `internal`
- **Role**: `web` (the single network-neutral core-service-container role; see fixed masterplan's readability note)
- **Contract**: `web.openapi.yml` (same as fixed)
- On elastic: a Fargate task in `web` + `internal` security groups, behind the env ALB.

#### `worker`

- **Networks**: `internal` only
- **Role**: `web` (same network-neutral role; routing is network-driven, so this internal-only worker gets no ALB exposure)
- **Contract**: none.
- On elastic: a Fargate task in the `internal` security group only — not reachable from the ALB.

### Code duplication between fixed and elastic test projects

Per the kickoff brief: "Two separate projects, one per foundation. Cleaner than a single toggleable project, even if it means some duplication." The two projects each carry their own `core/web/src/`, `core/worker/src/`, etc. — full copies. This is doctrine-faithful ("core services never share code"; each project has one project root) and accepts duplication as the cost.

**Smoke-test side benefit:** drift between the two source trees becomes a signal. The PRE_CUT_CHECKLIST's audit step diffs the two `core/` trees. Differences should be foundation-irrelevant (whitespace, comments) only. If real divergence appears, the parts-only env model is leaking foundation specifics into application code — itself a doctrine bug.

## Flows

Identical to the fixed companion — Ping creation, Ping processing, and Health, all exercising the same code paths against `db` (RDS, in `stage`/`prod`).

## Hard Boundaries

Same as fixed companion, plus:

- This project does **not** use any AWS resource outside what the elastic transfer tables prescribe. If a real elastic project would need (say) SQS or SNS, that's beyond the smoke test's scope.
- This project does **not** carry IAM roles outside what `docex bootstrap` provisions at the project tier. If a service-specific IAM role is needed, that's a doctrine gap or a docex bug — flag it.

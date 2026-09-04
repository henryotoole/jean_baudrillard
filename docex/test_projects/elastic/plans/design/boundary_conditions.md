# Intro and Goals

`docex_smoke_elastic` is one of two **doctrine smoke-test projects** that ship
inside the `docex/` tree. It is *not* a real product. It exists so that, before
cutting a minor or major `docex` version, the operator can drive a real
`elastic`-foundation project end-to-end through
`projinfra → envinfra → check → merge → containerize → release stage → stagetest → release prod → teardown`
and surface the bugs that only appear against real infrastructure. The companion
project at `docex/test_projects/fixed/` exercises the `fixed`-foundation path;
together they cover the two foundations the doctrine commits to.

The system-context picture is [`project_diagram.mmd`](./project_diagram.mmd).

## Requirements

1. **Exercise the elastic-foundation release path end-to-end** — the AWS surface
   that unit tests structurally cannot reach: master-VPC preinfra discovery,
   project-tier `tofu apply` (with the two-phase NS-delegation pause), state
   backend bootstrap, the Route53 zone, ACM cert validation, ALB SNI cert
   binding, ECR auth, the IAM execution-role inline policy, SSM secret push, ECS
   task definitions, and the first-time-release migration ordering swap.
2. **Stay doctrine-faithful.** Every artifact is what current doctrine
   prescribes an elastic-foundation project to look like. When walking the
   inception flow surfaces an ambiguity, the fix lands in the doctrine, not in a
   workaround here.
3. **Exercise the project-local transfer-table feature.**
   `infra/transfer_tables/{sidecar,clickhouse}.yml` declare two project-local
   engines — a stateless nginx sidecar and a stateful ClickHouse `analytics_db` —
   so each cut exercises the deep-merge path, container-backings on the dispatch
   surface, and the EFS `persistent_storage` machinery: an `aws_efs_file_system`
   per service, a mount target in each private subnet, `transit_encryption:
   ENABLED`, and `aws_efs_backup_policy` emitted when `backups: true`.
4. **Stay cost-bounded.** Because a walk stands up real, billable AWS resources,
   `teardown.sh` and `verify_clean.sh` are first-class deliverables, not
   afterthoughts — RDS `deletion_protection` and ECR `force_delete` are overridden
   at retirement time so nothing survives the walk to keep costing money.

# Constraints

- **Hexagonally-architectured Python.** The one codebase, `api`, is built per
  `doctrine/hexagonal_architecture/` and written in Python.
- **Two hosting modes across the four environments.** `dev` and `test` compile
  to fixed compose stacks and run as docker containers on the operator's dev
  machine; `stage` and `prod` compile to AWS HCL and run on ECS Fargate in the
  shared master VPC (`us-east-1`). The application code is identical across both
  modes — any inter-foundation divergence in `core/` would mean the parts-only
  env model is leaking, itself a doctrine bug.
- **One codebase.** The project is deliberately a single codebase exposing three
  core services, not several codebases — see
  [ADR 0001](./adrs/0001_one_codebase_three_core_services.md).

# Context and Scope

The project is a black box against the operator and the external systems an
elastic walk touches (ECR, Route53, the master VPC); the picture is
[`project_diagram.mmd`](./project_diagram.mmd) and the interior is
[`service_diagram.mmd`](./service_diagram.mmd). What this project deliberately
does **not** do bounds its scope:

- It does **not** solve a real problem. The flows are minimal by design.
- It does **not** carry custom transfer tables beyond `sidecar.yml` and
  `clickhouse.yml`. Those two exist specifically to keep the project-local
  transfer-table surface exercised every cut; an ambiguity a walk surfaces in the
  doctrine's project-local mechanism is fixed in doctrine, not in additional
  tables here.
- It does **not** use any AWS resource outside what the elastic transfer tables
  prescribe. A real project needing (say) SQS or SNS is beyond this smoke test's
  scope.
- It does **not** carry IAM roles outside what `docex projinfra up production`
  provisions at the project tier. A service-specific task role being needed is a
  doctrine gap or a docex bug to flag, not something added here.
- It does **not** opt into the `ec2_traefik_*` reverse-proxy variants. ALB is
  the doctrine default and the operator-chosen smoke variant; walking EC2-traefik
  is a separate future smoke-walk variant.
- It does **not** ship custom observability, alerting, or anything in the
  Deferred section of `doctrine/infrastructure/infrastructure.md`. A surfaced
  need for one of those is a Deferred item being un-deferred, not a change here.

# Quality Requirements

The project's one quality bar is **doctrine fidelity**: every artifact should be
exactly what current doctrine prescribes, so that a discrepancy the walk finds is
a doctrine bug rather than a project bug. When the walk surfaces an ambiguity, the
fix lands in the doctrine, never in a workaround inside this project. There are no
discrete quality scenarios, so no `quality_scenarios.md` is kept.

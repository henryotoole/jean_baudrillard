# Advance 008 — Elastic Smoke-Test Walk Evidence

Real AWS: account `256071447730`, us-east-1. Project `docex_smoke_elastic`, version `0.0.25`,
`docex_version: "2.1.0"` (image is advance-008 code; in-source `./bin/docex --version` prints
`2.0.1` — expected, in-source bump is the operator's cut step).

## Pre-walk state
- `preinfra development` → exit 0.
- `preinfra production` → exit 0 (master VPC `vpc-07e85ecd250b5af29` + subnets present).
- Secrets scaffolded dev/test/stage/prod; `TELEMETRY_API_KEY` SET for stage and prod.
- `compile` → exit 0. **No `rule_elastic_defaults_unread_key` rejection** — Mod 138
  `defaults.elastic` guard passes (the elastic task_definition path it scopes to compiled clean).
  Resources rounded to Fargate tiers (informational notes only).
- Dev A-records resolve: `dev.docex-smoke-elastic.luxrnd.tech` and wildcard → `3.214.203.31`.

## Mod 138 — `project_dns_label` HCL threading

Grepped the emitted `infra/output/{stage,prod}/main.tf`. Every **data-plane** site renders the
project segment as `docex-smoke-elastic` (hyphen-lowercased), consistent, with **no**
`docex_smoke_elastic` underscore leak and **no** mixed-case variant:

| Data-plane site | Rendered value (prod; stage identical mod env) |
| --------------- | ---------------------------------------------- |
| Security group `internal` `name` | `docex-smoke-elastic-prod-internal` |
| Security group `web` `name` | `docex-smoke-elastic-prod-web` |
| Service Connect namespace `name` (`aws_service_discovery_private_dns_namespace.env`) | `docex-smoke-elastic-prod` |
| Service Connect namespace `description` | `ECS Service Connect namespace for docex-smoke-elastic prod` |

The four sites agree. Underscored `docex_smoke_elastic` occurs ONLY in B.15-legal contexts:
resource `tags` (`Name`/`project` keys), SG `description` strings, SSM parameter paths
(`/docex_smoke_elastic/prod/...`), and OTel resource attributes (`service.namespace=...`). None
of those is a data-plane name. This is the fix that stopped the four HCL sites disagreeing.

## Walk steps

### projinfra up production
- Phase 1: child zone `Z073574638QTF0K46VH8U` created, exit 0. NS records delegated into parent
  `Z05249222MUE7QVI7SG0I` via single specific-name UPSERT (`docex-smoke-elastic.luxrnd.tech NS`):
  `ns-1164.awsdns-17.org`, `ns-2046.awsdns-63.co.uk`, `ns-385.awsdns-48.com`, `ns-542.awsdns-03.net`.
  Propagated across @1.1.1.1 / @8.8.8.8 / default resolver.
- Phase 2: full apply, **19 resources added, exit 0**. ACM certs validated (stage+prod), ALB up
  (`docex-smoke-elastic-alb`), one ECR repo `docex_smoke_elastic/api`, IAM exec role, both ECS clusters.

### containerize
- Exit 0. Pushed `256071447730.dkr.ecr.us-east-1.amazonaws.com/docex_smoke_elastic/api:0.0.25`
  (sha256 be8f3052…). Exactly **one** ECR repo (`aws ecr describe-repositories` → `docex_smoke_elastic/api`).

### release stage (D.9) — SUCCEEDED
Foreground bash wrapper hit a 10-min timeout mid-apply; the `docker run` container was **not** killed
and completed on its own (RDS creation alone took 6m6s). Verified via captured container logs + AWS.
Terminal output: **"release: stage deployed successfully via OpenTofu."** (a trailing
`Error response from daemon: can not get logs from container which is dead or marked for removal` is a
`docker logs -f` artifact against the `--rm` container, not a release error).

- SSM push: 2 configurable values under `/docex_smoke_elastic/stage/`.
- First-time release detected (no ECS services) → ordering `SSM → tofu apply → migrate`.
- **migrate stage: 'api' migration succeeded (exit 0)** — migrate ECS task STOPPED exit 0.
- tofu apply: **32 resources added**. Five ECS services: `api-web`, `api-worker`, `api-clock`,
  `probe`, `events` (`aws ecs list-services` → exactly 5).
- **Service Connect reconcile — verdict FIRE (2 consumers checked):**
  - `release: reconciling Service Connect consumer 'docex-smoke-elastic-stage-api-clock' — its current deployment predates the registration of its \`uses\` target 'docex-smoke-elastic-stage-api-worker'…`
  - `release: reconciling Service Connect consumer 'docex-smoke-elastic-stage-api-web' — …api-worker…`
  - Both consumers target `api.worker`; `api.worker` uses `[appdb]` only → 2 consumers, no cycle. Matches infra.yml.
  - Operands: post-reconcile consumer PRIMARY deployment createdAt — api-web `17:13:23`, api-clock
    `17:13:22`; Service Connect endpoint `api-worker` CreateDate `17:09:18`. Post-reconcile deployments
    now postdate the endpoint (the fire redeployed them), so resolution is correct.
- No scheduler emitted (`grep aws_scheduler_schedule|scheduler.amazonaws.com` HCL → none); no scheduler
  leak in AWS (`aws scheduler list-schedules` → none for project).
- Exactly one ACTIVE `-migrate` family: `docex-smoke-elastic-stage-api-migrate`.
- `api-web` has target group; `api-worker` loadBalancers `[]`; api-worker `desiredCount=1` (replicas:2 clamps outside prod).
- `/health`: `https://api-web.stage.…` → 200; `https://stage.…/health` → 200 `{"version":"0.0.25"}`.
- One early `events` task failed EFS mount (mount targets not yet ready) then ECS retried → RUNNING (self-healed).

### stagetest (D.10) — PASSED, exit 0
- **Orchestrator liveness/version gate ran BEFORE the tester image build**: `orchestrator pre-step
  passed — 3 core service(s), 3 instance(s) healthy on version 0.0.25`. Each of api-web/api-worker/
  api-clock reported `HEALTHY, RUNNING, image …/api:0.0.25` via ECS list_tasks/describe_tasks.
- Tester probes: **5 passed** (/health, /diagnostics/{probe,events}, POST /pings, defer-then-drain round trip).
- `stagetest: passed (staging_url=https://stage.docex-smoke-elastic.luxrnd.tech)`.

### release prod (D.11) — SUCCEEDED, exit 0
- `RELEASE_PROD_EXIT=0`; terminal line `release: prod deployed successfully via OpenTofu.`
- SSM push 2 values; first-time release detected; **migrate prod exit 0**.
- **Service Connect reconcile — verdict FIRE (2 consumers):** `api-clock` and `api-web`, both with
  the "current deployment predates the registration of its `uses` target …api-worker" message.
- **Prod replica unroll (prod-only path):** `api-worker` desiredCount=**2**, runningCount=2 (vs stage
  clamp to 1); `api-clock` desiredCount=**1**; all 5 services present (api-web, api-worker, api-clock,
  probe, events).
- Three `/health` URLs all 200 `{"version":"0.0.25"}`:
  `api-web.prod.…`, `prod.…` (bare-env → domain_default_service), `docex-smoke-elastic.…` (bare-project).

## Summary
projinfra up production went **green through phase 2**. Every walk step exited 0: containerize,
release stage, stagetest, release prod. Mod 138 HCL threading verified (all four data-plane sites
render `docex-smoke-elastic`, no underscore/case divergence); Mod 138 `defaults.elastic` guard passed
(compile clean, no `rule_elastic_defaults_unread_key`). Service Connect reconcile fired correctly on
both first-time releases. No blocking defects observed.



## Teardown + cleanup (completed by the sergeant — the walk subagent vanished during teardown)

The walk subagent dispatched `teardown.sh` and then disappeared from the session before
recording the result. The sergeant confirmed the outcome independently:

- **`teardown.sh` completed:** both project RDS (`prod-appdb`, `stage-appdb`) observed in
  `deleting` then gone; ECS services/clusters, ALB, ECR repo, and the child zone all destroyed.
- **`verify_clean.sh` → exit 0, "verify_clean: clean"** — every category OK (VPCs, ECS clusters,
  RDS, ALBs, ECR, SSM, Route53 zones, ACM, IAM, tofu state bucket + lock table, DynamoDB, SGs,
  Service Discovery namespaces, RDS subnet groups, CloudWatch log groups, EFS, target groups,
  task-def families, local docker images). Account 256071447730 / us-east-1 clean of project resources.
- **Parent-zone cleanup (sergeant, not caught by verify_clean's project-zone scan):** removed the
  three records the walk added to `luxrnd.tech` (`Z05249222MUE7QVI7SG0I`) — the
  `docex-smoke-elastic.luxrnd.tech NS` delegation (pointed at the now-destroyed child zone) and the
  two out-of-band dev A-records (`dev.` + `*.dev.` → 3.214.203.31). Parent zone now holds zero
  docex-smoke-elastic records, as before the walk.

**Verdict: elastic walk GREEN and fully torn down.** No spend lingering; no blocking defects.

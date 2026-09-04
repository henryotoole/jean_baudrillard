# Cross-Cutting Concepts

**Project-local transfer tables.** The project declares two project-local engines
at `infra/transfer_tables/{sidecar,clickhouse}.yml`: `probe` (a stateless nginx
`sidecar`) and `events` (a stateful ClickHouse `analytics_db`). They exist to keep
the project-local transfer-table surface exercised on every cut — the deep-merge
path, container-backings on the dispatch surface, and the EFS `persistent_storage`
machinery. On elastic, `events` compiles to an ECS Fargate task backed by an EFS
file system: an `aws_efs_file_system` per service, a mount target in each private
subnet, a `volume`+`mountPoints` entry on the task definition with
`transit_encryption: ENABLED`, and — because `backups: true` is declared —
`aws_efs_backup_policy.events`.

**Foundation parity.** The same codebase, modules, core-service topology, and
contracts serve both foundations; only the compiled infrastructure differs. Core
code stays foundation-agnostic (e.g. the backing service is named `appdb` on both
so a database URI is built the same way, whether it resolves to an RDS endpoint on
`stage`/`prod` or a postgres container on `dev`/`test`), which is what lets one
project shape validate `elastic` while its twin validates `fixed`.

**The decisions that shape the project**, each recorded as an ADR:

- **One codebase, three core services**
  ([ADR 0001](./adrs/0001_one_codebase_three_core_services.md)). `web` and
  `worker` are invocations of one artifact (CICL v2 can express "one artifact,
  many invocations"), and the retired `reaper` scheduler folded into `api` as the
  `clock` because a clock may enqueue only onto its own codebase's queue and `api`
  owns the schema. One codebase compiles to exactly one ECR repo, one image tag,
  and one `…-migrate` task-definition family.
- **Postgres tables as queues**
  ([ADR 0002](./adrs/0002_postgres_tables_as_queues.md)). The doctrine ships no
  `queue` backing-service role, so `pings` and `jobs` are tables owned by the
  enqueueing codebase. The worker's AsyncAPI channels address tables, not topics.
- **Tick-file liveness**
  ([ADR 0003](./adrs/0003_tick_file_liveness.md)). Liveness left HTTP; the loop
  cores expose a `/tmp/<svc>.tick` stat'd by `./health.sh` from a separate
  process, and `api.web` keeps `GET /health` only because the ALB has no other
  channel. On elastic the probe has teeth: ECS kills and replaces a task whose
  essential container fails it.
- **No cross-service health fan-out**
  ([ADR 0004](./adrs/0004_no_cross_service_health_fanout.md)). Each core service
  owns its own probe with no aggregation route; backing probes live under
  `/diagnostics`, not `/health`; the defer→drain round trip returns a work count,
  not a liveness verdict, and is the one flow that leans on Service Connect
  resolution between `api.web` and `api.worker`.

These are the principle-shaped boundaries the project holds itself to — stated
rather than left to be inferred, because a copying project inherits whatever it is
not told.

### Code duplication between fixed and elastic test projects

There are **two separate projects, one per foundation**, rather than a single
toggleable project — cleaner even at the cost of duplication. Each carries its own
full copy of `core/api/`. This is doctrine-faithful (`infrastructure.md`: core
services never share code; each project has one project root) and accepts the
duplicate source tree as the price.

The duplication is also a smoke-test asset: **drift between the two source trees
becomes a signal.** The `PRE_CUT_CHECKLIST`'s audit step
(`diff -r test_projects/fixed/core test_projects/elastic/core`) should produce no
output. Any difference would mean the parts-only env-and-secret model is leaking
foundation specifics into application code — itself a doctrine bug.

# Solution Strategy

- **One codebase, three core services.** `api` is built once and invoked three
  ways (`web`, `worker`, `clock`), each a `task_definition` + `ecs_service` on
  `stage`/`prod` — [ADR 0001](./adrs/0001_one_codebase_three_core_services.md).
- **Postgres-mediated queues.** Both units of async work (`pings`, `jobs`) are
  postgres tables (RDS on `stage`/`prod`) claimed with `FOR UPDATE SKIP LOCKED` —
  [ADR 0002](./adrs/0002_postgres_tables_as_queues.md).
- **Container-probe liveness.** Each core service is judged by `./health.sh
  <svc>`, sourced from a served route (`web`) or a loop tick file (`worker`,
  `clock`) and acted on by ECS — [ADR 0003](./adrs/0003_tick_file_liveness.md) —
  and no core service reports on another's health —
  [ADR 0004](./adrs/0004_no_cross_service_health_fanout.md).

# Risk, Unknowns, and Tech Debt

- **Queue rows accumulate.** Retention of the `jobs` table itself is not
  implemented; the project is torn down between walks, so nothing reaps it. A real
  project would prune finished rows with a scheduled job of its own
  ([ADR 0002](./adrs/0002_postgres_tables_as_queues.md)).
- **No real broker.** Both queues are postgres tables, the most visible loose end
  the CICL-v2 advance leaves; the AsyncAPI `events` document addresses tables
  rather than topics and says so in its header.
- **The two-codebase shape is no longer covered.** Folding `reaper` into `api`
  left the smoke walk with one codebase — notably the two-ECR-repo count is no
  longer exercised; what the second used to exercise is recorded in
  `docex/plans/design/specifics/test_projects.md § Shape`
  ([ADR 0001](./adrs/0001_one_codebase_three_core_services.md)).

Open unknowns are tracked in [unknowns.md](./unknowns.md).

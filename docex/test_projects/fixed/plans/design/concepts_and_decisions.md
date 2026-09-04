# Cross-Cutting Concepts

**Project-local transfer tables.** The project declares two project-local engines
at `infra/transfer_tables/{sidecar,clickhouse}.yml`: `probe` (a stateless nginx
`sidecar`) and `events` (a stateful ClickHouse `analytics_db`). They exist to keep
the project-local transfer-table surface exercised on every cut — the deep-merge
path, container-backings on the dispatch surface, and, on the elastic counterpart,
the EFS `persistent_storage` machinery. On `fixed`, `events` mounts a named docker
volume.

**Foundation parity.** The same codebase, modules, core-service topology, and
contracts serve both foundations; only the compiled infrastructure differs. Core
code stays foundation-agnostic (e.g. the backing service is named `appdb` on both
so a database URI is built the same way), which is what lets one project shape
validate `fixed` while its twin validates `elastic`.

**The decisions that shape the project**, each recorded as an ADR:

- **One codebase, three core services**
  ([ADR 0001](./adrs/0001_one_codebase_three_core_services.md)). `web` and
  `worker` are invocations of one artifact (CICL v2 can express "one artifact,
  many invocations"), and the retired `reaper` scheduler folded into `api` as the
  `clock` because a clock may enqueue only onto its own codebase's queue and `api`
  owns the schema.
- **Postgres tables as queues**
  ([ADR 0002](./adrs/0002_postgres_tables_as_queues.md)). The doctrine ships no
  `queue` backing-service role, so `pings` and `jobs` are tables owned by the
  enqueueing codebase. The worker's AsyncAPI channels address tables, not topics.
- **Tick-file liveness**
  ([ADR 0003](./adrs/0003_tick_file_liveness.md)). Liveness left HTTP; the loop
  cores expose a `/tmp/<svc>.tick` stat'd by `./health.sh` from a separate
  process, and `api.web` keeps `GET /health` only because a load balancer has no
  other channel.
- **No cross-service health fan-out**
  ([ADR 0004](./adrs/0004_no_cross_service_health_fanout.md)). Each core service
  owns its own probe with no aggregation route; backing probes live under
  `/diagnostics`, not `/health`; the defer→drain round trip returns a work count,
  not a liveness verdict.

These are the principle-shaped boundaries the project holds itself to — stated
rather than left to be inferred, because a copying project inherits whatever it is
not told.

# Solution Strategy

- **One codebase, three core services.** `api` is built once and invoked three
  ways (`web`, `worker`, `clock`) —
  [ADR 0001](./adrs/0001_one_codebase_three_core_services.md).
- **Postgres-mediated queues.** Both units of async work (`pings`, `jobs`) are
  postgres tables claimed with `FOR UPDATE SKIP LOCKED` —
  [ADR 0002](./adrs/0002_postgres_tables_as_queues.md).
- **Container-probe liveness.** Each core service is judged by `./health.sh
  <svc>`, sourced from a served route (`web`) or a loop tick file (`worker`,
  `clock`) — [ADR 0003](./adrs/0003_tick_file_liveness.md) — and no core service
  reports on another's health —
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
  left the smoke walk with one codebase; what the second used to exercise is
  recorded in `docex/plans/design/specifics/test_projects.md § Shape`
  ([ADR 0001](./adrs/0001_one_codebase_three_core_services.md)).

Open unknowns are tracked in [unknowns.md](./unknowns.md).

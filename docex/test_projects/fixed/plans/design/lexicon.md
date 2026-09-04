# Project Lexicon

Terms specific to this project. Shared doctrine vocabulary (codebase, core
service, backing service, surface, contract, foundation, …) is defined once in
the doctrine [lexicon](../../../../../doctrine/lexicon.md) and not restated here.

| Term | Meaning |
| ---- | ------- |
| Ping | A small unit of work created by the `api.web` core service and consumed (processed) by the `api.worker` core service. Postgres-mediated; no real queue. |
| Job | A named unit of deferred work. `api.clock` enqueues one when a schedule fires; `api.worker` claims and performs it. Carries a name and no payload. |
| Smoke test | The operator-driven manual walk through `PRE_CUT_CHECKLIST.md` against this project before a `docex` cut. |
| Tick file | The `/tmp/<svc>.tick` file a loop-owning core service touches each successful iteration; `./health.sh` stats it to judge liveness. See [ADR 0003](./adrs/0003_tick_file_liveness.md). |
| Drain | A `POST /jobs/drain` request asking `api.worker` to work the `jobs` queue now and reply with the count performed, rather than waiting for the next poll. |

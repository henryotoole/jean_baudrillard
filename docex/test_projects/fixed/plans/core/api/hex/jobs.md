# `jobs` — hex module

## Purpose

The deferred-work queue. It holds **both halves** of the deferral contract that
`role: clock` rests on:

- the **defer** side, driven by `api.clock` — a fired cron job becomes a row;
- the **perform** side, driven by `api.worker` — a claimed row becomes a call.

The module exists because a clock **defers; it does not work**
(`clock.md § The clock defers; it does not work`). A clock may only enqueue onto
its *own* codebase's queue, since only the codebase that owns a schema may write
to it — which is precisely why the retired `reaper` codebase could not simply
become a clock, and why the clock folded into `api`.

## Domain

**`Job`** — a *name* plus its lifecycle timestamps (`id`, `name`,
`enqueued_at`, `started_at`, `finished_at`, `error`).

It deliberately carries **no payload and no handler**. The clock defers a name;
the worker looks that name up in its own table. Keeping the handler out of the
entity is what lets the two sides stay independent.

Two state transitions carry the invariants:

- `start(at)` — illegal on an already-started job, and `at` may not precede
  `enqueued_at`.
- `finish(at, error=None)` — illegal on a job that never started, illegal
  twice, and `at` may not precede `started_at`.

`finish`'s "cannot finish what never started" rule is not ceremony: a job
finishing without ever having started would mean the queue handed out work it
never claimed, which is the exact failure `FOR UPDATE SKIP LOCKED` exists to
prevent. The domain refuses to represent it, so the runner asserts it in-process
on every pass.

## Driving Ports

| Port | Operations | Driven by |
| ---- | ---------- | --------- |
| `ContJobs` | `prune_pings()`, `heartbeat()` — **one method per job**, each returning the enqueued job's id | `api.clock` (cron), `api.web` (HTTP), CLI |
| `ContJobRunner` | `run_once() -> int` — claim a batch, perform each, return the count | `api.worker` |

**One method per job, not `fire(name)`.** That is what lets the HTTP adapter
expose one route per operation — a route an OpenAPI contract can actually
describe — instead of a single opaque `POST /jobs/{name}`.

## Driven Ports

| Port | Pattern | Operations |
| ---- | ------- | ---------- |
| `QueueJobs` | `Queue` (canonical) | `enqueue(name)`, `claim(limit)`, `complete(id, at)`, `fail(id, at, error)` |

## Adapters Included

| Adapter | Kind | Notes |
| ------- | ---- | ----- |
| `ContJobsCron` | driving, `Cron` | The **defer-side dispatch table** plus the fired / deferred / failed translation |
| `ContJobsHttp` | driving, `Http` | One route per job: `POST /jobs/prune_pings`, `POST /jobs/heartbeat`, both `202` with `{job_id}` |
| `ContJobsCli` | driving, `Cli` | Fires one job by name. Constructed by the composition root and invoked by no entrypoint — the root builds every mechanism, including ones the running core service never uses |
| `ContJobRunnerCli` | driving, `Cli` | Translation only: one `run_once()` in, a performed count out. The loop that drives it belongs to `entrypoints/worker.py` |
| `QueueJobsPostgres` | driven | The `jobs` table in `appdb` |

## The two dispatch tables are not duplication

**This is the single most important thing in this document**, because collapsing
them is the obvious "cleanup" and this tree is the doctrine's reference
implementation — a copying project inherits whatever it is not told.

There are two name-keyed tables:

| Table | Lives in | Maps a job name to |
| ----- | -------- | ------------------ |
| defer-side | `ContJobsCron` (adapter) | how the job is **deferred** |
| perform-side | `JobRunnerService` (alogic) | how the job is **performed** |

They agree on the vocabulary — the job names — and on nothing else.

The defer-side table is also what the clock **validates itself against at
startup**. `ContJobsCron.unbound(scheduled)` returns the scheduled names it
cannot dispatch, and `entrypoints/clock.py` treats a non-empty answer as fatal:
the process exits non-zero, naming both the offending job and the implemented
set, **before the cron loop is entered**. A typo in `schedules:` therefore fails
the *deploy* rather than surfacing at 03:00 as a logged failure.

The reverse direction is deliberately **not** checked. A job that is bound but
unscheduled is legitimate: `ContJobs` is a shared driving port, so a job
reachable only over HTTP or CLI is a design choice, not a mistake. The
asymmetry is real and is commented at both sites — making it symmetric is the
tempting "fix" that would break firing a job by hand.

Merging them would couple the clock to the worker's implementation: the clock
would have to know how a job is *performed* in order to know how to *defer* it,
and at that point nothing stops it performing the job itself. That is exactly
what `clock.md § The clock defers; it does not work` forbids, and the whole
reason `api.clock` is a singleton with no replicas and no queue-level retry
while `api.worker` runs two replicas with both.

## Concurrency

`QueueJobsPostgres.claim()` selects `FOR UPDATE SKIP LOCKED` inside a single
transaction, then stamps `started_at` on the claimed ids before committing. The
two halves buy different things:

- **`FOR UPDATE` buys exclusivity** — no job is ever claimed twice.
  `api.worker` declares `replicas: 2`, honoured in `prod`, so this is a genuine
  two-consumer race against one queue.
- **`SKIP LOCKED` buys liveness** — without it the second worker blocks behind
  the first's batch rather than taking different rows. Correct, but serialized,
  which defeats running two.

`tests/test_jobs_concurrency.py` asserts the **first** property and not the
second: drop `SKIP LOCKED` and the test still passes while throughput quietly
halves. That is stated in the adapter's comment and here, because a test cited
as proof of something it never covered is worse than no test.

The test drives 40 jobs through two connections on two threads in the `test`
env. Without it, the two-consumer race would first occur in the **prod
release** — the same prod-only `replicas` clamp under which a core service that
cannot tolerate a sibling first fails.

**There is a third claimer, and it is counted rather than wished away.**
`docex test` brings the whole `test` env up before running `test.sh`, so a live
`api.worker` container drains this queue throughout the run. It is identifiable:
it has no handler for the test's `conc_<hex>` marker name, so it stamps a "no
handler" error on every marker row it wins, and nothing else in the run writes
that column. The test asserts all three claim sets are pairwise disjoint and
that their union is the whole queue — exclusivity across a **separate container
on a separate connection pool**, which is what `FOR UPDATE SKIP LOCKED` actually
defends against in production and closer to it than two threads in one process.

The general rule this establishes, which matters to any project copying this
tree: **a test running in the `test` env has no sole agency.** The doctrine
requires the whole stack to be up, so an integration test may assert on outcomes
in shared state, never on being the only actor. Assertions that need sole agency
belong in `tests/test_jobs_alogic.py`, where the queue is a stub.

## Failure handling

A poisoned job is recorded on its own row and the drain **continues**. One job
that raises must not stall every job behind it, and a job name with no handler
is a data problem in one row rather than a reason to crash the worker.

## Hard Boundaries

- **This module performs no domain work.** `prune_pings` is performed by calling
  `retention`'s driving port; the queue knows how to route a name, never what
  the name means.
- **The clock never claims.** `api.clock` drives `ContJobs` only. Claiming and
  performing belong to `api.worker`.
- **Not a broker.** The transport is a postgres table, because the doctrine
  ships no `queue` backing-service role. The AsyncAPI channel addresses a table
  for that reason.
- **No backfill.** The clock is forward-only; a missed fire is not retroactively
  enqueued (`clock.md § Caveats`). Jobs must be idempotent regardless, because
  nothing guards a job whose runtime exceeds its interval.

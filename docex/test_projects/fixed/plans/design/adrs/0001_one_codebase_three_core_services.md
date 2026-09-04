---
id: 0001
title: one_codebase_three_core_services
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [architecture, codebases, core-services, clock]
---

## Context

The project needs an HTTP edge that accepts pings, a background loop that
processes them, and a scheduler that fires named jobs onto a queue. Three
distinct ways of running, three different failure modes. Two shaping questions
arise: how many *codebases*, and what to do with the scheduler.

`web` and `worker` were once two separate codebases. That split was never a
domain boundary — they always shared a database, a table, and six identical
`DATABASE_*` magic refs. It existed only because pre-v2 CICL had no way to say
"one artifact, two invocations": a codebase was the only unit that could be
invoked, so a second invocation forced a second codebase.

Scheduled pruning also used to be its own codebase, `reaper`, running as a
`role: scheduler` — a core service that was not a long-running process. When
`role: scheduler` was retired in favour of `role: clock`, the natural move was
to turn `reaper` into a clock. It cannot be done: a clock **defers onto its own
codebase's queue**, and only the codebase that owns a schema may write to that
queue. `reaper` owned no schema (it reached into `api`'s `pings` table), no
worker, and no queue.

## Decision

**One codebase, `api`, exposing three core services** (`web`, `worker`,
`clock`) — one build artifact, one image, one registry repo, one `migrate.sh`
run per release, started three different ways by three entrypoints.

CICL v2 can express "one artifact, many invocations", so `web` and `worker`
collapse back into the single codebase they always were. The clock folds in as a
third invocation of that same artifact rather than becoming a codebase of its
own, because `api` owns the schema, the `jobs` queue, and the worker that drains
it — the three things a clock's deferral requires. `reaper`'s pruning rule
survives as the [`retention`](../api/module/retention.md) hex module.

## Consequences

- The two dispatch shapes stay honest: a clock that only defers, and a worker
  that only performs. Merging them would let the clock perform its own jobs,
  which it must not — it is a singleton with no replicas and no queue-level
  retry (see [ADR 0002](./0002_postgres_tables_as_queues.md)).
- The smoke walk no longer covers the **two-codebase** shape. That loss is
  deliberate; what the second codebase used to exercise, and what its absence
  costs the walk, is recorded in
  `docex/plans/design/specifics/test_projects.md § Shape`, which is where a
  reader who finds one codebase should look before concluding the doc is stale.
- A copying project inherits the one-codebase shape as the reference, so the
  reasoning is stated at length rather than left to be inferred from an absence.

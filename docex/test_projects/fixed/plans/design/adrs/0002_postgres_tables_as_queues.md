---
id: 0002
title: postgres_tables_as_queues
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [queues, backing-services, postgres, cicl]
---

## Context

The project has two units of asynchronous work: pings (created at the web edge,
processed by the worker) and deferred jobs (enqueued by the clock, performed by
the worker). Both want a queue. The doctrine ships **no `queue` backing-service
role** — the CICL-v2 advance did not add one. So there is no broker to point at,
and the only durable substrate every core service already shares is the `appdb`
postgres backing service.

## Decision

**Both queues are postgres tables** owned by the enqueueing codebase: `pings`
for ping work and `jobs` for deferred jobs, both in `appdb`, both under
`schema_owned_by: api`. The table *is* the transport. Claiming is
`SELECT … FOR UPDATE SKIP LOCKED` inside one transaction — `FOR UPDATE` buys
exclusivity against the second worker replica, `SKIP LOCKED` buys liveness.

Table ownership is what forces the clock into `api` (see
[ADR 0001](./0001_one_codebase_three_core_services.md)): a clock may enqueue only
onto its own codebase's queue, because only the codebase that owns a schema may
write to it.

## Consequences

- The worker's AsyncAPI `events` surface addresses **tables, not topics**. That
  mismatch is the most visible loose end the CICL-v2 advance leaves, and it is
  recorded in `api.worker.events.asyncapi.yml`'s header rather than hidden.
- There is no broker, no acknowledgement, and no retry policy. A poisoned job is
  recorded on its own row (`error` set) and the drain continues past it.
- Queue rows accumulate; retention of the `jobs` table itself is deliberately
  not implemented. The smoke project is torn down between walks, so nothing
  reaps it. A real project would prune finished rows with a scheduled job of its
  own — the tech-debt note in
  [`concepts_and_decisions.md`](../concepts_and_decisions.md#risk-unknowns-and-tech-debt).

---
id: 0004
title: no_cross_service_health_fanout
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [healthchecks, topology, diagnostics]
---

## Context

An earlier shape of this project served a `/health/api/worker` fan-out: the web
edge reached across the network to report on the worker's health. It is exactly
the shape `healthchecks.md § What this doctrine does not do` forbids — **no core
service reports on another's health** — and `docex` reads every core service's
state from the orchestrator (the ECS API) rather than through an in-network
proxy, so the fan-out duplicated a channel that already exists and could go stale
against it.

This is a **topology** decision, distinct from the liveness *mechanism* in
[ADR 0003](./0003_tick_file_liveness.md): even granting the tick-file probe, one
still has to decide whether one service may aggregate another's verdict.

## Decision

**No cross-service health reporting.** Each core service owns its own probe and
no aggregation route exists. The `/health/api/worker` fan-out is deleted and not
replaced. Two consequences of the rule are made explicit because a copying
project inherits whatever it is not told:

- **Backing probes live under `/diagnostics`, not `/health`.**
  `GET /diagnostics/probe` and `GET /diagnostics/events` confirm `api.web` can
  reach the `probe` sidecar and the EFS-backed `events` ClickHouse task by
  Service Connect name. Left under `/health/*`, a reader would reasonably
  conclude the fan-out survived under a narrower name. They probe *backing*
  services (not core services) and exist so the stage tests catch Service
  Connect / SG / EFS-mount wiring regressions.
- **`POST /jobs/drain` is not a counter-example.** The defer→drain round trip
  (runtime-view flow 4) commands *work* and returns a **count of work
  performed** — no liveness verdict, no staleness judgement — so it cannot be
  mistaken for the deleted fan-out. It is the one flow that depends on
  `api.web → api.worker` resolution over Service Connect, which is an
  application call, not a health hop.

## Consequences

- The stage tester reads each core service's health from the orchestrator (ECS
  carries the container-health verdict and `docex stagetest` reads it from there;
  the fixed companion reads `docker inspect .State.Health.Status` over SSH),
  never through an application route. `api.clock`, which serves nothing and
  registers nothing in Service Connect, has its container probe as its **only**
  liveness channel.
- The rule is stated at length rather than left to be inferred from an absence,
  the same reason the one-codebase boundary
  ([ADR 0001](./0001_one_codebase_three_core_services.md)) is stated at length.

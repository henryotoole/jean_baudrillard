---
id: 0003
title: tick_file_liveness
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [healthchecks, liveness, clock, worker]
---

## Context

Three core services run three different kinds of process: a request-driven web
edge, a poll loop, and a cron loop. Liveness has to be judged for each. HTTP was
once the universal answer — every long-running service served a health route —
but a served `/health` proves only that an HTTP thread answers, which for a loop
is exactly the thread that is *not* the loop. A loop can wedge while its health
server stays cheerfully responsive.

The probe also runs as a **separate process** from the service (docker's
healthcheck on fixed, ECS container health on elastic), so whatever it reads has
to be observable from outside the process.

## Decision

**Liveness is a container tick-file probe, sourced from the loop itself.** Each
loop-owning entrypoint (`worker.py`, `clock.py`) touches `/tmp/<svc>.tick` at the
end of every successful iteration; `./health.sh <svc>`, run by the orchestrator
as a separate process, stats that file and fails when it is **absent or more than
30 s old**. The exit code is the entire contract.

`api.web` keeps `GET /health` — the one place HTTP survives in the health model —
**only** because a reverse proxy reads it and has no other channel to ask
(`healthchecks.md § web services also serve GET /health`). `api.clock` proves the
change is real: its entrypoint imports neither uvicorn nor fastapi and binds no
application socket at all.

The two numbers are a **pair**: the 30 s staleness threshold lives in
`health.sh` (the probe is the only thing that judges it), and the ≤10 s tick
cadence lives in the entrypoints — 1 s in the worker, 5 s in the clock (the loop
is the only thing that can honour it). 30 is three times 10, so a healthy loop
may miss two consecutive ticks before it is called stale: slack for jitter and
one slow iteration, without giving a wedged loop room to hide.

## Consequences

- An **absent** tick file fails deliberately. A loop that never completed an
  iteration was never alive; reporting healthy until the first tick would hide a
  loop that never started.
- The tick is **withheld on a failing pass** — a pass on which every job fire
  raised (clock), or either the ping or job drain half raised (worker). A worker
  that cannot drain is not doing its job even if pings still move.
- `curl` is in the image for the `web` arm and nothing else. The probe is
  POSIX `sh` (the base image ships dash, no bash), computing staleness with
  `stat -c %Y` + `date +%s` to pay no interpreter startup inside a 5 s timeout.
- Detection is not instantaneous on either foundation: the tick goes stale, the
  next scheduled probe fails, the retry count is exhausted. That lag is the price
  of not flapping.

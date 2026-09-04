---
id: 0005
title: durable_job_substrate
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [jobs, runtime, docker]
---

## Context

Some commands run for minutes (`test`, `check`, `merge`). The doctrine
([`docex.md § Asynchronous Usage`](../../../../doctrine/infrastructure/docex.md#asynchronous-usage))
requires such a run to be able to outlive the invoking call — detachable, re-attachable,
and self-healing after a hard kill. Under [DooD](./0003_docker_outside_of_docker.md) the
foreground `docex` runs inside the shim's `--rm` container and dies with it, and an
in-container `docex` can only spawn a **container** over the socket — so a "background host
process" cannot be durable here.

## Decision

Implement durable jobs as a **detached sibling container vessel** with an **on-disk run
record**. `ContainerVessel` is the one vessel kind: a deterministically-named, non-`--rm`
docex container launched by self-inspecting the foreground container (`docker inspect
$HOSTNAME`) and cloning its image / binds / user / workdir, so the vessel's mount set can
never drift from the shim. The record under `.docex/runs/<id>/` (`meta.json`,
`status.json`, an atomically-written `exit`, a `log`) is the handle; the deterministic
vessel **name** is the per-command lock (no flock); and a **reaper** reclaims whatever the
orphaned run's `meta.kind` owned on the next run's preflight.

## Consequences

- **One vessel class, not a polymorphic hierarchy.** What varies by `meta.kind` is the
  body run and the resource the reaper reclaims — never the vessel class. The only remnant
  of an earlier polymorphic design is a `vessel_kind` discriminator (always `"container"`),
  the seam a future second kind would key on.
- **Locking is name-based and per-command**, so a `check` and a `merge` do not block each
  other, but a second `test` loses the `docker run --name` race and refuses.
- **Self-heal, never auto-unwind.** The reaper reclaims leaked worktrees and throwaway
  stacks, but never unwinds `merge`'s real git mutations — those are the operator's.
- The vessel must be launched with an explicit `--entrypoint docex`; prepending `docex` to
  the command double-invokes it (`docex docex __run-job …` → exit 64), a real-image
  integration test guards this. Full mechanism:
  [`../specifics/subcommand_surface.md § Durable jobs`](../specifics/subcommand_surface.md#durable-jobs-the-job-substrate).

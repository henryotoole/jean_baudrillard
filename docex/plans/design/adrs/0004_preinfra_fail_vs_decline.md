---
id: 0004
title: preinfra_fail_vs_decline
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [preinfra, exit-codes, diagnostics]
---

## Context

`preinfra` probes prerequisite infrastructure and is the gate `envinfra up dev` runs. Some
of what it might report is genuinely out of its scope — notably registry *reachability* and
*auth*, which `containerize` surfaces naturally. If every negative outcome collapsed to
"exit 1", an out-of-scope statement (no registry credential on a fixed-only dev box, an
unreachable host, a `401`, a bare `405` from a proxy) would block a dev stack that never
touches a registry — and, worse, a green run would silently include questions the command
declined to answer, which reads as a pass.

## Decision

Give `preinfra` **two distinct negative outcomes**. **Failures** are in-scope questions
answered wrong (missing `docex-ingress` bridge, unresolved `dev` hostname, a master VPC
without subnets, a registry that answers a manifest `DELETE` with `405 UNSUPPORTED`) and
set exit code 1. **Declinations** are out-of-scope questions the command will not answer
(no credential, unreachable, timeout, `401`, any unreadable response); each is printed by
name with its own resolution under a `Declined` heading and does **not** affect the exit
code.

## Consequences

- One exit code cannot express both classes, so a run that declines is not conflated with
  one that fails. A declination is explicitly *not* a pass.
- The registry delete-capability check can only ever *fail* against a registry it could
  actually reach and authenticate to — a reachability problem declines instead of failing,
  so it cannot block a dev stack.
- This mirrors the "a verifier may decline to answer, but not quietly" principle used
  elsewhere (e.g. the linkcheck tool's Declined block). The full behavior is in
  [`../specifics/subcommand_surface.md § preinfra distinguishes failing from declining`](../specifics/subcommand_surface.md#preinfra-distinguishes-failing-from-declining).

# `_env_subdomain`'s expression has a fourth copy

**Found:** advance 006, mod 128 — as the near-miss beside a defect that was real.

## The finding

`orchestrate/aggregate.py::_host_for` re-derives the env subdomain expression by
hand rather than reading the carried field. Mod 128 needed the deployed host for
its fixed-foundation `docker inspect` and pointedly did **not** add a fifth copy:
it read `compiled.subdomain`, then confirmed byte-identity against `_host_for`.

That decision is safe. The duplication it declined to join is not obviously safe,
and it is the last of its family still standing.

## Why this is worth a brief and the cluster name was worth a fix

Mod 128 lifted the ECS cluster name into `naming.ecs_cluster_name` after finding
**five** copies where the design had predicted two. The two the design missed are
what made it urgent:

- `pipeline/projinfra.py` — another reader.
- `emit/hcl.py` — the **emitter**. It writes the clusters the other four read.

An emitter/reader disagreement is categorically worse than a reader/reader one: a
runtime read would address a cluster nothing created, and the failure would
present as a missing resource rather than as a naming bug. That asymmetry is what
earned the lift.

`_host_for` has no emitter in its family — every copy is a reader, and a
reader/reader drift degrades to "one command talks to the wrong host," which is
loud. So it is the same *class* of defect at a lower severity, which is exactly
why it should be recorded rather than either fixed in passing or forgotten.

## What a fix looks like

Read `compiled.subdomain` in `_host_for`, as mod 128 does, and delete the
hand-rolled expression. Then check whether any *other* site re-derives it — mod
128's experience says the count is discovered by grepping, never by predicting.

## The transferable lesson

Both halves of this came from one habit: **when about to copy an expression, count
the existing copies first.** Mod 128's design said two, the implementation found
five, and one of the three unpredicted ones was the emitter. A brief that says "I
declined to add a copy, and here is what I found while checking" is worth more
than the copy would have cost.

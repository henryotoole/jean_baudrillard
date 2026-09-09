# Rule 32's scope — `uses` targets, or every non-`web` core service?

CICL rule 32 constrains the `port` of a **`uses` target**. Both arms
(`rule_32_direct_target_needs_port`, `rule_32_unaddressed_target_declares_port`)
are keyed on being a `uses` target, so a core service nobody uses is outside the
rule's reach: a `worker` named in no one's `uses:` may declare `port: 8081`
forever and nothing objects — even though the port is decoration by exactly the
reasoning rule 32's second sentence gives. Adding one `uses` edge onto that worker
turns the legal port into a compile error, with no change to the worker itself.

This is coherence, not correctness — an unaddressed port costs only a compose
`expose` line and an ECS port mapping. It is untidiness, not a hazard.

Evidence the narrow scoping was not deliberate: `healthchecks.md § What this
doctrine does not do` already states the broader rule in prose — *"A core service
needs a `port` only when something addresses it directly"* — which is wider than
rule 32's `uses`-target scoping.

The question is a doctrine decision, not a `docex` cleanup: rescoping past the
sentence `cicl.md` wrote is a `cicl.md` edit first, and the validator only follows.

## Decision (plan review) — leave it, and align the prose

**No behavior change.** Resolve as won't-fix: rule 32 matches its sentence, the
gap is inert (a decorative port costs one `expose` line / port mapping), and
rescoping would newly *reject* projects that declare an unused port — a breaking
change for zero correctness gain. Instead, close the coherence gap the other way:
**soften `healthchecks.md § What this doctrine does not do`** so its broader prose
("a core service needs a `port` only when something addresses it directly") no
longer overstates what rule 32 enforces. That is the only edit this brief now
implies; the options below are kept as the rationale of record.

## Options (rationale of record)

1. **Leave it.** The rule matches its sentence; the gap is inert. Keeps `docex`
   strictly downstream of the doctrine.
2. **Rescope the negative arm to every non-`web` core service** — "a core service
   declares a `port` only when something addresses it directly," matching the
   healthchecks.md prose. Requires the `cicl.md` edit first.
3. **Split the arms.** Keep the positive arm per-edge (it cannot be asked of a
   service with no consumers) and rescope only the negative arm to all non-`web`
   core services. This is the shape option 2 takes if implemented, and the likely
   answer if this is taken up at all.

## Preserve on any rescope

Rule 32's current text (`cicl.md`, Validation Rules) already codifies three
properties any rescoping of the negative arm must keep:

- **Edge-scoped, not target-scoped** — "keyed on the edge, not the target"; two
  consumers can reach one target differently (one over an `rpc` surface, one
  through a broker), and only the first implies a port. A per-target derivation
  cannot express this.
- **"Directly" = a held magic ref** — addressing is detected by the consumer
  holding a magic ref to one of the target's provided parts, which asks the actual
  question per-edge.
- **The `web`-network exemption** — rule 15 requires a `port` on every
  `web`-network core service, and a consumer reaching a public edge by URL holds
  no ref to it; without the exemption rules 15 and 32 contradict each other on the
  `frontend`/`api` topology.

A rescoping that reaches services with no consumers must leave the per-edge
reasoning intact for the ones that have them.

# Rule 32's scope — `uses` targets, or every core service?

## Summary

CICL rule 32 constrains the `port` of a **`uses` target**. It therefore says nothing
about a core service that nobody uses, which may declare a decorative `port` forever.
The question for a future advance: should rule 32 be scoped to core services
*generally* rather than to `uses` targets?

Raised by mod 125 (advance 006), which implemented rule 32 and deliberately declined to
close this. Extending a rule past the sentence the doctrine wrote for it is a doctrine
edit wearing a validator's clothes, so it does not belong inside a `docex` mod.

## The rule as written

> 32. A `uses` target that its consumer addresses **directly** declares a `port`. A
> target reached only through a queue or broker declares none — there is no address at
> which a consumer reaches it, so a port would be decoration.
> — [`cicl.md § Validation Rules`](../../../../doctrine/infrastructure/cicl.md#validation-rules)

Both arms are keyed on "`uses` target". Mod 125 implements exactly that:

- **positive arm** — a target at least one consumer addresses via a magic ref must
  declare a `port` (`rule_32_direct_target_needs_port`);
- **negative arm** — a target no consumer addresses directly, and which is not on the
  `web` network, must not (`rule_32_unaddressed_target_declares_port`).

## The gap

A `worker` core service that is not named in anyone's `uses:` is outside the rule's
reach. It may declare `port: 8081` and nothing objects, even though the port is
decoration by exactly the reasoning rule 32's second sentence gives. The inconsistency
is visible to an author: adding one `uses` edge onto that worker turns a legal port into
a compile error, with no change to the worker itself.

Note this is not a hazard so much as an untidiness. A port that nothing routes to and
nothing addresses costs a compose `expose` line and an ECS port mapping. The argument
for closing it is coherence, not correctness.

## Options

1. **Leave it.** The rule matches its sentence; the gap is inert. Cheapest, and keeps
   `docex` strictly downstream of the doctrine.
2. **Rescope rule 32's negative arm to every non-`web` core service.** "A core service
   declares a `port` only when something addresses it directly" — which is very nearly
   what [`healthchecks.md § What this doctrine does not do`](../../../../doctrine/infrastructure/healthchecks.md#what-this-doctrine-does-not-do)
   already says in prose: *"A core service needs a `port` only when something addresses
   it directly."* That sentence is broader than rule 32's, which is itself evidence the
   narrow scoping was not deliberate. Requires a `cicl.md` edit first.
3. **Split the arms.** Keep the positive arm on the edge (it is genuinely per-edge — see
   below) and rescope only the negative arm to all non-`web` core services. This is the
   shape option 2 actually takes if implemented, since the positive arm cannot be
   asked of a service with no consumers.

Option 3 is the likely answer if this is taken up at all.

## Do not lose: the carve-out and the edge-scoping

Two properties of mod 125's implementation must survive any rescoping, because both are
load-bearing and neither is obvious from the doctrine sentence alone.

**The `web`-network carve-out.** Rule 15 requires a `port` on every `web`-network core
service. A `frontend.web` that declares `uses: [api.web]` reaches it by public URL from
`config:` — a browser cannot resolve an internal hostname — so it holds no magic ref,
and an uncarved negative arm would demand `api.web` drop the port rule 15 requires. The
two rules would contradict each other on the doctrine's most common two-codebase
topology. Arguably `cicl.md` rule 32 should say "off the `web` network" in its own text;
that is the operator's file.

**"Directly addressed" is edge-scoped, not target-scoped.** Rule 32's own wording is
*"a `uses` target that **its consumer** addresses directly"*. Two consumers can reach
one target differently — `api.web` calling a worker's RPC surface while `api.clock`
enqueues to it through a broker — so any per-target derivation (notably one derived from
the target's `api_styles`) structurally cannot express the relation and must collapse
the two edges into one answer. Mod 125 detects addressing by *the consumer holding a
magic ref to the target's provided parts*, which is per-edge and asks the actual
question. A rescoping that reaches services with no consumers must keep that reasoning
intact for the ones that have them.

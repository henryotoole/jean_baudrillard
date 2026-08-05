# Advance Brief: Retire authored `depends_on`; derive the readiness gate

**Status: proposal, not approved. Not a 1.6.0 cut blocker.** Raised by the
operator during the 1.6.0 pre-cut elastic walk, alongside
[mod 109](./109_service_connect_consumer_reconcile/overview.md). Two concerns
were named: *"the split from `consumes` is confusing"* and *"it should not exist
at all."*

This brief argues the second concern is substantially right, and that the honest
fix is not deletion but **derivation**.

## What `depends_on` actually buys today

It carries two jobs. They are unrelated, and neither justifies a first-class
authored field.

### Job 1 — the readiness gate

Emitted as a compose `condition:` on `fixed`; **discarded on `elastic`**, because
ECS has no cross-service ordering primitive. The doctrine is candid about the
value on offer:

> **`depends_on` is a convenience, never a correctness guarantee.**
> — [`cicl.md § Depends-On Relationships`](../../../doctrine/infrastructure/cicl.md#depends-on-relationships)

So job 1 is *startup ergonomics on one of two foundations*. It is real value —
without it `docex envinfra up dev` crash-loops noisily while postgres finishes
starting — but it is ergonomics, and the doctrine already says so.

### Job 2 — rule-7 bookkeeping

A backing-service magic ref obliges a matching `depends_on` entry, or the compile
fails. **This job is redundant.** The ref *is* the dependency: a core service
holding `${backing_services.appdb.host}` demonstrably depends on `appdb`, and the
compiler can see that without being told twice.

Rule 7's backing arm therefore catches nothing the compiler could not derive. It
catches only *disagreement between two statements of the same fact* — and that
class of error exists solely because the doctrine requires both statements. Remove
the second statement and the error class vanishes rather than going unchecked.

Evidence from the seed: every `depends_on` entry in both smoke projects is backed
by magic refs held by that same core service. `api.web` declares
`depends_on: [appdb, probe, events]` and holds refs to all three. `api.worker` and
`reaper.prune` declare `[appdb]` and hold the six `DATABASE_*` refs. There is not
one entry in the reference implementation that derivation would miss.

## The cost side

For that, the doctrine currently pays:

- A first-class authored CICL field.
- **Rule 24** — "a core service in `depends_on` is an error" — a rule whose
  entire job is to stop authors reaching for the wrong one of two similar fields.
- **Rule 7's backing arm**, the redundant bookkeeping above.
- An asymmetry that must be explained every time: `depends_on` cycles are
  **fatal**, `consumes` cycles are **legal**. This is the load-bearing reason the
  doctrine gives for why the two fields cannot merge — and it is only needed
  because both are authored.
- Foundation-visible behaviour: the author writes something that is honoured on
  fixed and silently dropped on elastic. This is the operator's other stated
  worry, and mod 109 shows the surrounding model has a genuine hole in it.

## Proposal — derive it

**Retire `depends_on` from the authoring surface. Have the compiler infer the
fixed readiness gate from the backing-service magic refs each core service
holds.**

The authoring surface then reduces to two things an author states for their own
reasons:

1. **Magic refs** — written because the process needs the *values*.
2. **`consumes`** — written because the process speaks to a core boundary.

And the readiness gate becomes a compiler output, like every other emitted
invariant.

### What this resolves

| Concern | Resolution |
| ------- | ---------- |
| "The split from `consumes` is confusing" | **Dissolved.** There is no longer a choice to get wrong: you never author the backing edge at all. The "is my target core or backing?" decision disappears from the surface. |
| "Silently discarded on elastic" | **Dissolved as an authoring surprise.** Nothing written is discarded, because nothing is written. The gate is a fixed-only compiler behaviour, which is where foundation asymmetry belongs. |
| Rule 24 | **Inexpressible**, so deleted rather than enforced. |
| Rule 7's backing arm | **Vacuous by construction**, so deleted rather than enforced. |
| The fatal-vs-legal cycle asymmetry | **Stops needing explanation.** Only `consumes` is authored; its cycles are legal, full stop. The derived gate is acyclic by construction, since refs cannot point at backing services that point back. |
| `depends_on` "is a convenience" | Becomes *true by construction* rather than a caveat the reader must hold. |

### What it costs

Stated honestly, because these are the arguments against:

1. **The dependency graph becomes implicit.** A reader can no longer see "this
   waits for the DB" on one line; they must notice the refs. Mitigations: the refs
   sit in the same `env:` block, and `docex describe` already renders graphs and
   would render the derived one. Counter-argument: an implicit gate that is always
   right beats an explicit one that can disagree with the refs — which is exactly
   what rule 7 exists to police.
2. **The no-ref-but-real-dependency case.** A process needing a backing service
   ready while holding no magic ref to it — e.g. reading its address from `config`
   instead. Not present anywhere in the seed. Options: accept that such a project
   should hold a ref (magic refs *are* the doctrine's mechanism for backing
   addresses, so bypassing them is already off-pattern), or keep a narrow, honestly
   named escape hatch. **Deciding this is the main open question.**
3. **It is a breaking authoring change** — `cicl_version: "3"`, or at minimum a
   minor with an upgrade guide that mechanically strips `depends_on` blocks. The
   upgrade is unusually safe, though: strip the field and recompile, with a
   compile-time check that the derived gate matches what was previously authored.
   That check makes the migration *provable* per project rather than trusted.

### A cheaper interim, if the full change is too much

Keep the field, and have the compiler **derive** the gate anyway, treating an
authored `depends_on` as an assertion to verify rather than an instruction to
follow — failing the compile when the two disagree. That converts rule 7 from
"restate the fact" into "the fact and your claim about it must match", which is
strictly more useful, costs no format break, and would surface any project where
derivation is insufficient *before* committing to removal. Recommended if the
operator wants evidence before a `cicl_version` bump.

## Sequencing

- **Not in 1.6.0.** 1.6.0 already carries a breaking format change
  (`cicl_version: "2"`) and a release cycle with no prod rollback path. Adding a
  second authoring break to the same cut is gratuitous.
- **Mod 109 is independent of this** and must land first — it is the cut blocker.
  Its doctrine edits are deliberately worded not to entrench `depends_on`.
- Natural shape: the interim verify-derivation step in a 1.6.x patch or 1.7.0,
  the field's removal in whichever cut next carries a `cicl_version` bump.

## Reading

- [`cicl.md § Depends-On Relationships`](../../../doctrine/infrastructure/cicl.md#depends-on-relationships)
  — the current rule, the "convenience" framing, and the elastic-discard argument.
- [`cicl.md § Consumes Relationships`](../../../doctrine/infrastructure/cicl.md#consumes-relationships)
  — the comparison table and the cycle asymmetry that this proposal removes the
  need to explain.
- [`cicl.md § Validation Rules`](../../../doctrine/infrastructure/cicl.md#validation-rules)
  — rules 7 and 24, both of which shrink or disappear.
- [Mod 109](./109_service_connect_consumer_reconcile/overview.md) — the
  resolvability hole in the surrounding model, and why application-level
  resilience does not cover it.

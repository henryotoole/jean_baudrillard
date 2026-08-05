# Merge `depends_on` and `consumes` into `uses`

A design record for collapsing the two service-relation fields in `infra.yml`
into a single relation named `uses`, and for retiring project-level startup
ordering as a doctrine feature.

> **Status.** **Design settled; no open questions.** Breaking — every
> `infra.yml` must be rewritten, so this is a `cicl_version` **2 → 3** cut and
> should ride with the other breaking work in this advance rather than justify a
> cut on its own. Touches resident doctrine, CICL, contracts, migrations,
> transfer tables, `docex`, one skill, and the upgrade guides.

## The change

Three moves, taken together:

1. **One relation, named `uses`.** `depends_on` and `consumes` merge. A `uses`
   entry may name a **backing service** (bare: `database`) or a **core
   service** (dotted and fully qualified: `api.worker`).
2. **Startup ordering stops being a doctrine feature.** The compiler no longer
   emits compose `depends_on` / `condition:` on core service blocks. Not
   deprecated-but-still-emitted — actually removed. See
   [Why the ordering goes](#why-the-ordering-goes).
3. **The exec block keeps its gate.** It remains the single site where ordering
   is emitted, derived from the codebase's backing-service `uses` edges.

Everything else about `uses` is what `consumes` does today.

## Motivation

Two fields, two cycle rules, two halves of one validation rule, and a
comparison table — for what an author experiences as a single question: *what
does this core service talk to?* The split forces prose that exists only to
explain itself, most visibly the paragraph at
[`cicl.md`](../../../../doctrine/infrastructure/cicl.md#the-cicl-format) (line
107) whose whole job is explaining why the worker's dependency on `cache` lives
in one field while its dependency on `api.web` lives in another.

The 12-factor grounding: infrastructure should not *require* any component to be
online for another to boot. The doctrine already mandates exactly this at
[`cicl.md § Depends-On Relationships`](../../../../doctrine/infrastructure/cicl.md#depends-on-relationships):

> **Startup ordering is not a substitute for connection resilience.** Every
> service must tolerate its dependencies being absent at any moment.

So full tolerance is already required, and the readiness gate is belt-and-braces
on top of a guarantee that exists independently. Removing it makes nothing less
resilient — the requirement was never the gate.

### Why the merge is sound

[`cicl.md § The graph may contain cycles`](../../../../doctrine/infrastructure/cicl.md#the-graph-may-contain-cycles)
currently argues the two fields *cannot* merge:

> There is one DAG (`depends_on`) and one cyclic digraph (`consumes`); no single
> field could carry a cycle rule that is simultaneously fatal and fine.

That is overstated. A merged field's cycle rule keys on **target kind** — legal
when the target is a core service, fatal when it is a backing service —
and target kind is something the compiler knows for every edge. Better still,
under this design a backing service **cannot declare outbound edges at all**
(see [Intra-backing ordering](#intra-backing-ordering-moves-to-engine-defaults)),
which makes it a graph **sink**. A sink cannot sit in a cycle, so acyclicity
across backing-targeted edges falls out *structurally* rather than needing
enforcement.

## Why the ordering goes

The ordering could have been kept as an undocumented compiler convenience,
dropped later at leisure. It should not be, and the reason is the sharpest point
in this record.

**A silently-emitted gate is worse than either a documented one or none at
all.** If `docex` keeps emitting it while the doctrine says nothing, then `dev`
and `test` genuinely do order startup. A developer writes a service that
connects at boot with no retry; it works in `dev`, works in `test`, works in
`stage`-on-fixed — and breaks the first time the project goes elastic, where
[the gate cannot be honoured](../../../../doctrine/infrastructure/cicl.md#depends-on-relationships).
The protection is real but invisible, so nobody knows to distrust it.

It also inverts the principle that motivated the change. 12-factor's dev/prod
parity wants environments as similar as possible; a silent gate makes `dev` and
`test` systematically **more forgiving** than elastic `prod`, concealing exactly
the bug class the resilience mandate exists to catch. `dev` should *expose*
non-resilient boot code, not shelter it.

Accepted cost: a burst of connection-refused lines on `envinfra up` while
backing services initialize. This is acceptable and arguably good signal — you
can watch backoff working — and per
[`logging.md`](../../../../doctrine/practices/logging.md) stdout is already the
home for that class of diagnostic. If `envinfra up` asserts container health
afterward, a service that crashes rather than retries fails the bring-up, which
is the correct outcome.

### Why the exec block keeps its gate

`migrate.sh`, `test.sh`, and `build.sh` are **one-off batch jobs whose entire
contract is an exit code**. 12-factor's disposability principle says a
long-running process must tolerate a dependency vanishing; nothing in it makes a
one-shot script succeed against a database not yet accepting connections. For a
batch job, "be tolerant" *means* "wait until ready" — which is a readiness gate.
It cannot be deleted, only relocated: into `docex` as a bespoke waiter (more
code than the emission it replaces), or into every project's `migrate.sh` as a
hand-rolled loop (pushing a deterministic concern onto projects, and the
doctrine deliberately fixes only the shim's *interface*, so it cannot assume a
`dbmate wait`-style capability exists).

Per
[`migrations.md`](../../../../doctrine/infrastructure/specifics/migrations.md#dev-and-test-mechanism),
the exec block today carries "the union of its `depends_on` rewritten to
`condition: service_healthy`". Under the merge that becomes **the union of the
codebase's `uses` edges whose target is a backing service**, rewritten the same
way. Identical derivation, different source word.

**This is not a carve-out; it is the last remaining emission site.** Ordering
stops being a property of the project's services and becomes a property of one
compiler-owned block. No project declares it and no project can rely on it.

Two supporting facts worth keeping:

- **An ungated batch-job class already ships.**
  [`scheduler.md`](../../../../doctrine/infrastructure/specifics/scheduler.md)
  notes that Ofelia-spawned job containers inherit neither Compose's
  `depends_on` gates nor its other conveniences, because Ofelia spawns them
  outside Compose. A doctrine cron job is *already* required to tolerate a cold
  database. The exec block is not a lone exception — it is the one member of
  that class that runs against a possibly-cold stack.
- **The fixed production path is already covered.** The stage/prod playbook runs
  the exec one-off with `--tags migrate` *before* `compose up -d`, so the exec
  gate proves the schema-owning database healthy before any core service starts.
  Dropping core→backing ordering costs essentially nothing there.
  Non-schema-owning backings (cache, object store) are not covered — and must be
  tolerated anyway, which is the point.

## Naming

`uses` was chosen over `consumes` (the incumbent) and `speaks_to` (the
doctrine's own gloss of the relation, at § Consumes Relationships: *"I speak to
this boundary"*). Recorded so it is not relitigated:

- **Honest for the numerically dominant case.** A typical core service names
  three backing services and one core target. `uses: [database, cache, bucket,
  api.worker]` reads correctly; `consumes: [database]` does not — you query
  postgres, you do not consume it.
- **It removes a carve-out rather than adding one.** Naming the field `consumes`
  would require explaining why consuming postgres does *not* make postgres a
  provider owing a contract. Under `uses`, provider/consumer survives as
  **derived** vocabulary — "a core service that is used by another is a
  provider" — instead of a name the field must justify.
- **No collision with `role: worker`.** The doctrine has real queue consumers.
  Not spending "consumer" on a second, unrelated axis is worth something.

Rejected outright, with reasons: `requires` and `depends_on` carry readiness
semantics natively and would resurrect ordering in the reader's head in the same
breath as its deletion (`depends_on` doubly so, being the compose keyword, and
because it *does* still emit on the exec block); `calls` lies about the
canonical case, since `api.web` enqueues rather than calling `api.worker`;
`reaches` collides with "reachability", now a term of art for the transient
property in [the Service Connect
record](./service_connect_reconcile_trigger.md); `binds` is already spent on
entrypoints binding driving adapters to a runtime host.

The one thing given up is grep distinctiveness. Mitigated in practice by
searching `uses:` with the colon, or `^\s*uses:`.

## Fruits

- **Rule 24 dies** (`depends_on` names only backing services).
- **Rule 7 collapses** from a bifurcation — "an edge of the kind the target
  calls for" — plus a documented not-applying case, to a single clause: a magic
  ref must be matched by a `uses` entry. The not-applying case for a *backing
  service* embedding a core service's part (a CORS origin, say) survives,
  and gets simpler to state: backing services declare no edges at all.
- **Rule 6 narrows** to backing-targeted edges, and is arguably deletable, since
  a backing service is structurally a sink.
- **The `depends_on` vs. `consumes` comparison table** goes.
- **The explanatory paragraph at `cicl.md:107`** goes.
- **§ Depends-On Relationships** collapses into **§ Uses Relationships**, its
  readiness prose reduced to one line about the exec block.
- **The resilience clause gets stronger.** It currently reads as a warning
  attached to a feature — here is a gate, do not trust it. With the gate out of
  project scope it becomes an unqualified requirement.
- `docex dag` keeps its solid/dashed edge-kind distinction, now derived from
  **target kind** rather than from which field the edge came from.

## Intra-backing ordering moves to engine defaults

`depends_on` is currently valid *on* backing services
([`cicl.md`](../../../../doctrine/infrastructure/cicl.md#service-fields), scope
column: "core service, backing"), though nothing in the doctrine
exercises it — the two candidates in `transfer_tables.md` (~lines 611, 681) are
both core→backing.

`uses` is declarable **only by core services**. Where an engine genuinely
needs another container beneath it, that belongs in the engine's
`defaults.fixed` block in its transfer table, not in `infra.yml`: which
containers an engine requires is an *engine* concern, not a project one. Net
effect is a tightening — backing services become pure sinks in the relation
graph, which is what makes the cycle rule vestigial.

## Blast radius

**Resident / CICL**

- `cicl.md` — sample `infra.yml` (three `depends_on` blocks, two `consumes`);
  the paragraph at 107; § Core Services field-scoping table; § Service Fields
  table (both field rows); § Magic Refs (the implied-edge sentence);
  § Depends-On Relationships → collapse; § Consumes Relationships → § Uses
  Relationships; the comparison table; validation rules 6, 7, 24, 25.

**Infrastructure specifics**

- `contracts.md` — the provider-set definition; § Fan-out's source; the
  paragraph at 69 (its parenthetical about the `depends_on` union becomes moot);
  § Declared by fields; the Service Connect paragraph at 85.
- `release.md` — § Service Connect Consumer Reconcile (field name); **line 114
  needs care**: "Fixed foundations need none of this. Compose has real
  `depends_on` ordering, and docker network DNS resolves a sibling container
  whenever it exists." The first clause becomes false, but the conclusion holds
  on the second — dynamic sibling DNS is the real reason. Drop the first clause,
  keep the second.
- `migrations.md` — lines 48 and 71 (exec gate derivation).
- `transfer_tables.md` — line 812's compose-`depends_on` emission rule, now
  scoped to the exec block alone; the `# depends_on comes from infra.yml`
  comments in the `web`/`container` walking example.
- `scheduler.md` — the example block and the field-behaviour sentence.
- `telemetry_infra.md` — line 240 mentions the core service not declaring a
  `depends_on` on its sidecar; still true, reword to the new vocabulary.
- `shape.md` — the example `infra.yml`.
- `docex.md` — the `dag` command description.

**Outside the doctrine**

- `skills/contracts/SKILL.md` — references the fields.
- `upgrades/upgrade_1.6.0.md` — references the fields.
- A new upgrade guide for the `cicl_version` 3 cut, carrying the mechanical
  rewrite (`depends_on:` → `uses:`, merge with any existing `consumes:` list on
  the same core service, delete `depends_on` from backing services).
- `docex` — the compiler's relation parsing and validation, the compose emission
  path (delete core-block ordering, retain the exec-block gate), and `dag`'s
  edge-kind derivation.

Thread-skill pointers must be re-checked mechanically after the section renames,
per [`doctrine.md`](../../../../doctrine/doctrine.md) — a section rename is
exactly what dangles a router link.

## Also noticed

Unrelated to this change, found while surveying: the `infra.yml` examples in
`transfer_tables.md` around lines 600–685 are still in the pre-`processes:` flat
form (`role`, `port`, `depends_on` directly on the core service), which
`cicl_version: "2"` rejects. Worth folding into the same coherence pass.

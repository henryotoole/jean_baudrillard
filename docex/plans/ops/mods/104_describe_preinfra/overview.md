# Mod 104 — `describe` and preinfra

Mod 104 of the *service process types* advance. This is the mod where the
advance's two relations become **visible to a human** reading the
infrastructure. Nothing about enforcement changes: `depends_on` is still a
readiness DAG whose cycles are fatal, `consumes` is still a cyclic interface
digraph read only by CI. What changes is that `describe` now shows both.

Rule of record:
[`service_processes_refactor.md § Rejected Alternatives`](../../advances/004_next/service_processes_refactor.md#rejected-alternatives)
item 6 and the paragraph closing that list —

> The single graph the merged form was reaching for is still available as a
> **view**: `describe/dag.py` should render the union with edge kinds visually
> distinguished (solid readiness, dashed interface). One DAG for understanding;
> two relations for enforcement.

— plus the Mod 104 section of
[`service_processes_implementation_plan.md`](../../advances/004_next/service_processes_implementation_plan.md).

## Scope

Four items, in descending size:

1. **`consumes` is carried onto `CompiledService`** as compiled process
   identities. Mod 098 deliberately left it on the authoring model only; this is
   the mod that first needs it compiled.
2. **`describe/dag.py` renders both edge kinds**, visually distinguished, over
   node ids that carry the process dimension in the doctrine's reference form.
3. **`describe/llm.py` gains `"kind": "consumes"`**, and the duplicated
   edge-derivation loop is deleted rather than doubled.
4. **`_check_dev_dns` per web process type** — *verified already true*, pinned
   with a test.

Explicitly out of scope: any doctrine file (Mod 106), rollback (105), version
artifacts (107). `docex.md § describe` will read stale after this mod, by plan —
see [Design questions](#design-questions) for the one line of it that goes from
*stale* to *arguably wrong*.

## 1. `consumes` on `CompiledService`

A new field, defaulted empty, populated only for core process types:

```py
# Rule 25's interface edges, as compiled identities — the same keys into
# `CompiledEnv.services` that `depends_on` holds. Empty for backing services,
# which have no `consumes:` (rule 14). CI/view-only: nothing is emitted from it.
consumes: list[str] = field(default_factory=list)
```

Three properties, each deliberate:

- **Compiled form, not dotted.** `depends_on` on `CompiledService` holds keys
  into `CompiledEnv.services`; `consumes` now holds the same kind of thing
  (`api-worker`, via `ProcessRef.compiled`). That makes the compiled model
  uniformly self-referential: any edge, of either relation, is resolvable by one
  dict lookup. The dotted *reference* form is a presentation concern and is
  applied by the renderers (see [item 2](#2-the-dag-renders-both-relations)),
  which is exactly the split
  [`cicl.md § Dots for reference, hyphens for emission`](../../../doctrine/infrastructure/cicl.md#dots-for-reference-hyphens-for-emission)
  draws.
- **Parsed through `ProcessType.consumes_refs()`.** Mod 101 promoted that parse
  onto the model precisely so there would not be a second one; this mod is its
  third reader (after rule 7 and `check.py`) and adds no parsing of its own.
  Malformed entries are therefore dropped here too, consistent with every other
  reader — rule 25 reports each once and it does not resurface as a phantom
  node.
- **Sorted.** Compiled output is order-stable everywhere else; `consumes_refs()`
  returns a `set`.

**It stays inert.** `consumes` is a declared field on both models, so it never
lands in `model_extra` and cannot reach field translation or any emitted
artifact. `tests/unit/test_process_expansion_emit.py`'s absence guard —
written because *"is not read" and "cannot be read" look identical until someone
adds a read site* — continues to hold, and is now doing real work: this mod is
that read site, and the guard is what proves the read did not leak into
emission.

## 2. The DAG renders both relations

### Node identity

Node ids become the **dotted** reference form for core process types
(`api.web`), staying bare for backing services (`appdb`, which has no process
dimension). This is not a new invention — it is
[`cicl.md § Dots for reference, hyphens for emission`](../../../doctrine/infrastructure/cicl.md#dots-for-reference-hyphens-for-emission)
naming `describe` node ids in its dotted list, which today's renderer does not
honor (it prints the compiled key, `api-web`). Aligning here is code following
the rule of record, and it is the same argument Mod 102 made for two OTel
attributes over one fused `service.name`: `api-web` does not decompose, because
`_SERVICE_NAME_RE` admits `-` in both segments. A view whose entire purpose is
human understanding should not hand the reader an ambiguous token.

Each node line keeps its emitted `global_name` alongside, so the two forms sit
side by side — the reference form to compare against `infra.yml`, the
hyphenated one to `docker ps` for:

```
Environment Infrastructure (prod)
  - network:internal          sample_prod_internal  (docker network)
  - core:api.web              sample-prod-api-web  [role=web, ...]
  - backing:appdb             sample-prod-appdb  [role=relational_db, ...]
```

(The `backing:` rows are also mis-columned today, because the padding is
applied to the name rather than to `kind:name`. Fixed in passing.)

### Edges

Two labeled groups under distinct arrow glyphs, each omitted when empty:

```
depends_on edges (readiness) — solid:
  api.web -> appdb

consumes edges (interface) — dashed:
  api.web ..> api.worker
  api.worker ..> api.web
```

`->` for readiness and `..>` for interface is the mermaid/graphviz convention
rendered in ASCII (`-->` / `-.->`), so the glyph reads as dashed without a
legend. The distinction is carried **twice** — glyph *and* heading — because the
output is as often grepped as read, and `grep consumes` should find the
interface edges.

### Cycles

`web ↔ worker` is legal in `consumes` and is the most common topology there is.
It renders as two lines because the renderer stays a **flat pass over
`CompiledEnv.services`** — no graph walk, no visited set, therefore nothing to
recurse. That is not an accident of the current code being retained; it is the
correct shape for this view, and a test pins it so that a future "let me lay
this out as a tree" refactor fails loudly rather than blowing the stack. The
enforcement asymmetry is untouched: rule 6's cycle detection still runs over the
backing graph alone.

### Replicas

`CompiledEnv.services` holds one entry per process type, so `replicas: 4` yields
**one** `api.worker` node. This mod adds no unrolling and no replica annotation —
per Mod 100, *a replica is an emission detail, not a topology node*. Pinned by a
test, because "the view shows topology, not emission" is the invariant that a
well-meaning future reader is most likely to "fix".

## 3. The duplicated edge loop does not survive

`llm.py` builds edges in a second, independent pass over the same relation.
Doubling that to four passes — two relations × two renderers — to serve the
design record's "one graph, two views" would be the wrong reading of it: there
is one derivation and two *renderings*.

So the derivation is extracted into two module-level functions, and `llm.py`
calls them:

| Function | Returns |
| -------- | ------- |
| `node_id(svc)` | the display id — dotted for a core process type, bare for a backing service |
| `collect_edges(compiled)` | `list[tuple[str, str, str]]` of `(from_id, to_id, kind)`, readiness group first, each group sorted |

**They live in `dag.py`**, not in a new `describe/graph.py`. `llm.py` already
imports the four tier constants from `dag.py`, so the import edge exists and its
direction is unchanged; a third module for ~25 lines of derivation would cost
more than it explains. They are named without a leading underscore, unlike those
constants, so the cross-module use is deliberate API rather than reaching into a
private name.

`collect_edges` resolves display ids through `compiled.services.get(key)` and
falls back to the raw key when a target is absent. `run_describe` calls
`compile_env` **without** `validate_document`, so a document with an
unresolvable `consumes` target reaches the renderer; `describe` is purely
illustrative and must degrade to printing an odd token rather than raise.

`llm.py` additionally gains a per-node `"consumes"` list beside the existing
`"depends_on"`, and `"core_service"` / `"process"` beside `"short"`. Both are
small extensions past the plan's letter, taken for the same reason the plan
gives for the edge kind: a consumer should not have to join the edge list to
learn a node's relations, nor split a hyphenated string to recover its two axes.

## 4. Dev DNS — verified, not changed

`_check_dev_dns` (`pipeline/preinfra.py:165`) delegates host derivation to
`web_hostnames_for_env`, which **Mod 096 already moved to process types**:

```py
entries: list[tuple[str, list[str]]] = [
    (ProcessRef(svc_name, proc_name).compiled, list(proc.networks))
    for svc_name, proc_name, _svc, proc in doc.all_processes()
]
```

Confirmed by reading, not assumed: every process type of every codebase is
enumerated, `_web_hosts` filters to the `web` network, and a non-web process
type contributes no host. `test_web_hostnames.py` already covers the derivation
with two web process types across two codebases plus a non-web sibling.

What is missing is coverage at the **preinfra** layer: its tests run against the
sample fixture, which has exactly one process type, so nothing pins that the
*check* enumerates per process type rather than per codebase. A regression that
collapsed the enumeration back to one host per codebase would pass the whole
preinfra module today. This mod adds that test — a second web process type in a
`tmp_path` copy of the fixture, asserting the resolver is asked about **both**
hosts. No production code changes for item 4.

## Findings

Recorded because they were verified rather than inherited:

1. **Node identity already carried the process dimension.** The plan's framing
   ("node identity gains the process dimension") reads as though today's DAG
   prints codebase-level nodes; it does not — Mod 096 made the `services` key
   two-segment, so the current output is already `api-web -> appdb`. The real
   remaining gap is the *form* of that id, addressed above. Rendered output
   confirmed against the sample fixture before designing.
2. **`_check_dev_dns` needed no change at all** (item 4).
3. **The `consumes` emission-absence guard survives intact** and is what makes
   the new compiled field safe to add.

## Design questions

**One.** The `dag` format name outlives its acronym.

`docex.md § describe` says the `dag` format describes the shape "with a directed
acyclic graph". Once `consumes` edges are drawn, the rendered union is a
directed graph that **may legally contain cycles** — `web ↔ worker` being the
common case. The word *acyclic* becomes wrong rather than merely stale, which is
a different thing from the staleness Mod 106 is already slated to absorb.

Two ways to close it:

- **(a) Keep the flag `--format dag`; amend the prose.** Mod 106 changes the
  sentence to a *directed* graph and notes that the readiness relation alone is
  the acyclic one. Costs one doctrine sentence; the CLI surface, every operator's
  muscle memory, and `masterplan.md`'s command table are untouched. **My
  recommendation.**
- **(b) Rename the format** (`graph`, `shape`), with `dag` as a deprecated alias.
  Honest, but it is a user-facing CLI surface change in a mod that has none, and
  it would ripple into the argparse choices, `docex.md`, `masterplan.md`'s
  command table, and both test projects' documentation.

I am not taking (b) on my own authority — renaming a command surface is a
decision above a single mod's scope, and it is the kind of thing better decided
once for the whole advance.

**Resolved: (a).** A format name is a label identifying which renderer to
invoke, not a claim; the `docex.md` sentence is what asserts the property, and
the sentence is the thing that is wrong. (b) would be a user-facing CLI break in
a mod with otherwise zero surface change, and it costs the same later if the
operator wants it. The specific amendment Mod 106 owes —
*"directed acyclic graph"* → *"directed graph"*, with its reason — is recorded in
[`implementation.md § Notes for Mod 106`](./implementation.md#notes-for-mod-106).

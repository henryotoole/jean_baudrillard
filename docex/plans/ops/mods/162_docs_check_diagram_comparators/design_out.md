# Mod 162 — `docs check` Diagram Comparators: Design-Out Finding

**Status:** DROPPED (this cycle) — raised to `sarge` as a keep/drop decision.
**Deliverable:** this written finding, satisfying Goal 2 SC4's "or dropped with a
written design-out finding explaining the infeasibility."

Two comparators were scoped for `docex docs check`:

1. **Diagrams vs. `infra.yml`** — the authored service diagram's service/codebase
   nodes + their `uses` edges should be a subgraph of `infra.yml`.
2. **Diagrams vs. each other** — `project` / `service` / `module` diagrams must be
   mutually consistent.

Both are **infeasible as `docs.md` currently specifies the diagrams**. The reason is
identical for both and is stated once, then applied to each.

---

## The single root cause: no machine-readable node identity in the authored diagrams

A comparator is a graph diff. A graph diff requires that a node in graph A be
identifiable with a node in graph B. On the `infra.yml` side this is solved and
already in code: `infra.yml` parses to `CICLDocument`, services carry
`uses_core` / `uses_backing`, and `ServiceRef` gives the canonical dotted identity
`<codebase>.<service>`. `docex describe dag` already renders exactly this graph —
`describe/dag.py:node_id()` emits dotted ids for core services and bare names for
backing services, and `collect_edges()` emits the `uses` edge set. **The infra
side of both comparators is done and free.**

The **authored** standard diagrams are the problem. `docs.md` § Standard Diagrams
mandates only:

- three mermaid diagrams (project / service / module);
- arrows in the direction of "calling / usage", labelled with the action;
- the infra-bearing diagram "should match `infra.yml`" (prose only);
- if a box has a doc/contract, it **must** be linked via a mermaid `click`.

It mandates **none** of the three things a comparator needs:

- **No node-id convention.** Nothing requires a mermaid node's id (or label) to be
  the dotted `<codebase>.<service>` / bare backing name. Node ids are free; labels
  are free human prose. There is no deterministic map from a diagram node to an
  `infra.yml` service.
- **No node-classification convention.** research.md's own caveat is that
  `infra.yml` contains *no* external actors and *no* hex internals, so those parts
  of the C4 diagrams are "legitimately distinct" and must be **excluded** from the
  subgraph check. But excluding them requires *knowing which nodes they are* —
  and nothing marks a node as external-actor vs. infra-bearing vs. hex-internal.
- **No cross-diagram identity convention.** Comparator 2 needs "the same service at
  one level exists at the adjacent level." With free node ids per file, there is no
  way to decide two nodes in two `.mmd` files are the same service.

The one machine-readable hook that *does* exist — the `click` href, which the
Mod 160 reachability check already parses — does **not** close the gap. A `click`
points at a **doc path**, not at an `infra.yml` service. Only a *surface* box has a
mandated clickable target (its contract, whose path encodes `codebase.service`);
core-service boxes and backing-service boxes have no mandated clickable doc. So
`click` covers a subset of nodes at best and cannot recover the node set, let alone
the edges.

---

## Comparator 1 — service diagram ⊆ `infra.yml`: infeasible

To check "service nodes + `uses` edges are a subgraph of `infra.yml`" we must:
(a) map each infra-bearing diagram node to an `infra.yml` service, and
(b) exclude external-actor / hex-internal nodes from the check.

(a) fails — no node-id convention. (b) fails — no node-classification convention.
Both are new authoring conventions absent from `docs.md`.

**No honest partial exists.** The only sub-check reachable from *existing*
conventions is: "for each surface box, follow its `click` contract href, parse
`codebase.service` out of the contract filename, and assert that service exists in
`infra.yml`." That is **not** the subgraph comparator — it covers only
surface-bearing services, ignores backing services and non-surface core services
entirely, and checks **no edges at all**. It also substantially overlaps the
existing contract gate. Shipping it and calling SC4's comparator "implemented"
would misrepresent the deliverable, so it is rejected rather than offered as a
partial.

## Comparator 2 — diagrams vs. each other: infeasible

Needs a cross-diagram node identity (to say "this service appears at both levels")
**and** the same node-classification (to compare only the infra-bearing overlap,
per the same caveat). Both are the missing conventions. With free per-file node
ids, nothing about cross-level consistency is computable from the mermaid alone.

---

## Note on a `docs.md` imprecision (surfaced, not fixed — out of scope)

`docs.md` line ~182 says *"the **project** diagram … should match `infra.yml`."*
The subgraph relation actually belongs to the **service** diagram: the project
diagram is a single black box (C4 System Context) with external actors and has no
internal service decomposition to compare against `infra.yml`'s service graph.
research.md § "Solving Standard Diagrams Against `infra.yml`" gets this right
(it names the *service* diagram). Any future convention must resolve which diagram
carries the subgraph obligation. Flagged for `sarge`; **not** edited here (doctrine
prose is out of scope per the fence).

---

## Recommendation: DROP NOW, propose the convention for a follow-up mod

The comparators are genuinely valuable — they are the anti-drift guarantee that
lets the standard diagrams be trusted as the doc "router". The missing piece is
small and well-shaped, and docex *already* owns the infra-truth renderer
(`describe dag`). But closing the gap requires **doctrine prose changes to
`docs.md`**, which this mod is fenced out of. So: drop the implementation this
cycle; the finding satisfies SC4; open a follow-up mod once (and if) `docs.md`
gains the convention below.

### Exactly what `docs.md` § Standard Diagrams would need

For **Comparator 1** (service diagram ⊆ `infra.yml`):

1. **Node-id convention.** Infra-bearing nodes in `service_diagram.mmd` use the
   dotted reference id — core service `codebase.service`, backing service bare
   name — **identical to `describe dag`'s `node_id()`**. This is the node→infra
   map. (docex can reuse `describe/dag.py` verbatim for the truth side.)
2. **`uses`-edge obligation** among infra-bearing nodes (usage-direction arrows are
   already required), so the authored edge set is comparable to `collect_edges()`.
3. **Node-classification convention** to mark legitimately-distinct nodes (external
   actors, hex internals) so the subgraph check can exclude them — e.g. a reserved
   mermaid `subgraph` block name or an id prefix.
4. **Resolve the project-vs-service imprecision** above: state which diagram carries
   the subgraph obligation (should be the service diagram).

For **Comparator 2** (diagrams vs. each other):

5. **Cross-diagram identity**: reuse the same dotted ids across project / service /
   module diagrams so a service is identifiable across files.
6. **A precise consistency relation per adjacent pair**, e.g. service↔module: every
   core service that has a `module_diagram.mmd` appears as a node in
   `service_diagram.mmd`, and each module diagram's inbound relations reference
   services present in the service diagram.

### A stronger alternative worth `sarge`'s consideration

Because `describe dag` already **generates** the infra-truth graph, the cleanest
future design may be **generate-and-compare** rather than diff-a-free-diagram:
have docex emit the infra-bearing skeleton of the service diagram (or a checkable
fenced region within `service_diagram.mmd`) from `infra.yml`, so authors annotate
external actors / hex internals *around* a generated core. This turns a brittle
text-diff into a regeneration check (same shape as the ADR-index drift gate in
Mod 161) and largely dissolves conventions 1–3. This is a design decision for
`sarge` / the doctrine, not something to bake in unilaterally here.

---

## Decision requested of `sarge`

Confirm the **drop** (this finding satisfies Goal 2 SC4), and rule on the
follow-up: (a) drop entirely, or (b) drop-now + open a follow-up mod to add the
`docs.md` convention — and if (b), whether to pursue the **diff** approach
(conventions 1–6) or the **generate-and-compare** alternative.

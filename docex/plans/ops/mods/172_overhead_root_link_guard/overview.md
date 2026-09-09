# Mod 172 — Overhead: don't follow links out of L1 standard roots

## Problem

`docex docs overhead` (and therefore `docex docs cxt_groups`, which computes
overhead per subject) treats the **L1 standard-root files** — the arc42 L1 docs,
the standard diagrams, and the ADR indices — as ordinary link sources. These
files are *routers*: they link outward to a large fraction of the design corpus
by design. When one of them is the subject of an overhead computation, rule 2
follows every one of its outbound links and the resulting overhead spans a
tremendous number of files, most of which are not genuinely needed to make an
informed edit. In `cxt_groups all`, every root is a subject, so this bloat
inflates the context groups the `doc-refine-orchestration` skill packs.

## Current behavior

`compute_overhead` (in `docex/src/docex/docs/overhead.py`) builds overhead from
three rules:

1. **Rule 1** — always include *all* L1 standard-root docs (membership only; no
   link-following).
2. **Rule 2** — include any design doc the **subject** directly links to
   (follows the subject's outbound links, any `link_type`).
3. **Rule 3** — for a *source* subject with a module doc, include any design doc
   the **module doc** directly links to (follows the module doc's outbound
   links).

Link-following happens only in rules 2 and 3. A standard root's links are
followed exactly when the **subject itself is a standard root** (rule 2). Rule 3
follows a *module doc's* links, and module docs are L3 — never roots — so rule 3
is not a path by which a root gets link-followed.

## The change

Introduce one guard: **do not follow the outbound links of a file that is an L1
standard root.** Concretely, in `compute_overhead`:

- Compute the root set once (it is already computed for rule 1 via
  `_rule_one_roots`).
- **Rule 2** contributes nothing when the subject is a standard root.
- **Rule 3** is guarded identically for uniformity, though it never triggers in
  practice (module docs are never roots).

Rule 1 is untouched: every standard root is still present in every subject's
overhead as membership. The change only removes the *transitive fan-out* a root
produces when it is itself the subject.

### Resulting behavior deltas

- **A standard-root subject's overhead collapses to rule 1** (the other roots)
  plus whatever rule 3 adds (nothing, for a non-source subject). This is the
  entire point — a router no longer drags its whole subtree into context.
- **Mermaid-click contributions vanish for diagram subjects.** Mermaid `click`
  edges originate only in `.mmd` diagrams, and the standard diagrams
  (`project_diagram`, `service_diagram`, each `module_diagram`) are all roots.
  So under this change, a diagram-as-subject no longer pulls its click targets
  into overhead. This is a wanted consequence — diagrams are the archetypal
  router files. (Non-root docs' markdown links and source files' emergent
  module-doc edges are unaffected.)
- **Source and non-root design-doc subjects are unaffected.** A source file is
  never a root, so its rule-2 emergent fold-in to the module doc, and rule 3's
  follow of the module doc's links, both still run. A normal L2/L3 doc that
  *links to* a root still gets that root as overhead (via rule 1 anyway); we
  never followed the root's links from there, so nothing changes.

## Scope

- `docex/src/docex/docs/overhead.py` — the guard + docstring update to state the
  new rule.
- `docex/tests/unit/test_docs_overhead.py` — update `test_rule2_mermaid_click_is_overhead`
  to assert the new (blocked) behavior, and add a test that a root subject's
  overhead excludes its non-root outbound links. Verify `cxt_groups` tests still
  pass (they consume the same core).
- `doctrine/infrastructure/docex.md` — update the resident-doctrine description
  of the `overhead` rules to state the root-link guard.

Out of scope: `cxt_groups.py` itself needs no change — it consumes
`compute_overhead` and inherits the fix.

## Release

Per the operator: **PATCH** (a `docex` bug/behavior fix that changes no consumed
contract — the command surface is identical, only the overhead heuristic tightens).
Gates for this cut: the six-artifact alignment + `docex` unit and integration
tests. Smoke walks and skill evals are explicitly waived by the operator. The
doctrine-prose edit to `docex.md` is a one-line rule correction; the operator has
scoped the cohere gate out.

## Design questions

1. **Rule-2 blocking granularity.** The change blocks a root subject's rule-2
   entirely (all its outbound links). The alternative — block only links to
   *non-root* targets — is equivalent in outcome here (root targets are already
   supplied by rule 1), so entire-rule-2 blocking is chosen for simplicity.
   Flagging in case a future case wants root→root edges preserved as
   *directional* signal (not currently used anywhere).

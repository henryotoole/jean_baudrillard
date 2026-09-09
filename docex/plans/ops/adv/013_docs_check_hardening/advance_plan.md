# Goals

Advance 013 hardens the `docex docs` command family with three fixes surfaced by
**test-driving the pre-3.0.0 doc-converter guidelines against a real project**
(the Nasmyth conversion — see
[`011_archdoc_skills/doc_converter_test_snags.md`](../011_archdoc_skills/doc_converter_test_snags.md),
snags **I**, **M**, **O**). All three are gaps in what `docex docs` guarantees, and all
three must be closed in `docex` itself rather than worked around in the converter
guideline (the guideline has already been updated to *rely* on these fixes).

The three fixes:
1. **`docs adr` emits a reference-linked index** so ADRs are reachable through the
   generated index rather than requiring a hand-written inbound link from a narrative
   doc (snag I).
2. **`docs check` validates anchor resolution** — every `#fragment` in a design-doc link
   must resolve to a real heading or explicit anchor. Today `docs check` validates
   reachability but not anchors, so a link to a reworded/de-emoji'd heading, or
   cross-file anchor drift from independent edits, passes silently (snag M).
3. **`docs check` reachability is scoped to documentation extensions**, so a non-doc
   asset (an `.svg`/`.png`/`.pdf`) sitting under `plans/design` no longer fails the
   reachability gate as an "unreachable doc" (snag O).

This advance is **docex-internal**: it changes the `docs` command, the doctrine files
that describe it, and docex's own aligned artifacts. It is validated by a
**fixed-foundation smoke test only** — no elastic smoke test and no release (the changes
ride the next doctrine cut, alongside the 3.0.0 archdoc work).

Continues mod numbering from advance 011: next mod is **170**.

---

## Goal 1: `docex docs adr` — a reference-linked ADR index

**Mod 170 — `docs_adr_reference_links`.**

Today `docex docs adr` regenerates `adr_index.md` and `adr_active.md` as plain-text
tables (ID / title / status / …) with **no links to the ADR files**. Because
`docs check` requires every design doc to be reachable from a standard root, and the ADR
indexes are standard roots, each ADR currently has to be linked from *some* narrative doc
to be reachable — which is wrong: a superseded ADR would then have to link back into the
docs, a state we do not want. The index itself should carry the reference.

### Success Criteria
1. `docex docs adr` renders each ADR row's **title (or ID) as a markdown link** to the
   ADR file (`adrs/${id}_${title}.md`), in **both** `adr_index.md` and `adr_active.md`.
2. The link makes the ADR **reachable** from the index root, so an ADR that no narrative
   doc links to still passes `docs check` reachability. Verified: scaffold a project with
   an ADR linked from nowhere but the index → `docs check` green.
3. Generation stays **deterministic and idempotent** — a no-op run rewrites nothing, and
   the `adr-fresh` gate (which regenerates and diffs) agrees with the new format.
4. The `<!-- generated … do not edit -->` banner and table columns are otherwise
   unchanged; only the cell contents gain links.
5. Aligned artifacts + doctrine updated: docex unit/integration tests; docex.md and the
   docex masterplan; and the doctrine descriptions of the ADR index in
   [`doctrine/practices/adrs.md`](../../../../doctrine/practices/adrs.md#adr-index) and
   [`doctrine/practices/docs.md`](../../../../doctrine/practices/docs.md) (the reachability
   discussion notes ADRs are reachable via the linked index).

---

## Goal 2: `docex docs check` — anchor resolution + doc-extension scoping

**Mod 171 — `docs_check_anchors_and_scope`.**

Two additions to `docs check`, both in the same file-enumeration / link-graph core, so
they are one mod.

### 2a — Anchor resolution (snag M)

`docs check` gains a fourth check: **Anchor Resolution**. Every intra-doc-tree markdown
link carrying a `#fragment` must resolve to a heading or explicit `<a id>` anchor in the
target file. This is the class reachability cannot see — a reference to a heading that
was reworded or de-emoji'd, and cross-file anchor drift when files are converted
independently.

#### Success Criteria
1. For every markdown link in a design doc whose target is an in-scope design doc
   (same-file `#frag` included), the `#fragment` resolves to (a) a heading whose
   GitHub-style slug equals the fragment, or (b) an explicit `<a id="frag">`. A
   non-resolving fragment fails `docs check` with a clear
   `unresolved anchor: <file> -> <target>#<frag>` message.
2. Slug computation matches the renderer already assumed elsewhere (lowercase, strip
   non-`[\w\s-]`, spaces→hyphens); explicit `<a id>` anchors are honored so a
   source-cited frozen anchor can be pinned deliberately.
3. Built on the **same link-graph builder** the reachability check and `docs linkmap`
   already share (per docex.md — one graph, one source of truth), extended to index each
   file's heading/explicit anchors. No second link walker.
4. Scope: anchors into other **design-tree** docs are validated. Fragments into targets
   outside the tracked doc scope (e.g. `../references/*`, source files) follow the same
   rule where the target is scannable; a target the check does not scan is not failed on
   its fragment (documented, so the rule is explicit rather than accidental).
5. A **negative fixture** proves it fires: a doc linking `other.md#no-such-heading` (and a
   same-file `#gone`) fails; correcting the anchor makes it pass.

### 2b — Doc-extension-scoped reachability (snag O)

The reachability check today enumerates **every file** under `plans/design` and requires
each be reachable — so a binary asset (icon `.svg`, `.png`, a `.pdf`) dropped under
`plans/design` fails as an "unreachable doc." Reachability should apply only to
**documentation files**.

#### Success Criteria
1. The reachability population is restricted to a small **documentation-extension
   allowlist**: `.md`, `.mmd`, and `.txt`. (`.mmd` stays in — the standard diagrams are
   docs and are link sources/roots; the operator's "`.md`/`.txt`" intent is honored with
   `.mmd` retained because a diagram is a first-class doc, not an asset.)
2. A non-doc asset under `plans/design` (e.g. `frontend/specifics/icons/logo.svg`) no
   longer fails `docs check`. Verified with a fixture carrying such an asset → green.
3. This narrows only *which files must be reachable*; the **Missing Standard File**,
   **ADR-fresh**, and new **Anchor Resolution** checks are unaffected.
4. Doctrine updated: the reachability description in
   [`doctrine/practices/docs.md § Reachability Check`](../../../../doctrine/practices/docs.md#reachability-check)
   (enumerates *documentation files*, not *every file*) and the `docs check` summary in
   [`doctrine/infrastructure/docex.md § docs`](../../../../doctrine/infrastructure/docex.md#docs)
   (now lists four checks).

### Shared Success Criteria (both 2a and 2b)
5. `docex docs check` continues to pass as a no-op where there is no `plans/design`.
6. Aligned artifacts + doctrine kept in sync: docex unit/integration tests; docex.md
   (`docs check` now documents four checks); docex masterplan; the six aligned docex
   artifacts reconciled.

---

## Smoke Test (fixed-foundation only)

A single fixed-foundation validation pass; **no elastic smoke test, no release.**

1. **Positive, real corpus.** Run the new `docex docs adr` and `docex docs check`
   against a known-good doc tree on the fixed test project
   (`docex/test_projects/fixed/`) and against docex's own dogfooded docs. Expect:
   `docs adr` produces a linked index; `docs check` green (four checks); a re-run of
   `docs adr` is a no-op.
2. **Dogfood the converter output.** Run `docs check` against the Nasmyth converted tree
   produced by the guideline test (0 known broken anchors) → green, confirming the anchor
   check agrees with the hand-rolled checker used during the test.
3. **Negative fixtures fire.** In a throwaway fixture: (a) a link to a missing anchor and
   a same-file dangling fragment → `docs check` fails on Anchor Resolution; fixing them →
   green. (b) an ADR linked only from the index → reachability green (proves Goal 1). (c)
   a stray `.svg` under `plans/design` → green, not an "unreachable doc" (proves 2b).
4. **Determinism.** `docs adr` and `docs check` run twice produce identical output/exit.

Success = every codebase's tests green under `docex test` on the fixed test project, plus
the four checks above. The advance closes on a full fixed-foundation suite run before
`report.md`.

---

## Deferred (explicitly out of scope)

- **Elastic smoke test.** These are `docs`-command changes with no foundation-specific
  behavior; the fixed smoke test fully exercises them.
- **Release / cut.** The changes ride the next doctrine cut alongside the 3.0.0 archdoc
  work; this advance does not `containerize`, `release`, or `stagetest`.
- **Converter guideline edits.** Already applied out-of-band (the guideline now relies on
  these fixes); this advance only makes the `docex` behavior the guideline assumes real.

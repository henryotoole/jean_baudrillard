# Advance 013 — `docs_check_hardening` — Report

**Status:** COMPLETE (fixed-foundation smoke test only; **not merged, not released** — deferred by design to the next doctrine cut alongside the 3.0.0 archdoc work).
**Branch:** `013_docs_check_hardening` (off the committed test-of-doc-conversion tip).
**Mods:** 170, 171. **Date:** 2026-09-07.

## Goal

Harden the `docex docs` command family with three fixes surfaced by test-driving the
pre-3.0.0 doc-converter guideline against the real Nasmyth repo (snags I, M, O in
`011_archdoc_skills/doc_converter_test_snags.md`). All closed in `docex` itself, not
worked around in the converter guideline.

## Delivered

### Mod 170 — `docs_adr_reference_links` (Goal 1, snag I)
`docex docs adr` now renders each ADR row's **`ADR ID` cell as a markdown link** to the
ADR's real on-disk file (`adrs/<filename>`), in both `adr_index.md` and `adr_active.md`.
An ADR reachable only through the generated index now passes `docs check` reachability —
so a superseded ADR need not link back into the live design docs.
- Source: `docex/src/docex/docs/adr.py` — `Adr.filename` (captured in `parse_adr`, never
  derived from id+title so it cannot dangle), `_adr_link` helper, ID cell linked in
  `render_index`/`render_active`. Banner, headings, columns, all other cells byte-identical.
- Idempotent/deterministic; `adr_index_drift` (the ADR-fresh gate) agrees with the new format.
- Fixtures regenerated: both `test_projects/{fixed,elastic}` ADR indexes.

### Mod 171 — `docs_check_anchors_and_scope` (Goal 2, snags M + O)
Two additions to `docs check`, both on the shared file-enumeration / link-graph core:
- **2a — Anchor Resolution (new fourth check).** Every markdown `#fragment` into an
  in-scope design doc (same-file included) must resolve to a heading's GitHub-style slug
  or an explicit `<a id>`. Non-resolving → `unresolved anchor: <src> -> <tgt>#<frag>`,
  exit 1. Fragments into targets the check does not scan (`references/*`, source) are
  deliberately not validated. Built on new **pure helpers in `linkmap.py`** (`_slug`,
  `anchors_in`, `fragment_links_in`) — the `Node` dataclass and `docs linkmap` JSON schema
  are untouched, so no ripple to `linkmap`/`overhead`/`cxt_groups`/`changed` consumers.
  `anchors_in` skips fenced code blocks. Slug algorithm mirrors the cohere `linkcheck.py`
  slugify.
- **2b — Doc-extension-scoped reachability.** Reachability population restricted to a
  `.md`/`.mmd`/`.txt` allowlist (`.mmd` retained — diagrams are first-class docs). A loose
  asset (`.svg`/`.png`/`.pdf`) under `plans/design` no longer fails as an "unreachable doc."
  Narrows only *which files must be reachable*; Missing-Standard-File, ADR-fresh, and the
  new Anchor check are unaffected.

## Doctrine + artifacts aligned (six-artifact alignment)
- `doctrine/infrastructure/docex.md § docs` — `check` now lists **four** checks (Anchor
  Resolution added); `adr` clause notes the linked index makes ADRs reachable.
- `doctrine/practices/docs.md` — reachability now enumerates **documentation files
  (`.md`, `.mmd`, `.txt`)**, not *every file*; new `### Anchor Resolution` subsection; the
  reachability discussion notes ADRs are reachable via the linked index.
- `doctrine/practices/adrs.md` — ADR-index description updated (linked rows).
- `docex/plans/design/` — `structures_and_views.md` (three→four gates),
  `specifics/subcommand_surface.md`.
- `CHANGELOG.md` `[Unreleased]`. Tests: 13 new unit tests across the two mods.
- `tables/roles/*.yml` and `doctrine_excerpts/*` — confirmed N/A (grep-verified; a docs
  command touches neither roles nor resource excerpts).

## Validation — fixed-foundation smoke test (all green)
1. **Positive, real corpus** (`test_projects/fixed`, run from source): `docs check` green
   (four checks), deterministic across two runs; `docs adr` a clean no-op, git clean; index
   carries the 4 ADR links.
2. **Dogfood the converter output** (Nasmyth converted tree, 50 docs / 963 links, branch
   `test/3.0.0-doc-conversion`): after regenerating its ADR index to the new format,
   `docs check` **fully green** — the new anchor check agrees with the hand-rolled checker's
   "0 broken anchors." (Nasmyth restored pristine; read-only to the operator's repo.)
3. **Negative fixtures fire** (throwaway copy, real CLI):
   (a) a cross-file `#no-such-heading` + a same-file `#gone-anchor` → `docs check` FAILS on
   Anchor Resolution (exit 1, exact messages); pointing both at real heading slugs → green.
   (b) an ADR (`0005`) linked from nowhere but the index → reachability green (Goal 1 E2E).
   (c) a stray `.svg` under `plans/design` → green, not an "unreachable doc" (2b E2E).
4. **Determinism:** `docs adr` / `docs check` re-runs produce identical output/exit.

**Suite:** full docex unit suite **1480 passed**; docs-relevant integration
(`test_docs_linkmap_real`, `test_docs_changed_real`) **2 passed**. (The compile/describe
integration tests were not re-run — unrelated to a `docs`-command change, and the host hit
memory pressure; the changed behavior is fully covered by unit + docs-integration + the
four CLI smoke passes above.)

## Drift review
Both mods reviewed against their diffs by the sergeant: **zero drift**. Corporal decisions
(link the ID cell not the title; carry real `Adr.filename`; thread anchors through pure
linkmap helpers rather than the linkmap return shape) were all within the plan's criteria
and correctly avoided the one escalation trigger (a public-schema change to `docs linkmap`).

## Deferred (per plan)
- **Elastic smoke test** — no foundation-specific behavior; fixed smoke fully exercises it.
- **Release / cut** — rides the next doctrine cut with the 3.0.0 archdoc work; this advance
  did not `containerize`/`release`/`stagetest`.
- **Merge to `main`** — not performed; awaiting operator direction (the branch sits atop the
  in-flight 011/3.0.0 work).

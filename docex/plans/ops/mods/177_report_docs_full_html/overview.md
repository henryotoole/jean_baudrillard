# Mod 177 — `report_docs_full_html`

## Goal

Implement `docex report docs --format full`: a single **self-contained HTML**
document that renders Mod 176's `data`-format bucket tree as three bespoke
treemap sections. `full` becomes the real default; the `TODO(mod 177)` stub in
`run_report_docs` is removed.

Authoritative layout spec:
[`docex_report_design.md § Full Report`](../../adv/014_docs_report_and_skill_refactor/docex_report_design.md).
Success criteria: advance plan Mod 177 block.

## Design

### Consuming 176, not recomputing (SC2)

`run_report_docs` already builds `doc = build_docs_data(nodes, project_root)` —
the exact `data` document (design-doc bucket tree + source bucket tree, both
`Bucket.to_dict()` dicts with `{name, tokens, children?}`). The `full` path
calls the **same** `build_docs_data`, then hands its dict to a new renderer.
177 never re-walks `plans/design`, never re-lints, never re-estimates tokens.
Every rectangle area derives from a `tokens` value already in that dict.

New module `src/docex/report/full.py`. Split into pure **layout** functions
(dict → list of positioned rectangles carrying their source `tokens`) and thin
**SVG emit** functions (rectangles → SVG markup). The layout/emit split is what
makes area-proportionality (SC2) and determinism (SC4) unit-testable without
parsing SVG.

### Section 1 — Code-Doc Comparison

A 4:3 rectangle (wider than tall) split into two vertical slices: left width ∝
`doc["design_docs"]["tokens"]`, right width ∝ `doc["source_code"]["tokens"]`.
Equal full height, so area ∝ weight.

### Section 2 — Doc Treemap

A 4:3 rectangle. The whole graphic is first split into **two master horizontal
bands** by weight:
- **top band** (height ∝ sum of the four non-ADR primaries) holds the four
  primary vertical slices;
- **ADR band** (height ∝ `ADRs` tokens) spans the full width **beneath** all
  four — graphically expressing that ADRs span every abstraction level.

The top band is split into **vertical slices**, one per primary bucket EXCEPT
ADRs, in the fixed order **L1 Standard Roots, L1 Detail Docs, L2 Architecture
Docs, L3 Module Docs**; each slice width ∝ that primary's tokens. Each primary
slice is split into **horizontal sub-slices** (its children / sub-buckets),
height ∝ each child's tokens. Each sub-slice is split into a further set of
**horizontal sub-sub-slices divided by dashed lines** (the child's children /
sub-sub-buckets), height ∝ each grandchild's tokens. A sub-bucket that is a leaf
(e.g. `lexicon.md`) renders as a single undivided band. `etc` remainder buckets,
present in the `data` dict wherever children under-sum, render as slices like
any other. Area ∝ token weight throughout.

This is a generic 3-level recursion over the `data` dict's primary → child →
grandchild structure — the dict already carries exactly these levels (verified
against the `data` shape: e.g. `L2 Architecture Docs → {Module Diagrams,
specifics, Other Files} → individual files`).

### Section 3 — Code Treemap

Per the design doc: a **square** cut into three horizontal slices — bottom =
`other / unlintable`, middle = `code`, top split into three vertical slices
(inline comments, docstrings, references, L→R). Heights ∝ the three grouped
weights; the top slice's three vertical-slice widths ∝ the three weights.

Rendered **one per codebase AND one per hex module**. Codebases are the children
of `Source Code`; a hex module is a codebase child that is a group of file
buckets. The five leaf weights for a codebase/module are **aggregated** by
summing the five leaf categories over all descendant file buckets in the `data`
dict (again: consuming 176, not re-linting). The synthetic `(root)` group
(module == `none`, non-module files under `src`) is **not** a hex module, so it
gets no standalone module treemap — its weight is still covered by the codebase
treemap.

### Self-containment (SC1)

One HTML string: inline `<style>`, inline `<svg>` elements, no external asset
references — no `<link>`, no `<img>`, no `src=`, no `http://`/`https://`.
Inline SVG in an HTML5 document does not need an `xmlns` (the HTML parser places
`<svg>` in the SVG namespace), so the SVG namespace URL — the one place an
`http://` would otherwise appear — is omitted. Emitted to **stdout** (consistent
with `--format data`), so "writes one HTML document" = prints it.

### Determinism (SC4)

Rendering iterates the `data` dict's already-deterministic child order; no
timestamps, no randomness, no volatile content anywhere in the body. Same corpus
→ byte-identical HTML.

### Visual-styling latitude (reported, not escalated)

- Fixed light-background report; a small fixed palette — one hue per doc-treemap
  primary + a distinct ADR-band hue; five fixed hues for the code-treemap
  categories; two hues for the comparison.
- System-font stack; labels drawn only when a slice is large enough to fit
  legibly (small slices render as colored area with no text) — a minimum-size
  legibility guard, not a change to any area.
- Zero-weight / empty-project corpora render valid HTML with all three section
  headings and a "no data" note where a section has nothing to draw.

## Six aligned artifacts

- `doctrine/.../docex.md` — `report` section edit **pre-authorized (SC 177.5)**:
  make the `full` sentence describe the shipped three-section HTML report.
- `docex/plans/design/**` — update `subcommand_surface.md`'s `report` row (drop
  the "full stubs to data" note; state the three-section HTML).
- `tables/roles/*.yml` — no change (report introduces no role/engine). Confirmed.
- `src/docex/**` — new `full.py`; `run_report_docs` full path; `__init__` export.
- `tests/**` — new `test_report_full.py`.
- `doctrine_excerpts/index.yml` — no change (report is not an infrastructural
  resource). Confirmed.

## Design questions

None. The design doc is concrete on layout; all open points are visual-styling
latitude resolved above.

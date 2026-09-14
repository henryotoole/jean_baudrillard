# Mod 177 — Implementation Steps

Implement `docex report docs --format full`: a self-contained HTML report of
three bespoke treemap sections that **consumes** Mod 176's `data` bucket tree.

Work only in `~/.claude/jean_baudrillard/docex`. Do **NOT** edit doctrine files,
`docex/plans/design/**`, `CHANGELOG.md`, `RELEASING.md`, `pyproject.toml`, or
`__init__.py` version — those are handled outside this implementation step.
Scope: new `src/docex/report/full.py`, edits to `src/docex/report/docs.py` and
`src/docex/report/__init__.py`, and a new test file.

## Background: the `data` document you consume

`docex.report.docs.build_docs_data(nodes, project_root)` returns:

```python
{
  "report": "docs", "format": "data",
  "estimator": {...},
  "design_docs": <bucket dict>,   # name == "Design Docs"
  "source_code": <bucket dict>,   # name == "Source Code"
}
```

A **bucket dict** is `{"name": str, "tokens": int, "children"?: [bucket, ...]}`.
A leaf omits `children`. `full` must render **only** from this dict — never
re-walk `plans/design`, re-lint, or re-estimate tokens.

Design-docs tree shape:
- `Design Docs` → primaries in order: `L1 Standard Roots`, `L1 Detail Docs`,
  `L2 Architecture Docs`, `L3 Module Docs`, `ADRs` (a **leaf** — no children),
  possibly a trailing `etc`.
- Each non-ADR primary → sub-buckets (children) → sub-sub-buckets (grandchildren)
  or a leaf sub-bucket.

Source tree shape:
- `Source Code` → per-codebase groups → (hex) per-module groups → per-file
  buckets → the five leaves; (non-hex) per-file buckets directly under codebase.
- File-bucket leaves are exactly, in order: `inline comments`, `docstrings`,
  `references`, `code`, `other / unlintable` (some may be absent if zero; an
  `etc` never appears at the file level because the five leaves partition the
  file).

## Step 1 — new module `src/docex/report/full.py`

Create the module. Structure: pure **layout** helpers returning positioned
rectangles, then **SVG emit** helpers, then `render_full_html(doc)`.

### 1a. Rect type and helpers

```python
from __future__ import annotations
from dataclasses import dataclass, field
from html import escape

LEAF_LABELS = (
    "inline comments", "docstrings", "references", "code", "other / unlintable",
)

@dataclass
class Rect:
    label: str
    x: float
    y: float
    w: float
    h: float
    tokens: int
    kind: str            # palette key, e.g. "primary:L1 Standard Roots", "leaf:code"
    dashed: bool = False # sub-sub-bucket dashed divider styling
```

Add a helper `def _kids(b): return b.get("children") or []`.

Add a **proportional split** helper that divides a length among weighted items,
guarding zero total:

```python
def _splits(total_len, weights):
    """Return a list of (offset, length) for each weight, lengths ∝ weight.
    If sum(weights) == 0, all lengths are 0."""
    s = sum(weights)
    out, off = [], 0.0
    for w in weights:
        ln = (total_len * w / s) if s else 0.0
        out.append((off, ln))
        off += ln
    return out
```

### 1b. Section 1 layout — Code-Doc Comparison

`def layout_comparison(doc, W, H) -> list[Rect]:`
- `W, H` a 4:3 box (e.g. 800×600).
- Two vertical slices: widths from `_splits(W, [design_tokens, source_tokens])`
  where `design_tokens = doc["design_docs"]["tokens"]`,
  `source_tokens = doc["source_code"]["tokens"]`. Full height `H`.
- Return two Rects: labels `"Design Docs"` / `"Source Code"`, kinds
  `"compare:design"` / `"compare:source"`, tokens the respective totals.

### 1c. Section 2 layout — Doc Treemap

`def layout_doc_treemap(design_bucket, W, H) -> list[Rect]:`
- Separate the primaries: `prims = _kids(design_bucket)`. Find the ADR primary
  (`name == "ADRs"`); the non-ADR primaries are everything else **excluding any
  top-level `etc`** — keep `etc` out of the four vertical slices (fold its weight
  into nothing; it should normally be absent because primaries sum exactly).
  Preserve the canonical order: L1 Standard Roots, L1 Detail Docs, L2
  Architecture Docs, L3 Module Docs. Sort the non-ADR primaries by that fixed
  order (fall back to given order for any unexpected name).
- Master vertical split of `H` into two bands by weight:
  `[sum(non-ADR primary tokens), adr_tokens]` → top band height `Ht`, ADR band
  height `Ha`. Top band occupies `y∈[0,Ht]`, ADR band `y∈[Ht,Ht+Ha]`.
- ADR band: one full-width Rect `(0, Ht, W, Ha)`, kind `"adr"`, label `"ADRs"`.
- Top band: vertical slices across `W` from `_splits(W, [p.tokens for non-ADR])`.
  For each primary slice `(px, pw)`:
  - Emit the primary's own frame Rect `(px, 0, pw, Ht)`, kind
    `f"primary:{name}"` (used for the slice's header/background color).
  - Horizontal sub-slices down `Ht` from `_splits(Ht, [c.tokens for children])`.
    For each child `(cy, ch)` at x-range `[px, px+pw]`:
    - Emit sub-slice Rect, kind `f"primary:{name}"` (lighter shade), label the
      child name.
    - If the child has grandchildren, split `ch` further into sub-sub-slices via
      `_splits(ch, [g.tokens ...])`, each emitted as a Rect with `dashed=True`
      and label the grandchild name. (A leaf child emits no sub-sub Rects.)
- Return the flat list of all Rects (primary frames, sub-slices, sub-sub-slices,
  ADR band). Tag each with enough info (kind, dashed) for emit + tests.

Keep emit order stable: ADR band last, primaries L→R, children top→bottom.

### 1d. Section 3 — Code Treemap aggregation + layout

Aggregation (consume the `data` dict, do not re-lint):

```python
def aggregate_leaves(bucket) -> dict[str, int]:
    """Sum the five leaf categories over all descendant FILE buckets."""
    totals = {k: 0 for k in LEAF_LABELS}
    def walk(b):
        kids = _kids(b)
        if kids and all(k["name"] in LEAF_LABELS for k in kids):
            for k in kids:
                totals[k["name"]] += k["tokens"]      # a file bucket
        else:
            for k in kids:
                walk(k)
    walk(bucket)
    return totals
```

Identify codebases and hex modules from the source tree:

```python
def _is_file_bucket(b):
    kids = _kids(b)
    return bool(kids) and all(k["name"] in LEAF_LABELS for k in kids)

def code_treemap_targets(source_bucket):
    """Ordered list of (title, leaves_dict): one per codebase, then one per hex
    module. A hex module = a codebase child that is a group of file buckets and
    is not the synthetic '(root)' group."""
    targets = []
    for cb in _kids(source_bucket):                    # codebase groups
        targets.append((cb["name"], aggregate_leaves(cb)))
    for cb in _kids(source_bucket):
        for child in _kids(cb):
            if not _is_file_bucket(child) and child["name"] != "(root)":
                # child is a hex module group
                targets.append((f"{cb['name']} / {child['name']}",
                                aggregate_leaves(child)))
    return targets
```

(Emit all codebases first, then all modules — deterministic and stable.)

Layout one square:

```python
def layout_code_treemap(leaves, S) -> list[Rect]:
    top = leaves["inline comments"] + leaves["docstrings"] + leaves["references"]
    mid = leaves["code"]
    bot = leaves["other / unlintable"]
    (ty, th), (my, mh), (by, bh) = _splits(S, [top, mid, bot])
    rects = []
    # top band split into three vertical slices L->R
    for (bx, bw), key in zip(
        _splits(S, [leaves["inline comments"], leaves["docstrings"],
                    leaves["references"]]),
        ("inline comments", "docstrings", "references"),
    ):
        rects.append(Rect(key, bx, ty, bw, th, leaves[key], f"leaf:{key}"))
    rects.append(Rect("code", 0, my, S, mh, mid, "leaf:code"))
    rects.append(Rect("other / unlintable", 0, by, S, bh, bot,
                      "leaf:other / unlintable"))
    return rects
```

### 1e. SVG emit + palette

Define a fixed palette dict mapping kind → fill. Keep it a light-background
report. Suggested (you may adjust hues — report your choices):
- `compare:design` `#4C78A8`, `compare:source` `#F58518`
- primaries: `L1 Standard Roots` `#4C78A8`, `L1 Detail Docs` `#72B7B2`,
  `L2 Architecture Docs` `#54A24B`, `L3 Module Docs` `#EECA3B`; `adr` `#B279A2`
- leaves: `inline comments` `#9ECAE9`, `docstrings` `#FFBF79`,
  `references` `#88D27A`, `code` `#BAB0AC`, `other / unlintable` `#E0E0E0`

Emit each Rect as `<rect x y width height fill ...>` (dashed sub-sub-slices get
`stroke-dasharray="4 3"` and a thin stroke; others a hairline light stroke).
Draw a `<text>` label centered in the rect **only** when the rect is large
enough for legibility (guard: `w >= ~40 and h >= ~14`); include a compact token
count in the label where it fits. Escape all labels with `html.escape`.

**Do NOT put an `xmlns` on the `<svg>`** — inline SVG in HTML5 needs none, and
omitting it keeps the no-`http://` self-containment guarantee. Use a `viewBox`
and set `width`/`height` (or a CSS max-width) so it scales.

### 1f. `render_full_html(doc) -> str`

Assemble one HTML string:
- `<!doctype html><html><head><meta charset="utf-8"><style>…</style>
  <title>docex report — docs</title></head><body>…</body></html>`
- Inline `<style>`: system font stack, section spacing, a small legend.
- Three `<section>`s in order with `<h2>` headings: "Code-Doc Comparison",
  "Doc Treemap", "Code Treemap". Section 3 lays the per-codebase / per-module
  squares out in a responsive grid (`display:flex;flex-wrap:wrap` or CSS grid),
  each square captioned with its title.
- **No timestamp / no volatile content** anywhere in the body.
- Zero-weight guard: if a section has nothing to draw (all weights 0 / empty
  project), still emit the heading and a "no data" `<p>`.

Determinism: rely solely on the `doc` dict's existing order; no `set` iteration
in emit order (sort or preserve list order), no `time`, no `random`.

## Step 2 — wire `full` into `run_report_docs` (`src/docex/report/docs.py`)

Replace the stub block in `run_report_docs`:

```python
    cbs = codebases(ctx)
    nodes, _edges = load_code_level_graph(ctx.project_root, cbs)
    doc = build_docs_data(nodes, ctx.project_root)
    if fmt == "full":
        from docex.report.full import render_full_html
        print(render_full_html(doc))
        return 0
    print(render_data_json(doc))
    return 0
```

Remove the `TODO(mod 177)` stub and the stderr "not implemented" note entirely.
Update the function docstring to state `full` renders the HTML report.

## Step 3 — export (`src/docex/report/__init__.py`)

Add `render_full_html` to the imports from `docex.report.docs`? No — it lives in
`docex.report.full`. Add `from docex.report.full import render_full_html` and
include `"render_full_html"` in `__all__`. Update the module docstring's "until
then it stubs to data" line to note `full` now renders HTML.

## Step 4 — tests: `tests/unit/test_report_full.py`

Reuse the `_corpus` fixture pattern from `tests/unit/test_report_docs.py` (build
a `data` doc via `build_linkmap` + `build_docs_data`; no git repo needed). Add:

1. **`test_full_html_has_three_sections`** — `render_full_html(doc)` contains the
   three `<h2>` headings in order, is a single HTML document (one `<!doctype`,
   one `</html>`), and contains `<svg` elements.
2. **`test_full_has_no_external_refs`** — assert the HTML contains **no**
   `http://`, `https://`, `src=`, `<link`, or `<img` (case-insensitive regex /
   substring checks). This proves self-containment (SC1).
3. **`test_full_determinism`** — `render_full_html(doc)` twice → byte-identical
   (SC4).
4. **`test_comparison_area_traces_to_data`** — call `layout_comparison(doc, 800,
   600)`; assert the two rects' width ratio equals the design/source token ratio
   (within a small epsilon), proving area ∝ 176's weights (SC2).
5. **`test_doc_treemap_adr_band_and_primaries`** — call `layout_doc_treemap(
   doc["design_docs"], W, H)`; assert (a) exactly one `kind == "adr"` full-width
   rect exists, positioned beneath the top band (its `y` ≈ top-band height); (b)
   the four non-ADR primaries appear as vertical slices whose widths are ∝ their
   `tokens`; (c) the ADR band height / total height ≈ adr_tokens / design_tokens.
6. **`test_code_treemap_per_codebase_and_module`** — from
   `code_treemap_targets(doc["source_code"])`, assert there is a target per
   codebase (`api`, `frontend`) **and** one per hex module (`api / m1`), and no
   target for `(root)`. For one target, assert `layout_code_treemap` yields a
   bottom `other`, middle `code`, and top three vertical slices whose widths ∝
   the three top-category weights (SC2/SC3).
7. **`test_full_default_renders_via_wrapper`** — monkeypatch
   `docex.report.docs.load_code_level_graph` (as the existing
   `test_run_report_docs_data_via_wrapper` does) and call `run_report(sample_ctx,
   "docs", "full")`; assert rc 0, stdout starts with `<!doctype`
   (case-insensitive) and has the three headings, and **stderr is empty** (the
   stub note is gone).
8. **`test_full_empty_project_ok`** — `run_report(sample_ctx, "docs", "full")`
   on the empty sample fixture returns 0 and still emits the three headings.

## Step 5 — run tests

From the docex root:

```sh
cd ~/.claude/jean_baudrillard/docex
python -m pytest tests/unit/test_report_full.py tests/unit/test_report_docs.py -q
```

Then run the full suite to confirm no regression:

```sh
python -m pytest tests
```

(Use `python -m pytest tests`, never bare `pytest`; the default suite is
`tests`, not `tests/unit`.) All must be green. Note `test_full_stubs_to_data_
with_note` in `test_report_docs.py` asserts the OLD stub behavior — **delete or
update that test** since `full` no longer stubs (replace its assertion with the
new full-render behavior, or remove it in favor of the new full tests).

## Done

Report: files changed, new tests added, and the full `python -m pytest tests`
result (green count). Do not commit — the corporal handles commits, review, and
the design-doc / doctrine reconciliation.

"""``docex report docs --format full`` — the self-contained HTML report.

Renders Mod 176's ``data`` bucket tree (the dict ``build_docs_data`` returns) as
three bespoke treemap sections. This module **consumes** that dict — it never
re-walks ``plans/design``, re-lints source, or re-estimates tokens. Every
rectangle's area derives from a ``tokens`` value already present in the dict.

The module is split into pure **layout** helpers (dict → positioned ``Rect``s
carrying their source ``tokens``) and thin **SVG emit** helpers (``Rect``s → SVG
markup). That split makes area-proportionality and determinism unit-testable
without parsing SVG.

Self-containment: one HTML string with an inline ``<style>`` and inline
``<svg>`` elements, no external asset references and no ``xmlns`` on the SVG
(inline SVG in an HTML5 document needs none), so no ``http://`` appears anywhere.
Determinism: layout iterates the dict's already-deterministic child order; no
timestamps, no randomness, no volatile body content.

Layout spec: ``docex_report_design.md § Full Report``.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

LEAF_LABELS = (
    "inline comments",
    "docstrings",
    "references",
    "code",
    "other / unlintable",
)

# Canonical primary order for the doc treemap's vertical slices (ADRs excluded —
# it renders as the full-width band beneath these four).
DOC_PRIMARY_ORDER = (
    "L1 Standard Roots",
    "L1 Detail Docs",
    "L2 Architecture Docs",
    "L3 Module Docs",
)


@dataclass
class Rect:
    label: str
    x: float
    y: float
    w: float
    h: float
    tokens: int
    kind: str  # palette key, e.g. "primary:L1 Standard Roots", "leaf:code"
    dashed: bool = False  # sub-sub-bucket dashed divider styling


# --- layout helpers ---------------------------------------------------------


def _kids(b: dict) -> list:
    return b.get("children") or []


def _splits(total_len: float, weights) -> list:
    """Return a list of ``(offset, length)`` per weight, lengths ∝ weight.

    If ``sum(weights) == 0``, all lengths are 0.
    """
    s = sum(weights)
    out, off = [], 0.0
    for w in weights:
        ln = (total_len * w / s) if s else 0.0
        out.append((off, ln))
        off += ln
    return out


# --- Section 1 layout — Code-Doc Comparison ---------------------------------


def layout_comparison(doc: dict, W: float, H: float) -> list:
    """Two full-height vertical slices, widths ∝ design vs. source totals."""
    design_tokens = doc["design_docs"]["tokens"]
    source_tokens = doc["source_code"]["tokens"]
    (dx, dw), (sx, sw) = _splits(W, [design_tokens, source_tokens])
    return [
        Rect("Design Docs", dx, 0.0, dw, H, design_tokens, "compare:design"),
        Rect("Source Code", sx, 0.0, sw, H, source_tokens, "compare:source"),
    ]


# --- Section 2 layout — Doc Treemap -----------------------------------------


def layout_doc_treemap(design_bucket: dict, W: float, H: float) -> list:
    """Four primary vertical slices in a top band, ADRs as a full-width band.

    Master vertical split by weight into a top band (Σ non-ADR primaries) and an
    ADR band beneath it. Each primary slice splits horizontally into its children
    (sub-slices); a child with grandchildren splits further into dashed
    sub-sub-slices. Emit order is stable: primaries L→R, children top→bottom,
    ADR band last.
    """
    prims = _kids(design_bucket)
    adr_bucket = next((p for p in prims if p["name"] == "ADRs"), None)
    # Non-ADR primaries, excluding any top-level etc (kept out of the slices).
    non_adr = [p for p in prims if p["name"] not in ("ADRs", "etc")]
    order = {name: i for i, name in enumerate(DOC_PRIMARY_ORDER)}
    non_adr.sort(key=lambda b: order.get(b["name"], len(order)))

    adr_tokens = adr_bucket["tokens"] if adr_bucket else 0
    non_adr_tokens = sum(p["tokens"] for p in non_adr)
    (_ty, Ht), (_ay, Ha) = _splits(H, [non_adr_tokens, adr_tokens])

    rects: list = []
    # Top band: one vertical slice per non-ADR primary, L→R.
    for (px, pw), primary in zip(
        _splits(W, [p["tokens"] for p in non_adr]), non_adr
    ):
        name = primary["name"]
        kind = f"primary:{name}"
        # Primary frame (identified in emit by label == primary name).
        rects.append(Rect(name, px, 0.0, pw, Ht, primary["tokens"], kind))
        children = _kids(primary)
        for (cy, ch), child in zip(
            _splits(Ht, [c["tokens"] for c in children]), children
        ):
            rects.append(
                Rect(child["name"], px, cy, pw, ch, child["tokens"], kind)
            )
            grandkids = _kids(child)
            for (gy, gh), gk in zip(
                _splits(ch, [g["tokens"] for g in grandkids]), grandkids
            ):
                rects.append(
                    Rect(
                        gk["name"],
                        px,
                        cy + gy,
                        pw,
                        gh,
                        gk["tokens"],
                        kind,
                        dashed=True,
                    )
                )

    # ADR band last: full-width, beneath the top band.
    if adr_bucket is not None:
        rects.append(Rect("ADRs", 0.0, Ht, W, Ha, adr_tokens, "adr"))
    return rects


# --- Section 3 — Code Treemap aggregation + layout --------------------------


def aggregate_leaves(bucket: dict) -> dict:
    """Sum the five leaf categories over all descendant FILE buckets."""
    totals = {k: 0 for k in LEAF_LABELS}

    def walk(b: dict) -> None:
        kids = _kids(b)
        if kids and all(k["name"] in LEAF_LABELS for k in kids):
            for k in kids:  # a file bucket
                totals[k["name"]] += k["tokens"]
        else:
            for k in kids:
                walk(k)

    walk(bucket)
    return totals


def _is_file_bucket(b: dict) -> bool:
    kids = _kids(b)
    return bool(kids) and all(k["name"] in LEAF_LABELS for k in kids)


def code_treemap_targets(source_bucket: dict) -> list:
    """Ordered ``(title, leaves_dict)``: one per codebase, then one per module.

    A hex module = a codebase child that is a group of file buckets and is not
    the synthetic ``(root)`` group. Codebases first, then modules — deterministic.
    """
    targets: list = []
    for cb in _kids(source_bucket):  # codebase groups
        targets.append((cb["name"], aggregate_leaves(cb)))
    for cb in _kids(source_bucket):
        for child in _kids(cb):
            if not _is_file_bucket(child) and child["name"] != "(root)":
                targets.append(
                    (f"{cb['name']} / {child['name']}", aggregate_leaves(child))
                )
    return targets


def code_treemap_groups(source_bucket: dict) -> list:
    """Ordered per-codebase groups for the sub-headinged code-treemap section.

    Returns ``[(codebase_name, codebase_leaves, [(module_name, module_leaves)])]``
    — the whole-codebase aggregate paired with its hex modules (each a codebase
    child that is a group of file buckets and not the synthetic ``(root)``).
    Deterministic: codebases and modules in the dict's child order.
    """
    groups: list = []
    for cb in _kids(source_bucket):  # codebase groups
        modules = [
            (child["name"], aggregate_leaves(child))
            for child in _kids(cb)
            if not _is_file_bucket(child) and child["name"] != "(root)"
        ]
        groups.append((cb["name"], aggregate_leaves(cb), modules))
    return groups


def layout_code_treemap(leaves: dict, S: float) -> list:
    """One square: bottom ``other``, middle ``code``, top three vertical slices."""
    top = leaves["inline comments"] + leaves["docstrings"] + leaves["references"]
    mid = leaves["code"]
    bot = leaves["other / unlintable"]
    (ty, th), (my, mh), (by, bh) = _splits(S, [top, mid, bot])
    rects: list = []
    for (bx, bw), key in zip(
        _splits(
            S,
            [
                leaves["inline comments"],
                leaves["docstrings"],
                leaves["references"],
            ],
        ),
        ("inline comments", "docstrings", "references"),
    ):
        rects.append(Rect(key, bx, ty, bw, th, leaves[key], f"leaf:{key}"))
    rects.append(Rect("code", 0.0, my, S, mh, mid, "leaf:code"))
    rects.append(
        Rect("other / unlintable", 0.0, by, S, bh, bot, "leaf:other / unlintable")
    )
    return rects


# --- palette + SVG emit -----------------------------------------------------

# Fixed, light-background palette. Keys are Rect ``kind`` values.
PALETTE = {
    "compare:design": "#4C78A8",
    "compare:source": "#F58518",
    "primary:L1 Standard Roots": "#4C78A8",
    "primary:L1 Detail Docs": "#72B7B2",
    "primary:L2 Architecture Docs": "#54A24B",
    "primary:L3 Module Docs": "#EECA3B",
    "adr": "#B279A2",
    "leaf:inline comments": "#9ECAE9",
    "leaf:docstrings": "#FFBF79",
    "leaf:references": "#88D27A",
    "leaf:code": "#BAB0AC",
    "leaf:other / unlintable": "#E0E0E0",
}
_FALLBACK_FILL = "#CCCCCC"


def _fmt(v: float) -> str:
    """Deterministic 2-decimal float formatting for SVG coordinates."""
    return f"{v:.2f}"


def _lighten(hex_color: str, factor: float) -> str:
    """Mix a hex color toward white by ``factor`` (0 → unchanged, 1 → white)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    r = round(r + (255 - r) * factor)
    g = round(g + (255 - g) * factor)
    b = round(b + (255 - b) * factor)
    return f"#{r:02X}{g:02X}{b:02X}"


def _fill_for(rect: Rect) -> str:
    if rect.dashed:
        return "none"
    color = PALETTE.get(rect.kind, _FALLBACK_FILL)
    # A primary sub-slice (child of a primary) renders in a lighter shade than
    # the primary frame; the frame is the rect whose label is the primary name.
    if rect.kind.startswith("primary:") and rect.label not in DOC_PRIMARY_ORDER:
        color = _lighten(color, 0.45)
    return color


def _svg_rect(rect: Rect) -> str:
    fill = _fill_for(rect)
    if rect.dashed:
        stroke = ' stroke="#555555" stroke-width="0.75" stroke-dasharray="4 3"'
    else:
        stroke = ' stroke="#FFFFFF" stroke-width="0.75"'
    # data-name always carries the full name + weight so the hover readout can
    # surface it even for boxes too small to hold a visible label.
    data_name = escape(f"{rect.label} ({rect.tokens})")
    parts = [
        f'<rect x="{_fmt(rect.x)}" y="{_fmt(rect.y)}" '
        f'width="{_fmt(rect.w)}" height="{_fmt(rect.h)}" '
        f'fill="{fill}"{stroke} data-name="{data_name}"/>'
    ]
    # Legibility guard: only label rects large enough to read.
    if rect.w >= 40 and rect.h >= 14:
        text = escape(rect.label)
        if rect.w >= 110:
            text += f" ({rect.tokens})"
        if rect.dashed:
            # Deepest (sub-sub-bucket) boxes stay centered.
            cx = _fmt(rect.x + rect.w / 2)
            cy = _fmt(rect.y + rect.h / 2)
            parts.append(
                f'<text x="{cx}" y="{cy}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="11" fill="#222222">'
                f"{text}</text>"
            )
        else:
            # Solid-line boxes: bold, anchored top-left.
            tx = _fmt(rect.x + 4)
            ty = _fmt(rect.y + 4)
            parts.append(
                f'<text x="{tx}" y="{ty}" text-anchor="start" '
                f'dominant-baseline="hanging" font-size="11" '
                f'font-weight="bold" fill="#222222">'
                f"{text}</text>"
            )
    return "".join(parts)


def _has_area(rects) -> bool:
    return any(r.w > 0 and r.h > 0 for r in rects)


def _svg(rects, w: float, h: float, extra: str = "") -> str:
    body = "".join(_svg_rect(r) for r in rects)
    return (
        f'<svg viewBox="0 0 {_fmt(w)} {_fmt(h)}" '
        f'width="{_fmt(w)}" height="{_fmt(h)}"{extra}>{body}</svg>'
    )


def _scope(inner: str) -> str:
    """Wrap diagram markup with a hover readout panel to its right."""
    return (
        '<div class="viz-scope">'
        f'<div class="viz-body">{inner}</div>'
        '<div class="readout" aria-live="polite"></div>'
        "</div>"
    )


def _code_cell(rects, title: str) -> str:
    return (
        '<figure class="code-cell">'
        + _svg(rects, 300, 300)
        + f"<figcaption>{escape(title)}</figcaption>"
        + "</figure>"
    )


# Inline, dependency-free hover behavior: within each viz-scope, hovering a box
# writes its data-name into that scope's readout panel. No external references.
_JS = (
    "document.querySelectorAll('.viz-scope').forEach(function(s){"
    "var o=s.querySelector('.readout');if(!o)return;"
    "s.addEventListener('mouseover',function(e){"
    "var n=e.target.getAttribute&&e.target.getAttribute('data-name');"
    "if(n)o.textContent=n;});"
    "s.addEventListener('mouseout',function(e){"
    "if(e.target.hasAttribute&&e.target.hasAttribute('data-name'))"
    "o.textContent='';});});"
)

_NO_DATA = "<p class=\"no-data\">no data</p>"

_STYLE = """
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
         Helvetica, Arial, sans-serif; margin: 0; padding: 24px;
         color: #222; background: #fff; }
  h1 { font-size: 20px; margin: 0 0 16px; }
  section { margin-bottom: 36px; }
  h2 { font-size: 16px; margin: 0 0 12px; border-bottom: 1px solid #ddd;
       padding-bottom: 4px; }
  h3 { font-size: 14px; margin: 20px 0 8px; color: #333; }
  svg { max-width: 100%; height: auto; border: 1px solid #eee; }
  svg rect { pointer-events: all; }
  svg rect:hover { stroke: #000; stroke-width: 3; stroke-dasharray: none;
       cursor: pointer; }
  .no-data { color: #888; font-style: italic; }
  .viz-scope { display: flex; gap: 16px; align-items: flex-start;
       flex-wrap: wrap; }
  .viz-body { flex: 1 1 auto; min-width: 0; }
  .readout { flex: 0 0 200px; align-self: stretch; min-height: 2.5em;
       font-size: 13px; color: #333; padding: 8px 10px; border: 1px solid #eee;
       background: #fafafa; border-radius: 4px; position: sticky; top: 8px;
       word-break: break-word; }
  .readout:empty::before { content: "hover a box\\2026"; color: #aaa; }
  .code-grid { display: flex; flex-wrap: wrap; gap: 16px; }
  .code-grid-solo { margin-bottom: 4px; }
  .code-cell { display: flex; flex-direction: column; align-items: center; }
  .code-cell figcaption { font-size: 12px; margin-top: 4px; color: #444;
       text-align: center; max-width: 200px; }
  figure { margin: 0; }
""".strip()


def render_full_html(doc: dict) -> str:
    """Render the ``data`` dict as one self-contained HTML report string.

    Three sections in order — Code-Doc Comparison, Doc Treemap, Code Treemap.
    Consumes ``doc`` verbatim; never recomputes weights. Every section emits its
    heading; a section with nothing to draw emits a "no data" note instead of a
    graphic. No timestamps or volatile content — same ``doc`` → identical HTML.
    """
    parts: list = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>docex report — docs</title>",
        f"<style>{_STYLE}</style>",
        "</head>",
        "<body>",
        "<h1>docex report — docs</h1>",
    ]

    # --- Section 1: Code-Doc Comparison ---
    parts.append("<section>")
    parts.append("<h2>Code-Doc Comparison</h2>")
    cmp_rects = layout_comparison(doc, 800, 600)
    if _has_area(cmp_rects):
        parts.append(_scope(_svg(cmp_rects, 800, 600)))
    else:
        parts.append(_NO_DATA)
    parts.append("</section>")

    # --- Section 2: Doc Treemap ---
    parts.append("<section>")
    parts.append("<h2>Doc Treemap</h2>")
    doc_rects = layout_doc_treemap(doc["design_docs"], 800, 600)
    if _has_area(doc_rects):
        parts.append(_scope(_svg(doc_rects, 800, 600)))
    else:
        parts.append(_NO_DATA)
    parts.append("</section>")

    # --- Section 3: Code Treemap (one sub-heading per codebase) ---
    parts.append("<section>")
    parts.append("<h2>Code Treemap</h2>")
    groups = code_treemap_groups(doc["source_code"])
    body: list = []
    for cb_name, cb_leaves, modules in groups:
        cb_rects = layout_code_treemap(cb_leaves, 300)
        if not _has_area(cb_rects):
            continue
        body.append(f"<h3>{escape(cb_name)}</h3>")
        # Whole-codebase treemap on its own line.
        body.append('<div class="code-grid code-grid-solo">')
        body.append(_code_cell(cb_rects, f"{cb_name} (all)"))
        body.append("</div>")
        # Tiled module treemaps beneath.
        cells = [
            _code_cell(r, mod_name)
            for mod_name, mod_leaves in modules
            if _has_area(r := layout_code_treemap(mod_leaves, 300))
        ]
        if cells:
            body.append('<div class="code-grid">')
            body.extend(cells)
            body.append("</div>")
    if body:
        parts.append(_scope("".join(body)))
    else:
        parts.append(_NO_DATA)
    parts.append("</section>")

    parts.append(f"<script>{_JS}</script>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)

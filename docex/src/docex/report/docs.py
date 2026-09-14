"""``docex report docs`` — the ``data`` (distillation) format.

Emits deterministic JSON of token-weight buckets for the design-doc corpus and
the source code. The design-doc bucket tree is built from the SHARED linkmap
graph (``load_code_level_graph``) — not a re-walk of ``plans/design`` — and all
token estimates use linkmap's estimator (``_CHARS_PER_TOKEN`` / ``_estimate_tokens``)
so report weights agree with ``cxt_groups`` budgets.

Bucket model: ``{name, tokens, children?}``. A leaf omits ``children``. At every
bucket with children, if ``tokens - Σ(child.tokens) > 0`` a final ``etc`` child
carries the remainder. Grouping buckets define ``tokens = Σ(children)`` (etc 0);
arc42 file buckets carry the whole-file weight and split into ``#`` sections,
where ``etc`` = the unsectioned preamble + rounding — the one place the invariant
does real work. Source-file buckets partition the file's characters into the
five leaves, which sum bottom-up (etc 0).

Structure per ``docex_report_design.md § Docs → Summarizing Metrics and Data``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from docex.docs.linkmap import (
    _CHARS_PER_TOKEN,
    load_code_level_graph,
)
from docex.report.lint import lint_file

# --- token estimation -------------------------------------------------------


def _weight(chars: int) -> int:
    """Token weight of a character span, using linkmap's divisor (SC5). No
    ``max(1, …)`` — a sub-portion may legitimately round to zero tokens."""
    return round(chars / _CHARS_PER_TOKEN)


# --- bucket type ------------------------------------------------------------


@dataclass
class Bucket:
    name: str
    tokens: int
    children: "list[Bucket] | None" = None

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "tokens": self.tokens}
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


def _finalize(name: str, own_tokens: int, children: "list[Bucket]") -> Bucket:
    """Attach an ``etc`` child for the remainder when children under-sum."""
    kids = list(children)
    remainder = own_tokens - sum(c.tokens for c in kids)
    if remainder > 0:
        kids.append(Bucket("etc", remainder))
    return Bucket(name, own_tokens, kids or None)


def _group(name: str, children: "list[Bucket]") -> Bucket:
    """A grouping bucket whose own weight is the sum of its children."""
    return _finalize(name, sum(c.tokens for c in children), children)


# --- arc42 section splitting ------------------------------------------------

import re as _re

_H1 = _re.compile(r"^#\s+(.*)$")
_FENCE = _re.compile(r"^\s*(```|~~~)")


def _split_sections(text: str) -> "tuple[int, list[tuple[str, int]]]":
    """Return (preamble_chars, [(section_name, chars), …]).

    Splits on level-1 (``#``) headings, fence-aware so a ``#`` inside a fenced
    code block is not a heading. Content before the first heading is preamble.
    Sections keep document order.
    """
    in_fence = False
    preamble = 0
    sections: list[list] = []
    for line in text.splitlines(keepends=True):
        is_fence = bool(_FENCE.match(line))
        is_h1 = (not in_fence) and bool(_H1.match(line))
        if is_fence:
            in_fence = not in_fence
        if is_h1:
            name = _H1.match(line).group(1).strip()
            sections.append([name, len(line)])
        elif sections:
            sections[-1][1] += len(line)
        else:
            preamble += len(line)
    return preamble, [(n, c) for n, c in sections]


def _arc42_bucket(name: str, abs_path: Path, file_tokens: int) -> Bucket:
    try:
        text = abs_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    _preamble, sections = _split_sections(text)
    kids = [Bucket(sec, _weight(chars)) for sec, chars in sections]
    own = max(file_tokens, sum(k.tokens for k in kids))
    return _finalize(name, own, kids)


# --- design-doc tree --------------------------------------------------------

_ARC42 = (
    "boundary_conditions.md",
    "concepts_and_decisions.md",
    "structures_and_views.md",
)
_STD_TOP = {
    "boundary_conditions.md",
    "concepts_and_decisions.md",
    "structures_and_views.md",
    "project_diagram.mmd",
    "service_diagram.mmd",
    "adr_index.md",
    "adr_active.md",
    "lexicon.md",
}


def build_design_tree(design_nodes, project_root) -> Bucket:
    """Build the design-doc bucket tree from the graph's ``design`` nodes."""
    project_root = Path(project_root)
    tok = {n.fpath: (n.tokens or 0) for n in design_nodes}
    rels = {
        n.fpath: n.fpath[len("plans/design/"):]
        for n in design_nodes
        if n.fpath.startswith("plans/design/")
    }

    def leaf(fp: str, name: str) -> Bucket:
        return Bucket(name, tok[fp])

    top = {fp: rel for fp, rel in rels.items() if "/" not in rel}
    specifics_l1 = sorted(
        fp for fp, rel in rels.items() if rel.startswith("specifics/")
    )
    adrs = sorted(fp for fp, rel in rels.items() if rel.startswith("adrs/"))
    l2 = [n for n in design_nodes if n.level == "L2"]
    l3 = [n for n in design_nodes if n.level == "L3"]

    # -- L1 Standard Roots --
    roots_kids: list[Bucket] = []
    for f in _ARC42:
        fp = f"plans/design/{f}"
        if fp in tok:
            roots_kids.append(_arc42_bucket(f, project_root / fp, tok[fp]))
    diag = [
        leaf(f"plans/design/{f}", f)
        for f in ("project_diagram.mmd", "service_diagram.mmd")
        if f"plans/design/{f}" in tok
    ]
    if diag:
        roots_kids.append(_group("Diagrams", diag))
    idx = [
        leaf(f"plans/design/{f}", f)
        for f in ("adr_index.md", "adr_active.md")
        if f"plans/design/{f}" in tok
    ]
    if idx:
        roots_kids.append(_group("ADR Indices", idx))
    if "plans/design/lexicon.md" in tok:
        roots_kids.append(leaf("plans/design/lexicon.md", "lexicon.md"))

    # -- L1 Detail Docs --
    detail_kids: list[Bucket] = []
    if specifics_l1:
        detail_kids.append(
            _group("specifics", [leaf(fp, Path(fp).name) for fp in specifics_l1])
        )
    for f in ("quality_scenarios.md", "unknowns.md"):
        fp = f"plans/design/{f}"
        if fp in tok:
            detail_kids.append(leaf(fp, f))
    named_top = _STD_TOP | {"quality_scenarios.md", "unknowns.md"}
    other_top = sorted(fp for fp, rel in top.items() if rel not in named_top)
    if other_top:
        detail_kids.append(
            _group("Other Files", [leaf(fp, Path(fp).name) for fp in other_top])
        )

    # -- L2 Architecture Docs (name form "<cb>/filename") --
    def cbname(fp: str) -> str:
        rel = rels[fp]
        return f"{rel.split('/', 1)[0]}/{Path(fp).name}"

    md_diagrams, l2_specifics, l2_other = [], [], []
    for n in l2:
        rel = rels[n.fpath]
        sub = rel.split("/", 1)[1] if "/" in rel else ""
        if sub == "module_diagram.mmd":
            md_diagrams.append(n.fpath)
        elif sub.startswith("specifics/"):
            l2_specifics.append(n.fpath)
        else:
            l2_other.append(n.fpath)
    l2_kids: list[Bucket] = []
    if md_diagrams:
        l2_kids.append(
            _group(
                "Module Diagrams",
                [leaf(fp, cbname(fp)) for fp in sorted(md_diagrams)],
            )
        )
    if l2_specifics:
        l2_kids.append(
            _group(
                "specifics", [leaf(fp, cbname(fp)) for fp in sorted(l2_specifics)]
            )
        )
    if l2_other:
        l2_kids.append(
            _group(
                "Other Files", [leaf(fp, cbname(fp)) for fp in sorted(l2_other)]
            )
        )

    # -- L3 Module Docs (per codebase folder) --
    by_cb: dict[str, list[str]] = {}
    for n in l3:
        by_cb.setdefault(n.codebase, []).append(n.fpath)
    l3_kids: list[Bucket] = []
    for cb in sorted(by_cb):
        files = sorted(by_cb[cb])
        l3_kids.append(
            _group(cb, [leaf(fp, f"{cb}/{Path(fp).name}") for fp in files])
        )

    # -- Assemble primaries --
    primaries: list[Bucket] = []
    if roots_kids:
        primaries.append(_group("L1 Standard Roots", roots_kids))
    if detail_kids:
        primaries.append(_group("L1 Detail Docs", detail_kids))
    if l2_kids:
        primaries.append(_group("L2 Architecture Docs", l2_kids))
    if l3_kids:
        primaries.append(_group("L3 Module Docs", l3_kids))
    if adrs:
        primaries.append(Bucket("ADRs", sum(tok[fp] for fp in adrs)))

    return _finalize("Design Docs", sum(p.tokens for p in primaries), primaries)


# --- source-code tree -------------------------------------------------------

_LEAF_ORDER = (
    ("inline comments", "inline_comments"),
    ("docstrings", "docstrings"),
    ("references", "references"),
    ("code", "code"),
    ("other / unlintable", "other"),
)


def _file_bucket(node, project_root: Path) -> Bucket:
    counts = lint_file(project_root / node.fpath)
    leaves = [Bucket(label, _weight(counts[key])) for label, key in _LEAF_ORDER]
    own = sum(l.tokens for l in leaves)
    return Bucket(Path(node.fpath).name, own, leaves)


def build_source_tree(source_nodes, project_root) -> Bucket:
    """Build the source-code bucket tree from the graph's ``source`` nodes."""
    project_root = Path(project_root)
    by_cb: dict[str, dict[str, list]] = {}
    for n in source_nodes:
        by_cb.setdefault(n.codebase, {}).setdefault(n.module, []).append(n)

    cb_buckets: list[Bucket] = []
    for cb in sorted(by_cb):
        mods = by_cb[cb]
        nonhex = set(mods) == {"none"}
        child_buckets: list[Bucket] = []
        for mod in sorted(mods):
            files = sorted(mods[mod], key=lambda x: x.fpath)
            file_buckets = [_file_bucket(n, project_root) for n in files]
            if nonhex:
                child_buckets.extend(file_buckets)
            else:
                mod_name = mod if mod != "none" else "(root)"
                child_buckets.append(_group(mod_name, file_buckets))
        cb_buckets.append(_group(cb, child_buckets))

    return _group("Source Code", cb_buckets)


# --- top-level assembly + command ------------------------------------------


def build_docs_data(nodes, project_root) -> dict:
    """Assemble the full ``data`` document from a linkmap graph's nodes."""
    design_nodes = [n for n in nodes if n.type == "design"]
    source_nodes = [n for n in nodes if n.type == "source"]
    return {
        "report": "docs",
        "format": "data",
        "estimator": {
            "name": "chars_per_token",
            "chars_per_token": _CHARS_PER_TOKEN,
        },
        "design_docs": build_design_tree(design_nodes, project_root).to_dict(),
        "source_code": build_source_tree(source_nodes, project_root).to_dict(),
    }


def render_data_json(doc: dict) -> str:
    """Deterministic, sorted JSON (mirrors linkmap's rendering discipline)."""
    return json.dumps(doc, indent=2, sort_keys=True)


def run_report_docs(ctx, fmt: str) -> int:
    """``docex report docs [--format data|full]`` — print the report.

    ``data`` emits the bucketed JSON. ``full`` (Mod 177) is not yet implemented;
    until it lands it stubs to ``data`` behind a stderr note.
    """
    from docex.orchestrate._common import codebases

    if fmt == "full":
        # TODO(mod 177): render a self-contained HTML report (treemaps).
        print(
            "docex report docs: --format full is not implemented yet "
            "(mod 177); emitting --format data.",
            file=sys.stderr,
        )
        fmt = "data"

    cbs = codebases(ctx)
    nodes, _edges = load_code_level_graph(ctx.project_root, cbs)
    doc = build_docs_data(nodes, ctx.project_root)
    print(render_data_json(doc))
    return 0

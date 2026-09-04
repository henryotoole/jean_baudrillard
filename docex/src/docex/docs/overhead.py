"""``docex docs overhead <file>`` — a subject file's structural overhead.

Consumes the ``code_level`` linkmap (so source subjects and their emergent
module-doc edges resolve) and returns the higher/adjacent design docs that
should be in context to make informed edits to the subject. Best-guess, *not*
exhaustive (design § overhead). Overhead is always **design docs only** — a
target that is a ``source`` or ``neither`` node is never overhead.

The three rules (verbatim from ``docex_doc_design.md § overhead``):
  1. All L1 root docs — the standard arc42 files + all standard diagrams.
  2. Any L1/L2/L3 doc the subject directly links to (any ``link_type``, which
     folds the emergent source→module-doc edge into rule 2 — see
     ``overview.md`` Interpretation call).
  3. For a source file with a corresponding module doc, any L1/L2/L3 doc the
     module doc directly links to.

The pure core (``compute_overhead`` / ``outgoing_design_targets``) takes the
already-built ``(nodes, edges)`` graph so it is unit-testable without git or a
``ProjectContext``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from docex.context import ProjectContext
from docex.docs.check import _ROOT_NAMES
from docex.docs.linkmap import Node, load_code_level_graph

# High→low abstraction ordering rank. All overhead is design (L1/L2/L3), so
# `C`/None never occur; the fallback keeps the sort total regardless.
_LEVEL_RANK = {"L1": 0, "L2": 1, "L3": 2}


def outgoing_design_targets(nodes, edges, subject_fpath) -> set[str]:
    """fpaths of design nodes the subject links to via an OUTGOING edge of
    ANY link_type (markdown, mermaid_click, OR emergent).

    An edge contributes subject→other when (subject==a and direction in
    {a_to_b, both}) or (subject==b and direction in {b_to_a, both}). Only
    targets whose node type == "design" are returned. Folding in the emergent
    link_type is deliberate: it is what makes a source file's module doc part
    of its overhead (overview § overhead, rule-2 interpretation).
    """
    by_fpath = {n.fpath: n for n in nodes}
    out: set[str] = set()
    for e in edges:
        target: str | None = None
        if e.a == subject_fpath and e.direction in ("a_to_b", "both"):
            target = e.b
        elif e.b == subject_fpath and e.direction in ("b_to_a", "both"):
            target = e.a
        if target is None:
            continue
        node = by_fpath.get(target)
        if node is not None and node.type == "design":
            out.add(target)
    return out


def _rule_one_roots(nodes) -> set[str]:
    """The always-loadable L1 roots + all standard diagrams present as nodes.

    Reuses ``check._ROOT_NAMES`` (the reachability roots: the arc42 L1 files,
    lexicon, the project/service diagrams, and the two ADR indices) mapped to
    ``plans/design/<name>`` fpaths, plus every standard ``module_diagram.mmd``
    design node. Only nodes that actually exist as ``design`` nodes are kept.
    """
    by_fpath = {n.fpath: n for n in nodes}
    roots: set[str] = set()
    for name in _ROOT_NAMES:
        fp = f"plans/design/{name}"
        node = by_fpath.get(fp)
        if node is not None and node.type == "design":
            roots.add(fp)
    for n in nodes:
        if (
            n.type == "design"
            and n.is_standard
            and n.fpath.endswith("/module_diagram.mmd")
        ):
            roots.add(n.fpath)
    return roots


def compute_overhead(nodes, edges, subject_fpath) -> list[Node]:
    """The subject's structural overhead per the three rules. Pure.

    Returns Node objects (design nodes only), ordered high→low abstraction
    (L1<L2<L3 rank) then fpath. Excludes the subject itself.
    """
    by_fpath = {n.fpath: n for n in nodes}
    subject = by_fpath.get(subject_fpath)

    fpaths: set[str] = set()

    # Rule 1 — L1 roots + standard diagrams.
    fpaths |= _rule_one_roots(nodes)

    # Rule 2 — design docs the subject directly links to (incl. emergent).
    rule2 = outgoing_design_targets(nodes, edges, subject_fpath)
    fpaths |= rule2

    # Rule 3 — for a source subject with a module doc, the module doc's links.
    if subject is not None and subject.type == "source":
        module_doc = _module_doc_fpath(by_fpath, rule2, subject)
        if module_doc is not None:
            fpaths |= outgoing_design_targets(nodes, edges, module_doc)

    # Exclude the subject itself; resolve to nodes; order high→low then fpath.
    fpaths.discard(subject_fpath)
    resolved = [by_fpath[fp] for fp in fpaths if fp in by_fpath]
    resolved.sort(key=lambda n: (_LEVEL_RANK.get(n.level, 3), n.fpath))
    return resolved


def _module_doc_fpath(by_fpath, rule2_targets, subject) -> str | None:
    """The subject source node's module doc, as a rule-2 target fpath.

    ``build_linkmap`` only emits the emergent edge when the module doc exists
    as a scanned design node, so a source subject with a module doc already has
    it among ``rule2_targets``. We identify it by node metadata: a design L3
    node whose ``codebase``/``module`` match the subject.
    """
    for fp in rule2_targets:
        node = by_fpath.get(fp)
        if (
            node is not None
            and node.type == "design"
            and node.level == "L3"
            and node.codebase == subject.codebase
            and node.module == subject.module
        ):
            return fp
    return None


def render_overhead_json(subject_fpath, overhead_nodes) -> str:
    """Render ``{subject, overhead:[…]}`` as deterministic JSON.

    ``sort_keys=True`` sorts object keys only; the overhead list keeps its
    high→low abstraction order as built by ``compute_overhead``.
    """
    doc = {
        "subject": subject_fpath,
        "overhead": [
            {
                "fpath": n.fpath,
                "level": n.level,
                "codebase": n.codebase,
                "module": n.module,
                "is_standard": n.is_standard,
                "tokens": n.tokens,
            }
            for n in overhead_nodes
        ],
    }
    return json.dumps(doc, indent=2, sort_keys=True)


def _normalize_fpath(project_root: Path, file: str) -> str:
    """Normalize ``file`` to a project-relative POSIX fpath (mirrors
    ``linkmap._fpath``). Accepts either a path relative to ``project_root`` or
    an already-relative fpath; both resolve against ``project_root``."""
    abs_path = (Path(project_root) / file).resolve()
    return Path(os.path.relpath(abs_path, project_root)).as_posix()


def run_docs_overhead(ctx: ProjectContext, file: str) -> int:
    """``docex docs overhead <file>`` — print the subject's overhead as JSON.

    ``file`` is a project-relative path to a design doc or source file; it must
    be an in-scope ``design``/``source`` node of the ``code_level`` graph.

    Args:
        ctx: the loaded project context (yields project root + codebases).
        file: project-relative path to the subject design/source file.

    Errors:
        A ``file`` that is not an in-scope design/source node → a diagnostic on
        stderr and exit 1.

    Returns:
        0 on success (JSON written to stdout); 1 on the not-a-node error.
    """
    from docex.orchestrate._common import codebases

    project_root = ctx.project_root
    cbs = codebases(ctx)
    nodes, edges = load_code_level_graph(project_root, cbs)

    subject_fpath = _normalize_fpath(project_root, file)
    by_fpath = {n.fpath: n for n in nodes}
    node = by_fpath.get(subject_fpath)
    if node is None or node.type not in ("design", "source"):
        print(
            f"docex docs overhead: {file} is not an in-scope design/source "
            f"file",
            file=sys.stderr,
        )
        return 1

    overhead = compute_overhead(nodes, edges, subject_fpath)
    print(render_overhead_json(subject_fpath, overhead))
    return 0

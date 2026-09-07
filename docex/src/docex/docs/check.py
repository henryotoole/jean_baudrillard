"""``docex docs check`` — missing-standard-file + reachability (orphan) checks.

The reachability algorithm is docs.md's / research.md's: enumerate every file
under ``plans/design``, build the link graph rooted at the arc42 files + the
standard diagrams (+ lexicon + the two ADR indices), and flag anything a root
can't reach. No per-doc frontmatter.

Both checks are exposed as pure functions so the standalone command AND the
``docex check`` gate call the same code.
"""

from __future__ import annotations

from pathlib import Path

from docex.context import ProjectContext
from docex.docs.adr import adr_index_drift
from docex.docs.linkmap import (
    _MD_LINK,
    _MMD_CLICK,
    _SCHEME,
    _enumerate_design_files,
    _tagged_links_in,
    anchors_in,
    build_linkmap,
    fragment_links_in,
)
from docex.docs.standard_set import resolve

# The three link regexes now live in linkmap.py (check's reachability is built
# on the linkmap); re-exported here so existing importers keep working.
__all__ = [
    "_MD_LINK",
    "_MMD_CLICK",
    "_SCHEME",
    "check_docs",
    "design_root_exists",
    "missing_standard_files",
    "run_docs_check",
    "unreachable_docs",
    "unresolved_anchors",
]

# Reachability roots — the always-loadable top-level entry set (docs.md § LLM
# Agent Usage). Per-codebase module_diagram.mmd files are added in code.
_ROOT_NAMES = (
    "lexicon.md",
    "boundary_conditions.md",
    "concepts_and_decisions.md",
    "structures_and_views.md",
    "project_diagram.mmd",
    "service_diagram.mmd",
    "adr_index.md",
    "adr_active.md",
)


def _design_root(project_root: Path) -> Path:
    return project_root / "plans" / "design"


def design_root_exists(project_root: Path) -> bool:
    return _design_root(project_root).is_dir()


def missing_standard_files(
    project_root: Path, codebase_names: list[str]
) -> list[str]:
    """Non-optional standard entries that don't exist (right kind)."""
    plans = project_root / "plans"
    problems: list[str] = []
    for entry in resolve(codebase_names):
        if entry.optional:
            continue
        target = plans / entry.rel_path
        if entry.kind == "dir":
            if not target.is_dir():
                problems.append(
                    f"missing standard directory: plans/{entry.rel_path}"
                )
        else:
            if not target.is_file():
                problems.append(
                    f"missing standard file: plans/{entry.rel_path}"
                )
    return problems


def _links_in(path: Path) -> list[Path]:
    """Resolved link targets referenced by a design file (md + mermaid-click).

    A thin wrapper over the linkmap's tagged extractor — the shared link
    primitive — kept so any external caller/test of this name is untouched.
    """
    return [target for target, _ in _tagged_links_in(path)]


def unreachable_docs(
    project_root: Path, codebase_names: list[str]
) -> list[str]:
    """Files under plans/design not reachable from any standard root.

    Built on the ``design_docs`` linkmap so the reachability check and the
    ``docex docs linkmap`` command share ONE graph. The returned problem
    strings are byte-for-byte the historical format.
    """
    base = _design_root(project_root)
    if not base.is_dir():
        return []

    design_files = _enumerate_design_files(project_root)

    nodes, edges = build_linkmap(
        project_root, codebase_names, "design_docs", design_files, []
    )
    node_type = {n.fpath: n.type for n in nodes}

    # Directed adjacency derived from the merged edges: an edge contributes
    # a→b when direction ∈ {a_to_b, both} and b→a when ∈ {b_to_a, both}.
    adjacency: dict[str, set[str]] = {}
    for e in edges:
        if e.direction in ("a_to_b", "both"):
            adjacency.setdefault(e.a, set()).add(e.b)
        if e.direction in ("b_to_a", "both"):
            adjacency.setdefault(e.b, set()).add(e.a)

    # Roots: the standard top-level entry set + each codebase's module diagram,
    # expressed as project-relative fpaths.
    roots: list[str] = []
    for name in _ROOT_NAMES:
        f = base / name
        if f.is_file():
            roots.append((base / name).relative_to(project_root).as_posix())
    for cb in codebase_names:
        f = base / cb / "module_diagram.mmd"
        if f.is_file():
            roots.append(f.relative_to(project_root).as_posix())

    reachable: set[str] = set()
    queue: list[str] = list(roots)
    while queue:
        cur = queue.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt in adjacency.get(cur, ()):
            # Follow only edges to in-scope design nodes.
            if node_type.get(nxt) == "design" and nxt not in reachable:
                queue.append(nxt)

    orphan_rels = sorted(
        fp[len("plans/design/"):]
        for fp, t in node_type.items()
        if t == "design" and fp not in reachable
    )
    return [
        f"unreachable doc: plans/design/{rel} "
        f"(not linked from any standard doc or diagram)"
        for rel in orphan_rels
    ]


def unresolved_anchors(
    project_root: Path, codebase_names: list[str]
) -> list[str]:
    """Fragment links whose ``#anchor`` does not resolve in the target doc.

    For every markdown link in a design doc carrying a ``#fragment`` whose target
    is an IN-SCOPE design doc (same-file ``#frag`` included), the fragment must be
    a heading slug or an explicit ``<a id>`` anchor in that target. Reachability
    validates that a file is *linked*, never that a fragment *resolves*; this is
    the class it cannot see (a reworded / de-emoji'd heading, cross-file anchor
    drift).

    Scope (deliberate, not accidental): a ``#fragment`` whose target is NOT an
    in-scope design doc — a ``references/*`` file, a source file, an out-of-tree
    path, or any target the design enumeration does not scan — is NOT validated
    and NOT failed. The check only asserts anchors whose definitions it can see.

    Built on the shared design enumeration and the linkmap's link/anchor
    primitives — no second walker.
    """
    base = _design_root(project_root)
    if not base.is_dir():
        return []
    design_files = _enumerate_design_files(project_root)
    rel_by_resolved = {
        p.resolve(): p.relative_to(project_root).as_posix()
        for p in design_files
    }
    in_scope = set(rel_by_resolved)
    anchor_cache: dict[Path, set[str]] = {}

    def _anchors(target: Path) -> set[str]:
        if target not in anchor_cache:
            anchor_cache[target] = anchors_in(target)
        return anchor_cache[target]

    problems: list[str] = []
    for p in design_files:
        src_rel = p.relative_to(project_root).as_posix()
        for target_abs, frag in fragment_links_in(p):
            if target_abs not in in_scope:
                continue  # target not scanned -> fragment not validated (docstring)
            if frag not in _anchors(target_abs):
                tgt_rel = rel_by_resolved[target_abs]
                problems.append(
                    f"unresolved anchor: {src_rel} -> {tgt_rel}#{frag}"
                )
    return sorted(problems)


def check_docs(project_root: Path, codebase_names: list[str]) -> int:
    """Run the four checks; print a report; return 0 (clean) or 1 (problems)."""
    if not design_root_exists(project_root):
        print(
            "docex docs check: no plans/design/ — skipped "
            "(run `docex docs scaffold` to create the design-doc set)."
        )
        return 0
    problems = (
        missing_standard_files(project_root, codebase_names)
        + unreachable_docs(project_root, codebase_names)
        + unresolved_anchors(project_root, codebase_names)
        + adr_index_drift(project_root)
    )
    if not problems:
        print(
            "docex docs check: OK — standard files present and all docs "
            "reachable."
        )
        return 0
    print("docex docs check: FAILED")
    for prob in problems:
        print(f"  - {prob}")
    return 1


def run_docs_check(ctx: ProjectContext) -> int:
    from docex.orchestrate._common import codebases

    return check_docs(ctx.project_root, codebases(ctx))

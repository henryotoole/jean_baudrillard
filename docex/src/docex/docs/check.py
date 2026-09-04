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
    _tagged_links_in,
    build_linkmap,
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

    design_files: list[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part.startswith(".") for part in rel.parts):
            continue  # skip .gitkeep and anything under a dot-dir
        design_files.append(p)

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


def check_docs(project_root: Path, codebase_names: list[str]) -> int:
    """Run both checks; print a report; return 0 (clean) or 1 (problems)."""
    if not design_root_exists(project_root):
        print(
            "docex docs check: no plans/design/ — skipped "
            "(run `docex docs scaffold` to create the design-doc set)."
        )
        return 0
    problems = (
        missing_standard_files(project_root, codebase_names)
        + unreachable_docs(project_root, codebase_names)
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

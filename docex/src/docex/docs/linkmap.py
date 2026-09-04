"""``docex docs linkmap <depth>`` — emit the doc/code link graph as JSON.

The linkmap is the single source of truth for the documentation link graph:
``docs check``'s reachability (orphan) test consumes the ``design_docs`` graph
this module builds, and outside agents/skills consume the emitted JSON.

Two depths:

* ``design_docs`` — the tracked scope is ``plans/design/**`` only.
* ``code_level`` — ``plans/design/**`` plus each codebase's git-tracked
  ``core/<cb>/src/**`` (a strict superset).

``build_linkmap`` is deliberately **pure and git-free** — it accepts the
already-enumerated ``design_files`` / ``source_files`` lists so it is unit
testable without touching a repo. All git I/O (the ``code_level`` source
enumeration) lives in ``run_docs_linkmap``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from docex.context import ProjectContext
from docex.docs.standard_set import resolve

# The three link-extraction primitives live here; check.py imports them, since
# its reachability is now built on top of the linkmap.
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_MMD_CLICK = re.compile(
    r'^\s*click\s+\S+\s+(?:href\s+|call\s+)?"([^"]+)"', re.MULTILINE
)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass(frozen=True)
class Node:
    fpath: str            # project-relative POSIX; the node key
    type: str             # "design" | "source" | "neither"
    is_standard: bool
    level: str | None     # "L1" | "L2" | "L3" | "C" | None
    codebase: str         # "<cb>" | "none"
    module: str           # "<module>" | "none"
    tokens: int | None    # None for "neither"


@dataclass(frozen=True)
class Edge:
    a: str                # min(fpath1, fpath2) lexicographically
    b: str                # max(...)
    link_type: str        # "markdown" | "mermaid_click" | "emergent"
    direction: str        # "a_to_b" | "b_to_a" | "both"


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------


def _resolve_link(path: Path, raw: str) -> Path | None:
    """Resolve one raw link target relative to the linking file.

    Returns None for external (scheme-bearing) links and unresolvable
    targets, matching the guards ``_links_in`` has always applied.
    """
    raw = raw.strip().split("#", 1)[0].strip()  # drop anchor
    if not raw or _SCHEME.match(raw):
        return None
    try:
        return (path.parent / raw).resolve()
    except (OSError, ValueError):
        return None


def _tagged_links_in(path: Path) -> list[tuple[Path, str]]:
    """Resolved link targets referenced by a file, each tagged with its kind.

    Returns ``(resolved_abs_target, link_type)`` where ``link_type`` is
    ``"markdown"`` (inline ``[text](target)``) or ``"mermaid_click"`` (a
    mermaid ``click … "target"`` directive, in both ``.mmd`` files and fenced
    mermaid blocks inside ``.md``). This is ``check._links_in`` split by which
    regex matched.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[tuple[Path, str]] = []
    for raw in _MD_LINK.findall(text):
        resolved = _resolve_link(path, raw)
        if resolved is not None:
            out.append((resolved, "markdown"))
    for raw in _MMD_CLICK.findall(text):
        resolved = _resolve_link(path, raw)
        if resolved is not None:
            out.append((resolved, "mermaid_click"))
    return out


# ---------------------------------------------------------------------------
# Classification (pure, path-based)
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Estimate the LLM context cost of reading ``text``.

    The standard ~4-chars-per-token heuristic. Deterministic; no dependency
    (deliberately avoids ``tiktoken``, which would be new infrastructure).
    """
    return max(1, round(len(text) / 4))


def _fpath(project_root: Path, abs_path: Path) -> str:
    """Project-relative POSIX path — the node key. A target outside the
    project root yields an ``os.path.relpath`` ``../``-style path."""
    return Path(os.path.relpath(abs_path, project_root)).as_posix()


def _standard_file_rels(codebase_names: list[str]) -> set[str]:
    """The ``plans/``-relative posix paths of the standard **file** entries."""
    return {e.rel_path for e in resolve(codebase_names) if e.kind == "file"}


def _hex_cb_module(
    project_root: Path, abs_path: Path, codebase_names: list[str]
) -> tuple[str | None, str | None]:
    """Parse ``core/<cb>/src/hex/<module>/**`` → ``(<cb>, <module>)``.

    Returns ``(None, None)`` when the path is not a hex-module source file.
    """
    rel = Path(os.path.relpath(abs_path, project_root / "core")).as_posix()
    parts = rel.split("/")
    if (
        len(parts) >= 5
        and parts[0] in codebase_names
        and parts[1] == "src"
        and parts[2] == "hex"
    ):
        return parts[0], parts[3]
    return None, None


def _classify(
    project_root: Path,
    codebase_names: list[str],
    abs_path: Path,
    node_type: str,
    standard_rels: set[str],
    tokens: int | None,
) -> Node:
    """Build a fully-classified ``Node`` for a scanned file of known type.

    ``type`` is passed in because it is depth-relative (a scanned design file
    is ``design``, a scanned source file is ``source``); the remaining fields
    are derived purely from the path.
    """
    fpath = _fpath(project_root, abs_path)

    if node_type == "source":
        cb, module = _hex_cb_module(project_root, abs_path, codebase_names)
        rel_core = Path(
            os.path.relpath(abs_path, project_root / "core")
        ).as_posix()
        codebase = rel_core.split("/")[0]
        return Node(
            fpath=fpath,
            type="source",
            is_standard=False,
            level="C",
            codebase=codebase,
            module=module or "none",
            tokens=tokens,
        )

    # node_type == "design"
    plans_rel = Path(
        os.path.relpath(abs_path, project_root / "plans")
    ).as_posix()
    is_standard = plans_rel in standard_rels

    rel_design = Path(
        os.path.relpath(abs_path, project_root / "plans" / "design")
    ).as_posix()
    parts = rel_design.split("/")
    codebase = "none"
    module = "none"
    if len(parts) >= 2 and parts[0] in codebase_names:
        codebase = parts[0]
        if len(parts) >= 3 and parts[1] == "module":
            level = "L3"
            module = Path(parts[2]).stem
        else:
            level = "L2"
    else:
        level = "L1"

    return Node(
        fpath=fpath,
        type="design",
        is_standard=is_standard,
        level=level,
        codebase=codebase,
        module=module,
        tokens=tokens,
    )


# ---------------------------------------------------------------------------
# Graph builder (pure — the testable core)
# ---------------------------------------------------------------------------


def _merge_directions(
    directed: set[tuple[str, str, str]],
) -> list[Edge]:
    """Collapse raw directed links into undirected edges with a direction.

    Reciprocal links of the **same** link_type merge to ``direction="both"``;
    a lone link becomes ``a_to_b`` / ``b_to_a`` over the lexicographically
    ordered pair. Different link_types between the same pair stay distinct.
    """
    groups: dict[tuple[str, str, str], set[str]] = {}
    for frm, to, link_type in directed:
        a, b = (frm, to) if frm < to else (to, frm)
        key = (a, b, link_type)
        groups.setdefault(key, set()).add("fwd" if frm == a else "rev")
    edges: list[Edge] = []
    for (a, b, link_type), dirs in groups.items():
        if "fwd" in dirs and "rev" in dirs:
            direction = "both"
        elif "fwd" in dirs:
            direction = "a_to_b"
        else:
            direction = "b_to_a"
        edges.append(Edge(a=a, b=b, link_type=link_type, direction=direction))
    return edges


def build_linkmap(
    project_root: Path,
    codebase_names: list[str],
    depth: str,
    design_files: list[Path],
    source_files: list[Path],
) -> tuple[list[Node], list[Edge]]:
    """Build the doc/code link graph for a depth. Pure and git-free.

    ``design_files`` (both depths) and ``source_files`` (``code_level`` only)
    are absolute paths the caller has already enumerated. Returns
    ``(nodes, edges)`` sorted by ``fpath`` and ``(a, b, link_type)``.

    ``type`` is **depth-relative**: a scanned design file is ``design``, a
    scanned source file is ``source``, and any edge target outside the
    scanned scope is a ``neither`` stub (recorded so the edge is not lost, but
    never read — no tokens, no outgoing scan). Consequences: at
    ``design_docs`` a link to ``core/*/src`` is ``neither``; at ``code_level``
    a git-tracked source file is ``source``; a target outside
    ``plans/design ∪ core/*/src`` (e.g. ``doctrine/**``, ``README.md``,
    ``../foo``) is ``neither`` at BOTH depths; and an **untracked** file under
    ``core/*/src`` (absent from ``source_files``) is ``neither`` at
    ``code_level`` — this pins the git-tracked boundary.
    """
    project_root = Path(project_root)
    design_set = {p.resolve() for p in design_files}
    source_set = (
        {p.resolve() for p in source_files}
        if depth == "code_level"
        else set()
    )
    scanned = design_set | source_set
    standard_rels = _standard_file_rels(codebase_names)

    # -- nodes for every scanned file --------------------------------------
    nodes: dict[str, Node] = {}
    for p in sorted(scanned):
        node_type = "design" if p in design_set else "source"
        try:
            text = p.read_text(encoding="utf-8")
            tokens: int | None = _estimate_tokens(text)
        except (OSError, UnicodeDecodeError):
            tokens = _estimate_tokens("")
        node = _classify(
            project_root, codebase_names, p, node_type, standard_rels, tokens
        )
        nodes[node.fpath] = node

    # -- edges -------------------------------------------------------------
    directed: set[tuple[str, str, str]] = set()
    neither_targets: set[Path] = set()

    for p in sorted(scanned):
        from_fpath = _fpath(project_root, p)
        for target_abs, link_type in _tagged_links_in(p):
            if target_abs == p:
                continue
            to_fpath = _fpath(project_root, target_abs)
            if to_fpath == from_fpath:
                continue
            directed.add((from_fpath, to_fpath, link_type))
            if target_abs not in scanned:
                neither_targets.add(target_abs)

    # Emergent: a hex source file → its module doc, when that doc is a
    # scanned design node (design § Structurally-Emergent Links).
    for p in sorted(source_set):
        cb, module = _hex_cb_module(project_root, p, codebase_names)
        if cb is None or module is None:
            continue
        doc = (
            project_root / "plans" / "design" / cb / "module" / f"{module}.md"
        ).resolve()
        if doc in design_set:
            directed.add(
                (_fpath(project_root, p), _fpath(project_root, doc), "emergent")
            )

    # -- neither stub nodes for out-of-scope edge targets ------------------
    for target_abs in neither_targets:
        fp = _fpath(project_root, target_abs)
        if fp not in nodes:
            nodes[fp] = Node(
                fpath=fp,
                type="neither",
                is_standard=False,
                level=None,
                codebase="none",
                module="none",
                tokens=None,
            )

    edges = _merge_directions(directed)
    node_list = sorted(nodes.values(), key=lambda n: n.fpath)
    edge_list = sorted(edges, key=lambda e: (e.a, e.b, e.link_type))
    return node_list, edge_list


# ---------------------------------------------------------------------------
# JSON rendering + command entry
# ---------------------------------------------------------------------------


def render_linkmap_json(
    depth: str, nodes: list[Node], edges: list[Edge]
) -> str:
    """Render the graph as deterministic, sorted JSON.

    Mirrors ``describe --format llm``: ``indent=2, sort_keys=True`` with all
    lists already deterministically sorted by the builder.
    """
    doc = {
        "depth": depth,
        "nodes": [asdict(n) for n in nodes],
        "edges": [asdict(e) for e in edges],
    }
    return json.dumps(doc, indent=2, sort_keys=True)


def _enumerate_design_files(project_root: Path) -> list[Path]:
    """Every file under ``plans/design``, skipping dot-parts.

    Matches ``unreachable_docs``' enumeration exactly so the two share one
    view of the design scope.
    """
    base = project_root / "plans" / "design"
    if not base.is_dir():
        return []
    out: list[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part.startswith(".") for part in rel.parts):
            continue  # skip .gitkeep and anything under a dot-dir
        out.append(p)
    return out


def _resolve_tracked_source(
    git: object, project_root: Path, codebase_names: list[str]
) -> list[Path]:
    """Absolute paths of git-tracked ``core/<cb>/src`` files.

    ``git ls-files`` (default form) emits paths relative to ``cwd``, so with
    ``cwd=project_root`` the results are ``project_root``-relative and resolve
    via ``project_root / entry`` regardless of whether ``project_root`` is the
    repo root or a subfolder of it. A defensive under-``src`` filter keeps a
    surprising pathspec expansion from leaking foreign paths in.
    """
    project_root = Path(project_root).resolve()
    out: set[Path] = set()
    for cb in codebase_names:
        src_root = (project_root / "core" / cb / "src").resolve()
        for entry in git.ls_files(project_root, f"core/{cb}/src"):
            abs_path = (project_root / entry).resolve()
            try:
                abs_path.relative_to(src_root)
            except ValueError:
                continue
            if abs_path.is_file():
                out.add(abs_path)
    return sorted(out)


def run_docs_linkmap(ctx: ProjectContext, depth: str) -> int:
    """``docex docs linkmap <depth>`` — print the link graph as JSON to stdout.

    Diagnostics (if any) go to stderr; the JSON is the sole stdout content,
    emitted once, deterministic. Returns 0 (a well-formed empty graph is a
    success, not a failure).
    """
    import sys

    from docex.orchestrate._common import codebases

    project_root = ctx.project_root
    cbs = codebases(ctx)

    design_files = _enumerate_design_files(project_root)
    if not design_files and not (project_root / "plans" / "design").is_dir():
        print(
            "docex docs linkmap: no plans/design/ — emitting the "
            "in-scope graph (empty design scope).",
            file=sys.stderr,
        )

    source_files: list[Path] = []
    if depth == "code_level":
        from docex.git import SubprocessGitClient

        source_files = _resolve_tracked_source(
            SubprocessGitClient(), project_root, cbs
        )

    nodes, edges = build_linkmap(
        project_root, cbs, depth, design_files, source_files
    )
    print(render_linkmap_json(depth, nodes, edges))
    return 0

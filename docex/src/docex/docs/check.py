"""``docex docs check`` — missing-standard-file + reachability (orphan) checks.

The reachability algorithm is docs.md's / research.md's: enumerate every file
under ``plans/design``, build the link graph rooted at the arc42 files + the
standard diagrams (+ lexicon + the two ADR indices), and flag anything a root
can't reach. No per-doc frontmatter.

Both checks are exposed as pure functions so the standalone command AND the
``docex check`` gate call the same code.
"""

from __future__ import annotations

import re
from pathlib import Path

from docex.context import ProjectContext
from docex.docs.standard_set import resolve

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_MMD_CLICK = re.compile(
    r'^\s*click\s+\S+\s+(?:href\s+|call\s+)?"([^"]+)"', re.MULTILINE
)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

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
    """Resolved link targets referenced by a design file (md + mermaid-click)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    raws = _MD_LINK.findall(text)
    raws += _MMD_CLICK.findall(text)  # md files may embed mermaid blocks too
    out: list[Path] = []
    for raw in raws:
        raw = raw.strip().split("#", 1)[0].strip()  # drop anchor
        if not raw or _SCHEME.match(raw):
            continue
        try:
            out.append((path.parent / raw).resolve())
        except (OSError, ValueError):
            continue
    return out


def unreachable_docs(
    project_root: Path, codebase_names: list[str]
) -> list[str]:
    """Files under plans/design not reachable from any standard root."""
    base = _design_root(project_root)
    if not base.is_dir():
        return []

    all_files: set[Path] = set()
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part.startswith(".") for part in rel.parts):
            continue  # skip .gitkeep and anything under a dot-dir
        all_files.add(p.resolve())

    roots: list[Path] = []
    for name in _ROOT_NAMES:
        f = base / name
        if f.is_file():
            roots.append(f.resolve())
    for cb in codebase_names:
        f = base / cb / "module_diagram.mmd"
        if f.is_file():
            roots.append(f.resolve())

    reachable: set[Path] = set()
    queue: list[Path] = list(roots)
    while queue:
        cur = queue.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for tgt in _links_in(cur):
            if tgt in all_files and tgt not in reachable:
                queue.append(tgt)

    orphans = sorted(all_files - reachable)
    return [
        f"unreachable doc: plans/design/{p.relative_to(base).as_posix()} "
        f"(not linked from any standard doc or diagram)"
        for p in orphans
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

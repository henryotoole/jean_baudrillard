"""``docex docs scaffold`` — lay down the standard design-doc set, idempotently.

Never clobbers an existing file; creates only what is missing. Empty standard
directories get a ``.gitkeep`` so git (and the ``docex check`` worktree) keeps
them.
"""

from __future__ import annotations

from pathlib import Path

from docex.context import ProjectContext
from docex.docs.standard_set import resolve

# A freshly-scaffolded tree must pass its own `docs check`. The only mandatory,
# non-root file is unknowns.md, so concepts_and_decisions.md links to it here;
# every other mandatory file is a reachability root. Templates carry the
# doctrine's arc42 headers (docs.md § arc42) so the stubs are useful, not empty.
_MMD_STUB = 'graph TD\n    placeholder["(replace with the real diagram)"]\n'

_TEMPLATES: dict[str, str] = {
    "design/boundary_conditions.md": (
        "# Intro and Goals\n\n"
        "# Constraints\n\n"
        "# Context and Scope\n\n"
        "# Quality Requirements\n"
    ),
    "design/concepts_and_decisions.md": (
        "# Cross-Cutting Concepts\n\n"
        "# Solution Strategy\n\n"
        "# Risk, Unknowns, and Tech Debt\n\n"
        "Open unknowns are tracked in [unknowns.md](./unknowns.md).\n"
    ),
    "design/structures_and_views.md": (
        "# Building-Block View\n\n"
        "# Runtime View\n\n"
        "# Deployment View\n"
    ),
    "design/lexicon.md": "# Project Lexicon\n",
    "design/unknowns.md": (
        "# Unknowns\n\n"
        "| ID | Name | Description | Satisfying Record |\n"
        "| -- | ---- | ----------- | ----------------- |\n"
    ),
    "design/adr_index.md": (
        "# ADR Index\n\n"
        "| ADR ID | Title | Status | Date | Supersedes | Superseded By |\n"
        "| ------ | ----- | ------ | ---- | ---------- | ------------- |\n"
    ),
    "design/adr_active.md": (
        "# Active ADRs\n\n"
        "| ADR ID | Title | Date | Supersedes |\n"
        "| ------ | ----- | ---- | ---------- |\n"
    ),
    "design/project_diagram.mmd": _MMD_STUB,
    "design/service_diagram.mmd": _MMD_STUB,
}


def _template_for(rel_path: str) -> str:
    if rel_path in _TEMPLATES:
        return _TEMPLATES[rel_path]
    if rel_path.endswith("module_diagram.mmd"):
        return _MMD_STUB
    return ""


def scaffold_design(
    project_root: Path, codebase_names: list[str]
) -> list[str]:
    """Create every missing standard entry. Returns the created rel-paths."""
    plans = project_root / "plans"
    created: list[str] = []
    for entry in resolve(codebase_names):
        target = plans / entry.rel_path
        if entry.kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
            has_content = any(
                p.name != ".gitkeep" for p in target.iterdir()
            )
            gitkeep = target / ".gitkeep"
            if not has_content and not gitkeep.exists():
                gitkeep.write_text("")
                created.append(f"plans/{entry.rel_path}/.gitkeep")
        else:
            if entry.optional:
                continue  # never auto-create optional files
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_template_for(entry.rel_path))
                created.append(f"plans/{entry.rel_path}")
    return created


def run_docs_scaffold(ctx: ProjectContext) -> int:
    from docex.orchestrate._common import codebases

    created = scaffold_design(ctx.project_root, codebases(ctx))
    if created:
        print(f"docex docs scaffold: created {len(created)} item(s):")
        for rel in created:
            print(f"  + {rel}")
    else:
        print("docex docs scaffold: nothing to create — structure is complete.")
    return 0

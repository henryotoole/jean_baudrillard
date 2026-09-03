"""The single canonical definition of the standard design-doc set.

Consumed by both ``docex docs scaffold`` (what to lay down) and
``docex docs check`` (what must exist). Keeping ONE list is the whole point:
scaffold and check can never drift on "the standard set".

Paths are relative to ``plans/``. A ``{cb}`` placeholder in a codebase-scoped
entry is expanded once per ``infra.yml`` codebase at ``resolve()`` time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StandardEntry:
    path: str          # relative to plans/, may contain "{cb}"
    kind: str          # "file" | "dir"
    optional: bool
    scope: str         # "project" | "codebase"


@dataclass(frozen=True)
class ResolvedEntry:
    rel_path: str      # relative to plans/, fully expanded
    kind: str
    optional: bool


# L1 — project-scoped, always present (docs.md § Standard Documentation Structure).
_PROJECT_ENTRIES: tuple[StandardEntry, ...] = (
    StandardEntry("design/boundary_conditions.md", "file", False, "project"),
    StandardEntry("design/concepts_and_decisions.md", "file", False, "project"),
    StandardEntry("design/structures_and_views.md", "file", False, "project"),
    StandardEntry("design/lexicon.md", "file", False, "project"),
    StandardEntry("design/unknowns.md", "file", False, "project"),
    StandardEntry("design/adr_index.md", "file", False, "project"),
    StandardEntry("design/adr_active.md", "file", False, "project"),
    StandardEntry("design/project_diagram.mmd", "file", False, "project"),
    StandardEntry("design/service_diagram.mmd", "file", False, "project"),
    StandardEntry("design/doctrine_ext.md", "file", True, "project"),
    StandardEntry("design/quality_scenarios.md", "file", True, "project"),
    StandardEntry("design/adrs", "dir", False, "project"),
    StandardEntry("references", "dir", False, "project"),
    StandardEntry("product", "dir", True, "project"),
)

# L2 — codebase-scoped, one per infra.yml codebase.
_CODEBASE_ENTRIES: tuple[StandardEntry, ...] = (
    StandardEntry("design/{cb}/module_diagram.mmd", "file", False, "codebase"),
    StandardEntry("design/{cb}/module", "dir", False, "codebase"),
    StandardEntry("design/{cb}/specifics", "dir", False, "codebase"),
)

STANDARD_SET: tuple[StandardEntry, ...] = _PROJECT_ENTRIES + _CODEBASE_ENTRIES


def resolve(codebase_names: list[str]) -> list[ResolvedEntry]:
    """Expand the standard set against a project's codebases."""
    out: list[ResolvedEntry] = [
        ResolvedEntry(e.path, e.kind, e.optional) for e in _PROJECT_ENTRIES
    ]
    for cb in codebase_names:
        for e in _CODEBASE_ENTRIES:
            out.append(
                ResolvedEntry(e.path.replace("{cb}", cb), e.kind, e.optional)
            )
    return out

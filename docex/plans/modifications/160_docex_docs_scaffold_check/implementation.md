# Mod 160 — Implementation Steps

Work is entirely inside `docex/` (project root: `~/.claude/jean_baudrillard/docex`).
All paths below are relative to that root unless noted. Use absolute paths in tools.

Scope fence: edit `src/docex/**` and `tests/**` only (plus this mod folder, already
created). Do **not** edit `doctrine/`, `skills/`, `agents/`, or `plans/core/*`
(the masterplan row + changelog are handled by the mod driver, not here). Do **not**
bump `VERSION` / `pyproject.toml` / `__init__.py`.

---

## Step 1 — New package `src/docex/docs/`

Create `src/docex/docs/__init__.py`:

```python
"""``docex docs`` — scaffold and police the standard design-doc structure.

Both subcommands (and the ``docex check`` gate) share ONE definition of the
standard file set (``standard_set.py``) so scaffold and check cannot disagree.
"""

from __future__ import annotations

from docex.docs.check import (
    check_docs,
    design_root_exists,
    missing_standard_files,
    run_docs_check,
    unreachable_docs,
)
from docex.docs.scaffold import run_docs_scaffold, scaffold_design

__all__ = [
    "check_docs",
    "design_root_exists",
    "missing_standard_files",
    "unreachable_docs",
    "run_docs_check",
    "run_docs_scaffold",
    "scaffold_design",
]
```

Create `src/docex/docs/standard_set.py`:

```python
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
```

Create `src/docex/docs/scaffold.py`:

```python
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
```

Create `src/docex/docs/check.py`:

```python
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
```

---

## Step 2 — Dispatcher (`src/docex/__main__.py`)

1. In `_HELP_TEXT`, add:
   ```python
       "docs": "Scaffold or check the standard design-doc structure "
               "(scaffold/check).",
   ```
2. In `_GROUPS`, add a new group (append after `Configuration`):
   ```python
       ("Documentation", ("docs",)),
   ```
3. Add the handler function near the other command groups (e.g. after
   `_cmd_config`):
   ```python
   def _cmd_docs(args: list[str]) -> int:
       """``docex docs <scaffold|check>`` — scaffold or police the standard
       design-doc structure (docs.md § Standard Documentation Structure)."""
       parser = argparse.ArgumentParser(prog="docex docs", add_help=True)
       sub = parser.add_subparsers(dest="op", required=True)
       sub.add_parser(
           "scaffold",
           help="lay down the standard design-doc file set (idempotent)",
       )
       sub.add_parser(
           "check",
           help="validate the design-doc structure "
                "(missing-file + reachability)",
       )
       ns = parser.parse_args(args)

       from docex.context import load_project_context
       from docex.docs import run_docs_check, run_docs_scaffold

       ctx = load_project_context(Path(os.getcwd()))
       if ns.op == "scaffold":
           return run_docs_scaffold(ctx)
       if ns.op == "check":
           return run_docs_check(ctx)
       return 64  # unreachable — argparse requires a valid subcommand
   ```
4. In `_build_handler_table`, add (a new "# Documentation" comment block):
   ```python
       # Documentation
       "docs": _cmd_docs,
   ```

---

## Step 3 — Wire `docs check` into `docex check`

In `src/docex/pipeline/check.py`, add a gate function next to the other
`_gate_*` functions:

```python
def _gate_docs(
    worktree: Path,
    ctx: ProjectContext,
    report: CheckReport,
) -> None:
    """Blocking design-doc gates: standard files present + all docs reachable.

    Skips (PASS) when the worktree has no ``plans/design`` — the checks are
    anti-drift guards for an EXISTING design corpus, mirroring `_gate_contracts`
    skipping when there is no infra.yml. Inception scaffolds the tree at project
    birth; from then on these gates enforce it.
    """
    from docex.docs import (
        design_root_exists,
        missing_standard_files,
        unreachable_docs,
    )
    from docex.orchestrate._common import codebases

    if not design_root_exists(worktree):
        report.add("docs_standard_files", True, "no plans/design — skipped")
        report.add("docs_reachability", True, "no plans/design — skipped")
        return

    cbs = codebases(ctx)
    missing = missing_standard_files(worktree, cbs)
    report.add(
        "docs_standard_files",
        not missing,
        "all standard design docs present" if not missing
        else "; ".join(missing),
    )
    orphans = unreachable_docs(worktree, cbs)
    report.add(
        "docs_reachability",
        not orphans,
        "all design docs reachable" if not orphans else "; ".join(orphans),
    )
```

Then call it in `run_check`, immediately after the `_gate_codebase_scripts(...)`
line and before `_gate_observability_backend_url_reachable(...)`:

```python
        _gate_codebase_scripts(worktree, worktree_ctx, report)
        _gate_docs(worktree, worktree_ctx, report)
        _gate_observability_backend_url_reachable(worktree_ctx, report)
```

(`Path` and `ProjectContext` are already imported in this module.)

---

## Step 4 — Tests (`tests/unit/`, UNMARKED)

Keep everything under `tests/unit/` and add **no** `integration` marker — the
work crosses no docker/AWS/git boundary, and `test_collection_partition.py`
requires unit tests live under `tests/unit/`.

Create `tests/unit/test_docs_standard_set.py`:
- `resolve([])` returns exactly the project entries (assert the mandatory L1
  files are present; assert `product` is marked optional).
- `resolve(["api", "frontend"])` adds `design/api/module_diagram.mmd`,
  `design/api/module`, `design/api/specifics` and the same for `frontend`.

Create `tests/unit/test_docs_scaffold.py` (use `tmp_path` as project_root):
- `scaffold_design(tmp_path, ["api"])` then assert every non-optional resolved
  entry exists (files are files, dirs are dirs); optional files
  (`doctrine_ext.md`, `quality_scenarios.md`) do **not** exist; empty dirs
  contain a `.gitkeep`.
- Idempotency: write a sentinel string into
  `plans/design/lexicon.md`, run `scaffold_design` again, assert the sentinel is
  preserved (no clobber) and the second call reports nothing created.
- Freshly-scaffolded tree passes both checks:
  `missing_standard_files(tmp_path, ["api"]) == []` and
  `unreachable_docs(tmp_path, ["api"]) == []`.

Create `tests/unit/test_docs_check.py` (use `tmp_path`):
- **missing-file**: scaffold, then delete `plans/design/unknowns.md`; assert
  `missing_standard_files` names it. Delete `plans/design/api/module_diagram.mmd`
  (after scaffolding with `["api"]`) and assert it's named too.
- **optional not required**: scaffold; assert missing-file is empty even though
  `doctrine_ext.md` / `quality_scenarios.md` were never created.
- **skip-when-absent**: on a bare `tmp_path` (no plans/design),
  `design_root_exists` is False, `missing_standard_files`/`unreachable_docs`
  return `[]`, and `check_docs(tmp_path, [])` returns 0.
- **reachability orphan**: scaffold, add
  `plans/design/orphan.md` with some text that nothing links to; assert
  `unreachable_docs` names `plans/design/orphan.md`.
- **reachability via markdown link**: scaffold, create
  `plans/design/extra.md`, then append `[extra](./extra.md)` to
  `plans/design/structures_and_views.md` (a root); assert `unreachable_docs`
  is empty (extra.md now reachable).
- **reachability via mermaid click**: scaffold with `["api"]`, create
  `plans/design/api/module/orders.md`, then append a click line to
  `plans/design/api/module_diagram.mmd` (a root):
  `click orders "./module/orders.md"`; assert `unreachable_docs` is empty.
- **check_docs return code**: a tree with an orphan returns 1; a clean tree
  returns 0.

Create `tests/unit/test_docs_dispatcher.py`:
- `from docex.__main__ import _build_handler_table, _HELP_TEXT, _cmd_docs,
  _format_usage`.
- `_build_handler_table()` contains `"docs"`.
- `"docs" in _HELP_TEXT`; `"Documentation:"` appears in `_format_usage()`.
- `_cmd_docs(["scaffold"])` routes to `run_docs_scaffold` (monkeypatch
  `docex.docs.run_docs_scaffold` — note the dispatcher imports it from the
  `docex.docs` package, so patch the name **on that package**:
  `monkeypatch.setattr("docex.docs.run_docs_scaffold", fake)`; `chdir` into the
  `sample_ctx.project_root`). Same for `check`.
- `_cmd_docs([])` raises `SystemExit` with code 2 (subcommand required).

Extend the check gate coverage — add to `tests/unit/test_pipeline_check.py`
(reuse the existing `worktree_setup` + `stub_test_and_compile` fixtures):
- A test that runs `run_check` to green (as the existing happy-path test does)
  and asserts the report contains rows named `docs_standard_files` and
  `docs_reachability`, both passed with the "no plans/design — skipped" detail
  (the sample fixture has no `plans/` dir). Locate the report via the same
  mechanism the existing success test uses; if the existing tests only inspect
  the return code, assert on `capsys` output containing both gate names instead.

---

## Step 5 — Run the tests (from `docex/`, the documented discipline)

```
cd ~/.claude/jean_baudrillard/docex
python -m pytest tests -q                 # unit (integration deselected)
python -m pytest tests -q -m integration  # integration, ALONE
```

Both must be green. Fix any failure before reporting. Report both collected/passed
counts.

---

## Notes / non-goals
- Do NOT add a `doctrine_excerpts/index.yml` entry — `docs` is a command, not an
  infrastructural resource (docex_process.md § Additional Artifacts).
- Do NOT touch `plans/core/masterplan.md`, the changelog, or version files — the
  mod driver owns those in the documentation/close steps.
- No contract changes (docex ships no `infra.yml` surfaces affected here).

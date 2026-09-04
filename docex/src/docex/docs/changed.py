"""``docex docs changed <git_ref>`` — in-scope files changed since a ref.

The raw selection helper the orchestration skill's "what did this mod/advance
touch" step needs. Scope is the **location allowlist**: ``plans/design/**`` and
each codebase's ``core/<cb>/src/**``, git-tracked only (matching the linkmap's
own tracked-source boundary).

Semantics: ``git diff --name-only <ref> -- <allowlist pathspecs>`` — ref vs. the
current working tree, so a mod's still-uncommitted edits to tracked files are
included; deleted-since-``ref`` paths are dropped (a file that no longer exists
can't be a subject). Passing git's empty-tree object as the ref makes
"changed since the beginning of history" == "all in-scope files".

Output is a plain sorted newline list of project-relative fpaths.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docex.context import ProjectContext

# The empty-tree object id — "changed since here" == "all tracked".
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def in_scope(path: str, codebase_names: list[str]) -> bool:
    """True iff a project-relative POSIX path is under the location allowlist:
    ``plans/design/**`` OR ``core/<cb>/src/**`` for a known codebase."""
    if path.startswith("plans/design/"):
        return True
    parts = path.split("/")
    return (
        len(parts) >= 4
        and parts[0] == "core"
        and parts[1] in codebase_names
        and parts[2] == "src"
    )


def filter_changed(paths, codebase_names, project_root) -> list[str]:
    """Keep in-scope paths that still EXIST on disk (drop deletions), sorted &
    deduped. ``project_root`` is used only for the existence check."""
    root = Path(project_root)
    kept: set[str] = set()
    for p in paths:
        if not in_scope(p, codebase_names):
            continue
        if not (root / p).is_file():
            continue  # deleted-since-ref → drop
        kept.add(p)
    return sorted(kept)


def changed_fpaths(
    project_root: Path,
    codebase_names: list[str],
    git_ref: str,
    git: object | None = None,
) -> list[str]:
    """In-scope, existing files changed since ``git_ref`` (sorted, deduped).

    Shared by ``run_docs_changed`` and ``run_docs_cxt_groups`` so the
    ref→changed-set logic lives in one place. ``git`` defaults to
    ``SubprocessGitClient()``.

    Raises ``ValueError`` on an unresolvable ref — ``diff_names`` returns ``[]``
    on git failure and so cannot itself distinguish "no changes" from "bad
    ref", so we validate the ref up front via ``rev_parse``. The empty-tree id
    is always treated as resolvable (it lists all tracked files, and resolves
    fine via ``rev_parse`` in a normal repo, but an empty repo needs the guard).
    """
    from docex.git import SubprocessGitClient

    project_root = Path(project_root)
    if git is None:
        git = SubprocessGitClient()

    if git_ref != EMPTY_TREE and not git.rev_parse(project_root, git_ref):
        raise ValueError(f"unresolvable git ref: {git_ref}")

    pathspecs = ["plans/design"] + [
        f"core/{cb}/src" for cb in codebase_names
    ]
    raw = git.diff_names(project_root, git_ref, pathspecs)
    return filter_changed(raw, codebase_names, project_root)


def run_docs_changed(ctx: ProjectContext, git_ref: str) -> int:
    """``docex docs changed <git_ref>`` — print the sorted in-scope changed set.

    Output is a plain newline-delimited sorted list of project-relative fpaths
    to stdout (nothing else); an empty result prints nothing. Returns 0 on
    success, 1 on an unresolvable ref (diagnostic to stderr).
    """
    from docex.orchestrate._common import codebases

    project_root = ctx.project_root
    cbs = codebases(ctx)
    try:
        names = changed_fpaths(project_root, cbs, git_ref)
    except ValueError as exc:
        print(f"docex docs changed: {exc}", file=sys.stderr)
        return 1
    for name in names:
        print(name)
    return 0

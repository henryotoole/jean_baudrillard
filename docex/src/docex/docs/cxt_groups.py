"""``docex docs cxt_groups <tokens_max> {<git_ref> | all}`` — context groups.

Partitions the selected subject files into **context groups** — sets of subjects
with highly-overlapping overhead whose combined in-context cost (subjects +
shared overhead, using linkmap ``tokens``) stays under ``tokens_max``. The
groups fully cover the selection with no repeated subject. This is the grouping
engine the ``doc-refine-orchestration`` skill consumes to spawn one subagent per
group.

The algorithm is a **heuristic** — overlap-greedy bin-packing under
``tokens_max``, fully deterministic. It does not promise optimality (optimal
set-cover-under-a-budget is NP-hard and not worth it for an estimate whose
inputs are themselves estimates). An oversize subject (self + overhead alone
> ``tokens_max``) becomes its own singleton group with a stderr diagnostic; that
is a heuristic result, not a failure, so exit stays 0.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from docex.context import ProjectContext
from docex.docs.linkmap import load_code_level_graph, load_design_docs_graph
from docex.docs.overhead import compute_overhead

_LEVEL_RANK = {"L1": 0, "L2": 1, "L3": 2}


@dataclass(frozen=True)
class ContextGroup:
    overhead: tuple[str, ...]   # fpaths, high→low abstraction then fpath
    subjects: tuple[str, ...]   # fpaths, sorted
    estimated_tokens: int


def build_context_groups(
    nodes, edges, subject_fpaths, tokens_max
) -> tuple[list[ContextGroup], list[str]]:
    """Overlap-greedy bin-packing under ``tokens_max``. Pure.

    Returns ``(groups, oversize)`` where ``oversize`` is the list of subject
    fpaths whose own (self + overhead) cost alone exceeds ``tokens_max`` (each
    becomes its own singleton group; the caller warns on stderr).
    """
    by_fpath = {n.fpath: n for n in nodes}

    def tokens(fp: str) -> int:
        node = by_fpath.get(fp)
        return (node.tokens or 0) if node is not None else 0

    # Overhead fpath set per subject, computed once.
    ov: dict[str, frozenset[str]] = {
        s: frozenset(n.fpath for n in compute_overhead(nodes, edges, s))
        for s in subject_fpaths
    }

    def cost(subjects_set) -> int:
        union: set[str] = set(subjects_set)
        for s in subjects_set:
            union |= ov[s]
        return sum(tokens(fp) for fp in union)

    unplaced = sorted(subject_fpaths)
    groups: list[ContextGroup] = []
    oversize: list[str] = []

    while unplaced:
        seed = unplaced.pop(0)
        group = [seed]
        ovu = set(ov[seed])

        if cost({seed}) > tokens_max:
            oversize.append(seed)
            groups.append(_emit_group(group, ov, by_fpath, cost))
            continue

        while True:
            best = None
            best_key = None
            base_cost = cost(set(group))
            for c in unplaced:  # already in fpath order
                if cost(set(group) | {c}) > tokens_max:
                    continue
                overlap = len(ov[c] & ovu)
                added = cost(set(group) | {c}) - base_cost
                key = (-overlap, added, c)
                if best_key is None or key < best_key:
                    best_key = key
                    best = c
            if best is None:
                break
            unplaced.remove(best)
            group.append(best)
            ovu |= ov[best]

        groups.append(_emit_group(group, ov, by_fpath, cost))

    groups.sort(key=lambda g: g.subjects)
    return groups, oversize


def build_module_integrity_groups(
    nodes, edges, subject_fpaths, tokens_max
) -> tuple[list[ContextGroup], list[str]]:
    """Category-integrity packing. Pure.

    Never splits a category (module / codebase / design-docs set) across groups
    unless forced by ``tokens_max``, and then only across groups containing
    nothing but that category's files. See
    ``plans/ops/mods/175_cxt_groups_depth_and_integrity/overview.md`` for the
    rule and its validation against the prep's Module Integrity table.

    Returns ``(groups, oversize)`` with the same contract as
    ``build_context_groups``: an ``oversize`` fpath is a single file whose own
    self+overhead exceeds ``tokens_max`` (emitted as its own singleton group;
    the caller warns on stderr).
    """
    by_fpath = {n.fpath: n for n in nodes}

    def tokens(fp: str) -> int:
        node = by_fpath.get(fp)
        return (node.tokens or 0) if node is not None else 0

    ov: dict[str, frozenset[str]] = {
        s: frozenset(n.fpath for n in compute_overhead(nodes, edges, s))
        for s in subject_fpaths
    }

    def cost(subjects_set) -> int:
        union: set[str] = set(subjects_set)
        for s in subjects_set:
            union |= ov[s]
        return sum(tokens(fp) for fp in union)

    # -- classify subjects into top-level units --------------------------------
    # unit key: ("design",) | ("codebase", <cb>)
    units: dict[tuple, list[str]] = {}
    for fp in subject_fpaths:
        node = by_fpath.get(fp)
        if node is not None and node.type == "design":
            key: tuple = ("design",)
        else:
            cb = node.codebase if node is not None else "none"
            key = ("codebase", cb)
        units.setdefault(key, []).append(fp)

    oversize: list[str] = []
    dedicated: list[list[str]] = []   # pure groups from fragmented units
    whole_atoms: list[list[str]] = []  # whole top-level units that fit

    def leaf_split(files: list[str]) -> list[list[str]]:
        """Split a leaf category's files into pure groups under the budget.

        Only these files ever appear in the returned groups. A single file whose
        own self+overhead exceeds the budget becomes its own group and is
        recorded in ``oversize``.
        """
        out: list[list[str]] = []
        cur: list[str] = []
        for fp in sorted(files):
            if cost([fp]) > tokens_max:
                if cur:
                    out.append(cur)
                    cur = []
                out.append([fp])
                oversize.append(fp)
                continue
            if cur and cost(set(cur) | {fp}) > tokens_max:
                out.append(cur)
                cur = [fp]
            else:
                cur.append(fp)
        if cur:
            out.append(cur)
        return out

    def pack_atoms(atoms: list[list[str]]) -> list[list[str]]:
        """Deterministic first-fit combining of whole atoms under the budget.

        Each atom is kept intact (never split); atoms that fit together share a
        group. Used both for the top-level whole units and for a fragmented
        codebase's module/root children (within that codebase's own groups).
        """
        packed: list[list[str]] = []
        for atom in sorted(atoms, key=lambda a: sorted(a)):
            placed = False
            for g in packed:
                if cost(set(g) | set(atom)) <= tokens_max:
                    g.extend(atom)
                    placed = True
                    break
            if not placed:
                packed.append(list(atom))
        return packed

    for key in sorted(units):
        files = units[key]
        if cost(files) <= tokens_max:
            whole_atoms.append(files)
            continue
        # Unit does not fit whole → fragment.
        if key[0] == "design":
            dedicated.extend(leaf_split(files))
            continue
        # A codebase: subdivide into module children + a codebase-root residual.
        children: dict[str, list[str]] = {}
        for fp in files:
            node = by_fpath.get(fp)
            module = node.module if node is not None else "none"
            children.setdefault(module, []).append(fp)
        if len(children) == 1 and "none" in children:
            # Non-hex / codebase-root only: no module tier to subdivide into →
            # treat as a leaf.
            dedicated.extend(leaf_split(files))
            continue
        child_atoms: list[list[str]] = []
        for _module, cfiles in sorted(children.items()):
            if cost(cfiles) <= tokens_max:
                child_atoms.append(cfiles)
            else:
                dedicated.extend(leaf_split(cfiles))
        dedicated.extend(pack_atoms(child_atoms))

    all_groups = pack_atoms(whole_atoms) + dedicated
    groups = [_emit_group(g, ov, by_fpath, cost) for g in all_groups]
    groups.sort(key=lambda g: g.subjects)
    return groups, oversize


def _emit_group(group, ov, by_fpath, cost) -> ContextGroup:
    """Freeze a list of subject fpaths into a ContextGroup.

    Overhead = (⋃ ov[s]) MINUS the group's own subjects (a subject already in
    context is not listed as overhead), ordered high→low abstraction then
    fpath. estimated_tokens = cost(group subjects).
    """
    subjects = sorted(group)
    ov_union: set[str] = set()
    for s in group:
        ov_union |= ov[s]
    ov_union -= set(group)

    def rank(fp: str):
        node = by_fpath.get(fp)
        level = node.level if node is not None else None
        return (_LEVEL_RANK.get(level, 3), fp)

    overhead = tuple(sorted(ov_union, key=rank))
    return ContextGroup(
        overhead=overhead,
        subjects=tuple(subjects),
        estimated_tokens=cost(set(group)),
    )


def render_cxt_groups_json(tokens_max, selection, groups, nodes) -> str:
    """Render the context groups as deterministic JSON.

    ``nodes`` is needed to look up each fpath's ``level``/``tokens`` for the
    per-entry metadata (the ContextGroup carries only fpaths).
    """
    by_fpath = {n.fpath: n for n in nodes}

    def entry(fp: str):
        node = by_fpath.get(fp)
        return {
            "fpath": fp,
            "level": node.level if node is not None else None,
            "tokens": node.tokens if node is not None else None,
        }

    doc = {
        "tokens_max": tokens_max,
        "selection": selection,
        "groups": [
            {
                "index": i,
                "estimated_tokens": g.estimated_tokens,
                "overhead": [entry(fp) for fp in g.overhead],
                "subjects": [entry(fp) for fp in g.subjects],
            }
            for i, g in enumerate(groups)
        ],
    }
    return json.dumps(doc, indent=2, sort_keys=True)


def run_docs_cxt_groups(
    ctx: ProjectContext,
    tokens_max: int,
    selection: str,
    depth: str = "code_level",
    optimize: str = "tokens",
) -> int:
    """``docex docs cxt_groups <tokens_max> {<git_ref>|all}`` — print groups JSON.

    Args:
        ctx: the loaded project context (yields project root + codebases).
        tokens_max: the per-group in-context token budget (must be > 0).
        selection: the literal ``all`` (every design/source node) or a git ref
            (the ``changed <ref>`` set intersected with the graph's nodes).
        depth: ``code_level`` (default; ``plans/design`` + tracked
            ``core/<cb>/src``) or ``design_docs`` (``plans/design`` only) — the
            tracked scope the subjects are drawn from, mirroring ``docex docs
            linkmap <depth>``.
        optimize: ``tokens`` (default; overlap-greedy bin-packing) or
            ``module_integrity`` (never split a module / codebase / design-docs
            category across groups except into category-pure groups when forced).

    Both defaults reproduce the pre-mod-175 output byte-for-byte.

    Errors:
        ``tokens_max <= 0`` or an unresolvable git ref → diagnostic on stderr
        and exit 1. An oversize subject is NOT a failure (exit stays 0; a
        stderr warning names it).

    Returns:
        0 on success (JSON written to stdout); 1 on a validation/ref failure.
    """
    from docex.docs.changed import changed_fpaths
    from docex.orchestrate._common import codebases

    if tokens_max <= 0:
        print(
            f"docex docs cxt_groups: tokens_max must be positive, got "
            f"{tokens_max}",
            file=sys.stderr,
        )
        return 1

    project_root = ctx.project_root
    cbs = codebases(ctx)
    if depth == "design_docs":
        nodes, edges = load_design_docs_graph(project_root, cbs)
    else:
        nodes, edges = load_code_level_graph(project_root, cbs)
    node_fpaths = {n.fpath for n in nodes if n.type in ("design", "source")}

    if selection == "all":
        subjects = sorted(node_fpaths)
    else:
        try:
            changed = changed_fpaths(project_root, cbs, selection)
        except ValueError as exc:
            print(f"docex docs cxt_groups: {exc}", file=sys.stderr)
            return 1
        subjects = sorted(set(changed) & node_fpaths)

    if optimize == "module_integrity":
        groups, oversize = build_module_integrity_groups(
            nodes, edges, subjects, tokens_max
        )
    else:
        groups, oversize = build_context_groups(
            nodes, edges, subjects, tokens_max
        )

    # An oversize subject appears as its own singleton group; report the true
    # self+overhead cost that group carries.
    group_cost = {g.subjects[0]: g.estimated_tokens for g in groups if len(g.subjects) == 1}
    for fp in oversize:
        cost = group_cost.get(fp)
        print(
            f"docex docs cxt_groups: {fp} ({cost} tokens self+overhead) "
            f"exceeds tokens_max={tokens_max}; emitted as its own group.",
            file=sys.stderr,
        )

    print(render_cxt_groups_json(tokens_max, selection, groups, nodes))
    return 0

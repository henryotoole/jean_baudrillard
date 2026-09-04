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
from docex.docs.linkmap import load_code_level_graph
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
    ctx: ProjectContext, tokens_max: int, selection: str
) -> int:
    """``docex docs cxt_groups <tokens_max> {<git_ref>|all}`` — print groups JSON.

    Args:
        ctx: the loaded project context (yields project root + codebases).
        tokens_max: the per-group in-context token budget (must be > 0).
        selection: the literal ``all`` (every design/source node) or a git ref
            (the ``changed <ref>`` set intersected with the graph's nodes).

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

    groups, oversize = build_context_groups(nodes, edges, subjects, tokens_max)

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

"""``docex docs`` — scaffold, check, and regenerate the design-doc structure.

All subcommands (and the ``docex check`` gate) share ONE definition of the
standard file set (``standard_set.py``) and ONE canonical render of the ADR
index files (``adr.py``) so they cannot disagree.
"""

from __future__ import annotations

from docex.docs.adr import (
    Adr,
    adr_index_drift,
    load_adrs,
    parse_adr,
    regenerate_adr_indexes,
    render_active,
    render_index,
    run_docs_adr,
)
from docex.docs.check import (
    check_docs,
    design_root_exists,
    missing_standard_files,
    run_docs_check,
    unreachable_docs,
)
from docex.docs.changed import (
    changed_fpaths,
    filter_changed,
    in_scope,
    run_docs_changed,
)
from docex.docs.cxt_groups import (
    ContextGroup,
    build_context_groups,
    run_docs_cxt_groups,
)
from docex.docs.linkmap import (
    Edge,
    Node,
    build_linkmap,
    load_code_level_graph,
    render_linkmap_json,
    run_docs_linkmap,
)
from docex.docs.overhead import (
    compute_overhead,
    outgoing_design_targets,
    run_docs_overhead,
)
from docex.docs.scaffold import run_docs_scaffold, scaffold_design

__all__ = [
    "Adr",
    "adr_index_drift",
    "load_adrs",
    "parse_adr",
    "regenerate_adr_indexes",
    "render_active",
    "render_index",
    "run_docs_adr",
    "check_docs",
    "design_root_exists",
    "missing_standard_files",
    "unreachable_docs",
    "run_docs_check",
    "build_linkmap",
    "render_linkmap_json",
    "run_docs_linkmap",
    "load_code_level_graph",
    "Node",
    "Edge",
    "run_docs_overhead",
    "compute_overhead",
    "outgoing_design_targets",
    "run_docs_changed",
    "changed_fpaths",
    "in_scope",
    "filter_changed",
    "run_docs_cxt_groups",
    "build_context_groups",
    "ContextGroup",
    "run_docs_scaffold",
    "scaffold_design",
]

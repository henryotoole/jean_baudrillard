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
from docex.docs.linkmap import (
    Edge,
    Node,
    build_linkmap,
    render_linkmap_json,
    run_docs_linkmap,
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
    "Node",
    "Edge",
    "run_docs_scaffold",
    "scaffold_design",
]

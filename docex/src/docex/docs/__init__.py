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

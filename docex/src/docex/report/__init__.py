"""``docex report <type>`` — distilled, bucketed views of a project.

Ships one report type, ``docs``, at the ``data`` format (the distillation
layer). ``full`` (HTML treemaps) is Mod 177; until then it stubs to ``data``.
"""

from __future__ import annotations

from docex.report.docs import (
    Bucket,
    build_design_tree,
    build_docs_data,
    build_source_tree,
    render_data_json,
    run_report_docs,
)

__all__ = [
    "Bucket",
    "build_design_tree",
    "build_docs_data",
    "build_source_tree",
    "render_data_json",
    "run_report_docs",
    "run_report",
]


def run_report(ctx, report_type: str, fmt: str) -> int:
    """Dispatch a ``docex report <type>`` invocation to its report handler."""
    if report_type == "docs":
        return run_report_docs(ctx, fmt)
    import sys

    print(f"docex report: unknown report type {report_type!r}", file=sys.stderr)
    return 64

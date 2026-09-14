"""``docex report <type>`` — distilled, bucketed views of a project.

Ships one report type, ``docs``, in two formats: ``data`` (the bucketed JSON
distillation layer) and ``full`` (a self-contained HTML report of three treemap
sections rendered from that same bucket tree).
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
from docex.report.full import render_full_html

__all__ = [
    "Bucket",
    "build_design_tree",
    "build_docs_data",
    "build_source_tree",
    "render_data_json",
    "render_full_html",
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

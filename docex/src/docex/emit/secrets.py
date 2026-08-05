"""The shared grouped-``KEY=value`` manifest renderer.

Exposes ``render_manifest_env``: given an ordered list of ``ManifestEntry``
rows, it renders them as env text grouped by declaring source with ``#``
comment headers. Used by ``docex secrets scaffold`` and ``docex config
scaffold`` (secretsmgmt/engine.py) to reconcile the gitignored ``<env>.env``
value files against their committed manifests.
"""

from __future__ import annotations

from itertools import groupby
from typing import Mapping

from docex.cicl.categories import ManifestEntry
from docex.cicl.model import CICLDocument


def _group_header(source: str, doc: CICLDocument) -> str:
    """The grouped comment header for one manifest source: a doctrine block,
    then ``# <svc> (core service)`` blocks, then ``# <svc> (<engines>)``
    backing blocks."""
    if source == "doctrine":
        return "# Doctrine-injected secrets"
    if source in doc.codebases:
        return f"# {source} (core service)"
    svc = doc.backing_services.get(source)
    if svc is not None:
        engines = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        return f"# {source} ({', '.join(engines)})"
    return f"# {source}"


def render_manifest_env(
    entries: list[ManifestEntry],
    doc: CICLDocument,
    *,
    prefix_lines: list[str],
    values: Mapping[str, str],
) -> str:
    """Render the grouped-by-source env text for a manifest.

    ``entries`` are the ``ManifestEntry`` rows to render (the caller supplies
    them — secret or config — so scaffold renders the right category rather
    than always the secret manifest). ``doc`` is consulted only to build the
    grouped ``#`` source headers. ``prefix_lines`` are emitted verbatim
    (already ``#``-prefixed) at the top. Each key is written as ``KEY=<value>``
    using ``values`` (empty string when absent); ``scaffold`` passes the
    reconciled values so secret and config renders share one layout."""
    lines = list(prefix_lines)
    if not entries:
        lines.append("# (no backing services declare runtime env vars)")
        return "\n".join(lines)
    for source, group in groupby(entries, key=lambda e: e.source):
        lines.append(_group_header(source, doc))
        entry: ManifestEntry
        for entry in group:
            if entry.desc:
                lines.append(f"# {entry.desc}")
            lines.append(f"{entry.key}={values.get(entry.key, '')}")
        lines.append("")
    return "\n".join(lines)

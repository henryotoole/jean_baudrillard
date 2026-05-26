"""docex why <resource> — print a doctrine excerpt for a named resource.

``doctrine_excerpts/index.yml`` maps resource names to markdown files
under the same directory. The mapping is loaded at request time. The
excerpt is rendered via ``rich.markdown.Markdown`` so it looks clean
in a terminal but still copies as plain text.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from rich.console import Console
from rich.markdown import Markdown

from docex.errors import DocexError


# Candidate roots for ``doctrine_excerpts/`` (same pattern as transfer tables).
_EXCERPTS_CANDIDATES = [
    Path("/opt/docex/doctrine_excerpts"),
    Path(__file__).resolve().parent.parent.parent.parent / "doctrine_excerpts",
]


class WhyError(DocexError):
    pass


def _excerpts_root() -> Path | None:
    for c in _EXCERPTS_CANDIDATES:
        if c.is_dir():
            return c
    return None


def _load_index(root: Path) -> dict[str, str]:
    idx_path = root / "index.yml"
    if not idx_path.is_file():
        raise WhyError(f"missing doctrine_excerpts/index.yml at {idx_path}")
    raw = yaml.safe_load(idx_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise WhyError(f"{idx_path}: expected a YAML mapping at the root")
    return {str(k): str(v) for k, v in raw.items()}


def run_why(resource: str | None) -> int:
    """Look up ``resource`` and print its excerpt.

    With no arg: print the index of known resources.
    Unknown resource: print known list, exit 1.
    """
    root = _excerpts_root()
    if root is None:
        raise WhyError("doctrine_excerpts/ directory not found in any expected location")
    index = _load_index(root)
    console = Console()

    if not resource:
        console.print("[bold]Available resources (use `docex why <name>`):[/bold]")
        for name in sorted(index):
            console.print(f"  - {name}")
        return 0

    if resource not in index:
        console.print(f"[red]unknown resource:[/red] {resource!r}")
        console.print("[bold]Available resources:[/bold]")
        for name in sorted(index):
            console.print(f"  - {name}")
        return 1

    fname = index[resource]
    excerpt_path = root / fname
    if not excerpt_path.is_file():
        raise WhyError(
            f"index lists {resource!r} -> {fname} but file is missing at {excerpt_path}"
        )
    text = excerpt_path.read_text()
    console.print(Markdown(text))
    return 0

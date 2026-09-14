# Mod 176 — Implementation Steps

Execute against `~/.claude/jean_baudrillard/docex` on the current branch
(`advance_014_docs_report_and_skill_refactor`). Do **not** create/switch
branches, touch version artifacts, `CHANGELOG.md`, or `RELEASING.md`. Do **not**
edit any doctrine file or the docex design docs — those are handled outside this
implementation. Your scope is: the new `src/docex/report/` package, the
dispatcher wiring in `src/docex/__main__.py`, and unit tests.

Run tests from the docex root with `python -m pytest tests` (NOT bare `pytest`,
NOT `tests/unit`). Iterate with a scoped run
`python -m pytest tests/unit/test_report_docs.py tests/unit/test_report_lint.py
tests/unit/test_dispatcher.py -q`, then close with the full `python -m pytest
tests`.

---

## Step 1 — Create `src/docex/report/lint.py`

Per-language linter attributing a source file's **characters** to the five
report leaf categories. Returns char counts (the caller converts to tokens).

```python
"""Per-language linting for ``docex report docs`` source buckets.

Attributes a source file's characters across the five report leaf categories:
``inline_comments``, ``docstrings``, ``references``, ``code``,
``other``. Returns character counts (not tokens); the caller applies the shared
token estimator so report weights agree with linkmap / cxt_groups.

Real lexers cover Python and a C-family family (``//`` + ``/* */``) spanning
JavaScript/TypeScript, Go, C/C++, C#, and Rust — i.e. the doctrine's language
list (``doctrine/practices/languages.md``). An unknown extension routes the whole
file to ``other`` (unlintable).

A ``reference`` is a file-path-like token appearing INSIDE a comment or
docstring — a name with a recognized source/doc extension, optionally
slash-qualified (this also catches markdown-link targets). Reference spans are
carved out of the comment/docstring counts so the five leaves stay a clean
character partition of the file.
"""

from __future__ import annotations

import re
from pathlib import Path

CATEGORIES = (
    "inline_comments",
    "docstrings",
    "references",
    "code",
    "other",
)

# A file-path-like reference token: optional slash-qualified prefix + a filename
# with a recognized source/doc extension.
_REF = re.compile(
    r"(?:[\w.\-]+/)*[\w.\-]+\."
    r"(?:py|pyi|js|jsx|ts|tsx|mjs|cjs|go|rs|c|h|cc|cpp|cxx|hpp|hh|cs|"
    r"md|mmd|ya?ml|json|toml|sh|txt|ini|cfg)"
)

_PY_EXTS = {".py", ".pyi"}
_CFAMILY_EXTS = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go",
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh",
    ".cs",
    ".rs",
}


def _blank() -> dict[str, int]:
    return {c: 0 for c in CATEGORIES}


def lint_file(path: Path) -> dict[str, int]:
    """Character counts per category for one file. Deterministic.

    An unreadable file yields all-zero counts; a readable file of unknown type
    counts entirely as ``other``.
    """
    path = Path(path)
    ext = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _blank()

    if ext in _PY_EXTS:
        code_chars, comment_text, docstring_text = _lex_python(text)
    elif ext in _CFAMILY_EXTS:
        code_chars, comment_text, docstring_text = _lex_cfamily(text)
    else:
        c = _blank()
        c["other"] = len(text)
        return c

    return _finalize_counts(code_chars, comment_text, docstring_text)


def _finalize_counts(
    code_chars: int, comment_text: str, docstring_text: str
) -> dict[str, int]:
    """Carve references out of comment/docstring text into their own leaf.

    Preserves the partition: ``inline_comments + docstrings + references``
    equals ``len(comment_text) + len(docstring_text)``, and adding ``code``
    equals the whole file length.
    """
    ref_c = sum(len(m) for m in _REF.findall(comment_text))
    ref_d = sum(len(m) for m in _REF.findall(docstring_text))
    return {
        "inline_comments": max(0, len(comment_text) - ref_c),
        "docstrings": max(0, len(docstring_text) - ref_d),
        "references": ref_c + ref_d,
        "code": code_chars,
        "other": 0,
    }


def _lex_python(text: str) -> tuple[int, str, str]:
    """(code_chars, comment_text, docstring_text) for Python.

    Heuristic: EVERY triple-quoted string literal counts as a docstring (the big
    triple-quoted blocks are what "docstring" means for this report); single/
    double quoted strings count as code. The scanner consumes comments and
    string literals as whole regions, so a ``#`` or quote inside another literal
    is never re-interpreted.
    """
    code = 0
    comments: list[str] = []
    docstrings: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "#":
            j = text.find("\n", i)
            j = n if j == -1 else j
            comments.append(text[i:j])
            i = j
            continue
        if text.startswith('"""', i) or text.startswith("'''", i):
            q = text[i:i + 3]
            end = text.find(q, i + 3)
            end = n if end == -1 else end + 3
            docstrings.append(text[i:end])
            i = end
            continue
        if ch in ('"', "'"):
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    j += 1
                    break
                if text[j] == "\n":
                    break
                j += 1
            code += j - i
            i = j
            continue
        code += 1
        i += 1
    return code, "".join(comments), "".join(docstrings)


def _lex_cfamily(text: str) -> tuple[int, str, str]:
    """(code_chars, comment_text, docstring_text) for the C-family.

    Docstrings: JSDoc ``/** */``, Rust ``///`` / ``//!`` / ``/*! */``. All other
    ``//`` and ``/* */`` comments are inline. Go has no distinct docstring form,
    so Go comments all fall to inline (accepted). Strings (``"`` ``'`` `` ` ``)
    count as code.
    """
    code = 0
    comments: list[str] = []
    docstrings: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        three = text[i:i + 3]
        two = text[i:i + 2]
        if three in ("///", "//!"):
            j = text.find("\n", i)
            j = n if j == -1 else j
            docstrings.append(text[i:j])
            i = j
            continue
        if two == "//":
            j = text.find("\n", i)
            j = n if j == -1 else j
            comments.append(text[i:j])
            i = j
            continue
        if three in ("/**", "/*!"):
            end = text.find("*/", i + 3)
            end = n if end == -1 else end + 2
            docstrings.append(text[i:end])
            i = end
            continue
        if two == "/*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            comments.append(text[i:end])
            i = end
            continue
        if ch in ('"', "'", "`"):
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    j += 1
                    break
                if text[j] == "\n" and ch != "`":
                    break
                j += 1
            code += j - i
            i = j
            continue
        code += 1
        i += 1
    return code, "".join(comments), "".join(docstrings)
```

---

## Step 2 — Create `src/docex/report/docs.py`

The `docs` report's `data` builder. Builds both the design-doc and source-code
bucket trees, reusing the shared linkmap builder and its token estimator.

```python
"""``docex report docs`` — the ``data`` (distillation) format.

Emits deterministic JSON of token-weight buckets for the design-doc corpus and
the source code. The design-doc bucket tree is built from the SHARED linkmap
graph (``load_code_level_graph``) — not a re-walk of ``plans/design`` — and all
token estimates use linkmap's estimator (``_CHARS_PER_TOKEN`` / ``_estimate_tokens``)
so report weights agree with ``cxt_groups`` budgets.

Bucket model: ``{name, tokens, children?}``. A leaf omits ``children``. At every
bucket with children, if ``tokens - Σ(child.tokens) > 0`` a final ``etc`` child
carries the remainder. Grouping buckets define ``tokens = Σ(children)`` (etc 0);
arc42 file buckets carry the whole-file weight and split into ``#`` sections,
where ``etc`` = the unsectioned preamble + rounding — the one place the invariant
does real work. Source-file buckets partition the file's characters into the
five leaves, which sum bottom-up (etc 0).

Structure per ``docex_report_design.md § Docs → Summarizing Metrics and Data``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from docex.docs.linkmap import (
    _CHARS_PER_TOKEN,
    load_code_level_graph,
)
from docex.report.lint import lint_file

# --- token estimation -------------------------------------------------------


def _weight(chars: int) -> int:
    """Token weight of a character span, using linkmap's divisor (SC5). No
    ``max(1, …)`` — a sub-portion may legitimately round to zero tokens."""
    return round(chars / _CHARS_PER_TOKEN)


# --- bucket type ------------------------------------------------------------


@dataclass
class Bucket:
    name: str
    tokens: int
    children: "list[Bucket] | None" = None

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "tokens": self.tokens}
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


def _finalize(name: str, own_tokens: int, children: "list[Bucket]") -> Bucket:
    """Attach an ``etc`` child for the remainder when children under-sum."""
    kids = list(children)
    remainder = own_tokens - sum(c.tokens for c in kids)
    if remainder > 0:
        kids.append(Bucket("etc", remainder))
    return Bucket(name, own_tokens, kids or None)


def _group(name: str, children: "list[Bucket]") -> Bucket:
    """A grouping bucket whose own weight is the sum of its children."""
    return _finalize(name, sum(c.tokens for c in children), children)


# --- arc42 section splitting ------------------------------------------------

import re as _re

_H1 = _re.compile(r"^#\s+(.*)$")
_FENCE = _re.compile(r"^\s*(```|~~~)")


def _split_sections(text: str) -> "tuple[int, list[tuple[str, int]]]":
    """Return (preamble_chars, [(section_name, chars), …]).

    Splits on level-1 (``#``) headings, fence-aware so a ``#`` inside a fenced
    code block is not a heading. Content before the first heading is preamble.
    Sections keep document order.
    """
    in_fence = False
    preamble = 0
    sections: list[list] = []
    for line in text.splitlines(keepends=True):
        is_fence = bool(_FENCE.match(line))
        is_h1 = (not in_fence) and bool(_H1.match(line))
        if is_fence:
            in_fence = not in_fence
        if is_h1:
            name = _H1.match(line).group(1).strip()
            sections.append([name, len(line)])
        elif sections:
            sections[-1][1] += len(line)
        else:
            preamble += len(line)
    return preamble, [(n, c) for n, c in sections]


def _arc42_bucket(name: str, abs_path: Path, file_tokens: int) -> Bucket:
    try:
        text = abs_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    _preamble, sections = _split_sections(text)
    kids = [Bucket(sec, _weight(chars)) for sec, chars in sections]
    own = max(file_tokens, sum(k.tokens for k in kids))
    return _finalize(name, own, kids)


# --- design-doc tree --------------------------------------------------------

_ARC42 = (
    "boundary_conditions.md",
    "concepts_and_decisions.md",
    "structures_and_views.md",
)
_STD_TOP = {
    "boundary_conditions.md",
    "concepts_and_decisions.md",
    "structures_and_views.md",
    "project_diagram.mmd",
    "service_diagram.mmd",
    "adr_index.md",
    "adr_active.md",
    "lexicon.md",
}


def build_design_tree(design_nodes, project_root) -> Bucket:
    """Build the design-doc bucket tree from the graph's ``design`` nodes."""
    project_root = Path(project_root)
    tok = {n.fpath: (n.tokens or 0) for n in design_nodes}
    rels = {
        n.fpath: n.fpath[len("plans/design/"):]
        for n in design_nodes
        if n.fpath.startswith("plans/design/")
    }

    def leaf(fp: str, name: str) -> Bucket:
        return Bucket(name, tok[fp])

    top = {fp: rel for fp, rel in rels.items() if "/" not in rel}
    specifics_l1 = sorted(
        fp for fp, rel in rels.items() if rel.startswith("specifics/")
    )
    adrs = sorted(fp for fp, rel in rels.items() if rel.startswith("adrs/"))
    l2 = [n for n in design_nodes if n.level == "L2"]
    l3 = [n for n in design_nodes if n.level == "L3"]

    # -- L1 Standard Roots --
    roots_kids: list[Bucket] = []
    for f in _ARC42:
        fp = f"plans/design/{f}"
        if fp in tok:
            roots_kids.append(_arc42_bucket(f, project_root / fp, tok[fp]))
    diag = [
        leaf(f"plans/design/{f}", f)
        for f in ("project_diagram.mmd", "service_diagram.mmd")
        if f"plans/design/{f}" in tok
    ]
    if diag:
        roots_kids.append(_group("Diagrams", diag))
    idx = [
        leaf(f"plans/design/{f}", f)
        for f in ("adr_index.md", "adr_active.md")
        if f"plans/design/{f}" in tok
    ]
    if idx:
        roots_kids.append(_group("ADR Indices", idx))
    if "plans/design/lexicon.md" in tok:
        roots_kids.append(leaf("plans/design/lexicon.md", "lexicon.md"))

    # -- L1 Detail Docs --
    detail_kids: list[Bucket] = []
    if specifics_l1:
        detail_kids.append(
            _group("specifics", [leaf(fp, Path(fp).name) for fp in specifics_l1])
        )
    for f in ("quality_scenarios.md", "unknowns.md"):
        fp = f"plans/design/{f}"
        if fp in tok:
            detail_kids.append(leaf(fp, f))
    named_top = _STD_TOP | {"quality_scenarios.md", "unknowns.md"}
    other_top = sorted(fp for fp, rel in top.items() if rel not in named_top)
    if other_top:
        detail_kids.append(
            _group("Other Files", [leaf(fp, Path(fp).name) for fp in other_top])
        )

    # -- L2 Architecture Docs (name form "<cb>/filename") --
    def cbname(fp: str) -> str:
        rel = rels[fp]
        return f"{rel.split('/', 1)[0]}/{Path(fp).name}"

    md_diagrams, l2_specifics, l2_other = [], [], []
    for n in l2:
        rel = rels[n.fpath]
        sub = rel.split("/", 1)[1] if "/" in rel else ""
        if sub == "module_diagram.mmd":
            md_diagrams.append(n.fpath)
        elif sub.startswith("specifics/"):
            l2_specifics.append(n.fpath)
        else:
            l2_other.append(n.fpath)
    l2_kids: list[Bucket] = []
    if md_diagrams:
        l2_kids.append(
            _group(
                "Module Diagrams",
                [leaf(fp, cbname(fp)) for fp in sorted(md_diagrams)],
            )
        )
    if l2_specifics:
        l2_kids.append(
            _group(
                "specifics", [leaf(fp, cbname(fp)) for fp in sorted(l2_specifics)]
            )
        )
    if l2_other:
        l2_kids.append(
            _group(
                "Other Files", [leaf(fp, cbname(fp)) for fp in sorted(l2_other)]
            )
        )

    # -- L3 Module Docs (per codebase folder) --
    by_cb: dict[str, list[str]] = {}
    for n in l3:
        by_cb.setdefault(n.codebase, []).append(n.fpath)
    l3_kids: list[Bucket] = []
    for cb in sorted(by_cb):
        files = sorted(by_cb[cb])
        l3_kids.append(
            _group(cb, [leaf(fp, f"{cb}/{Path(fp).name}") for fp in files])
        )

    # -- Assemble primaries --
    primaries: list[Bucket] = []
    if roots_kids:
        primaries.append(_group("L1 Standard Roots", roots_kids))
    if detail_kids:
        primaries.append(_group("L1 Detail Docs", detail_kids))
    if l2_kids:
        primaries.append(_group("L2 Architecture Docs", l2_kids))
    if l3_kids:
        primaries.append(_group("L3 Module Docs", l3_kids))
    if adrs:
        primaries.append(Bucket("ADRs", sum(tok[fp] for fp in adrs)))

    return _finalize("Design Docs", sum(p.tokens for p in primaries), primaries)


# --- source-code tree -------------------------------------------------------

_LEAF_ORDER = (
    ("inline comments", "inline_comments"),
    ("docstrings", "docstrings"),
    ("references", "references"),
    ("code", "code"),
    ("other / unlintable", "other"),
)


def _file_bucket(node, project_root: Path) -> Bucket:
    counts = lint_file(project_root / node.fpath)
    leaves = [Bucket(label, _weight(counts[key])) for label, key in _LEAF_ORDER]
    own = sum(l.tokens for l in leaves)
    return Bucket(Path(node.fpath).name, own, leaves)


def build_source_tree(source_nodes, project_root) -> Bucket:
    """Build the source-code bucket tree from the graph's ``source`` nodes."""
    project_root = Path(project_root)
    by_cb: dict[str, dict[str, list]] = {}
    for n in source_nodes:
        by_cb.setdefault(n.codebase, {}).setdefault(n.module, []).append(n)

    cb_buckets: list[Bucket] = []
    for cb in sorted(by_cb):
        mods = by_cb[cb]
        nonhex = set(mods) == {"none"}
        child_buckets: list[Bucket] = []
        for mod in sorted(mods):
            files = sorted(mods[mod], key=lambda x: x.fpath)
            file_buckets = [_file_bucket(n, project_root) for n in files]
            if nonhex:
                child_buckets.extend(file_buckets)
            else:
                mod_name = mod if mod != "none" else "(root)"
                child_buckets.append(_group(mod_name, file_buckets))
        cb_buckets.append(_group(cb, child_buckets))

    return _group("Source Code", cb_buckets)


# --- top-level assembly + command ------------------------------------------


def build_docs_data(nodes, project_root) -> dict:
    """Assemble the full ``data`` document from a linkmap graph's nodes."""
    design_nodes = [n for n in nodes if n.type == "design"]
    source_nodes = [n for n in nodes if n.type == "source"]
    return {
        "report": "docs",
        "format": "data",
        "estimator": {
            "name": "chars_per_token",
            "chars_per_token": _CHARS_PER_TOKEN,
        },
        "design_docs": build_design_tree(design_nodes, project_root).to_dict(),
        "source_code": build_source_tree(source_nodes, project_root).to_dict(),
    }


def render_data_json(doc: dict) -> str:
    """Deterministic, sorted JSON (mirrors linkmap's rendering discipline)."""
    return json.dumps(doc, indent=2, sort_keys=True)


def run_report_docs(ctx, fmt: str) -> int:
    """``docex report docs [--format data|full]`` — print the report.

    ``data`` emits the bucketed JSON. ``full`` (Mod 177) is not yet implemented;
    until it lands it stubs to ``data`` behind a stderr note.
    """
    from docex.orchestrate._common import codebases

    if fmt == "full":
        # TODO(mod 177): render a self-contained HTML report (treemaps).
        print(
            "docex report docs: --format full is not implemented yet "
            "(mod 177); emitting --format data.",
            file=sys.stderr,
        )
        fmt = "data"

    cbs = codebases(ctx)
    nodes, _edges = load_code_level_graph(ctx.project_root, cbs)
    doc = build_docs_data(nodes, ctx.project_root)
    print(render_data_json(doc))
    return 0
```

---

## Step 3 — Create `src/docex/report/__init__.py`

```python
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
```

---

## Step 4 — Wire the dispatcher in `src/docex/__main__.py`

1. Add to `_HELP_TEXT` (alongside the other entries):

   ```python
       "report": "Distill a project view into bucketed metrics — "
                 "'report docs' (data JSON | full HTML).",
   ```

2. Add a new group to `_GROUPS` (append after the `Documentation` entry):

   ```python
       ("Reporting", ("report",)),
   ```

3. Add the handler `_cmd_report` (place it after `_cmd_docs`, before the
   Dispatch section):

   ```python
   def _cmd_report(args: list[str]) -> int:
       """``docex report <type> [--format data|full]`` — distilled project views.

       Ships one type, ``docs``. ``--format`` defaults to ``full`` (Mod 177);
       until that lands, ``full`` stubs to ``data``. ``data`` emits the bucketed
       token-weight JSON (design docs + source code)."""
       parser = argparse.ArgumentParser(prog="docex report", add_help=True)
       parser.add_argument(
           "type", choices=["docs"], help="report type (currently: docs)"
       )
       parser.add_argument(
           "--format", default="full", choices=["data", "full"],
           help="data (bucketed JSON) | full (HTML report; mod 177). "
                "default: full",
       )
       ns = parser.parse_args(args)

       from docex.context import load_project_context
       from docex.report import run_report

       ctx = load_project_context(Path(os.getcwd()))
       return run_report(ctx, ns.type, ns.format)
   ```

4. Add to the handler table in `_build_handler_table()` (a new `# Reporting`
   section after `# Documentation`):

   ```python
           # Reporting
           "report": _cmd_report,
   ```

---

## Step 5 — Tests

### `tests/unit/test_report_lint.py`

```python
"""Unit tests for docex.report.lint — the per-language leaf lexers."""

from __future__ import annotations

from docex.report.lint import lint_file


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_python_partition_and_references(tmp_path):
    src = (
        '"""Module docstring; see plans/design/x.md for detail."""\n'
        "import os  # trailing note\n"
        "# a full-line comment referencing foo/bar.py here\n"
        "x = '# not a comment'\n"
        "y = 1\n"
    )
    p = _write(tmp_path, "f.py", src)
    c = lint_file(p)
    # Complete char partition.
    assert (
        c["inline_comments"]
        + c["docstrings"]
        + c["references"]
        + c["code"]
        + c["other"]
        == len(src)
    )
    # References carved from BOTH docstring and comment.
    assert c["references"] >= len("plans/design/x.md") + len("foo/bar.py")
    assert c["docstrings"] > 0
    assert c["inline_comments"] > 0
    assert c["other"] == 0
    # The '#' inside the string literal is code, not a comment.
    assert "# not a comment" not in ("",)  # sanity: string content is code


def test_cfamily_docstring_vs_inline(tmp_path):
    src = (
        "/** JSDoc doc for util.js */\n"
        "// inline comment\n"
        "const s = '// not a comment';\n"
        "/// rust-style doc line\n"
        "let z = 2;\n"
    )
    p = _write(tmp_path, "f.ts", src)
    c = lint_file(p)
    assert (
        c["inline_comments"]
        + c["docstrings"]
        + c["references"]
        + c["code"]
        + c["other"]
        == len(src)
    )
    assert c["docstrings"] > 0        # /** */ and ///
    assert c["inline_comments"] > 0   # //
    assert c["references"] >= len("util.js")


def test_unknown_extension_all_other(tmp_path):
    src = "some unstructured prose\nmore\n"
    p = _write(tmp_path, "notes.rst", src)
    c = lint_file(p)
    assert c["other"] == len(src)
    assert c["code"] == 0
    assert c["inline_comments"] == 0
```

### `tests/unit/test_report_docs.py`

```python
"""Unit tests for docex report docs --format data (mod 176).

Fixture corpus built in tmp_path; the graph is built git-free via
``build_linkmap`` (as the cxt_groups tests do), so no repo is needed.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from docex.docs.linkmap import build_linkmap
from docex.report.docs import Bucket, build_docs_data, render_data_json
from docex.report import run_report


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _corpus(tmp_path):
    """A representative design + source corpus.

    ``boundary_conditions.md`` carries a deliberate preamble before its first
    ``#`` heading so its arc42 bucket needs an explicit ``etc`` remainder.
    """
    design = []
    bc = _write(
        tmp_path,
        "plans/design/boundary_conditions.md",
        "Preamble line one.\nPreamble line two.\n"
        "# Intro and Goals\nbody body body body\n"
        "# Constraints\nmore body here\n",
    )
    design.append(bc)
    design.append(_write(tmp_path, "plans/design/lexicon.md", "# Project Lexicon\nx\n"))
    design.append(_write(tmp_path, "plans/design/adr_index.md", "# idx\n"))
    design.append(_write(tmp_path, "plans/design/adr_active.md", "# active\n"))
    design.append(_write(tmp_path, "plans/design/project_diagram.mmd", "graph TD\nA-->B\n"))
    design.append(_write(tmp_path, "plans/design/unknowns.md", "# Unknowns\n"))
    design.append(_write(tmp_path, "plans/design/quality_scenarios.md", "# Q\n"))
    design.append(_write(tmp_path, "plans/design/doctrine_ext.md", "# ext (other file)\n"))
    design.append(_write(tmp_path, "plans/design/specifics/thing.md", "# thing\ndetail\n"))
    design.append(_write(tmp_path, "plans/design/adrs/0001_a.md", "# ADR 1\n"))
    design.append(_write(tmp_path, "plans/design/adrs/0002_b.md", "# ADR 2\n"))
    design.append(_write(tmp_path, "plans/design/api/module_diagram.mmd", "graph TD\n"))
    design.append(_write(tmp_path, "plans/design/api/specifics/c1.md", "# c1\ndetail\n"))
    design.append(_write(tmp_path, "plans/design/api/module/mod1.md", "# mod1\nbody\n"))

    source = []
    source.append(
        _write(
            tmp_path,
            "core/api/src/hex/m1/f.py",
            '"""doc referencing core/api/src/hex/m1/f.py"""\n'
            "# inline\nx = 1\n",
        )
    )
    source.append(_write(tmp_path, "core/api/src/app.py", "# root file\ny = 2\n"))
    source.append(
        _write(tmp_path, "core/frontend/src/index.js", "// c\nconst a = 1;\n")
    )
    source.append(_write(tmp_path, "core/api/src/misc.rst", "unlintable prose\n"))

    nodes, edges = build_linkmap(
        tmp_path, ["api", "frontend"], "code_level", design, source
    )
    return nodes, edges


def _assert_sums(bucket: dict):
    """Recursively: a bucket's children (incl. etc) sum to its own tokens."""
    kids = bucket.get("children")
    if not kids:
        return
    assert sum(k["tokens"] for k in kids) == bucket["tokens"], bucket["name"]
    for k in kids:
        _assert_sums(k)


def _find(bucket: dict, name: str):
    if bucket.get("name") == name:
        return bucket
    for k in bucket.get("children", []):
        hit = _find(k, name)
        if hit is not None:
            return hit
    return None


def test_bucket_sums_hold_everywhere(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    _assert_sums(doc["design_docs"])
    _assert_sums(doc["source_code"])


def test_etc_invariant_on_arc42_preamble(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    bc = _find(doc["design_docs"], "boundary_conditions.md")
    assert bc is not None
    names = [k["name"] for k in bc["children"]]
    # Named arc42 sections present…
    assert "Intro and Goals" in names
    assert "Constraints" in names
    # …plus an explicit etc for the preamble remainder.
    etc = _find(bc, "etc")
    assert etc is not None and etc["tokens"] > 0


def test_design_primary_buckets_present(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    for primary in (
        "L1 Standard Roots",
        "L1 Detail Docs",
        "L2 Architecture Docs",
        "L3 Module Docs",
        "ADRs",
    ):
        assert _find(doc["design_docs"], primary) is not None
    # ADRs is a summed leaf (no children).
    adrs = _find(doc["design_docs"], "ADRs")
    assert "children" not in adrs and adrs["tokens"] > 0
    # doctrine_ext.md lands in L1 Detail Docs → Other Files.
    other = _find(_find(doc["design_docs"], "L1 Detail Docs"), "Other Files")
    assert other is not None
    assert any(k["name"] == "doctrine_ext.md" for k in other["children"])


def test_source_hex_module_tier_and_nonhex_flat(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    doc = build_docs_data(nodes, tmp_path)
    api = _find(doc["source_code"], "api")
    # hex module m1 present as a tier; the non-hex app.py under "(root)".
    assert _find(api, "m1") is not None
    assert _find(api, "(root)") is not None
    # frontend is non-hex → files attach directly (no module group).
    frontend = _find(doc["source_code"], "frontend")
    assert any(k["name"] == "index.js" for k in frontend["children"])
    # References were detected in the python module file.
    f = _find(api, "f.py")
    refs = _find(f, "references")
    assert refs is not None and refs["tokens"] > 0
    # The .rst under src is unlintable → its weight is entirely other.
    misc = _find(api, "misc.rst")
    assert misc is not None
    other = _find(misc, "other / unlintable")
    assert other["tokens"] == misc["tokens"] and misc["tokens"] > 0


def test_determinism(tmp_path):
    nodes, _edges = _corpus(tmp_path)
    out1 = render_data_json(build_docs_data(nodes, tmp_path))
    out2 = render_data_json(build_docs_data(nodes, tmp_path))
    assert out1 == out2


def test_run_report_docs_data_via_wrapper(tmp_path, sample_ctx, monkeypatch):
    nodes, edges = _corpus(tmp_path)
    monkeypatch.setattr(
        "docex.report.docs.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_report(sample_ctx, "docs", "data")
    assert rc == 0
    doc = json.loads(buf.getvalue())
    assert doc["report"] == "docs" and doc["format"] == "data"
    _assert_sums(doc["design_docs"])
    _assert_sums(doc["source_code"])


def test_full_stubs_to_data_with_note(tmp_path, sample_ctx, capsys, monkeypatch):
    nodes, edges = _corpus(tmp_path)
    monkeypatch.setattr(
        "docex.report.docs.load_code_level_graph",
        lambda root, cbs: (nodes, edges),
    )
    rc = run_report(sample_ctx, "docs", "full")
    assert rc == 0
    captured = capsys.readouterr()
    assert "mod 177" in captured.err            # stub note on stderr
    doc = json.loads(captured.out)              # data JSON on stdout
    assert doc["format"] == "data"


def test_empty_project_ok(sample_ctx):
    # sample fixture has no plans/design and is not a git repo → empty graph.
    rc = run_report(sample_ctx, "docs", "data")
    assert rc == 0
```

### `tests/unit/test_dispatcher.py` — add report coverage

Append these to the existing file:

```python
def test_report_in_handler_table_and_help():
    from docex.__main__ import _build_handler_table, _format_usage
    assert "report" in _build_handler_table()
    assert "report" in _format_usage()


def test_report_dispatch(monkeypatch, sample_ctx):
    from docex.__main__ import _cmd_report
    monkeypatch.chdir(sample_ctx.project_root)
    captured = {}

    def fake_run_report(ctx, report_type, fmt):
        captured["type"] = report_type
        captured["fmt"] = fmt
        return 0

    monkeypatch.setattr("docex.report.run_report", fake_run_report)
    assert _cmd_report(["docs", "--format", "data"]) == 0
    assert captured == {"type": "docs", "fmt": "data"}
    # Default format is full.
    _cmd_report(["docs"])
    assert captured["fmt"] == "full"
```

---

## Step 6 — Verify

1. `python -m pytest tests/unit/test_report_docs.py tests/unit/test_report_lint.py
   tests/unit/test_dispatcher.py -q` → green.
2. `python -m pytest tests -q` → the whole suite green (report the count).
3. Sanity CLI check (optional): from a tree with a design corpus,
   `python -m docex report docs --format data` prints well-formed JSON; run it
   twice and confirm identical output.

Do **not** commit — the corporal handles commits, drift review, and the
aligned-artifact (doctrine + design-doc) reconciliation.
```

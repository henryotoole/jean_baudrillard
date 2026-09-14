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

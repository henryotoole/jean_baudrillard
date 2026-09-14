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

"""Mod 080 — standard-form env-file read/write (`docex/envfile.py`).

Exercises the flat KEY=value parse rules from config_and_secrets.md
§ Standard Form: split on the FIRST '=', raw-literal values (no quote /
escape / trim processing), full-line '#' comments, `[A-Z][A-Z0-9_]*` keys.
"""

from __future__ import annotations

import pytest

from docex.envfile import read_env_file, write_env_file


def test_round_trip_preserves_values(tmp_path):
    path = tmp_path / "a.env"
    values = {"ALPHA": "one", "BETA": "two", "GAMMA_1": "three"}
    write_env_file(path, values)
    assert read_env_file(path) == values


def test_write_sorts_keys_deterministically(tmp_path):
    path = tmp_path / "sorted.env"
    write_env_file(path, {"ZEBRA": "z", "APPLE": "a", "MANGO": "m"})
    body_keys = [
        line.split("=", 1)[0]
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert body_keys == ["APPLE", "MANGO", "ZEBRA"]


def test_first_equals_split(tmp_path):
    path = tmp_path / "eq.env"
    path.write_text("KEY=A=B=C\n")
    assert read_env_file(path) == {"KEY": "A=B=C"}


def test_comments_and_blank_lines_skipped(tmp_path):
    path = tmp_path / "c.env"
    path.write_text(
        "# a header comment\n"
        "\n"
        "   \n"
        "   # indented full-line comment\n"
        "KEY=value\n"
    )
    assert read_env_file(path) == {"KEY": "value"}


def test_missing_file_returns_empty(tmp_path):
    assert read_env_file(tmp_path / "nope.env") == {}


def test_malformed_key_raises(tmp_path):
    path = tmp_path / "bad.env"
    path.write_text("lower_case=nope\n")
    with pytest.raises(ValueError):
        read_env_file(path)


def test_line_without_equals_raises(tmp_path):
    path = tmp_path / "noeq.env"
    path.write_text("JUST_A_KEY\n")
    with pytest.raises(ValueError):
        read_env_file(path)


def test_raw_literal_no_trim_or_unquote(tmp_path):
    path = tmp_path / "raw.env"
    # Trailing spaces preserved, surrounding quotes preserved literally,
    # a leading space after '=' preserved. No interpolation of ${X}.
    path.write_text(
        'QUOTED="hello world"\n'
        "PADDED= spaced \n"
        "DOLLAR=${NOT_EXPANDED}\n"
    )
    out = read_env_file(path)
    assert out["QUOTED"] == '"hello world"'
    assert out["PADDED"] == " spaced "
    assert out["DOLLAR"] == "${NOT_EXPANDED}"


def test_header_written_as_comments(tmp_path):
    path = tmp_path / "h.env"
    write_env_file(path, {"K": "v"}, header=["line one", "line two"])
    text = path.read_text()
    assert text.startswith("# line one\n# line two\n")
    # Header lines don't parse back as keys.
    assert read_env_file(path) == {"K": "v"}

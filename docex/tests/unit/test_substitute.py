"""Tests for the three-syntax substitution grammar."""

from __future__ import annotations

import pytest

from docex.cicl.substitute import (
    HCLLiteral,
    substitute_string,
    substitute_tree,
)
from docex.errors import HCLInFixedError, SubstitutionError


# ---- compile-time substitution ${var} ----------------------------------


def test_simple_compile_time_substitution():
    rendered = substitute_string("hello ${name}", {"name": "world"}, foundation="fixed")
    assert rendered.value == "hello world"
    assert rendered.raw_hcl is False
    assert rendered.runtime_refs == set()


def test_multiple_compile_time_subs():
    rendered = substitute_string(
        "${project}_${env}_${svc}",
        {"project": "p", "env": "dev", "svc": "api"},
        foundation="fixed",
    )
    assert rendered.value == "p_dev_api"


def test_undefined_compile_time_raises():
    with pytest.raises(SubstitutionError) as exc:
        substitute_string("${missing}", {}, foundation="fixed")
    assert "missing" in str(exc.value)


def test_hyphenated_compile_var_raises_rather_than_passing_through():
    """Regression pin (Mod 097). `_COMPILE_RE` excluded '-', so a mistyped
    `${env-name}` matched no pattern at all and survived substitution into
    the emitted compose/HCL as literal text. It must fail loudly instead.
    Note there is no escape form for a genuinely literal `${a-b}`; the
    grammar has exactly ${var}, $[var], @expr."""
    with pytest.raises(SubstitutionError) as exc:
        substitute_string("${some-var}", {}, foundation="fixed")
    assert "some-var" in str(exc.value)


def test_compile_time_with_dotted_name():
    # Magic-ref-like dotted names are parsed by the compile-time matcher,
    # but resolved via the magic-ref layer. For substitute_string alone,
    # a dotted name in ctx works literally.
    rendered = substitute_string("${a.b.c}", {"a.b.c": "value"}, foundation="fixed")
    assert rendered.value == "value"


# ---- runtime substitution $[var] ---------------------------------------


def test_runtime_passthrough_left_alone():
    rendered = substitute_string(
        "user=$[POSTGRES_USER]", {}, foundation="fixed"
    )
    assert rendered.value == "user=$[POSTGRES_USER]"
    assert rendered.runtime_refs == {"POSTGRES_USER"}


def test_runtime_refs_collected_across_template():
    rendered = substitute_string(
        "$[A]/$[B]/$[A]", {}, foundation="fixed",
    )
    assert rendered.value == "$[A]/$[B]/$[A]"
    assert rendered.runtime_refs == {"A", "B"}


# ---- HCL pass-through @ ------------------------------------------------


def test_hcl_passthrough_marks_value():
    rendered = substitute_string(
        "@aws_db_instance.x.endpoint", {}, foundation="elastic",
    )
    assert rendered.raw_hcl is True
    assert rendered.value == "aws_db_instance.x.endpoint"


def test_hcl_with_embedded_compile_var():
    rendered = substitute_string(
        "@aws_db_instance.${name}.endpoint",
        {"name": "db1"},
        foundation="elastic",
    )
    assert rendered.raw_hcl is True
    assert rendered.value == "aws_db_instance.db1.endpoint"


def test_hcl_in_fixed_raises():
    with pytest.raises(HCLInFixedError):
        substitute_string("@anything", {}, foundation="fixed")


# ---- mixed syntax ------------------------------------------------------


def test_mixed_syntax():
    rendered = substitute_string(
        "${prefix}-$[VAR]-x",
        {"prefix": "P"},
        foundation="fixed",
    )
    assert rendered.value == "P-$[VAR]-x"
    assert rendered.runtime_refs == {"VAR"}


# ---- substitute_tree --------------------------------------------------


def test_substitute_tree_dict_and_list():
    tree = {
        "name": "${name}",
        "list": ["a", "${name}", "$[X]"],
        "nested": {"inner": "@${name}"},
    }
    out = substitute_tree(tree, {"name": "n"}, foundation="elastic")
    assert out["name"] == "n"
    assert out["list"] == ["a", "n", "$[X]"]
    inner = out["nested"]["inner"]
    assert isinstance(inner, HCLLiteral)
    assert str(inner) == "n"


def test_substitute_tree_preserves_non_strings():
    tree = {"a": 1, "b": True, "c": None, "d": 3.14}
    out = substitute_tree(tree, {}, foundation="fixed")
    assert out == tree

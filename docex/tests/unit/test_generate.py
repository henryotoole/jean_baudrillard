"""Mod 076: generation policies + the CSPRNG value generator."""

from __future__ import annotations

import string

import pytest

from docex.cicl.generate import (
    GenerationPolicy,
    generate,
    parse_generation_policies,
)
from docex.errors import TransferTableError


def test_generate_respects_length_and_alphabet():
    policy = GenerationPolicy(name="p", length=40, alphabet="url_safe")
    val = generate(policy)
    assert len(val) == 40
    allowed = set(string.ascii_letters + string.digits + "-_")
    assert set(val) <= allowed


def test_generate_url_safe_alphabet_membership():
    """url_safe includes `-`/`_` and excludes unsafe URL chars."""
    policy = GenerationPolicy(name="p", length=5000, alphabet="url_safe")
    val = generate(policy)
    # Over 5000 draws every alphabet member should appear at least once.
    assert "-" in val and "_" in val
    for bad in "@:/#?%&+":
        assert bad not in val


def test_generate_alnum_excludes_dash_and_underscore():
    policy = GenerationPolicy(name="p", length=5000, alphabet="alnum")
    val = generate(policy)
    assert "-" not in val and "_" not in val
    assert set(val) <= set(string.ascii_letters + string.digits)


def test_generate_is_random_across_calls():
    policy = GenerationPolicy(name="p", length=32, alphabet="url_safe")
    # CSPRNG: collision across a handful of 32-char draws is astronomically
    # unlikely, so all distinct.
    vals = {generate(policy) for _ in range(5)}
    assert len(vals) == 5


def test_parse_shipped_password_policy():
    policies = parse_generation_policies(
        {"password": {"length": 32, "alphabet": "url_safe"}}
    )
    p = policies.get("password")
    assert p.length == 32
    assert p.alphabet == "url_safe"


def test_parse_rejects_unknown_alphabet():
    with pytest.raises(TransferTableError) as exc:
        parse_generation_policies({"p": {"length": 8, "alphabet": "base64"}})
    assert "alphabet" in str(exc.value)


def test_parse_rejects_non_positive_length():
    with pytest.raises(TransferTableError):
        parse_generation_policies({"p": {"length": 0, "alphabet": "alnum"}})


def test_parse_rejects_non_int_length():
    with pytest.raises(TransferTableError):
        parse_generation_policies({"p": {"length": "8", "alphabet": "alnum"}})


def test_get_unknown_policy_raises():
    policies = parse_generation_policies({})
    with pytest.raises(TransferTableError):
        policies.get("nope")

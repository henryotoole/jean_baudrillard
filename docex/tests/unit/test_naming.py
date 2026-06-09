"""Unit tests for the naming-policy primitive.

Covers:
- ``apply_policy`` translates underscores ↔ hyphens, lowercases when
  asked, and raises on max-len overflow.
- ``parse_policies`` rejects malformed entries.
- ``NamingPolicies.get`` errors clearly on unknown policy names.
"""

from __future__ import annotations

import pytest

from docex.errors import TransferTableError
from docex.naming import NamingPolicies, NamingPolicy, apply_policy, parse_policies


def test_apply_policy_hyphen_translates_underscores():
    policy = NamingPolicy(name="s3", separator="hyphen", case="lower", max_len=None)
    assert apply_policy("docex_smoke_elastic_tofu_state", policy) == (
        "docex-smoke-elastic-tofu-state"
    )


def test_apply_policy_underscore_translates_hyphens_back():
    # Synthetic underscore policy — exercises apply_policy's hyphen→underscore
    # translation, decoupled from any doctrine policy.
    policy = NamingPolicy(name="iam", separator="underscore", case="any", max_len=None)
    assert apply_policy("foo-bar-baz", policy) == "foo_bar_baz"


def test_apply_policy_case_lower():
    # Synthetic lowercasing policy — `s3` happens to be lowercasing in
    # doctrine; using it here is fine as we're testing apply_policy mechanics.
    policy = NamingPolicy(name="s3", separator="underscore", case="lower", max_len=None)
    assert apply_policy("Project_Name", policy) == "project_name"


def test_apply_policy_case_any_preserves_case():
    policy = NamingPolicy(name="iam", separator="underscore", case="any", max_len=None)
    assert apply_policy("Project_Name", policy) == "Project_Name"


def test_apply_policy_max_len_overflow_raises():
    policy = NamingPolicy(name="rds", separator="hyphen", case="lower", max_len=8)
    with pytest.raises(TransferTableError) as exc_info:
        apply_policy("this_is_too_long", policy)
    msg = str(exc_info.value)
    assert "max_len" in msg
    assert "rds" in msg


def test_apply_policy_no_max_len_allows_long_names():
    policy = NamingPolicy(name="ssm_path", separator="underscore", case="any", max_len=None)
    long = "a" * 500
    assert apply_policy(long, policy) == long


def test_parse_policies_happy_path():
    raw = {
        "s3": {"separator": "hyphen", "case": "lower", "max_len": 63},
        "ecs": {"separator": "hyphen", "case": "any"},
    }
    policies = parse_policies(raw)
    s3 = policies.get("s3")
    assert s3.separator == "hyphen"
    assert s3.case == "lower"
    assert s3.max_len == 63
    ecs = policies.get("ecs")
    assert ecs.separator == "hyphen"
    assert ecs.case == "any"
    assert ecs.max_len is None


def test_parse_policies_empty_input():
    assert parse_policies({}).by_name == {}
    assert parse_policies(None).by_name == {}  # type: ignore[arg-type]


def test_parse_policies_rejects_bad_separator():
    raw = {"oops": {"separator": "comma"}}
    with pytest.raises(TransferTableError) as exc_info:
        parse_policies(raw)
    assert "separator" in str(exc_info.value)


def test_parse_policies_rejects_bad_case():
    raw = {"oops": {"separator": "hyphen", "case": "title"}}
    with pytest.raises(TransferTableError) as exc_info:
        parse_policies(raw)
    assert "case" in str(exc_info.value)


def test_parse_policies_rejects_non_int_max_len():
    raw = {"oops": {"separator": "hyphen", "max_len": "lots"}}
    with pytest.raises(TransferTableError) as exc_info:
        parse_policies(raw)
    assert "max_len" in str(exc_info.value)


def test_parse_policies_rejects_non_mapping():
    raw = {"oops": "not-a-dict"}
    with pytest.raises(TransferTableError):
        parse_policies(raw)


def test_get_unknown_policy_raises_clearly():
    policies = NamingPolicies(by_name={})
    with pytest.raises(TransferTableError) as exc_info:
        policies.get("nonexistent")
    msg = str(exc_info.value)
    assert "unknown naming policy" in msg
    assert "nonexistent" in msg

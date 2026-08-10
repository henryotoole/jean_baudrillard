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
from docex.naming import (
    NamingPolicies,
    NamingPolicy,
    apply_policy,
    dns_label,
    ecs_cluster_name,
    parse_policies,
)


def test_dns_label_hyphenates_and_lowercases():
    assert dns_label("docex_smoke_elastic") == "docex-smoke-elastic"
    assert dns_label("MyProject") == "myproject"
    assert dns_label("already-fine") == "already-fine"


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


# --- overflow: hash_truncate (mod 069) -------------------------------------

_ALB = NamingPolicy(
    name="alb", separator="hyphen", case="any", max_len=32,
    overflow="hash_truncate",
)


def test_hash_truncate_fits_and_has_hash_suffix():
    out = apply_policy("tactical_lifecycle_test_stage_web_tg", _ALB)
    assert len(out) <= 32
    # ends with `-` + 6 hex chars
    assert out[-7] == "-"
    assert all(c in "0123456789abcdef" for c in out[-6:])


def test_hash_truncate_is_deterministic():
    name = "tactical_lifecycle_test_stage_web_tg"
    assert apply_policy(name, _ALB) == apply_policy(name, _ALB)


def test_hash_truncate_distinct_for_shared_prefix():
    # Identical in the first 25 chars, differ later — the truncated
    # readable prefixes collide but the full-name hashes must not.
    a = "shared_prefix_xxxxxxxxxxx_alpha_service_tg"
    b = "shared_prefix_xxxxxxxxxxx_bravo_service_tg"
    assert a[:25] == b[:25]
    assert apply_policy(a, _ALB) != apply_policy(b, _ALB)


def test_hash_truncate_no_double_hyphen():
    # A name whose truncation boundary lands on a separator must not emit
    # `foo--<hash>`.
    out = apply_policy("aaaaaaaaaaaaaaaaaaaaaaaa_bbbb_cccc_tg", _ALB)
    assert "--" not in out


def test_error_overflow_default_still_raises():
    policy = NamingPolicy(name="rds", separator="hyphen", case="lower", max_len=8)
    assert policy.overflow == "error"
    with pytest.raises(TransferTableError):
        apply_policy("this_is_too_long", policy)


def test_within_limit_untouched_regardless_of_overflow():
    out = apply_policy("short_web_tg", _ALB)
    assert out == "short-web-tg"


def test_parse_policies_rejects_bad_overflow():
    raw = {"oops": {"separator": "hyphen", "overflow": "truncate"}}
    with pytest.raises(TransferTableError) as exc_info:
        parse_policies(raw)
    assert "overflow" in str(exc_info.value)


def test_parse_policies_accepts_known_overflow_values():
    raw = {
        "a": {"separator": "hyphen", "overflow": "error"},
        "b": {"separator": "hyphen", "overflow": "hash_truncate"},
        "c": {"separator": "hyphen"},  # default
    }
    policies = parse_policies(raw)
    assert policies.get("a").overflow == "error"
    assert policies.get("b").overflow == "hash_truncate"
    assert policies.get("c").overflow == "error"


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


# ---------------------------------------------------------------------------
# Mod 128 — the ECS cluster-name helper.
# ---------------------------------------------------------------------------


def _real_policies():
    """The `ecs` policy as actually shipped in the transfer tables, not a
    hand-rolled stand-in — the point of the helper is that it agrees with what
    the emitters produce."""
    from docex.cicl.transfer import load_transfer_tables

    return load_transfer_tables(None).naming_policies


def test_ecs_cluster_name_hyphenates_an_underscored_project():
    """The `ecs` policy is hyphen/lower, so an underscored project name renders
    as the DNS-label form the cluster (and the env's Service Connect namespace)
    actually carries."""
    policies = _real_policies()
    assert ecs_cluster_name("docex_smoke_elastic", "stage", policies) == (
        "docex-smoke-elastic-stage"
    )
    assert ecs_cluster_name("sample", "prod", policies) == "sample-prod"


def test_ecs_cluster_name_matches_every_lifted_call_site():
    """Mod 128 lifted this from four verbatim `apply_policy(f"{project}_{env}",
    ecs_policy)` copies — release.py, orchestrate/migrate.py, projinfra.py, and
    emit/hcl.py (which *emits* the clusters the other three read). Pin that the
    helper produces the identical string, so the lift cannot have changed a name
    that real infrastructure already answers to."""
    policies = _real_policies()
    for project in ("sample", "docex_smoke_elastic", "Mixed_Case"):
        for env in ("stage", "prod"):
            assert ecs_cluster_name(project, env, policies) == apply_policy(
                f"{project}_{env}", policies.get("ecs")
            )


def test_ecs_cluster_name_takes_primitives_and_adds_no_imports():
    """`naming.py` is a low-level module: importing `docex.context` to accept a
    ProjectContext would create a cycle. Taking primitives is what buys that, so
    pin it — a future signature change to `(ctx, env)` would compile and then
    break the import graph."""
    import inspect

    from docex import naming

    params = inspect.signature(ecs_cluster_name).parameters
    assert list(params) == ["project_name", "env", "policies"]
    imports = [
        line.strip()
        for line in inspect.getsource(naming).splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert not any("context" in line for line in imports), imports

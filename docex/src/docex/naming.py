"""Naming policies.

Per ``transfer_tables.md § Naming Policies``, name interpolation is
governed by a small, named set of policies that map "AWS resource type"
to "how to format an identifier." Engines reference a policy by name
(``naming: rds``); structural emitters in docex code reference one by
hardcoded name (``apply_policy(..., policy_name="s3")``).

This module exposes:

- ``NamingPolicy`` — the dataclass form of one policy.
- ``NamingPolicies`` — the loaded table, keyed by policy name.
- ``apply_policy(name, policy)`` — the single translation entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from docex.errors import TransferTableError

# Per transfer_tables.md § Failure-mode contract — strict allowlist of
# the keys a naming-policy body may contain. Anything else is a hard
# error at load time.
_ALLOWED_POLICY_KEYS: frozenset[str] = frozenset({
    "separator",
    "case",
    "max_len",
})


def _validate_policy_keys(
    display_path: str, name: str, body: dict
) -> None:
    """Strictly validate a naming-policy body's keys. Source-attributed.

    Called from transfer.py::_validate_file during the per-file pass,
    before policies are merged across layers. The structural value
    checks (separator/case/max_len semantics) still happen in
    parse_policies — this function is only the unknown-key gate.
    """
    # WHY: lazy import — transfer.py imports naming.py at module load
    # so a top-level import here would create a circular dependency.
    from docex.cicl.transfer import _did_you_mean
    for key in body:
        if key not in _ALLOWED_POLICY_KEYS:
            raise TransferTableError(
                f"{display_path}: naming_policies.{name}: "
                f"unknown key {key!r}"
                + _did_you_mean(key, _ALLOWED_POLICY_KEYS)
            )


@dataclass(frozen=True)
class NamingPolicy:
    """One naming policy.

    Attributes mirror the per-engine ``naming:`` block as documented in
    ``transfer_tables.md``. The schema is intentionally narrow: binary
    separator choice, optional case lowercasing, optional max-length
    ceiling.
    """

    name: str
    separator: str  # 'underscore' | 'hyphen'
    case: str       # 'any' | 'lower'
    max_len: int | None


@dataclass(frozen=True)
class NamingPolicies:
    """Loaded set of policies, keyed by name."""

    by_name: Mapping[str, NamingPolicy]

    def get(self, policy_name: str) -> NamingPolicy:
        if policy_name not in self.by_name:
            raise TransferTableError(
                f"unknown naming policy {policy_name!r}; defined: "
                f"{sorted(self.by_name)}"
            )
        return self.by_name[policy_name]


def parse_policies(raw: dict) -> NamingPolicies:
    """Parse a transfer-table ``naming_policies:`` block."""
    by_name: dict[str, NamingPolicy] = {}
    for name, body in (raw or {}).items():
        if not isinstance(body, dict):
            raise TransferTableError(
                f"naming_policies.{name}: expected a mapping"
            )
        sep = body.get("separator")
        if sep not in ("underscore", "hyphen"):
            raise TransferTableError(
                f"naming_policies.{name}.separator must be "
                f"'underscore' or 'hyphen' (got {sep!r})"
            )
        case = body.get("case", "any")
        if case not in ("any", "lower"):
            raise TransferTableError(
                f"naming_policies.{name}.case must be "
                f"'any' or 'lower' (got {case!r})"
            )
        max_len = body.get("max_len")
        if max_len is not None and not isinstance(max_len, int):
            raise TransferTableError(
                f"naming_policies.{name}.max_len must be an int or absent"
            )
        by_name[name] = NamingPolicy(
            name=name, separator=sep, case=case, max_len=max_len
        )
    return NamingPolicies(by_name=by_name)


def dns_label(name: str) -> str:
    """A name as a DNS label (underscores → hyphens, lowercased).

    Single source of truth for the rule that turns an underscored
    project name (``docex_smoke_elastic``) into a DNS-valid label
    (``docex-smoke-elastic``). Used both when emitting hostnames and
    when *displaying* resource names so logs match what was emitted.
    """
    return name.replace("_", "-").lower()


def apply_policy(name: str, policy: NamingPolicy) -> str:
    """Apply one naming policy to an assembled identifier.

    The compiler always joins parts with ``_`` internally; this function
    decides whether to keep them or translate to ``-``. If ``case`` is
    ``lower``, the result is lowercased. If ``max_len`` is set and the
    result exceeds it, a clear error is raised — silent truncation is a
    known footgun and the doctrine prefers a clean compile-time failure
    (per ``transfer_tables.md`` validation rule).
    """
    if policy.separator == "hyphen":
        out = name.replace("_", "-")
    else:
        out = name.replace("-", "_")
    if policy.case == "lower":
        out = out.lower()
    if policy.max_len is not None and len(out) > policy.max_len:
        raise TransferTableError(
            f"name {out!r} exceeds policy {policy.name!r} max_len "
            f"{policy.max_len}; shorten project/env/service names"
        )
    return out

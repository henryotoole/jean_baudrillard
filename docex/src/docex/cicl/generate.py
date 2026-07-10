"""Generation policies + the value generator.

Per ``transfer_tables.md § Generation Policies``, a ``kind: minted``
engine env var is produced by ``docex`` rather than supplied by the
operator. A **generation policy** describes how to mint such a value:
a length and a named character-set alphabet. Engines reference a policy
by name via a minted env var's ``policy:`` field.

This is a deliberate sibling to — not part of — naming policies
(``naming.py``): a naming policy drives a *formatter* that reshapes an
existing identifier; a generation policy drives a *generator* that
produces a fresh random value. Keeping them apart keeps both the
formatter/generator surfaces and their load-time allowlists clean.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Mapping

from docex.errors import TransferTableError

# Per transfer_tables.md § Failure-mode contract — strict allowlist of
# the keys a generation-policy body may contain.
_ALLOWED_GENERATION_POLICY_KEYS: frozenset[str] = frozenset({
    "length",
    "alphabet",
})

# Named character sets a policy may draw from. `url_safe` is load-bearing,
# not incidental: under the parts-only rule the application composes its
# own connection string from parts, so a password containing `@ : / # ? %
# & +` breaks a naive `scheme://user:pass@host/db`; AWS RDS independently
# forbids `/ @ "` and spaces in the master password. `url_safe`
# ([A-Za-z0-9] plus `-` and `_`) is the intersection safe for both. See
# transfer_tables.md § Generation Policies.
_ALPHABETS: dict[str, str] = {
    "url_safe": string.ascii_letters + string.digits + "-_",
    "alnum": string.ascii_letters + string.digits,
}


def _validate_generation_policy_keys(
    display_path: str, name: str, body: dict
) -> None:
    """Strictly validate a generation-policy body's keys. Source-attributed.

    Called from transfer.py::_validate_file during the per-file pass,
    before policies are merged across layers. The structural value checks
    (length/alphabet semantics) still happen in parse_generation_policies —
    this function is only the unknown-key gate.
    """
    # WHY: lazy import — transfer.py imports this module at load, so a
    # top-level import of _did_you_mean here would be circular.
    from docex.cicl.transfer import _did_you_mean
    for key in body:
        if key not in _ALLOWED_GENERATION_POLICY_KEYS:
            raise TransferTableError(
                f"{display_path}: generation_policies.{name}: "
                f"unknown key {key!r}"
                + _did_you_mean(key, _ALLOWED_GENERATION_POLICY_KEYS)
            )


@dataclass(frozen=True)
class GenerationPolicy:
    """One generation policy — a length and a named alphabet."""

    name: str
    length: int
    alphabet: str  # a key in _ALPHABETS


@dataclass(frozen=True)
class GenerationPolicies:
    """Loaded set of generation policies, keyed by name."""

    by_name: Mapping[str, GenerationPolicy]

    def get(self, policy_name: str) -> GenerationPolicy:
        if policy_name not in self.by_name:
            raise TransferTableError(
                f"unknown generation policy {policy_name!r}; defined: "
                f"{sorted(self.by_name)}"
            )
        return self.by_name[policy_name]


def parse_generation_policies(raw: dict) -> GenerationPolicies:
    """Parse a transfer-table ``generation_policies:`` block."""
    by_name: dict[str, GenerationPolicy] = {}
    for name, body in (raw or {}).items():
        if not isinstance(body, dict):
            raise TransferTableError(
                f"generation_policies.{name}: expected a mapping"
            )
        length = body.get("length")
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise TransferTableError(
                f"generation_policies.{name}.length must be a positive int "
                f"(got {length!r})"
            )
        alphabet = body.get("alphabet")
        if alphabet not in _ALPHABETS:
            raise TransferTableError(
                f"generation_policies.{name}.alphabet must be one of "
                f"{sorted(_ALPHABETS)} (got {alphabet!r})"
            )
        by_name[name] = GenerationPolicy(
            name=name, length=length, alphabet=alphabet
        )
    return GenerationPolicies(by_name=by_name)


def generate(policy: GenerationPolicy) -> str:
    """Mint a fresh value of ``policy.length`` chars from its alphabet.

    Uses the stdlib ``secrets`` CSPRNG (never ``random``) — minted values
    are credentials. Generation is impure and never runs at compile time.
    """
    import secrets as _secrets
    alphabet = _ALPHABETS[policy.alphabet]
    return "".join(_secrets.choice(alphabet) for _ in range(policy.length))

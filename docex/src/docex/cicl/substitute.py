"""Three-syntax substitution engine for transfer-table templates.

The substitution grammar (see transfer_tables.md § Substitution
Grammar) defines three syntaxes, each resolved at a different stage:

    ${var}      compile-time. Resolved here against a context dict.
    $[var]      runtime pass-through. Left alone, but tracked.
    @<expr>     HCL pass-through (elastic only). The leading '@' is
                stripped; ${var} inside <expr> is resolved; the rest
                is marked as raw HCL for the emitter.

This module is the single source of truth for that grammar. The
compiler uses it on every template before handing values to emitters.

The output of a substitution is a ``RenderedValue`` carrying:
  - the resolved string,
  - whether the value is raw HCL (i.e. came from an ``@`` template),
  - the set of $[runtime_vars] referenced by the source template.

Emitters use these to translate to compose's ``${...}`` form or to
ECS's ``secrets[]`` block, and to know whether to quote an HCL value.

Magic refs (``${backing_services.X.Y}``) live in ``magic_refs.py`` and
are resolved *before* this module is called, by inlining the referenced
``provides:`` template into the substitution context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docex.errors import HCLInFixedError, SubstitutionError


# ${name} or ${a.b.c} — letters, digits, '.', '_'.
_COMPILE_RE = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")
# $[NAME] — runtime pass-through.
_RUNTIME_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


@dataclass
class RenderedValue:
    """Result of substituting a single string template."""

    value: str
    raw_hcl: bool = False
    runtime_refs: set[str] = field(default_factory=set)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


def _resolve_compile_time(template: str, ctx: dict[str, Any]) -> str:
    """Replace every ``${var}`` in ``template`` from ``ctx``."""
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in ctx:
            raise SubstitutionError(
                f"undefined compile-time variable ${{{name}}} (template: "
                f"{template!r}; available: {sorted(ctx)})"
            )
        v = ctx[name]
        if v is None:
            raise SubstitutionError(
                f"compile-time variable ${{{name}}} is None (template: "
                f"{template!r})"
            )
        return str(v)
    return _COMPILE_RE.sub(repl, template)


def _collect_runtime_refs(template: str) -> set[str]:
    return set(_RUNTIME_RE.findall(template))


def substitute_string(
    template: str,
    ctx: dict[str, Any],
    *,
    foundation: str,
) -> RenderedValue:
    """Apply the three-syntax substitution grammar to a single string.

    ``foundation`` ('fixed' | 'elastic') controls whether ``@`` syntax
    is legal: ``@<expr>`` in a fixed-target template is a hard error.
    """
    if not isinstance(template, str):
        raise TypeError(f"substitute_string expects str, got {type(template)!r}")

    raw_hcl = False
    body = template

    if body.startswith("@"):
        if foundation != "elastic":
            raise HCLInFixedError(
                f"HCL pass-through @-syntax is not allowed in fixed-target "
                f"templates: {template!r}"
            )
        raw_hcl = True
        body = body[1:]

    # Collect runtime refs from the *original* body (before compile-time subs).
    runtime_refs = _collect_runtime_refs(body)

    # Resolve compile-time vars.
    resolved = _resolve_compile_time(body, ctx)

    return RenderedValue(value=resolved, raw_hcl=raw_hcl, runtime_refs=runtime_refs)


def substitute_tree(
    node: Any,
    ctx: dict[str, Any],
    *,
    foundation: str,
    runtime_refs: set[str] | None = None,
) -> Any:
    """Recursively substitute all strings in a YAML-shaped tree.

    Returns a new tree. Collects all runtime refs encountered into the
    optional accumulator (callers that want to enumerate them should
    pass a fresh ``set()`` and read it after).

    Lists, dicts, and scalars are handled. Booleans, ints, floats, None
    pass through unchanged. Strings are run through ``substitute_string``;
    on success, ``raw_hcl`` rendered values are wrapped in
    ``_HCLLiteral`` so the emitter can recognize them.
    """
    if runtime_refs is None:
        runtime_refs = set()

    if isinstance(node, str):
        rendered = substitute_string(node, ctx, foundation=foundation)
        runtime_refs |= rendered.runtime_refs
        if rendered.raw_hcl:
            return HCLLiteral(rendered.value)
        return rendered.value
    if isinstance(node, dict):
        return {
            k: substitute_tree(v, ctx, foundation=foundation, runtime_refs=runtime_refs)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [
            substitute_tree(item, ctx, foundation=foundation, runtime_refs=runtime_refs)
            for item in node
        ]
    return node


class HCLLiteral(str):
    """A string subclass marking a value as raw HCL (no quoting at emit time).

    Subclasses ``str`` so it flows through YAML round-trips transparently;
    emitters check via ``isinstance(value, HCLLiteral)``.
    """

    __slots__ = ()


__all__ = [
    "HCLLiteral",
    "RenderedValue",
    "substitute_string",
    "substitute_tree",
]

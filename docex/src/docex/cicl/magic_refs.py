"""Magic-ref resolution.

A *magic ref* is a compile-time variable in ``infra.yml`` of the form

    ${backing_services.<service_name>.<part_name>}
    ${core_services.<service_name>.<part_name>}

It resolves by:

  1. Looking up the named service in the parsed ``infra.yml``.
  2. Finding that service's engine's ``provides:`` block in the
     transfer table.
  3. Substituting the foundation-appropriate template *in the
     referenced service's substitution context*.
  4. Recording the dependency for validation (cicl.md rule 7).

The resolved value may itself contain ``$[var]`` runtime refs or be a
raw HCL expression — both are propagated up to the caller as a
``RenderedValue``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docex.cicl.model import BackingService, CICLDocument, CoreService
from docex.cicl.substitute import (
    HCLLiteral,
    RenderedValue,
    _COMPILE_RE,
    substitute_string,
)
from docex.cicl.transfer import EngineEntry, TransferTables
from docex.errors import SubstitutionError


# Matches the magic-ref form ``${kind.name.part}`` where:
#   kind ∈ {core_services, backing_services}
_MAGIC_RE = re.compile(
    r"\$\{(core_services|backing_services)\.([a-zA-Z][a-zA-Z0-9_-]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\}"
)

# Same shape as substitute._RUNTIME_RE — a ``$[VAR]`` runtime ref.
_RUNTIME_REF_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


@dataclass
class MagicRefDependency:
    """One ``${kind.name.part}`` reference detected during compile."""

    consumer: str  # service name doing the referencing
    kind: str  # 'core_services' | 'backing_services'
    target: str  # service name being referenced
    part: str  # the provides[] part referenced


@dataclass
class MagicRefResolver:
    """Stateful resolver. One per compile invocation per env."""

    doc: CICLDocument
    tables: TransferTables
    foundation: str
    # ContextBuilder: service_name -> dict[str, Any]
    # Populated by the compiler before resolution.
    contexts: dict[str, dict[str, Any]] = field(default_factory=dict)
    engines: dict[str, EngineEntry] = field(default_factory=dict)
    # Output: dependency tracking and runtime ref accumulation.
    deps: list[MagicRefDependency] = field(default_factory=list)
    runtime_refs: dict[str, set[str]] = field(default_factory=dict)

    # Cycle guard.
    _resolving: set[tuple[str, str, str]] = field(default_factory=set)

    def resolve_in_string(
        self,
        template: str,
        consumer: str,
    ) -> RenderedValue:
        """Resolve all magic refs in ``template``.

        First pass: replace each ``${kind.name.part}`` with the
        rendered string from the target's ``provides:`` block. Second
        pass: run the result through normal substitution against the
        *consumer's* context.

        Returns a RenderedValue with combined runtime refs.
        """
        runtime_refs: set[str] = set()
        raw_hcl_flag = False

        # First pass: handle magic refs.
        def magic_repl(m: re.Match[str]) -> str:
            nonlocal raw_hcl_flag
            kind, target, part = m.group(1), m.group(2), m.group(3)
            self.deps.append(
                MagicRefDependency(consumer=consumer, kind=kind, target=target, part=part)
            )

            key = (kind, target, part)
            if key in self._resolving:
                raise SubstitutionError(
                    f"cyclic magic-ref chain through {kind}.{target}.{part}"
                )
            self._resolving.add(key)
            try:
                rendered = self._resolve_part(kind, target, part)
            finally:
                self._resolving.discard(key)

            if rendered.value == "":
                raise SubstitutionError(
                    f"magic ref ${{{kind}.{target}.{part}}} in {consumer!r} "
                    f"resolved to an empty value — {target!r}'s {part!r} field "
                    f"is unset and the engine declares no default for it."
                )
            runtime_refs.update(rendered.runtime_refs)
            if rendered.raw_hcl:
                raw_hcl_flag = True
                # Splice the HCL-pass-through value in place verbatim.
                # The caller's compile-time substitution does not touch
                # what's left because HCL refs do not look like ${var}.
                return rendered.value
            return rendered.value

        first_pass = _MAGIC_RE.sub(magic_repl, template)

        # Second pass: substitute against the consumer's context.
        ctx = self.contexts.get(consumer, {})
        # If the magic ref produced raw HCL, we mark the whole result
        # as HCL by prefixing '@' before falling through to substitute.
        # We've already resolved magic refs, so substitute_string will
        # only see ${name}, ${env_name}, etc.
        if raw_hcl_flag:
            # Strip any leading '@' the consumer template carried; we'll
            # re-add ours so the result is properly marked.
            body = first_pass[1:] if first_pass.startswith("@") else first_pass
            rendered = substitute_string("@" + body, ctx, foundation=self.foundation)
        else:
            rendered = substitute_string(first_pass, ctx, foundation=self.foundation)
        # Inline this consumer's own kind:fixed env vars to literals. A core
        # consumer has no fixed vars (no-op); a backing body inlines its engine's.
        rendered = self._inline_fixed(rendered, self.engines.get(consumer))
        rendered.runtime_refs |= runtime_refs

        # Track runtime refs by consumer for dependency propagation.
        self.runtime_refs.setdefault(consumer, set()).update(rendered.runtime_refs)
        return rendered

    def _resolve_part(self, kind: str, target: str, part: str) -> RenderedValue:
        # Look up target service.
        if kind == "core_services":
            svc = self.doc.core_services.get(target)
        elif kind == "backing_services":
            svc = self.doc.backing_services.get(target)
        else:
            raise SubstitutionError(
                f"magic ref kind must be core_services or backing_services, got {kind!r}"
            )
        if svc is None:
            raise SubstitutionError(
                f"magic ref ${{{kind}.{target}.{part}}} -> unknown service {target!r}"
            )

        engine = self.engines.get(target)
        if engine is None:
            raise SubstitutionError(
                f"magic ref ${{{kind}.{target}.{part}}} -> no engine resolved for service {target!r}"
            )

        provides = engine.provides_for(self.foundation)
        if part not in provides:
            raise SubstitutionError(
                f"magic ref ${{{kind}.{target}.{part}}} -> engine "
                f"{engine.engine!r} does not expose part {part!r} on "
                f"{self.foundation}; known: {sorted(provides)}"
            )

        template = provides[part]
        target_ctx = self.contexts.get(target, {})

        # Resolve any magic refs inside the provides template (rare but allowed).
        # We pass through resolve_in_string for the target as consumer.
        if _MAGIC_RE.search(template):
            return self._inline_fixed(
                self.resolve_in_string(template, consumer=target), engine
            )

        # Plain substitution against the *target's* context.
        return self._inline_fixed(
            substitute_string(template, target_ctx, foundation=self.foundation), engine
        )

    def _inline_fixed(
        self, rendered: RenderedValue, engine: EngineEntry | None
    ) -> RenderedValue:
        """Replace $[VAR] with its literal when ``engine`` declares VAR kind:fixed.

        minted/secret vars are left as runtime refs. Inlined vars are also
        dropped from ``rendered.runtime_refs`` (they no longer reach the runtime
        layer). No-op when ``engine`` is None or declares no fixed env vars.
        """
        if engine is None or not engine.env:
            return rendered
        fixed = {n: s.value for n, s in engine.env.items() if s.kind == "fixed"}
        if not fixed:
            return rendered
        inlined: set[str] = set()

        def repl(m: re.Match[str]) -> str:
            var = m.group(1)
            if var in fixed:
                inlined.add(var)
                return fixed[var]  # the literal value
            return m.group(0)  # leave minted/secret refs untouched

        new_value = _RUNTIME_REF_RE.sub(repl, rendered.value)
        if not inlined:
            return rendered
        return RenderedValue(
            value=new_value,
            raw_hcl=rendered.raw_hcl,
            runtime_refs=rendered.runtime_refs - inlined,
        )


def find_magic_refs(template: str) -> list[tuple[str, str, str]]:
    """Return all ``(kind, target, part)`` tuples in ``template``.

    Useful for dependency analysis without performing resolution.
    """
    return [(m.group(1), m.group(2), m.group(3)) for m in _MAGIC_RE.finditer(template)]


def walk_strings(node: Any) -> list[str]:
    """Walk a YAML-shaped tree and yield all string values.

    Used to scan ``infra.yml`` for magic refs before compile."""
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            out.extend(walk_strings(v))
    elif isinstance(node, list):
        for item in node:
            out.extend(walk_strings(item))
    return out

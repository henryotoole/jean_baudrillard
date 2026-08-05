"""Magic-ref resolution.

A *magic ref* is a compile-time variable in ``infra.yml`` of the form

    ${codebases.<codebase>.core_services.<service>.<part>}   # five segments
    ${backing_services.<service>.<part>}                     # three segments

The asymmetry is honest rather than accidental: a backing service has no
core service, so there is nothing to qualify.

A core ref is a LITERAL PATH into the document: every segment names a key
the reader can walk in ``infra.yml``, including the intermediate
``core_services`` collection. See cicl.md § Magic Refs.

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

from docex.cicl.model import BackingService, CICLDocument, Codebase, ServiceRef
from docex.cicl.substitute import (
    HCLLiteral,
    RenderedValue,
    _COMPILE_RE,
    substitute_string,
)
from docex.cicl.transfer import EngineEntry, TransferTables
from docex.errors import SubstitutionError


# Matches ANY ``${<kind>.<body>}`` where kind ∈ {codebases,
# backing_services}. Deliberately body-agnostic: whether a string IS a magic
# ref must be decided independently of whether that ref is WELL-FORMED.
#
# WHY: the previous pattern hard-coded three segments and an identifier
# charset, so a four-segment ref, or any ref carrying a '-' in a name, matched
# neither this pattern nor substitute._COMPILE_RE and was emitted into the
# compose/HCL output as literal '${...}' text — silent corruption of
# infrastructure config rather than a compile error. Claiming every
# kind-prefixed ref here and arity-checking after the split is what closes it.
_MAGIC_RE = re.compile(r"\$\{(codebases|backing_services)\.([^{}$]*)\}")

# Same shape as substitute._RUNTIME_RE — a ``$[VAR]`` runtime ref.
_RUNTIME_REF_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


# Segment counts are stated the way cicl.md states them — INCLUDING the kind
# segment. A core ref is five segments; the body this module splits is four.
_REF_FORM = {
    "codebases": "${codebases.<codebase>.core_services.<service>.<part>}",
    "backing_services": "${backing_services.<service>.<part>}",
}
_REF_BODY_SEGMENTS = {"codebases": 4, "backing_services": 2}
_REF_SEGMENT_WORD = {"codebases": "five-segment", "backing_services": "three-segment"}

# The literal collection segment a core ref must carry at body position 1.
# WHY a literal rather than a wildcard: the ref is a path walk, so the segment
# that names the nested key is part of the grammar, not a name the author
# chooses. Rejecting anything else here is what makes the pre-1.7.0
# four-segment form a loud, migratable error instead of a "codebase not found".
_CORE_COLLECTION = "core_services"


class MagicRefArityError(SubstitutionError):
    """A magic ref whose segment count is wrong for its kind."""


@dataclass(frozen=True)
class ParsedMagicRef:
    kind: str
    target: str
    service: str | None  # None for backing services — they have no core services
    part: str
    raw: str  # the literal "${...}" text, for messages

    @property
    def text(self) -> str:
        """Canonical rendering — the form the author should have written."""
        if self.service is None:
            return f"${{{self.kind}.{self.target}.{self.part}}}"
        return (
            f"${{{self.kind}.{self.target}.{_CORE_COLLECTION}."
            f"{self.service}.{self.part}}}"
        )


@dataclass(frozen=True)
class MagicRefMatch:
    """One raw ``${<kind>.<body>}`` hit, not yet arity-checked."""

    kind: str
    body: str
    raw: str

    @property
    def segments(self) -> list[str]:
        return self.body.split(".")

    def parse(self) -> ParsedMagicRef:
        """Arity-check by kind. Raises MagicRefArityError."""
        segs = self.segments
        if len(segs) != _REF_BODY_SEGMENTS[self.kind] or not all(s.strip() for s in segs):
            raise MagicRefArityError(self._arity_message())
        if self.kind == "codebases":
            if segs[1] != _CORE_COLLECTION:
                raise MagicRefArityError(self._arity_message())
            return ParsedMagicRef(self.kind, segs[0], segs[2], segs[3], self.raw)
        return ParsedMagicRef(self.kind, segs[0], None, segs[1], self.raw)

    def _arity_message(self) -> str:
        segs = self.segments
        msg = (
            f"magic ref {self.raw} is malformed: `{self.kind}` refs take the "
            f"{_REF_SEGMENT_WORD[self.kind]} form `{_REF_FORM[self.kind]}`."
        )
        if self.kind == "codebases":
            # The pre-1.7.0 four-segment form, `${codebases.api.web.host}`.
            # Naming the exact replacement is the whole migration story for
            # this ref, so spell it out rather than restating the grammar.
            if len(segs) == 3 and all(s.strip() for s in segs) \
                    and segs[1] != _CORE_COLLECTION:
                msg += (
                    f" This looks like the pre-1.7.0 four-segment form. Did "
                    f"you mean ${{codebases.{segs[0]}.{_CORE_COLLECTION}."
                    f"{segs[1]}.{segs[2]}}}?"
                )
            elif len(segs) == 4 and segs[1] != _CORE_COLLECTION:
                msg += (
                    f" Body segment 2 must be the literal "
                    f"`{_CORE_COLLECTION}`, not {segs[1]!r} — a core ref is a "
                    f"path walk through the document."
                )
            elif len(segs) == 2 and all(s.strip() for s in segs):
                msg += (
                    f" Did you mean ${{codebases.{segs[0]}."
                    f"{_CORE_COLLECTION}.<service>.{segs[1]}}}?"
                )
            msg += (
                " A codebase has no single boundary, so a bare codebase "
                "name has no answer."
            )
        else:
            msg += (
                " A backing service has no core service, so there is nothing "
                "to qualify."
            )
            if len(segs) == 3 and all(s.strip() for s in segs):
                msg += (
                    f" Did you mean ${{backing_services.{segs[0]}.{segs[2]}}}?"
                )
        return msg + " See cicl.md § Magic Refs."


# The self-reference rule, stated once. Two rules forbid a core service from
# pointing at itself — a magic ref (rule 3) and a `consumes` entry (rule 25) —
# and their messages must state the RULE identically while differing in
# consequence. A shared constant is what makes that a guarantee rather than a
# request; the previous form was a docstring asking the next editor to keep
# them alike.
_SELF_REF_RULE = "A core service may not reference itself"


def self_reference_message(ref: ParsedMagicRef, consumer_label: str) -> str:
    """cicl.md § Magic Refs — a core service may not reference itself.

    Sibling to :func:`self_consumes_message` below (rule 25's self-`consumes`
    clause). Both state ``_SELF_REF_RULE`` and then diverge on consequence.
    """
    return (
        f"magic ref {ref.text} in {consumer_label!r} references the process "
        f"type itself. {_SELF_REF_RULE}: "
        f"`provides.{ref.part}` is the *internal* discovery name, so the one "
        f"plausible motive — building an absolute URL to oneself — would not "
        f"return what you expect. Use `localhost` with the core service's own "
        f"`port`. See cicl.md § Magic Refs."
    )


def self_consumes_message(ref: ServiceRef) -> str:
    """cicl.md rule 25 — a core service may not consume itself.

    Lives in this module, beside :func:`self_reference_message`, despite being
    a `consumes` concern rather than a magic-ref one: the two messages must
    state ``_SELF_REF_RULE`` identically, and co-location is what makes that
    visible to whoever edits either. Do not "tidy" it into validate.py.
    """
    return (
        f"core service {ref.dotted!r} lists itself in `consumes:`. "
        f"{_SELF_REF_RULE}: a self-edge makes both derivations `consumes` "
        f"feeds nonsensical — the core service would be its own contract "
        f"provider, and its health fan-out would proxy its own `/health` at "
        f"`/health/{ref.codebase}/{ref.service}`. "
        f"See cicl.md § Consumes Relationships."
    )


@dataclass
class MagicRefDependency:
    """One magic ref detected during compile."""

    # The COMPILED identity of whatever holds the ref: 'api-web' for a core
    # core service (Mod 096 re-keyed contexts/engines onto it), the service
    # name for a backing service.
    consumer: str
    kind: str  # 'codebases' | 'backing_services'
    target: str  # service being referenced — the CODEBASE name for core
    target_service: str | None  # core service; None for backing targets
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

    # Cycle guard, keyed on (kind, target, process, part).
    _resolving: set[tuple[str, str, str | None, str]] = field(default_factory=set)

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
            ref = MagicRefMatch(
                kind=m.group(1), body=m.group(2), raw=m.group(0)
            ).parse()  # MagicRefArityError propagates — it IS the message

            # cicl.md § Magic Refs: a core service may not reference itself.
            if (
                ref.kind == "codebases"
                and ServiceRef(ref.target, ref.service).compiled == consumer
            ):
                raise SubstitutionError(self_reference_message(ref, consumer))

            self.deps.append(MagicRefDependency(
                consumer=consumer, kind=ref.kind, target=ref.target,
                target_service=ref.service, part=ref.part,
            ))

            key = (ref.kind, ref.target, ref.service, ref.part)
            if key in self._resolving:
                raise SubstitutionError(
                    f"cyclic magic-ref chain through {ref.text}"
                )
            self._resolving.add(key)
            try:
                rendered = self._resolve_part(ref)
            finally:
                self._resolving.discard(key)

            if rendered.value == "":
                raise SubstitutionError(
                    f"magic ref {ref.text} in {consumer!r} "
                    f"resolved to an empty value — {ref.target!r}'s "
                    f"{ref.part!r} field is unset and the engine declares no "
                    f"default for it."
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

    def _resolve_part(self, ref: ParsedMagicRef) -> RenderedValue:
        # `key` is what contexts/engines are keyed on: the two-segment compiled
        # identity for a core service (Mod 096), the bare name for a
        # backing service.
        if ref.kind == "codebases":
            svc = self.doc.codebases.get(ref.target)
            if svc is None:
                raise SubstitutionError(
                    f"magic ref {ref.text} -> unknown core service "
                    f"{ref.target!r}; known: {sorted(self.doc.codebases)}"
                )
            if ref.service not in svc.core_services:
                raise SubstitutionError(
                    f"magic ref {ref.text} -> codebase {ref.target!r} "
                    f"declares no core service {ref.service!r}; known: "
                    f"{sorted(svc.core_services)}"
                )
            key = ServiceRef(ref.target, ref.service).compiled
        elif ref.kind == "backing_services":
            if ref.target not in self.doc.backing_services:
                raise SubstitutionError(
                    f"magic ref {ref.text} -> unknown service {ref.target!r}"
                )
            key = ref.target
        else:  # pragma: no cover — the pattern admits no other kind
            raise SubstitutionError(
                f"magic ref kind must be codebases or backing_services, "
                f"got {ref.kind!r}"
            )

        engine = self.engines.get(key)
        if engine is None:
            raise SubstitutionError(
                f"magic ref {ref.text} -> no engine resolved for {key!r}"
            )

        provides = engine.provides_for(self.foundation)
        if not provides:
            raise SubstitutionError(
                f"magic ref {ref.text} -> the {engine.role!r} role's "
                f"{engine.engine!r} engine exposes no parts on "
                f"{self.foundation}: it publishes no discovery surface and "
                f"therefore cannot be the target of a magic ref."
            )
        if ref.part not in provides:
            raise SubstitutionError(
                f"magic ref {ref.text} -> engine {engine.engine!r} does not "
                f"expose part {ref.part!r} on {self.foundation}; known: "
                f"{sorted(provides)}"
            )

        template = provides[ref.part]
        target_ctx = self.contexts.get(key, {})

        # Resolve any magic refs inside the provides template (rare but allowed).
        # We pass through resolve_in_string for the target as consumer.
        if _MAGIC_RE.search(template):
            return self._inline_fixed(
                self.resolve_in_string(template, consumer=key), engine
            )

        # Plain substitution against the *target's* context.
        return self._inline_fixed(
            substitute_string(template, target_ctx, foundation=self.foundation),
            engine,
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


def find_magic_refs(template: str) -> list[MagicRefMatch]:
    """Return every raw magic-ref match in ``template``, unparsed.

    Matches are returned *without* arity checking so callers can decide how a
    malformed ref surfaces: the resolver lets ``parse()`` raise, the validator
    catches ``MagicRefArityError`` into a ``ValidationIssue``. One message,
    two surfaces.
    """
    return [
        MagicRefMatch(kind=m.group(1), body=m.group(2), raw=m.group(0))
        for m in _MAGIC_RE.finditer(template)
    ]


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

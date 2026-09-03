---
stratum: resident
---

# Code-Level Documentation

This file details best practices for code-level documentation: the docstrings and comments that live alongside the code itself. Code-level docs record only what neither the code nor the [design docs](./docs.md#design-documentation) already say. They **never** replicate a design decision — they *reference* it (see [Reference outward](#inline-comments) below).

Code-level docs come in two **forms**, split by audience:

1. **Docstrings** — outward-facing, for the *caller* who will use the object without reading its body. A docstring documents the object as a black box.
2. **Inline comments** — inward-facing, for the *maintainer* working inside the object.

Each form has its own jobs.

## Docstrings

A docstring records the object's **contract**: its purpose, arguments, return value, error/exception states, and any side effects. Written in whatever form is standard for the language.

By default, add a docstring **only** when the name and signature don't already communicate the non-obvious — an unexpected side effect, a non-obvious precondition, or an important performance characteristic. A docstring that merely restates the type signature is noise.

That default is overridden where the doctrine mandates fuller documentation. Controllers, domain, and application logic carry a stricter requirement regardless of how self-evident they look — see [hex_overview.md § Critical Documented Code](../hexagonal_architecture/hex_overview.md#critical-documented-code). Controllers in particular must document every externally-accessible function's purpose, arguments, error states, and return shape.

## Inline Comments

An inline comment records only what the code and the design docs leave unsaid. There are four jobs:

1. **The why (the workhorse).** Explain *why* a non-obvious approach was chosen over the simpler or expected one. This is the single most valuable comment you can write.
2. **A caveat.** Flag something that will bite a maintainer who doesn't know it:
   - a workaround for a known bug or limitation in a dependency,
   - an invariant or assumption that breaks things if violated,
   - why a performance-critical section is written the way it is.
3. **A translation of genuinely opaque code.** For a dense math expression or a bitwise trick, state the *intent* in prose. This is the one case where you may describe *what* the code does — because here the code genuinely does **not** say it. It is the exception to the Never rule below, not a violation of it.
4. **A reference outward.** When the reason lives elsewhere, point to it rather than restating it:
   - **up** to an [ADR](./adrs.md) or design doc when the rationale is an architectural decision,
   - **sideways** to a related part of the system when the relationship isn't obvious from the imports.

   Reference, never replicate. A copied rationale drifts from its source; a link does not.

## Never Comment

- What a self-evident line of code does — the code already says it.
- Obvious parameter descriptions that repeat the type signature.
- Section dividers or decorative comments.

## Format

Keep "why" comments scannable and grep-able:

```
// WHY: <reason>
```

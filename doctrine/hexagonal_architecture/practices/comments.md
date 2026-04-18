# Comments

This file details best-practices for commenting code.

## Commenting Standards

When writing or modifying code, include comments only when they provide information that cannot be inferred from reading the code itself.

Always comment:
- WHY a non-obvious approach was chosen over the simpler/expected one
- Workarounds for known bugs or limitations in dependencies
- Invariants or assumptions that would break things if violated
- Performance-critical sections explaining why they're written that way
- Relationships to other parts of the system that aren't obvious from imports

Never comment:
- What a line of code does (the code says that)
- Obvious parameter descriptions that repeat the type signature
- Section dividers or decorative comments

For functions/methods, add a docstring ONLY when the name + signature don't fully communicate: unexpected side effects,
non-obvious preconditions, or
important performance characteristics.

Format for "why" comments:
// WHY: <reason> — keeps them scannable and grep-able
# `linkcheck`'s citation arm is nearly blind in the directory it was built for

**Found:** advance 006, mod 133, while retracting a different finding.

## The two halves

**1. Unbounded citations are counted, not enumerated.** `linkcheck.py`'s
`Declined` block reports `27 unbounded (file checked, heading not)` — a number,
never a list. Its docstring claimed the block prints unbounded citations; it
increments a counter and returns. The overclaim is now corrected in place; the
behavior is not.

**2. `doctrine_excerpts/`'s house style is systematically unbounded** — **14 of
16** `Doctrine reference:` lines. The arm classifies a heading only when the path
and the `§` sit inside **one** inline-code span; a bare-prose reference gets its
*file* verified and its *heading* skipped.

Put together: the citation check is close to blind in the one directory whose dead
citation (`service_discovery.md`, advance 006) is what motivated building the arm
in the first place. It would not have caught that instance either.

## Why this was not fixed in mod 133

Mod 132 was closed, and enumerating 25–27 previously-silent citations in every
`cohere` run is a change to that tool's output contract, not a bug fix. It is an
output-volume judgement about a tool an operator reads by hand.

## What a fix looks like, and the order that matters

Two changes, and **the second is worth more than the first**:

1. **Enumerate.** List the unbounded citations in the `Declined` block, or behind
   a flag. Cheap. On its own it converts a silent gap into a visible one without
   closing it.
2. **Convert `doctrine_excerpts/` to bounded form.** Mod 133 did exactly one line
   as a demonstration: `unbounded` 25 → 24, `exact` 238 → 239. Fourteen more lines
   would bring that directory almost entirely inside the check. This is a *pure
   verifiability gain* — the prose reads the same and the heading becomes
   checkable.

Do (1) first only because it tells you which lines (2) has left.

## The transferable part

The arm was built to catch a class found in `doctrine_excerpts/`, and its
matching rule requires a syntax that directory does not use. Nobody checked
whether the new check could see its own motivating example — the gap is not in the
rule or in the style, but in never having asked that question. Worth asking of any
new check: **run it against the instance that motivated it, and confirm it fires.**
Mod 132 did demonstrate the arm failing, but on a *reconstruction* it had written
in bounded form, not on the original line.

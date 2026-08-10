# Released `CHANGELOG.md` sections carry 14 broken relative links

**Found:** advance 006, mod 131, while confirming the `[Unreleased]` section had none.

## The defect

Fourteen relative links in **released** sections of the repo-root `CHANGELOG.md`
resolve from nowhere: their paths are written as if the file sat at `docex/`,
which it did before the doctrine-wide versioning move at 1.3.0. `[Unreleased]`
is clean — mod 131 confirmed that separately — so this is entirely historical
residue, not an active drift.

## Why it was left

Released changelog sections are **frozen**: they record what a version shipped,
and revising them falsifies the record. Mod 130 established that rule and mod 131
held to it. These are not *claims*, though — they are paths, and a path that
resolves nowhere records nothing. So the freeze argument is weaker here than it
looks, which is precisely why this is a judgement call worth writing down rather
than a fix worth sneaking in.

## The reason it matters now rather than never

Advance 006 requires mod 132 to widen `linkcheck.py` and add an arm that resolves
`<file>.md § <Heading>` citations written as prose. Both of those, pointed at the
repo root, would fire on this file forever. **A tool that always exits non-zero
trains readers to ignore it** — the exact failure mod 132 exists not to ship.

So there are two coherent end states and the choice must be deliberate:

1. **Exclude released changelog sections from both checks**, as frozen history.
   One rule, uniform, and it also covers the dead `contracts.md §` prose citations
   that live permanently in four released entries.
2. **Repair the fourteen paths** — mechanical, preserves every word of prose, and
   lets the changelog come fully into scope.

Mod 132 was given (1) as a hard constraint because it is the smaller change and
because the prose-citation instances genuinely cannot be repaired without
rewriting released claims. (2) remains available and is strictly better for a
reader who wants to follow a link out of the history; the two are not exclusive.

## The transferable part

Two rules collided here and both are sound: *frozen history is not revised*, and
*a link that resolves nowhere is debt*. The resolution is that a **link target**
may be repointed where a **claim** may not — `upgrades/README.md` already says
exactly this about upgrade guides, and the same distinction should govern the
changelog. Worth stating once, somewhere both files can cite.

## A third end state, found by mod 132 (appended)

Mod 132 implemented option (1) and, while measuring whether the repo-root files
could come into scope at all, found a case neither option above contemplates.

`CHANGELOG.md:633` — inside **`[Unreleased]`**, so not frozen and not covered by
the exclusion — reads:

> `doctrine_excerpts/secrets.md` cited `specifics/release_mechanism.md § Secrets`
> — a file and a heading that have **never existed** …

That is a changelog entry describing mod 118's *repair* of a dead citation. The
citation is quoted **in order to be dead**, as evidence. Any checker pointed at
that file flags it, and no repair is possible: rewording it would destroy the
evidence, and the entry is a claim rather than a link target.

So repairing the fourteen paths (option 2) is **not sufficient** to bring the
repo-root files into scope. A checker reaching released history — or any live
prose that quotes a dead reference — needs an inline suppression marker
(`<!-- linkcheck-ignore -->` on the line, about two lines of code in
`scannable_lines`). Mod 132 declined to add one on the grounds that it would have
exactly one user, and left the root files out of scope for this measured reason
rather than an aesthetic one.

Whoever takes this brief therefore chooses between three end states, not two:
(1) exclude frozen sections — **done**; (2) repair the fourteen paths; (3) add a
suppression marker, which is what option (2) additionally requires if the goal is
`CHANGELOG.md`, `README.md`, and `RELEASING.md` inside the default scan. Accepting
a *file* (not only a directory) as a root is a five-line change in
`linkcheck.py::main`, deliberately not made.

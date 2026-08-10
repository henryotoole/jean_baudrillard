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

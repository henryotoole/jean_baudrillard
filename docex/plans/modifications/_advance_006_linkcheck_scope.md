# Advance 006 — `linkcheck.py` cannot be widened to reach the seed trees

**Found:** advance 005, Mod 124 (sharpening a gap first logged by Mod 122).

## The gap as originally logged

`PRE_CUT_CHECKLIST.md` sits outside `linkcheck.py`'s default scan root, so its
links are validated only when someone points the tool at it by hand. A hand
check that passes once is not a check — the same argument that got `skills/`
added to the tool in Mod 121.

## Why the obvious fix does not work

Mod 124 established that `linkcheck.py doctrine skills docex/test_projects`
**cannot exit 0**, for a structural reason rather than a defect:

- **Check 1 (links + anchors) is green** at that scope — the half that matters
  for the checklist.
- **Check 3 (identical filenames) fires on twelve permanent duplicates**, because
  `test_projects/fixed/` and `test_projects/elastic/` mirror each other *by
  design*. B.14 requires their `core/` trees be byte-identical; the duplicate
  filenames are the doctrine working correctly.

So widening the root to reach the checklist necessarily drags in two
deliberately-mirrored repos and makes check 3 unusable at that scope.

## What a real fix has to do

Scope the two checks **independently** — or exclude the seed trees from check 3
specifically. A plain root widening will not do, and shipping the tool in a
configuration that always exits non-zero would train readers to ignore it, which
is the failure mode advance 005 spent thirteen mods correcting.

## Not urgent

Check 1 is green at the widened scope today, so the checklist's links *are*
verifiable — just not reproducibly, and not by the shipped default. That is the
whole cost until someone renames a doctrine section the checklist points at.

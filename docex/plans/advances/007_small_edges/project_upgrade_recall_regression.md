# `project-upgrade` trigger recall reported 1.00 → 0.50 — re-measure before deciding there is a defect

Booked from advance 006's `RELEASING.md` trigger-eval gate. **Not caused by advance 006.**

**The first action here is re-measurement, not a fix.** The 0.50 was produced by the trigger
harness *before* mod 135 fixed its cwd confound, and that confound is now known to
**systematically convert precision failures into recall failures** — it turns a misroute into a
∅, which is the bucket both of these failures landed in. So this may not be a regression at all.
It may be the same artifact running in the other direction.

Anyone who edits `project-upgrade`'s description off the old number would be repeating mod 135's
mistake with a different skill: changing a durable trigger surface on the strength of a
confounded measurement. Re-run first on the corrected `run_suite.py`; then decide whether there
is anything to fix.

## The finding

`project-upgrade`'s suite-level recall fell from **1.00** (last recorded run, 2026-07-11) to
**0.50**, reproduced across two runs at 1/5 and 0/5 on the failing queries.

Three things say this is not ours:

1. Its description was **untouched** by advance 006.
2. Both misses land in **∅** — no skill fires at all — rather than being poached by a sibling. A
   poach would implicate a description that advance 006 changed; ∅ does not.
3. The remaining `project-upgrade` queries still fire correctly, so the description is not broadly
   broken.

That leaves model/CLI drift since the last recorded run as the explanation.

## The pattern in the failures

Both failing queries name an **old pin** without carrying an action verb the description holds.
The description's trigger verbs are upgrade-shaped — "upgrade", "repin", "bring up to date",
"move this project's pin". A query that describes the *state* ("still pinned to a docex from
months ago", "several doctrine versions behind") rather than requesting the *action* falls through.

This is the same failure **shape** as the `contracts` hole mod 135 investigated: a description
whose triggers are all authoring/action verbs missing a query phrased as a condition or a
diagnosis. Worth noting because it suggests a general description-authoring lesson rather than a
one-off — descriptions built purely from verbs miss state-shaped and yes/no-shaped queries.

## Caveat on the numbers — measure again before acting

The runs that produced 1.00 → 0.50 used the trigger harness **before** mod 135 fixed its cwd
confound (see `trigger_eval_cwd_confound_run_eval.md`). The child `claude -p` inherited the jean
repo as cwd and could grep `doctrine/` directly instead of loading a skill, which scores as ∅ —
and ∅ is exactly the bucket both of these failures land in.

Mod 135 measured two other supposed ∅ holes on the corrected harness and found one of them was
never a hole at all. **So re-run `project-upgrade`'s queries on the corrected `run_suite.py`
before changing its description.** The regression may be partly or wholly the same artifact.

The corrected-harness full-suite run in mod 135 is the first datum; anything 007 does here should
start from re-measurement, not from the 0.50.

## If it survives re-measurement

Add state-shaped and diagnosis-shaped triggers to the description rather than more verbs — e.g.
the condition "a project sitting on an old `docex_version` pin" alongside the existing actions.
Then re-run the suite and confirm `doctrine-update`'s precision does not fall, since that skill is
`project-upgrade`'s nearest neighbour and the two already have four boundary near-miss queries
between them (`queries.json` entries covering machine-refresh-only vs. project-move).

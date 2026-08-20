# Overhaul `docex why` prose to match current doctrine

`docex why <resource>` serves prose from `docex/doctrine_excerpts/` — 18 markdown
entries plus `index.yml` mapping resource names to them (`why/catalog.py`). It is
the one aligned `docex` artifact with no automated consumer, so nothing fails
when it drifts, and it has drifted: entries describe superseded infrastructure
(per-project VPCs, per-env ALBs, `example.env` secrets, pre-`apex_domain` DNS),
some stating the inverse of the current rule.

## The instruction

Audit every entry in `doctrine_excerpts/` against current doctrine and rewrite it
to match. This is a prose overhaul only — `docex why` behavior does not change.

- Read each entry against its rule of record and rewrite against it. Inversions
  (an entry asserting the opposite of a doctrine rule, often with rationale built
  on the inversion) are found only by reading entry-against-rule, one at a time —
  no vocabulary grep finds them, because the wrong phrasing uses no doctrine term.
- Leave each entry a bounded `Doctrine reference:` footer with `§` **inside** the
  backticks (so `linkcheck.py`'s citation checker can verify it).
- Reconcile `index.yml` keys with `shape.md`'s `[resource]` notation. At minimum
  fix the `network_web` / `network_internal` keys, which are spelled opposite to
  shape.md's `web_network` / `internal_network` — a `docex why web_network`
  exit-1 today. **Retire the `vpc` key** (decided at plan review) — there is no
  `vpc` resource in `shape.md` and the entry actively misinstructs; its content is
  covered by `master_network`'s new entry, chosen over keeping a misleading alias.
- Add entries for the `shape.md` resources that have none (`master_network` and
  `web_demux` first — they are where a preinfra question lands).

## The standing fix

Give the artifact an automated consumer so it stops drifting silently — e.g. a
check that every `index.yml` key resolves to a `shape.md` resource (or a
documented exception). An artifact with no consumer drifts at the rate nobody
looks.

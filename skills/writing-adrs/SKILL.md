---
name: writing-adrs
description: Doctrine for authoring an Architecture Decision Record (ADR) — the file format, the status lifecycle, and the generated index files that capture the *reasoning* behind a design decision. Use this whenever you are writing, recording, proposing, accepting, superseding, or deprecating an ADR, or need to durably capture *why* a design choice was made, even if you never say the word "ADR".
metadata:
  type: thread
---

# writing-adrs

Recording an architecture decision (ADR) is one activity: capture the *reasoning*
behind a design choice as an immutable, append-only record, then regenerate the
indexes. The format spec is short — read it now.

## General Information

Critical orienting information — **read the referenced file now.**

[adrs.md](../../doctrine/practices/adrs.md) — the whole ADR practice: why ADRs exist
(they hold the reasoning that would otherwise clutter the lightweight state design
docs), the per-file frontmatter schema, the status enum, the immutable / append-only
rule, and the two generated index files (`adr_index.md`, `adr_active.md`).

## Specific Information

Detailed context — read on demand.

[docs.md](../../doctrine/practices/docs.md) — where ADRs sit in the documentation
taxonomy: they are the *reasoning-doc* half of the design docs, stored under
`plans/design/adrs/`. Read this if you need to place the ADR correctly or understand
its relationship to the state design docs.

## Thread

Write an ADR whenever a design decision needs its *why* preserved. Read `adrs.md` for
the frontmatter schema and status enum, then:
1. Pick the next sequential integer `id` and name the file `${id}_${snake_case_title}`
   under `$pr/plans/design/adrs/`.
2. Fill `Context` / `Decision` / `Consequences`; set `status` (usually `proposed`,
   then `accepted` once agreed).
3. Old ADRs are **immutable** — never edit a shipped decision. To change one, write a
   *new* ADR and link the pair with `supersedes` / `superseded-by`.
4. Regenerate the index files (`adr_index.md` + `adr_active.md`) rather than
   hand-editing them — they are derived from the ADR files by `docex`.

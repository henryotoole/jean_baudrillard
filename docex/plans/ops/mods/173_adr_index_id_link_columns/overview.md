# Mod 173 — ADR index: split the ID cell into an ID column + a link column

## Problem

`docex docs adr` renders `adr_index.md` / `adr_active.md` with the **`ADR ID`
cell itself carrying the markdown link** to the ADR file (mod 170):

```
| [0001](adrs/0001_use_postgres.md) | Use Postgres | accepted | … |
```

This conflates two things in one cell — the ADR's identity (a pure number) and a
navigational link. It reads as confusing: the "ID" is not a plain id, it is a
link whose text happens to be the id. We want the identity and the link to be
**distinct columns**: a pure-number `ADR ID` column and a separate link column.

## The change

`render_index` / `render_active` (in `docex/src/docex/docs/adr.py`) gain one new
leading column. Each data row's first cell becomes the **bare id** (`0001`), and
a new second column carries the **markdown link** to the ADR's source file.

**Resolved rendered form** (index) — operator decision: column named `Link`,
link-cell form `[${id}](adrs/${filename})`:

```
| ADR ID | Link | Title | Status | Date | Supersedes | Superseded By |
| ------ | ---- | ----- | ------ | ---- | ---------- | ------------- |
| 0001   | [0001](adrs/0001_use_postgres.md) | Use Postgres | accepted | … |
```

- **`ADR ID` column** — the bare `a.id` (e.g. `0001`), no link.
- **New `Link` column** — `[${a.id}](adrs/${a.filename})`, using `Adr.filename`
  (the real on-disk name, which cannot dangle — the mod-170 invariant is kept).
  Placed immediately after `ADR ID`. NOTE: `Adr.filename` **already ends in
  `.md`** (it is `path.name`), so the target is `adrs/{a.filename}` — do **not**
  append another `.md`. The link-cell content is therefore byte-identical to the
  current `_adr_link` output; only its column position changes, and a bare-id
  column is added ahead of it.
- Active table gets the same treatment:
  `| ADR ID | Link | Title | Date | Supersedes |`.

The existing `_adr_link` already renders exactly this link cell; it is reused for
the `Link` column, and the bare-id cell (`a.id`) is added as the new first cell.

### Why the link must remain in the row (the docs-check safety point)

`docs check`'s **reachability** is what makes an ADR reachable *through its
index* (a superseded ADR need not be linked from any narrative doc). Reachability
parses **all** links in the file via the shared linkmap — it does not care which
column a link sits in. So moving the link from the ID cell to the new `File`
column **preserves the `adr_index.md → adrs/<file>` edge** and reachability is
unaffected. The **ADR-index-freshness** check compares on-disk indexes against
these same render functions (the single canonical render), so it stays
self-consistent once docex's own dogfood indexes are regenerated. Verified: no
`docs check` code path keys on the ID cell specifically.

## Scope

Code + tests:
- `docex/src/docex/docs/adr.py` — `render_index`, `render_active`, the link
  helper; add the ID column + File column. The empty-set render (header +
  separator only) changes only by the added header/separator column.
- `docex/tests/unit/test_docs_adr.py` — the only test file that hard-codes the
  old `| [0001](adrs/…) |` cell shape; update row/link assertions to the new
  two-column form. `test_docs_check.py`'s ADR-reachability test uses the real
  render and needs no change (confirm it stays green).

Docs (six-artifact alignment — handled in the mod's documentation step, not the
implementation step):
- Doctrine prose: `doctrine/practices/adrs.md` (the two header examples at
  lines 51/53 + the two "the `ADR ID` cell is a markdown link" prose lines 57/63),
  `doctrine/practices/docs.md` line 199 ("links each ADR by its `ADR ID` cell"),
  `doctrine/infrastructure/docex.md` line 186 ("each row's `ADR ID` cell links").
- docex design docs: `docex/plans/design/specifics/subcommand_surface.md`
  ("each row's `ADR ID` cell rendered as a markdown link").
- Regenerate docex's own dogfood indexes `docex/plans/design/adr_index.md` and
  `adr_active.md` via the new render (keeps them from drifting).

Do **not** change the `# ADR Index` / `# Active ADRs` headings or the
`adrs.md#adr-index` / `docs.md#reachability-check` anchors — several links resolve
to them.

Out of scope: the reachability/linkmap engine (unchanged), `standard_set.py`,
scaffold logic (auto-inherits the new render).

## Release

Folds into the **same 3.0.1 PATCH** as mod 172 (the local 3.0.1 cut was unwound
so both ship together). Still a PATCH: the command surface is identical and the
change is a cosmetic index-format refinement that requires no downstream action
(a project regenerates its index with `docex docs adr` whenever it repins). Gates
as before: six-artifact alignment + docex unit + integration; smoke/skill/cohere
waived per operator.

## Design questions — RESOLVED

1. **New column name.** → **`Link`** (operator decision).
2. **Link-cell text.** → **bare id**, form `[${id}](adrs/${filename})` (operator
   decision). This is byte-identical to the current `_adr_link` output, so the
   link string is merely relocated to the new column.
3. **Column placement.** → immediately after `ADR ID` (recommendation accepted by
   default; operator raised no objection).

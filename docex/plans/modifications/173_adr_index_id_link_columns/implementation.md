# Mod 173 — Implementation

Split the ADR index's single linked `ADR ID` cell into two columns: a bare
`ADR ID` column and a new `Link` column carrying the markdown link. Applies to
both `adr_index.md` and `adr_active.md`, via the single canonical render in
`docex/src/docex/docs/adr.py`.

All paths under `~/.claude/jean_baudrillard`. Branch: `mod-173-adr-index-id-link-columns`.

Scope of THIS document: **code + tests only.** Do **not** edit anything under
`plans/design` (including docex's dogfood `adr_index.md` / `adr_active.md`), the
resident doctrine (`doctrine/**`), `CHANGELOG.md`, or version files — those are
handled outside this step.

## Key fact to avoid a bug

`Adr.filename` is `path.name` and **already ends in `.md`** (e.g.
`0001_use_postgres.md`). The link target is therefore `adrs/{a.filename}` — do
NOT append another `.md`. The existing `_adr_link` helper already renders exactly
the wanted link cell (`[{a.id}](adrs/{a.filename})`); reuse it unchanged for the
new `Link` column.

## Step 1 — `docex/src/docex/docs/adr.py`

### 1a. `render_index`

Add the `Link` column immediately after `ADR ID`. The header, separator, and
each data row gain one column:

- Header line → `"| ADR ID | Link | Title | Status | Date | Supersedes | Superseded By |"`
- Separator line → `"| ------ | ---- | ----- | ------ | ---- | ---------- | ------------- |"`
- Each data row → `_row([a.id, _adr_link(a), a.title, a.status, a.date, ", ".join(a.supersedes), ", ".join(a.superseded_by)])`

(The only change to each row is inserting `a.id` as the new first cell; the old
first cell `_adr_link(a)` becomes the second cell.)

### 1b. `render_active`

Same treatment:

- Header line → `"| ADR ID | Link | Title | Date | Supersedes |"`
- Separator line → `"| ------ | ---- | ----- | ---- | ---------- |"`
- Each data row → `_row([a.id, _adr_link(a), a.title, a.date, ", ".join(a.supersedes)])`

### 1c. `_adr_link`

Leave the rendering logic unchanged (it already produces
`[{a.id}](adrs/{a.filename})`). Lightly update its docstring first line to say it
renders the **`Link`-column** cell (still: link text = id, target = the real
on-disk filename, and this resolvable link is what keeps the ADR reachable from
the index root). Do not change what it returns.

Do not touch `parse_adr`, `load_adrs`, `adr_index_drift`, `regenerate_adr_indexes`,
sorting, or the empty-set behavior (header + separator only, now with the extra
column — no data rows).

## Step 2 — `docex/tests/unit/test_docs_adr.py`

Most assertions still pass because the link string `[0001](adrs/…)` is unchanged
(merely relocated). Make these precise edits:

### 2a. `test_index_lists_all_and_renders_supersede_chain` (the two full-row asserts)

These are the assertions that actually break. Update both rows to the new column
order with the bare-id first cell:

- `"| 0001 | [0001](adrs/0001_old.md) | old | superseded | 2026-01-01 |  | 0002 |"`
- `"| 0002 | [0002](adrs/0002_new.md) | new | accepted | 2026-01-01 | 0001 |  |"`

### 2b. `test_regenerate_and_idempotency` (the on-disk row assert)

Update the substring assert to include the new leading id column, for clarity:
`"| 0001 | [0001](adrs/0001_a.md) | a | accepted |"`.

### 2c. `test_id_cell_is_linked_to_adr_file`

Rename to `test_link_column_links_to_adr_file` and update its docstring to say the
link now lives in the dedicated `Link` column. Keep the two existing asserts
(`link in render_index` / `render_active`). ADD, for both renders, an assert that
the header carries the new column — `"| ADR ID | Link |"` is a substring of each
render — and that the `ADR ID` cell is now the bare id: assert the data row's
first cell is `0001` and its second cell is the link, e.g. that
`"| 0001 | [0001](adrs/0001_thing.md) |"` is a substring.

### 2d. Add `test_id_and_link_are_distinct_columns`

A focused test on the new structure. For a single accepted ADR
(`0001_a.md`, id `0001`, title `a`):

- `render_index` header line equals exactly
  `"| ADR ID | Link | Title | Status | Date | Supersedes | Superseded By |"`.
- `render_active` header line equals exactly
  `"| ADR ID | Link | Title | Date | Supersedes |"`.
- The index data row equals exactly
  `"| 0001 | [0001](adrs/0001_a.md) | a | accepted | 2026-01-01 |  |  |"`.
- The active data row equals exactly
  `"| 0001 | [0001](adrs/0001_a.md) | a | 2026-01-01 |  |"`.

(Use exact line matching by splitting the render on `\n` and asserting membership,
or `in`-substring on the row string — either is fine; the render is deterministic.)

### 2e. Leave unchanged

`test_active_excludes_non_accepted_and_superseded` (line-74 link assert and the
`[excluded]` absence checks still hold), `test_sorted_by_id`,
`test_empty_adrs_case` (`count("\n|") == 2` is unaffected by column count),
`test_drift_detection`, `test_check_docs_flags_drift`,
`test_fresh_scaffold_passes_staleness`, `test_link_target_is_real_filename_not_derived_from_title`
(its asserts are all substrings that survive). Verify they still pass; do not
edit them unless one actually fails.

## Step 3 — Run the tests

From `docex/` (never the repo root, never bare `pytest`):

```bash
cd ~/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/test_docs_adr.py tests/unit/test_docs_check.py tests/unit/test_docs_linkmap.py tests/unit/test_docs_standard_set.py
```

All green. `test_docs_check.py`'s `test_adr_reachable_only_via_generated_index`
must still pass unedited — it uses the real render, proving reachability survives
the column split. Then the full unit suite:

```bash
cd ~/.claude/jean_baudrillard/docex
python3 -m pytest tests
```

Report pass/fail counts. Do NOT run integration (the review runs the full gate
separately). Do NOT commit.

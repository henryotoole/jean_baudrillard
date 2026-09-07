# Mod 170 — Implementation Steps: `docs_adr_reference_links`

Fresh-context handoff. You are executing the implementation of mod 170 in the
**jean_baudrillard mono-repo**; the docex codebase lives under `docex/`. All paths
below are relative to the repo root `/home/ubuntu/.claude/jean_baudrillard/` unless
absolute.

**What this mod does:** make `docex docs adr` render each ADR row's `ADR ID` cell as
a markdown link to that ADR's source file, so ADRs are reachable through the
generated index (not only through a hand-written narrative link). Deterministic and
idempotent; only the ID cell of each data row changes.

**Do NOT** edit any doctrine file (`doctrine/**`), any `docex/plans/design/**` file,
or `CHANGELOG.md` — the corporal handles those in the documentation step. Your scope
is source, tests, and the two tool-generated test-project index fixtures.

---

## Step 1 — `src/docex/docs/adr.py`: carry the real filename + link the ID cell

File: `docex/src/docex/docs/adr.py`.

### 1a. Add a `filename` field to the `Adr` dataclass.

Find:

```python
@dataclass(frozen=True)
class Adr:
    id: str
    title: str
    status: str
    date: str
    supersedes: tuple[str, ...]
    superseded_by: tuple[str, ...]
    tags: tuple[str, ...]
```

Add `filename` as the last field:

```python
@dataclass(frozen=True)
class Adr:
    id: str
    title: str
    status: str
    date: str
    supersedes: tuple[str, ...]
    superseded_by: tuple[str, ...]
    tags: tuple[str, ...]
    # The ADR's real on-disk filename (e.g. "0001_foo.md"), captured by
    # parse_adr. The index links to THIS, never a path derived from id+title,
    # which could drift from the actual file and dangle. See mod 170.
    filename: str
```

### 1b. Populate `filename` in `parse_adr`.

Find:

```python
def parse_adr(path: Path) -> Adr:
    data = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return Adr(
        id=str(data.get("id", "")).strip(),
        title=str(data.get("title", "")).strip(),
        status=str(data.get("status", "")).strip(),
        date=str(data.get("date", "")).strip(),
        supersedes=_as_id_list(data.get("supersedes")),
        superseded_by=_as_id_list(data.get("superseded-by")),
        tags=_as_id_list(data.get("tags")),
    )
```

Add the `filename` kwarg:

```python
def parse_adr(path: Path) -> Adr:
    data = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return Adr(
        id=str(data.get("id", "")).strip(),
        title=str(data.get("title", "")).strip(),
        status=str(data.get("status", "")).strip(),
        date=str(data.get("date", "")).strip(),
        supersedes=_as_id_list(data.get("supersedes")),
        superseded_by=_as_id_list(data.get("superseded-by")),
        tags=_as_id_list(data.get("tags")),
        filename=path.name,
    )
```

### 1c. Add the link helper.

Insert this function immediately **after** the existing `_row` helper (the
`def _row(cells: list[str]) -> str:` block) and before `render_index`:

```python
def _adr_link(a: Adr) -> str:
    """Render the ADR id as a markdown link to its source file.

    The path is relative to the index files, which both sit at plans/design/, so
    it targets plans/design/adrs/<file>. The link TEXT is the ADR id; the link
    TARGET is the ADR's real on-disk filename (``Adr.filename``) — never a path
    derived from id+title, which could drift from the actual file and dangle. This
    resolvable link is what makes an ADR reachable from the index root in
    ``docs check`` (doctrine/practices/docs.md § Reachability Check).
    """
    return f"[{a.id}](adrs/{a.filename})"
```

### 1d. Link the ID cell in `render_index`.

Find:

```python
    for a in sorted(adrs, key=_sort_key):
        lines.append(_row([
            a.id, a.title, a.status, a.date,
            ", ".join(a.supersedes), ", ".join(a.superseded_by),
        ]))
```

Replace the first cell `a.id` with `_adr_link(a)`:

```python
    for a in sorted(adrs, key=_sort_key):
        lines.append(_row([
            _adr_link(a), a.title, a.status, a.date,
            ", ".join(a.supersedes), ", ".join(a.superseded_by),
        ]))
```

### 1e. Link the ID cell in `render_active`.

Find:

```python
    for a in sorted((a for a in adrs if a.is_active), key=_sort_key):
        lines.append(_row([a.id, a.title, a.date, ", ".join(a.supersedes)]))
```

Replace with:

```python
    for a in sorted((a for a in adrs if a.is_active), key=_sort_key):
        lines.append(_row([_adr_link(a), a.title, a.date, ", ".join(a.supersedes)]))
```

**Leave everything else in `adr.py` unchanged** — the `GENERATED_MARKER`, the `#`
headings, the column-header and separator rows, `regenerate_adr_indexes`,
`adr_index_drift`, and `run_docs_adr` are all untouched. Only the ID data cell
changes.

---

## Step 2 — `tests/unit/test_docs_adr.py`: update row asserts + add link tests

File: `docex/tests/unit/test_docs_adr.py`. The exact-row assertions break because
the ID cell is now a link; update them and add link-format coverage.

### 2a. `test_parse_preserves_zero_padded_id` — assert the filename is captured.

Find the end of that test:

```python
    assert adr.id == "0004"          # not int-coerced to "4"
    assert adr.title == "thing"
    assert adr.status == "accepted"
    assert adr.date == "2026-01-01"
```

Append one line:

```python
    assert adr.id == "0004"          # not int-coerced to "4"
    assert adr.title == "thing"
    assert adr.status == "accepted"
    assert adr.date == "2026-01-01"
    assert adr.filename == "0004_thing.md"   # real on-disk name (mod 170)
```

### 2b. `test_active_excludes_non_accepted_and_superseded` — update assert forms.

Find:

```python
    active = render_active(adrs)
    assert "| 0001 |" in active
    for excluded in ("0002", "0003", "0004", "0005", "0006"):
        assert f"| {excluded} |" not in active
```

Replace with (ID cell is now a link; the file for 0001 is `0001_a.md`):

```python
    active = render_active(adrs)
    assert "[0001](adrs/0001_a.md)" in active
    for excluded in ("0002", "0003", "0004", "0005", "0006"):
        assert f"[{excluded}]" not in active
```

### 2c. `test_index_lists_all_and_renders_supersede_chain` — update exact rows.

Find:

```python
    assert index.startswith(GENERATED_MARKER)
    assert "| 0001 | old | superseded | 2026-01-01 |  | 0002 |" in index
    assert "| 0002 | new | accepted | 2026-01-01 | 0001 |  |" in index
```

Replace the two row asserts (files are `0001_old.md` / `0002_new.md`):

```python
    assert index.startswith(GENERATED_MARKER)
    assert (
        "| [0001](adrs/0001_old.md) | old | superseded | 2026-01-01 |  | 0002 |"
        in index
    )
    assert (
        "| [0002](adrs/0002_new.md) | new | accepted | 2026-01-01 | 0001 |  |"
        in index
    )
```

### 2d. `test_sorted_by_id` — search on the link form.

Find:

```python
    index = render_index(load_adrs(tmp_path))
    assert index.index("| 0002 |") < index.index("| 0010 |")
```

Replace (files `0002_b.md`, `0010_j.md`; the bare `| 0002 |` no longer appears):

```python
    index = render_index(load_adrs(tmp_path))
    assert index.index("[0002](adrs/0002_b.md)") < index.index(
        "[0010](adrs/0010_j.md)"
    )
```

### 2e. `test_regenerate_and_idempotency` — update the on-disk assert.

Find:

```python
    idx = (tmp_path / "plans" / "design" / "adr_index.md").read_text()
    assert "| 0001 | a | accepted |" in idx
```

Replace (file `0001_a.md`):

```python
    idx = (tmp_path / "plans" / "design" / "adr_index.md").read_text()
    assert "| [0001](adrs/0001_a.md) | a | accepted |" in idx
```

### 2f. Add two new tests at the end of the file.

```python
def test_id_cell_is_linked_to_adr_file(tmp_path):
    # The ADR id cell is a markdown link to the ADR's source file, in BOTH
    # indexes (mod 170 success criterion 1).
    d = _adrs_dir(tmp_path)
    _write_adr(d, "0001_thing.md", id="0001", title="thing", status="accepted")
    adrs = load_adrs(tmp_path)
    link = "[0001](adrs/0001_thing.md)"
    assert link in render_index(adrs)
    assert link in render_active(adrs)


def test_link_target_is_real_filename_not_derived_from_title(tmp_path):
    # The link target is the real on-disk filename, NOT a slug derived from the
    # human title — so it can never drift from the file it points at (mod 170
    # design decision 2). Human title differs from the snake_case filename stem.
    d = _adrs_dir(tmp_path)
    _write_adr(
        d, "0007_use_postgres.md",
        id="0007", title="Use Postgres for storage", status="accepted",
    )
    idx = render_index(load_adrs(tmp_path))
    assert "[0007](adrs/0007_use_postgres.md)" in idx        # real filename
    assert "use-postgres-for-storage" not in idx             # not a title slug
    assert "| Use Postgres for storage |" in idx             # title stays bare
```

**Do not change** `test_empty_adrs_case`, `test_drift_detection`,
`test_drift_silent_when_index_missing`, `test_check_docs_flags_drift`,
`test_fresh_scaffold_passes_staleness`, `test_cmd_docs_adr_routes`,
`test_parse_id_list_fields` — they are unaffected by the row-cell change.

---

## Step 3 — `tests/unit/test_docs_check.py`: prove ADR-reachable-via-index

File: `docex/tests/unit/test_docs_check.py`.

### 3a. Add the import.

Find:

```python
from docex.docs.check import (
    check_docs,
    design_root_exists,
    missing_standard_files,
    unreachable_docs,
)
from docex.docs.scaffold import scaffold_design
```

Add the adr import below it:

```python
from docex.docs.check import (
    check_docs,
    design_root_exists,
    missing_standard_files,
    unreachable_docs,
)
from docex.docs.scaffold import scaffold_design
from docex.docs.adr import regenerate_adr_indexes
```

### 3b. Add the reachability proof at the end of the file.

```python
def test_adr_reachable_only_via_generated_index(tmp_path):
    # An ADR linked from NOWHERE but the generated index is still reachable: the
    # linked index carries the edge (mod 170). Before regeneration the stub index
    # is empty, so the ADR is a genuine orphan — proving the link is load-bearing.
    scaffold_design(tmp_path, ["api"])
    adrs = tmp_path / "plans" / "design" / "adrs"
    adrs.mkdir(parents=True, exist_ok=True)
    (adrs / "0001_thing.md").write_text(
        "---\nid: 0001\ntitle: thing\nstatus: accepted\n"
        "date: 2026-01-01\nsupersedes: []\nsuperseded-by: []\ntags: []\n---\n\n"
        "## Context\n...\n"
    )
    # Empty stub index -> the ADR is unreachable.
    before = unreachable_docs(tmp_path, ["api"])
    assert any("adrs/0001_thing.md" in p for p in before)
    # Regenerate: the index now links the ADR -> reachable, whole check green.
    regenerate_adr_indexes(tmp_path)
    assert unreachable_docs(tmp_path, ["api"]) == []
    assert check_docs(tmp_path, ["api"]) == 0
```

---

## Step 4 — Regenerate the tool-generated test-project indexes

The two nested test projects carry tool-generated ADR indexes that must be
regenerated with the new renderer (else they are stale under the new format).
docex's OWN dogfood indexes (`docex/plans/design/adr_index.md` / `adr_active.md`)
are hand-maintained — **do NOT touch them.**

From the `docex/` directory, with the same environment the tests run in, run:

```bash
cd /home/ubuntu/.claude/jean_baudrillard/docex
PYTHONPATH=src python -c "
from pathlib import Path
from docex.docs.adr import regenerate_adr_indexes
for p in ('test_projects/fixed', 'test_projects/elastic'):
    written = regenerate_adr_indexes(Path(p))
    print(p, '->', written)
"
```

(If `docex` is already importable without `PYTHONPATH=src` in this environment, the
bare `python -c` works too — use whichever imports cleanly.)

Confirm with `git diff -- docex/test_projects/*/plans/design/adr_index.md
docex/test_projects/*/plans/design/adr_active.md` that the **only** change per row
is the `ADR ID` cell gaining a `[<id>](adrs/<file>.md)` link — the marker, headings,
columns, and all other cells identical.

---

## Step 5 — Run the relevant tests

Per the mod cycle (only tests relevant to the change; the full suite runs later in
the advance smoke test):

```bash
cd /home/ubuntu/.claude/jean_baudrillard/docex
python -m pytest tests/unit/test_docs_adr.py tests/unit/test_docs_check.py -q
```

All must pass. If import of `docex` fails, use the project's standard invocation
(the same one `tests/README.md` documents). Report the pass/fail counts.

---

## Done criteria

- `adr.py`: `Adr.filename` added, populated in `parse_adr`; `_adr_link` helper
  added; ID cell linked in both `render_index` and `render_active`; nothing else
  changed.
- `test_docs_adr.py`: row asserts updated to the link form; two new link tests;
  filename assertion added.
- `test_docs_check.py`: adr import added; ADR-reachable-via-index test added.
- Both test-project index pairs regenerated (ID cells linked; nothing else).
- `python -m pytest tests/unit/test_docs_adr.py tests/unit/test_docs_check.py`
  green.
- No `doctrine/**`, no `docex/plans/design/**`, no `CHANGELOG.md` edits.

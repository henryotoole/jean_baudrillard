# Mod 170 — `docs_adr_reference_links`: a reference-linked ADR index

## Goal

`docex docs adr` today renders `adr_index.md` and `adr_active.md` as plain-text
tables with **no links to the ADR files**. Because `docs check`'s reachability
treats the two ADR indexes as standard roots, an ADR reachable *only* through the
index is flagged unreachable unless a narrative doc also links it — which is wrong:
a superseded ADR should not have to link back into the docs. The fix: the generated
index must carry the reference link itself, so the index root reaches every ADR.

Source of truth: `plans/advances/013_docs_check_hardening/advance_plan.md` § Goal 1;
root cause in `plans/advances/011_archdoc_skills/doc_converter_test_snags.md` snag I.

## Design

### The change

`render_index` / `render_active` (in `src/docex/docs/adr.py`) gain a single change:
the **first cell** of each ADR data row — the `ADR ID` cell — becomes a markdown
link to that ADR's source file, relative to the index (which sits at
`plans/design/adr_index.md`):

```
| 0001 | title | accepted | … |      →   | [0001](adrs/0001_title.md) | title | accepted | … |
```

Everything else is byte-identical: the `<!-- generated … do not edit -->` marker,
the `#` heading, the column header, the separator row, and every other cell. Only
the ID cell of each data row gains a link. The empty-ADR-set render (header +
separator only) is therefore unchanged — a fresh scaffold stays byte-identical.

Because the link resolves (relative to `plans/design/`) to a real enumerated design
file, `docs check`'s reachability graph gains an edge `adr_index.md → adrs/<file>.md`,
making the ADR reachable from the index root with no narrative inbound link.

### Design decisions (all within the plan's success criteria)

1. **Link the `ADR ID` cell, not the title.** The plan permits "title (or ID)".
   The ID cell is chosen because (a) it is the safest cell — an ADR id is a short
   token (`0001`) with no characters that could break a markdown link or table
   cell, whereas a human title can carry punctuation; and (b) it matches the
   **existing in-repo precedent**: docex's own hand-maintained dogfood indexes
   (`docex/plans/design/adr_index.md`, `adr_active.md`) already link the ID cell
   (`[0001](./adrs/0001_….md)`). The title cell stays bare text.

2. **Carry the real on-disk filename in the `Adr` record; do not derive the path
   from `id`+`title`.** The link target must be the ADR file's *actual* name, or the
   link resolves to a non-existent path and the ADR stays unreachable (a silent
   regression the reachability gate would then correctly flag). The doctrine
   filename is `${id}_${snake_case_title}.md`, but the frontmatter `title` is a
   *human* title that need not equal the snake_case filename stem — so deriving the
   path from frontmatter can drift from disk. Instead, `parse_adr(path)` already has
   the real path; the `Adr` dataclass gains a `filename` field populated from
   `path.name`, and the link is `adrs/${filename}`. This **cannot drift from the file
   on disk** because it *is* the file on disk. (Sergeant explicitly delegated this
   choice: "pick whichever cannot drift from the actual file on disk.")

3. **Path form `adrs/${filename}`** (no `./` prefix), matching the plan's literal
   spec `adrs/${id}_${title}.md`. Resolves identically to docex's `./adrs/` dogfood
   form via `(index.parent / raw).resolve()`.

4. **Reachability logic is untouched.** This mod only changes what `docs adr`
   *emits*; `check.py`'s reachability algorithm is unchanged. (Extending the check
   itself is mod 171.) The new edge appears purely because the emitted index now
   contains a resolvable markdown link, which the existing link extractor already
   turns into a graph edge.

5. **Regenerate the tool-generated test-project indexes.** `test_projects/fixed`
   and `test_projects/elastic` carry tool-generated (`<!-- generated … -->`) indexes
   that would otherwise be stale under the new renderer and fail their own
   `docs check`. They are regenerated with the new renderer as part of this mod
   (deterministic; no test couples to them). docex's **own** dogfood indexes are
   **not** touched — they are hand-maintained (docex has no `project.yml`/`infra.yml`
   so the CLI cannot run against docex itself), already link the ID cell, already
   reachable, and deliberately diverge in header prose.

### Why this is safe

- **Determinism / idempotency preserved.** The render is still a pure function of
  the sorted `Adr` list; the link is a pure function of `id` + `filename`. Two runs
  produce byte-identical output; the `adr_index_drift` gate regenerates-and-diffs
  and therefore agrees with the new format automatically.
- **No new consumer risk.** Nothing parses the ID cell as bare text — the drift
  gate compares against the render, and reachability only extracts links. Verified
  by grep across `src/`.

## Six-artifact alignment (docex-internal)

| Artifact | Action |
| --- | --- |
| `doctrine/.../*.md` | `doctrine/practices/adrs.md` (§ ADR Index / § Docex — index links each ADR to its file, reachable via the index); `doctrine/practices/docs.md` (§ Reachability Check — ADRs are reachable via the linked index, no narrative inbound link required); `doctrine/infrastructure/docex.md` (§ docs `adr` verb — notes the reference links). **Corporal, documentation step.** |
| `docex/plans/design/**` | `specifics/subcommand_surface.md` `docs adr` description gains the reference-link note. **Corporal, documentation step.** |
| `tables/roles/*.yml` | **N/A** — `docs` is a command, not a role/engine. |
| `src/docex/**` | `src/docex/docs/adr.py` — `Adr.filename` field + linked ID cell. **Implementation step.** |
| `tests/**` | `tests/unit/test_docs_adr.py` (link-format + updated row asserts), `tests/unit/test_docs_check.py` (ADR-reachable-via-index proof). **Implementation step.** |
| `doctrine_excerpts/*.md` + `index.yml` | **N/A** — no infrastructural *resource* is introduced/retired/renamed; no excerpt restates the ADR-index format (grep-verified). |

## Success criteria mapping

1. ID cell linked to `adrs/${filename}` in both files → decisions 1–3; test asserts.
2. ADR reachable from index root with no narrative link → new `test_docs_check.py` test.
3. Deterministic + idempotent; `adr_index_drift` agrees → pure render; existing idempotency test retained.
4. Marker + columns unchanged, only cell contents gain links → decision (only ID cell changes).
5. Six-artifact alignment → table above.

## Design questions

None. All decisions sit inside the plan's success criteria and the sergeant's
explicit delegation (ID-vs-title, filename-vs-derived). No change to the ADR
file-path convention and no ripple into the reachability logic, so no escalation.

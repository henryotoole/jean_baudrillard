# Mod 165 — `docex docs linkmap <depth>`

## Goal

Add a `linkmap` verb to the existing `docex docs` command group that emits the
project's full documentation/code **link graph** as deterministic JSON to stdout,
and refactor the existing reachability check to consume that one graph. This is
Goal 1 of advance 011 (archdoc skills). Design intent:
`plans/advances/011_archdoc_skills/docex_doc_design.md § linkmap` and
`advance_plan.md § Goal 1`.

## Behavior

`docex docs linkmap <depth>` where `<depth>` ∈ {`design_docs`, `code_level`}.

- **`design_docs`** — the tracked scope is `plans/design/**` only.
- **`code_level`** — the tracked scope is `plans/design/**` **plus** each
  codebase's `core/<cb>/src/**`, restricted to **git-tracked files** (so
  compiled artifacts like `.pyc` never appear). `code_level` is a strict
  superset of `design_docs`.

Emits the full graph (nodes + edges) as JSON to **stdout**, including every
in-scope file even those unreachable from the roots. Output discipline mirrors
`docex describe --format llm`: pure JSON on stdout, diagnostics to stderr,
`json.dumps(..., indent=2, sort_keys=True)` with all lists deterministically
sorted, emitted once, nonzero exit on failure.

### Node model

One node per file (each keyed by its project-relative `fpath`). Fields:

| Field | Meaning |
| ----- | ------- |
| `fpath` | project-relative POSIX path (the node key). For an out-of-scope target that resolves outside the project root, an `os.path.relpath` `../`-style path. |
| `type` | `design` (under `plans/design`), `source` (under a codebase's `core/<cb>/src`, git-tracked), or `neither` (an edge target outside **this depth's** tracked scope). |
| `is_standard` | `true` iff the file is a doctrine-named standard file (from `standard_set.resolve()` — the arc42 L1 files, standard diagrams, ADR indices, per-codebase `module_diagram.mmd`, etc.). A `{module}.md` doc is **not** standard (name varies); `doctrine_ext.md` **is** (standard even if optional). Source and `neither` nodes are never standard. |
| `level` | `L1` / `L2` / `L3` / `C`, or `null` for `neither`. Design: L1 = project-scoped (`plans/design/*` + `adrs/*`), L2 = codebase-scoped non-module (`plans/design/<cb>/module_diagram.mmd`, `specifics/*`), L3 = module doc (`plans/design/<cb>/module/*`). Source = `C`. |
| `codebase` | The owning codebase (`<cb>` from `plans/design/<cb>/…` when `<cb>` is a real `infra.yml` codebase, or from `core/<cb>/src/…`); otherwise `"none"`. |
| `module` | `<module>` from `plans/design/<cb>/module/<module>.md` or `core/<cb>/src/hex/<module>/**`; otherwise `"none"`. |
| `tokens` | Estimated LLM context cost of reading the file (see [token estimation](#token-estimation)); `null` for `neither`. |

**`type` is depth-relative.** The `neither` type exists to record edge targets
that fall *outside the depth's tracked scope* (design line 27). So a `plans/design`
doc that links to a `core/api/src/foo.py` file yields a **`neither`** node under
`design_docs` (source isn't scanned at that depth) but a **`source`** node under
`code_level`. `neither` nodes are recorded so the edge is not lost, but they are
never read (no `tokens`, no outgoing-edge scan).

### Edge model

Edges connect two nodes `a` and `b`, where `a`/`b` are the pair's two `fpath`s
**ordered lexicographically** (deterministic). Fields:

| Field | Meaning |
| ----- | ------- |
| `a`, `b` | the two endpoint `fpath`s, `a < b` by string order. |
| `link_type` | `markdown`, `mermaid_click`, or `emergent`. |
| `direction` | `a_to_b`, `b_to_a`, or `both`. |

Reciprocal links of the **same** `link_type` between the same pair merge into one
edge with `direction: both`. A lone link from the higher-sorted file to the
lower-sorted one is `b_to_a`; otherwise `a_to_b`. Different `link_type`s between
the same pair remain distinct edges.

**Link sources:**
1. `markdown` — inline `[text](target)` links (existing `_MD_LINK`).
2. `mermaid_click` — mermaid `click … "target"` directives (existing `_MMD_CLICK`),
   in both `.mmd` files and fenced mermaid blocks inside `.md`.
3. `emergent` — the one structurally-emergent rule (design § Structurally-Emergent
   Links): a hex source file `core/<cb>/src/hex/<module>/**` gets an edge to its
   module doc `plans/design/<cb>/module/<module>.md` **when that doc exists**.
   Directed source → doc.

External links (a URL scheme, per the existing `_SCHEME` guard) and unresolvable
targets are skipped, exactly as `_links_in` already does.

### JSON shape

```json
{
  "depth": "code_level",
  "nodes": [ { "fpath": "...", "type": "...", "is_standard": false,
               "level": "L3", "codebase": "api", "module": "orders",
               "tokens": 512 }, ... ],
  "edges": [ { "a": "...", "b": "...", "link_type": "markdown",
               "direction": "a_to_b" }, ... ]
}
```

`nodes` sorted by `fpath`; `edges` sorted by `(a, b, link_type)`.

## Reachability refactor

The existing `unreachable_docs()` (used by `docs check` and the `docex check`
gate) is refactored to **build the `design_docs` linkmap and compute orphans from
it** — one graph source of truth. Mechanics:

- A shared graph builder produces nodes + edges for a given depth.
- `unreachable_docs()` builds the `design_docs` graph, identifies the root nodes
  (the existing `_ROOT_NAMES` at `plans/design/` + each codebase's
  `module_diagram.mmd`), and BFS-traverses the directed adjacency derived from the
  edges (an edge contributes `a→b` when `direction ∈ {a_to_b, both}` and `b→a`
  when `direction ∈ {b_to_a, both}`), following only edges to in-scope `design`
  nodes.
- Orphans = in-scope `design` nodes not reached. **The returned problem strings
  are byte-for-byte unchanged**, so `docs check`, its tests, and the `docex check`
  gate stay green.

`_links_in` remains the shared link-extraction primitive; the graph builder wraps
it (adding per-link `link_type` tagging, which `_links_in` currently discards).

## Resolved design points

The advance left three open; resolved here (corporal authority — none forces new
infra, a doctrine-file rule change, or another codebase's design docs):

1. **`link_type` encoding → self-describing strings** `"markdown"` /
   `"mermaid_click"` / `"emergent"`. The JSON is consumed by outside agents/skills
   (Mod 167's `overhead`/`cxt_groups`, the `doc-refine-orchestration` skill);
   readable, stable string tags beat an int enum whose meaning lives elsewhere.
   Deterministic. (Rejects the design NOTE's `md`/`mmd`/`emerg` abbreviations and
   the int-enum alternative.)

2. **`direction` encoding → strings** `"a_to_b"` / `"b_to_a"` / `"both"` over the
   lexicographically-ordered `(a, b)` pair, with reciprocal same-type links merged
   to `both`. Honors the design's three-value direction datum exactly, is fully
   deterministic, and lets a consumer reconstruct directed adjacency trivially.

3. **Other link forms → none beyond the three.** The doctrine doc corpus uses only
   markdown inline links and mermaid `click` directives; `emergent` covers the
   structural case. No HTML anchors or reference-style links are present to warrant
   more. (Resolves the design TODO with the plan's default.)

Two further implementation calls made here:

4. **Token estimation → `max(1, round(len(text) / 4))`** over the file's decoded
   text — the standard ~4-chars-per-token heuristic. **No new dependency**
   (avoids adding `tiktoken`, which would be new infrastructure). Deterministic
   and good enough for the `cxt_groups` heuristic that consumes it (Mod 168
   calibrates accuracy). `null` for `neither` (unread) nodes.

5. **Git-tracked enumeration → a new `ls_files()` on the `GitClient` Protocol**
   (`git ls-files -- <pathspec>`) with a `SubprocessGitClient` implementation,
   mirroring the existing client abstraction. Used only by `code_level` to list
   `core/<cb>/src` source files; crosses the real git boundary, so it earns an
   integration test.

## Files touched

- `src/docex/docs/linkmap.py` — **new.** Node/Edge dataclasses, the depth-aware
  graph builder (`build_linkmap`), JSON rendering, and `run_docs_linkmap(ctx, depth)`.
- `src/docex/docs/check.py` — refactor `unreachable_docs()` onto the graph builder;
  keep `_links_in` (now returning tagged links, or a small wrapper that does).
- `src/docex/docs/__init__.py` — export the new public functions.
- `src/docex/__main__.py` — add the `linkmap <depth>` subparser to `_cmd_docs`;
  update the `_cmd_docs` docstring.
- `src/docex/git/client.py` + `src/docex/git/subprocess_client.py` — add `ls_files`.

## Tests

- `tests/unit/test_docs_linkmap.py` — **new.** Node metadata (type/level/codebase/
  module/is_standard/tokens) across representative fixture paths; markdown +
  mermaid-click + emergent edge extraction; direction merging (`a_to_b`/`b_to_a`/
  `both`); `neither` nodes for out-of-scope targets; depth-relative typing;
  deterministic sorted JSON; both depths (design_docs via `tmp_path`; code_level's
  pure graph logic via an injected file list / fake git client).
- `tests/unit/test_docs_check.py` — extend to assert the refactored
  `unreachable_docs` output is unchanged (existing tests must stay green as-is).
- `tests/unit/test_docs_dispatcher.py` — `linkmap` wired and arg-validated.
- `tests/integration/test_docs_linkmap_real.py` — **new, `@pytest.mark.integration`.**
  `code_level` against a real temp git repo: git-tracked source appears,
  untracked/ignored (`.pyc`) does not.

Test discipline: unit (`python -m pytest tests`) and integration
(`python -m pytest tests -m integration`) run as **separate** invocations from
`docex/`; the `test_collection_partition` guard stays satisfied; close with a full
suite run.

## Artifact alignment (six-artifact)

- `doctrine/.../*.md` — **`doctrine/infrastructure/docex.md § docs`** updated to
  document the `linkmap` verb and its JSON output format (pre-authorized by the
  C.O. in the Goal 1 success criteria; scoped narrowly to the `docs` section).
- `docex/plans/core/masterplan.md` — the `docs` command row updated to list
  `linkmap` and note reachability now consumes it.
- `tables/roles/*.yml` — **n/a** (no role/engine change).
- `src/docex/**`, `tests/**` — above.
- `doctrine_excerpts/*.md` + `index.yml` — **n/a**: `linkmap` introduces no new
  *infrastructural resource*, only a docs verb, so the excerpt index is unaffected
  (per docex_process § What earns an entry).

## Out of scope

The `overhead`, `changed`, `cxt_groups` verbs (Mod 167), the docex doc migration
to `plans/design` (Mod 166), and token-estimate calibration (Mod 168). This mod
delivers the linkmap and the reachability refactor only.

## Open design questions for C.O.

None blocking. One item for awareness: this mod updates `doctrine/infrastructure/docex.md § docs`
(documenting the new verb's output format) — a doctrine edit, but one you
pre-authorized in the Goal 1 criteria and scoped to the `docs` section. Flagging
per the "ask before altering doctrine" rule; proceeding unless you object.

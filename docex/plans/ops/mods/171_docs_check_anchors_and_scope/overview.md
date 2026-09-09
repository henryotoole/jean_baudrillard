# Mod 171 — `docs_check_anchors_and_scope`

## Goal

Harden `docex docs check` with two additions surfaced by the Nasmyth
doc-conversion test run (advance 013, Goal 2; snags **M** and **O**). Both live in
the same file-enumeration / link-graph core, so they are one mod:

- **2a — Anchor Resolution (snag M):** a new, fourth `docs check` validator. Every
  markdown link in a design doc that carries a `#fragment` and points at an in-scope
  design doc (same-file `#frag` included) must resolve to a real heading (GitHub-slug)
  or an explicit `<a id="…">` anchor in the target. Today reachability validates that
  a file is *linked*, never that a `#fragment` *resolves* — so a link to a reworded /
  de-emoji'd heading, or cross-file anchor drift, passes silently.
- **2b — Doc-extension-scoped reachability (snag O):** the reachability population is
  narrowed from *every file* under `plans/design` to a documentation-extension
  allowlist (`.md`, `.mmd`, `.txt`). A loose non-doc asset (an `.svg`/`.png`/`.pdf`)
  under `plans/design` no longer fails reachability as an "unreachable doc."

## Design

### Where the code lives

Both additions extend the **existing** shared link-graph core — no second link
walker, no new file walk:

- `docex/src/docex/docs/linkmap.py` — the single source of truth for the design link
  graph (`build_linkmap`, the `_MD_LINK` regex, `_tagged_links_in`, and the shared
  enumerator `_enumerate_design_files`). Reachability and `docs linkmap` already share
  it.
- `docex/src/docex/docs/check.py` — `check_docs` concatenates the validators;
  `unreachable_docs` runs the reachability enumeration. The fourth validator is added
  here.

### 2a — Anchor Resolution

New **pure** helpers added to `linkmap.py` (the link-graph module — kept here so the
anchor index is part of the one link source-of-truth, reusing its `_MD_LINK` regex and
its file enumeration):

- `_slug(heading: str) -> str` — GitHub's heading-anchor algorithm: lowercase, strip
  characters outside `[\w\s-]`, then map **each** whitespace char to one hyphen (no
  run-collapsing — `Driven Port / Adapter Patterns` → `driven-port--adapter-patterns`).
  This is byte-for-byte the algorithm the cohere executor `linkcheck.py::slugify`
  already uses and the one the operator's hand-rolled checker used during the Nasmyth
  test, satisfying "matches the renderer already assumed elsewhere."
- `anchors_in(path) -> set[str]` — the set of anchors a file defines:
  - Every `#…######` heading's slug, with GitHub's numeric de-duplication
    (`foo`, `foo-1`, `foo-2`, …). Headings inside fenced code blocks
    (```` ``` ````/`~~~`) are ignored (a `#` in a code block is not a heading).
  - Every explicit `<a id="…">` anchor (case-insensitive), honored so a source-cited
    frozen anchor can be pinned deliberately.
- `fragment_links_in(path) -> list[tuple[Path, str]]` — reuses the shared `_MD_LINK`
  regex; returns `(resolved_target_abs, fragment)` for every markdown link **carrying a
  non-empty `#fragment`**. A bare same-file `#frag` resolves its target to the file
  itself; a scheme-bearing (external) target is dropped, matching `_resolve_link`'s
  existing guards.

New validator in `check.py`, added as the **fourth** check in `check_docs`:

- `unresolved_anchors(project_root, codebase_names) -> list[str]` — walks the same
  `_enumerate_design_files` list (one enumeration, shared), builds the in-scope design
  set, and for each fragment link whose target **is an in-scope design file**, fails if
  the fragment is not in that target's `anchors_in`. Message form:
  `unresolved anchor: <file> -> <target>#<frag>` (project-relative posix paths). Anchor
  sets are cached per target file within a run.

**Scope rule (criterion 2a.4), made explicit:** a `#fragment` whose target is **not**
an in-scope design doc — a `../references/*` file, a source file, an out-of-tree path,
or any target the reachability enumeration does not scan — is **not** validated and
**not** failed. The check only asserts anchors it can actually see the definitions for.
Documented in doctrine + the docstring so the boundary is deliberate, not accidental.

### 2b — Doc-extension-scoped reachability

A module-level allowlist `_DOC_EXTS = {".md", ".mmd", ".txt"}` is applied in the
**shared** enumerator `_enumerate_design_files` (linkmap.py), and `unreachable_docs`
is refactored to consume that same enumerator instead of its own private `rglob`. One
enumeration, one allowlist, so reachability, the anchor check, and `docs linkmap` keep
a single view of the design scope. Consequences:

- A loose `frontend/specifics/icons/logo.svg` under `plans/design` is no longer a
  `design` node anywhere, so it cannot fail reachability. If a doc *links* to it, it
  becomes a `neither` edge-stub (like a `references/*` target) — never required to be
  reachable.
- `.mmd` stays in the allowlist — the standard diagrams are first-class docs and are
  link sources/roots.

This narrows **only which files must be reachable.** The Missing-Standard-File,
ADR-fresh, and new Anchor-Resolution checks are unaffected (Missing-Standard-File reads
the standard set directly; ADR-fresh diffs the indexes; anchors validate links, not the
population).

### What is deliberately NOT changed (no ripple, no escalation)

The `Node` dataclass and the `docs linkmap` JSON schema are **untouched** — no anchor
field is threaded through `build_linkmap`'s return, so `docs linkmap` / `overhead` /
`cxt_groups` / `changed` consumers see no shape change. The one content change to the
linkmap is that a loose non-doc asset is no longer enumerated as a `design` node (it
becomes a `neither` stub only if linked), which is correct: an asset is not a design
doc. Because the design forced **no** public-shape change to `Node` or the linkmap JSON,
the escalation trigger the advance plan named (threading anchors through `build_linkmap`
in a way that ripples to linkmap consumers) does not fire.

### Mod 170 non-regression

Mod 170's ADR-index links are fragment-less (`adrs/0001_foo.md`). `fragment_links_in`
skips any link without a `#`, so the anchor check leaves them untouched. Confirmed by a
green `check_docs` on a scaffolded tree with a linked ADR index.

## Six-artifact alignment

1. **Doctrine `*.md`:**
   - `doctrine/practices/docs.md § Reachability Check` — "enumerates every file" →
     "enumerates every documentation file (`.md`, `.mmd`, `.txt`)"; add an
     **Anchor Resolution** subsection describing the new check and its scope rule.
   - `doctrine/infrastructure/docex.md § docs` — the `check` bullet's "Three checks" →
     "Four checks", adding the Anchor Resolution bullet.
2. **`docex/plans/design/**`:**
   - `specifics/subcommand_surface.md` — the `docs check` cell lists three checks → add
     anchor resolution (four); note the doc-extension reachability scope.
   - `structures_and_views.md` — "`docs check`'s three gates" → four gates.
3. **`tables/roles/*.yml`:** N/A — `docs check` is unrelated to roles/engines. Confirmed.
4. **`src/docex/**`:** the code (linkmap.py helpers + check.py validator + allowlist).
5. **`tests/**`:** unit tests in `test_docs_check.py` (negative anchor fixture: cross-file
   `other.md#no-such-heading` + same-file `#gone`; correcting → green; loose-`.svg`
   fixture → green; explicit `<a id>` honored; mod-170 ADR-index non-regression) and
   `test_docs_linkmap.py` (`_slug`, `anchors_in` incl. fence-skip + dup-suffix +
   explicit anchor, `fragment_links_in`, and the `_DOC_EXTS` enumeration filter).
6. **`doctrine_excerpts/*.md` + `index.yml`:** N/A — the excerpts index infrastructural
   *resources*; none restate the `docs check` check-list or reachability text.
   Confirmed by grep.

## Design questions

None. The design stays within the advance-plan criteria and forced no public-shape
change, so nothing required escalation.

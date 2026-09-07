# Mod 171 — Implementation Steps

`docs_check_anchors_and_scope`. Two additions to `docex docs check`, both on the
shared link-graph core. Repo root of the docex codebase: `/home/ubuntu/.claude/jean_baudrillard/docex`
(referred to below as `$docex`). Run change-relevant tests only (see step 6).

There are **no core-service contracts** to update (docex has no `infra.yml`/surfaces).

---

## Step 1 — `linkmap.py`: slug + anchor + fragment primitives, and the doc-extension allowlist

File: `$docex/src/docex/src/docex/docs/linkmap.py`
(actual path: `$docex/src/docex/docs/linkmap.py`).

### 1a. New regexes + allowlist constant

Immediately after the existing `_SCHEME = re.compile(...)` line (near the top,
after `_MMD_CLICK`), add:

```python
_HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
_EXPLICIT_ANCHOR = re.compile(
    r'<a\s+[^>]*\bid\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE
)
_FENCE = re.compile(r"^\s*(```|~~~)")

# Reachability / design-scope population is documentation files only (mod 171,
# snag O): a loose non-doc asset (an icon .svg, a .png) under plans/design is
# not a design doc and must not be required to be reachable. `.mmd` stays — the
# standard diagrams are first-class docs and are link sources/roots.
_DOC_EXTS = {".md", ".mmd", ".txt"}
```

### 1b. New pure helpers

Add these three functions in the "Link extraction" section (after
`_tagged_links_in`):

```python
def _slug(heading: str) -> str:
    """GitHub's heading-anchor slug.

    Lowercase, strip characters outside ``[\\w\\s-]``, then map EACH whitespace
    char to one hyphen (runs are NOT collapsed — ``Driven Port / Adapter
    Patterns`` -> ``driven-port--adapter-patterns``). Byte-for-byte the algorithm
    the cohere executor ``linkcheck.py::slugify`` uses and the hand-rolled checker
    used during the Nasmyth conversion test — the renderer assumed elsewhere.
    """
    h = heading.strip().lower()
    h = re.sub(r"[^\w\s-]", "", h)
    h = re.sub(r"\s", "-", h)
    return h


def anchors_in(path: Path) -> set[str]:
    """Every anchor a file defines: heading slugs + explicit ``<a id>`` anchors.

    Heading slugs carry GitHub's numeric de-duplication (``foo``, ``foo-1``,
    ``foo-2`` …). Headings inside fenced code blocks (```` ``` ````/``~~~``) are
    ignored — a ``#`` there is not a heading. Explicit ``<a id="...">`` anchors are
    honored so a source-cited frozen anchor can be pinned deliberately. Pure;
    returns an empty set for an unreadable file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    non_fence: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            non_fence.append(line)
    heading_src = "".join(non_fence)
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for m in _HEADING.finditer(heading_src):
        s = _slug(m.group(1))
        if s in seen:
            seen[s] += 1
            anchors.add(f"{s}-{seen[s]}")
        else:
            seen[s] = 0
            anchors.add(s)
    for m in _EXPLICIT_ANCHOR.finditer(text):
        anchors.add(m.group(1))
    return anchors


def fragment_links_in(path: Path) -> list[tuple[Path, str]]:
    """``(resolved_target_abs, fragment)`` for each markdown link with a
    non-empty ``#fragment``.

    Reuses the shared ``_MD_LINK`` regex — no second link walker. A bare same-file
    ``#frag`` resolves its target to ``path`` itself; a scheme-bearing (external)
    target is dropped, matching ``_resolve_link``'s guards. Returns ``[]`` for an
    unreadable file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[tuple[Path, str]] = []
    for raw in _MD_LINK.findall(text):
        raw = raw.strip()
        if "#" not in raw:
            continue
        target_part, frag = raw.split("#", 1)
        target_part = target_part.strip()
        frag = frag.strip()
        if not frag:
            continue
        if target_part == "":
            out.append((path.resolve(), frag))
            continue
        if _SCHEME.match(target_part):
            continue
        try:
            out.append(((path.parent / target_part).resolve(), frag))
        except (OSError, ValueError):
            continue
    return out
```

### 1c. Apply the allowlist in the shared enumerator

In `_enumerate_design_files`, add the extension filter and update the docstring.
Replace the function body's loop guard so it skips non-doc extensions:

```python
def _enumerate_design_files(project_root: Path) -> list[Path]:
    """Every DOCUMENTATION file (``.md``/``.mmd``/``.txt``) under ``plans/design``,
    skipping dot-parts.

    Restricting to doc extensions (mod 171, snag O) keeps a loose non-doc asset —
    an icon ``.svg``, a ``.png`` — from being enumerated as a design node and thus
    failing reachability as an "unreachable doc." This is THE single design-scope
    enumeration: ``unreachable_docs`` and the anchor check consume it too, so the
    three keep one view of the design scope.
    """
    base = project_root / "plans" / "design"
    if not base.is_dir():
        return []
    out: list[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _DOC_EXTS:
            continue
        rel = p.relative_to(base)
        if any(part.startswith(".") for part in rel.parts):
            continue  # skip .gitkeep and anything under a dot-dir
        out.append(p)
    return out
```

---

## Step 2 — `check.py`: consume the shared enumerator + add the fourth validator

File: `$docex/src/docex/docs/check.py`.

### 2a. Imports

Extend the `from docex.docs.linkmap import (...)` block to also import
`_enumerate_design_files`, `anchors_in`, and `fragment_links_in`:

```python
from docex.docs.linkmap import (
    _MD_LINK,
    _MMD_CLICK,
    _SCHEME,
    _enumerate_design_files,
    _tagged_links_in,
    anchors_in,
    build_linkmap,
    fragment_links_in,
)
```

Add `"unresolved_anchors"` to `__all__`.

### 2b. Refactor `unreachable_docs` onto the shared enumerator

In `unreachable_docs`, delete the private `rglob` loop that builds `design_files`
and replace it with a call to the shared enumerator. The function becomes:

```python
    base = _design_root(project_root)
    if not base.is_dir():
        return []

    design_files = _enumerate_design_files(project_root)

    nodes, edges = build_linkmap(
        project_root, codebase_names, "design_docs", design_files, []
    )
    ...  # (rest unchanged)
```

(`base` is still used further down to build the root fpaths — keep it.)

### 2c. New validator `unresolved_anchors`

Add this function (place it after `unreachable_docs`, before `check_docs`):

```python
def unresolved_anchors(
    project_root: Path, codebase_names: list[str]
) -> list[str]:
    """Fragment links whose ``#anchor`` does not resolve in the target doc.

    For every markdown link in a design doc carrying a ``#fragment`` whose target
    is an IN-SCOPE design doc (same-file ``#frag`` included), the fragment must be
    a heading slug or an explicit ``<a id>`` anchor in that target. Reachability
    validates that a file is *linked*, never that a fragment *resolves*; this is
    the class it cannot see (a reworded / de-emoji'd heading, cross-file anchor
    drift).

    Scope (deliberate, not accidental): a ``#fragment`` whose target is NOT an
    in-scope design doc — a ``references/*`` file, a source file, an out-of-tree
    path, or any target the design enumeration does not scan — is NOT validated
    and NOT failed. The check only asserts anchors whose definitions it can see.

    Built on the shared design enumeration and the linkmap's link/anchor
    primitives — no second walker.
    """
    base = _design_root(project_root)
    if not base.is_dir():
        return []
    design_files = _enumerate_design_files(project_root)
    rel_by_resolved = {
        p.resolve(): p.relative_to(project_root).as_posix()
        for p in design_files
    }
    in_scope = set(rel_by_resolved)
    anchor_cache: dict[Path, set[str]] = {}

    def _anchors(target: Path) -> set[str]:
        if target not in anchor_cache:
            anchor_cache[target] = anchors_in(target)
        return anchor_cache[target]

    problems: list[str] = []
    for p in design_files:
        src_rel = p.relative_to(project_root).as_posix()
        for target_abs, frag in fragment_links_in(p):
            if target_abs not in in_scope:
                continue  # target not scanned -> fragment not validated (docstring)
            if frag not in _anchors(target_abs):
                tgt_rel = rel_by_resolved[target_abs]
                problems.append(
                    f"unresolved anchor: {src_rel} -> {tgt_rel}#{frag}"
                )
    return sorted(problems)
```

### 2d. Wire it into `check_docs`

Add `unresolved_anchors` to the concatenated problem list, between reachability
and ADR drift:

```python
    problems = (
        missing_standard_files(project_root, codebase_names)
        + unreachable_docs(project_root, codebase_names)
        + unresolved_anchors(project_root, codebase_names)
        + adr_index_drift(project_root)
    )
```

---

## Step 3 — Unit tests: `tests/unit/test_docs_linkmap.py`

File: `$docex/tests/unit/test_docs_linkmap.py`. Extend the import to include
`_slug`, `anchors_in`, `fragment_links_in`, and `_enumerate_design_files` from
`docex.docs.linkmap`. Add tests:

1. **`test_slug_matches_github_no_collapse`** — `_slug("Driven Port / Adapter
   Patterns") == "driven-port--adapter-patterns"`; `_slug("⚠️ meta is data")`
   starts with a leading hyphen (emoji stripped leaves a leading space →
   hyphen); `_slug("Keeps_Underscore") == "keeps_underscore"`.
2. **`test_anchors_in_headings_and_dedup`** — a file with `# A`, `## A` yields
   `{"a", "a-1"}`; a `### B C` yields `b-c`.
3. **`test_anchors_in_skips_fenced_headings`** — a `#`-prefixed line inside a
   ```` ``` ```` fence is NOT an anchor.
4. **`test_anchors_in_explicit_id`** — `<a id="frozen"></a>` (any attribute order,
   case-insensitive) yields `frozen`.
5. **`test_fragment_links_in`** — a file with `[x](./other.md#sec)`,
   `[y](#local)`, `[z](./plain.md)` (no frag), and `[w](https://h/x#f)` yields
   exactly the first two: cross-file target resolves under the file's dir with
   fragment `sec`; same-file `#local` targets the file itself; the fragment-less
   and external links are absent.
6. **`test_enumerate_design_files_doc_exts_only`** — write `plans/design/a.md`,
   `plans/design/x/diagram.mmd`, `plans/design/notes.txt`, and
   `plans/design/x/logo.svg`; `_enumerate_design_files` returns the first three,
   not the `.svg`.

## Step 4 — Unit tests: `tests/unit/test_docs_check.py`

File: `$docex/tests/unit/test_docs_check.py`. Import `unresolved_anchors` from
`docex.docs.check`. Add tests:

1. **`test_anchor_cross_file_unresolved_is_named`** — scaffold; write
   `plans/design/target.md` with `# Real Heading`; append to a standard root
   (e.g. `structures_and_views.md`) a link `[t](./target.md#no-such-heading)` AND
   a link `[t2](./target.md)` (so `target.md` is reachable). Assert
   `unresolved_anchors` contains a message matching
   `unresolved anchor: plans/design/structures_and_views.md -> plans/design/target.md#no-such-heading`,
   and `check_docs(...) == 1`.
2. **`test_anchor_same_file_dangling_is_named`** — append `[g](#gone)` to a
   standard root; assert an `unresolved anchor:` problem naming `#gone` with the
   target equal to the same file.
3. **`test_anchor_resolves_when_corrected`** — the same tree as test 1 but the
   link is `[t](./target.md#real-heading)`; `unresolved_anchors == []` and
   `check_docs == 0`.
4. **`test_anchor_explicit_id_resolves`** — target defines `<a id="pinned"></a>`
   and no matching heading; a link `...#pinned` resolves (no problem).
5. **`test_anchor_into_unscanned_target_not_failed`** — a link from a standard
   root to `../references/foo.md#whatever` (a path OUTSIDE `plans/design`, target
   need not exist) produces NO anchor problem — documents the scope rule.
6. **`test_loose_asset_does_not_fail_reachability`** (2b) — scaffold; write a
   binary-ish asset `plans/design/api/specifics/icons/logo.svg` with some bytes;
   assert `unreachable_docs(tmp_path, ["api"]) == []` and `check_docs == 0` (the
   `.svg` is not enumerated as a design doc).
7. **`test_mod170_adr_index_links_survive_anchor_check`** — reuse the mod-170
   pattern: scaffold, add an ADR, `regenerate_adr_indexes`, assert
   `unresolved_anchors(tmp_path, ["api"]) == []` (the index's links are
   fragment-less, so the anchor check leaves them alone) and `check_docs == 0`.

Keep the existing tests unchanged; they must still pass (scaffold templates carry
no fragment links, so the anchor check is a no-op on a clean scaffolded tree).

---

## Step 5 — Doctrine (the rule of record; change with the code)

### 5a. `doctrine/infrastructure/docex.md` § `docs`

In the `- **`check`**` bullet, change **"Three checks:"** to **"Four checks:"**
and add a fourth sub-bullet after the ADR-index one:

```
	+ Anchor Resolution - a markdown link's `#fragment` into an in-scope design doc must resolve to a real heading (GitHub slug) or explicit `<a id>` anchor. A fragment into a target the check does not scan (e.g. `references/*`, source) is not validated.
```

Also, in the same `docs` section's description of `check`'s reachability, if it
says the reachability enumerates "every file", align it to "documentation files"
(only if such wording is present in docex.md — the canonical wording lives in
docs.md, edited below).

### 5b. `doctrine/practices/docs.md` § Reachability Check

Change the sentence (line ~191):

> It enumerates every file under `plans/design`, builds the link graph …

to:

> It enumerates every **documentation file** (`.md`, `.mmd`, `.txt`) under
> `plans/design`, builds the link graph …

Then add a new subsection after "### Reachability Check" (before "### Missing
Standard File") describing the anchor check:

```markdown
### Anchor Resolution

Reachability proves a doc is *linked*; it cannot prove a `#fragment` *resolves*.
`docex docs check` additionally validates that every markdown link carrying a
`#fragment` whose target is an in-scope design doc (a same-file `#frag` included)
points at a real anchor in that target — a heading whose GitHub-style slug equals
the fragment, or an explicit `<a id="…">` anchor. A non-resolving fragment fails
with `unresolved anchor: <file> -> <target>#<frag>`. This catches a link to a
reworded or de-emoji'd heading and cross-file anchor drift, which reachability
passes silently.

The rule is scoped to targets the check can actually see: a `#fragment` into a
target *outside* the tracked design scope (a `references/*` file, a source file)
is **not** validated, since the check does not scan the target for its anchors.
```

Leave the reachability standard-roots list unchanged.

---

## Step 6 — Run change-relevant tests

From `$docex`:

```bash
.venv/bin/python -m pytest tests/unit/test_docs_check.py tests/unit/test_docs_linkmap.py -q
```

(If imports fail, prefix `PYTHONPATH=src`.) All must pass. Do **not** run the full
suite — that is the advance smoke test's job.

## Notes / boundaries

- Do NOT touch `docex/plans/design/**` (docex's own design docs) or `CHANGELOG.md`
  — those are handled in the mod cycle's documentation step by the driving agent.
- Do NOT change the `Node` dataclass, `build_linkmap`'s signature, or the
  `render_linkmap_json` output — the linkmap JSON shape must stay identical.
- Preserve the existing reachability problem-string format byte-for-byte (tests
  assert it).

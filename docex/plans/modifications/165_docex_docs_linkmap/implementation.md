# Mod 165 — Implementation Steps: `docex docs linkmap <depth>`

Execute these steps against the `docex` project at
`~/.claude/jean_baudrillard/docex` (its own project root; `$pr` below = that
path). Design rationale lives in `overview.md` in this folder — read it first.

Run all tests from `docex/`. Test invocation is **`python -m pytest`, never bare
`pytest`** (the bare binary silently collects nothing). Run only tests relevant
to this mod while iterating; the driving corporal runs the full suite at close.

---

## Step 1 — Add `ls_files` to the git client

Only `code_level` needs it (to enumerate git-tracked source). Mirror the existing
`GitClient` Protocol / `SubprocessGitClient` split.

### 1a. `src/docex/git/client.py`

Add to the `GitClient` Protocol (near the other read-only inspections like
`show`):

```python
def ls_files(self, cwd: Path, pathspec: str) -> list[str]:
    """Return git-tracked file paths under ``pathspec`` (repo-relative,
    POSIX), sorted. Empty list if none tracked or on failure.

    Used to enumerate a codebase's tracked source so compiled / generated
    artifacts (e.g. ``.pyc``) never enter the linkmap.
    """
    ...
```

### 1b. `src/docex/git/subprocess_client.py`

Implement it via `_capture`:

```python
def ls_files(self, cwd: Path, pathspec: str) -> list[str]:
    res = self._capture(["ls-files", "--", pathspec], cwd=cwd)
    if res is None:
        return []
    return sorted(line.strip() for line in res.splitlines() if line.strip())
```

`git ls-files` returns paths relative to the repo root, POSIX-separated — which is
what we want (docex's own repo root is `$jb`, but callers pass `cwd=project_root`
and a pathspec relative to it; `ls-files` output is relative to the repo root, so
the linkmap builder must resolve those against the repo root — see Step 2's note
on path resolution).

**Path-resolution note for Step 2:** `git ls-files` emits paths relative to the
**git repo root**, not necessarily `project_root`. For docex the project root *is*
a subfolder of the jean repo. To stay correct regardless, in the builder resolve
each `ls_files` entry to an absolute path via `(repo_root / entry)`, where
`repo_root` is obtained by running `ls-files` with `cwd=project_root` and treating
returned paths as repo-root-relative — **simplest robust approach:** call
`ls_files(cwd=project_root, pathspec="core/<cb>/src")` and, because we cannot
assume `project_root == repo_root`, filter/resolve by checking which returned
paths, when joined to the repo root, land under `project_root/core/<cb>/src`.

To avoid that ambiguity entirely, **use `--full-name` semantics through the
project root**: run the enumeration with `cwd=project_root` and pass the pathspec
as a path relative to `project_root` (`core/<cb>/src`); then map each returned
repo-relative path `p` to an absolute path and keep only those under
`project_root`. Concretely in the builder:

```python
repo_root = <resolve via `git rev-parse --show-toplevel` OR reuse project_root>
```

Prefer the pragmatic path: since every consumer here operates within
`project_root`, have the builder accept the **already-resolved list of absolute
source paths** as an argument (see Step 2 `build_linkmap` signature) and let
`run_docs_linkmap` do the git call + resolution. This keeps `build_linkmap` pure
and unit-testable without git. For resolution in `run_docs_linkmap`, obtain the
repo root with a `SubprocessGitClient` call to `rev-parse --show-toplevel` if
needed, or resolve entries relative to `project_root` when `ls-files` is invoked
with `cwd=project_root` and the returned paths already begin with `core/`. Add a
tiny helper and cover it in the integration test (Step 6) which runs against a
real repo where `project_root == repo_root` and (optionally) a nested case.

> Keep `build_linkmap` git-free and pure. All git I/O lives in
> `run_docs_linkmap`.

---

## Step 2 — New module `src/docex/docs/linkmap.py`

### Dataclasses

```python
@dataclass(frozen=True)
class Node:
    fpath: str            # project-relative POSIX; the node key
    type: str             # "design" | "source" | "neither"
    is_standard: bool
    level: str | None     # "L1"|"L2"|"L3"|"C"|None
    codebase: str         # "<cb>" | "none"
    module: str           # "<module>" | "none"
    tokens: int | None    # None for "neither"

@dataclass(frozen=True)
class Edge:
    a: str                # min(fpath1, fpath2) lexicographically
    b: str                # max(...)
    link_type: str        # "markdown" | "mermaid_click" | "emergent"
    direction: str        # "a_to_b" | "b_to_a" | "both"
```

### Constants / helpers

- Reuse the regexes and `_SCHEME` guard from `check.py` (import them, or move the
  three regexes here and have `check.py` import from `linkmap.py` — pick one home;
  recommend **linkmap.py owns them** and `check.py` imports, since check is being
  refactored onto the linkmap anyway).
- `_estimate_tokens(text: str) -> int`: `return max(1, round(len(text) / 4))`.
- A link-extraction primitive that returns **tagged** links:
  `_tagged_links_in(path) -> list[tuple[Path, str]]` returning
  `(resolved_abs_target, link_type)` where `link_type ∈ {"markdown","mermaid_click"}`.
  This is `_links_in` split by which regex matched. `check.py`'s `_links_in` can
  become a thin wrapper (`[t for t,_ in _tagged_links_in(path)]`) so its existing
  callers/tests are untouched.

### Classification helpers (pure, path-based)

Given `project_root`, `codebase_names`, and an absolute file path, compute:

- **type** (depth-relative — see below).
- **is_standard**: build the set of standard file rel-paths once via
  `standard_set.resolve(codebase_names)` (these are relative to `plans/`); a file
  is standard iff its `plans/`-relative path equals a resolved **file** entry.
  Source and `neither` nodes: always `False`.
- **level**:
  - source → `"C"`.
  - design under `plans/design/`:
    - `plans/design/<cb>/module/<x>.md` where `<cb>` ∈ codebase_names → `"L3"`.
    - `plans/design/<cb>/…` (not `module/…`) where `<cb>` ∈ codebase_names → `"L2"`.
    - otherwise (directly under `plans/design/`, incl. `adrs/…`) → `"L1"`.
  - `neither` → `None`.
- **codebase**: `<cb>` when the path is `plans/design/<cb>/…` (and `<cb>` ∈
  codebase_names) or `core/<cb>/src/…`; else `"none"`.
- **module**: `<x>` for `plans/design/<cb>/module/<x>.md`; `<module>` for
  `core/<cb>/src/hex/<module>/**`; else `"none"`.
- **fpath**: `os.path.relpath(abs_path, project_root)` as POSIX. (For targets
  outside the project root this yields a `../…` path — correct for `neither`.)

### `build_linkmap` (pure — the testable core)

```python
def build_linkmap(
    project_root: Path,
    codebase_names: list[str],
    depth: str,                      # "design_docs" | "code_level"
    design_files: list[Path],        # absolute; caller enumerates
    source_files: list[Path],        # absolute git-tracked; [] for design_docs
) -> tuple[list[Node], list[Edge]]:
```

Algorithm:

1. **Scanned scope** = `design_files` (both depths) + `source_files`
   (code_level only). Build a set of absolute scanned paths.
2. **`type` is depth-relative:** a scanned design file → `"design"`; a scanned
   source file → `"source"`; **any edge target not in the scanned scope →
   `"neither"`** (recorded as a stub node, no tokens/level, is_standard False).
   - Consequence (record this in a comment, per C.O. ruling): at `design_docs`
     depth a link to a `core/*/src` file is a `neither` stub; at `code_level` a
     git-tracked source file is `source`; a target outside
     `plans/design ∪ core/*/src` (e.g. `doctrine/**`, `README.md`, `../foo`) is
     `neither` at **both** depths; and an **untracked** file under `core/*/src`
     linked from a tracked file is `neither` at `code_level` (it is not in
     `source_files`, so it is an unscanned target → stub). This last case pins the
     git-tracked boundary — assert it in tests (Step 5).
3. **Nodes**: for every scanned file, read text (utf-8, tolerate errors like
   `_links_in`), estimate tokens, classify, make a `Node`. For every out-of-scope
   edge target discovered in step 4, make a `neither` `Node` (dedup by fpath).
4. **Edges**:
   - For each scanned file that is readable (design files, and source files —
     source files can carry markdown/mermaid too, though rare), extract
     `_tagged_links_in`. For each `(target_abs, link_type)`: the edge is between
     the scanning file and the target. Skip if target == self.
   - **Emergent**: for each scanned **source** file matching
     `core/<cb>/src/hex/<module>/**`, if
     `project_root/plans/design/<cb>/module/<module>.md` exists **and is a scanned
     design node**, add an `emergent` edge source→doc.
   - Represent each raw directed link as `(from_fpath, to_fpath, link_type)`.
5. **Direction merge**: group directed links by the unordered pair + link_type.
   For each group with endpoints sorted `a < b`:
   - forward present (a→b) and reverse present (b→a) → `direction="both"`.
   - only a→b → `"a_to_b"`. only b→a → `"b_to_a"`.
   Emit one `Edge` per group.
6. Return `(sorted nodes by fpath, sorted edges by (a,b,link_type))`.

### JSON rendering + command entry

```python
def render_linkmap_json(depth, nodes, edges) -> str:
    doc = {
        "depth": depth,
        "nodes": [asdict(n) for n in nodes],   # already sorted by fpath
        "edges": [asdict(e) for e in edges],   # already sorted
    }
    return json.dumps(doc, indent=2, sort_keys=True)

def run_docs_linkmap(ctx: ProjectContext, depth: str) -> int:
    # diagnostics -> stderr; pure JSON -> stdout; deterministic; emit once.
    from docex.orchestrate._common import codebases
    project_root = ctx.project_root
    cbs = codebases(ctx)
    design_files = <rglob plans/design for files, skipping dot-parts —
                    mirror unreachable_docs' enumeration>
    if depth == "code_level":
        source_files = <git ls_files per cb for core/<cb>/src, resolved to
                        absolute paths under project_root>
    else:
        source_files = []
    nodes, edges = build_linkmap(project_root, cbs, depth, design_files, source_files)
    print(render_linkmap_json(depth, nodes, edges))   # stdout
    return 0
```

- If `plans/design` is absent, mirror `check_docs`' skip posture but for a data
  command: still emit valid JSON (`{"depth":..., "nodes":[], "edges":[]}`) to
  stdout and return 0 — a consumer gets a well-formed empty graph. (Put the
  informational note, if any, on **stderr**, never stdout.)
- Use the `SubprocessGitClient` for `ls_files` (import locally like the other
  `_cmd_*` handlers do). Resolve `ls-files` output to absolute paths and keep only
  those under `project_root/core/<cb>/src` (see Step 1b resolution note).

---

## Step 3 — Refactor reachability in `src/docex/docs/check.py`

Rewrite `unreachable_docs()` to consume the `design_docs` linkmap. **The returned
problem strings must stay byte-for-byte identical** so all existing tests and the
`docex check` gate stay green.

```python
def unreachable_docs(project_root, codebase_names) -> list[str]:
    base = _design_root(project_root)
    if not base.is_dir():
        return []
    design_files = [<same enumeration as today>]
    nodes, edges = build_linkmap(project_root, codebase_names,
                                 "design_docs", design_files, [])
    # roots: existing _ROOT_NAMES at base + per-cb module_diagram.mmd, as fpaths
    # BFS over directed adjacency derived from edges:
    #   edge a,b: a->b if direction in {a_to_b, both}; b->a if in {b_to_a, both}
    #   follow only to nodes whose type == "design"
    # orphans = design-type nodes not reached, sorted by fpath
    return [f"unreachable doc: plans/design/{rel} (not linked from any standard "
            f"doc or diagram)" for rel in sorted(orphan_rels)]
```

Notes:
- The orphan message uses the path **relative to `plans/design`** (today's format
  is `p.relative_to(base)`), while linkmap fpaths are relative to `project_root`
  (`plans/design/...`). Strip the `plans/design/` prefix when formatting so the
  string matches exactly.
- Keep `_links_in` present (thin wrapper over `_tagged_links_in`) so nothing else
  breaks.
- `missing_standard_files`, `check_docs`, `adr_index_drift`, `run_docs_check`
  unchanged.

---

## Step 4 — Export + wire the CLI

### 4a. `src/docex/docs/__init__.py`

Export `build_linkmap`, `render_linkmap_json`, `run_docs_linkmap`, `Node`, `Edge`
(add to imports and `__all__`).

### 4b. `src/docex/__main__.py` — `_cmd_docs`

- Add a `linkmap` subparser with a required positional `depth` constrained to
  `choices=["design_docs", "code_level"]`.
- Update the `_cmd_docs` docstring to include `linkmap`.
- Dispatch: `if ns.op == "linkmap": return run_docs_linkmap(ctx, ns.depth)`.
- The `_DESCRIPTIONS["docs"]` one-liner (near line 49) may stay, or be lightly
  updated to mention the graph — optional, keep terse.

---

## Step 5 — Unit tests

### `tests/unit/test_docs_linkmap.py` (new)

Use `tmp_path` + `scaffold_design(tmp_path, ["api"])` as a base where useful.
Cover:

1. **Node metadata** across representative paths (build files under `tmp_path`):
   - L1: `plans/design/boundary_conditions.md` → type design, is_standard True,
     level L1, codebase none, module none, tokens int.
   - L2: `plans/design/api/module_diagram.mmd` → L2, is_standard True, codebase
     api, module none.
   - L2 specifics: `plans/design/api/specifics/foo.md` → L2, is_standard False.
   - L3: `plans/design/api/module/orders.md` → L3, is_standard False (name
     varies), codebase api, module orders.
   - ADR: `plans/design/adrs/0001_x/...` under design root → L1. (An ADR index at
     root `adr_index.md` → L1, is_standard True.)
2. **Edges**:
   - markdown link A→B produces `link_type="markdown"`.
   - mermaid `click` in a `.mmd` produces `mermaid_click`.
   - **emergent**: a source file `core/api/src/hex/orders/service.py` +
     existing `plans/design/api/module/orders.md` → an `emergent` edge (test at
     `code_level` with an injected `source_files`).
3. **Direction merge**: A links B and B links A (same link_type) → single edge,
   `direction="both"`. Only-B→A (with A<B) → `"b_to_a"`. Only-A→B → `"a_to_b"`.
4. **`neither` nodes**:
   - design doc linking to `../../doctrine/foo.md` (outside project) → `neither`
     node, tokens None, level None, is_standard False.
   - **depth-relative**: at `design_docs`, a design doc linking to
     `core/api/src/foo.py` → target node type `neither`; the same setup at
     `code_level` with that file in `source_files` → type `source`.
   - **git-tracked boundary (C.O.-requested):** at `code_level`, a tracked design
     doc (or tracked source file) linking to a `core/api/src/generated.py` that is
     **not** in the passed `source_files` list → target node type `neither`. One
     assertion pinning that unscanned-source-under-core = `neither`.
5. **Determinism**: `render_linkmap_json` output equals itself across two builds;
   nodes sorted by fpath, edges by (a,b,link_type); valid JSON round-trips.
6. **tokens heuristic**: a file of known length N → tokens == max(1, round(N/4)).

### `tests/unit/test_docs_check.py` (extend)

- Keep all existing tests unchanged (they are the regression guard for the
  refactor).
- Add one test asserting the exact orphan message string format is preserved
  (e.g. compare to `"unreachable doc: plans/design/orphan.md (not linked from any "
  "standard doc or diagram)"`).

### `tests/unit/test_docs_dispatcher.py` (extend)

- `docex docs linkmap design_docs` dispatches and returns 0 (monkeypatch/scaffold
  a tmp project cwd as the other dispatcher tests do).
- An invalid `depth` (e.g. `linkmap bogus`) exits nonzero (argparse `choices`).
- `linkmap` with no depth exits nonzero.

---

## Step 6 — Integration test

### `tests/integration/test_docs_linkmap_real.py` (new, `@pytest.mark.integration`)

Against a **real temp git repo** (init, add, commit a tiny tree):

- Create `core/api/src/hex/orders/service.py` (tracked) and
  `core/api/src/generated.pyc` (present but **not** added / gitignored).
- Create `plans/design/api/module/orders.md` and the standard scaffold.
- Run the `code_level` enumeration path (call `run_docs_linkmap` capturing stdout,
  or the git-resolution helper + `build_linkmap`).
- Assert: `service.py` appears as a `source` node; `generated.pyc` does **not**
  appear as a `source` node (it may only appear as a `neither` stub *if* something
  links to it — otherwise absent entirely); the emergent edge
  `service.py → plans/design/api/module/orders.md` is present.

Follow existing integration-test conventions in `tests/integration/` for repo
setup (see `test_stagetest_real.py` etc. for the marker + temp-dir pattern). Do
**not** run `-m integration` concurrently with the default suite.

---

## Step 7 — Documentation (artifact alignment)

> Per the mod process, do NOT update core planning design docs here beyond the
> masterplan artifact-alignment row (the six-artifact rule requires masterplan +
> docex.md). The driving corporal handles any further core-doc updates in the
> mod's documentation step.

1. **`doctrine/infrastructure/docex.md § docs`** (pre-authorized doctrine edit,
   scoped to the `docs` section): add `linkmap` to the command list and a short
   subsection documenting: the two depths, that output is deterministic JSON on
   stdout (diagnostics on stderr), and the node/edge field shape (a compact
   version of overview.md's tables). Add `./bin/docex docs linkmap <depth>` to the
   usage lines at the top of § docs.
2. **`docex/plans/core/masterplan.md`**: update the `docs <...>` command row
   (~line 111) to include `linkmap` and note that reachability now consumes the
   linkmap (one graph source of truth).

Do **not** touch `tables/roles/*.yml` or `doctrine_excerpts/` (no new
infrastructural resource — linkmap is a docs verb).

---

## Step 8 — Verify

From `docex/`, iterate with scoped runs, e.g.:

```sh
python -m pytest tests/unit/test_docs_linkmap.py tests/unit/test_docs_check.py \
    tests/unit/test_docs_dispatcher.py -q
python -m pytest tests -m integration -q     # includes the new integration test
```

Confirm the `test_collection_partition` guard still passes (it runs as part of
`tests`). Leave the **full** suite run to the driving corporal at mod close.

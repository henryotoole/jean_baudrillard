# Mod 167 — Implementation Steps

Implements three consumer verbs on top of Mod 165's link graph
(`src/docex/docs/linkmap.py`) plus a finalize pass on the
`doc-refine-orchestration` skill. Read `overview.md` in this folder first for the
design rationale; this file is the executable step list.

**Project root:** `/home/ubuntu/.claude/jean_baudrillard/docex/` (the docex
codebase). All paths below are relative to it unless absolute. Branch is
`011_archdoc_skills` — do NOT create branches or commit; the mod owner handles git.
Leave the `../engineer/` files alone.

**Before you start**, read these for context (do not modify unless a step says so):
- `src/docex/docs/linkmap.py` — the graph builder you consume. Key exports:
  `Node`, `Edge`, `build_linkmap(project_root, codebase_names, depth,
  design_files, source_files)`, `_enumerate_design_files(project_root)`,
  `_resolve_tracked_source(git, project_root, codebase_names)`, `render_linkmap_json`.
- `src/docex/docs/check.py` — see how `unreachable_docs` derives directed
  adjacency from merged edges (you reuse that pattern for "outgoing links").
- `src/docex/docs/__init__.py` — the docs package exports.
- `src/docex/__main__.py` `_cmd_docs` (~line 969) — the `docs` subcommand
  dispatcher you extend.
- `src/docex/git/client.py` + `src/docex/git/subprocess_client.py` — the git
  abstraction you extend with `diff_names`.
- `tests/conftest.py` `FakeGitClient` (~line 366) + `tests/unit/test_docs_linkmap.py`
  + `tests/unit/test_docs_dispatcher.py` — test patterns to mirror.
- `src/docex/orchestrate/_common.py::codebases(ctx)` and
  `src/docex/context.py` — how a `ProjectContext` yields `project_root` + codebase
  list.

Node dataclass fields (frozen): `fpath` (str, project-relative POSIX, the key),
`type` (`"design"|"source"|"neither"`), `is_standard` (bool), `level`
(`"L1"|"L2"|"L3"|"C"|None`), `codebase` (str), `module` (str), `tokens` (int|None).
Edge fields (frozen): `a`, `b` (fpaths, `a<b` lexicographically), `link_type`
(`"markdown"|"mermaid_click"|"emergent"`), `direction` (`"a_to_b"|"b_to_a"|"both"`).

---

## Step 1 — Git: add `diff_names`

### 1a. `src/docex/git/client.py`
Add a method to the `GitClient` Protocol (place it near `ls_files`, ~line 135):

```python
def diff_names(
    self, cwd: Path, ref: str, pathspecs: list[str]
) -> list[str]:
    """Return the tracked paths that differ between ``ref`` and the working
    tree, restricted to ``pathspecs`` (cwd-relative, POSIX), sorted.

    Thin wrapper over ``git diff --name-only <ref> -- <pathspecs...>``:
    compares ``ref`` against the current working tree (so uncommitted edits
    to tracked files are included; brand-new untracked files are not).
    Passing git's empty-tree object as ``ref`` lists every tracked file under
    ``pathspecs``. Empty list if nothing differs or on failure.
    """
    ...
```

### 1b. `src/docex/git/subprocess_client.py`
Implement it on `SubprocessGitClient` (near `ls_files`, ~line 108), using the
existing `self._capture` helper:

```python
def diff_names(self, cwd: Path, ref: str, pathspecs: list[str]) -> list[str]:
    res = self._capture(
        ["diff", "--name-only", ref, "--", *pathspecs], cwd=cwd
    )
    if res is None:
        return []
    return sorted(line.strip() for line in res.splitlines() if line.strip())
```

### 1c. `tests/conftest.py`
On `FakeGitClient` add a scripted map + method (mirror `ls_files_map` /
`ls_files`, ~line 400 / ~line 489):

```python
# field, near ls_files_map:
diff_names_map: dict[str, list[str]] = field(default_factory=dict)

# method, near ls_files:
def diff_names(self, cwd, ref, pathspecs):
    self.calls.append(("diff_names", str(cwd), ref, tuple(pathspecs)))
    return sorted(self.diff_names_map.get(ref, []))
```

(The fake keys purely on `ref` — pathspec filtering is asserted at the pure-filter
layer, not the fake.)

---

## Step 2 — `linkmap.py`: shared `load_code_level_graph` helper

Add to `src/docex/docs/linkmap.py` (after `run_docs_linkmap`, keep imports local as
the module already does):

```python
def load_code_level_graph(
    project_root: Path,
    codebase_names: list[str],
    git: object | None = None,
) -> tuple[list[Node], list[Edge]]:
    """Build the ``code_level`` graph for a project from an explicit root.

    Reuses ``_enumerate_design_files`` + ``_resolve_tracked_source`` +
    ``build_linkmap``. Takes an explicit ``project_root`` + ``codebase_names``
    (NOT a ``ProjectContext``) so it can be driven against a tree that has no
    ``project.yml`` — e.g. docex's own corpus in Mod 168's calibration. ``git``
    defaults to ``SubprocessGitClient()``.
    """
    from docex.git import SubprocessGitClient

    project_root = Path(project_root)
    if git is None:
        git = SubprocessGitClient()
    design_files = _enumerate_design_files(project_root)
    source_files = _resolve_tracked_source(git, project_root, codebase_names)
    return build_linkmap(
        project_root, codebase_names, "code_level", design_files, source_files
    )
```

Export `load_code_level_graph` from `src/docex/docs/__init__.py` (add to both the
`from docex.docs.linkmap import (...)` block and `__all__`).

**Do NOT change `run_docs_linkmap` behavior.** (Optionally it may call this helper
for the `code_level` branch, but only if byte-identical output is preserved and
`test_docs_linkmap.py` stays green. If unsure, leave `run_docs_linkmap` as-is.)

---

## Step 3 — `overhead.py` (new)

Create `src/docex/docs/overhead.py`.

### Pure core

```python
def outgoing_design_targets(
    nodes, edges, subject_fpath
) -> set[str]:
    """fpaths of design nodes the subject links to via an OUTGOING edge of
    ANY link_type (markdown, mermaid_click, OR emergent).

    An edge contributes subject→other when (subject==a and direction in
    {a_to_b, both}) or (subject==b and direction in {b_to_a, both}). Only
    targets whose node type == "design" are returned. Folding in the emergent
    link_type is deliberate: it is what makes a source file's module doc part
    of its overhead (overview § overhead, rule-2 interpretation).
    """
```

```python
def compute_overhead(nodes, edges, subject_fpath) -> list[Node]:
    """The subject's structural overhead per the three rules. Pure.

    Returns Node objects (design nodes only), ordered high→low abstraction
    (L1<L2<L3 rank) then fpath. Excludes the subject itself.

    Rule 1: every design node whose is_standard L1-root membership holds — i.e.
      the standard L1 root files that exist as design nodes: boundary_conditions.md,
      concepts_and_decisions.md, structures_and_views.md, and the standard
      diagrams (project_diagram.mmd, service_diagram.mmd, each codebase's
      module_diagram.mmd). Resolve these via standard_set (see below), keep those
      present as design nodes.
    Rule 2: outgoing_design_targets(subject) — design docs the subject directly
      links to (incl. the emergent module-doc edge for a source subject).
    Rule 3: if the subject is a source node WITH a module doc (its emergent
      target, i.e. a design node at plans/design/<cb>/module/<module>.md that is
      among rule-2 targets), add outgoing_design_targets(module_doc).
    """
```

Implementation notes:
- Build a `by_fpath = {n.fpath: n for n in nodes}` map.
- **Rule 1 roots:** reuse the canonical set. Import
  `from docex.docs.standard_set import resolve`; the L1 roots are the standard
  **file** entries whose `rel_path` (plans-relative) sits directly under `design/`
  and is one of the arc42 L1 files or a standard diagram. Simplest robust approach:
  reuse `check._ROOT_NAMES` for the design-root filenames PLUS each codebase's
  `module_diagram.mmd`, mapped to `plans/design/<name>` fpaths, and keep those that
  exist in `by_fpath` with `type=="design"`. (Import `_ROOT_NAMES` from
  `docex.docs.check`, or re-declare the tuple locally with a comment pointing at
  check.py — prefer import to avoid drift. Note `_ROOT_NAMES` includes `lexicon.md`,
  `adr_index.md`, `adr_active.md`; per the design, rule 1 is "L1 root docs +
  standard diagrams". Including lexicon + ADR indices as overhead is harmless and
  consistent with "always-loadable roots"; include them.) Also add each codebase's
  `plans/design/<cb>/module_diagram.mmd` when present as a design node.
- **Module doc for a source subject:** its emergent target. Find it as the rule-2
  target that is a design node at `plans/design/<cb>/module/<something>.md`. Since
  `build_linkmap` only emits the emergent edge when the module doc exists as a
  scanned design node, it will already be in `outgoing_design_targets` for a source
  subject. Detect it by node metadata: a design node with `level=="L3"` whose
  `codebase`/`module` match the subject's. Use that node's fpath for rule 3.
- **Ordering:** rank `{"L1":0, "L2":1, "L3":2}` then `fpath`. (All overhead is
  design → no `C`/`None`.)
- Dedup by fpath across the three rules (a set of fpaths → resolve to nodes → sort).

### Command wrapper + render

```python
def render_overhead_json(subject_fpath, overhead_nodes) -> str:
    # {"subject": subject_fpath, "overhead": [ {fpath, level, codebase,
    #   module, is_standard, tokens}, ... ]}  (order preserved from the list)
    # json.dumps(..., indent=2, sort_keys=True) — BUT order is carried by the
    # list, which sort_keys does not reorder (it only sorts object keys). The
    # overhead list stays in high→low order.

def run_docs_overhead(ctx, file: str) -> int:
    # Resolve project_root + codebases from ctx.
    # Build code_level graph via load_code_level_graph(project_root, cbs).
    # Normalize `file` to a project-relative POSIX fpath (accept either a path
    #   relative to project_root or an already-relative fpath; resolve against
    #   project_root, then os.path.relpath back — mirror linkmap._fpath).
    # If the normalized fpath is not a design/source node → stderr error
    #   ("docex docs overhead: <file> is not an in-scope design/source file")
    #   and return 1.
    # Else compute_overhead, print render_overhead_json to stdout, return 0.
```

Diagnostics (the not-a-node error) go to **stderr** (`file=sys.stderr`); the JSON is
the sole stdout content.

---

## Step 4 — `changed.py` (new)

Create `src/docex/docs/changed.py`.

### Pure filter

```python
# The empty-tree object id — "changed since here" == "all tracked".
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

def in_scope(path: str, codebase_names: list[str]) -> bool:
    """True iff a project-relative POSIX path is under the location allowlist:
    plans/design/** OR core/<cb>/src/** for a known codebase."""
    if path.startswith("plans/design/"):
        return True
    parts = path.split("/")
    return (
        len(parts) >= 4
        and parts[0] == "core"
        and parts[1] in codebase_names
        and parts[2] == "src"
    )

def filter_changed(paths, codebase_names, project_root) -> list[str]:
    """Keep in-scope paths that still EXIST on disk (drop deletions), sorted &
    deduped. `project_root` is used only for the existence check."""
```

### Command wrapper

```python
def run_docs_changed(ctx, git_ref: str) -> int:
    # project_root + cbs from ctx.
    # pathspecs = ["plans/design"] + [f"core/{cb}/src" for cb in cbs]
    # from docex.git import SubprocessGitClient
    # raw = SubprocessGitClient().diff_names(project_root, git_ref, pathspecs)
    #   (diff_names returns [] on git failure — but we cannot distinguish "no
    #    changes" from "bad ref" that way. To honor "nonzero exit on failure",
    #    first validate the ref with git.rev_parse(project_root, git_ref): if it
    #    returns "" AND git_ref != EMPTY_TREE, print an "unresolvable git ref"
    #    error to stderr and return 1. The empty-tree id resolves fine via
    #    rev_parse in a normal repo, but guard it explicitly so an empty repo
    #    still treats it as "all".)
    # names = filter_changed(raw, cbs, project_root)
    # print each on its own line to stdout (sorted). return 0.
```

Output is a **plain newline-delimited sorted list** of fpaths to stdout (nothing
else). An empty result prints nothing and returns 0.

---

## Step 5 — `cxt_groups.py` (new)

Create `src/docex/docs/cxt_groups.py`. Depends on `compute_overhead` /
`outgoing_design_targets` from `overhead.py` (import them).

### Group dataclass + pure builder

```python
@dataclass(frozen=True)
class ContextGroup:
    overhead: tuple[str, ...]   # fpaths, high→low abstraction then fpath
    subjects: tuple[str, ...]   # fpaths, sorted
    estimated_tokens: int

def build_context_groups(
    nodes, edges, subject_fpaths, tokens_max
) -> tuple[list[ContextGroup], list[str]]:
    """Overlap-greedy bin-packing under tokens_max. Pure.

    Returns (groups, oversize) where `oversize` is the list of subject fpaths
    whose own (self + overhead) cost alone exceeds tokens_max (each becomes its
    own singleton group; the caller warns on stderr).

    Algorithm (deterministic):
      - by_fpath = {n.fpath: n}. tokens(fp) = by_fpath[fp].tokens or 0.
      - For each subject s in subject_fpaths: ov[s] = frozenset of
        compute_overhead(nodes, edges, s) fpaths.
      - cost(subjects_set) = sum of tokens over the UNIQUE union
        (subjects_set ∪ ⋃ ov[s]) — count a file once even if it is both a
        subject and another subject's overhead.
      - unplaced = sorted(subject_fpaths). groups = [].
      - while unplaced:
          seed = unplaced[0]; remove it; group = [seed]; ovu = set(ov[seed]).
          if cost({seed}) > tokens_max:  # oversize singleton
              record seed in oversize; emit group([seed]); continue.
          loop:
              # candidates that still fit, best overhead overlap first
              best = None
              for c in unplaced (in fpath order):
                  if cost(set(group) | {c}) > tokens_max: continue
                  overlap = len(ov[c] & ovu)
                  added = cost(set(group) | {c}) - cost(set(group))
                  key = (-overlap, added, c)
                  track min key → best
              if best is None: break
              move best from unplaced into group; ovu |= ov[best].
          emit group.
      - For an emitted group: overhead fpaths = (⋃ ov[s]) MINUS the group's own
        subject fpaths (a subject already in context is not listed as overhead);
        order high→low abstraction (L1<L2<L3 rank via by_fpath[fp].level) then
        fpath. subjects sorted by fpath. estimated_tokens = cost(group subjects).
      - groups sorted by their subjects tuple.
    """
```

Notes:
- `compute_overhead` returns Node objects; take `.fpath` for the sets. Cache
  `ov[s]` once per subject (don't recompute inside the cost loop).
- Level rank helper: `{"L1":0,"L2":1,"L3":2}.get(level, 3)`.
- A subject with an empty overhead and `tokens <= tokens_max` still forms/joins a
  group normally.

### Command wrapper + render

```python
def render_cxt_groups_json(tokens_max, selection, groups) -> str:
    # {"tokens_max": int, "selection": "all"|<ref>,
    #  "groups": [ {"index": i, "estimated_tokens": int,
    #    "overhead": [ {fpath, level, tokens}, ... ],
    #    "subjects": [ {fpath, level, tokens}, ... ] }, ... ] }
    # index is the group's position in the sorted list.
    # overhead/subjects entries carry node metadata (look up via by_fpath).

def run_docs_cxt_groups(ctx, tokens_max: int, selection: str) -> int:
    # Validate tokens_max > 0 (argparse type=int already; also guard here →
    #   stderr + return 1 if <= 0).
    # project_root + cbs from ctx. graph = load_code_level_graph(...).
    # if selection == "all":
    #     subjects = [n.fpath for n in nodes if n.type in ("design","source")]
    # else:  # a git ref
    #     validate ref (rev_parse; see changed.py guard) → stderr+1 on bad ref.
    #     changed = run changed-logic (reuse changed.filter_changed + diff_names)
    #     node_fpaths = {n.fpath for n in nodes if n.type in ("design","source")}
    #     subjects = sorted(set(changed) & node_fpaths)
    # groups, oversize = build_context_groups(nodes, edges, subjects, tokens_max)
    # for fp in oversize: print(f"docex docs cxt_groups: {fp} (... tokens) exceeds
    #     tokens_max={tokens_max}; emitted as its own group.", file=sys.stderr)
    # print(render_cxt_groups_json(tokens_max, selection, groups))  # stdout
    # return 0
```

**Reuse, don't duplicate, the changed-selection logic:** factor the "ref → in-scope
changed fpaths" into a helper in `changed.py` (e.g. `changed_fpaths(project_root,
codebase_names, git_ref, git=None) -> list[str]`) that both `run_docs_changed` and
`run_docs_cxt_groups` call. Keep the bad-ref guard in that helper (raise or return a
sentinel the callers turn into stderr+exit-1). Simplest: have the helper raise a
`ValueError` on unresolvable ref; both wrappers catch it → stderr + return 1.

Failures → nonzero exit: bad/unresolvable ref, `tokens_max <= 0`. An oversize
subject is NOT a failure (exit stays 0).

---

## Step 6 — `docs/__init__.py` exports

Add the new public names to `src/docex/docs/__init__.py` (import block + `__all__`):
`run_docs_overhead`, `compute_overhead`, `outgoing_design_targets`,
`run_docs_changed`, `changed_fpaths`, `in_scope`, `filter_changed`,
`run_docs_cxt_groups`, `build_context_groups`, `ContextGroup`,
`load_code_level_graph`.

---

## Step 7 — `__main__.py` dispatcher

In `src/docex/__main__.py` `_cmd_docs` (~line 969):

- Update the docstring + the `docs` help line at ~line 50 ("scaffold/check/adr/
  linkmap") to include `overhead/changed/cxt_groups`.
- Add three subparsers:

```python
p_overhead = sub.add_parser(
    "overhead",
    help="list a subject file's structurally-inferred overhead docs (JSON)",
)
p_overhead.add_argument("file", help="project-relative path to a design or source file")

p_changed = sub.add_parser(
    "changed",
    help="list in-scope files changed since <git_ref> (plain list)",
)
p_changed.add_argument("git_ref", help="git ref; the empty-tree id means 'all'")

p_cxt = sub.add_parser(
    "cxt_groups",
    help="group changed/all subject files into context groups under a token budget (JSON)",
)
p_cxt.add_argument("tokens_max", type=int, help="max total in-context tokens per group")
p_cxt.add_argument("selection", help="a git ref, or the literal 'all'")
```

- In the imports and dispatch tail, add:

```python
from docex.docs import (
    run_docs_adr, run_docs_changed, run_docs_check, run_docs_cxt_groups,
    run_docs_linkmap, run_docs_overhead, run_docs_scaffold,
)
...
if ns.op == "overhead":
    return run_docs_overhead(ctx, ns.file)
if ns.op == "changed":
    return run_docs_changed(ctx, ns.git_ref)
if ns.op == "cxt_groups":
    return run_docs_cxt_groups(ctx, ns.tokens_max, ns.selection)
```

---

## Step 8 — Tests

Run from `docex/`. Unit: `python -m pytest tests`. Integration:
`python -m pytest tests -m integration`. Keep them as **separate** invocations
(there is a collection-partition guard). Iterate with a scoped subset while
developing (e.g. `python -m pytest tests/unit/test_docs_overhead.py`), then run the
full unit suite and the integration suite before finishing.

### 8a. `tests/unit/test_docs_overhead.py` (new)
Use `tmp_path` + `scaffold_design` + the `_write` helper pattern from
`test_docs_linkmap.py`. Build the graph with `build_linkmap(..., "code_level", ...)`
(inject file lists directly — pure, no git). Cover:
- Rule 1: L1 roots (boundary_conditions/concepts_and_decisions/structures_and_views
  + diagrams) always appear in overhead for any subject.
- Rule 2 markdown: a design doc linking `[x](./specifics/foo.md)` → foo.md is
  overhead.
- Rule 2 mermaid: a diagram subject with a `click` to a doc → that doc is overhead.
- Source subject + module doc (emergent): overhead includes the module doc (rule-2
  fold-in) AND the docs the module doc links to (rule 3).
- Exclusions: a link to a source file or an out-of-project (`neither`) target is
  NOT in overhead (design docs only).
- Ordering: returned nodes are high→low abstraction (all L1 before any L2 before
  any L3), ties by fpath.
- `run_docs_overhead` on a non-node path → returns 1 (capture with `capsys`,
  assert stderr mentions the file). Build a real `sample_ctx`-style ctx? Simpler:
  test the pure `compute_overhead` for behavior, and test the not-a-node error via
  a tiny ctx built from a `tmp_path` project. If wiring a ctx is heavy, assert the
  error path by calling `run_docs_overhead` with a `sample_ctx` fixture and a
  bogus file — but `sample_ctx` has no plans/design; acceptable, the bogus-file
  branch still returns 1. Prefer testing `compute_overhead` purely + one dispatcher
  arg-validation test in 8d.

### 8b. `tests/unit/test_docs_changed.py` (new)
- `in_scope`: keeps `plans/design/x.md` and `core/api/src/hex/o/s.py`; drops
  `core/api/tests/...`, `infra/...`, `README.md`, `core/api/src` for an unknown cb.
- `filter_changed`: drops a path that doesn't exist on disk (deletion); sorts &
  dedups.
- `changed_fpaths` with a `FakeGitClient` (inject via the helper's `git=` param):
  `diff_names_map[ref]` returns a mix of in-scope + out-of-scope + one deleted →
  result is the sorted in-scope existing set. Empty-tree ref returns all (script
  `diff_names_map[EMPTY_TREE]`).
- Bad ref: `FakeGitClient` whose `rev_parse` returns "" for the ref (script
  `rev_parse_map` — note the fake's `rev_parse` falls back to `head`; to model an
  unresolvable ref, set `rev_parse_map={ref: ""}`) and `ref != EMPTY_TREE` →
  `changed_fpaths` raises `ValueError` (or `run_docs_changed` returns 1).

### 8c. `tests/unit/test_docs_cxt_groups.py` (new)
Build small graphs with controlled `tokens` (write files of known length; recall
`tokens == max(1, round(len(text)/4))`). Cover:
- Full cover + no repeated subject: every selected subject appears in exactly one
  group's `subjects`.
- Budget: every group's `estimated_tokens <= tokens_max` (except recorded oversize
  singletons).
- Overlap clustering: two subjects sharing a module doc land in the same group when
  the budget allows; raising overlap keeps them together.
- Oversize: a single subject whose self+overhead > tokens_max → its own group AND
  appears in the returned `oversize` list; `run_docs_cxt_groups` returns 0 and
  emits a stderr warning (assert with `capsys`).
- Determinism: same inputs → identical `render_cxt_groups_json` output; group order
  stable.
- `tokens_max <= 0` → `run_docs_cxt_groups` returns 1.
- Selection `all` vs a ref (ref path via FakeGit `diff_names_map`).

### 8d. `tests/unit/test_docs_dispatcher.py` (extend)
Add cases mirroring the existing `linkmap` dispatcher tests: `overhead <file>`,
`changed <ref>`, `cxt_groups <int> <sel>` parse and route; `cxt_groups` rejects a
non-int `tokens_max` (argparse SystemExit); missing positional args error.

### 8e. `tests/integration/test_docs_changed_real.py` (new, `@pytest.mark.integration`)
Mirror `test_docs_linkmap_real.py`'s temp-repo setup. Commit an initial tree, note
the ref (`HEAD`), then modify a `plans/design/*.md` and an out-of-allowlist file and
(optionally) commit. Assert `SubprocessGitClient().diff_names(repo, <ref>,
["plans/design", "core/api/src"])` includes the design change and excludes the
out-of-allowlist change. Assert the empty-tree ref lists all tracked in-scope files.

---

## Step 9 — Six-artifact alignment (docs)

### 9a. `doctrine/infrastructure/docex.md § docs`
File: `/home/ubuntu/.claude/jean_baudrillard/doctrine/infrastructure/docex.md`.
In the `### docs` section (~line 169): add the three verbs to the command-signature
list at the top and a bullet each after the `linkmap` bullet (~line 187):
- `overhead <file>` — lists a subject file's structural overhead as JSON
  (`{subject, overhead:[…]}`, ordered high→low abstraction); state the three rules
  briefly and that it consumes the linkmap. Note it is a best-guess, not exhaustive.
- `changed <git_ref>` — plain sorted list of in-scope (`plans/design` +
  `core/<cb>/src`, tracked) files changed since the ref (ref vs working tree);
  empty-tree ref = all.
- `cxt_groups <tokens_max> {<git_ref> | all}` — JSON context groups (shared
  overhead high→low, then subjects) that fully cover the selection with no repeated
  subject, each under `tokens_max` (a heuristic; the budget is an estimate, an
  oversize subject forms its own group). Note the skill consumes it.

### 9b. `docex/plans/design/specifics/subcommand_surface.md`
File: `plans/design/specifics/subcommand_surface.md`. In the `docs` table row
(~line 13): change the command cell from `docs <scaffold|check|adr|linkmap>` to
include `|overhead|changed|cxt_groups`, and append to the "Writes / acts on" cell a
sentence covering the three consumer verbs (all read-only stdout emitters consuming
`linkmap`'s graph: `overhead`/`cxt_groups` emit JSON, `changed` a plain list). Keep
it a navigation aid, not a re-spec.

### 9c. Confirm n/a
`tables/roles/*` and `doctrine_excerpts/*` need **no change** (no infrastructural
resource added). State this in your final report; make no edits there.

**Do NOT** edit any core planning-doc state files
(`boundary_conditions.md`/`concepts_and_decisions.md`/`structures_and_views.md`/
module docs) — the mod owner handles design-doc updates in the documentation step.
`subcommand_surface.md` is an explicit contract-alignment target here (it is the
command-table artifact), so editing it is in scope; other design docs are not.

---

## Step 10 — Skill finalize: `doc-refine-orchestration`

File: `/home/ubuntu/.claude/jean_baudrillard/skills/doc-refine-orchestration/SKILL.md`.

1. **Fix the glossary table** (lines ~10–13): it is missing its markdown header
   separator row, and the `docmap` row must go. Result:

```md
| Name | Definition |
| ---- | ---------- |
| subject file | A doc or source code file which we are planning to make load-bearing edits to. |
| overhead | The docs which must be in-context to make good, meaningful edits to a subject file. |
```

   (Drop the `docmap` line entirely.)

2. **Replace the restated overhead rules** (the paragraph + numbered list at lines
   ~21–25, "Now, overhead is tricky … module doc directly links to."). Do NOT
   restate the rules (the restatement had drifted — "L2 or L3" vs the spec's
   "L1/L2/L3"). Replace with a short pointer, e.g.:

```md
Overhead is inferred structurally. We do not restate the rules here — they live in
one place, `docex docs overhead` (see
[`docex.md § docs`](../../doctrine/infrastructure/docex.md#docs)), and
`docex docs cxt_groups` applies them for us. A pointer can't drift from its source;
a restatement did.
```

   Verify the relative link resolves from `skills/doc-refine-orchestration/SKILL.md`
   to `doctrine/infrastructure/docex.md` (i.e. `../../doctrine/infrastructure/docex.md`).

3. **Fill the `TEMPLATE TODO`** (lines ~63–65) with a real subagent prompt template.
   It must: load the group's **overhead files FIRST** (primacy), then the subject
   files, and invoke the `doc-refine` skill. Use placeholders the orchestrator fills
   from `cxt_groups` JSON. Example:

```md
You are refining documentation for one context group. Work strictly in this order.

1. FIRST, read these overhead files into context (highest abstraction first) — do
   NOT edit them; they are reference for editing the subjects:
   {{overhead_files, one per line, high→low abstraction}}

2. Invoke the `doc-refine` skill and follow it to make load-bearing edits to each of
   these subject files, one at a time:
   {{subject_files, one per line}}

   For each subject: read it, pull any additional docs you find you need, then make
   only subtractive / condensing / organizing edits per `doc-refine`.

Do not edit any file outside the subject list except as `doc-refine` directs. Report
which subjects you changed and any overhead file that itself turned out to need work
(flag it; do not edit it — a later group owns it).
```

4. **`executor/design.md`** — already retired (deleted in commit `1a67a8a`; not in
   the tree). Do NOT recreate or delete anything. Confirm no *live* reference
   remains (`grep -rn "executor/design" skills/` should return nothing;
   `advance_plan.md` mentions are plan docs and stay). If a live skill reference
   exists, repoint it to `docex_doc_design.md`; otherwise no action.

Per the advance Non-Goals: **do NOT run** `doc-refine` / `doc-refine-orchestration`
end-to-end — only wire the routing and fix the drift.

---

## Step 11 — Final verification

From `docex/`:
1. `python -m pytest tests` (full unit suite) — all green.
2. `python -m pytest tests -m integration` — all green.
3. Sanity-smoke the CLI against docex itself is NOT possible (no `project.yml`); the
   mod owner smoke-invokes during review. Do not attempt to run the verbs via the
   CLI against docex's own tree.

Report: the exact test counts for both invocations, any deviation you made from
this plan and why, and confirm the `tables/roles` / `doctrine_excerpts` n/a. Do NOT
commit — the mod owner handles all git.

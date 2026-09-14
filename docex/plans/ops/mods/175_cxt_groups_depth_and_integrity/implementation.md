# Mod 175 — Implementation Steps

Docex-internal mod on branch `advance_014_docs_report_and_skill_refactor`. Docex
project root: `~/.claude/jean_baudrillard/docex` (all paths below are relative to
it unless noted). Repo root: `~/.claude/jean_baudrillard`.

**Test discipline (docex-specific):** run `python -m pytest tests` from the docex
root — NOT bare `pytest`, NOT `tests/unit`. During iteration you may narrow with
`python -m pytest tests/unit/test_docs_cxt_groups.py tests/unit/test_docs_dispatcher.py`,
but confirm the FULL `python -m pytest tests` suite is green before finishing.

There is **no manual-test phase** for docex mods.

---

## Step 1 — `linkmap.py`: add `load_design_docs_graph`

In `src/docex/docs/linkmap.py`, next to the existing `load_code_level_graph`
(end of file), add a sibling loader that builds the `design_docs`-depth graph
from the SAME enumeration primitives (no new allowlist):

```python
def load_design_docs_graph(
    project_root: Path,
    codebase_names: list[str],
    git: object | None = None,
) -> tuple[list[Node], list[Edge]]:
    """Build the ``design_docs`` graph for a project from an explicit root.

    Sibling of ``load_code_level_graph``: same ``_enumerate_design_files`` +
    ``build_linkmap`` primitives, but with an EMPTY source enumeration so the
    scope is ``plans/design/**`` only — exactly the ``design_docs`` depth of
    ``docex docs linkmap``. ``git`` is accepted for signature parity but unused
    (no tracked-source walk at this depth).
    """
    project_root = Path(project_root)
    design_files = _enumerate_design_files(project_root)
    return build_linkmap(
        project_root, codebase_names, "design_docs", design_files, []
    )
```

Add `load_design_docs_graph` to any `__all__`/export list if the module or
`docs/__init__.py` maintains one (check `src/docex/docs/__init__.py` — export it
alongside `load_code_level_graph` if that is exported there; if `load_code_level_graph`
is not exported from `__init__.py`, leave both unexported).

## Step 2 — `cxt_groups.py`: import the new loader

At the top of `src/docex/docs/cxt_groups.py`, extend the linkmap import:

```python
from docex.docs.linkmap import load_code_level_graph, load_design_docs_graph
```

## Step 3 — `cxt_groups.py`: add `build_module_integrity_groups`

Add this pure function (place it after `build_context_groups`, before
`_emit_group`, so it can call `_emit_group`). It reuses the same overhead/cost
setup as `build_context_groups`.

```python
def build_module_integrity_groups(
    nodes, edges, subject_fpaths, tokens_max
) -> tuple[list[ContextGroup], list[str]]:
    """Category-integrity packing. Pure.

    Never splits a category (module / codebase / design-docs set) across groups
    unless forced by ``tokens_max``, and then only across groups containing
    nothing but that category's files. See
    ``plans/ops/mods/175_cxt_groups_depth_and_integrity/overview.md`` for the
    rule and its validation against the prep's Module Integrity table.

    Returns ``(groups, oversize)`` with the same contract as
    ``build_context_groups``: an ``oversize`` fpath is a single file whose own
    self+overhead exceeds ``tokens_max`` (emitted as its own singleton group;
    the caller warns on stderr).
    """
    by_fpath = {n.fpath: n for n in nodes}

    def tokens(fp: str) -> int:
        node = by_fpath.get(fp)
        return (node.tokens or 0) if node is not None else 0

    ov: dict[str, frozenset[str]] = {
        s: frozenset(n.fpath for n in compute_overhead(nodes, edges, s))
        for s in subject_fpaths
    }

    def cost(subjects_set) -> int:
        union: set[str] = set(subjects_set)
        for s in subjects_set:
            union |= ov[s]
        return sum(tokens(fp) for fp in union)

    # -- classify subjects into top-level units --------------------------------
    # unit key: ("design",) | ("codebase", <cb>)
    units: dict[tuple, list[str]] = {}
    for fp in subject_fpaths:
        node = by_fpath.get(fp)
        if node is not None and node.type == "design":
            key: tuple = ("design",)
        else:
            cb = node.codebase if node is not None else "none"
            key = ("codebase", cb)
        units.setdefault(key, []).append(fp)

    oversize: list[str] = []
    dedicated: list[list[str]] = []   # pure groups from fragmented units
    whole_atoms: list[list[str]] = []  # whole top-level units that fit

    def leaf_split(files: list[str]) -> list[list[str]]:
        """Split a leaf category's files into pure groups under the budget.

        Only these files ever appear in the returned groups. A single file whose
        own self+overhead exceeds the budget becomes its own group and is
        recorded in ``oversize``.
        """
        out: list[list[str]] = []
        cur: list[str] = []
        for fp in sorted(files):
            if cost([fp]) > tokens_max:
                if cur:
                    out.append(cur)
                    cur = []
                out.append([fp])
                oversize.append(fp)
                continue
            if cur and cost(set(cur) | {fp}) > tokens_max:
                out.append(cur)
                cur = [fp]
            else:
                cur.append(fp)
        if cur:
            out.append(cur)
        return out

    def pack_atoms(atoms: list[list[str]]) -> list[list[str]]:
        """Deterministic first-fit combining of whole atoms under the budget.

        Each atom is kept intact (never split); atoms that fit together share a
        group. Used both for the top-level whole units and for a fragmented
        codebase's module/root children (within that codebase's own groups).
        """
        packed: list[list[str]] = []
        for atom in sorted(atoms, key=lambda a: sorted(a)):
            placed = False
            for g in packed:
                if cost(set(g) | set(atom)) <= tokens_max:
                    g.extend(atom)
                    placed = True
                    break
            if not placed:
                packed.append(list(atom))
        return packed

    for key in sorted(units):
        files = units[key]
        if cost(files) <= tokens_max:
            whole_atoms.append(files)
            continue
        # Unit does not fit whole → fragment.
        if key[0] == "design":
            dedicated.extend(leaf_split(files))
            continue
        # A codebase: subdivide into module children + a codebase-root residual.
        children: dict[str, list[str]] = {}
        for fp in files:
            node = by_fpath.get(fp)
            module = node.module if node is not None else "none"
            children.setdefault(module, []).append(fp)
        if len(children) == 1 and "none" in children:
            # Non-hex / codebase-root only: no module tier to subdivide into →
            # treat as a leaf.
            dedicated.extend(leaf_split(files))
            continue
        child_atoms: list[list[str]] = []
        for _module, cfiles in sorted(children.items()):
            if cost(cfiles) <= tokens_max:
                child_atoms.append(cfiles)
            else:
                dedicated.extend(leaf_split(cfiles))
        dedicated.extend(pack_atoms(child_atoms))

    all_groups = pack_atoms(whole_atoms) + dedicated
    groups = [_emit_group(g, ov, by_fpath, cost) for g in all_groups]
    groups.sort(key=lambda g: g.subjects)
    return groups, oversize
```

Notes for the implementer:
- `_emit_group`, `compute_overhead`, and `ContextGroup` are already in the module
  / imported — reuse them, do not re-define.
- **Do not touch `build_context_groups`** — `--optimize tokens` must stay
  byte-identical.

## Step 4 — `cxt_groups.py`: extend `run_docs_cxt_groups`

Change the signature to accept the two new args with today's defaults, pick the
graph by depth (preserving the `load_code_level_graph` seam so existing tests'
monkeypatch still works), and dispatch the packer by optimize. Update the
docstring to document the new args and their defaults.

Replace the current signature/body around the graph load and packing call:

```python
def run_docs_cxt_groups(
    ctx: ProjectContext,
    tokens_max: int,
    selection: str,
    depth: str = "code_level",
    optimize: str = "tokens",
) -> int:
    """``docex docs cxt_groups <tokens_max> {<git_ref>|all}`` — print groups JSON.

    Args:
        ctx: the loaded project context (yields project root + codebases).
        tokens_max: the per-group in-context token budget (must be > 0).
        selection: the literal ``all`` (every design/source node) or a git ref
            (the ``changed <ref>`` set intersected with the graph's nodes).
        depth: ``code_level`` (default; ``plans/design`` + tracked
            ``core/<cb>/src``) or ``design_docs`` (``plans/design`` only) — the
            tracked scope the subjects are drawn from, mirroring ``docex docs
            linkmap <depth>``.
        optimize: ``tokens`` (default; overlap-greedy bin-packing) or
            ``module_integrity`` (never split a module / codebase / design-docs
            category across groups except into category-pure groups when forced).

    Both defaults reproduce the pre-mod-175 output byte-for-byte.

    Errors:
        ``tokens_max <= 0`` or an unresolvable git ref → diagnostic on stderr
        and exit 1. An oversize subject is NOT a failure (exit stays 0; a
        stderr warning names it).

    Returns:
        0 on success (JSON written to stdout); 1 on a validation/ref failure.
    """
    from docex.docs.changed import changed_fpaths
    from docex.orchestrate._common import codebases

    if tokens_max <= 0:
        print(
            f"docex docs cxt_groups: tokens_max must be positive, got "
            f"{tokens_max}",
            file=sys.stderr,
        )
        return 1

    project_root = ctx.project_root
    cbs = codebases(ctx)
    if depth == "design_docs":
        nodes, edges = load_design_docs_graph(project_root, cbs)
    else:
        nodes, edges = load_code_level_graph(project_root, cbs)
    node_fpaths = {n.fpath for n in nodes if n.type in ("design", "source")}

    if selection == "all":
        subjects = sorted(node_fpaths)
    else:
        try:
            changed = changed_fpaths(project_root, cbs, selection)
        except ValueError as exc:
            print(f"docex docs cxt_groups: {exc}", file=sys.stderr)
            return 1
        subjects = sorted(set(changed) & node_fpaths)

    if optimize == "module_integrity":
        groups, oversize = build_module_integrity_groups(
            nodes, edges, subjects, tokens_max
        )
    else:
        groups, oversize = build_context_groups(
            nodes, edges, subjects, tokens_max
        )

    # (leave the existing oversize-warning loop + render/print unchanged)
```

Keep the existing oversize warning loop and the final
`print(render_cxt_groups_json(...))` exactly as they are. **Do not add `depth`
or `optimize` to the rendered JSON** — that would break byte-identical output.

## Step 5 — `__main__.py`: argparse options + dispatch

In `src/docex/__main__.py`, in `_cmd_docs`, after the two existing positional
`p_cxt` args (`tokens_max`, `selection`), add:

```python
    p_cxt.add_argument(
        "--depth",
        choices=["design_docs", "code_level"],
        default="code_level",
        help="scope subjects are drawn from (default: code_level)",
    )
    p_cxt.add_argument(
        "--optimize",
        choices=["tokens", "module_integrity"],
        default="tokens",
        help="packing objective (default: tokens)",
    )
```

Update the dispatch call:

```python
    if ns.op == "cxt_groups":
        return run_docs_cxt_groups(
            ctx, ns.tokens_max, ns.selection, ns.depth, ns.optimize
        )
```

argparse `choices` gives the invalid-value error on stderr + `SystemExit(2)`
for free (SC 175a.3).

Optionally refresh the `_cmd_docs` docstring's `cxt_groups` clause to mention the
two optional args.

## Step 6 — Tests

### 6a — `tests/unit/test_docs_dispatcher.py`

The existing `test_cmd_docs_cxt_groups_routes` fake takes exactly
`(ctx, tokens_max, selection)`; the dispatcher now passes five args. Update the
fake to accept `depth`/`optimize` and assert the defaults, and add a test that
the flags are threaded through:

```python
def test_cmd_docs_cxt_groups_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    seen = {}

    def fake(ctx, tokens_max, selection, depth, optimize):
        seen.update(
            tokens_max=tokens_max, selection=selection,
            depth=depth, optimize=optimize,
        )
        return 0

    monkeypatch.setattr("docex.docs.run_docs_cxt_groups", fake)
    assert _cmd_docs(["cxt_groups", "40000", "all"]) == 0
    assert seen["tokens_max"] == 40000
    assert seen["selection"] == "all"
    assert seen["depth"] == "code_level"       # default
    assert seen["optimize"] == "tokens"        # default


def test_cmd_docs_cxt_groups_threads_depth_and_optimize(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    seen = {}

    def fake(ctx, tokens_max, selection, depth, optimize):
        seen.update(depth=depth, optimize=optimize)
        return 0

    monkeypatch.setattr("docex.docs.run_docs_cxt_groups", fake)
    assert _cmd_docs([
        "cxt_groups", "40000", "all",
        "--depth", "design_docs", "--optimize", "module_integrity",
    ]) == 0
    assert seen["depth"] == "design_docs"
    assert seen["optimize"] == "module_integrity"


def test_cmd_docs_cxt_groups_rejects_invalid_depth():
    import pytest
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["cxt_groups", "40000", "all", "--depth", "bogus"])
    assert excinfo.value.code == 2


def test_cmd_docs_cxt_groups_rejects_invalid_optimize():
    import pytest
    with pytest.raises(SystemExit) as excinfo:
        _cmd_docs(["cxt_groups", "40000", "all", "--optimize", "bogus"])
    assert excinfo.value.code == 2
```

### 6b — `tests/unit/test_docs_cxt_groups.py`

Add tests. Use the existing `_write` / `_big` helpers.

1. **175a — `design_docs` scope excludes source subjects.** Build a project with a
   design doc AND a hex source file (`core/api/src/hex/m1/f.py`). Call
   `run_docs_cxt_groups(..., depth="design_docs")` (monkeypatch
   `load_design_docs_graph` OR just build via `load_design_docs_graph` against a
   `tmp_path`). Assert every emitted subject fpath starts with `plans/design/`
   and none is a `core/` source path. Also assert the direct
   `load_design_docs_graph(tmp_path, cbs)` produces zero `source`-type nodes.

2. **175a — byte-identical default.** For a fixed `(tokens_max, selection)` graph,
   assert `render_cxt_groups_json` over `build_context_groups(...)` is identical
   whether reached via the default args or explicit `depth="code_level",
   optimize="tokens"`. (Easiest: call `run_docs_cxt_groups` twice capturing
   stdout — once with 3 args, once with the two defaults spelled out — and assert
   equal stdout.)

3. **175b — the prep Module Integrity table.** Encode a validity oracle in the
   test module and assert each of the six rows:

   ```python
   def _mi_valid(groups, nodes):
       """Module-integrity validity oracle (test-side).

       For every top-level unit (design, each codebase) and, recursively, every
       module of a fragmented codebase: a category fragmented across >1 group
       requires each touching group to contain ONLY that category's files.
       """
       by_fpath = {n.fpath: n for n in nodes}
       group_sets = [set(g.subjects) for g in groups]

       def unit_of(fp):
           n = by_fpath[fp]
           return ("design",) if n.type == "design" else ("cb", n.codebase)

       def check(members: set[str], sibling_pred):
           # members: all files of this category across the whole selection.
           touching = [g for g in group_sets if g & members]
           if len(touching) <= 1:
               return True
           # fragmented → every touching group must be pure to `members`
           for g in touching:
               if g - members:
                   return False
           return sibling_pred(touching)

       # design category
       design = {fp for fp in by_fpath if by_fpath[fp].type == "design"}
       design = {fp for g in group_sets for fp in g if fp in design}
       if design and not check(design, lambda ts: True):
           return False
       # codebase categories
       cbs = {by_fpath[fp].codebase for g in group_sets for fp in g
              if by_fpath[fp].type == "source"}
       for cb in cbs:
           members = {fp for g in group_sets for fp in g
                      if by_fpath[fp].type == "source"
                      and by_fpath[fp].codebase == cb}

           def modules_ok(touching, cb=cb):
               mods = {by_fpath[fp].module for fp in members}
               for m in mods:
                   mm = {fp for fp in members if by_fpath[fp].module == m}
                   tt = [g for g in touching if g & mm]
                   if len(tt) > 1 and any(g - mm for g in tt):
                       return False
               return True

           if not check(members, modules_ok):
               return False
       return True
   ```

   Then for each row build the literal `ContextGroup` arrangement (a tiny fixture
   with `core/c1/src/hex/m1/…`, `m2`, `core/c2/src/hex/m3/…`, `m4`, and design
   docs; build nodes via `build_linkmap` at `code_level`) and assert
   `_mi_valid(rows, nodes)` equals the table's Valid column. Construct the
   `ContextGroup`s directly (you only need `.subjects` for the oracle).

4. **175b — the algorithm always emits a valid partition + achieves valid targets.**
   Build the C-1/C-2/design fixture. Run `build_module_integrity_groups` at
   several budgets (huge → everything in one group; medium → whole codebases
   fragment on module lines; tiny → single-file groups). Assert (a) full cover +
   no repeated subject, (b) `_mi_valid(groups, nodes)` is True at every budget,
   (c) at a budget where a whole codebase fits, that codebase's files are NOT
   split (SC 175b.2), (d) a mid budget yields whole-module groups pure to one
   codebase.

5. **175b — oversize still exit 0 + note (SC 175b.5).** A single source/design file
   whose self+overhead exceeds a tiny budget → `build_module_integrity_groups`
   returns it in `oversize` and as its own singleton group; the
   `run_docs_cxt_groups` wrapper prints the stderr note and returns 0. (Mirror
   the existing `test_oversize_subject_singleton_and_exit_0`.)

6. **175b — compose with depth (SC 175b.4).** At `depth="design_docs",
   optimize="module_integrity"`: when the design docs fit, exactly one group whose
   subjects are all the design docs; at a tiny budget, multiple groups each
   containing only design docs.

7. **175b — byte-identical `--optimize tokens`.** For a fixture, assert
   `render_cxt_groups_json(tokens_max, sel, build_context_groups(...))` equals the
   output reached through `run_docs_cxt_groups(..., optimize="tokens")` (default),
   confirming tokens mode is untouched.

Run: `python -m pytest tests/unit/test_docs_cxt_groups.py tests/unit/test_docs_dispatcher.py`
then the full `python -m pytest tests`.

## Step 7 — Doctrine `docex.md` (pre-authorized, SC 175.6)

In `doctrine/infrastructure/docex.md`, update the `docs` section:

- Change the usage line (currently line 176)
  `./bin/docex docs cxt_groups <tokens_max> {<git_ref> | all}` to:
  `./bin/docex docs cxt_groups <tokens_max> {<git_ref> | all} [--depth design_docs|code_level] [--optimize tokens|module_integrity]`
- Extend the `cxt_groups` bullet (currently line 197) to document both new args
  and their defaults. Append, after the existing text, roughly:

  > Two optional args tune grouping. `--depth` mirrors `linkmap <depth>`:
  > `code_level` (default — `plans/design` + tracked `core/<cb>/src`) or
  > `design_docs` (`plans/design` only), sharing linkmap's one scope definition.
  > `--optimize` selects the packing objective: `tokens` (default — the
  > overlap-greedy bin-packing above) or `module_integrity`, which never splits a
  > **category** — a hex module, a codebase, or the design-docs set — across
  > groups, except that a category too big for one group splits only across groups
  > containing nothing but that category (only a codebase subdivides, into its
  > modules). Both defaults reproduce the prior output byte-for-byte.

Do **not** edit any other doctrine file. If another doctrine file appears to need
a change, stop and escalate.

## Step 8 — Docex design docs

- `plans/design/specifics/subcommand_surface.md`: the `docs` row's `cxt_groups`
  clause (in the long `Reads`/`Writes` cell) — note the two optional args
  (`--depth {design_docs|code_level}`, `--optimize {tokens|module_integrity}`)
  and that both defaults are byte-identical to the prior behavior. This table is a
  navigation aid, so keep it to a phrase, not a re-spec.
- `plans/design/structures_and_views.md`: line ~68 lists the docs command family;
  no structural change is required, but if it enumerates cxt_groups args, keep it
  consistent. A one-line mention that `cxt_groups` now takes `--depth`/`--optimize`
  is sufficient if the surrounding prose lists command options; otherwise leave it.

## Step 9 — Confirm & report

- Full `python -m pytest tests` green (record the pass count).
- Confirm byte-identical defaults empirically (Step 6 tests 2 and 7).
- No edits to `tables/roles/*.yml` or `doctrine_excerpts/` (confirm none needed:
  no new resource, no role/engine change).

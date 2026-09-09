# Mod 167 — `docex docs overhead` / `changed` / `cxt_groups` + skill finalize

## Goal

Add the three **consumer verbs** that sit on top of Mod 165's link graph, and
finalize the `doc-refine-orchestration` skill that routes to them. This is Goal 3
of advance 011 (archdoc skills). Design intent:
`plans/advances/011_archdoc_skills/docex_doc_design.md §§ overhead / changed /
cxt_groups`, and `advance_plan.md § Goal 3 / Mod 167`.

All three verbs **consume Mod 165's `linkmap`** (`src/docex/docs/linkmap.py::build_linkmap`)
as the single graph source of truth — none re-walks the tree independently. Each
matches linkmap's output discipline: deterministic data to **stdout**, diagnostics
to **stderr**, deterministic sort, emit-once, **nonzero exit on failure** (the
`describe --format llm` contract).

## The verbs

### `docex docs overhead <file>`

Lists the subject file's **structurally-inferred overhead** — the higher/adjacent
docs that should be in context to make informed edits to it. Best-guess, *not*
exhaustive (design § overhead). `<file>` is a project-relative path to a design
doc or a source file; it must be an in-scope node of the graph (else usage error →
stderr + nonzero exit).

Overhead rules (verbatim from `docex_doc_design.md § overhead`):
1. All **L1 root docs** — `boundary_conditions.md`, `concepts_and_decisions.md`,
   `structures_and_views.md`, and all standard diagrams.
2. Any **L1/L2/L3 doc the subject directly links to**.
3. For a **source file with a corresponding module doc**, any **L1/L2/L3 doc the
   module doc directly links to**.

Computed off the **`code_level`** graph (so source subjects and their emergent
module-doc edges resolve). Overhead is always **design docs only** (L1/L2/L3);
targets that are source or `neither` nodes are never overhead (the rules name only
docs).

**Interpretation call (mine, corporal authority):** a source file's own module doc
*is* part of its overhead. The graph expresses the source→module-doc relationship
as the **`emergent`** edge, so I treat rule 2's "directly links to" as *any
outgoing edge from the subject to a design node, regardless of `link_type`* — which
folds the emergent edge in and makes the module doc appear under rule 2. Rule 3
then extends coverage to the docs that module doc links to. This is the only
reading under which a source file's module doc — the single most relevant doc to
it — is not silently dropped. Recorded here so the behavior is intentional, not
incidental.

Rule 1's roots are resolved from `standard_set` (the same canonical set
`scaffold`/`check` use), filtered to files that exist as design nodes.

**Output — JSON.** Overhead is ordered, token-weighted, structured data, not a flat
path set; a plain list would throw away the abstraction ordering and the per-file
`tokens` that make it useful. JSON also matches the `linkmap` precedent and lets an
agent reason about cost. Shape:

```json
{
  "subject": "core/api/src/hex/orders/service.py",
  "overhead": [
    { "fpath": "plans/design/boundary_conditions.md", "level": "L1",
      "codebase": "none", "module": "none", "is_standard": true, "tokens": 512 },
    ...
  ]
}
```

`overhead` is ordered **high→low abstraction** (L1 → L2 → L3), ties broken by
`fpath`. Each entry is the node's own metadata (so no second lookup is needed).

### `docex docs changed <git_ref>`

Lists **in-scope files changed since `<git_ref>`** — the raw selection helper the
orchestration skill's "what did this mod/advance touch" step needs. Scope is the
**location allowlist**: `plans/design/**` and each codebase's `core/<cb>/src/**`,
**git-tracked** only (matching the linkmap's own tracked-source boundary).

Semantics: `git diff --name-only <ref> -- <allowlist pathspecs>` — **ref vs. the
current working tree**, so a mod's still-uncommitted edits to tracked files are
included (only brand-new *untracked* files are excluded, consistent with linkmap
treating untracked source as out-of-scope). Deleted-since-`ref` paths are dropped
(a file that no longer exists can't be a subject). Results are filtered to the
allowlist, de-duplicated, and sorted.

**Empty-tree ref means "all"** (design § changed): passing git's empty-tree object
(`4b825dc642cb6eb9a060e54bf8d69288fbee4904`) diffs every tracked in-scope file, so
"changed since the beginning of history" == "all in-scope files" falls straight out
of the same code path — no special case.

**Output — plain sorted newline list** of project-relative `fpath`s. `changed` is
genuinely just a *set of paths* with no per-file structure; a plain list is
pipe-composable (`docex docs changed <ref> | …`) and is the honest shape for the
datum. (The two verbs that carry ordering/tokens — `overhead`, `cxt_groups` — emit
JSON; the one flat path-set emits a list. Clean, justifiable split; no `--format`
flag added — out of scope.)

### `docex docs cxt_groups <tokens_max> {<git_ref> | all}`

Partitions the selected subject files into **context groups** — sets of subjects
with highly-overlapping overhead whose *combined* in-context cost (subjects +
shared overhead, using linkmap `tokens`) stays under `<tokens_max>`. The groups
**fully cover** the selection with **no repeated subject**. This is the grouping
engine the `doc-refine-orchestration` skill consumes to spawn one subagent per
group.

Selection:
- **`all`** — every `design`/`source` node in the `code_level` graph is a subject.
- **`<git_ref>`** — the `changed <ref>` set, intersected with the graph's
  `design`/`source` nodes (only nodes have `tokens`/overhead).

**Output — JSON** (the skill machine-reads it → subagents):

```json
{
  "tokens_max": 40000,
  "selection": "all",
  "groups": [
    {
      "index": 0,
      "estimated_tokens": 38210,
      "overhead": [ { "fpath": "...", "level": "L1", "tokens": 512 }, ... ],
      "subjects": [ { "fpath": "...", "level": "L3", "tokens": 1400 }, ... ]
    },
    ...
  ]
}
```

Per group, `overhead` lists the group's **shared overhead ordered high→low
abstraction** (then `fpath`); `subjects` lists the group's subjects (deterministic
`fpath` order). `estimated_tokens` is the group's total unique-file cost.

#### `cxt_groups` algorithm (open design point — resolved, corporal authority)

A **heuristic**: overlap-greedy bin-packing under `tokens_max`. It does **not**
promise optimality (optimal set-cover-under-a-budget is NP-hard and not worth it
for an estimate whose inputs — `tokens`, overhead — are themselves estimates).

1. Build the `code_level` graph once. Compute `overhead(s)` for every subject `s`
   (the same routine `overhead` uses).
2. `cost(group)` = sum of `tokens` over the **unique** files in
   `(subjects ∪ ⋃ overhead(subjects))` — a file that is both a subject and another
   subject's overhead is counted once.
3. Greedy grow-by-best-overlap, fully deterministic:
   - `unplaced` = all subjects, ordered by `fpath`.
   - Seed a new group with the first unplaced subject.
   - Repeatedly, among unplaced candidates **that still fit** (adding them keeps
     `cost ≤ tokens_max`), add the one maximizing overhead overlap with the group's
     current overhead union; tie-break by *smallest added cost*, then `fpath`. When
     no candidate fits, close the group and seed the next.
4. Emit groups sorted by their subjects' sorted `fpath` tuple.

**Clustering:** because subjects sharing a module/codebase share overhead
(L1 roots + the same module/L2 docs), overlap-greedy naturally clumps groups on
**module then codebase lines** — exactly the design's NOTE prediction.

**Oversize subject (self + overhead > `tokens_max`):** it cannot fit any group. It
is placed in its **own singleton group** and a **stderr** diagnostic names it and
its cost. This is a heuristic result, not a command failure — the spec states
`tokens_max` "should not be considered exact" — so **exit stays 0** and coverage /
no-repeat still hold. (Command *failures* — a git error, an unresolvable ref, a
non-positive `tokens_max` — are stderr + nonzero exit.)

## New git capability

`changed` needs "files changed since a ref", which the `GitClient` Protocol does
not yet expose. Add one thin, doc-agnostic method (mirroring the existing `ls_files`
abstraction):

- `GitClient.diff_names(cwd, ref, pathspecs) -> list[str]` — `git diff
  --name-only <ref> -- <pathspecs>`, cwd-relative POSIX paths, sorted; `[]` on
  failure. Implemented in `SubprocessGitClient`; scripted in `conftest.FakeGitClient`
  (a `diff_names_map` keyed by `ref`). Crosses the real git boundary → earns an
  integration test.

## Shared plumbing

To avoid re-deriving the graph in three places, factor a small helper in
`linkmap.py` — `load_code_level_graph(project_root, codebase_names, git=None)
-> (nodes, edges)` — that reuses the existing `_enumerate_design_files` +
`_resolve_tracked_source` + `build_linkmap` (git defaults to
`SubprocessGitClient()`). The `run_docs_*` wrappers resolve `ctx` →
`(project_root, codebases(ctx))` and call it. No behavior change to `linkmap`.

**Mod-168 guard (C.O.):** this helper — and the pure `compute_overhead` /
`build_context_groups` — take an **explicit project root + codebase list**, never a
`ProjectContext` that demands `project.yml` discovery. docex itself has no
`project.yml`, so Mod 168 calibrates by calling `load_code_level_graph(<docex
root>, ["docex"])` and the pure grouping function directly, bypassing CLI project
discovery. The three `run_docs_*` entry points remain the only `ctx`-consuming
layer.

## Skill finalize — `doc-refine-orchestration`

Per advance Goal 3 SC4 (and Non-Goals: **wire routing + fix drift only**; do NOT
exercise doc-refine end-to-end):

1. **Fill the subagent template** (the `TEMPLATE TODO` placeholder). A concrete
   prompt that: names the group's **overhead files to load FIRST** (primacy bias),
   then the **subject files** to work through, and instructs the subagent to invoke
   the **`doc-refine`** skill, reading each subject and pulling any extra needed
   docs itself. Serial, never parallel (already stated in the body).
2. **Route to `cxt_groups`** as the grouping engine — already present
   (`docex docs cxt_groups <tokens_max> {<git_ref> | all}`); confirmed/kept, and the
   template is fed from its JSON.
3. **Drop the duplicated overhead-rule prose** (SKILL.md lines ~21–24) and replace
   with a **pointer** to docex's overhead rules (the `overhead` verb /
   `docex.md § docs`). The restatement had **drifted** — it says "L2 or L3" where
   the spec says **L1/L2/L3** — which is exactly why a pointer replaces it (a
   pointer can't drift). The skill no longer needs to state the rules at all: it
   calls `cxt_groups`, which applies them.
4. **Drop the stale `docmap` glossary line** (and fix the malformed glossary table
   header while I'm in it — it's missing its separator row).
5. **`executor/design.md`** — **already retired** in a prior baseline commit
   (`1a67a8a` deleted it; it is not in the tree). Confirmed the only remaining
   references are in `advance_plan.md` (a plan doc describing the intent — left
   untouched). Nothing live points at it, so there is nothing to delete or repoint;
   noted for completeness.

## Files touched

- `src/docex/docs/overhead.py` — **new.** Pure `compute_overhead(nodes, edges,
  subject) -> list[Node]` (the 3 rules) + `run_docs_overhead(ctx, file)` + JSON
  render.
- `src/docex/docs/changed.py` — **new.** Pure `in_scope_changed(paths, codebases)`
  allowlist filter + `run_docs_changed(ctx, git_ref)`.
- `src/docex/docs/cxt_groups.py` — **new.** Pure `build_context_groups(nodes,
  edges, subjects, tokens_max) -> list[Group]` + `run_docs_cxt_groups(ctx,
  tokens_max, selection)` + JSON render.
- `src/docex/docs/linkmap.py` — add `load_code_level_graph(ctx)` helper (reuses
  existing enumeration; no behavior change).
- `src/docex/docs/__init__.py` — export the new public functions.
- `src/docex/__main__.py` — add `overhead <file>`, `changed <git_ref>`,
  `cxt_groups <tokens_max> <selection>` subparsers to `_cmd_docs`; update its
  docstring + the `docs` help line (currently "scaffold/check/adr/linkmap").
- `src/docex/git/client.py` + `src/docex/git/subprocess_client.py` — add
  `diff_names`.
- `tests/conftest.py` — `FakeGitClient.diff_names` + `diff_names_map`.
- `skills/doc-refine-orchestration/SKILL.md` — the four edits above.

## Tests

- `tests/unit/test_docs_overhead.py` — **new.** The 3 rules over `tmp_path`
  fixtures: L1 roots always present; direct-link (md + mermaid) targets included;
  source subject pulls its module doc (emergent) + the module doc's links (rule 3);
  non-doc / `neither` / source targets excluded from overhead; high→low ordering;
  unknown-file → nonzero exit.
- `tests/unit/test_docs_changed.py` — **new.** Allowlist filter (keeps
  `plans/design` + `core/<cb>/src`, drops others); deleted-path drop; empty-tree
  ref → all; ordering/dedup; via `FakeGitClient.diff_names_map`.
- `tests/unit/test_docs_cxt_groups.py` — **new.** Full cover + no repeated subject;
  cost ≤ `tokens_max` respected; overlap clustering (module/codebase lines);
  oversize-subject singleton + exit 0; deterministic group/overhead/subject
  ordering; `all` vs `<ref>` selection.
- `tests/unit/test_docs_dispatcher.py` — extend: the three verbs wired +
  arg-validated (`tokens_max` a positive int; `cxt_groups` selection accepts `all`
  or a ref string).
- `tests/integration/test_docs_changed_real.py` — **new, `@pytest.mark.integration`.**
  `diff_names` against a real temp git repo: a committed change since a ref appears,
  an out-of-allowlist change does not, empty-tree ref lists all tracked in-scope.

Test discipline: unit (`python -m pytest tests`) and integration
(`python -m pytest tests -m integration`) run as **separate** invocations from
`docex/`; close with a full suite run.

## Artifact alignment (six-artifact)

- **`doctrine/infrastructure/docex.md § docs`** — document the three new verbs +
  their output formats (JSON for `overhead`/`cxt_groups`, plain list for `changed`).
  Scoped narrowly to the `docs` section; pre-authorized by the Goal 3 criteria.
- **`docex/plans/design/specifics/subcommand_surface.md`** — extend the `docs`
  command row to list `overhead`/`changed`/`cxt_groups` (this is the post-166 home
  of the command table; there is no more `masterplan.md`).
- `tables/roles/*.yml` + `doctrine_excerpts/*` — **n/a.** The verbs add no
  *infrastructural resource* (no role, engine, or backing service), only docs
  tooling, so neither the role tables nor the excerpt index is affected (per
  `docex_process § What earns an entry`). Confirmed.
- `src/docex/**`, `tests/**` — above.

## Out of scope

Context-grouping *calibration* against docex's real corpus (Mod 168) — this mod
ships the estimator/heuristic, not its accuracy tuning. No end-to-end run of
`doc-refine` / `doc-refine-orchestration` (advance Non-Goal). No `--format` flags.

## Open design questions for C.O.

None blocking. Three awareness items — I proceed unless you object:

1. **`overhead` rule-2 folds in the emergent edge** so a source file's module doc
   is part of its overhead (see Interpretation call above). Without this, a source
   file's single most relevant doc would be excluded. I believe this matches
   intent; flagging because the design's prose says "directly links to" and the
   module-doc inclusion is my reading of it.
2. **`cxt_groups` oversize subject → singleton group, exit 0** (stderr warning),
   rather than a hard failure — because `tokens_max` is explicitly an estimate.
3. **`docex.md § docs` edit** — a doctrine file, but pre-authorized in the Goal 3
   criteria and scoped to the `docs` section. Flagging per the "ask before altering
   doctrine" rule.

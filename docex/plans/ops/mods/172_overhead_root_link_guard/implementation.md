# Mod 172 — Implementation

Guard `compute_overhead` so it never follows the outbound links of a file that
is an L1 standard root. This affects both `docex docs overhead` and
`docex docs cxt_groups` (the latter consumes `compute_overhead` unchanged).

All paths are under `~/.claude/jean_baudrillard`. Work on branch
`mod-172-overhead-root-guard`.

Scope of THIS document: **code + tests only.** Do **not** edit any docs under
`plans/design`, the resident doctrine (`doctrine/**`), or `CHANGELOG.md` — those
are handled outside this step.

## Step 1 — `docex/src/docex/docs/overhead.py`

### 1a. Guard link-following in `compute_overhead`

The current body computes rule 1, then rule 2 (subject's links), then rule 3
(module doc's links for a source subject). Change it so that:

- The root set is computed once via the existing `_rule_one_roots(nodes)`.
- **Rule 2 is skipped when the subject is a root.** When skipped, the value used
  downstream (the `rule2` set that rule 3 consults to find the module doc) must
  still be a well-defined set — use an empty set in that case.
- **Rule 3's follow of the module doc is guarded** with the same root check, for
  uniformity. (A module doc is L3 and never a root, so this guard never fires in
  practice, but it makes the "never follow a root's links" invariant explicit
  and local.)

Replace the rule 2 / rule 3 region of `compute_overhead` (currently the block
from the `# Rule 2` comment through the rule-3 `if` block) with logic equivalent
to:

```python
    roots = _rule_one_roots(nodes)

    # Rule 1 — L1 roots + standard diagrams.
    fpaths |= roots

    # Rule 2 — design docs the subject directly links to (incl. emergent).
    # A standard root is a router: never follow its outbound links (mod 172).
    if subject_fpath in roots:
        rule2: set[str] = set()
    else:
        rule2 = outgoing_design_targets(nodes, edges, subject_fpath)
    fpaths |= rule2

    # Rule 3 — for a source subject with a module doc, the module doc's links.
    # Guarded by the same root check for uniformity (a module doc is never a
    # root, so this never fires; the guard makes the invariant explicit).
    if subject is not None and subject.type == "source":
        module_doc = _module_doc_fpath(by_fpath, rule2, subject)
        if module_doc is not None and module_doc not in roots:
            fpaths |= outgoing_design_targets(nodes, edges, module_doc)
```

Note the existing code already does `fpaths |= _rule_one_roots(nodes)` for rule 1;
fold that into the single `roots` computation above so `_rule_one_roots` is
called once. Leave everything before (`by_fpath`, `subject`, `fpaths = set()`)
and after (the `fpaths.discard(subject_fpath)` / resolve / sort / return) intact.

### 1b. Update the module docstring

In the module docstring's numbered "three rules" block, update rule 2 (and note
on rule 3) to state the guard. Keep it accurate to the new behavior — e.g. after
the existing rule list, add a sentence such as:

> A standard root is a router file; its own outbound links are never followed, so
> rules 2 and 3 contribute nothing when their source file is a standard root.
> (In practice this only affects a standard-root *subject* under rule 2, since a
> module doc is never a root.)

## Step 2 — `docex/tests/unit/test_docs_overhead.py`

### 2a. Flip `test_rule2_mermaid_click_is_overhead`

This test currently uses a `module_diagram.mmd` (a standard root) as the subject
and asserts its click target IS overhead. Under mod 172 that is now blocked.
Rewrite it to assert the click target is NOT in the diagram subject's overhead,
and rename it to reflect the new intent, e.g.
`test_diagram_subject_does_not_follow_click_links`.

Keep the fixture shape (a `module_diagram.mmd` with a `click` to a `module/`
doc). Because a bare `module_diagram.mmd` built alone may not register as a
standard root in the linkmap, ensure the diagram node is recognized as a root —
the simplest robust approach is to build the graph from a scaffolded design tree
so the standard roots exist, mirroring `test_rule1_l1_roots_always_present`
(`scaffold_design(tmp_path, ["api"])` then `_enumerate_design_files`). Assert:

- The click target (`plans/design/api/module/orders.md`) is **not** in the
  overhead of subject `plans/design/api/module_diagram.mmd`.
- Sanity: another root (e.g. `plans/design/api/module_diagram.mmd` is the
  subject, so check `plans/design/boundary_conditions.md`) **is** still present
  (rule 1 unaffected).

### 2b. Add a root-subject markdown-link test

Add a test that a standard-root **subject** with an outbound markdown link to a
non-root doc does not pull that doc into overhead, while rule 1 still supplies
all roots. Suggested shape (`test_root_subject_does_not_follow_markdown_links`):

- `scaffold_design(tmp_path, ["api"])`.
- Overwrite a standard root — e.g. `plans/design/concepts_and_decisions.md` —
  to contain a markdown link to a fresh non-root doc
  `plans/design/api/specifics/detail.md`; create that target file.
- Build via `_enumerate_design_files` + `build_linkmap(..., "code_level", ...)`.
- Compute overhead for subject `plans/design/concepts_and_decisions.md`.
- Assert `plans/design/api/specifics/detail.md` is **not** in the overhead.
- Assert a sibling root (e.g. `plans/design/boundary_conditions.md`) **is** in
  the overhead (rule 1 still fires for a root subject).

### 2c. Confirm unaffected tests

`test_source_subject_pulls_module_doc_and_its_links` must still pass unchanged
(a source subject is never a root: its emergent module-doc fold-in and rule-3
follow both still run). Leave rule-1 and ordering tests as-is.

## Step 3 — Run the tests

Run from `docex/` (never the repo root, never bare `pytest`):

```bash
cd ~/.claude/jean_baudrillard/docex
python -m pytest tests/unit/test_docs_overhead.py tests/unit/test_docs_cxt_groups.py
```

Both files must be green. `test_docs_cxt_groups.py` is expected to pass without
edits (it consumes `compute_overhead`); if any cxt_groups assertion depends on a
root subject's fan-out, report it rather than silently changing it.

Then run the full unit suite to catch anything else touching overhead:

```bash
cd ~/.claude/jean_baudrillard/docex
python -m pytest tests
```

Report the pass/fail counts. Do not run the integration suite in this step (the
mod-cycle review runs the full gate separately).

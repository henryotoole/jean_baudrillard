# Execution plan — the codebase / core-service rename

Companion to [`codebase_core_service_rename.md`](./codebase_core_service_rename.md),
which holds the design and the locked decisions. This file is the *how*.

> **Status.** Phases 0–2 **done**. Phase 3 steps **1–5 done and verified** —
> unit **995 passed**, integration **64 passed**, compile byte-diff confirms
> decision 4 (see [Step 3 verification](#step-3-verification--decision-4-holds)),
> protected tokens identical to pristine HEAD, zero residual old vocabulary.
>
> **Step 6 (release surface) is deliberately NOT started.** It flips
> `cicl_version` 2 → 3 and writes `upgrade_2.0.0.md` — and
> [`uses_relation_merge.md`](./uses_relation_merge.md) is *also* a 2 → 3 change
> that must ride the same cut. Doing step 6 now would mean two 2 → 3 bumps and an
> upgrade guide amended mid-flight. Awaiting the operator's sequencing call.

## Why not a find-and-replace

Three properties of this rename defeat the obvious approach.

**1. It is a cycle, not two renames.** `core service → codebase` and
`process type → core service` both write into the same slot. Run them
sequentially in either order and the second pass cannot distinguish its own
output from its input.

*Mitigation — sentinel translation.* Pass 1 maps `core service → @@CODEBASE@@`
and `process type → @@CORESVC@@`. Pass 2 maps sentinels to final words. The swap
becomes atomic and order-independent, and any `@@` surviving into a committed
file is a detectable bug rather than a silent double-translation.

**2. `core service` is two senses sharing one spelling.** Most mentions are the
codebase, but some already mean the deployed unit (`core service container`) and
must stay unchanged. This is the only part of the rename requiring judgment, and
it is why the inventory is *sense-tagged* rather than merely recorded.

**3. ~920 protected tokens contain `process` as a substring** — `subprocess`,
`processor`, `processed_at`, `docex_process` — plus 12-factor "processes" in the
OS sense. A `s/process/service/` would corrupt all of them.

## Phase 0 — Guard rails *(done)*

| Artifact | What it is |
| -------- | ---------- |
| `baseline/affected_all.txt` | 311 files carrying an affected term |
| `baseline/frozen.txt` | 107 files deliberately **not** touched |
| `baseline/working.txt` | 204 files that change |
| `baseline/protected_tokens.txt` | 21 token kinds, 922 occurrences, to be re-counted after |
| `baseline/anchors_all.txt` | 774 markdown anchor links, for link-integrity diffing |
| `baseline/compiled/` + `compiled.sha256` | 21 compiled artifacts from both test projects |

Two findings worth keeping:

- **The elastic test project's committed output is byte-reproducible.** A fresh
  `docex compile` produces a zero-diff against what is in git. That makes the
  Phase 4 identity check exact rather than approximate.
- **The `fixed` project's `infra/output/` is untracked.** Compiling it dirties
  the tree with ~12 untracked files. Baselining copied them out and then removed
  them; anyone repeating this must do the same or `git status` will look alarming.

### Freeze list rationale

107 files are frozen because they are *records of the past*, and rewriting them
would falsify history:

- `docex/plans/modifications/**` (97) — per
  [`practices/modifications.md`](../../../../doctrine/practices/modifications.md),
  a mod doc records a change as designed at the time. Several *titles* correctly
  record the old vocabulary (`094_doctrine_process_types`, `096_process_nesting`,
  `103_scheduler_process_type`).
- `docex/plans/advances/{003_envmageddon,004_next}/**` — same reasoning.
- `upgrades/upgrade_{1.2.0,1.5.0,1.6.0,1.6.1}.md` — each instructs an upgrade
  *to a version that used the old vocabulary*. Rewriting them makes their
  instructions wrong. `upgrade_2.0.0.md` is the one that explains the rename.
- `skill_iter/eval/outcome/project-cohere/full.run.2x.sonnet-sub.json` — a
  recorded run result.
- `codebase_core_service_rename.md` — this advance's own design record, which is
  written in deliberately mixed vocabulary (it is the old→new mapping).

Sibling design docs *within* this advance (`uses_relation_merge.md`,
`service_connect_reconcile_trigger.md`) are live input, not history, and **are**
reworded.

> A prior version of the freeze regex used `advances/(003|004)/`, which silently
> matched nothing because the directories are `003_envmageddon` and `004_next`.
> The bug inflated the working set by 38 files. Anchor freeze patterns on
> `[^/]*/`, and always assert `frozen + working == affected`.

## Phase 1 — Sense-tagged inventory *(done)*

`rename_classify.py` walks the working set and emits one row per hit:
`file, line, term, sense, confidence, proposed, context`.

| Sense | Rows | Meaning | Auto? |
| ----- | ---: | ------- | ----- |
| `SVC` | 920 | `process type` family → `core service` family | yes |
| `IDENT` | 672 | code identifier / data key → deterministic | yes |
| `CB` | 127 | prose carrying the codebase sense → `codebase` | yes |
| `KEY_FIELD` | 82 | `domain_default_process` → `domain_default_service` | yes |
| `KEY_NEST` | 53 | `processes:` → `core_services:` | yes |
| `KEY_TOP` | 49 | `core_services:` → `codebases:` | yes |
| `REF` | 38 | magic ref namespace → full literal path | yes |
| `KEEP` | 28 | already the deployed sense → unchanged | yes |
| `AMBIG` | 238 | **needs adjudication** | **no** |
| `PROTECTED_NEARBY` | 28 | a protected token shares the line | **no** |

**1,969 of 2,235 rows (88%) are mechanical. 266 rows across 62 files need a
human.** Those are extracted to `rename_adjudicate.tsv`.

### The classifier defect worth knowing about

An early version resolved lines carrying *both* senses to `KEEP` at high
confidence — which would have suppressed review on exactly the rows most likely
to be wrong. Nine such rows exist, and they are substantive. The worst is
[`infrastructure.md:228`](../../../../doctrine/infrastructure/infrastructure.md):

> All **core service containers** place the service working directory at a fixed
> root: `/service`. This root maps to the "**core service folder**" in the source code.

First mention is the deployed unit (stays `core service`); second is the codebase
(becomes `codebase folder`). One sentence, both senses, opposite treatments — and
it also touches decision 5, which keeps `/service` and `$pr/core/` as they are.

**Rule for the classifier, now encoded: when both sense-signals fire, emit
`AMBIG`/`mixed` and never auto-resolve.** A wrong `AMBIG` costs a glance; a wrong
high-confidence call ships.

## Phase 2 — Adjudicate *(next)*

Work `rename_adjudicate.tsv`, 266 rows / 62 files. Resolve each to `CB`, `KEEP`,
or `SVC` and write the decision back into the `sense` column. Order by leverage:

1. The **9 `mixed`** rows first — highest risk, and they set precedent.
2. `doctrine/infrastructure/specifics/telemetry_infra.md` (28),
   `transfer_tables.md` (21), `cicl.md` (15), `infrastructure.md` (14) — the
   dense doctrine files.
3. The 28 `PROTECTED_NEARBY` rows — confirm the protected token is untouched and
   classify the real hit.
4. The long tail.

Adjudicating a file wholesale, by reading it, beats adjudicating row-by-row: the
sense is usually obvious in context and ambiguous in isolation.

## Phase 3 — Apply

Sentinel translation, in dependency order. Each step ends green before the next
begins.

1. **`docex` source** — `cicl/model.py` (the dataclasses) → `cicl/compile.py`,
   `validate.py`, `magic_refs.py` → `emit/*` including the two `.tf.j2`
   templates → **tag filters** → `__main__.py`, `errors.py`.
2. **Transfer tables** (`docex/tables/roles/{web,worker,scheduler}.yml`) and
   **`doctrine_excerpts`** — note `core_service.md`'s *filename* is referenced by
   `index.yml`; file and index move together or neither does.
3. **Authored surface** — `tests/fixtures/**/infra.yml` (4), both test projects'
   `infra.yml`, then regenerate committed compiled output.
4. **Doctrine markdown** — [`lexicon.md`](../../../../doctrine/lexicon.md) first;
   every other prose file leans on those definitions. Then `cicl.md`, then the
   rest. Rename headings and fix all inbound anchors in the same commit.
5. **Skills** (6) and **eval fixtures** — 8 live `evals.json` plus `queries.json`
   must be reworded or the outcome evals fail against the new vocabulary.
6. **Release surface** — `upgrade_2.0.0.md`, `CHANGELOG.md`, `VERSION` → 1.7.0,
   `cicl_version` → 3.

### Step 1 outcome — five bug classes a scripted rename produces

Recorded because every one of them will recur in steps 2–6, and three were
invisible to review.

1. **Simultaneous swaps defeat ordered rules.** At a `standard_tags()` call site
   the old `service=` must become `codebase=` *while* `process=` becomes
   `service=`. No sequence of regex passes expresses that — the first pass's
   output is the second pass's input. The 13 call sites were edited by hand.
   Python caught the failure as `duplicate keyword argument`; a language without
   that check would have shipped it.
2. **Bare fields the rename forgot.** `ServiceRef.service` (the codebase slot)
   and `_global_service_name`'s positional `service` were spelled without the
   `core_` prefix, so no `core_service` rule matched them, and the `process` rule
   renamed *their sibling* into a collision. Symptom: `duplicate argument`.
3. **Quoted string literals are invisible to context-anchored rules.**
   `doc["processes"]` and `web["process"]` never matched `processes(?=\s*[:=])`
   or `\.process\b`. Only a test run surfaced them — 112 collection errors.
   Any rule keyed on *syntax* misses keys carried as *data*.
4. **Prose grammar breaks in ways greps don't show.** `core process type` →
   `core core service` (37 sites), and `process types` → `core service` silently
   lost plurality (~26 agreement errors). Fixed with a targeted repair pass;
   worth re-running after every prose step.
5. **A mechanical "fix" can corrupt a deliberate example.** The ref-upgrade pass
   rewrote a comment that intentionally quoted the *old* four-segment form as an
   example, making the comment contradict itself. Comments that quote
   pre-rename syntax are data, not code.
6. **The rename target already existed — silent shadowing.** The worst of the
   six. `all_processes()` → `all_services()` collided with an *existing*
   `CICLDocument.all_services()`, so Python kept the second definition and
   every one of the original's callers silently received the wrong type. This
   accounted for the bulk of the ~370 failures: rule 14 raised
   `TypeError: unhashable type: 'Codebase'` because it was iterating tuples
   where it expected a dict of names.

   **A rename must check that its target name is free before taking it.** Grep
   the destination, not just the source. The mechanical guard is an AST pass for
   duplicate definitions per class/module — cheap, and it finds this instantly:

   ```
   docex/cicl/model.py: CICLDocument: DUPLICATE ['all_services']
   ```

   Resolution split the two accessors on what they actually return:
   - `all_core_services()` — every `(codebase, service, Codebase, CoreService)`
     tuple. 20 of the 22 call sites.
   - `all_authored()` — the merged top-level map. Deliberately **not**
     `all_services()`: it merges `Codebase` with `BackingService` entries, and a
     codebase is not a service. Keeping the old name here would have preserved
     exactly the kind of wart this whole rename exists to remove.

7. **The swap at attribute level: old name of field A becomes new name of field
   B.** `ServiceRef` (was `ProcessRef`) had fields `service` (the codebase) and
   `process` (the core service). After renaming `service`→`codebase` and
   `process`→`service`, every reference that still read `.service` **silently
   began returning field B's value.**

   ```python
   svc = doc.codebases.get(ref.service)   # ran fine, returned the wrong thing
   ```

   No exception, no type error, no test-collection failure — valid Python
   producing a wrong string. Symptom was a nonsense validation message:
   `domain_default_service 'api.web' names core service 'web', which is not
   declared`. Sites where both fields appeared collapsed into self-comparisons
   that are *always true*:

   ```python
   if (ref.service, ref.process) == ...   # became (ref.service, ref.service)
   ```

   That second form is worse than a crash: `rule_3` self-reference detection
   would have silently stopped detecting anything.

   **This is why the sentinel discipline must extend to attribute access, not
   just declarations.** The fix used `git grep` against HEAD to recover which of
   the 27 current `.service` accesses had *originally* been `.service` (→
   `.codebase`, 12 sites) versus rewritten from `.process` (→ already correct).
   The pre-rename tree is the only oracle for that distinction once the rename
   has landed — so **do this reconstruction before the source of truth is
   overwritten**, or keep the sentinel form in the tree until it is resolved.

8. **`\b` is defeated by escape sequences and underscores.** `\bdomain_default_process\b`
   silently skipped both of these:

   ```python
   f"container_registry: reg.example.com\ndomain_default_process: {value}"
   def _validate_domain_default_process(doc): ...
   ```

   In the first, the character before `d` is the literal `n` of `\n` — a word
   character, so there is no word boundary. In the second it is `_`. Neither is
   a boundary, so neither matched, and both survived into a passing-looking tree
   until pydantic rejected `domain_default_process` as an extra input.

   **For tokens long enough to be unambiguous — `domain_default_process`,
   `core_services`, `process_type` — drop `\b` and replace unconditionally.**
   Word-boundary anchoring buys protection only for short tokens that appear as
   substrings of unrelated words; on a 21-character compound it buys nothing and
   costs coverage. Reserve `\b` for `process`, `service`, and friends.

9. **Emitters are not all Python.** `emit/templates/*.tf.j2` call
   `standard_tags()` from Jinja with no type checking, so the pre-rename
   `service="etc"` survived and asserted out on every env-tier resource. A grep
   restricted to `*.py` reports all-clear. See the four-file-kind table in
   [Phase 4](#phase-4--verify) check 2.

10. **A declaration renamed without its uses.** `process: str = None` matched the
    `process(?=\s*[:=])` rule and became `service:`, but the bare *use* one line
    later did not:

    ```python
    service=process,     # NameError: name 'process' is not defined
    ```

    Same shape inside an f-string YAML template (`{process}` where the parameter
    had become `service`).

### The tool that should have come first: parse, don't grep

Classes 3, 8, and 10 are all the same mistake — **using regexes to find
identifiers in a language that has a parser.** Every one of them was a
context a text pattern could not see: a string-literal key, a `\n`-prefixed
token, a bare read with no adjacent punctuation.

A twenty-line `ast` walk answers the question exactly, with no false positives
and no false negatives:

```python
for node in ast.walk(ast.parse(src)):
    if (isinstance(node, ast.Name)      and node.id  in TARGETS) or \
       (isinstance(node, ast.Attribute) and node.attr in TARGETS) or \
       (isinstance(node, ast.keyword)   and node.arg  in TARGETS) or \
       (isinstance(node, ast.arg)       and node.arg  in TARGETS):
        report(node)
```

Run over `docex/src` + `docex/tests` it found **exactly 6** live references to
`process`/`processes` and correctly ignored ~920 protected tokens and every
mention in a comment or docstring — no tuning, no allowlist. Two of the six were
real breakages; four were a self-consistent loop variable that worked but
carried stale vocabulary.

The same pass is what caught class 6 (duplicate definitions per scope). **Use
regexes for prose and the AST for code.** The reverse — which is what steps 1's
first pass did — is what produced five of the ten bug classes.

### Step 1 also carried a real behavior change

Decision 3 is **not** a rename: magic-ref arity goes 4 → 5 segments, with
`core_services` a *literal* grammar segment. `magic_refs.py` now rejects the old
form with a migration-specific message rather than a generic arity error:

```
${codebases.api.worker.host}
  -> This looks like the pre-1.7.0 four-segment form.
     Did you mean ${codebases.api.core_services.worker.host}?

${codebases.api.processes.worker.host}
  -> Body segment 2 must be the literal `core_services`, not 'processes'
     — a core ref is a path walk through the document.
```

The second case is the one that pays off: an operator hand-migrating who reaches
for the *old nested key* gets told exactly what is wrong, instead of a
"codebase not found" that sends them looking in the wrong place.

### Step 3 verification — decision 4 holds

Both test projects recompiled and diffed against a pristine-HEAD compile.
**21/21 artifacts.** Every single difference is one of the four intended key
renames:

| Kind | Before | After |
| ---- | ------ | ----- |
| OTel resource attr | `docex.core_service=` | `docex.codebase=` |
| OTel resource attr | `docex.process_type=` | `docex.service=` |
| Elastic env tag key | `service = "…"` | `codebase = "…"` |
| Elastic env tag key | `process = "…"` | `service = "…"` |

Verified mechanically rather than by eye: canonicalize the pre-rename output by
applying exactly those four substitutions, then assert equality. Result —
**zero unexplained differences**. Which confirms, on real output:

- **Every emitted `Name` is byte-identical.** `docex_smoke_elastic_stage_api_web`
  on both sides. The `(codebase, service)` segment order renders the same as the
  old `(service, process)` order.
- **`shape_name` values are untouched** (`core_service` / `backing_service`) —
  [P5](./codebase_core_service_rename_adjudication.md#p5--shape_name-values-are-unchanged)
  confirmed against output, not just asserted.
- **`role` values, container names, image refs, domain labels: all identical.**
- **Backing services carry `codebase` but no `service` key** — the dimension is
  correctly absent, exactly as `process` was.

Two files (`prod/main.tf`, `stage/main.tf`) additionally **reorder** one tag
block: tags render alphabetically, and `codebase` sorts before `descriptor`
where `service` sorted after `role`. Same multiset of lines, different order.
HCL `tags` is a map, so tofu compares it order-insensitively — cosmetic, no
resource churn. Worth knowing before reading a `tofu plan` diff.

> **A confound worth avoiding.** The first attempt diffed against
> `baseline/compiled/`, which had been produced by `./bin/docex` — i.e. the
> **pinned docex Docker image (1.6.0)** — while the new output came from local
> 1.6.1 source. That surfaced a spurious `internal: true` line that had nothing
> to do with the rename. **The oracle must be a pristine-HEAD compile run
> through the same code path as the comparison** (`PYTHONPATH=…/src python3 -m
> docex compile` on a `git archive HEAD` tree), differing only in the rename.

### Anchors are load-bearing

Renaming headings breaks ~73 inbound links. `#core-services` alone has **47**.
Others: `#codebase-containers` (8),
`#per-core-service-env-both-foundations` (8), `#what-is-not-process-qualified`
(3), `#process-expansion` (2), `#why-processes-is-mandatory` (1),
`#the-backbone-process-expansion` (1),
`#per-core-service-sidecar-both-foundations` (1).

The doctrine names this cost explicitly in
[`doctrine.md § Skills`](../../../../doctrine/doctrine.md) — keeping thread-skill
pointers valid "should be checked mechanically." Diff `anchors_all.txt` before
and after; every changed anchor must resolve to a real heading.

## Phase 4 — Verify

A green suite is **not** sufficient: it stays green if the emitter and the tag
filters move together but both move wrongly. Five checks:

1. **Compiled output byte-identical except tag keys.** Recompile both projects,
   diff against `baseline/compiled/`. Every difference must be one of the two
   elastic tag keys. Any change to a container name, domain label, image ref, or
   contract path is a defect — per
   [decision 4](./codebase_core_service_rename.md#on-decision-4--why-the-tag-churn-is-cheap)
   every emitted string renders identically.
2. **Tag filters match the emitter.** `docex` reads env-tier tags for teardown
   and Service-Connect reconcile. A filter left on an old key matches zero
   resources and fails *silently*. Grep every literal `"service"` / `"process"`
   used as a tag key and confirm it moved.

   **The tag surface is not only Python.** It spans four file kinds, and step 1
   proved the point: `emit/templates/main.tf.j2` calls `standard_tags()` from
   *Jinja*, kept passing the pre-rename `service="etc"`, and asserted out on
   every env-tier resource. A grep restricted to `*.py` reports all-clear.

   | Where | What to check |
   | ----- | ------------- |
   | `*.py` | `standard_tags()` call sites, tag-filter dict keys |
   | `*.j2` | `standard_tags()` called from templates — same signature, no type checking |
   | emitted `*.tf` | the rendered `tags = { … }` blocks |
   | emitted `*.yml` | compose `labels:` |
3. **Protected tokens unchanged.** All 21 kinds must match, with **no count
   lower** than the pre-rename tree.

   Two corrections to how this is measured, both learned the hard way:

   - **The oracle is `git archive HEAD`, not the working tree.**
     `baseline/protected_tokens.txt` was captured *after* the design record was
     written, so it already counted that file's own enumeration of the protected
     tokens. Comparing against it produced a uniform −1 across nearly every kind
     — pure artifact, indistinguishable at a glance from real corruption.
   - **Exclude this advance's own directory from both sides.** The rename's
     paperwork discusses `subprocess`, `processor`, and `docex_process` by name,
     so leaving it in inflates the "now" side and masks a genuine loss.

   ```sh
   git archive HEAD | tar -x -C /tmp/pristine
   # count in /tmp/pristine, and in the working tree with
   # --exclude-dir=005_process_type_solidification, then diff the two
   ```

   Run against steps 1–2 this reports **zero differences** — every count
   identical to HEAD, no kind lost. A measurement that cannot distinguish
   "unchanged" from "off by one everywhere" is not a check, so fix the
   instrument before trusting the reading.
4. **No surviving sentinels.** `grep -r '@@'` returns nothing.
5. **Anchors resolve.** Diff against `baseline/anchors_all.txt`; no dangling
   targets. Then the full unit + integration suite.

## Open: the changelogs

`CHANGELOG.md` contributes 27 adjudication rows, and they are a different kind of
question from the rest. Entries for shipped versions describe what was true at
the time — e.g. the 1.6.0 entry *"A core service is a codebase declaring N
process types"*, which was an accurate statement about 1.6.0.

By the same logic that freezes the mod docs and the old upgrade guides, **past
changelog entries should be frozen** and a new 1.7.0 entry should describe the
rename, giving the old→new mapping. The alternative — rewriting history so the
changelog reads uniformly — makes every historical entry subtly false.

Recommendation: **freeze past entries; add a 1.7.0 entry.** Same for the two test
projects' `CHANGELOG.md` (4 rows). Flagged rather than decided, because it moves
~31 rows out of the adjudication bucket and into the freeze list.

# Mod 168 — `cxt_groups` token-estimate calibration

## Nature of this mod

This is an **empirical calibration**, not a feature cycle. Its primary output is a
**calibration report** (`calibration.md`) on how accurate the `linkmap`/`cxt_groups`
per-file `tokens` estimate is against real, measured token consumption. A **tuning
code change ships ONLY IF** the calibration shows the estimate is materially off
(>~25% systematic bias). If the estimate is within tolerance, this mod ships the
report and **no code change** — that is an explicitly valid outcome (advance 011,
Goal 3 SC5).

This `overview.md` is the **measurement methodology** for C.O. review. Per the C.O.
directive I pause after it — a flawed method yields a useless calibration, so the
method is vetted *before* execution.

## What is being calibrated

The estimator under test (`src/docex/docs/linkmap.py::_estimate_tokens`):

```python
def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
```

A flat **4-chars-per-token** heuristic, deliberately dependency-free (no `tiktoken`
— an operator-aware ruling). Every `Node.tokens`, and therefore every
`cxt_groups` group `estimated_tokens`, is built from it. The calibration measures
the **real** chars-per-token of docex's own migrated design corpus and compares it
to the assumed 4.0.

## Foundation (from mods 165 / 166 / 167)

- **165** added `linkmap` + the `_estimate_tokens` heuristic above.
- **166** migrated docex's design docs into `plans/design/**` (the dogfood corpus).
- **167** added `cxt_groups` and the root-parameterized pure cores
  (`load_code_level_graph`, `build_context_groups`, `compute_overhead`) that take an
  **explicit project root + codebase list**, NOT a `ProjectContext`. docex has no
  `project.yml`, so the CLI cannot run `cxt_groups` against docex itself; I drive
  the pure functions directly from a throwaway script in docex's importable `src/`.

## Step 1 — Selection of subjects (how the corpus is grouped)

**Subject set = every `design` node of docex's `code_level` graph** rooted at docex
with codebase list `["docex"]`. Concretely: `load_code_level_graph(<docex root>,
["docex"])` yields **20 design nodes**, **0 source nodes**, 31 `neither` stubs.

Two facts drive the method and are called out honestly:

1. **The `changed <ref>` selection path is unusable here — I select design nodes
   directly instead** (the task explicitly permits "or select them directly").
   Reason: docex is a **subfolder** of the `jean_baudrillard` git repo. `changed`
   runs `git diff --name-only <ref> -- <allowlist>` and git returns **repo-root-relative**
   paths (`docex/plans/design/…`), which then fail the *project-relative* allowlist
   filter (`plans/design/…`). Empirically `changed_fpaths(<docex root>, ["docex"],
   "1fb9f5c")` returns **0** in-scope subjects for exactly this reason — not because
   nothing changed (all 20 design files were added by mod 166's migration). Direct
   selection of the 20 design nodes is the equivalent intended subject set and
   sidesteps the subfolder-git artifact. (`1fb9f5c` = `8c30d1f^`, the pre-dogfood
   commit, is noted for the record; it is not used as the ref.)

2. **There are 0 source nodes**, because docex's source lives at `src/docex/**`, not
   at the doctrine-standard `core/<cb>/src/**` that `_resolve_tracked_source` scans.
   **Consequence: this calibration measures the heuristic against markdown/prose
   only** (arc42 docs, ADRs, `.mmd` diagrams). It does **not** measure source-code
   density. Source code is known to tokenize denser than prose (~3–3.5 chars/token),
   so the len/4 heuristic likely undercounts source more than prose — but that is
   **out of scope of what this corpus can measure** and will be recorded as an
   explicit limitation, not a tested claim.

## Step 1b — Forcing a handful of groups

Total design-corpus estimate ≈ **59,310 tokens** across 20 docs. A few docs are
individually large (`compiler.md` ≈ 19,400; `release_flow.md` ≈ 8,954), so their
self+overhead cost alone exceeds any small budget and they fall out as oversize
singletons.

**Chosen `tokens_max = 20,000`** → **8 groups** (subject counts `[12, 2, 1, 1, 1, 1,
1, 1]`; 6 oversize singletons). A handful — not 1, not dozens. The clustering is the
design's predicted behavior: everything shares the L1 roots as overhead, so the
small docs clump into one group and the big docs stand alone.

## Step 2 — The group I will measure

The **representative group is the 12-subject clump** (`estimated_tokens = 19,973`) —
the only substantial multi-subject, non-oversize group, and exactly the kind of
group `doc-refine-orchestration` would hand to one subagent. Its **16 unique files**
(12 subjects ∪ 4 shared overhead):

| kind | file | len/4 est | chars | lines |
| ---- | ---- | --------- | ----- | ----- |
| subj | adr_active.md | 238 | 950 | 17 |
| subj | adr_index.md | 255 | 1019 | 15 |
| subj | adrs/0001_single_bundled_docex_image.md | 502 | 2006 | 41 |
| subj | adrs/0002_patch_only_tags_digest_pinned_base.md | 310 | 1240 | 32 |
| subj | adrs/0003_docker_outside_of_docker.md | 648 | 2591 | 50 |
| subj | adrs/0004_preinfra_fail_vs_decline.md | 506 | 2024 | 41 |
| subj | adrs/0005_durable_job_substrate.md | 605 | 2421 | 46 |
| subj | adrs/0006_host_brokered_git_credentials.md | 589 | 2356 | 45 |
| subj | project_diagram.mmd | 328 | 1311 | 26 |
| subj | specifics/subcommand_surface.md | 5923 | 23691 | 247 |
| subj | specifics/the_shim.md | 1780 | 7119 | 95 |
| subj | unknowns.md | 104 | 414 | 12 |
| ovh | boundary_conditions.md | 1438 | 5751 | 100 |
| ovh | concepts_and_decisions.md | 3235 | 12939 | 211 |
| ovh | lexicon.md | 653 | 2613 | 20 |
| ovh | structures_and_views.md | 2859 | 11436 | 175 |

**Totals: 79,881 chars → sum(len/4) = 19,973 tokens** (exactly the group's
`estimated_tokens`; confirms the group cost is just chars/4 over the unique set).
Max file = 247 lines, **well under Read's 2000-line default**, so a Read returns each
file's *full* content — the measured token cost covers the same text the estimator
sized.

## Step 3 — Measuring real tokens (paired reader/control)

I isolate **file-content tokens** from the subagent's fixed overhead (system prompt,
tool definitions, task prompt) with a **paired-control** design. Both agents are the
**same `subagent_type`** so their fixed overhead is identical and cancels.

- **Reader (private):** its *only* job is to Read all **16** files above, issuing the
  Reads in a **single batched turn** (parallel Read calls → one clean context-growth
  event), then end. No summarizing, no other work.
- **Control (private):** identical scaffold and an equivalently-sized task prompt
  (it is handed the same 16 paths as text) but is told **not to read anything** —
  just reply "done". This cancels system + tools + the path-list prose.

**Signal — "tokens that entered context" = `input + cache_creation`** (from
`token_metrics.py --json`, which reports per-subagent `{input, cache_read,
cache_creation, output}` and dedupes by `message.id`). I deliberately **exclude
`cache_read`**: cached content is re-billed on every subsequent turn and would
multiplicatively inflate a naive total. `cache_creation` counts each unique block's
**first** entry into context exactly once — precisely the "unique content the model
had to ingest" quantity I want.

**Accounting:**

```
measured_file_tokens  =  (reader.input + reader.cache_creation)
                       −  (control.input + control.cache_creation)
```

The residual after the subtraction is the Read **tool-call framing** (tool_use +
tool_result JSON wrappers, ~tens of tokens per file). It *inflates* `measured`, which
*deflates* empirical chars/token — i.e. it biases the result conservatively toward
"heuristic undercounts". I will (a) report the raw delta, (b) estimate framing as a
per-file constant and report the framing-corrected figure, and (c) report the
sensitivity so the verdict does not hinge on the framing estimate.

## Step 4 — The comparison metric

The headline number is the corpus's **empirical chars-per-token** vs the heuristic's
assumed 4.0:

```
empirical_cpt   =  total_chars (79,881)  /  measured_file_tokens
bias_ratio      =  measured_file_tokens  /  group.estimated_tokens   ( = 4.0 / empirical_cpt )
```

- `bias_ratio ≈ 1.0` → heuristic accurate.
- `empirical_cpt < 4.0` (`bias_ratio > 1`) → len/4 **undercounts** (real tokenizer denser).
- `empirical_cpt > 4.0` (`bias_ratio < 1`) → len/4 **overcounts**.

## Step 5 — Tuning decision & threshold

- **Within tolerance — `bias_ratio ∈ [0.80, 1.25]` (|bias| ≤ 25%): NO code change.**
  Ship `calibration.md` only. Close with a cleanup commit.
- **Materially off — `bias_ratio` outside [0.80, 1.25] AND the bias is systematic:**
  propose and apply a tuning to `_estimate_tokens` — e.g. a recalibrated divisor
  (`len/empirical_cpt`, rounded to a clean constant) — with unit tests updated and
  six-artifact alignment kept green. A code/prose split is **not** proposable from
  this corpus (no source measured), so any tuning stays a single prose-calibrated
  divisor.
- **Systematic-bias guard:** one group yields one aggregate ratio. If the primary
  ratio lands **near a threshold boundary** (within ~5 points of 0.80 or 1.25), I
  measure a **second group** (the 2-subject group, est ≈ 19,989) as corroboration
  before declaring the bias systematic. If it lands clearly inside or clearly
  outside, one group suffices (the 16-file, ~80KB sample is already well-averaged).
- **HARD ESCALATION (C.O. ruling):** if the only accurate fix requires a **new
  dependency** (a real tokenizer like `tiktoken`), I do **NOT** add it — I stop and
  escalate. The no-tokenizer choice is the operator's to reverse. A divisor
  recalibration needs no dependency and is in-scope.

## Deliverable

`plans/modifications/168_cxt_groups_calibration/calibration.md`: the forced grouping
(params + group table), the measured-vs-estimated numbers (both raw and
framing-corrected, with the paired-control figures), empirical chars/token, the
accuracy verdict, and the tuning decision with rationale + the source-code
limitation.

## If a code change lands (test discipline)

Full suite: unit (`python -m pytest tests`) then integration (`python -m pytest
tests -m integration`) as **separate** invocations from `docex/`. Known
non-deterministic docker-sandbox flakes in `*_real.py` compose-bringup tests are
unrelated to docs tooling — if hit, I confirm no docs-tooling symbol/file is
involved, don't chase them, and report which failed. Six-artifact alignment kept
green (a `_estimate_tokens` divisor change touches only `linkmap.py` + its unit
tests; `subcommand_surface.md`/`docex.md` describe the *verbs*, not the divisor, so
likely n/a — I'll confirm during review).

## Open questions for C.O. (method review)

None blocking; four items to vet before I execute:

1. **Group choice** — measuring the **12-subject / 16-file / est-19,973** clump at
   `tokens_max = 20,000`. Representative multi-subject, non-oversize group. OK, or
   would you prefer a different group / `tokens_max`?
2. **Fixed-overhead isolation** — the **paired reader/control, same `subagent_type`,
   `input + cache_creation` (cache_read excluded)** signal. This is the crux of "file
   tokens vs fixed overhead". Endorse, or want a different isolation (e.g. read the
   transcript's per-turn deltas directly)?
3. **Threshold** — `bias_ratio ∈ [0.80, 1.25]` → no change (matches your ~25%). Good?
4. **Prose-only scope** — this corpus has no source nodes, so the calibration
   measures **markdown/prose density only**; source-code density is recorded as a
   limitation, not measured. Acceptable for SC5, or do you want source pulled in
   some other way (it can't come from docex's own `src/` without a `core/<cb>/src`
   layout)?

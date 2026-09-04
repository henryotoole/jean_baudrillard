# Mod 168 — Implementation / Execution Procedure

This mod is an **empirical calibration**. "Implementation" here means running the
measurement, writing `calibration.md`, and applying a divisor tuning **only if
warranted**. The measurement is driven by the **corporal directly** (it spawns
reader/control subagents — a mod-implementor private cannot spawn subagents).

All grouping is produced by driving mod-167's pure functions against an explicit
project root (no `project.yml` / CLI needed). Estimator under test:
`src/docex/docs/linkmap.py::_estimate_tokens` = `max(1, round(len(text)/4))`.

## The two measurement targets (pre-computed, deterministic)

### PRIMARY — docex prose group (SC5's literal target)

- Root `/home/ubuntu/.claude/jean_baudrillard/docex`, codebases `["docex"]`.
- `build_context_groups(nodes, edges, all_design_fpaths, tokens_max=20000)` → 8
  groups; measure the **12-subject / 16-unique-file** group, `estimated_tokens =
  19,973`, **79,881 chars** total over the unique file set.
- 16 files (12 subjects + 4 shared overhead) — full list in `overview.md` table.
- Max file 247 lines (< Read's 2000 default → full content per Read).

### SECONDARY — fixed test-project source group (source-density data point)

- Root `/home/ubuntu/.claude/jean_baudrillard/docex/test_projects/fixed`, codebases
  `["api"]`. This project HAS `project.yml` and 77 tracked `core/api/src` source
  nodes, 0 design nodes → a group there is **100% `.py` content, zero prose
  overhead**.
- `build_context_groups(nodes, edges, all_source_fpaths, tokens_max=8000)` → the
  **6-real-`.py`-file** group, `estimated_tokens = 6,748`, **26,993 chars**, 0
  overhead. Files:
  - `core/api/src/entrypoints/clock.py`
  - `core/api/src/hex/jobs/adapters/driven/gwy_job_runner_http.py`
  - `core/api/src/hex/jobs/adapters/driven/queue_jobs_postgres.py`
  - `core/api/src/hex/jobs/adapters/driving/cont_job_runner_http.py`
  - `core/api/src/hex/jobs/adapters/driving/cont_jobs_http.py`
  - `core/api/src/hex/jobs/alogic/job_runner_service.py`
- Max file 216 lines (< 2000 → full content per Read).

## Measurement procedure (per target)

**Paired reader/control**, both the **same `subagent_type`** (fixed overhead —
system prompt + tool defs — cancels on subtraction):

1. **Reader** private: sole job is to Read every file in the target's unique set (by
   absolute path), full content, no offset/limit, no other tool use, no exploration,
   no content summarizing. Batch the Reads. Then stop.
2. **Control** private: identical prompt scaffold and the same path list, but
   instructed **not to read anything** — reply `done`. Cancels system + tools + the
   path-list prose.

Then, from this session:

3. `python3 <transcript-summary skill>/executor/token_metrics.py <this-session-id>
   --json`.
4. For each subagent, take **`entered = tokens.input + tokens.cache_creation`**
   (exclude `cache_read` — cached blocks are re-billed every turn and would
   multiplicatively inflate).
5. `measured_file_tokens = reader.entered − control.entered`.
6. Report **raw** measured, a **framing-corrected** measured (subtract an estimated
   per-file Read tool_use+tool_result wrapper constant × N files), and the
   **sensitivity** of the verdict to that framing estimate.

## Metrics & verdict

```
empirical_cpt = total_chars / measured_file_tokens
bias_ratio    = measured_file_tokens / group.estimated_tokens   ( = 4.0 / empirical_cpt )
```

- PRIMARY (prose): `total_chars = 79,881`, `estimated = 19,973`.
- SECONDARY (source): `total_chars = 26,993`, `estimated = 6,748`.

**Tuning decision (threshold ±25%):**

- Both `bias_ratio ∈ [0.80, 1.25]` → **NO code change**; ship `calibration.md` only.
- A `bias_ratio` outside [0.80, 1.25] AND systematic → tuning warranted. If prose and
  source cpt **agree**, a single recalibrated divisor is the corporal's call within
  threshold logic. If they **diverge materially**, that is evidence for a
  **code-vs-prose split** in `_estimate_tokens` (linkmap already types nodes
  source/design, so a split is trivially applicable) — **propose to C.O., do not
  auto-apply**.
- **HARD ESCALATION:** if the only accurate fix needs a new dependency (a real
  tokenizer) → STOP and escalate. Do not add one.

## If a tuning code change lands

- Edit `src/docex/docs/linkmap.py::_estimate_tokens` (divisor, or a source/design
  split keyed off the already-known node type — note: `_estimate_tokens` currently
  takes only `text`; a split needs the node type threaded in).
- Update `tests/unit/test_docs_linkmap.py` (the `_estimate_tokens` / tokens
  assertions).
- Six-artifact alignment: the divisor is an internal heuristic constant, not part of
  the documented command surface — `subcommand_surface.md` / `doctrine/.../docex.md`
  describe the verbs, not the divisor, so likely **n/a**; confirm during review.
  `tables/roles/*`, `doctrine_excerpts/*` untouched (no infra resource).
- Full suite from `docex/`: `python -m pytest tests` then `python -m pytest tests -m
  integration` as **separate** invocations. Known docker-sandbox flakes in `*_real.py`
  compose-bringup tests are unrelated to docs tooling — confirm no docs-tooling
  symbol/file is involved, don't chase, report which failed.

## Deliverable

`calibration.md` in this folder: forced grouping (params + group tables for both
targets), the paired-control measurement figures (raw + framing-corrected +
sensitivity), prose cpt and source cpt, the accuracy verdict, the tuning decision +
rationale, and the two recorded limitations:
1. **Prose vs. source scope** — primary measures prose; secondary adds the source
   data point.
2. **`changed`-in-a-subfolder** — `diff_names` returns repo-root-relative paths that
   miss the project-relative allowlist when project root ≠ git root (docex is a
   subfolder of the jean_baudrillard repo); harmless when the two coincide. Recorded
   as a documented limitation only — NOT fixed here (mod-167 territory; C.O. decides
   on a follow-up).

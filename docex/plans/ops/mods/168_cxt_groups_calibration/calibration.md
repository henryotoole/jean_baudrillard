# Mod 168 — `cxt_groups` token-estimate calibration report

## Summary / verdict

The `linkmap`/`cxt_groups` per-file token estimator (`_estimate_tokens =
max(1, round(len(text)/4))`) **materially undercounts** real token cost. Measured
against docex's own corpus with real, transcript-measured token counts:

| content | intrinsic bias (meas/est) | as-read bias (meas/est) |
| ------- | ------------------------: | ----------------------: |
| prose (design docs) | **1.65×** | **1.87×** |
| Python source | **1.71×** | **1.98×** |

Both far exceed the ±25% tuning threshold, and prose and source **agree** (no
material divergence), so the fix is a **single divisor recalibration** — not a
code-vs-prose split. **Applied: divisor `4 → 2.4`** (the char-weighted empirical
intrinsic density). No tokenizer dependency added (the operator ruling stands).

## Method

**Estimator under test:** `src/docex/docs/linkmap.py::_estimate_tokens`, a flat
4-chars-per-token heuristic feeding every `Node.tokens` and thus every
`cxt_groups` `estimated_tokens`.

**Grouping driver:** docex has no `project.yml`, so mod-167's root-parameterized
pure functions were driven directly (`load_code_level_graph(<root>, <cbs>)` +
`build_context_groups`) from a throwaway script — no CLI project discovery.

**Real-token measurement — paired reader/control.** For each target, two `general-purpose`
subagents (identical `subagent_type` ⇒ identical fixed overhead — system prompt +
tool defs — which cancels on subtraction):
- **reader** reads every file in the group; **control** reads nothing (same path
  list handed to it as text, so the task-prompt size ≈ cancels too).
- Per subagent, the measured signal is **`entered = input + cache_creation`** from
  `token_metrics.py --json` (transcript-summary skill). `cache_read` is
  **excluded**: cached blocks are re-billed every turn and would multiplicatively
  inflate a naive total; `cache_creation` counts each unique block's *first* entry
  into context exactly once — the quantity we want.
- `measured = reader.entered − control.entered`.

**Two reader modes, to separate two effects:**
- **Read mode** (the Read tool) = **as-read cost**: includes the tool's `cat -n`
  line-number prefixes + per-file tool framing. This is the *operationally correct*
  target — `doc-refine` subagents ingest files via Read.
- **`cat` mode** (one Bash `cat`, no line numbers) = **intrinsic content cost**:
  near-raw text tokens, the property a `len/N` divisor structurally models.

**Measurement artifact caught & corrected:** a single `cat` of the 80 KB prose set
was **truncated by the Bash tool's output limit** (only 3,146 tokens entered — an
impossible 25 cpt), so that datum was **discarded** and the prose intrinsic was
re-measured by catting the 16 files in **4 sub-limit batches** (each < 25 KB). The
27 KB source `cat` fit under the limit in one call and is reliable.

## Targets

**PRIMARY — docex prose (SC5's literal target).** Root `docex`, cbs `["docex"]`.
Graph: 20 design nodes, **0 source nodes** (docex src is `src/docex/**`, not the
doctrine-standard `core/<cb>/src/**` that the scanner reads), 31 `neither` stubs.
Subjects = the 20 design nodes selected **directly** (see Limitation 1 for why the
`changed <ref>` path can't be used here). `build_context_groups(…, tokens_max=20000)`
→ 8 groups; measured the **12-subject / 16-unique-file** group,
`estimated_tokens = 19,973`, **79,881 chars**.

**SECONDARY — fixed test-project source (source-density data point).** Root
`docex/test_projects/fixed` (has `project.yml`), cbs `["api"]`. Graph: 0 design, 77
source nodes ⇒ a group there is **100% `.py`, zero prose overhead**.
`build_context_groups(…, tokens_max=8000)` → measured the **6-real-`.py`-file**
group (no `__init__` stubs), `estimated_tokens = 6,748`, **26,993 chars**.

All files < 250 lines ⇒ Read returns each in full (no per-file truncation).

## Raw measurements (per-subagent `entered = input + cache_creation`)

| subagent | entered |
| -------- | ------: |
| PRIMARY control (reads nothing) | 43,977 |
| PRIMARY reader — Read (16 files) | 81,307 |
| PRIMARY reader — cat, 4 batches | 76,846 |
| PRIMARY reader — cat, 1 call (**TRUNCATED, discarded**) | 47,123 |
| SECONDARY control (reads nothing) | 43,651 |
| SECONDARY reader — Read (6 files) | 57,038 |
| SECONDARY reader — cat, 1 call | 55,200 |

## Results

**PRIMARY (prose) — 79,881 chars, estimate 19,973:**
- as-read (Read): `81,307 − 43,977 = ` **37,330 tok** → **2.140 cpt** → bias **1.87×**
- intrinsic (cat×4): `76,846 − 43,977 = ` **32,869 tok** → **2.430 cpt** → bias **1.65×**
- Read decoration = `37,330 − 32,869 = ` 4,461 tok (1,173 lines ⇒ ~3.8 tok/line incl. 16 file framings)

**SECONDARY (source) — 26,993 chars, estimate 6,748:**
- as-read (Read): `57,038 − 43,651 = ` **13,387 tok** → **2.016 cpt** → bias **1.98×**
- intrinsic (cat): `55,200 − 43,651 = ` **11,549 tok** → **2.337 cpt** → bias **1.71×**
- Read decoration = `13,387 − 11,549 = ` 1,838 tok (657 lines ⇒ ~2.8 tok/line incl. 6 file framings)

**Interpretation.**
- The `~4 chars/token` rule of thumb holds for *English prose*; this content is
  technical markdown (paths, symbols, tables, mermaid) and Python (identifiers,
  punctuation), which tokenizes far denser — **~2.34–2.43 chars/token** intrinsic.
- Prose and source intrinsic densities are **within ~4%** of each other (2.43 vs
  2.34) — the undercount is a **content-density** effect common to both, **not** a
  prose-vs-code divergence. A single divisor is therefore correct; a code/prose
  split is **not** warranted by the data.
- The Read tool adds a further per-line decoration (line numbers + framing), which
  pushes the *as-read* bias to ~1.9×. This is **per-line**, so a char-based divisor
  cannot model it precisely; it is left as consumer-side margin (see Limitation 2).

## Tuning decision

**Warranted** (bias 1.65–1.98× ≫ 1.25 threshold; systematic; no divergence).
**Applied — single divisor `4 → 2.4`** in `_estimate_tokens`, via a named
`_CHARS_PER_TOKEN = 2.4` constant with a WHY comment citing this report. 2.4 is the
char-weighted intrinsic density across both corpora:
`(79,881 + 26,993) / (32,869 + 11,549) = 106,874 / 44,418 = 2.406`.

**Why intrinsic (2.4) rather than as-read (~2.1):** `_estimate_tokens` is a generic
"context cost of *text*" estimator (its output `Node.tokens` is consumed by more than
just doc-refine budgeting); the Read line-number decoration is an artifact of *one*
ingestion path, is per-line (not char-modelable), and is only ~12–14% of the
as-read cost. Calibrating to the text's own density is the principled, path-neutral
choice. It cuts the worst-case undercount from ~1.9× to ~1.15× (well inside the
"`tokens_max` is not exact" contract), where the old value overshot budgets by ~90%.

**No dependency added** — pure arithmetic, no tokenizer. (Had an accurate fix
required `tiktoken`, this mod would have escalated instead of adding it.)

## Changes shipped

- `src/docex/docs/linkmap.py` — `_CHARS_PER_TOKEN = 2.4` + recalibrated
  `_estimate_tokens`; docstring updated.
- `tests/unit/test_docs_linkmap.py` — `test_tokens_heuristic` divisor 4→2.4.
- `tests/unit/test_docs_cxt_groups.py` — `_big(n)` helper made divisor-aware
  (`round(2.4*n)`, preserving every threshold's intent) + formula comment.

**Six-artifact alignment:** the divisor value is documented *nowhere* outside the
code — `doctrine/infrastructure/docex.md § docs` and
`plans/design/specifics/subcommand_surface.md` describe `tokens` as "an estimated
read cost" (still accurate; no edit). `tables/roles/*`, `doctrine_excerpts/*` — n/a
(no infrastructural resource). Only `src/` + `tests/` change.

## Limitations

1. **`changed <ref>` in a subfolder repo.** docex is a *subfolder* of the
   `jean_baudrillard` git repo, so `changed`'s `diff_names` returns
   **repo-root-relative** paths (`docex/plans/design/…`) that miss the
   *project-relative* allowlist (`plans/design/…`) — empirically
   `changed_fpaths(<docex root>, ["docex"], "1fb9f5c")` returns **0** subjects even
   though mod 166 added all 20 design files. Harmless for a normal project where
   project root == git root. Recorded here as a documented limitation; **not fixed**
   in this mod (mod-167 territory — C.O. to decide on a follow-up).
2. **As-read vs intrinsic margin.** The shipped divisor tracks *intrinsic* text
   density; a doc-refine subagent reading via Read pays a further ~12–14%
   (line-number + framing), which is per-line and left as consumer margin. Given
   `tokens_max` is explicitly non-exact, this residual is acceptable.
3. **Scope.** One representative group per content type (well-averaged: 16 files /
   ~80 KB prose; 6 files / ~27 KB source). docex's own corpus has no source nodes,
   so the source data point necessarily came from the fixed test project.

# doc-coherer — run history

Append-only log of past runs' aggregate scores, referenced by
[`test.md`](./test.md). A single run is a **non-deterministic sample** (see
test.md § Philosophy), so a "good" score is the *distribution* of these rows over
time — not any one row, and never an all-pass expectation. Read the **trend** in
recall (PASS/In) and the **precision guards** (Bdry, Uncat).

Add a row after every graded run: `scripts/record_run.py <results_dir> --append`
(then fill the Notes cell by hand).

## Column legend

| Column | Meaning |
| ------ | ------- |
| Date | Run date. |
| Ref | Agent-under-test identity — this repo's short SHA (`+dirty` if the working tree had uncommitted changes). |
| Groups | Group indices run (`cg` = clean-guard). |
| tok_max | `cxt_groups` token budget the group fixture was packed at. |
| In | In-scope inventory entries, summed across groups. |
| PASS / FAIL | Auto-graded `fix`/`defer` outcomes by signature. **FAIL is a data point, not a regression** (test.md § Philosophy). |
| JUDGE | `NEEDS_JUDGE` entries — hand-reviewed, never auto-failed. |
| Det | Entries the agent's report *mentioned* (detection), independent of outcome. A FAIL with high Det = found-but-didn't-finish; low Det = genuine miss. |
| Bdry | `boundary_conditions.md` edits — **hard violation, must be 0.** |
| Uncat | Uncataloged design-doc changes — false-positive candidates (triage each). |
| srcΔ | Source files touched — judge docstring-only (allowed) vs real source (forbidden). |
| Notes | Grader version, anomalies, triage outcomes, context. Record any grader/inventory change here so trend breaks are explained. |

## Runs

| Date | Ref | Groups | tok_max | In | PASS | FAIL | JUDGE | Det | Bdry | Uncat | srcΔ | Notes |
| ---- | --- | ------ | ------- | -- | ---- | ---- | ----- | --- | ---- | ----- | ---- | ----- |
| 2026-09-30 | 5fadb0d+dirty | 0,2,5,7,11,clean-guard | 400000 | 41 | 9 | 22 | 10 | 18 | 0 | 0 | 7 | grader: exact (pre-whitespace); +1 PASS/-1 FAIL in grp0 (web-flatten wrap) under current ws-tolerant grader. All srcΔ verified docstring-only. |

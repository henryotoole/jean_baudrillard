# Outcome eval: `project-cohere`

`project-cohere` reads a project's core planning docs (`plans/core/`) against the
actual code and heals drift. That makes it an odd skill to outcome-eval: its
**input is a whole doctrine project in a specific drift state**, and its
**output is a diff** against that project's docs — including the *empty* diff,
which is the correct result when the project is already coherent. The generic
outcome pattern (prompt → produced file content → grade) doesn't fit, so this
folder carries a fixture harness on top of the standard `evals.json` + grader.

## Layout

```
evals.json          one case per state: prompt + `fixture` (state name) + diff-expectations
run_fixture.py      assemble (base + overlay → scratch git repo) and capture (diff vs baseline)
fixtures/
  _base/            ONE small, coherent doctrine project (service `web`, module `links`)
  states/<state>/overlay/   only the files that differ for that state (mirrors project root)
```

State storage is **base + per-state overlay**, never full copies, so every state
is provably `_base + exactly one intended drift`. That isolation is the whole
point — each state exercises one of the skill's finding cases in isolation.

The overlay dir mirrors the project root: each file in it replaces/adds the same
relative path in the assembled tree. An optional `DELETE` manifest at the overlay
root lists paths to remove. The `coherent` overlay is empty (just `.gitkeep`).

### States

`_base` is a small coherent project: a `web` service with two documented hex
modules, `links` (shorten/resolve) and `analytics` (total-click counting).

| State | Injected drift | Skill case | Correct result |
| ----- | -------------- | ---------- | -------------- |
| `coherent` | none | — | **empty diff** — the conservative no-op |
| `code-mismatch` | `links.md` claims 6-char codes and a raising `resolve`; code does 7 chars / returns `None` | Case 2 | doc edited to match code; source untouched |
| `unimplemented` | `links.md` describes a custom-alias feature with no code | Case 1 | alias section **marked unimplemented, not deleted**; no code written |
| `doc-doc-conflict` | `analytics.md` says "unique visitors"; masterplan + code say total clicks | Case 3 | conflict broken toward the code-backed side — `analytics.md` bent, masterplan untouched |
| `undocumented-module` | `analytics` exists in code but its doc is deleted and it's absent from the masterplan | Case 4 | **defer to operator** — no doc invented; the gap surfaced, nothing changed |
| `masterplan-drift` | `masterplan.md` (highest doc) claims a 301 redirect; code returns 302 | Source-of-truth rules | **stop and ask** — masterplan left unchanged, discrepancy raised |

The last two are **deferral** cases: the doctrine-correct behavior is to change
nothing and surface a judgment call to the operator. Because a headless run has no
interactive question tool (verified — `AskUserQuestion` is not offered in `claude -p`),
that deferral appears only as final-report text. So an empty diff is **necessary but
not sufficient** — `run_outcome.py` captures the run's tool-call trace and final
report and hands both to the grader, whose expectations demand *positive evidence*
(the run named the specific gap AND its trace shows it inspected the relevant code).
An agent that never noticed the issue leaves the same empty diff but fails on that
evidence. New states drop in as `states/<name>/overlay/` dirs (add files to overlay,
or list paths in a `DELETE` manifest to remove them) plus an `evals.json` case.

## Running — one command

`run_outcome.py` runs the whole loop for you: for each case and each configuration
it assembles a scratch repo, runs a headless `claude -p` to cohere it, captures the
diff, grades it with another headless `claude -p` (the shared `../../agents/grader.md`),
and prints the with-skill vs baseline delta-driver gap — the skill's measured value.

### Token / cost per run

Each cohere run is metered two ways (the grader run is never metered):

- **`cost_usd`** — the harness's own `total_cost_usd` off the terminal `result` event.
  The authoritative dollar figure; it bills the full run including subagents.
- **`total_tokens`** — the **true** billed-token count, computed by summing per-turn
  `usage` across the run's main transcript **and every subagent transcript** it spawned
  (`<projects>/<dir>/<session_id>/subagents/agent-*.jsonl`), located by `session_id`.
  Each record also splits out `main_tokens`, `subagent_tokens`, and `n_subagents`.

> **Why not just use the `result` event's `usage`?** That field is a final-turn
> *snapshot* — it misses both the per-turn accumulation (each turn re-reads its context)
> and *all* subagent work, undercounting real consumption ~4×. It is kept per-record as
> `final_ctx_snapshot` for reference only; **do not** use it as a consumption figure.
> `project-cohere` fans out to subagents that routinely account for ~20–35% of a
> with-skill run, so summing the transcripts is the only honest total.

These surface in each `done …` line (`… 2540k tok, 480k in 1 sub, $2.6`), per-config in
the summary (`2540k tok/run (19% subagent)  $2.6/run`), and as a `COST` line giving the
with-skill-vs-baseline overhead — the price of the delta-driver value above it.

```bash
cd skill_iter/eval/outcome/project-cohere
python3 run_outcome.py --runs 3                        # full suite, 3 runs/config
python3 run_outcome.py --state unimplemented --runs 1  # one case, smoke
python3 run_outcome.py --state coherent --configs with_skill --runs 1
```

Grading needs an LLM but **not** an interactive agent: both LLM steps are `claude -p`
subprocesses, the same mechanism the trigger runners (`run_eval.py` / `run_suite.py`)
use. Runs execute with `--permission-mode bypassPermissions` inside a throwaway
scratch repo created **outside** this repository, so the model edits fixture docs
without prompts and never touches the doctrine repo. `--runs N` matters: the skill is
nondeterministic (it may occasionally over-edit an already-coherent project), so the
pass *rate* over N runs is the real signal, not a single run. Flags: `--model`,
`--skill-path`, `--run-timeout`, `--grade-timeout`, `--out <results.json>`.

## Running — by hand (what the wrapper does under the hood)

The same loop, step by step — useful for debugging one stage or grading a run you
drove manually. `run_fixture.py` does the deterministic scaffolding (assemble /
capture); the skill run and grading happen in between and reuse `../../agents/grader.md`.

Run for **each** case in `evals.json`, in **both** configurations (`with-skill`
and `baseline`). The delta-driver pass gap between the two is the skill's measured
value. All paths below are relative to the repo root (`$jb`).

### Per case, per configuration

**1. Assemble a fresh scratch repo for the state.** Use a *separate* scratch dir
per configuration so the two runs don't collide. The scratch repo is created
OUTSIDE this repository so its inner `.git` never entangles the doctrine repo.

```bash
python3 skill_iter/eval/outcome/project-cohere/run_fixture.py \
  assemble --state <state> --out /tmp/cohere-<state>-<config> --force
```

The `<state>` is the case's `fixture` field. Note the printed `scratch` path and
`baseline_commit`.

**2. Run the skill (or baseline) in that scratch dir via a subagent.** Spawn a
subagent whose working directory is the scratch dir and that is told to operate
*only* inside it. Prompts:

- **with-skill:** "Read `skills/project-cohere/SKILL.md` and follow its process
  exactly to cohere this project's core planning docs. Operate only inside
  `<scratch>`." (The skill resolves its own `executor/word_count.py` by the
  skill-relative path in its SKILL.md — no path fix-ups needed.)
- **baseline:** "Make the core planning docs under `plans/core/` internally
  consistent and consistent with the code under `core/`. Work only from general
  software-engineering knowledge — do NOT read any skill or doctrine files.
  Operate only inside `<scratch>`."

Save the subagent's final report as the run transcript (e.g. `<scratch>.transcript.md`).

**3. Capture the diff** the run produced against the fixture baseline. This works
whether the run left changes uncommitted or committed them.

```bash
python3 skill_iter/eval/outcome/project-cohere/run_fixture.py \
  capture --dir /tmp/cohere-<state>-<config> --with-diff
```

**4. Grade the diff** against the case's `expectations` with `../../agents/grader.md`.
Mapping the generic grader onto this flavor: **the graded artifact is the captured
diff, not files in an `outputs_dir`.** Hand the grader (a) the case's
`expectations`, (b) the run transcript from step 2, and (c) the `capture` output
(the `diff`, `files_changed`, and `is_empty` fields) as "the output." For the
`coherent` case the whole test is `is_empty == true`. Emit a `grading.json` per
`../../schemas.md`.

### Reading the result

Compare `with-skill` vs `baseline` grading per case. The **delta-driver** pass gap
is the headline. Expect ≈zero delta on inferable cases (e.g. `code-mismatch`) and
a real gap where the skill's discipline is non-obvious (`unimplemented`: mark vs
delete; `coherent`: no-op vs fiddle). Grade on the **diff**, not an exact expected
tree — "mark unimplemented" and "edit the doc to match code" have free wording, so
exact-match would be far too brittle.

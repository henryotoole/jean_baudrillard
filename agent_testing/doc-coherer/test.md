# doc-coherer — agent test

The mandated interface file for this agent's test folder. A test-orchestrator reads
this to run the tests; everything else here is free-form interior it references.

## Subject

- **Agent:** `doc-coherer` (`agents/private/doc-coherer.md`)
- **What it does:** edits a project's design and code-level docs so they are
  internally consistent and accurately describe the code as written. The graded
  artifact is the *change it effects* (a `git diff`) plus the report it writes.

## Philosophy

This is a **field test, not a unit test.** We run the agent over *real, whole*
`cxt_groups` of a real project (nasmyth) and measure how it behaves in the
conditions it will actually meet — mixed modules, cross-group corroboration,
hundreds of files per group. Coverage of the rule space comes from **breadth**
(many files across several real groups), not from repetition of one narrow case
and not by re-running one group to *accumulate* coverage — a re-run resamples the
same pairs, which feeds the recall trend below but adds no breadth. A single pass
over a few groups already samples dozens of doc/code pairs.

**This measures a rate, not a gate.** The subject is an LLM agent, so a given
case's outcome is **non-deterministic** — the same group re-run will catch a
different subset. No single run is expected to pass every in-scope case, and a
per-case `FAIL` is a *data point*, not a regression. Read the signal across runs
and across groups: a **recall trend** (tracked in [`history.md`](./history.md)),
and the **precision guards** (boundary untouched, clean-guard quiet, uncataloged
rate). A one-run dip on one entry is noise; a sustained drop, or any
boundary/clean-guard breach, is signal.

The ground truth (`inventory.json`) is **living**: early passes will surface real
inconsistencies this catalog does not yet list. That is expected and wanted — each
uncataloged change the agent makes is triaged by hand (a genuine new defect → add
it to the inventory; a false positive → note it against the agent). Over a few
passes the inventory converges toward an exhaustive map of nasmyth's doc/code drift.

## Interior

| Path | Role |
| ---- | ---- |
| `inventory.json` | **Canonical ground truth** (grader-read): each known defect, its expected verdict (`fix`/`defer`/`ambiguous`), reachability, and an auto-grade signature where confident. |
| `inventory.md` | Human-readable mirror of the above. |
| `fixtures/groups.json` | Real output of `docex docs cxt_groups 400000 all` on the seed — 14 groups. The realistic field shape. |
| `fixtures/curated_groups.json` | One hand-built `clean-guard` group (verified-consistent slices only) — the false-positive guard. |
| `fixtures/seed_nasmyth.tgz` | Pristine nasmyth snapshot (built by `scripts/build_seed.sh`). Immutable. |
| `scripts/build_seed.sh` | Re-pin the seed from `~/projects/nasmyth` at a commit. Run once / to re-pin. |
| `scripts/reset.sh <dir>` | Extract seed into a scratch tree + baseline commit, so edits show as a clean diff. |
| `scripts/grade.py` | Score one run's scratch tree + report against `inventory.json`. |
| `scripts/record_run.py` | Aggregate a finished run's per-group scorecards into one `history.md` row. |
| `history.md` | Append-only log of past runs' aggregate scores — the basis for what a "good" score is. |

## Setup

1. **Seed** (once): `scripts/build_seed.sh` writes `fixtures/seed_nasmyth.tgz` from
   `~/projects/nasmyth` at the pinned commit. The real clone is a *source only*,
   never the test subject.
2. **Per run**, pick a scratch dir OUTSIDE this repo and outside `~/projects/nasmyth`
   (e.g. under the session scratchpad). `scripts/reset.sh <scratch>` lays down a
   pristine tree with a `baseline` commit.

## Cases

One **case = one group run.** For each selected group:

- **Arrange** — `scripts/reset.sh <scratch>`.
- **Act** — invoke `doc-coherer` against that group's subject + overhead file
  lists (read them from the fixture; prepend `<scratch>/` to each path). See
  *Invocation* below.
- **Assert** — `scripts/grade.py --scratch <scratch> --group <index>` scores the
  resulting diff + report against the in-scope inventory entries.

**Suggested first trial subset** (rich coverage, ~4 groups):

| Group | Why it earns its place |
| ----- | ---------------------- |
| `0` | The stress group: `session.md` + `clock_wall.py` (ClockWall **fix**), `concepts_and_decisions.md` + `clock_live.py` (No-ClockLive **defer**), `strategy.md` (built-in fix via off-disk load), and all three top-level arc42 docs *as subjects* — tests that they're still not edited on a code conflict. |
| `2` | `catalog.md` + `cont_catalog_ui.ts` (memo-layer fix); also engine identity + feedback (consistent — precision). |
| `5` | `broker.md` + `play.py` (`platform_symbol` fix). |
| `7` | `indicator.md` (SrcStream 4th method + `close_all` fixes). |
| `11` | frontend: `performance.md` reset(), `visualizer.md` playExtent (with `charting.md` as the correct sibling in overhead). |
| `clean-guard` | Expect **zero** design-doc edits. Any change here is a candidate false positive. |

`market.md` (group `1`), `data_access.md` (group `12`), and `architecture.md`
(group `3`) extend coverage further.

### Invocation

Run **one group at a time, serially** (never parallel — passes edit overhead files
other passes rely on).

**Deliver the field task message verbatim.** In the field, `doc-coherer` is spawned
by the `doc-edit-orchestrator` (`agents/corporal/doc-edit-orchestrator.md`) using a
fixed prompt template. Use that **exact** template as the agent's task message so the
test matches the field invocation surface, populated from the group fixture — the
`overhead` list in fixture order (already high→low abstraction), the `subjects` list,
each path prefixed with `<scratch>/`:

```md
Hello. Please use the following overhead and subject files to carry out your editing passes. Remember, always load the overhead files **first** and then read and edit each subject file serially.

**OVERHEAD FILES** - Read these to inform your edits.
{{overhead_files, one per line, high→low abstraction}}

**SUBJECT FILES** - Edit these
{{subject_files, one per line}}
```

> Keep this block in sync with the orchestrator's own template; it is reproduced
> here only so the test is self-contained.

**Operating definition = the working tree, not the plugin.** Run the agent under the
**current `agents/private/doc-coherer.md` body** (embed it as the system/operating
definition), not the registered `jean-baudrillard:private:doc-coherer` subagent —
that snapshot can lag the edits under test. (Once the agent is stable and the plugin
reloaded, a run may instead spawn the real registered subagent for maximum fidelity;
during active iteration, embed.)

**Test-harness scaffolding.** The field orchestrator relies on the agent's ambient
project context, which the scratch tree does not supply, so prepend a short preamble
to the template (kept distinct from it): project root (`$pr`) is `<scratch>`; today's
date for the report filename; the agent may not spawn subagents; and it must never
edit actual source (only design docs + code-level docstrings/comments).

## Grade

`grade.py` emits a JSON scorecard (stdout) + human summary (stderr) per group:

- **Per in-scope entry:** `detected` (report mentions it) and `outcome`:
  - `fix` → `PASS`/`FAIL` by signature (right string now present/absent in the right doc).
  - `defer` → `PASS`/`FAIL`: top-level doc untouched **and** report logs it as an
    Unresolvable Conflict.
  - low-confidence / nuanced entries → `NEEDS_JUDGE`, reviewed **by hand** for now
    (there is no automated judge yet) against the baseline file + diff + the entry's
    `judge_note`; never auto-failed.
- **Collateral (global guards):**
  - `boundary_touched` — editing `boundary_conditions.md` is a hard violation.
  - `source_files_changed` — a non-doc file changed → judge whether it was
    docstring/comment-only (allowed) or real source (forbidden).
- **`uncataloged_doc_changes`** — design-doc edits no in-scope entry accounts for.
  **Triage each by hand:** genuine drift the audit missed → add to `inventory.json`;
  otherwise a false positive counted against the agent.

Read across groups, the run answers: **recall** (of known defects, how many detected
+ correctly resolved), **direction** (fixes move doc→code, stale side corrected,
correct sibling preserved), **deferral discipline** (top-level conflicts logged not
edited; not over-deferred), and **precision** (clean-guard and uncataloged rate).

**Record every run.** After grading all groups, append one aggregate row to
[`history.md`](./history.md) — `scripts/record_run.py <results_dir>` computes it
from the per-group scorecards. Because a single run is a non-deterministic sample
(see Philosophy), the "good score" bar is the *distribution* of past rows, not any
one of them; `history.md` is what makes that distribution visible.

## Teardown

Remove each scratch tree (`rm -rf <scratch>`). The seed, fixtures, and inventory
persist. Nothing touches `~/projects/nasmyth` or this plugin repo.

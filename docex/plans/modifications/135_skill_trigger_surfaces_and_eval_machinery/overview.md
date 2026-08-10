# Mod 135 — Skill Trigger Surfaces and Eval Machinery

## Goal

Advance 006 changed doctrine that four skills route into, and it changed two of those
skills' *bodies* without touching their **descriptions** — which are the entire trigger
interface. It also left the eval machinery that is supposed to catch exactly that pointing
at doctrine the advance deleted.

This mod closes two measured trigger holes, brings two stale outcome-eval cases to current
doctrine, removes two structural blindnesses from the query set, and resolves one dangling
reference. Subject is `skills/` and `skill_iter/eval/` — **no `docex/src` change, no doctrine
prose change.**

Every claim below was reproduced by a suite-level trigger eval run as this advance's
`RELEASING.md` gate: canonical set 54/56, supplementary 12/14, **precision 1.00 for every
skill in both runs**. The four changed doctrine-facing skills each scored full recall. The
surface is healthy; what follows are holes, not regressions.

> **AMENDED MID-CYCLE — read [The instrument was broken](#the-instrument-was-broken) before the
> scopes below.** The gate numbers in the paragraph above were measured with a confounded
> harness, and one of them is false. `precision 1.00 for every skill` does not hold: on a
> corrected harness `contracts` poaches `infra-compile` **5/5**. The scopes below are preserved
> as designed and approved; where the corrected measurement overruled them, the amendment says
> so and the amendment governs.

## Scope 1 — Two trigger descriptions

### 1a. `infra-compile` — the word "surface" never appears

The advance gave `infra-compile` the surfaces-**authoring** role in its `Thread` section
and never touched its description. Measured consequence: *"Where in `infra.yml` does the
`surfaces` block go, and what does declaring it change about compiled output?"* fires **no
skill at all** (0/5). `contracts` does not cover it either. The authoring half of this
advance's central new concept is unreachable.

**Before** (verbatim):

> Doctrine for authoring a project's infra.yml and the transfer tables that compile it into
> per-foundation infrastructure. Use this whenever you are writing or changing infra.yml,
> adding a service/role/engine, declaring the secrets or config a service requires (its
> `secrets:` / `config:` blocks), or extending docex with a project-local transfer table for
> an engine it doesn't ship — and whenever reasoning about how CICL compiles to
> docker-compose or OpenTofu, even if you never name CICL or transfer tables.

**After** (proposed):

> Doctrine for authoring a project's infra.yml and the transfer tables that compile it into
> per-foundation infrastructure. Use this whenever you are writing or changing infra.yml,
> adding a service/role/engine, declaring what a core service exposes or requires in its
> `surfaces:` / `uses:` / `secrets:` / `config:` blocks, or extending docex with a
> project-local transfer table for an engine it doesn't ship — and whenever reasoning about
> how CICL compiles to docker-compose or OpenTofu, even if you never name CICL or transfer
> tables.

**Why this shape, and why it should not poach `contracts`.** The edit folds `surfaces:` and
`uses:` into the *existing* block-declaration clause rather than adding a new sentence, so
the trigger stays anchored to the thing that is unambiguously `infra-compile`'s: **a block
in `infra.yml`**. The two skills' territories divide as their `Thread` sections already say
— `infra-compile` owns *where the block goes and what it compiles to*; `contracts` owns
*how to split surfaces, which format each resolves to, and what goes in the contract file*.
`contracts` keeps every word of its own surface vocabulary ("which API styles share a
surface", "writing a contract"). None of the three existing `contracts` queries mentions
`infra.yml`, so the expected poaching risk is low — but it is a risk, and it is measured,
not asserted (see Verification).

`uses:` is added in the same clause because it is the sibling half of the same advance-006
concept (a `uses` edge is only legal against a core service that declares a surface) and
because `uses:` likewise appears nowhere in any description today. **Its inclusion is
conditional on being measured** (approved on that condition): `uses:` gets its own
should-trigger query in the canonical set. If it fires, the coverage is real; if it does not,
that is a second hole and worth knowing. Unmeasured vocabulary in a durable artifact is a
guess, which is this advance's governing lesson.

### 1b. `contracts` — a phrasing-shaped hole, in the dangerous direction

*"Does my internal queue worker need to serve an http health endpoint, or is there another
way it proves it's alive?"* → **0/5**. Authoring-shaped health queries fire 5/5 and 3/3, so
the description works on **tasks** but not on this **diagnostic yes/no** form.

Two things make this worse than an ordinary miss:

1. The model's **unloaded** answer is "yes, expose `/health`", which is now *doctrine-wrong*
   (`healthchecks.md`: a non-`web`-network core service "needs no HTTP surface of any kind —
   a queue consumer built under this doctrine listens on nothing"), and it is delivered
   confidently.
2. The canonical set's surviving health query passes only because it contains the tell
   "web-network", which **masks** the hole.

**Before** (verbatim):

> Doctrine for defining core-service surfaces and their contracts — which API styles share a
> surface, the OpenAPI/AsyncAPI format each resolves to, and the health probe every core
> service owes. Use this whenever you are declaring or changing a service's surfaces, writing
> a contract, adding a provider/consumer relationship, or wiring health checks, even if the
> words "contract" or "surface" are never used.

**After** (proposed):

> Doctrine for defining core-service surfaces and their contracts — which API styles share a
> surface, the OpenAPI/AsyncAPI format each resolves to, and the health probe every core
> service owes. Use this whenever you are declaring or changing a service's surfaces, writing
> a contract, adding a provider/consumer relationship, or wiring health checks — including
> deciding whether a given core service needs an HTTP health endpoint at all, and how a
> service that owns a loop proves it is still alive — even if the words "contract" or
> "surface" are never used.

**Why this shape.** The failing form is a *policy* question ("do I need…", "is there another
way…"), and every verb in the old description is an *authoring* verb ("declaring",
"writing", "adding", "wiring"). The inserted clause supplies the two things the old
description lacked: the **decide-whether** framing, and the vocabulary the diagnostic form
actually uses — *HTTP health endpoint*, *owns a loop*, *proves it is still alive*. It states
the boundary as a question rather than as an answer, which is what lets it fire before the
model has committed to the wrong answer.

Deliberately **not** added: the words `health.sh`, `10s`/`30s`, `web`-network. The first two
are body content, not trigger content; the third is the very tell whose presence masks the
hole, so leaning on it would re-encode the blindness in the description.

### The bar

Both holes closed **and precision still 1.00 everywhere**. There is no headroom to lose. A
description that widens into a sibling's territory is a worse outcome than the hole — if a
hole cannot be closed without costing precision, the trade gets reported and the hole gets
left.

## Scope 2 — Two stale outcome-eval cases

Same defect class as a checklist box that fails against correct code. Run as written, both
gates can only report a false negative.

### How drivers were chosen

A driver the Resident stratum already supplies measures nothing — the baseline arm carries
the Resident stratum in its system prompt and cannot un-read it. Every driver below was
grepped against the 13 `stratum: resident` files. Results:

| Candidate | Resident hits | Verdict |
| --------- | ------------- | ------- |
| surfaces exist / declaring one makes a provider | `lexicon.md`, `infrastructure.md` §Contracts | **confirmatory** |
| five-segment `${codebase}.${service}.${surface}.${format}.${ext}` path | `infrastructure.md:262` | **confirmatory** |
| `rest`→openapi, `events`→asyncapi | `infrastructure.md:264-265` (worked examples) | **confirmatory** |
| `health.sh` exists, invoked `./health.sh <service>` | `infrastructure.md:199,247` | **confirmatory** |
| a loop must expose liveness via an externally observable tick | `internal_dependency_rules.md:42` | **confirmatory** |
| **10s tick cadence / 30s staleness threshold, doctrine-fixed** | 0 | **delta driver** |
| **`GET /health` only on `web`-network services; non-`web` listens on nothing** | 0 | **delta driver** |
| **`{"version": "x.x.x"}` body shape** | 0 | **delta driver** |
| **no service reports on another — no `/health/<dep>`, no dependency fan-out** | 0 | **delta driver** |
| **`health_check_path` has one consumer: elastic + `reverse_proxy: alb`** | 0 | **delta driver** |
| **staging tests do not assert liveness** | 0 | **delta driver** |

This matches what the gate run observed unaided: the baseline arm reproduced surfaces, the
five-segment path, and even the tick idea — but invented **60s** staleness as "my engineering
judgment", omitted `GET /health` from the web contract on principle, and licensed a deep
dependency-health endpoint. The drivers are placed exactly where the baseline goes wrong.

### 2a. `outcome/contracts/evals.json`

Both of its delta drivers are doctrine this advance **deleted**:

- `/health/worker` downstream fan-out — now explicitly forbidden (`healthchecks.md`: "No
  service reports on another. There is no proxying, no `/health/<codebase>/<service>`, no
  fan-out.").
- the path `infra/contracts/web.openapi.yml` — the path is now five-segment,
  `infra/contracts/api.web.rest.openapi.yml`.

A *correct* with-skill answer fails both. Rewrite:

- Keep case 1's prompt (web + worker, ask for `web`'s provider contract) with two edits: name
  the codebase `api` so the five-segment path is answerable, and declare the surface.
- Case 1's drivers become: `GET /health` **is** in the contract, with the `{"version":
  "x.x.x"}` body; the contract defines **no** endpoint reporting on the worker or on Postgres
  (negative driver — this is where the baseline actively goes wrong); `health_check_path`'s
  single consumer.
- Path and openapi-vs-asyncapi drop to **confirmatory** — they are Resident-supplied and the
  gate run measured ≈zero delta on them.
- **Add a case 2** covering the worker side: no HTTP surface at all, liveness from a loop tick
  at the fixed 10s/30s thresholds, `health.sh worker`. Justification for adding rather than
  only repairing: the non-inferable doctrine this advance shipped — loop-liveness thresholds,
  the no-fan-out rule, "a non-`web` core service listens on nothing" — has **no** outcome
  coverage otherwise, and it is precisely the part where a skill earns its keep. It is also
  the exact question the trigger hole in 1b makes unreachable, so the two halves of this mod
  measure the same doctrine from both ends.

### 2b. `outcome/testing/evals.json`

Its last expectation asserts as CONFIRMATORY that "staging tests include liveness/health-check
probes". Reversed by this advance (`cicd.md` §Staging Tests: "They do **not** assert liveness.
Every core service's health is read from the orchestrator before the tester runs").

Fix: invert it and **promote it to a delta driver** — a capable model naturally puts a health
probe in a staging suite, the doctrine forbids it, and the rule is absent from the Resident
stratum. The end-to-end smoke half of the old expectation survives as its own confirmatory
entry, restated in current terms (drive the public edge and observe the effect; a stage test
cannot reach a non-`web` core service at all).

Everything else in that case was re-verified against current doctrine and still holds
(`STAGING_URL`/`PROJECT_VERSION` injection, `infra/stage/*` paths, contract tests as a
service-tier concern).

## Scope 3 — Query-set blindness

### 3a. Unpin `competing_skills`

`queries.json` pins the set to 13 names, omitting `skill-iteration`, `cohere`,
`project-cohere`, `browser-investigate`, `chain-of-command`, and `transcript-summary`. The
suite therefore **cannot** score those six or detect poaching involving them. Deleting the
key makes `run_suite.py` auto-discover all 19 from `skills/*/SKILL.md`.

Deleting the key alone only half-fixes it: with no `expect`-labeled query, those six become
poach-*detectable* but still recall-*unscoreable*. So one substantive should-trigger query is
added for each. This is the natural completion of the same fix and the queries are durable
artifacts.

### 3b. Zero queries in this advance's vocabulary

The set contains no `surfaces`, no `api_styles`, no `health.sh`, nothing on staging tests
dropping liveness — and its `contracts` coverage is 3 against the methodology's own 8-10
target. Additions (final wording in `implementation.md`; all written per the methodology —
substantive, multi-step, realistic, with the boundary named in the `note`):

| expect | count | covers |
| ------ | ----- | ------ |
| `contracts` | +6 → 9 | the diagnostic yes/no form; `api_styles` combination into one surface; one-surface-vs-two-vs-two-core-services split; `health.sh` for a wedging loop; an `rpc` surface's format; whether a non-routed core service needs a `health_check_path` and what reads it |
| `infra-compile` | +3 → 8 | the `surfaces:` block's placement and compiled effect; authoring a `uses:` edge and what the target must declare; `health_check_path`'s placement in the service block |
| `testing` | +2 → 4 | staging tests and liveness (diagnostic form); which tier contract tests belong to |
| the six unscored skills | +6 | one should-trigger each |

Total 56 → 73 queries.

Two of the additions are a **deliberate phrasing pair** on one boundary — the liveness-mechanism
form ("does it need a `/health` route, and if not how does anything know it works?") and the
field form ("does it need a `health_check_path`, and what reads it?"). Both label to
`contracts`. Near-duplicate subjects normally inflate recall spuriously, but phrasing
robustness on exactly this boundary is the defect class this mod exists to fix, so the pair is
the measurement, not redundancy. The `note` on each says so.

**On the diagnostic form.** The 14 supplementary queries that found these holes were *not*
human-reviewed, which the methodology requires before a query set drives description changes.
So the holes are actionable — measured and reproduced — but no supplementary query is copied
verbatim into the canonical set. What is carried over is the *form* (diagnostic yes/no), which
is now a known blind spot and is therefore represented in both `contracts` and `testing`,
freshly worded.

## Scope 4 — The dangling `Isolation` reference

`skills/skill-iteration/references/evaluation.md` §Outcome Eval → "The run pattern" points at
a section **"per Isolation"** that does not exist, so the outcome-eval isolation protocol is
unspecified. It bit this advance's run.

Fix: write a short `### Isolation` subsection stating the achievable limit **plainly** rather
than an aspiration. Content:

1. **What cannot be isolated.** A subagent's system prompt loads the Resident stratum. The
   baseline arm cannot un-read it. There is no arm with zero doctrine.
2. **What the delta therefore measures.** *Navigation into the conditional stratum* — did the
   thread route to the right files — not knowledge. This is already the framing in
   §The System; Isolation is where it becomes an operational constraint.
3. **The consequence for case authoring.** Before using an expectation as a delta driver,
   **grep it against the `stratum: resident` files**. A driver the Resident stratum supplies
   measures nothing and silently deflates the skill's apparent value.
4. **The on-disk-strata requirement** (the original parenthetical's intent): both arms read
   the working tree, so run them from a context restarted after any doctrine edit, or the arms
   measure the previous revision.

## The instrument was broken

Found while verifying scope 1 and it changed the mod. Recorded at length because the lesson
outlives every description edit here.

### The confound

`run_suite.py::detect_triggered_skill` called `subprocess.Popen(cmd, ...)` with **no `cwd=`**, so
the child `claude -p` inherited the runner's cwd — this repo, where `doctrine/` sits in the
working directory. Observed directly: for the `surfaces` query the model's **first tool call** was

```
Bash  grep -rn "surfaces" doctrine/ --include=*.md | head -50
```

No downstream operator has that shortcut. A trigger eval claims to measure whether a description
routes a query to a skill; that claim is only valid when loading the skill is the **only** route
to the doctrine. Cwd is a route.

### It corrupted the measurement in one specific, flattering direction

| Query | repo cwd (gate run) | empty cwd (corrected) |
| ----- | ------------------- | --------------------- |
| `infra-compile` surfaces-authoring, **old** description | 0/5 → ∅ | **5/5 → `contracts`** |
| `infra-compile` surfaces-authoring, **new** description | — | **5/5 → `infra-compile`** |
| `contracts` health diagnostic, **old** description | 0/5 → ∅ | **4/5 → `contracts`** (passes) |
| `contracts` health diagnostic, **new** description | — | 5/5 |

The confound did not add noise. It **systematically converted precision failures into recall
failures**: with a grep available, a query that would have been *mis-routed* was instead answered
from the filesystem and recorded as ∅, which reads as *under*-triggering. That is the one
direction that makes a trigger surface look **healthier** than it is — a hole is a gap, while
poaching is an active defect in a neighbouring description.

So the gate's reassuring headline — *"precision 1.00 for every skill in both runs — no poaching,
no mis-triggering introduced"* — was itself the artifact. It is withdrawn.

### Two corrections to the mod's own premises

1. **`infra-compile`'s hole was real, but this mod's diagnosis of it was wrong.** "The description
   never says surface" stands. "The query fires no skill at all" was the instrument: it fires
   `contracts`, every time. Being poached by a sibling and falling to ∅ are different defects
   with different fixes.
2. **The `contracts` description edit is reverted.** Its hole was mostly artifact — the old
   wording already passes 4/5 — and the corrected instrument shows `contracts` is the *aggressor*
   in this pair. Widening it further would have worsened the real defect while appearing to fix a
   phantom. `infra-compile`'s edit stands, measured 5/5.

This is the failure `skill-iteration` exists to prevent, committed by the gate that exists to
prevent it: a durable trigger surface edited on the strength of an unvalidated measurement. Twice.
One edit survives because it was re-measured; the other does not.

### A third defect, found by disbelieving a number

The first full-suite run on the corrected harness returned **accuracy 0.178**, with near-universal
∅ — including the two queries measured at **5/5** twenty minutes earlier. That is not a trigger
result. Load average was **31** with `--num-workers 8`, and each `claude -p` is an entire CLI plus
model round-trips.

The defect: `detect_triggered_skill` fell through to `return None` when its deadline expired, and
`None` is also how it reports "the model acted and reached for no skill." **A timed-out run was
therefore scored as a recall failure.** Re-running two of the ∅ queries at `--num-workers 2` with
a 240s timeout: both **3/3**.

This is the cwd confound's twin — infrastructure masquerading as a finding — and it is arguably
worse, because it is *load-dependent*, so the same command on the same tree yields different
"findings" depending on what else the box is doing. It also fails in the flattering-looking
direction again: it manufactures recall failures, which read as holes to be fixed.

Fixed here: a `TIMEOUT` sentinel distinct from `None`; timed-out runs excluded from the modal
vote; a query whose every run timed out is recorded as `unscored` rather than incorrect; the
report carries `timed_out_runs` and `unscored_queries`; accuracy is reported as `n/a` rather than
fabricated when nothing was scored; and a loud stderr warning names the fix (lower
`--num-workers`) and says not to trust the numbers until it reads zero. Confound 3 in the
docstring. Both branches were verified by forcing a 5s timeout.

**The lesson these three defects share** is not about cwd, or deadlines, or descriptions. Each one
took a condition that had nothing to do with the thing being measured and reported it *as* the
measurement — and all three did so in the direction that looks like an actionable finding rather
than like a broken tool. An instrument that cannot say "I failed to measure" will say something
else instead, and that something else gets acted on.

### What was fixed, and what was deliberately not

**Fixed here** — `run_suite.py` runs each query in its own `tempfile.mkdtemp()` sandbox
(`cwd=sandbox`, removed in the `finally`), and the module docstring's "Confound to keep in mind"
note became a numbered list carrying this as confound 2 with an instruction never to drop the
argument. `RELEASING.md`'s Skills gate row now directs the gate at `run_suite.py` and names
`run_eval.py`'s outstanding confound, so the next operator learns which instrument is trustworthy
*and* which is not.

**Booked, not absorbed** — `run_eval.py:89` passes `cwd=project_root` **deliberately**: unlike
`run_suite.py` it installs the skill under test by writing `<project_root>/.claude/commands`
(line 53) and needs the cwd to find it. Sandboxing it means switching to `--plugin-dir` or
scaffolding the sandbox — a restructure, and restructuring a second harness inside a mod whose
subject is the first is how a scope stops holding. Filed at
`docex/plans/advances/007_small_edges/trigger_eval_cwd_confound_run_eval.md`.

**Stated, not coded** — the outcome-eval path has the same exposure but enforces isolation by
*instruction* rather than cwd. The honest statement of that ceiling is the fix, and it is what
scope 4's new `### Isolation` section says.

## Out of scope — booked, not fixed

`project-upgrade`'s recall was reported as regressing **1.00 → 0.50**, reproduced at 1/5 and 0/5.
Its description was untouched by this advance, so it is not ours. Booked to
`docex/plans/advances/007_small_edges/project_upgrade_recall_regression.md`.

**But that number is suspect for the reason above, and the brief says so as its first line.** Both
misses land in ∅ — the exact bucket the cwd confound manufactures. It may not be a regression at
all; it may be the same artifact running the other way. Anyone editing that description off the
0.50 would repeat this mod's mistake with a different skill. The brief's first instruction is
therefore *re-measure on the corrected harness, then decide whether there is anything to fix.*

## Verification

| Verifier | Invocation |
| -------- | ---------- |
| unit | `./.venv/bin/python -m pytest tests -q` from `docex/` → expect 1199 passed, 21 deselected |
| integration | `./.venv/bin/python -m pytest tests -q -m integration` from `docex/` → expect 21 passed |
| linkcheck | `linkcheck.py` → green |
| examples | `verify_examples.py` → green |
| **trigger eval** | `run_suite.py --runs-per-query 3` over the full 73-query set, plus a focused `--grep` pre-check on the two holes |

Never bare `pytest`, never both `-m` flags in one run, never from the repo root.

**The 1199/21 counts are expected-unchanged, not a pass.** Nothing under `docex/src` is in this
mod's territory, so movement in those numbers is a **signal that something went wrong** rather
than a green light. That distinction is the one three of this advance's instrument defects
turned on: an instrument that reports green against a changed world is worse than one that
reports nothing.

The trigger eval is the load-bearing verifier, and it is run by the mod owner rather than the
implementor — interpreting a precision trade is a design call, not an execution step.

The trigger eval is the load-bearing verifier. Reported per-skill recall **and** per-skill
precision, measured by this mod's own run; the gate run's artifacts live in another agent's
scratchpad and are not inherited.

## Design questions — resolved

All four were put to the operator's authority and answered. Recorded here because the
resolutions, not the questions, are what the implementation follows.

1. **`uses:` — include, conditional on measurement.** Approved on the condition that `uses:`
   gets its own should-trigger query, so the added vocabulary is measured rather than assumed.
   The `_advance_retire_depends_on` risk was judged not to bear: that brief proposes deriving
   the *fixed readiness gate* from magic refs, not deleting the relation, and a description
   naming a field that later changes shape is a cheap edit.

2. **Second `contracts` outcome case — add it; the gated artifact should grow.** One case for a
   materially-changed skill was already below the methodology's own target, and the
   worker-liveness case covers the thresholds and the no-fan-out rule nothing else reaches.
   That it measures the same doctrine the trigger hole made unreachable is the argument rather
   than a coincidence: the two failures had one cause, and closing only the trigger half would
   leave the outcome half unmeasured forever.

3. **Six new should-trigger queries — yes, and the handling is pre-agreed.** Omitting
   `competing_skills` without labels leaves those six recall-unscoreable, so the queries are the
   completion of the change rather than an extension of it. Anything they surface is
   **booked-not-caused**, the same treatment as `project-upgrade`'s 1.00 → 0.50: reported, not
   fixed here.

4. **`health_check_path` — the ambiguity is in the question, not the seam.** Declining to guess
   a label was right, but the resolution is better than the gap: *"where does `health_check_path`
   go in `infra.yml`?"* is unambiguously `infra-compile`, and *"does my worker need a
   `health_check_path`?"* is unambiguously `contracts`. Split into two queries that each label
   cleanly, converting one unmeasured seam into two measured ones. If either resists a confident
   label while being written, it is left out and booked rather than forced.

Both queries were written and both label cleanly, so the seam is measured rather than booked.
The `infra-compile` side is scoped to *placement and validation within the service block*
(`cicl.md`, rule 33); the `contracts` side to *whether a non-routed service needs the field and
what consumes it* (`healthchecks.md`, whose answer is "one consumer: elastic with
`reverse_proxy: alb`"). Neither query mentions `web`-network, for the reason given in 1b.

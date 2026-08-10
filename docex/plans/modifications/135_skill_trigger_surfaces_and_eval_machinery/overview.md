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

## Out of scope — booked, not fixed

`project-upgrade`'s recall regressed **1.00 → 0.50**, reproduced at 1/5 and 0/5. Its
description was untouched by this advance and both misses land in ∅ rather than being poached,
so it is model/CLI drift since the last recorded run (2026-07-11), not ours. Both failures
name an *old pin* without an action verb the description carries. Booked to
`docex/plans/advances/007_small_edges/`.

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

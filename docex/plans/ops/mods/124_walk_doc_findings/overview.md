# Mod 124 — Elastic-walk documentation findings

The last mod of advance 005. Two findings from the completed 1.7.0 elastic
smoke walk, neither of which is a `docex` defect.

> **Scope.** Implementation: one checklist file
> (`docex/test_projects/PRE_CUT_CHECKLIST.md`) and two doctrine files
> (`specifics/clock.md`, `specifics/migrations.md`). Documentation step:
> `CHANGELOG.md` and `docex/plans/core/test_projects.md`.
> **No `docex` source change, no test change, no emitted-output change, no
> `cicl_version` implication.** `pytest tests/unit` (1009) and
> `pytest -m integration` (20/0) must be unmoved by this mod; any movement is
> a finding in itself.
>
> Nothing inside `test_projects/fixed` or `test_projects/elastic` is touched,
> so both inner repos stay clean at `v0.0.23`.

---

## Finding 1 — the checklist names the wrong consumer pair

### What is wrong

`PRE_CUT_CHECKLIST.md` D.9 (`:370`) and D.11 (`:419`) both open the
reconcile-operand box with:

> For each consumer (`api-web` and `api-worker` — they form a `uses` cycle):

Both halves of that parenthesis are false for this project, and the
`describe-services` command two lines below each one (`:373`, `:422`) queries
the same wrong pair.

The elastic seed's `infra.yml` declares:

| Core service | `uses` | Core-targeted? |
| ------------ | ------ | -------------- |
| `api.web` | `[appdb, probe, events, api.worker]` | **yes** → `api.worker` |
| `api.worker` | `[appdb]` | no — backing only |
| `api.clock` | `[appdb, api.worker]` | **yes** → `api.worker` |

The reconcile's candidate set is every core service with a non-empty
`uses_core` that emits an `ecs_service` (`pipeline/release.py`,
`_reconcile_candidates`). That is **`api-web` and `api-clock`**, both pointing
at `api.worker`. `api.worker` declares no core-targeted edge at all, so it is
never a consumer — and there is therefore **no cycle** anywhere in this
project.

The walk's own evidence already agreed with reality rather than with the
checklist: `release` printed `2 consumer(s) checked` and named `api-web` and
`api-clock` in both the fire and the skip verdicts.

### Why it matters beyond tidiness

The box tells the walker to record two timestamps and then confirm they agree
with `release`'s printed verdict. A walker following it literally would look
for an `api-worker` reconcile line, not find one, and reasonably read a
**correct** release as a regression — or, worse, record `api-worker`'s
deployment timestamp and "confirm" the predicate against an operand the
predicate never touched. This is the same shape as the finding mod 123 raised
at its § 3: an instrument that cannot observe the thing it claims to observe.

### The shape of the fix — an assertion that detects its own rot

**This is the lesson of the mod and the reason the fix takes the form it does.**
The defect exists because a *static claim about `infra.yml`* was written into the
checklist and then drifted silently when `infra.yml` moved. Replacing one static
pair with a corrected static pair would leave the drift mechanism entirely
intact — the next `infra.yml` change breaks it again, just as quietly.

So the repair is keyed on the **tool's own output**: `release` prints
`N consumer(s) checked`, and the box tells the walker that `N ≠ 2` means the box
is stale. A clause keyed on what the executor reports cannot drift away from
what the executor does; the only way to break it is to change the executor,
which is not a silent act. The corrected pair is the smaller half of this fix.
The self-checking clause is the part that matters.

The same instinct governed the sweep below: B.9's provider set and B.10's
fan-out set were **re-derived** from `infra.yml` rather than assumed correct,
and the derivation is recorded so a future reader can audit the sweep instead of
trusting it.

### The fix

In **both** D.9 and D.11:

1. Replace the parenthetical with a statement that derives the consumer set
   from the rule rather than asserting a pair, and says explicitly why
   `api-worker` is not in it.
2. Change `--services api-web api-worker` to `--services api-web api-clock`.
3. Add one self-checking line: `release` reports `N consumer(s) checked` — if
   `N ≠ 2`, the consumer set changed and the box is stale. This is what stops
   the same defect recurring silently the next time `infra.yml` moves.

Proposed replacement for the box's opening (identical in both, modulo the
cluster name):

> - [ ] **Record both reconcile operands, and the verdict.** The consumers are
>   the core services that declare a **core-targeted** `uses` entry — here
>   `api-web` and `api-clock`, both targeting `api.worker`. `api.worker` itself
>   declares `uses: [appdb]` only, and a backing-targeted entry never makes a
>   consumer, so the worker is a target and never a consumer; **there is no
>   `uses` cycle in this project.** For each consumer:
>   ```bash
>   aws ecs describe-services --cluster docex-smoke-elastic-stage \
>     --services api-web api-clock \
>     --query "services[].[serviceName,deployments[?status=='PRIMARY']|[0].createdAt]"
>   aws servicediscovery list-services \
>     --query "Services[].[Name,CreateDate]"
>   ```
>   `release`'s own output states the count it used — `N consumer(s) checked`.
>   **If `N` is not 2, the consumer set has changed and this box is stale**;
>   re-derive it from `infra.yml` before recording anything.

Everything below the command in each box — the verdict table, the
"neither line appearing is itself a finding" paragraph, and the "why this box
exists" note — is correct and unchanged.

### Did anything else inherit the same model?

Swept. **No.** The only two other places in the corpus that mention a `uses`
cycle are both correct general statements about the *rule*, not claims about
this project:

| Location | Text | Verdict |
| -------- | ---- | ------- |
| `PRE_CUT_CHECKLIST.md:196` (B.10 fan-out) | "never calling the target's own fan-out (the `uses` graph may legally cycle)" | Correct — justifies the one-hop rule in general. |
| `test_projects/fixed/plans/core/masterplan.md:115` | same justification for the one-hop fan-out | Correct, and inside an inner repo — **not touched**. |

Two adjacent checklist items were also re-derived against `infra.yml` and are
**correct as written**, recorded here so the sweep is auditable rather than
asserted: B.9's provider set (`api.web` via the `web` network, `api.worker` via
being a core `uses` target — both carry contracts) and B.10's fan-out set
(`api.web` → `/health/api/worker`, one route).

---

## Finding 2 — the clock fires against an unmigrated database on a first
elastic release

### What the walk observed

On the first-time-release path the ordering is documented and deliberate:
`SSM push → tofu apply → migrate`
([`migrations.md § First-Time Release of an Env`](../../../../doctrine/infrastructure/specifics/migrations.md#first-time-release-of-an-env)).
Core services therefore start *before* migrations run. The walk saw `api-clock`
fire `heartbeat` at 20:41:01 against a schema that did not yet exist and log
`psycopg2.errors.UndefinedTable: relation "jobs" does not exist`. It did not
crash, did not crash-loop, and the next tick at 20:42:01 succeeded.

So: a consequence of the documented ordering, not a bug. But **the clock is the
one service guaranteed to exercise it**, because it fires on a schedule rather
than in response to a request. It will recur on every elastic first release of
every project that has a clock, and an operator watching a first release will
see a stack trace and reasonably conclude something is broken.

### Why it self-heals, mechanically

Worth stating because the note asserts it. The reference clock loop
(`test_projects/*/core/api/src/entrypoints/clock.py`) wraps each `cron.fire()`
in a `try/except`, logs, counts the failure, and recomputes `next_at` forward
from `now`. Health is unaffected: the tick is withheld only on a pass where
*every* due job failed, and the following passes have nothing due and bump it —
so a failed fire never approaches the 30 s staleness threshold. Recovery is
therefore automatic and needs no operator action.

The obligation this places on a **job** is real and the doctrine does not
currently state it: a fire may fail outright, before the handler does anything
at all, and the job must be safe to attempt again on its next slot. That is the
existing idempotence caveat extended backwards to cover the failed-before-doing-
anything case.

### Where it belongs — three places, each a different reader

| Document | Reader | What it gets |
| -------- | ------ | ------------ |
| `clock.md § Caveats` | a project author writing a job | the obligation (the substantive half) |
| `migrations.md § First-Time Release of an Env` | someone reading the ordering | one sentence naming the clock as the service that exercises it |
| `PRE_CUT_CHECKLIST.md` D.11 clock group | the walker | expectation-setting, so a stack trace is not read as a regression |

Splitting it this way keeps each statement short and puts the obligation where
the person who must honour it is already reading. `clock.md` is the primary; the
other two are pointers.

### Draft prose — for review before it lands

**(a) `clock.md § Caveats` — new bullet, appended after the existing three.**
*(Revised per ruling Q1: stated as a property of the ordering, with the elastic
first release named as the case where it is guaranteed rather than as a second
observation.)*

> - **A scheduled job may fire before migrations have run.** Nothing gates a
>   core service's startup on its backing services, and migrations run *after*
>   the stack is up: in `dev` and `test` on both foundations
>   ([`migrations.md § Invocation Timing`](./migrations.md#invocation-timing)),
>   and after `tofu apply` on an elastic env's
>   [first release](./migrations.md#first-time-release-of-an-env) — where a
>   clock is **guaranteed** to meet the window rather than merely liable to.
>   Because a clock fires on its own schedule rather than in response to a
>   request, it is the service most likely to reach a cold schema first, and a
>   `relation "…" does not exist` stack trace in a clock's log on a first
>   bring-up is expected rather than a fault. Recovery is automatic: the loop
>   treats a failed fire as a failed fire and not a failed loop, so the job
>   retries on its own next slot — no operator action, and no effect on the
>   clock's health probe. **The obligation this places on a job is that a fire
>   must tolerate a cold schema**: it may fail before doing anything at all, and
>   the next attempt must be able to proceed as if it had never been made.

**(b) `migrations.md § First-Time Release of an Env` — appended to the existing
"transient consequence" paragraph (`:98`).**

> A [`clock`](./clock.md) core service is the one guaranteed to exercise this
> window, because it fires on its own schedule rather than in response to a
> request: a minutely job will fire, fail against the missing schema, and log a
> stack trace before the migration lands. That is expected and self-healing —
> see [`clock.md § Caveats`](./clock.md#caveats).

**(c) `PRE_CUT_CHECKLIST.md` D.11 — new box, first in the "Clock — fire → defer
→ drain" group, ahead of the existing "the clock started and its schedule
arrived" box.**

> - [ ] **Expect one failed fire before the migration lands, and do not read it
>   as a regression.** The first-release ordering is
>   `SSM → tofu apply → migrate`, so `api-clock` starts before the schema
>   exists; its first `heartbeat` logs
>   `psycopg2.errors.UndefinedTable: relation "jobs" does not exist`. This is
>   the documented ordering
>   ([`migrations.md § First-Time Release of an Env`](../../doctrine/infrastructure/specifics/migrations.md#first-time-release-of-an-env))
>   and it self-heals
>   ([`clock.md § Caveats`](../../doctrine/infrastructure/specifics/clock.md#caveats));
>   the next tick ~60 s later succeeds. The same happens on the D.9 `stage`
>   release, where no box reads the clock's log. **A clock still failing two
>   ticks after the migration completed is a genuine finding.**

### Not changed, and why

- **Fixed C.9.** On fixed, `stage`/`prod` migrations run inside the Ansible
  playbook *before* `docker compose up -d`
  ([`migrations.md § Stage and Prod on Fixed Foundation`](../../../../doctrine/infrastructure/specifics/migrations.md#stage-and-prod-on-fixed-foundation)),
  so the fixed prod clock never meets a cold schema. No checklist change there.
- **Fixed/elastic C.4/D.6 dev bring-up.** The `dev` window is real on both
  foundations — see design question 1 — but the checklist already warns at
  `:347` that core services crash-loop on a first `envinfra up dev` for an
  unrelated reason, so a second warning in the same place buys little. The
  generality is carried by `clock.md` instead.
- **No code, no tests.** The reference implementation already does the right
  thing; this mod documents behaviour it already has.

---

## Verification

1. `pytest tests/unit` — 1009 passed, **unchanged**.
2. `pytest -m integration` — 20 passed / 0 failed, **unchanged**.
3. `python3 skills/cohere/executor/linkcheck.py` — green over the default
   `doctrine/` + `skills/` roots. **Run this only after the prose has landed.**
   The links inside the drafts above are written relative to their *eventual*
   homes, so a run against the overview reports them broken and a run against
   the landed files is the only one that proves them. A link verified in a
   quotation is not verified.
4. **Checklist links validated separately.** `PRE_CUT_CHECKLIST.md` sits
   outside `linkcheck`'s default scan root (a known gap logged for advance 006),
   so it is checked with the scan root widened to include it *alongside* the
   defaults — `linkcheck.py doctrine skills docex/test_projects` — which is what
   makes its links *into* `doctrine/` anchor-verified rather than fail-open.
5. `git status` shows no modification under `docex/test_projects/{fixed,elastic}/`;
   both inner repos remain clean at `v0.0.23`.

## Verification notes — two corrections to this document's own predictions

Both surfaced during execution. Neither is a drift in the landed prose; both are
errors in the *expected values* written above and in `implementation.md`, and
they are recorded rather than quietly patched.

1. **`grep -c 'N consumer(s) checked'` returns 4, not 2.** The string already
   occurred twice at HEAD, inside the `| **skip** |` row of each verdict
   table — text that sits in the region this mod required to stay
   byte-identical. The two new clauses land at `:383` and `:441`, giving
   2 pre-existing + 2 new. The substantive requirement (the clause present
   exactly once in D.9 and once in D.11) is met and was verified by line
   number. **The check was written as though the grep would see only the new
   text; the implementor was right to report the mismatch rather than adjust
   prose to chase the number.**

2. **The widened-root `linkcheck` run cannot exit 0, and this sharpens the
   advance-006 gap.** `linkcheck.py doctrine skills docex/test_projects` exits 1
   on **check 3 (identical filenames)** — the `fixed/` and `elastic/` seeds
   mirror each other by design, so `masterplan.md`, `api.md`, `CHANGELOG.md` and
   nine others are duplicated structurally and permanently. **Check 1
   (links/anchors) is green**, which is the half this step exists to obtain, and
   it is what proves the two new `../../doctrine/…` links in the D.11 box
   resolve with anchors verified.

   So the gap logged for advance 006 is not merely *"`PRE_CUT_CHECKLIST.md`
   sits outside the default scan root."* It is: **widening the root to reach it
   necessarily drags in two deliberately-mirrored repos, which makes check 3
   unusable at that scope.** Any fix must let the two checks be scoped
   independently, or exclude the seed trees from check 3 — a plain root
   widening will not do. Recorded here for whoever picks it up; minting the
   advance-006 stub is an advance-scoping act and not this mod's to take.

## Non-goals

- The advance's `report.md`, the version artifacts, and the changelog roll — all
  the operator's.
- Fixing `linkcheck`'s scan root so `test_projects/` is covered by default.
  Real, already logged for advance 006, and out of scope here.
- Any change to the reconcile predicate, its operands, or its output wording —
  mod 123 settled those and the walk confirmed them.

---

## Design questions — resolved

All three ruled by the C.O. before implementation.

1. **Scope of the `clock.md` caveat.** Ruled: **cover both, but write it as a
   property of the ordering rather than as two observations.** The `dev` case is
   real and ours — since mod 113 no core-service compose block carries a
   readiness gate, so `envinfra up dev` genuinely starts the clock before
   migrations run — and scoping the caveat to the elastic first release would
   under-warn in the place an author is *least* suspicious. But we did not
   observe the `dev` case and must not claim we did. So the bullet states the
   general property (*a scheduled job may fire before migrations have run, so a
   fire must tolerate a cold schema*) and names the elastic first release as
   the case where it is **guaranteed** rather than merely possible. That is
   honest to both readers and stays true if the ordering changes. Draft (a)
   revised accordingly.

2. **Level of the obligation.** Ruled: **keep the narrow form.** "A fire may
   fail for any reason" restates the idempotence caveat two bullets up, and a
   caveat list whose entries overlap teaches less than one whose entries are
   distinct. "Must tolerate a cold schema" names a specific thing an author can
   go and check in their handler. Draft (a) unchanged on this point.

3. **The clock loop's own obligation ("must not exit on a failed fire").**
   Ruled: **logged to advance 006; the rule is not added here.** It is a new
   rule rather than a record of what the walk found, and close-out is the wrong
   moment. It is also not silent if violated — a loop that exits takes its
   container down, which the health probe and the release's steady-state wait
   both surface immediately.

   One **descriptive** clause is allowed in its place, explicitly as a
   description of what the seed does and not as a requirement. It is folded
   into draft (a)'s recovery sentence as *"the loop treats a failed fire as a
   failed fire and not a failed loop"* — a statement of the mechanism that makes
   the self-healing true, carrying no `must`.

   **Two deliberate narrowings of the allowance, recorded for review.** The
   clause names no filesystem path and does not cite the seed tree, because
   **no doctrine file currently references `test_projects/`** (verified by
   grep). Introducing the first doctrine → seed link in a close-out mod is a
   structural precedent this mod has no business setting, and a globbed path
   (`test_projects/*/core/api/…`) would fail `linkcheck` besides. If the C.O.
   wants the seed named explicitly, that is a one-line follow-up.

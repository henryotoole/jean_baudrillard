# Mod 156 — Test-Selection Policy (F6 / SC5)

**Advance 009 — Test Overhaul, Wave 4, Mod 10 (final mod; closes Goal 5).**

This is a **pure-prose / process-doctrine mod.** No docex source changes, no
tests written. It encodes the test-selection *policy* — full-vs-scoped as a
sanctioned, hard-governed decision — into the process strata and the agent
definitions that carry them. The *mechanism* the policy governs already shipped
earlier this advance:

- **Mod 151** — `docex test unit [subset]` (no-stack fast lane) /
  `docex test integration [subset]`, the scoped-run mechanism
  (`DOCEX_TEST_SELECTOR`).
- **Mod 154** — `docex test --slots N` sharding (`DOCEX_TEST_SLOT` /
  `DOCEX_TEST_SLOTS`), which is what makes "close on full `integration`"
  affordable.

## Design

### The policy (verbatim intent)

Three clauses, plus a scope-selection rule, stated in one vocabulary
(`unit` / `integration`, "iterate scoped / close full") across all five files:

1. **Mod cycle — iterate scoped, close full.** A mod cycle *may* iterate with
   scoped runs (`docex test unit [subset]` / `docex test integration [subset]`)
   to keep the inner loop fast, but its test step **closes** on the full `unit`
   tier (cheap, no stack) **plus the relevant `integration`** tests, all green.
2. **Advance — closes full.** An advance **closes with a full run of both tiers**
   — full `unit` and full `integration` — across the project.
3. **CI/CD — always full.** `check` / `merge` always run the full suite and never
   scope.
4. **Scope is judgment, not a computed set.** The agent — who just wrote the diff
   — chooses the subset via the Mod-151 subset mechanism. **No computed
   "affected" selector ships** (no `--changed` path-mirror, no dependency-graph
   selector). SC5's rationale: cross-module driving-port imports, `shared/` blast
   radius, and domain changes with no test mirror make a computed "affected" set
   give false confidence.

### Where the policy lives (ratified layering)

The doctrine's architecture forbids doctrine files pointing *out* to skills
(skills route *into* the doctrine, never the reverse). Each clause is stated once,
in its **natural doctrine home**; the agent defs carry a **brief, rank-specific
discipline statement that links back** to that home (per the chain-of-command
convention — agent files link to doctrine for shared rules and uniquely define
only their subject-matter/escalation); the skill routes into the doctrine:

- **`modifications.md`** — canonical **mod-cycle** clause (clause 1 + the
  judgment/no-selector rule).
- **`advance.md`** — canonical **advance** clause (clause 2), with clauses 1/3 as
  context, under a stable anchor the sarge agent links to.
- **`cicd.md`** — canonical **CI/CD** clause (clause 3: `check` / `merge` always
  run the full suite, never scope).
- **`agents/corporal/mod-developer.md`** — brief corporal rule → links to
  `modifications.md`.
- **`agents/sergeant/doctrine-advance.md`** — brief sarge rule → links to
  `advance.md`.
- **`testing` skill** — gathers all three clauses + routes to the mechanism.

Identical vocabulary (`unit` / `integration`, "iterate scoped / close full")
throughout.

### Not touched (confirmed)

- **docex core planning docs** (`masterplan.md`, etc.) — *no change*. This mod
  touches process doctrine + agent defs + the skill, not docex's code or its own
  project docs.
- **No computed selector ships.** Prose only.

---

## Proposed wording — exact edits

### 1. `doctrine/practices/modifications.md`

Replace process step **6.4** (`Ensure relevant tests are all green.`) with:

> 4. **Close the test step on a full run.** You may iterate during the cycle with
>    scoped runs (`docex test unit [subset]` / `docex test integration [subset]`)
>    to keep the loop fast, but the cycle **closes** on the full `unit` tier
>    (cheap, no stack) plus the **relevant `integration`** tests, all green.
>    Choose the scope by your own judgment as the author of the diff — nothing
>    computes an "affected" set from the changes.

### 2. `doctrine/practices/advance.md`

**(a)** Add a new subsection immediately after `### Heuristics for Tactical
Planning` (before `## Process`):

> ## Test Scope Across an Advance
>
> Test scope is a sanctioned, policy-governed choice — not license to skip tests.
> Individual mods within the advance may iterate with scoped runs
> (`docex test unit [subset]` / `docex test integration [subset]`) and close each
> cycle on the full `unit` tier plus the **relevant `integration`** tests (see
> [modifications.md](./modifications.md)). The **advance itself closes on a full
> run of both tiers** — full `unit` and full `integration` across the project —
> before you write `report.md`. CI/CD gates (`check` / `merge`) always run full
> and never scope. Scope is agent judgment via the `docex test` subset
> mechanism; no computed "affected" selector exists.

**(b)** In `## Process`, add a sub-point to step **4 (Report)**, as new **4.1**
(renumbering the current 4.1–4.3 to 4.2–4.4):

> 1. Before reporting, ensure the advance has **closed on a full run of both
>    tiers** (see [Test Scope Across an Advance](#test-scope-across-an-advance)).

**(c)** Align the example plan's close-out step **6** — change
"Bring up a fresh `test` env, run unit/integration, and (if…" to:

> 6. **Test + release.** Bring up a fresh `test` env and run the **full `unit`
>    and `integration` tiers across the project**, and (if in scope for this
>    advance) run the CI/CD pipeline to stage/prod. Otherwise defer to the
>    process step 4 offer to merge.

### 3. `agents/corporal/mod-developer.md`

Append a **brief, link-back** section:

> # Test Discipline
>
> Iterate with scoped runs (`docex test unit [subset]` /
> `docex test integration [subset]`) to keep the loop fast, but **close the mod's
> test step on a full run** — the full `unit` tier plus the **relevant
> `integration`** tests, all green. Scope is your judgment as the diff's author;
> there is no computed "affected" selector. This is the mod-cycle test rule from
> [modifications.md](../../doctrine/practices/modifications.md).

### 4. `agents/sergeant/doctrine-advance.md`

Append a **brief, link-back** section:

> # Test Discipline
>
> An advance **closes on a full run of both tiers** — full `unit` and full
> `integration` across the project — before you write `report.md`; never report
> an advance complete on a scoped run. Your scoped mods each close on full `unit`
> + relevant `integration` (the corporal enforces that); CI/CD gates
> (`check` / `merge`) always run full. This is the advance test rule from
> [advance.md](../../doctrine/practices/advance.md#test-scope-across-an-advance).

### 5. `skills/testing/SKILL.md`

**(a)** Append one clause to the `description` frontmatter (after the
`DOCEX_TEST_SELECTOR` sentence), so scope-policy questions trigger the skill:

> …including the `DOCEX_TEST_SELECTOR` subset contract, and the full-vs-scoped
> test-selection policy (a mod cycle iterates scoped and closes full; an advance
> closes full; CI/CD is always full).

**(b)** Add a new final `## Thread` bullet:

> - **Test-selection policy (scope is a sanctioned choice).** A mod cycle may
>   iterate with scoped runs but **closes on the full `unit` tier plus the
>   relevant `integration` tests**; an **advance closes on a full run of both
>   tiers** across the project; **CI/CD (`check` / `merge`) is always full**.
>   Scope is agent judgment via the subset mechanism above — and
>   `docex test --slots N` sharding is what makes closing on full `integration`
>   affordable. **No computed "affected" selector exists**, by design:
>   cross-module driving-port imports, `shared/` blast radius, and domain changes
>   with no test mirror make a computed set give false confidence. The process
>   side lives in [`modifications.md`](../../doctrine/practices/modifications.md)
>   (mod cycle) and [`advance.md`](../../doctrine/practices/advance.md) (advance).

### 6. `doctrine/infrastructure/cicd.md`

In the **Build Test Step**, append a sentence to the paragraph introducing the
two shims (after "…the same way for every project."):

> The pipeline always runs the **full** suite: `check` and `merge` never scope to
> a subset — the scoped/subset runs (`DOCEX_TEST_SELECTOR`) are a development-loop
> convenience only, never a CI/CD gate (see
> [modifications.md](../practices/modifications.md)).

---

## Link integrity (to verify at implementation)

New/relied-on links, all resolvable:

- `advance.md` → `./modifications.md` (sibling; exists).
- `doctrine-advance.md` → `../../doctrine/practices/advance.md#test-scope-across-an-advance`
  (new anchor added by edit 2a).
- `mod-developer.md` → `../../doctrine/practices/modifications.md` (exists).
- `cicd.md` → `../practices/modifications.md` (exists).
- testing skill → `../../doctrine/practices/{modifications,advance}.md` (exist;
  skill-into-doctrine direction is correct).
- No doctrine file gains an outbound link to a skill.

## Success criteria (Advance Goal 5)

- **SC1** — `modifications.md`, `advance.md`, and the `mod-developer` /
  `doctrine-advance` agent defs encode the policy (iterate scoped; mod closes on
  full `unit` + relevant `integration`; advance closes full; CI/CD always full).
- **SC2** — No computed "affected" selector ships; scope is agent judgment via
  the F5 mechanism. This mod is prose only.

## Design questions — resolved by sarge

1. **Layering (was: distributed vs central).** Ratified: each clause lives once
   in its natural doctrine home (mod→`modifications.md`, advance→`advance.md`,
   CI/CD→`cicd.md`); agent defs carry brief rank-specific statements that **link
   back**; the skill routes into the doctrine. No doctrine→skill link.
2. **`cicd.md` — add it.** "CI/CD always full" is a rule *about* CI/CD, so it
   belongs in the CI/CD doctrine. Blast radius is now **six files**.

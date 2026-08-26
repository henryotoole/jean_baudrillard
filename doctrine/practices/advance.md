---
stratum: conditional
---

# Advance

The "advance" is a planned collection of mods and other processes executed together in service of one or more goals. It provides the framework for organizing those high level goals into an *advance plan*, and then translating the plan into a set of mod cycles which realize the plan by altering the project.

## Structure

Every individual advance gets a folder at `$pr/plans/advances/${advance_number}_${advance_name}/`. This folder contains:
+ `advance_plan.md`
+ `report.md`

## Advance Plan

The `advance_plan.md` should contain the following sections:
1. Goals - A formal listing of the goals of the plan, including success criteria. Good success criteria are specific and testable. See example below.
2. Tactical Plan - A section which details the approximate path by which the goals will be achieved. The bulk of this will usually be mod cycles. However, this may also include a `project-cohere` step, a "release to production" step, etc.
	+ Steps in the plan which will leverage subagents should note which subagent will be used.

Example of `advance_plan.md` with only "Goals" and "Tactical Plan" sections:
```md
# Goals

## Goal 1: Add Functional Frontend To Existing Backend

The existing backend needs a frontend which drives core operations. This frontend will be accessed only by project admins to check on the state of customers and orders. 

### Success Criteria
1. Stateful auth mechanism proven to work by direct interaction with the frontend via the `browser-investigate` skill.
2. Dashboard page shows overview of customers and open orders.
3. Unified color / styling scheme matching company standards (see references).

## Goal 2: Add Status Email To backend

The backend should be able to send emails when certain trigger events occur. The trigger events themselves will be part of a future update.

### Success Criteria
1. Backend code can requisition a new inbox under the project domain.
2. Backend can send an email with new or existing inboxes.
3. A system-wide whitelist step ensures that email can *only* be sent to addresses in the whitelist.

# Tactical Plan

1. **Mod: scaffold `frontend` codebase.** `corporal`.
   Add the `frontend` codebase and its one core service to `infra.yml` (consumer
   of `api.web`'s `rest` surface, `health_check_path` declared), Dockerfile with
   the standard build/dev/prod/test stages, and `build.sh`/`test.sh`/`health.sh`
   shims. Its own
   mod not for size, but because it is a *verification gate* — the service must
   stand and health-check green before features land on it — and because it is
   infra territory (`infra.yml`, `infra-compile`), distinct from the frontend app
   code that follows.
2. **Mod: stateful auth.** `corporal`.
   Admin login + session handling. Kept separate from the dashboard despite
   sharing frontend territory, because two cut-points fall on this boundary:
   → DECISION (rippled to sarge): session state in the relational DB vs. a cache
     backing service. Corporal raises this in design; sarge rules, or ripples to
     operator if it implies new infrastructure.
   → GATE: Success Criterion 1 (auth proven by real interaction) is verified by a
     one-shot `private` launch using the `browser-investigate` skill against the
     dev stack before the dashboard is built on top of the session.
3. **Mod: dashboard page + styling.** `corporal`.
   Customers + open-orders overview, plus the unified color/styling scheme from
   `plans/references`. Styling shares frontend territory with the dashboard and is
   small, so it is folded in rather than paying a separate mod's overhead.
   → RECON FIRST: send a one-shot `private` to check whether the backend read
     endpoints this page needs already exist. If they are missing and non-trivial,
     they become their own *backend*-territory mod that lands before this one; if
     trivial, the corporal adds them within this cycle (contract updated).
4. **Mod: email module.** `corporal`.
   New backend hex module: a `Gwy` to the email provider, inbox requisition under
   the project domain, and the recipient-whitelist guard. The whitelist is a
   domain invariant living inside this same module, so it is one vertical slice,
   not a separate mod. Requires the provider API key — a blocker to raise with the
   operator at plan presentation. If SC3's whitelist proves genuinely
   *system-wide* rather than email-local, split it back out as its own mod.

## Close-out

5. **`project-cohere`.** `corporal`. Run once, after all mods land, per the
   token-cost heuristic — reconcile core planning docs against the delivered code.
6. **Test + release.** Bring up a fresh `test` env, run unit/integration, and (if
   in scope for this advance) run the CI/CD pipeline to stage/prod. Otherwise
   defer to the process step 4 offer to merge.
```

### Heuristics for Tactical Planning

Drafting up the tactical plan is something of an art because it can take so many different forms depending on the goals. The following heuristics can help:
1. Use `project-cohere` agents sparingly, as it uses a great many tokens and can exhaust a context window quickly. It's best to only use `project-cohere` once per advance, after all mod cycles are done.
2. Mod scoping is tricky. Try to bundle changes which share *territory*; a series of changes to one module or even one core service often should be combined into one mod. However, there are good reasons to split territory-sharing changes out into separate mods:
	1. **A decision must ripple.** If part of the change hinges on a decision that exceeds the corporal's authority — and so ends its turn for escalation — cut the boundary there. Don't leave downstream work sitting uncommitted in a context that is about to pause; the escalation *is* the seam.
	2. **A verification gate sits between the pieces.** When one piece must be proven to work before the next is built on top of it (a health check gone green, an auth flow confirmed via `browser-investigate`), that gate is a mod boundary.
	3. **The combined mod would breach the context ceiling.** Territory sharing keeps *comprehension* cheap, but a large or unfamiliar diff still spends context — roughly lines-changed × a familiarity multiplier, plus test and debugging churn. Estimate conservatively and target well under the corporal's limit; hitting compaction mid-mod drops quality far more than an extra mod cycle costs.

## Test Scope Across an Advance

Test scope is a sanctioned, policy-governed choice — not license to skip tests. Individual mods within the advance may iterate with scoped runs (`docex test [subset]`) and close each cycle on a full run of the suite (see [modifications.md](./modifications.md)). The **advance itself closes on a full run** across the project — before you write `report.md`. CI/CD gates (`check` / `merge`) always run full and never scope. Scope is agent judgment via the `docex test` subset mechanism; no computed "affected" selector exists.

## Process

The following process should be followed rigidly for every advance.

1. **Setup**
	1. Read the project's *core planning docs* if you haven't already.
	2. Ensure that the current branch is `main` and that the working directory is clean. If it isn't, end the turn with a message noting which check failed.
	3. Make a new branch called `advance_${advance_number}_${advance_name}`. This will be the working branch for the advance's changes.
	4. Create the advance folder at `$pr/plans/advances/${advance_number}_${advance_name}` if it does not already exist.
2. **Plan**
	1. If `advance_plan.md` already exists:
		1. Read it.
		2. "Fill in" any parts of the plan which are missing or stubbed.
		3. Ask any questions needed to clarify the goals.
	2. If `advance_plan.md` did not exist:
		1. Ask for goals and success criteria.
		2. Draft up `advance_plan.md` yourself.
		3. Ask any questions needed to clarify the goals.
	3. End the turn and present the plan to the operator for review.
		1. If you foresee any definite blockers only the operator can resolve (e.g. needing an API key for email), note them now.
3. **Act**
	1. Perform the plan, but keep in mind that *plans can change*. Unexpected problems can and will surface during design which may alter the original plan. An extra mod cycle might need to be injected to refactor a module or add some needed infrastructure. 
	2. After each plan step is performed, be sure to update your context with the results and the resulting change to the project.
		1. For mod-cycle steps, always use git-diffs to see what parts of the project's *core planning docs* have changed. The core planning docs reflect the actual resultant state of the project after a mod cycle. Keeping abreast of changes to core planning docs ensures that surprises can't sneak by you (e.g. decisions silently made by the subagent) and that an accurate map of the project's code is always present in context. Project-map context rot is thus avoided by recency bias.
4. **Report**
	1. Write a report summarizing the advance to `report.md`.
	2. End turn and report to the operator that the advance has completed:
		1. Give them a concise summary of the report.
		2. Tell the operator that the work is complete and they may now proof the result if they wish.
		3. If merging and releasing wasn't part of the plan, then ask the operator if they'd like you to perform the final merge and version release.
	3. If the operator does request a final merge, then:
		1. Check that the working directory is clean.
		2. Increment the project version in adherence with semver standards.
		3. Merge the advance working branch back into main with `./bin/docex merge`.
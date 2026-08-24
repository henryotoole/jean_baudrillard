# Advance 009 — Test Overhaul: Advance Plan

Design rationale for every choice below lives in [`pre_plan.md`](./pre_plan.md)
(systemic changes SC1–SC5, features F1–F7, all resolved). This plan does not
restate that reasoning; it turns it into goals and a mod sequence. Cite the
pre-plan section, don't duplicate it.

**This advance touches two layers.** It changes docex's own *source* (real mod
cycles on the docex codebase, oriented by the `docex-edit` skill) **and** the
*doctrine prose* docex implements (`tests.md`, `cicl.md`, `infrastructure.md`,
`lexicon.md`, `shape.md`, `configurable.md`, plus practice files). The doctrine is
*upstream* of docex — its spec — not docex's own core planning docs. Handling
rule for the whole advance: **each mod lands the doctrine-text amendments for the
systemic change it implements** (the way a normal mod updates core planning
docs), and a single [`cohere`](../../../../doctrine/doctrine.md#skills) pass at
close-out validates cross-file consistency and link integrity. docex's *own* core
planning docs are reconciled by `project-cohere` at close-out.

---

# Goals

## Goal 1 — Long-running test runs decoupled from call limits

Suite runs (6–26 min on large projects) must stop colliding with an agent's
per-call wall-clock limit and stop orphaning containers. Realized by F3 + F4 on
the SC3 substrate.

### Success Criteria
1. `docex test --detach` returns a run handle in under ~5 s; `docex job
   status|wait|logs|result <h>` operate on it.
2. A `docex test` whose foreground monitor is **killed** leaves the run alive and
   re-attachable (verified: kill the monitor, then `docex job ls` finds the run
   and `docex job wait <h>` returns the real result — no re-run). `job ls` is the
   durable, non-fragile discovery path (no `pgrep` / `docker ps` proxy).
3. A second suite run against the **same slot** refuses rather than contending
   (deterministic-name lock), verified by launching two and observing the refusal.
4. An orphaned run (hard-killed vessel) is reaped by the next invocation's
   preflight; the run leaves an authoritative `exit` file read by `job result`.

## Goal 2 — A blessed fast inner loop for iterating on tests

A sanctioned way to run a subset, with the no-infra tier running with no stack at
all. Realized by SC1 (tier split) + F5 (scoped/two-mode).

### Success Criteria
1. The tier contract is **two shims** — `test_unit.sh` and `test_integration.sh`
   — and `docex check` asserts both exist. `contract` tests run under
   integration.
2. `docex test unit [subset]` runs the no-infra tier in a throwaway container
   with **no compose stack** brought up (verified: no stack containers created).
3. `docex test integration [subset]` runs stack-backed; a subset (tier + path /
   marker) runs only the named tests.
4. tests.md and the `testing` skill document the two modes and the injected shard
   contract.

## Goal 3 — CI/CD stops paying known-wasted test time

Realized by F1 + F2.

### Success Criteria
1. `docex merge` with broken git auth exits non-zero in seconds, naming the auth
   problem, **without building an image or running any test** (`git ls-remote`
   preflight). The defensive check never runs against stale `main`.
2. docex output redirected to a file reads in **true chronological order**
   (unbuffered): a narration line that precedes a subprocess block in code
   precedes it in the file.
3. `docex merge` **skips** the defensive recheck when `origin/main` and the
   feature tip sit at the commits the last successful `check` recorded, the tree
   is clean, and the docex version matches — and **runs the full recheck** on any
   staleness. Both branches verified.

## Goal 4 — The integration tier shards across parallel test slots

Realized by F7 on the SC2 slot axis.

### Success Criteria
1. `docex test --slots N` brings up **N fully-isolated** test stacks (every
   physical resource name carries the slot segment) and runs the integration tier
   sharded via injected `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS`; the unit tier runs
   once.
2. **Default is byte-identical:** `--slots 1` (or omitted) produces compiled
   output diff-identical to today (verified by `git diff` on `infra/output`).
3. The slot primitive is **env-agnostic** in the compiler but the CLI exposes it
   **only for `test`** this advance.
4. A crashed slot is reaped on the next preflight; the latent `check
   --project-name` DB-volume collision is closed.

## Goal 5 — Test scope is a policy-governed choice in mod cycles and advances

Realized by F6 + SC5 (process stratum).

### Success Criteria
1. `modifications.md`, `advance.md`, and the `mod-developer` / `doctrine-advance`
   agent definitions encode the policy: iterate with scoped runs; a mod's test
   step **closes** on full `unit` + relevant `integration`; an **advance closes
   with a full run**; CI/CD is **always full**.
2. No computed "affected" selector ships; scope is agent judgment via the F5
   mechanism.

---

# Tactical Plan

All mod-cycle steps are driven by the **`jean-baudrillard:corporal:mod-developer`**
corporal and, being docex-source work, load the **`docex-edit`** skill (plus
`infra-compile` where the compiler/`infra.yml` is involved). Steps that are pure
doctrine/agent prose are noted as such. Waves follow the pre-plan sequencing; the
cut rationale is given only where a split is non-obvious.

### Wave 1 — cheap, independent

1. **Mod: merge QoL (F1).** corporal.
   `git ls-remote origin` preflight at the top of `merge`; run docex unbuffered
   (`python -u` / `PYTHONUNBUFFERED=1`). Doctrine: touch `cicd.md` / `docex.md`
   only if the preflight changes documented behavior. First because it is
   independent, safe, and the unbuffered fix makes every *later* mod's logs
   readable. Design detail: [pre_plan F1](./pre_plan.md#f1--merge-qol-auth-preflight--unbuffered-output-small-non-systemic).

2. **Mod: the unit/integration tier contract (SC1).** corporal.
   Split the test contract into `test_unit.sh` / `test_integration.sh`; make
   `docex check` assert both; fold `contract` into integration. Doctrine:
   `tests.md` (§Codebase Tests — the "one test.sh" line), `hex_overview.md
   §Tests`, `cicd.md §Build-Test-Step`, `docex.md`.
   → **Cut rationale:** foundational vocabulary that F5 (Wave 2) and F7 (Wave 3)
     both build on, so it is established once, early. The intermediate state
     (`docex test` runs both shims sequentially in one stack, as today) is
     coherent even before the fast lane exists.
   Design detail: [pre_plan SC1](./pre_plan.md#sc1--the-unitintegration-split-becomes-operational-not-just-documentary).

### Wave 2 — the async keystone

3. **Mod: the `job` substrate + `docex test` as its first vessel (F3 core; SC3).**
   corporal.
   Build the general job abstraction: `.docex/runs/` run records, the exit-file /
   `status.json` signals, `docex job ls|status|wait|logs|result` (`ls` shares the
   reaper's enumeration primitive), the `--detach` launch wrapper; make `docex
   test` a durable job with the **container vessel**
   and the deterministic-name lock. Folds in **F4's single-run self-heal reaper**
   (the lock falls out of the name; the basic reaper is inherent to owning the
   vessel — the *fleet* reaper is deferred to Wave 3). Add `.docex/` to gitignore
   via `docex_install.sh`. Doctrine: new command-lifecycle section in `docex.md`;
   cite `healthchecks.md` / `internal_dependency_rules.md` as the liveness
   precedent.
   → **Cut rationale:** the keystone everything else routes through; large enough
     to own a mod. F4's basic lock/self-heal rides here because it is the same
     territory (the vessel's lifecycle); its multi-slot generalization is Wave 3.
   Design detail: [pre_plan SC3 Resolved design](./pre_plan.md#resolved-design).

4. **Mod: convert `check` / `merge` onto the job substrate (SC3).** corporal.
   Make `check`/`merge` `--detach`-able jobs with the **host-process vessel**.
   Depends on Mod 3. Doctrine: `docex.md` / `cicd.md` surfaces.
   → **Cut rationale:** boundary condition 6 ("not a test-only bolt-on"); split
     from Mod 3 because the host-process vessel is a distinct concern and the two
     together would breach the context ceiling. Verification gate: check/merge
     must still pass as jobs before recheck-skip logic lands on them (Mod 5).

5. **Mod: redundant-recheck elimination (F2; SC4).** corporal.
   `check` writes the `.docex/checks/` provenance record `{feature_tip,
   origin_main, merged_tree_sha, checked_at, docex_version}` on success; `merge`
   applies the commit-based skip predicate with the safe-default full recheck.
   Depends on Mod 4 (shared check/merge territory — sequenced adjacent to avoid
   churn). Doctrine: `cicd.md §Check` + `§Merge`.
   Design detail: [pre_plan SC4](./pre_plan.md#sc4--a-pipeline-green-acquires-provenance--the-gate-becomes-trust-forward).

6. **Mod: scoped runs + two honest modes (F5).** corporal.
   Wire the differential execution: `docex test unit` → no-stack throwaway
   container; `docex test integration [subset]` → stack-backed; subset scoping
   (tier / path / marker). Builds on Mod 2 (tiers) + Mod 3 (job substrate).
   Doctrine: `tests.md` (two modes + injection contract), `testing` skill.
   Design detail: [pre_plan F5](./pre_plan.md#f5--standard-scoped-runs--two-honest-modes-medium-rides-on-f3).

### Wave 3 — the slot axis (F7; SC2)

7. **Mod: the env-agnostic slot primitive in the compiler (SC2).** corporal
   (+`infra-compile`).
   Thread `slot=k` through name interpolation (`compile.py`) and output-dir
   layout; **default slot 1 emits no suffix**. Land the SC2 doctrine amendments as
   the *general slot framing* (not a test-only carve-out): `infrastructure.md`
   (four-env → slot axis; promote out of §Deferred), `lexicon.md` (`Environment`),
   `configurable.md`, `shape.md` — each naming parallel-dev as the next slot user.
   → **Verification gate:** `--slots 1` output must be proven **byte-identical**
     (`git diff` clean on `infra/output`) before any N>1 work builds on it.
   Design detail: [pre_plan SC2](./pre_plan.md#sc2--a-fixed-env-may-be-instantiated-into-multiple-slots-the-four-env-symmetry-is-amended).

8. **Mod: re-tier the `test` web network (F7 §4).** corporal (+`infra-compile`).
   `emit/compose.py`: the `test` web network becomes an env-tier, per-slot,
   non-external bridge (finishing Mod 054), removing `test`'s last projinfra
   dependency and subsuming the `check --project-name` collision.
   → **Verification gate:** a **single** test slot must still work (any flow test
     reaching the live `-web` container over HTTP still passes) before fan-out.

9. **Mod: `docex test --slots N` orchestration + fleet reaper + shard injection
   (F7).** corporal.
   `orchestrate/test.py`: the N-slot loop (compile + up + migrate + run per slot),
   inject `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS`, `finally`-teardown, keep-failed-
   slot-up for debug, and the **deterministic-slot reaper** (generalizing Mod 3's
   single-run reaper). Depends on Mods 6, 7, 8. Doctrine: `tests.md` shard
   contract (recommend-but-not-mandate split/tier pattern).
   → **Cut rationale:** F7 is split into 7/8/9 on its two internal verification
     gates (byte-identical default; single-slot-still-works) and by territory
     (compiler vs emitter vs orchestrator); the combined diff would breach the
     context ceiling.

### Wave 4 — process policy

10. **Doctrine/process edit: test-selection policy (F6; SC5).** corporal (prose
    mod, not a code cycle).
    Encode the policy into `modifications.md`, `advance.md`, and the
    `mod-developer` / `doctrine-advance` agent definitions + `testing` skill:
    iterate scoped, close full; advance closes full; CI/CD always full. No
    computed selector. Depends on Mod 6 (the scoping mechanism must exist).
    Design detail: [pre_plan SC5](./pre_plan.md#sc5--test-scope-becomes-a-first-class-decision-carried-by-the-process-strata).

---

# Close-out

11. **`cohere`** — doctrine coherency pass over every amended file (dangling
    links, cross-file contradictions introduced by the SC amendments, moved
    sections). Run once, after all mods land. corporal.
12. **`project-cohere`** — reconcile docex's *own* core planning docs against the
    delivered source. Run once. corporal. (Two distinct passes: `cohere` for the
    doctrine spec, `project-cohere` for docex's project docs.)
13. **Verify + close.** Run docex's full own test suite (green), then **manually
    exercise the new surfaces** against a scratch test project: `docex test
    --detach` + `docex job wait`; a killed-monitor re-attach; `docex test unit`
    with no stack; `docex test --slots 2` sharded + reaped; a `merge` auth-fail
    fast-exit; a recheck-skip and a recheck-forced case. Merge + release are
    **out of scope** for this planning exercise — offer them per Advance process
    step 4 when the real run completes.

---

# Blockers / notes for the operator

- **No external blockers** (no API keys, no third-party infra) — this is
  self-contained doctrine + docex work.
- **`.docex/` is a new machine-local artifact.** Mod 3 must add it to gitignore
  via `docex_install.sh`; existing installs pick it up on the next
  `docex_install.sh` re-run.
- **Breaking contract change:** the two-shim split (Mod 2) means every downstream
  project must ship `test_unit.sh` / `test_integration.sh`. This wants a
  project-upgrade guide and a doctrine-wide version bump — flag for the release
  that follows this advance (out of scope here, but named so it isn't a surprise).
- **Sequencing is provisional.** Per Advance process step 3, plans change:
  design surprises inside Mod 3 (the job substrate) or Mod 7 (the compiler slot
  thread) are the most likely to inject an extra refactor mod.

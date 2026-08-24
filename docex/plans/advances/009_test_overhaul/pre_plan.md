# Advance 009 — Test Overhaul: Pre-Plan

This document is the pre-plan for the test-overhaul advance. It sits between the
raw problem notes (now in [`prep/`](./prep)) and the eventual advance plan. It
does two things:

1. Names the **systemic changes** (SC) — the load-bearing doctrine invariants
   this advance deliberately breaks or amends. These set the *blast radius*.
2. Enumerates the **features** (F) — the concrete units of change — and maps each
   to the systemic change(s) it lives under.

The features stay; the systemic-change layer exists to make explicit *what
conceptual pillars we are moving* before any mod is scoped, so the advance is
planned with eyes open rather than discovering the blast radius mid-flight.

## Source material

The problem statements this pre-plan is built from live in [`prep/`](./prep):

- [`preamble.md`](./prep/preamble.md) — the top-level catalogue of pain points.
- [`docex_test_command_monolith_limitations.md`](./prep/docex_test_command_monolith_limitations.md)
  — boundary conditions for the async runner, mined from ~485 `nasmyth`
  transcripts.
- [`parallel_test_env_proposal.md`](./prep/parallel_test_env_proposal.md) — the
  `env_number` sharding-axis proposal.
- [`redundant_merge_recheck.md`](./prep/redundant_merge_recheck.md) — skipping
  the doubled CI/CD check.
- [`docex_qol_merge.md`](./prep/docex_qol_merge.md) — the merge auth-preflight
  and log-ordering QoL fixes.

## The root cause, in one line

The doctrine only blesses *"run the entire suite, synchronously, on the one
shared `test` stack."* Invisible on a small project; on a project with 6–26 min
suites it produces hand-rolled backgrounding, orphaned containers racing over
shared infra, doubled CI/CD cost, and no sanctioned way to run one failing test.
Every symptom traces to that single blessed shape being too coarse.

## Settled decisions

These were resolved during pre-planning and are treated as fixed inputs to the
plan:

- **F7 (parallel test environments) is in scope for this advance** — not a
  follow-on.
- **`check` and `merge` convert to callers of the async runner now** — the async
  model is the substrate, not a `test`-only bolt-on (boundary condition 6).
- **The execution-tier vocabulary is `unit` / `integration`** (flow is a subset
  of integration). The conceptual 5-tier taxonomy is unchanged; it *maps onto*
  these two execution classes.
- **The only execution distinction is needs-infra vs not.** `contract` folds
  into `integration` (it needs a container ⇒ integration). No third execution
  class — a finer split is a later refinement if a project ever feels the pain,
  and none has.
- **The tier split is realized as two separate shim files**
  (`test_unit.sh` / `test_integration.sh`), not one shim taking a tier argv — two
  files are clearer and less error-prone than four branches of a `case`.
- **The multiplicity axis is a general "slot", not a test-only feature.** The
  compiler primitive that lets N isolated stacks of one fixed env coexist on one
  host is built **env-agnostic** (`compile(env, slot=k)`, `infra/output/{env}/…`),
  but **exposed only for `test`** this advance. It is deliberate, named
  groundwork for future **parallel development** (two agents on different mods,
  one machine). See **SC2** below.
- **The async surface is a general `job` abstraction**, not per-command verbs:
  any long command runs `--detach` → handle, and `docex job ls|status|wait|logs|
  result` operates on handles uniformly (covers `test`/`check`/`merge`);
  `job ls` provides durable, non-fragile run discovery. The
  handle is an on-disk run record under `.docex/runs/`; the vessel is polymorphic
  (container for `test`, host process for `check`/`merge`); the deterministic
  container name is the lock (no flock). See [SC3](#sc3--some-docex-commands-become-async-stateful-lifecycle-managed).
- **docex gains a `.docex/` machine-local scratch dir** (gitignored) as the
  single home for local state — `.docex/runs/` (SC3) and `.docex/checks/` (SC4).
- **The recheck-skip predicate is commit-based** (SC4): `merge` skips iff
  `origin/main` + feature tip are at the recorded commits, tree clean, docex
  version matched; any staleness forces the full recheck.
- **Test scope is chosen by judgment via the F5 mechanism** (SC5), not a computed
  selector; docex defines policy (iterate scoped, close full; advance closes full;
  CI/CD always full).
- **SC4 and SC5 are accepted as genuinely systemic**, not merely features.

---

# Systemic Changes

Each systemic change is stated as: the **invariant broken**, the concrete
**blast radius** (which doctrine files / concepts move), the **features** that
live under it, and any **open decision** it still forces.

## SC1 — The unit/integration split becomes *operational*, not just documentary

**Invariant broken.** Today the test taxonomy (domain / alogic / adapter /
module-integration / flow / contract) is rich but **documentary** — a way to
reason about coverage. For *execution* it collapses to one rule
([`tests.md`](../../../../doctrine/infrastructure/tests.md) line 17: *"Unit,
integration, and contract tests should all be run by the standard test
script"*): one `test.sh` per codebase, one way, one place (fresh `test` env).
The moment unit tests must run with **no stack** (instant) and integration tests
run **against real backing services** (and are the shardable tier), the taxonomy
stops being documentary and starts **determining invocation, environment,
parallelization, and locking**.

**Consequences.**
- The 5 conceptual tiers map onto **two execution classes**: `unit` (no-stack
  fast lane) and `integration` (stack-backed). Flow is a subset of integration.
- The `test.sh` contract changes to **two shims** — `test_unit.sh` and
  `test_integration.sh` — decided above.
- Every project gains a **new way to be wrong**: misclassifying a test into the
  wrong execution class (a "unit" test that secretly needs the DB; an
  integration test parked in the fast lane).
- The docex↔project boundary may widen with a new **injected coordination
  contract** on the [stagetest injection](../../../../doctrine/infrastructure/tests.md#injected-environment)
  model (one-way, stable; adding to it is a doctrine change). SC1 owns this
  dimension; F7's shard-distribution vars (`DOCEX_TEST_SLOT` / `_SLOTS`, renamed
  from the proposal's `_INSTANCE` per the slot framing) are its first example.

**Blast radius.** [`hex_overview.md §Tests`](../../../../doctrine/hexagonal_architecture/hex_overview.md#tests),
[`tests.md`](../../../../doctrine/infrastructure/tests.md),
[`cicd.md §Build-Test-Step`](../../../../doctrine/infrastructure/cicd.md#build-test-step),
[`docex.md`](../../../../doctrine/infrastructure/docex.md) (`test`, `check`), the
check step's shim-existence assertion, the `testing` skill.

**Resolved.** `contract` folds into `integration`. The only execution
distinction worth drawing now is **needs-infra vs not**; contract tests spin a
provider server / mock inside a container, so they are on the needs-infra side.
No third execution class — a finer split is deferred until a project feels the
pain (none has).

## SC2 — A fixed env may be instantiated into multiple **slots**; the four-env symmetry is amended

**Invariant broken.** The doctrine asserts *"every project has exactly four
environments"* and *"all environments as similar as possible"* across
[`infrastructure.md`](../../../../doctrine/infrastructure/infrastructure.md), the
[lexicon](../../../../doctrine/lexicon.md) `Environment` definition,
[`configurable.md`](../../../../doctrine/infrastructure/configurable.md),
[`cicd.md`](../../../../doctrine/infrastructure/cicd.md), and
[`shape.md §Shape and Environment`](../../../../doctrine/infrastructure/shape.md).
F7 shards `test` into N stacks; and even without F7 the warm/kept-hot fast lane
uses `test` in a way no other env is. `test` accumulates disqualifying
differences: never TLS'd, never routed (Mod 054), soon owns its own web network
(F7 §4 re-tiers it out of projinfra), can be kept hot, and **can exist as many
stacks at once**.

**The general primitive: the "slot".** The right frame is not "`test` is
special." It is that a **fixed env may be instantiated into multiple isolated
*slots* on one host** — the k-th slot of env E scopes every physical resource
name (`{project}_{env}_{k}_{codebase}_{service}`), analogous to `replicas` but at
the environment level. Default is slot 1, which emits **no** suffix, so existing
output is byte-identical until someone asks for parallelism. This is the correct
general fix for *"N isolated stacks of one project coexisting on one host without
name collisions,"* and it **subsumes the latent `docex check --project-name`
collision bug** (compose only re-prefixes auto-named resources, missing the
explicit `name:` / `container_name` fields; the slot segment namespaces *all* of
them). See [§ Slots as parallel-dev groundwork](#slots-as-parallel-dev-groundwork).

**Consequences.**
- "Environment" must admit a **slot axis**. The containment that keeps it cheap:
  the env *string* stays `test`; only a slot *number* is added as a physical-name
  segment, so config/secrets/foundation lookups (`infra/<kind>/test.env`,
  `_env_foundation("test")`) stay singular.
- The compiler primitive is built **env-agnostic** (`compile(env, slot=k)`,
  generic output layout), but the CLI **exposes slots only for `test`** this
  advance. This is the cheap forward-compatibility that makes parallel dev a
  later slot-in rather than an unwind.
- [`infrastructure.md §Deferred`](../../../../doctrine/infrastructure/infrastructure.md#deferred)'s
  "heavier test topology" is promoted out of Deferred; parallel development is
  named there as the next user of the slot axis.

**Blast radius.** `infrastructure.md`, `lexicon.md`, `configurable.md`,
`shape.md`, `cicd.md`; in docex: `compile.py` name interpolation,
`emit/compose.py` (web-network re-tiering), `orchestrate/test.py`, output-dir
layout.

### Slots as parallel-dev groundwork

Parallel development — two agents working different mods on one machine — is a
future capability with a large blast radius of its own. We do **not** scope it
into this advance, but the slot axis is deliberately designed to lay its
groundwork. Parallel dev needs **three** isolation axes; the slot axis is the
first and the one worth building now:

| Axis | Isolates | Shared with test-sharding? |
| --- | --- | --- |
| **1. Runtime-name isolation** (the slot segment) | container / volume / network names | **Yes — this is what we build now.** |
| **2. Code isolation** (git worktrees) | each agent's working tree / branch / `dist/` | No — orthogonal, net-new, but cheap (git already does it) |
| **3. Ingress multiplicity** (routing / DNS / cert per slot) | who owns `api-web.dev.…` | No — net-new and genuinely hard |

Parallel dev = **worktree × slot**; test-sharding = **one tree × N slots**. Same
slot primitive, different second factor. Two honest divergences bound how far the
groundwork carries:

- **Lifecycle is opposite.** Test slots are fungible, anonymous, dense `1..N`,
  aggressively **reaped** — a stack with nothing running against it is garbage.
  A parallel-dev slot is *owned* by an agent on a branch and must **survive**
  precisely when idle. Same name / lock primitive, antithetical ownership policy.
  **Non-goal now:** do not generalize the lifecycle / reaper model — test's is
  right for test and wrong for dev.
- **`dev` is routed; `test` is not.** F7 can cheaply re-tier `test`'s web network
  to a per-slot non-external bridge *because* `test` is never browsed or TLS'd
  (Mod 054; excluded from the dev-DNS preinfra check). `dev` resolves in public
  DNS with real HTTP-01 certs and live traefik labels, so two `dev` slots collide
  on `api-web.dev.…` — pushing the slot segment *up* into the domain / cert /
  traefik layer (the opposite direction from where F7 pushes `test`'s network).
  **Non-goal now:** ingress multiplicity is untouched. Note a useful fork for the
  future: *headless* parallel dev (run code + tests, no browsing) barely needs
  axis 3 and nearly falls out of the slot axis directly; only *browsable*
  parallel dev needs the hard ingress work.

**Resolved.** Amend the four-env doctrine with the **general** slot framing, not
a test-only carve-out: environments are singletons by default, but a **fixed env
may be instantiated into multiple isolated slots on one machine**; `test` is the
first and only user this advance (shard parallelism), and this is explicitly the
named groundwork for future `dev` parallelism. Build the compiler / naming / lock
primitive env-agnostic; expose it only for `test`. Two explicit non-goals now:
generalizing the slot lifecycle model, and ingress multiplicity.

## SC3 — Some docex commands become async, stateful, lifecycle-managed

**Invariant broken.** Every docex command today is synchronous: run, block,
exit-code, forget ([`docex.md`](../../../../doctrine/infrastructure/docex.md)'s
whole mental model). F3 introduces the first command whose **run outlives the
invoking call** — a durable handle with separate `status`/`wait`/`logs`/`result`
verbs — and F4 adds **mutual-exclusion state** (a per-`(project, env[, slot])`
lock) over shared infra. docex acquires a category of thing it has never owned:
persistent run state.

**Consequences.**
- docex needs somewhere durable run-state lives (a run record + exit-file +
  observable progress). Boundary condition 3 mandates **reusing the existing
  liveness pattern** —
  [`healthchecks.md`](../../../../doctrine/infrastructure/healthchecks.md#what-the-probe-must-actually-check)'s
  touched-file / exit-file mechanism and
  [`internal_dependency_rules.md §Entrypoints rule 6`](../../../../doctrine/hexagonal_architecture/internal_dependency_rules.md#entrypoints)
  — rather than inventing a parallel notion.
- `check` and `merge` convert to **callers** of this substrate (settled above).
- The doctrine currently trains agents to expect blocking; it must retrain them
  (docex.md, testing skill, the mod-developer / advance agents).

**Blast radius.** `docex.md` (new command-lifecycle section + the `job` surface +
`test`/`check`/`merge` surfaces), `cicd.md`, the `./bin/docex` shim (must stay
additive / backward-compatible per its own rule), `healthchecks.md` +
`internal_dependency_rules.md` (cited as the liveness precedent), the `testing`
skill, `docex_install.sh` (ensure `.docex/` is gitignored).

### Resolved design

**D1 — a general job abstraction.** Any long command launches detached and
returns a handle; one uniform verb set operates on handles. Not a `test`-only
bolt-on — it covers `test`, `check`, `merge` (and future `release`/
`containerize`) uniformly, which is the honest reading of boundary condition 6.

```
docex test              # blocks + attaches + exits with the run's code (durable underneath)
docex test --detach     # -> handle, returns immediately
docex check --detach    # -> handle (host-process vessel)
docex job ls            # enumerate all runs (id, kind, scope/slot, state, started, exit)
docex job wait   <h> [--timeout S]
docex job status <h>    # reads status.json
docex job logs   <h>
docex job result <h>    # reads the exit-file
```

`job ls` is what makes runs **discoverable** — a killed / compacted agent, or a
fresh one inheriting an in-flight run, recovers the handle here rather than via a
fragile `docker ps` / `pgrep` proxy. It reads the `.docex/runs/` records and
reconciles each against its vessel's liveness, which is the **same enumeration
the reaper performs** (an orphan = a record whose vessel is dead with no `exit`
file), so the two share one primitive.

The **blocking default is preserved** (exit-code contract intact for CI) but
creates a durable run underneath — so a killed foreground `docex test` leaves the
run **alive and re-attachable** (`docex job wait <h>`) instead of orphaned. That
single property kills the largest observed pain (25 killed-and-relaunched runs)
and applies to the default path, not just `--detach`.

**D2 — handle is an on-disk run record; vessel is polymorphic.** The general,
vessel-agnostic handle is a record under `.docex/runs/<id>/` (`meta.json`,
`status.json`, `exit`, `log`). The *vessel* underneath differs by kind — `test`
→ a detached, deterministically-named container + its compose stack; `check`/
`merge` → a detached host process owned by docex. Record-as-handle is what lets
one `job` surface span both.

**D3 — observable signals reuse the exit-file half of the healthcheck pattern.**
An atomically-written **`exit` file** is the authoritative terminal signal
(survives vessel teardown + a killed monitor; read by `job result`). A
**`status.json`** (state / progress / timestamps) plus vessel-liveness
(`docker inspect .State.Running` or pid-alive) drives `job status`. These are
non-fragile signals keyed on an owned resource — the replacement for the
`pgrep -f "docex check"` proxy that broke under concurrency. **Deferred to a
later refinement:** the healthcheck tick/staleness mechanism for *wedged-suite*
detection — a finite job differs from a perpetual loop, and a watching agent can
kill a hang.

**D4 — run-state lives in `.docex/`.** A new machine-local, gitignored scratch
dir at project root — explicitly *not* `infra/output/` (that is git-tracked
compiled output; run-state is ephemeral and machine-local). This is the single
home for docex local state and **unifies with SC4**: `.docex/runs/` (SC3) and
`.docex/checks/` (SC4) are the same kind of thing (ephemeral, degrade-safe if
missing).

**D5 — the deterministic container name is the lock (no flock).** `docker run
--name` fails if the name exists, so the second concurrent run on the same
`(project, test, slot)` loses the create race **atomically** — that *is* the
mutex. A flock would be wrong here (held by the launching process, which the
detached run outlives). The **reaper** (F4) clears the dead-orphan case
(name exists but vessel exited → reap, then create). One primitive — the
deterministic name — serves **vessel + lock + reap** together; different slots
never collide (the F7 payoff). This lock/name primitive is also the one parallel
dev reuses (SC2), with the opposite lifecycle policy.

## SC4 — A pipeline "green" acquires provenance — the gate becomes trust-forward

**Invariant broken.** Every gate result today is **stateless**: `check` runs,
passes, forgets. F2 requires `check` to **record what it validated** (trunk
commit + tree fingerprint) and `merge` to **trust that record** and skip the
redundant recheck when nothing moved. "Check passed" changes meaning from *"true
at the instant it ran"* to *"true, recorded, and reusable under stated staleness
conditions."* A green now has **identity and provenance**.

**Why systemic, not just a feature.** It establishes a *caching / provenance
principle* in the pipeline that, unbounded, is a correctness footgun (trusting a
stale green). The mitigation is doctrinal and must be stated as such: *any*
staleness — trunk moved, tree dirty, no trusted record — forces the full rerun;
the safe default is always to run.

**Blast radius.** [`cicd.md §Check`](../../../../doctrine/infrastructure/cicd.md#check-step)
+ [`§Merge`](../../../../doctrine/infrastructure/cicd.md#merge),
[`docex.md`](../../../../doctrine/infrastructure/docex.md). New artifact: the
check-result record.

**Resolved.**
- **Where:** `.docex/checks/` (SC3-D4), machine-local and gitignored — a
  performance cache; a missing/unreadable record degrades safely to "run the
  check."
- **What it records:** `{feature_tip, origin_main, merged_tree_sha, checked_at,
  docex_version}` — written by `check` only on success. `merged_tree_sha` (the
  git tree SHA of the validated merged worktree) is the authoritative "what was
  tested," recorded for audit and a possible future stronger comparison.
- **Skip predicate (commit-based):** `merge` skips the defensive recheck iff
  `origin/main` **and** the feature tip are at the recorded commits, the working
  tree is clean, **and** the docex version matches. Cheap (two `git rev-parse`)
  and sufficient — identical inputs deterministically produce identical content.
- **Invariant rule (doctrinal):** *any* staleness — trunk moved, feature moved,
  tree dirty, no record, unreadable record, docex-version mismatch — forces the
  full recheck. Never skip on doubt. This artifact is distinct from the SC3 job
  record: `runs/` = "did this invocation pass"; `checks/` = "what tree a passing
  check blessed, for `merge` to trust forward."

## SC5 — Test **scope** becomes a first-class decision carried by the process strata

**Invariant broken.** "Run the tests" is atomic and total everywhere in the
process doctrine. F6 makes **full-vs-affected a standard, sanctioned choice** —
so the *mod cycle* and the *advance* now carry a test-scope decision as part of
their state, with a hard rule: *an advance must close with a full run; CI/CD is
always full*. This is a shift in the **practice/process stratum**, distinct from
the infra-layer shifts above.

**Blast radius.** [`modifications.md`](../../../../doctrine/practices/modifications.md),
the advance doctrine, the `mod-developer` and `doctrine-advance` agent
definitions, the `testing` skill. Depends on SC1/F5 existing (no subset selection
until subsets are blessed).

**Resolved.** v1 is **judgment via the F5 mechanism**, not a computed selector.
docex offers the subset mechanism (tier / path / marker); the agent — who just
wrote the diff — chooses the scope. docex defines only **policy**:
- A mod cycle may iterate with scoped runs, but its test step **closes** on the
  full `unit` tier (cheap, no stack) plus the relevant `integration` tests.
- An **advance must close with a full run of both tiers** across the project.
- CI/CD (`check`/`merge`) is **always full**.

"Affected" stays a judgment, not an artifact. **Deferred and why:** a structural
path-mirror convenience (`docex test --changed`, mapping changed `src/` paths to
mirror `tests/` paths) is tempting but untrustworthy as "affected" — cross-module
driving-port imports, `shared/` blast radius, and domain changes with no mirror
give false confidence. A true dependency-graph selector violates "docex never
parses tests" and is deferred outright. Synergy worth noting: "close with full
`integration`" is made affordable precisely by **F7 sharding**.

---

# Features

The concrete units of change. Each names its source note and the systemic
change(s) it lives under. Rough size in parentheses.

## F1 — Merge QoL: auth preflight + unbuffered output *(small; non-systemic)*
Source: [`docex_qol_merge.md`](./prep/docex_qol_merge.md). Under: *none* — pure
bug-fix/QoL inside the existing synchronous model.
- Fail-fast `git ls-remote origin` preflight at the top of `merge` (kills the
  ~34-min-then-auth-die waste), which also closes the latent "defensive check ran
  against stale `main`" correctness gap for free.
- Run docex unbuffered (`python -u` / `PYTHONUNBUFFERED=1`) so narration and
  subprocess output interleave in true chronological order.
- This is the safe wave-1 work; unbuffered output also pays off again as a
  prerequisite for readable async logs under SC3.

## F2 — Redundant-recheck elimination *(medium)*
Source: [`redundant_merge_recheck.md`](./prep/redundant_merge_recheck.md). Under:
**SC4**.
- `check` records, on success, the trunk commit + tree it validated.
- `merge` skips its defensive recheck when trunk hasn't moved and the tree is
  clean; falls back to full recheck on any staleness. Saves the doubled ~30 min.

## F3 — Async, re-attachable test runner *(large — keystone)*
Source: [`docex_test_command_monolith_limitations.md`](./prep/docex_test_command_monolith_limitations.md).
Under: **SC3** (and needs **SC1** to know which class it is running).
- Split the blocking monolith into `launch → status → wait → logs → result` over
  a durable, named run (fixed container name + exit-file + observable progress).
- A killed monitor never kills the run; blocking-until-done becomes a caller's
  `wait` choice.
- `check` and `merge` become callers of this substrate.

## F4 — Concurrency lock + orphan reaper *(small–medium; rides on F3)*
Source: [`preamble.md`](./prep/preamble.md) problem 1 + boundary condition 7.
Under: **SC3** (and **SC2** — the lock is per project+env+slot).
- Per-`(project, env[, slot])` single-run lock; a second concurrent run refuses
  rather than silently contending.
- Preflight reap of orphaned test containers so a hard-killed run self-heals.
- Built as the first increment of F7's deterministic-slot reaper.

## F5 — Standard scoped runs + two honest modes *(medium; rides on F3)*
Source: [`preamble.md`](./prep/preamble.md) problem 5 + boundary conditions 4/5.
Under: **SC1**.
- A blessed way to run a **subset** for iteration (what agents hand-roll raw
  `docker run` for today).
- Two first-class modes: **fast iteration** (no-stack `unit` lane / warm
  stack) vs the **formal fresh-throwaway-`test` isolation** guarantee.
- Scope vocabulary is the doctrine's own tiers (`unit` / `integration`), not raw
  framework paths.

## F6 — Mod-cycle & advance test-selection policy *(doctrine-process; rides on F5)*
Source: [`preamble.md`](./prep/preamble.md) problem 2. Under: **SC5**.
- Make full-vs-affected an explicit, standard choice in a mod cycle.
- Require that an advance *closes out* with a full run; CI/CD always runs full.
- Touches `modifications.md`, the advance doctrine, the mod-developer /
  doctrine-advance agents + `testing` skill — not docex code.

## F7 — Parallel test environments (the **slot** axis) *(large; doctrine change)*
Source: [`parallel_test_env_proposal.md`](./prep/parallel_test_env_proposal.md)
(written as `env_number`; generalized to **slot** per SC2).
Under: **SC2** (primary), **SC1** (shard only the slow tier), **SC3** (reaper).
- Shard the slow no-mock integration/flow tier across N isolated `test` stacks
  via an additive slot segment in physical names (default slot 1 emits no suffix).
- Re-tier the `test` web network to an env-tier, per-slot, non-external bridge
  (finishing what Mod 054 started).
- Subsumes the latent `check --project-name` DB-volume collision bug.
- Built on the env-agnostic slot primitive but exposed only for `test`; the CLI
  and injected shard contract stay test-scoped.

---

# Feature → Systemic-Change map

| Systemic change | Invariant broken | Features under it |
| --- | --- | --- |
| SC1 unit/integration operational split | taxonomy was documentary-only | F5 (primary), F7 (shard slow tier); F3 needs it |
| SC2 fixed env → N slots | four-env symmetry | F7 (primary), F4, F5 |
| SC3 docex commands async/stateful | commands were synchronous | F3, F4, check/merge conversion |
| SC4 green acquires provenance | gate was stateless | F2 |
| SC5 test-scope is a process decision | "run tests" was atomic/total | F6 |
| *(none)* | — | F1 |

# Suggested sequencing (not yet the plan)

- **Wave 1 — cheap, independent:** F1, F2.
- **Wave 2 — keystone:** F3, then F4 + F5 ride on it.
- **Wave 3 — parallelism:** F7 (needs F3's runner + F4's reaper + SC2 amendments).
- **Wave 4 — process:** F6 (needs F5's subset mechanism).

# Open decisions carried into the plan

**All five systemic changes are resolved.** Summary of resolutions:

- **SC1** — `contract` folds into `integration`; the only execution distinction
  is needs-infra vs not.
- **SC2** — a general **slot** axis (any fixed env may be instantiated into N
  isolated slots); env-agnostic primitive, exposed only for `test` this advance;
  named groundwork for parallel dev.
- **SC3** — a general `job` abstraction; handle = on-disk run record in
  `.docex/runs/`; exit-file is the authoritative signal; deterministic container
  name is the lock (no flock).
- **SC4** — record in `.docex/checks/` = `{feature_tip, origin_main,
  merged_tree_sha, checked_at, docex_version}`; commit-based skip predicate; any
  staleness forces full recheck.
- **SC5** — scope by judgment via the F5 mechanism; docex defines policy only;
  no computed "affected" selector in v1.

What remains is **not** a systemic-design question but the ordinary plan work:
turning the features (F1–F7) into scoped mods with wave sequencing, and the
downstream doctrine-text edits each systemic change implies.

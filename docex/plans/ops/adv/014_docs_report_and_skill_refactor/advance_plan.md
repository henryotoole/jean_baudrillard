# Goals

Advance 014 does two things that reinforce each other:

1. **Gets the doc-refine / cohere skill family onto `docex`** rather than each
   skill carrying its own executor code. Today `doc-refine-orchestration` drives
   `docex docs cxt_groups`, but `project-cohere` ships its *own* `chunk_map.py`
   and `word_count.py`. They solve overlapping problems two different ways, and
   the two chunkers diverge in grouping semantics (see
   [`cohere-chunker-not-obsolete` memory finding](#background-the-two-chunkers)).
2. **Gives us one holistic way to see the state of a project's docs and code** —
   a new `docex report` command whose first report type, `docs`, visualizes where
   the *token weight* of documentation and source code falls. This replaces the
   crude "word count before/after" instrument `project-cohere` uses today.

The full motivation and the informal report design live alongside this plan in
[`adv_014_prep.md`](./adv_014_prep.md) and
[`docex_report_design.md`](./docex_report_design.md). Read both before executing.

## Why the phasing is unusual

This advance is deliberately split into four sequenced phases with **hard gates**
between them, because ownership changes hand-to-hand:

| Phase | Owner | What |
| ----- | ----- | ---- |
| **A** | agent (mechanical) | Build the `docex report` command and extend `docex docs cxt_groups`. Pure docex-internal code work, fully specified, no judgement calls. |
| **B** | operator (solo) | Refactor the doc skills (`doc-refine`, `doc-refine-orchestration`, `project-cohere`) onto the new machinery. Sensitive skill-authoring work the operator does by hand. |
| **C** | agent + operator (together) | Rework the skill-testing / evaluation portion of the release process for the doc-refine-type skills. |
| **D** | agent (standard) | Fixed-foundation smoke test, then cut and release. |

Phase A must be **fully complete and merged-to-branch** before Phase B begins —
the operator's refactor consumes the finished `cxt_groups` behavior and the
`report` command as fixed contracts. Phase C cannot begin until Phase B's new
skill set exists (there is nothing to evaluate before then). Phase D closes.

This document specifies **Phase A** in full (it is the only agent-executable,
deterministic phase). Phases B, C, and D are specified as **intent, deliverables,
and gate contracts** — enough to hand off cleanly, not prescriptive step lists,
because their execution is the operator's or is jointly designed.

Continues mod numbering from advance 013 (last mod 174): next mod is **175**.
Target cut: **3.2.0** (minor — additive `report` command, backward-compatible
`cxt_groups` extension; the doc-skill refactor is conditional-stratum). The cut
decides the final number.

---

# Background: the two chunkers

Recorded finding (memory `cohere-chunker-not-obsolete`, verified on a real
finished-docs branch): `docex docs cxt_groups` and `project-cohere`'s
`chunk_map.py` are **not** redundant tools — they group by different axes:

- `cxt_groups` groups by **shared doc overhead**: it will scatter one hex module
  across several groups and mix codebases within a group. Ideal for **refine**
  (per-file prose edits), fatal for **cohere** (a module split across N subagents
  gives each a blind spot for that module's own features — worst for Class-3
  unimplemented-feature detection).
- `chunk_map.py` groups by **code bounded-context**: each hex module kept whole,
  codebases never mixed, plus code↔doc `hints`. Ideal for cohere.

The consolidation end-state is **one grouping engine with a pluggable mode**, not
two tools. Phase A delivers that engine (the `--optimize module_integrity` mode
on `cxt_groups`); Phase B rewires the skills onto it and retires `chunk_map.py`.

---

# Phase A — Mechanical (agent-owned)

Four docex-internal mods. The first three build the report/cxt_groups machinery;
the fourth (178) is a bundled-in bugfix for a network-orphan leak that bites
sharded runs and therefore must be fixed before Phase D exercises `--slots`. All
are docex-code (± doctrine) changes with aligned-artifact updates; none touches
foundation-specific behavior. Use the `docex-edit` skill for orientation.

## Mod 175 — `cxt_groups_depth_and_integrity`

Extend `docex docs cxt_groups <tokens_max> {<git_ref>|all>}` with two optional
args, both changing how groups are formed. Code lives in
[`src/docex/docs/cxt_groups.py`](../../../../src/docex/docs/cxt_groups.py); the
node metadata it needs (`level`, `codebase`, `module`, `type`, `tokens`) is
already produced by the shared linkmap builder.

### 175a — `--depth {design_docs | code_level}`

Mirror the existing `docex docs linkmap <depth>` arg (see
[`docex.md § docs`](../../../../../doctrine/infrastructure/docex.md#docs)). It selects
the tracked scope the groups are drawn from:
- `code_level` — `plans/design/**` + each codebase's tracked `core/<cb>/src/**`.
  **Current behavior; remains the default.**
- `design_docs` — `plans/design/**` only.

This lets the caller generate design-doc-only context groups (the input the new
"resolve inconsistencies" pass wants) without hand-filtering.

#### Success Criteria
1. `cxt_groups <max> all --depth design_docs` emits groups whose subjects are
   exclusively `design` nodes; source nodes never appear.
2. Omitting `--depth`, or `--depth code_level`, is **byte-identical** to today's
   output for the same `(tokens_max, selection)`.
3. `--depth` and the linkmap `<depth>` share one scope definition (no second
   allowlist); an invalid value errors on stderr with non-zero exit.

### 175b — `--optimize {tokens | module_integrity}`

Selects the packing objective:
- `tokens` — smallest number of groups whose combined self+overhead stays under
  `tokens_max`. **Current behavior; remains the default.**
- `module_integrity` — never split a **category** (module, codebase, or the
  design-docs set) across two groups, *unless* both groups contain only files of
  the same category and that category cannot be subdivided further. Of the
  categories, only a codebase subdivides (into its modules).

The module-integrity rules are specified by example in
[`adv_014_prep.md § Module Integrity`](./adv_014_prep.md); implement exactly that
table. The natural output is groups of whole modules under one codebase, the
design docs as one group, and whole codebases together where they fit — while
still degrading gracefully (a module too big for one group splits across groups
that contain *only* that module).

#### Success Criteria
1. Every row of the prep's module-integrity validity table is honored — encode
   the table's cases as unit tests (the invalid rows must be rejected/never
   emitted; the valid rows must be achievable).
2. A category that fits in one group is **never** split; a category that does not
   fit is split only across groups that contain nothing but that category.
3. `--optimize tokens` (or omitted) reproduces today's output byte-for-byte.
4. `--optimize` composes with `--depth`: `--depth design_docs --optimize
   module_integrity` yields the design docs as a single group when they fit, or
   design-docs-only groups when they do not.
5. `tokens_max` remains an estimate/heuristic ceiling; an indivisible unit
   exceeding it still forms its own group with a stderr note, exit stays 0
   (matches current oversize behavior).

### Shared (175)
6. Aligned artifacts + doctrine: docex unit tests for `cxt_groups`; the `docs`
   entry in [`docex.md`](../../../../../doctrine/infrastructure/docex.md#docs)
   documents both new args and their defaults; the docex masterplan and the six
   aligned docex artifacts reconciled.

## Mod 176 — `report_command_and_docs_data`

Introduce the `docex report <type> [--format data|full]` command family and
its first type, `docs`, at the **`data`** format (the distillation /
interpretation layer — the "real value" per the design doc). `full` is Mod 177.

Per [`docex_report_design.md`](./docex_report_design.md): `data` emits the
**summarizing metrics** — token weight bucketed by document type, abstraction
level, and location for design docs, and by codebase → module → file →
{inline-comments, docstrings, references, code, other} for source. Every bucket
whose sub-buckets under-sum carries an explicit `etc` remainder.

Source-code bucketing requires **per-language linting** to separate comments,
docstrings, and references from code. Support the doctrine's languages
(Python, Go, JavaScript, plus the others in
[`languages.md`](../../../../../doctrine/practices/languages.md)) and route
everything else to `other / unlintable`. Count only git-tracked files (compiled
artifacts are gitignored), reusing the linkmap's tracked-scope discipline.

#### Success Criteria
1. `docex report docs --format data` prints **deterministic JSON** (stdout;
   diagnostics to stderr; sorted, stable), reusing the shared linkmap builder for
   the design-doc bucket tree rather than re-walking `plans/design`.
2. Design-doc buckets match the design doc's structure exactly: L1 Standard
   Roots (with arc42 sections, diagrams, ADR indices, lexicon), L1 Detail Docs,
   L2 Architecture Docs, L3 Module Docs, and ADRs (summed, not split). `etc`
   sub-buckets present wherever children under-sum.
3. Source buckets: per codebase → per module (for hex-structured codebases) →
   per file → the five leaf categories, produced by real linting. A leaf project
   with a non-hex codebase (e.g. a frontend) buckets to the codebase level with
   no module tier; unknown file types land in `other / unlintable`.
4. `--format` defaults to `full` (Mod 177); until 177 lands, `full` may stub to
   `data` behind a clear TODO, but the command **must** accept `--format data`
   and `report <type>` dispatch must be complete.
5. Token estimates use the same estimator as `linkmap`'s `tokens` so report
   weights and cxt_groups budgets agree.
6. Aligned artifacts + doctrine: docex unit tests over a fixture corpus asserting
   bucket sums and the `etc` invariant; a new `docex report` section in
   [`docex.md`](../../../../../doctrine/infrastructure/docex.md); masterplan and the
   six aligned artifacts reconciled.

## Mod 177 — `report_docs_full_html`

Implement `docex report docs --format full` — a self-contained **HTML** report
with all diagrams embedded inline (no separate files), per
[`docex_report_design.md § Full Report`](./docex_report_design.md). Three
sections in order: (1) Code-Doc Comparison, (2) Doc Treemap, (3) Code Treemap.

The treemaps are **bespoke** (area ∝ token weight) — the doc treemap's
vertical-slice-then-horizontal-slice structure with the ADR band spanning
beneath all four abstraction slices, and the per-codebase / per-module code
treemaps (comments / docstrings / references over code over other). Bespoke
rendering, not a charting library.

#### Success Criteria
1. `docex report docs` (default `--format full`) writes one HTML document with
   the three sections; every diagram is embedded (inline SVG or equivalent), no
   external asset references.
2. Areas are proportional to the `data`-format token weights (177 consumes 176's
   distillation; it does not recompute buckets independently).
3. One code treemap per codebase **and** one per hex module, and one doc treemap
   covering all design-doc buckets with the ADR band, exactly as the design doc
   specifies.
4. Deterministic: same corpus → same HTML (stable ordering, no timestamps in the
   diffed body).
5. Aligned artifacts + doctrine: docex tests that the full render is produced and
   internally consistent with `data`; `docex.md` `report` section notes the two
   formats; masterplan + six aligned artifacts reconciled.

## Mod 178 — `exec_service_network_membership`

Fixes the network-orphan leak documented in
[`orphaned_network_problem.md`](./orphaned_network_problem.md) (a report from a
downstream project — ignore its "advance 012" numbering). A critical read of that
report against the docex source (`compose.py:595-601`, `exec_service.md:32`)
sharpens the diagnosis and **reprioritizes its three proposed fixes**; the mod
implements the corrected version, not the report verbatim.

### The true root cause (sharper than the report)
The report frames this as "the compiler inconsistently emits `networks:` on some
exec services." It is not an inconsistency — the compiler faithfully implements
the doctrine rule in
[`exec_service.md § Networks`](../../../../../doctrine/infrastructure/specifics/exec_service.md):
an exec service's networks are *"the union of the codebase's networks less
`web`."* For a **web-only codebase** (a typical frontend: its only core service
is on `web`), that union is **empty**, so the guard at `compose.py:595-601`
(`if exec_nets:`) writes no `networks:` key — and the exec block never sets
`network_mode` either. A service with **neither** key lands on Compose's implicit,
auto-created `<project>_default` bridge, which the top-level `networks:` block
never declares. Every `docker compose run --rm …-exec ./test.sh` then mints an
unreaped `_default`; `--slots N` multiplies it; the host address pool exhausts.

The defect is therefore an **unhandled empty-set case** in a doctrine rule the
compiler obeys — the fix touches **both** the compiler *and*
`exec_service.md`.

### Fix (report fix #1, corrected — the true fix)
When an exec service's `exec_nets` is empty, it must still be emitted with
explicit network intent so Compose never auto-creates `_default`. Pick, in the
mod's implementation, between:
- **`network_mode: none`** — doctrinally honest (a one-off build/test shell that
  needs no intra-stack network gets none) and creates **zero** networks. The one
  thing to verify first: no doctrine-conformant `build.sh`/`test.sh` needs
  network egress at exec time (dependencies install at image-build, not here) —
  if any legitimately does, `none` is wrong for it.
- **attach to `internal`** when the env declares it — reuses an existing network
  (zero new networks) and keeps an ops shell able to reach backing services;
  needs a fallback when no `internal` exists.

Prefer `network_mode: none` as the default with `internal` as the considered
alternative; whichever is chosen, **update `exec_service.md`'s Networks rule** to
state the empty-set fallback explicitly.

### Report fix #3 (address-pool ceiling) — GOOD, folded in as doctrine only
Raising the host's Docker address-pool ceiling is a legitimate **amplifier** fix:
even leak-free, a max `--slots 8` run plus standing dev/stage/prod stacks plus the
check worktree approaches Docker's default ~31-network ceiling. There is
**precedent** — [`telemetry_preinfra.md`](../../../../../doctrine/infrastructure/preinfra/telemetry_preinfra.md)
already configures `/etc/docker/daemon.json` (the json-file log cap) with the
right caveats (applies only to containers created afterward; a daemon restart
bounces every container on a shared host). This mod adds a
`default-address-pools` stanza to the **fixed development-side preinfra
doctrine**, sharing that same daemon.json and repeating those caveats, plus the
collision caveat (the pool must not overlap the master network / existing
subnets). It is **operator host config, not compiler code** — so the mod ships
the doctrine text; the operator applies it on the dev host (a Phase D pre-req,
below).

### Report fix #2 (`--remove-orphans` on teardown) — LOW value, mostly dropped
Verified against the code, this one is misdiagnosed and largely subsumed by the
fix above:
- `compose_down` never passes `--remove-orphans` (`subprocess_client.py:145-159`),
  but `--remove-orphans` removes containers/networks for services *dropped from
  the compose file* — it is **not** the mechanism that reaps a stray `_default`.
- The single-stack path **already** tears down on a mid-`up` failure via a
  `finally` (`test.py:199-206`). The sharded path leaves a failed slot up **by
  design** for debugging (`test.py:373-383`), reclaimed by the next run's pre-up
  down or the fleet reaper (`reaper.py:129-135`) — an intentional tradeoff, not a
  bug.
- The genuine leak vector — `compose run --rm` creating `_default` with no
  following `down` (`subprocess_client.py:161-191`) — **disappears once the fix
  above stops `_default` from ever being created.**

So this mod does **not** adopt fix #2 in any form — no `--remove-orphans`, no
added reaper-side network prune. It is left out by decision: fix #1 removes the
`_default` at its source, and the Phase D sharded smoke check (step 0) is the
proof that no further teardown change is needed. Should that check ever surface a
residual leak, a targeted network reap in the existing preflight/reaper is the
correct follow-up — but it is out of scope for this advance.

### Success Criteria
1. **A web-only codebase's exec service is never emitted network-less.** With the
   fix, its compiled block carries explicit network intent (`network_mode: none`
   or an `internal` attachment) and `docker compose run --rm …-exec …` creates
   **no** `<project>_default` network. Proven with a **web-only codebase fixture**
   (the current fixed test project's `api-exec` has `internal`, so it does *not*
   reproduce the bug — add/confirm a frontend-like web-only codebase, or a
   fixture, that does).
2. Exec services with a non-empty `exec_nets` are **byte-identical** to today
   (the `internal`-bearing case at `compose.py:595-601` is unchanged).
3. `exec_service.md`'s Networks rule is amended to state the empty-set fallback,
   so doctrine and compiler agree.
4. The fixed development-side preinfra doctrine documents the
   `default-address-pools` daemon.json stanza (with the log-cap-style caveats and
   the subnet-collision caveat), co-located with the existing log-cap guidance.
5. A `--slots 4` (or higher) run on a corpus that includes the web-only fixture
   completes without minting per-slot `_default` networks (checked via
   `docker network ls` before/after).
6. Aligned artifacts + doctrine: docex unit tests over the compiled output for the
   web-only case; masterplan and the six aligned artifacts reconciled.

### Phase A gate
Phase A is done when mods 175–178 are complete, `docex test` is green on the
fixed test project, and `docex docs check` passes on docex's own docs. **Do not
proceed to Phase B automatically — hand back to the operator.**

---

# Phase B — Doc-skill refactor (operator-owned, HARD PAUSE)

**The agent does not execute this phase.** It is sensitive skill-authoring work
the operator performs by hand. This section records the *target end-state and
constraints* so the handoff is unambiguous and Phase A builds the right
contracts; the operator owns the actual skill edits.

### Target end-state

The prep identifies four subagent *tasks* the orchestration currently conflates
under "refine" (see [`adv_014_prep.md § Refactor of Doc Skills`](./adv_014_prep.md)):

| Type | Task | Scope |
| ---- | ---- | ----- |
| I | **Refine** — subtractive/condensing/organizing, move detail to the right level or an ADR | changed design docs + code |
| II | **Resolve Inconsistencies** — find and fix doc-vs-doc contradictions | all design docs |
| III | **Fix Inaccuracies** — reconcile docs against the code as-written | changed design docs + code |
| IV | **Document Missing** — add docs for wholly-undocumented objects | its own pass, likely not context-group-shaped |

Goals for the refactor:
- Break I, II, III into **dedicated worker skills** (splitting today's
  `doc-refine`), and IV into its **own standalone skill** (the prep suspects IV
  is not suited to context-group orchestration).
- **Rewrite `doc-refine-orchestration`** into one scaffold that can drive I, II,
  and III — parameterized by (a) the worker skill and (b) the **grouping mode**:
  overhead-packed (`--optimize tokens`) for refine, module-whole
  (`--optimize module_integrity`) for cohere-style passes, and `--depth
  design_docs` for the all-docs inconsistency pass.
- **Retire `project-cohere`'s bespoke executors** in favor of docex:
  `chunk_map.py` → `cxt_groups --optimize module_integrity`; `word_count.py`
  (the "line count" instrument) → `docex report docs`.

### Contract Phase A owes Phase B
Phase A must deliver, as fixed contracts the operator can build skills on:
1. `cxt_groups --depth {design_docs|code_level}`.
2. `cxt_groups --optimize {tokens|module_integrity}` implementing the prep's
   module-integrity table.
3. `docex report docs [--format data|full]`.

If, during Phase B, the operator finds a contract gap (e.g. cohere needs the
code↔doc `hints` that `chunk_map.py` emitted but `cxt_groups` does not), that is
an escalation back into a **Phase A addendum mod**, not a workaround inside a
skill.

### Phase B gate
Phase B is done when the operator declares the new skill set complete and hands
back for Phase C. The operator sets the branch; the agent does not commit skill
files in this phase.

---

# Phase C — Skill-testing / eval rework (agent + operator, together)

The doc-refine-type skills have two standing evaluation problems the current
release process cannot absorb:

1. **The new skills (post-Phase-B I/II/III/IV) have no evaluation at all** — no
   trigger eval, no outcome eval. They ship blind.
2. **The existing doc-refine-type evals blow out usage every run.** The
   `project-cohere` outcome eval already runs to ~tens of millions of tokens per
   suite (memory `project-cohere-outcome-eval`), dominated by turns × context
   with heavy subagent fan-out; multiplying that across four new skills is not
   affordable as a release gate.

This phase is **collaborative** because the resolution is a design judgement
about cost vs. coverage, tied into the `skill-iteration` eval machinery
(`skill_iter/eval/`). Work it together using the `skill-iteration` skill.

### Deliverables
- A trigger + outcome eval approach that **covers the new I/II/III/IV skills**.
- A **cost envelope** that makes doc-skill evals runnable as (or before) a
  release gate — candidate levers already identified in the memory: cheaper
  subagent models (Sonnet subagents cost ~15% less with no pass-rate loss),
  fewer/leaner fixtures, fewer turns, smaller resident-stratum context, `-p`
  vs. interactive trade-offs.
- A clear statement in the release process (RELEASING.md / the doc-skill
  eval gates) of **which doc-skill evals gate a cut** and at what sample size.

### Open design questions (resolve together, do not pre-decide)
- Do I/II/III share one outcome-eval fixture family, or need separate ones?
- Is IV (Document Missing) even outcome-evaluable, given it is explicitly
  "ask the operator before adding" (conservative-by-design)?
- Where is the cost ceiling for a gating run, and which levers hit it without
  losing the discipline-case signal the current eval proves it catches?
- Does `docex report docs` (now available) become part of eval *grading* — e.g.
  asserting a refine pass actually reduced doc token weight?

### Phase C gate
Phase C is done when the new eval approach exists, has been run at least once at
the agreed sample size, and the release-gate policy for doc skills is written
down. Then proceed to Phase D.

---

# Phase D — Smoke test, cut, release (agent-driven, standard)

A **fixed-foundation smoke test only**, then a normal doctrine cut per
[`RELEASING.md`](../../../../../RELEASING.md), driven with the `cicd-pipeline` skill.

### Pre-req (operator, host config)
Before the sharded smoke check below, the operator applies the
`default-address-pools` daemon.json stanza (Mod 178's doctrine) on the dev host
and restarts the daemon — otherwise the `--slots` check may itself trip the very
ceiling this advance raises.

### Smoke test (fixed only)
0. **Network-leak fix (Mod 178).** With the web-only fixture in the corpus, run a
   `--slots 4`+ `docex test`/`check`; confirm via `docker network ls` before/after
   that **no** per-slot `<project>_default` networks are minted and the count
   returns to baseline after teardown.
1. **`cxt_groups` regression + new modes.** On the fixed test project and on
   docex's own docs: `--depth code_level`/`--optimize tokens` byte-identical to
   pre-advance; `--depth design_docs` and `--optimize module_integrity` produce
   correct groups (spot-check against the prep table).
2. **`report docs`.** `--format data` produces well-formed deterministic JSON
   whose buckets sum correctly (the `etc` invariant holds); `--format full`
   renders a self-contained HTML report with all three sections and embedded
   diagrams. Run twice → identical.
3. **Skills exercised end-to-end.** Drive the refactored orchestration skill
   against a real changed-doc set to confirm it reads the new `cxt_groups`
   contracts and completes a pass.
4. **Green suite.** `docex test` green across every codebase on the fixed test
   project; `docex docs check` green.

### Cut
Standard `check → merge → containerize → release → stagetest` per RELEASING.md,
version **3.2.0** (or as the cut decides). Update the root `CHANGELOG.md`.

### Deferred (explicitly out of scope)
- **Elastic smoke test.** `report` and `cxt_groups` have no foundation-specific
  behavior; the doc-skill refactor is conditional-stratum. Fixed fully exercises
  them (same rationale as advance 013).
- **Further report types.** The design ships `docs` only; other `report <type>`s
  are future advances.
- **Narrowing the overhead rule-3 sibling fan-out.** Noted as a possible future
  lever (memory `cohere-chunker-not-obsolete`); not needed here.

---

# Sequencing summary

```
Phase A (agent)     : mods 175 → 176 → 177 →│
                      178 (network-leak fix)─┐
                                            │ HARD GATE (hand back to operator)
Phase B (operator)  : refactor doc skills ──┤
                                            │ HARD GATE (new skills exist)
Phase C (together)  : rework doc-skill evals┤
                                            │ GATE (eval policy written)
Phase D (agent)     : fixed smoke → cut 3.2.0
```

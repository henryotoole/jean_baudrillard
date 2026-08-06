# Mod 118 — Artifact Alignment Sweep

The close-out mod of advance 005. Seven mods (112–117, 119, 120) have moved the
doctrine, the compiler, the release flow, and the role set. Each mod aligned
what it touched; this mod performs the cross-cutting read none of them could,
and leaves a **defensible per-artifact verdict** rather than an impression.

Baseline: tree clean at `bc06d94`, unit **988** (re-run during design: 988
passed, 97.8 s), integration **20 / 0**.

**No code change.** This mod touches documentation, one eval corpus, and the two
nested smoke-project repos. `src/docex/**` and `tests/**` are not edited, and
neither suite should move. If either does, that is a finding, not a fix.

---

## 1. What the sweep found

### 1.1 Corrections to the worklist

Three items in the advance plan's § 2a drift log were checked against the tree
and do not survive contact. Recorded here because a stale worklist entry is
itself drift.

| Logged claim | Reality |
| ------------ | ------- |
| `transfer_tables.md` ~615/~687 "still carry pre-`processes:` flat-form examples" | **False.** Both worked examples are already in the current nested `codebases:` → `core_services:` form and already use `uses:`. A later mod fixed the shape and the log entry was never updated. **But the line numbers were right**: 615 and 687 are the two `uses:` lines, and they carry a *different*, real defect (§ 1.3). |
| `index.yml` "maps 19 resources" | **18.** Verified by `docex why` with no argument. |
| test_projects carries "six occurrences" of stale four-segment wording | **Five.** The claimed sixth — the elastic masterplan's counterpart line — was already correct. The prior report's own enumeration (2 `infra.yml` + 2 smoke tests + 1 masterplan) sums to five. |

### 1.2 `doctrine_excerpts/` — the sixth artifact

The artifact with no automated consumer. Findings:

**Vocabulary: clean.** Zero hits across all 18 excerpts for `depends_on`,
`consumes`, `scheduler`, `ofelia`, `process type`, `cicl_version`, or the v2
nesting keys. Mod 111's rename repair held through seven subsequent mods. This
is the good news and it should be stated, because "we checked and it was clean"
is a different fact from "nobody looked".

**One dangling pointer, pre-dating this advance.**
`doctrine_excerpts/secrets.md:21` cites
`infrastructure/specifics/release_mechanism.md § Secrets`. **Neither exists** —
the file is `specifics/release.md`, and it has no `Secrets` heading. Introduced
in the original bulk commit `307d47a`, never caught, because nothing links-checks
this artifact. Exactly the silent-drift class the artifact is prone to.

Every other `Doctrine reference:` anchor in every excerpt was resolved
mechanically against a real file and a real heading. All 20 resolve.

**One content gap, flagged by Mod 114.** `service_discovery.md` describes
elastic discovery as Cloud Map + Service Connect and stops. It omits the
property this advance made load-bearing and, at Step 0, **empirically verified**:
a client task's set of resolvable endpoint names is frozen at task start. That
property is now written doctrine —
`cicl.md § Resilience covers reachability, not resolvability` (`:412-416`) — and
the excerpt is a restatement of doctrine that no longer restates it. See design
question **Q2**; the excerpt is the reason `docex why service_discovery` would
today tell an operator something true but dangerously incomplete.

### 1.3 Doctrine examples the compiler would reject

The verification bar is "prove it by compiling, not by reading". Two hits, both
mechanical:

| Where | Defect |
| ----- | ------ |
| `doctrine/infrastructure/shape.md:101` | `cicl_version: "2"` — a hard error under rule 21. Every other line of that example is already v3 (`codebases:` → `core_services:` → `uses:`); only the version header was left behind, so the example is both internally inconsistent and non-compiling. |
| `doctrine/infrastructure/specifics/transfer_tables.md:615` and `:687` | `uses: [probe, appdb]` / `uses: [events, appdb]` where `appdb` is declared nowhere in the snippet. Fails magic-ref / rule-25 target resolution. See **Q1**. |

Verified compilable and correct, needing no change: `cicl.md:22-107` (the
canonical full example), `cicl.md:115-128`, `cicl.md:376-382`,
`clock.md:15-30`, `transfer_tables.md:530-536`. Backing services declare no
outbound edges anywhere — the sink property holds throughout.

### 1.4 `skill_iter` — invisible to both pytest suites

| Where | Defect |
| ----- | ------ |
| `skill_iter/eval/outcome/infra-compile/evals.json:7, 11` | Hard-codes *"adds `cache` to web's `depends_on`"* as expected output, and as a graded DELTA DRIVER expectation. Grades a correct answer wrong. Found by Mod 113. |
| `skill_iter/eval/queries.json:70` | A trigger-eval query asks *"…with its resources, networks, and `depends_on`?"*. **Not in the worklist** — found by this sweep. See **Q3**. |

`skill_iter/eval/outcome/{contracts,testing}/evals.json` were checked and are
clean; their "consumes jobs from a queue" is ordinary English, not the retired
field.

### 1.5 `docex`'s own core planning docs

Eighteen findings across five files. Concentration is in `release_flow.md`'s
rollback section, which is stale in **six** places on the v2→v3 bump — including
one that now teaches the exact opposite of the truth.

| # | File:line | Class | Finding |
| - | --------- | ----- | ------- |
| R1 | `release_flow.md:262` | SEMANTIC | Uses `cicl_version '3'` as the *rejected* generation in a failure-mode table. `"3"` is now the only accepted one (`model.py:30`). A reader diagnoses the inverse of what happened. |
| R2 | `release_flow.md:218` | SEMANTIC | The "one-cycle window" is anchored to the v1→v2 break at 1.6.0. The window has re-opened at v2→v3 / 1.7.0; every extant tag is now v2. Needs re-anchoring, not find/replace. See **Q4**. |
| R3 | `release_flow.md:209` | SEMANTIC | Outcome enumeration wrong. `_RECOGNIZED_OLDER_CICL = ("1", "2")` (`rollback.py:290`) plus absent all take the boundary branch, and the message is parameterized (`rollback.py:316`) precisely so it would not go stale — the doc drifted in the way the code was written to prevent. |
| R4 | `release_flow.md:261` | MECHANICAL | Literal `v1→v2` in a failure string that now renders `v1→v3` / `v2→v3`. |
| R5 | `release_flow.md:205` | MECHANICAL | "v1 → v2 boundary" → v2 → v3. |
| R6 | `release_flow.md:207` | MECHANICAL | "pre-v2" → pre-v3; and "no `core_services:`" → **`codebases:`** — mod 112 traded the nouns, so a v2 doc's top-level `core_services:` is now itself a forbidden extra. |
| R7 | `release_flow.md:18` | MECHANICAL | `docex up` — not a command; it is `docex envinfra up <env>`. |
| C1 | `compiler.md:395-400` | MECHANICAL | A blockquote warning of "transient duplication, self-resolving at mod 116". Mod 116 landed; `cicl/cron.py` is gone. The whole callout is dead. |
| C2 | `compiler.md:350-353` | MECHANICAL | Present-tense citation of the deleted `cicl/cron.py`. The claim it supports is still true; the citation is a ghost. |
| C3 | `compiler.md:103-106` | MECHANICAL | `nightly_cleanup` example — a `role: scheduler`-shaped name. The reference third invocation is now `clock`. |
| C4 | `compiler.md:156` | MECHANICAL | "a migration reporting the name of a cron job" — retired-role vocabulary. |
| M1 | `masterplan.md:113-115` (echoed `:190, :205, :219`) | MECHANICAL | The Subcommand Surface table lists `bootstrap`, `up`, `down` — **none are commands**. Missing rows for `preinfra`, `projinfra`, `envinfra`, `roles`, `role`. |
| M2 | `masterplan.md:267-273` | MECHANICAL | Repo-structure block shows `compile/` (it is `cicl/`), `bootstrap/` (a module, not a package), `describe/ (+why)` (`why/` is its own package); omits `emit/` and every adapter package. |
| M3 | `masterplan.md:260-265` | MECHANICAL | Shows `plans/core/` with two files; it holds five. |
| M4 | `masterplan.md:135` | SEMANTIC | "`docex` builds none of them itself" — but `orchestrate/up.py:58` issues a `docker build`. Defensible reading, misleading sentence. One clarifying clause. |
| T1 | `test_projects.md:10` | MECHANICAL | "Route53 zone created by `docex bootstrap`" → `docex projinfra up production`. **Mod 120's update otherwise holds** — every other factual claim spot-checked green against both `infra.yml`s and the `api` tree. |
| P1 | `docex_process.md:32-35` | MECHANICAL | Lists the core docs as two of five, and contradicts its own `:90`, which links `test_projects.md`. |
| P2 | `docex_process.md:88` | MECHANICAL | `bootstrap` in the walk sequence; `test_projects.md:3` states the same walk without it, so the two docs disagree. |

Note the pattern: **`bootstrap` / `up` / `down` appear in four separate
documents.** This is not four bugs, it is one un-swept rename that predates this
advance. It is in scope because it is exactly what "the cross-cutting read"
means.

### 1.6 Rename residue in the nested smoke repos

Fifteen hits, all pre-existing committed content in the two nested repos. Both
inner repos and the outer repo are clean at a consistent baseline
(`fixed` HEAD `d96d878` / `v0.0.17`; `elastic` HEAD `d075bea` / `v0.0.19`).

**(a) Stale "four-segment" wording — 5 hits** (the ref data itself is correct
five-segment everywhere; this is prose only):
`fixed/infra/infra.yml:69`, `elastic/infra/infra.yml:79`,
`fixed/infra/stage/tests/test_smoke.py:54`,
`elastic/infra/stage/tests/test_smoke.py:47`,
`fixed/plans/core/masterplan.md:67`.

**(b) NEW — naive rename artifacts, 6 hits.** The prior sweep missed these. A
blind `service` → `core service` swap was applied where **`codebase`** was
meant. Pre-v2, `web` and `worker` were separate *source trees*; saying they
"were separate core services until CICL v2" is self-contradictory, because they
still are core services.
`fixed/infra/infra.yml:20`, `elastic/infra/infra.yml:26`,
`fixed/plans/core/api/api.md:21`, `elastic/plans/core/api/api.md:21`,
`fixed/plans/core/masterplan.md:63`, `elastic/plans/core/masterplan.md:69`.
The two masterplan hits carry a **second** error: "Two core services on one
artifact" — it is now three (`web`, `worker`, `clock`), contradicting line 51 /
line 9 of the same files.

**(c) Stale core-service count in codebase smoke tests — 2 hits.**
`{fixed,elastic}/core/api/tests/test_smoke.py:6-8` says "One image, two core
services" and names two test files; `test.sh` now runs five across three.

**(d) Retired "process type" vocabulary — 2 hits.**
`{fixed,elastic}/plans/core/api/api.md:23`.

Verified clean and needing no change: `cicl_version: "3"` in both `infra.yml`s;
zero live `reaper` / `ofelia` / `scheduler` usage (all surviving mentions are
deliberate tombstones); zero `depends_on:` on any core-service block in compiled
output (the four hits are all in the `api-exec` block, exactly as
`PRE_CUT_CHECKLIST.md` B.16 permits); `PRE_CUT_CHECKLIST.md` itself clean.

---

## 2. The `doctrine_excerpts` decision — recorded, not silent

**Decision: neither `uses` nor `clock` earns an `index.yml` entry.**

The criterion, which is the durable half of this decision:

> `doctrine_excerpts/` indexes **infrastructural resources** — the nouns a
> deployed stack is physically made of. It does not index CICL *fields*, and it
> does not index *roles*.

Three things support it:

1. **`index.yml`'s own stated contract** is to track `shape.md`'s `[resource]`
   notation. `uses` is a relation between resources, not a resource. Its two
   predecessors, `depends_on` and `consumes`, never had entries across their
   entire lifetimes — merging two non-entries yields a non-entry.
2. **Roles already have a served surface, and it is generated.** `docex role
   clock` reads `tables/roles/clock.yml` and today prints correct prose,
   engines, provided parts, and role-specific fields (`health_check_path`,
   `schedules`) — verified. `web`, `worker`, `cache`, `relational_db`, and
   `object_store` have no excerpt entries either. `scheduler` never had one, so
   its retirement removes nothing.
3. **This artifact's marginal cost is drift.** It is the one artifact with no
   automated consumer. Adding a third hand-maintained restatement of something
   two artifacts already serve correctly buys nothing and creates a new silent
   drift surface.

**Where the decision is recorded matters more than the decision.** It goes into
`docex/plans/core/docex_process.md § Additional Artifacts`, beside the row that
already warns about the sixth artifact — **not** into this mod folder.
The doctrine's own `practices/docs.md` says *"modification files are almost
always irrelevant to development and should not ever be loaded into context"*. A
"no" recorded only in a mod folder is therefore indistinguishable from silence —
which is the exact failure this mod exists to prevent.

---

## 3. Work items

| ID | Item | Files |
| -- | ---- | ----- |
| **W1** | Record the excerpt criterion + the explicit `uses`/`clock` "no" | `docex/plans/core/docex_process.md` § Additional Artifacts |
| **W2** | Fix the dangling `release_mechanism.md § Secrets` pointer | `docex/doctrine_excerpts/secrets.md:21` |
| **W3** | Close the `service_discovery.md` gap (**Q2**) | `docex/doctrine_excerpts/service_discovery.md` |
| **W4** | `cicl_version: "2"` → `"3"` | `doctrine/infrastructure/shape.md:101` |
| **W5** | Resolve the undeclared `appdb` (**Q1**) | `doctrine/infrastructure/specifics/transfer_tables.md:615, :687` |
| **W6** | `depends_on` → `uses` in the graded expectation and expected output | `skill_iter/eval/outcome/infra-compile/evals.json:7, :11` |
| **W7** | `depends_on` → `uses` in the trigger query (**Q3**) | `skill_iter/eval/queries.json:70` |
| **W8** | R1–R7 | `docex/plans/core/release_flow.md` |
| **W9** | C1–C4 | `docex/plans/core/compiler.md` |
| **W10** | M1–M4 | `docex/plans/core/masterplan.md` |
| **W11** | T1, P1, P2 | `docex/plans/core/test_projects.md`, `docex_process.md` |
| **W12** | Residue (a)–(d), 15 hits, **inner-repo commits** | `docex/test_projects/{fixed,elastic}/**` |

### W12 commit cadence

Per `test_projects.md § Commit cadence`: **inner repo first** with a
project-shaped message, then the outer catch-up. The outer repo tracks these
files directly (259 paths, no gitlinks), so every fix dirties both.

**Version tags do not move.** This is a comment- and prose-only change; no
project version moves, so `v0.0.17` / `v0.0.19` stay where they are. The inner
commits are non-version-bump commits.

---

## 4. Verification

1. **Compile, don't read.** A throwaway harness (scratchpad, **not committed**)
   extracts every `yml` fence under `doctrine/` and `skills/` that is
   `infra.yml`-shaped, runs the real validator against each, and reports.
   Complete documents must validate as-is. Fragments are spliced into a single
   declared minimal skeleton before validating, and the skeleton is reported
   alongside the result so the proof is auditable rather than asserted.
2. **`docex why`** exits 0 for all 18 resources and serves prose with no retired
   vocabulary; every `Doctrine reference:` anchor in every excerpt resolves to a
   real file and a real heading. (This is what caught W2 and is worth keeping as
   a repeatable one-liner.)
3. **`docex roles` / `docex role clock`** serve correct prose — already verified
   during design; re-confirm after edits.
4. **`pytest tests/unit` = 988 and `pytest -m integration` = 20/0, unchanged.**
   Movement in either is a finding to escalate, not a result to accept.
5. **Verdict table.** The report closes with one row per artifact and an
   explicit verdict, so the close-out has a defensible statement.

---

## 5. Out of scope

- **`clock.md:96`'s binding-coverage sentence** — held with the operator. Not
  touched.
- **`engineer/scratch.md`** — tracked, and carries `role: scheduler` and
  pre-1.6.0 CICL shape at `:13` and `:33`. It is a scratch/thinking file, not
  one of the six artifacts. **Ruled out of scope** — the six-artifact list
  means something precisely because it is bounded.
- **`cohere`** — the dangling-link and thread-skill-pointer audit is the next
  step, not this one. This mod fixes only pointers *inside* the artifacts it
  owns.
- **Upgrade guides and `CHANGELOG.md`** — their retired vocabulary is the
  historical record and is correct as written. Confirmed, not touched.

---

## Design Questions — all five ruled

Raised at design, ruled by the C.O. before `implementation.md` was written.
Recorded here in resolved form; the operative instructions live in
`implementation.md`.

**Q1 — `transfer_tables.md`'s undeclared `appdb`. → Proposal taken.** Drop
`appdb` from both `uses:` lists (`:615`, `:687`). The snippets teach the sidecar
and the ClickHouse backing; `appdb` carries no weight there, and the shortest
valid example is the best one. Prove it by compiling, not by reading.

**Q2 — `service_discovery.md`. → Approved as drafted, verbatim.** Judged
restatement rather than new reasoning: the freeze property is already
`cicl.md § Resilience covers reachability, not resolvability`, and Step 0
measured it. *"It does not exist for it, for the task's whole remaining life,
and retrying never converges"* is the right emphasis — the failure that gets
misdiagnosed is precisely the one that looks like it should heal. The closing
fixed/elastic contrast is **required**: it is the sentence that stops an
operator generalizing an elastic constraint onto a fixed stack.

**Q3 — retired vocabulary in a trigger query. → My proposal overruled; the
query text stays, and must be labeled.**

The counter-argument I raised was the stronger one and I undersold it. A trigger
eval measures whether a skill fires on *user* phrasing, and the user with the
most acute need for `infra-compile` to fire is someone on a not-yet-upgraded
project typing "how do I add a `depends_on`". That is not stale phrasing — it is
the highest-value query in the corpus, the moment the skill loads and tells them
the field is now `uses`. Rewriting it to current vocabulary would test a user
who already knows the answer. The realism is not speculative; the upgrade guide
exists because those users exist right now.

The other half of my argument still holds, so it becomes the condition:
unlabeled dead vocabulary is indistinguishable from un-swept residue and the
next sweeper will "fix" it. **Resolution: keep the query, label it on the `note`
field** — a real field on the entry, read by `run_suite.py:193`, surfaced in
results at `:236`, and fed to `improve_description.py:116-117`. The schema
allows it and the label is actually displayed, so the fallback (update to
`uses` if no label were possible) does not apply.

**Q4 — `release_flow.md:218`, the one-cycle window. → Rewrite approved, with a
consistency requirement.** The argument's *shape* is unchanged — one release
cycle with no rollback path because every extant older tag declares the prior
generation — so re-anchoring to v2→v3 restates a known consequence rather than
reasoning a new one.

The requirement: Mod 120 already stated this trap in `upgrade_1.7.0.md:456-479`,
and sourced it by **quoting the rendered output of `rollback.py::_boundary_message`
rather than composing it**. The new wording must agree with that and with the
code. Three descriptions of one behaviour that drift apart are worse than one
description — and `release_flow.md:262`, which currently teaches the exact
inverse of the truth, is the proof of what that costs.

**Q5 — `engineer/scratch.md`. → Leave it.** Sweeping it would invite treating
every tracked file as an artifact, and the six-artifact list means something
precisely because it is bounded.

---

## Assessment delivered on request: `bootstrap` / `up` / `down`

The C.O. asked whether the commands documented in four files but existing
nowhere are mechanical residue (fix it) or need genuinely new prose (log and
hand back).

**Verdict: mechanical rename residue. In scope, fixed.**

`masterplan.md:104` declares its table to be "the full set of commands defined
in [docex.md]", and `:126` calls it "a navigation aid, not a re-spec".
`doctrine/infrastructure/docex.md:36-52` — the authority the table names — is
**fully current**: it lists `roles`, `role`, `preinfra`, `projinfra`, `envinfra`
and does not list `bootstrap`/`up`/`down`. Bringing the table into agreement
with the source it already cites is transcription, not authorship. Line 104's
claim is presently *false*, and making a false sentence true from its own named
authority is repair.

The mapping is clean: `bootstrap` → internal, reached via `projinfra`
(`__main__.py:345, :356`); `up <env>` / `down <env>` → `envinfra <direction>
<env>` (`__main__.py:179-186`). The `Reads` / `Writes` cells for the added rows
are descriptive transcription of what the handlers do, in the same register as
every existing row.

---

## Post-implementation: what the compile-don't-read bar caught

The verification bar for this mod was *"every example `infra.yml` in the
doctrine actually validates — prove it by compiling, not by reading."*

**It caught its own author.** § 1.3 of this document lists
`cicl.md:376-382` under "verified compilable and correct, needing no change".
It is neither. It declares `uses: [database, cache, bucket, api.worker]` with
`database` undeclared — `rule_25_unresolved_uses`, **the same defect class as
the `appdb` fix four lines above it in the same table**. I reached that verdict
by reading the fence. Compiling it took seconds and returned the opposite
answer.

Recorded deliberately rather than quietly corrected. The rule stated abstractly
is forgettable; a worked example of the bar catching the person who wrote the
bar is not. Two specific lessons:

1. **Reading finds the defect you are already looking for.** I was scanning
   that fence for retired vocabulary and pre-`processes:` shape — the advance's
   residue classes. It had neither, so it read as clean. An undeclared `uses`
   target was not on the list I was matching against, so I did not see it,
   *while fixing exactly that defect elsewhere in the same file*.
2. **A verdict of "verified" must name its instrument.** "Verified correct" in
   § 1.3 meant "I read it and it looked right", which is indistinguishable in
   the written record from "I compiled it and it passed". The verdict table in
   the final report was made to carry evidence per row for this reason.

## Findings carried forward — inputs to `cohere`, not surprises

Found by the Part F harness, verified independently, **not fixed**: all four
predate advance 005, and the `database` rename ripples through Mod 112's
protected output. Root causes dated so a later pass need not re-establish
provenance.

| Finding | Where | Root cause |
| ------- | ----- | ---------- |
| Postgres backing named `database` is a **reserved engine identifier** — `rule_engine_reserved_name`, *"AWS RDS would reject this at apply time"* (`tables/roles/relational_db.yml:43`) | `cicl.md:22-107`, `shape.md:100-134` | Rule landed `991b76d` (docex 0.7.0 cut); the examples predate it |
| **Literal TAB indentation** — YAML forbids tabs, so the canonical example is unparseable | `cicl.md:103, :105` and throughout | `307d47a` (original bulk commit) |
| **Rule 7 violated by the canonical example itself** — `api.clock` and `api.worker` magic-ref `${backing_services.bucket.bucket_name}` without `bucket` in `uses:` | `cicl.md:22-107` | `307d47a` |
| **Undeclared `database` in `uses:`** — `rule_25_unresolved_uses` | `cicl.md:376-382` | `307d47a` |

Two things to carry with them:

**The `cicl.md` canonical example is the fence every project author copies
first**, and `upgrade_1.7.0.md` sends readers to it. Being simultaneously
unparseable *and* self-rejecting matters more in the release whose entire
subject is how to author `infra.yml` than its age would suggest. Long-standing
is not the same as low-priority.

**16 of 42 `yml` fences under `doctrine/` + `skills/` indent with tabs.** This
looks like a formatting-convention question and is not one: YAML forbids tabs
for indentation, so those fences are not examples — they are text shaped like
examples. None is copy-pasteable into a working `infra.yml`.

# Mod 118 — Implementation Steps

Close-out artifact alignment sweep for advance 005. **Documentation, one eval
corpus, and the two nested smoke repos. No `src/docex/**` or `tests/**` edits.**

## Before you start

- Repo root (`$jb`): `/home/ubuntu/.claude/jean_baudrillard`. **Absolute paths
  only.** Branch: `005_process_type_solidification`.
- Baseline to preserve: `pytest tests/unit` = **988 passed**,
  `pytest -m integration` = **20 passed / 0 failed**. Run from `$jb/docex` with
  `PYTHONPATH=src python3 -m pytest ...`. There is no `python` on PATH — use
  `python3`.
- **If either suite moves, stop and report it.** This mod edits no code; a
  moved count is a finding, not something to fix.
- **Do not touch** `doctrine/infrastructure/specifics/clock.md:96` (the
  binding-coverage sentence — held with the operator), `$jb/engineer/scratch.md`
  (ruled out of scope), `upgrades/**`, or any `CHANGELOG.md` retired-vocabulary
  prose (that is the historical record and is correct as written).

---

# Part A — `doctrine_excerpts/` (the sixth artifact)

## A1. Record the indexing criterion and the explicit `uses` / `clock` "no"

**File:** `$jb/docex/plans/core/docex_process.md`

This is the load-bearing step of the mod. The decision must live in a core
planning doc, **not** in the mod folder, because `practices/docs.md` states that
modification files should never be loaded into context — a "no" filed there is
indistinguishable from the silence this mod exists to end.

In § Additional Artifacts, immediately **after** the existing paragraph that
ends `Mod 110 drifted here; mod 111 added the missing `codebase` entry and wrote
this row.`, insert:

```markdown
**What earns an entry.** `doctrine_excerpts/` indexes **infrastructural
resources** — the nouns a deployed stack is physically made of, tracking
`shape.md`'s `[resource]` notation. It does **not** index CICL *fields*, and it
does **not** index *roles*. Fields are specified by `cicl.md § Service Fields`;
roles are served by `docex role <name>`, which reads `tables/roles/*.yml` and is
therefore generated rather than restated — it cannot drift the way this artifact
can. Adding a hand-maintained third restatement of something two artifacts
already serve correctly buys nothing and creates a new silent-drift surface.

Applying that criterion at advance 005 (mod 118): **`uses` gets no entry** — it
is a relation between resources, not a resource, and its two predecessors
`depends_on` and `consumes` had no entries across their entire lifetimes, so
merging two non-entries yields a non-entry. **`clock` gets no entry** — it is a
role; `docex role clock` already serves it correctly, and no other role
(`web`, `worker`, `cache`, `relational_db`, `object_store`) has an entry either.
The retired `scheduler` role had none, so its deletion removed nothing. Both
decisions are recorded here rather than left implicit, because on this artifact
a silent "no" is indistinguishable from an oversight.
```

## A2. Fix the dangling pointer in `secrets.md`

**File:** `$jb/docex/doctrine_excerpts/secrets.md`, line 21.

It cites `infrastructure/specifics/release_mechanism.md § Secrets`. **Neither
the file nor the section has ever existed** — the file is
`doctrine/infrastructure/specifics/release.md`. Dangling since the original bulk
commit `307d47a`, uncaught because nothing link-checks this artifact.

Replace:

```
See `infrastructure/specifics/release_mechanism.md § Secrets`.
```

with:

```
See `infrastructure/specifics/release.md`.
```

Verify before writing: `grep -n '^#\+ ' $jb/doctrine/infrastructure/specifics/release.md`
confirms there is no `Secrets` heading, so **do not** invent a section anchor —
the bare file reference is the correct repair. If the surrounding sentence needs
a word adjusted so it reads naturally without the `§`, that is fine.

## A3. Close the `service_discovery.md` gap (approved as drafted)

**File:** `$jb/docex/doctrine_excerpts/service_discovery.md`

Flagged by Mod 114. The excerpt omits the property this advance made
load-bearing and Step 0 measured. The replacement text below was **reviewed and
approved verbatim** — land it as written. Do not paraphrase, and in particular
**keep the closing fixed/elastic contrast sentence**: it is what stops an
operator generalizing an elastic constraint onto a fixed stack.

Replace the final line (`Doctrine reference: `infrastructure/shape.md`.`) with:

```markdown
On elastic, a client task's set of **resolvable** endpoint names is fixed when
that task starts. A name registered in the namespace afterwards is not merely
unreachable from that task — it does not exist for it, for the task's whole
remaining life, and retrying never converges. This is why a release redeploys
any consumer whose tasks predate an endpoint it uses. Fixed has no equivalent
constraint: docker DNS resolves at lookup time.

Doctrine reference: `infrastructure/shape.md`;
`infrastructure/cicl.md § Resilience covers reachability, not resolvability`.
```

Keep the existing lines 1–8 unchanged.

---

# Part B — Doctrine examples the compiler rejects

## B1. `shape.md` — stale `cicl_version`

**File:** `$jb/doctrine/infrastructure/shape.md`, **line 101**.

`cicl_version: "2"` → `cicl_version: "3"`.

A hard error under rule 21. Every other line of that example (fence at ~100–134)
is already v3 — `codebases:` → `core_services:` → `uses:`. Change **only** the
version literal; the rest of the fence is correct and verified.

## B2. `transfer_tables.md` — undeclared `appdb`

**File:** `$jb/doctrine/infrastructure/specifics/transfer_tables.md`

Two worked-example snippets name `appdb` in `uses:` while declaring it nowhere,
which fails target resolution. **Ruling: drop it** — the shortest valid example
is the best one, and `appdb` teaches nothing in snippets about a sidecar and a
ClickHouse backing.

- **Line 615:** `        uses: [probe, appdb]` → `        uses: [probe]`
- **Line 687:** `        uses: [events, appdb]` → `        uses: [events]`

Preserve the exact leading indentation. Change nothing else in either fence.

> **Note for the record:** the advance plan's § 2a logged these two locations as
> "pre-`processes:` flat-form examples". That is **stale** — the shape was
> corrected by a later mod and the log entry never was. The line numbers were
> right; the described defect was not.

---

# Part C — `skill_iter` (invisible to both pytest suites)

## C1. `outcome/infra-compile/evals.json` — `depends_on` → `uses`

**File:** `$jb/skill_iter/eval/outcome/infra-compile/evals.json`

This grades a *correct* answer wrong. Two edits.

**Line 7**, in `expected_output`, replace clause (3):

```
and (3) adds `cache` to web's `depends_on`, because a magic ref between services that lacks a matching depends_on entry is a hard compile error.
```

with:

```
and (3) adds `cache` to web's `uses`, because a magic ref between services that lacks a matching `uses` entry is a hard compile error.
```

**Line 11**, replace the third expectation string:

```
DELTA DRIVER (doctrine-specific, not inferable): adds `cache` to web's `depends_on` list and ties this to the rule that any magic ref implying a cross-service dependency MUST be matched by a corresponding depends_on entry or the compiler errors
```

with:

```
DELTA DRIVER (doctrine-specific, not inferable): adds `cache` to web's `uses` list and ties this to the rule that any magic ref implying a cross-service dependency MUST be matched by a corresponding `uses` entry or the compiler errors
```

Leave the `prompt` (line 6) alone — it describes the user's situation in plain
English and names no field. Leave the two CONFIRMATORY expectations alone.

Validate the file parses afterwards:
`python3 -c "import json;json.load(open('$jb/skill_iter/eval/outcome/infra-compile/evals.json'))"`

## C2. `queries.json:70` — keep the retired vocabulary, but **label it**

**File:** `$jb/skill_iter/eval/queries.json`

**Ruling: the query text stays as-is.** A trigger eval measures whether a skill
fires on *user* phrasing, and the user with the most acute need for
`infra-compile` to fire is someone on a not-yet-upgraded project typing
"`depends_on`". That is the highest-value query in the corpus, not stale
phrasing. Rewriting it to `uses` would test a user who already knows the answer.

The condition attached to that ruling is that the deliberateness must be
**recorded on the entry**, so the next sweeper does not silently "fix" it.

The schema supports this: `note` is a real field on every entry, read by
`run_suite.py:193` (search filter), surfaced in results at `run_suite.py:236`,
and fed to `improve_description.py:116-117`. **Do not add a new key** — `note`
is both allowed and actually displayed, which an unread new key would not be.

Change **only** the `note` on the entry whose `query` contains `depends_on`
(currently `"CICL authoring"`) to:

```json
      "note": "CICL authoring. DELIBERATE LEGACY VOCABULARY — `depends_on` was retired in doctrine 1.7.0 and replaced by `uses`. This query is NOT stale: it simulates a user on a not-yet-upgraded project, which is exactly when infra-compile most needs to fire. Do not 'correct' it to `uses`."
```

Leave `query` and `expect` untouched. Then validate the JSON parses:
`python3 -c "import json;json.load(open('$jb/skill_iter/eval/queries.json'))"`

**Belt and braces.** In `$jb/skill_iter/README.md`, the layout block line reading:

```
  queries.json          labeled trigger query set (the single source of truth for queries)
```

becomes:

```
  queries.json          labeled trigger query set (the single source of truth for queries);
                        `note` carries each query's rationale, including any that
                        deliberately use retired vocabulary — read it before "fixing" one
```

Keep the surrounding code-fence alignment tidy. **Do not** add a `queries.json`
section to `eval/schemas.md` — that file documents no query schema today and
authoring one is out of scope.

---

# Part D — `docex`'s own core planning docs

## D1. `release_flow.md` — the v2→v3 re-anchoring

**File:** `$jb/docex/plans/core/release_flow.md`

**Read these two sources first and make every edit agree with both.** Three
descriptions of one behaviour that drift apart are worse than one description,
and line 262 is the proof of what that costs:

1. `$jb/docex/src/docex/pipeline/rollback.py:280-332` — `_boundary_message` and
   `_RECOGNIZED_OLDER_CICL`. Note the `WHY` docstring: the message is
   parameterized on the target's own generation *specifically so it cannot go
   stale at a CICL bump*.
2. `$jb/upgrades/upgrade_2.0.0.md:456-479` — § Rollback is unavailable across
   the boundary. Mod 120 wrote this by **quoting the rendered output** of
   `_boundary_message` rather than composing prose. Your wording must agree
   with the strings quoted there.

**D1a — line 18.** `dev` and `test` are local-only via `docex up`. → via
`docex envinfra up`.

**D1b — line 205.** "rollback across the v1 → v2 boundary aborts at pre-flight"
→ v2 → v3.

**D1c — line 207.** Two errors in one sentence. "a pre-v2 `infra.yml` fails full
validation … (no `core_services:`, …)" → **pre-v3**, and the missing top-level
key is **`codebases:`**, not `core_services:` — mod 112 traded the nouns, so a
v2 document's top-level `core_services:` is now itself a forbidden extra under
`extra="forbid"` (`model.py:327`, `:361`). Also retarget the trailing "You are
across the v1 boundary" to the current boundary. Keep the paragraph's argument
(a single-key read cannot get it wrong) — only the operands move.

**D1d — line 209.** The outcome enumeration. Truth, from `rollback.py:290`
(`_RECOGNIZED_OLDER_CICL = ("1", "2")`) and `:307`: `"3"` proceeds; `"1"`,
`"2"`, **and absent** all take the boundary branch; any other value gets the
unrecognized-generation message; unreadable/unparseable/not-a-mapping aborts
naming tag and path. Also correct the claim that the message is a fixed
`v1 → v2` string — it renders `f"v{generation}→v{CURRENT_CICL_VERSION}"`
(`rollback.py:315-316`). Worth one clause noting the message is parameterized
by design.

**D1e — line 218, the one-cycle window.** Approved to rewrite the argument. The
*shape* is unchanged — one release cycle with no rollback path because every
extant older tag declares the prior generation — so re-anchor, do not re-reason.
Every operand moves: the break is the **v2→v3** break at doctrine **1.7.0**;
every extant older tag is **v2**, not v1; the clearing condition is a **second
v3 version**. Keep the existing justification sentence ("the alternative was a
read-only flat-form parser maintained permanently to serve one code path") —
it is still true. Cross-reference `upgrade_2.0.0.md § Rollback is unavailable
across the boundary` so the two statements are visibly one statement.

**D1f — line 261**, failure-mode table. `rollback aborted — cannot roll back
across the CICL v1→v2 boundary` → the rendered form is now `v1→v3` **or**
`v2→v3` depending on the target. Say so rather than picking one. "Expected for
every target older than doctrine 1.6.0" → **1.7.0**.

**D1g — line 262. The worst single defect in this advance's documentation.**
The row currently uses `cicl_version '3'` as the *rejected* generation:

```
| `rollback aborted — target v... declares cicl_version '3'` | Target declares a generation this `docex` does not compile … |
```

`"3"` is now the only generation docex **does** compile (`model.py:30`). A
reader hitting this row diagnoses the exact inverse of what happened. Re-cast it
with a genuinely unrecognized generation — `'4'` — which is what
`rollback.py:326-331` would actually fire on. Keep the row's diagnosis
("usually a `docex` older than the target, i.e. rolling *forward* by mistake")
and its "Where to look" cell; only the generation literal is wrong.

**D1h.** Add one sentence, in whichever of §§ D1d/D1g reads most naturally, on
*why this drifted*: `_boundary_message` is parameterized precisely so it could
not go stale, and this document went stale by restating it instead of quoting
it. That is an argument for reading generated output rather than restating it,
and it is the transferable lesson from this row. Keep it to a sentence or two —
do not turn the failure-mode table into an essay.

## D2. `compiler.md`

**File:** `$jb/docex/plans/core/compiler.md`

**D2a — lines 393-400.** Delete the entire blockquote beginning
`> **Transient duplication, self-resolving at mod 116.**`. Mod 116 landed;
`src/docex/cicl/cron.py` no longer exists (confirm: `ls
$jb/docex/src/docex/cicl/` shows no `cron.py`). The callout warns of a pending
reconciliation that has already happened. Delete the blockquote outright — do
not rewrite it in the past tense; there is nothing left to warn about.

**D2b — lines 350-353.** The sentence ends `…the dialect-mismatch bug class that
`cicl/cron.py` exists to manage has no counterpart here.` The *claim* is correct
(`emit/schedules.py` has no translation function) but it cites a deleted module
in the present tense. Recast so it does not depend on a file that no longer
exists — e.g. refer to the retired scheduler's cron-dialect translation as
something the doctrine deleted, not something that exists elsewhere.

**D2c — lines 101-106.** The worked example uses
`Codebase(api) × {web, worker, nightly_cleanup}` and
`CompiledService(name="api-nightly_cleanup", …)`. `nightly_cleanup` is a
`role: scheduler`-shaped name from the retired role. Replace the third
invocation with `clock` → `api-clock`, matching the reference implementation
(`test_projects/{fixed,elastic}/infra/infra.yml` declare `clock: role: clock`).

**D2d — line 156.** "a migration reporting the name of a cron job" — retired
vocabulary; no core-service role produces a cron job now (`tables/roles/` is
`cache, clock, object_store, relational_db, web, worker`). Reword to name a
plausible current core service. The mod-102 narrative around it is accurate —
change only the vocabulary.

## D3. `masterplan.md`

**File:** `$jb/docex/plans/core/masterplan.md`

**Assessment, made and reported:** this is **mechanical rename residue**, and it
is fixable without new reasoning. Line 104 declares the table to be "the full
set of commands defined in [docex.md]", and line 126 calls it "a navigation aid,
not a re-spec". `$jb/doctrine/infrastructure/docex.md:36-52` — the authority the
table names — is **fully current**: it lists `roles`, `role`, `preinfra`,
`projinfra`, `envinfra` and does not list `bootstrap`/`up`/`down`. Bringing the
table into agreement with the source it already cites is transcription, not
authorship. Line 104's claim is presently *false*; making a false sentence true
from its own named authority is repair.

**D3a — the Subcommand Surface table (lines 106-124).**

- **Delete the `bootstrap` row** (113). `bootstrap` is not a command;
  `run_bootstrap` is internal, called from the `projinfra` path
  (`__main__.py:345, :356`). Its S3-bucket + DynamoDB-table behavior belongs on
  a `projinfra` row.
- **Replace the `up <env>` and `down <env>` rows** (114, 115) with one
  `envinfra <direction> <env>` row (`__main__.py:179-186`, `direction ∈
  {up, down}`). Preserve the real content of both rows — the compose-up /
  migrations-after behavior and the compose-down / keeps-named-volumes
  behavior — in the merged row's cells.
- **Add rows** for `preinfra <side>`, `projinfra <direction> <side>`, `roles`,
  and `role <name>`. Take each description from `docex.md:39-43`; fill the
  `Reads` / `Writes` columns from `__main__.py` and the relevant handler. Keep
  the cells terse and consistent with the existing rows' register.
- Cross-check the finished list against `_HELP_TEXT` (`__main__.py:27-47`) and
  `_build_handler_table()` (`:795-822`). The full real surface is: `compile,
  describe, why, roles, role, preinfra, projinfra, envinfra, build, test,
  migrate, check, merge, containerize, release, stagetest, rollback, secrets,
  config`.

**D3b — line 190**, the Foundation-Aware table's `bootstrap` row. Retarget to
`projinfra`; the fixed/elastic behavior described (no-op vs. creating
`<project>-tofu-state` + `<project>-tofu-locks`) is still accurate.

**D3c — line 205**, credentials table: "Used by: `bootstrap`, `release`
(elastic), `containerize` (when ECR)" → `projinfra`, `release` (elastic),
`containerize` (when ECR).

**D3d — line 219** (numbered consequence 1). Two occurrences of `docex up dev` /
`docex up` → `docex envinfra up dev` / `docex envinfra up`. The point being made
(spawned containers are siblings and outlive the invocation) is unaffected.

**D3e — lines 258-273**, the repository-structure block. Correct against the
real tree (`ls $jb/docex/src/docex/`):

- `plans/core/` shows two files; it holds **five** — add `compiler.md`,
  `release_flow.md`, `test_projects.md`.
- `compile/         (CICL compiler)` → the package is **`cicl/`**.
- `bootstrap/       (elastic state-backend setup)` → not a package; it is the
  single module `pipeline/bootstrap.py`. Remove the directory entry.
- `describe/        (describe + why)` → `why/` is its own package. Split them.
- Add the packages the block omits: `emit/`, plus the adapter packages `aws/`,
  `docker/`, `git/`, `ssh/`, `dns/`, `ansible/`, `opentofu/`, `secretsmgmt/`,
  `roles/`, and top-level `context.py`, `naming.py`, `errors.py`, `envfile.py`.
  Verify the list against the directory before writing it — do not copy this
  list on faith.
- `orchestrate/     (up, down, build, test, migrate, …)` — check the real module
  names in `$jb/docex/src/docex/orchestrate/` and correct if `up`/`down` are no
  longer what those modules are called.

**D3f — line 135.** "…so `compose up --build` builds every codebase's tag and
`docex` builds none of them itself." `orchestrate/up.py:58` does issue
`docker.build_image(svc_dir, target="build", tag=f"docex-initial-build-{svc}:latest")`.
The sentence is defensible on a narrow reading ("them" = the codebases' *tags*,
and this is a throwaway tag) but reads as "docex issues no build", which is
false. Add one clarifying clause naming the throwaway pre-populate build. Do not
restructure the surrounding argument — the mod-116 half of the sentence is
correct.

## D4. `test_projects.md` and `docex_process.md`

**D4a — `$jb/docex/plans/core/test_projects.md:10`.** "Route53 zone created by
`docex bootstrap`" → `docex projinfra up production`. The project's own
`elastic/infra/infra.yml:14` already says this. **Everything else in this file
was spot-checked green against both `infra.yml`s and the `api` tree — Mod 120's
update holds. Do not redo it.**

**D4b — `$jb/docex/plans/core/docex_process.md:32-35`.** The core-doc list names
two of five and contradicts this same file's line 90, which links
`test_projects.md`. Add the three missing entries with one-line descriptions:
`compiler.md`, `release_flow.md`, `test_projects.md`.

**D4c — `docex_process.md:88`.** The walk sequence reads
`bootstrap → compile → containerize → …`. `bootstrap` is not a command
(`__main__.py:274` describes the handler as "the existing state-backend setup
(formerly ``bootstrap``)"). Note that `test_projects.md:3` states the same walk
*without* that step, so the two docs disagree. Make `docex_process.md` agree
with `test_projects.md` — prefer removing the step over renaming it, unless
reading `test_projects.md:3` shows a rename is the better match.

---

# Part E — Rename residue in the nested smoke repos

**Read `$jb/docex/plans/core/test_projects.md § Commit cadence` before editing.**

Two nested git repos: `$jb/docex/test_projects/fixed` and
`$jb/docex/test_projects/elastic`. The **outer** repo tracks their files
directly (259 paths, no gitlinks), so every edit dirties both. Baseline: `fixed`
HEAD `d96d878` / tag `v0.0.17`; `elastic` HEAD `d075bea` / tag `v0.0.19`; all
three repos clean.

**Version tags do not move.** This is a comment- and prose-only change; no
project version moves, so `v0.0.17` / `v0.0.19` stay exactly where they are, and
`project.yml` is not edited in either repo. These are non-version-bump commits.

All 15 hits are prose/comments. **No magic-ref data changes** — every literal
ref in the tree is already correctly five-segment; verify this holds after your
edits.

## E1. Stale "four-segment" wording → "five-segment" (5 hits)

Ground truth, `doctrine/infrastructure/cicl.md § Magic Refs` (~lines 170-178):
`${codebases.<codebase>.core_services.<service>.<part>}` is **five** segments;
`${backing_services.<service>.<part>}` is three.

| Repo | File:line | Current |
| ---- | --------- | ------- |
| fixed | `infra/infra.yml:69` | `# Four-segment core magic refs — the worker's docker-DNS address` |
| elastic | `infra/infra.yml:79` | `# Four-segment core magic refs — the worker's Service Connect` |
| fixed | `infra/stage/tests/test_smoke.py:54` | `…worked: the four-segment magic` |
| elastic | `infra/stage/tests/test_smoke.py:47` | `…worked: the four-segment magic` |
| fixed | `plans/core/masterplan.md:67` | ``api.web` holds four-segment magic refs to `${codebases.api.core_services.worker.host}`` |

`Four-segment` → `Five-segment`, `four-segment` → `five-segment`. The refs
themselves are already correct — do not touch them.

`elastic/plans/core/masterplan.md:73` already reads "five-segment". **Leave it.**
(The prior sweep reported six hits; there are five. The claimed sixth was
already correct.)

## E2. Blind `service` → `core service` swap where **`codebase`** was meant (6 hits)

A naive rename applied to sentences about the *pre-v2* world. Pre-v2, `web` and
`worker` were separate **source trees / codebases**; saying they "were separate
core services until CICL v2" is self-contradictory, because they still are core
services. Self-contradiction sitting beside a correct sentence is the same
failure class as E1 — it reads as authoritative.

| Repo | File:line | Fix |
| ---- | --------- | --- |
| fixed | `infra/infra.yml:20` | `# separate core services before CICL v2` → `# separate codebases before CICL v2` |
| elastic | `infra/infra.yml:26` | same |
| fixed | `plans/core/api/api.md:21` | `two separate *core services* until CICL v2` → `two separate *codebases* until CICL v2` |
| elastic | `plans/core/api/api.md:21` | same |
| fixed | `plans/core/masterplan.md:63` | **two errors — see below** |
| elastic | `plans/core/masterplan.md:69` | **two errors — see below** |

The two masterplan hits read:

> See [`api/api.md`](./api/api.md). Two core services on one artifact; they were
> two separate core services until CICL v2, purely because pre-v2 CICL could not
> express "one artifact, two invocations".

Both errors must be fixed:

1. **"Two core services on one artifact" → three.** `api` now declares `web`,
   `worker`, and `clock`. This contradicts `fixed/plans/core/masterplan.md:51`
   and `elastic/…:9, :57`, which already say "One codebase, three core
   services."
2. **"two separate core services until CICL v2" → "two separate codebases".**

Consider whether "one artifact, two invocations" in the trailing quote should
become "three invocations" — read the surrounding sentence and keep it coherent;
it is describing what pre-v2 CICL *could not express*, so the historical "two"
may well be correct there. Use judgement and keep it self-consistent.

## E3. Stale core-service count in the codebase smoke tests (2 hits)

`{fixed,elastic}/core/api/tests/test_smoke.py:6-8` currently:

```
One image, two core services: `test.sh` runs this file and
`test_processor_smoke.py` together, because tests are keyed on the
codebase, not on the invocation.
```

`test.sh` now runs **five** test files across **three** core services. Before
editing, run `ls $jb/docex/test_projects/fixed/core/api/tests/` and read
`core/api/test.sh` to get the real file list — reported as
`test_processor_smoke.py`, `test_jobs_smoke.py`, `test_jobs_concurrency.py`,
`test_clock_smoke.py` alongside `test_smoke.py`, but **verify**. Update the
count to three and the file list to match reality. Keep the docstring's point
(tests are keyed on the codebase, not the invocation) — that is still the
lesson.

## E4. Retired "process type" vocabulary (2 hits)

`{fixed,elastic}/plans/core/api/api.md:23`:

```
running as a `role: scheduler` — a process type that was not a process.
```

"process type" is retired 1.6.0 vocabulary. → `a **core service** that was not a
process.` This sentence is a deliberate tombstone for the retired role and
should stay a tombstone — only the retired *noun* changes.

## E5. Commit cadence for Part E

Per `test_projects.md § Commit cadence`: **inner repo first, then the outer
catch-up.** Do not let the outer commit precede the inner ones.

1. `git -C $jb/docex/test_projects/fixed add -A && git -C ... commit` with a
   project-shaped message, e.g.:
   `docs: correct five-segment magic-ref wording and the codebase/core-service count`
2. Same for `$jb/docex/test_projects/elastic`.
3. **Do not tag.** `v0.0.17` / `v0.0.19` stay put.
4. The outer catch-up commit is folded into the Part G commit below —
   path-scoped to `docex/test_projects/`.

Confirm afterwards that all three repos are clean and that
`git -C <inner> describe --tags` still reports the pre-existing tag on an
*earlier* commit (expected — the tag does not follow these doc commits).

---

# Part F — Verification

## F1. Prove the examples compile (do not read them)

Write a throwaway harness in the **scratchpad** —
`/tmp/claude-1000/-home-ubuntu--claude-jean-baudrillard/67dcf749-a5b8-4bf1-9cfc-d41708121d48/scratchpad/verify_examples.py`.
**Do not commit it** and do not add it to `tests/`.

It must:

1. Walk `$jb/doctrine/` and `$jb/skills/` for ```` ```yml ```` / ```` ```yaml ````
   fences. **Exclude `$jb/upgrades/`** — those deliberately contain v2 BEFORE-state.
2. Classify a fence as `infra.yml`-shaped if it has a top-level `cicl_version:`,
   `codebases:`, or `backing_services:` key.
3. **Complete documents** (those carrying `cicl_version:`) validate **as-is**.
4. **Fragments** are spliced into one declared minimal skeleton and then
   validated. Model the skeleton on `_BASE_FIXED` in
   `$jb/docex/tests/unit/test_validate.py:22-44` — it is a known-good v3
   document. Merge the fragment's top-level keys into it.
5. Validate via the real code path, exactly as the unit tests do:

```python
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document

doc = CICLDocument.model_validate(yaml.safe_load(src))
issues = validate_document(doc, load_transfer_tables(project_root=None))
```

Run with `PYTHONPATH=$jb/docex/src python3 …`.

6. **Print the skeleton it used alongside each fragment result**, so the proof is
   auditable rather than asserted. A fragment that only passes because the
   skeleton supplied the missing piece is a *reported* fact, not a hidden one.

**Expected result:** every fence validates. Known fixtures that must pass
afterwards: `cicl.md:22-107` (already green before your edits — a regression here
means you broke something), `shape.md:100-134` (green only after B1),
`transfer_tables.md:601-620` and `:672-692` (green only after B2),
`clock.md:15-30`, `cicl.md:115-128`, `cicl.md:376-382`,
`transfer_tables.md:530-536`.

Report the harness output in your summary — the count of fences found, the
count validated, and any that needed a skeleton.

## F2. Excerpt integrity

Both of these caught real defects during design. Re-run them after editing.

- `cd $jb/docex && PYTHONPATH=src python3 -m docex why` lists **18** resources
  and exits 0. Then `docex why <name>` for each of the 18 exits 0.
- Every `Doctrine reference:` line in `$jb/docex/doctrine_excerpts/*.md` resolves
  to a real file **and**, where a `§` is named, a real heading in that file.
  Check mechanically, not by eye — that is how A2 was found and it is the check
  the next sweep should inherit. All 20 must resolve.
- `grep -rniE 'depends_on|consumes|scheduler|ofelia|process type' $jb/docex/doctrine_excerpts/`
  returns nothing.

## F3. Role surface

`cd $jb/docex && PYTHONPATH=src python3 -m docex roles` lists 6 roles including
`clock`; `python3 -m docex role clock` reports engine `container`, provided
parts `host`/`port`, and role-specific fields `health_check_path, schedules`.
This underwrites the A1 decision, so confirm it still holds.

## F4. Suites unchanged

```
cd $jb/docex
PYTHONPATH=src python3 -m pytest tests/unit -q          # expect 988 passed
PYTHONPATH=src python3 -m pytest -m integration -q      # expect 20 passed
```

**Any movement is a finding — report it, do not fix it.**

## F5. The verdict table

Close your report with one row per artifact and an explicit verdict, so the
advance close-out has a defensible statement rather than an impression:

| # | Artifact | Verdict | Evidence |
| - | -------- | ------- | -------- |
| 1 | `doctrine/**/*.md` | | |
| 2 | `docex/plans/core/*.md` | | |
| 3 | `tables/roles/*.yml` | | |
| 4 | `src/docex/**` | | |
| 5 | `tests/**` | | |
| 6 | `doctrine_excerpts/*.md` + `index.yml` | | |

For artifacts 3, 4, and 5 the expected verdict is **untouched, verified aligned**
— `tables/roles/` holds exactly `cache, clock, object_store, relational_db, web,
worker` with no `scheduler`, and both suites are unchanged. State the evidence,
do not just assert the verdict.

---

# Part G — Commit

Path-scoped. One outer commit covering Parts A–D, F, and the Part E catch-up,
**after** the two inner-repo commits from E5 have landed.

```
git add doctrine/infrastructure/shape.md \
        doctrine/infrastructure/specifics/transfer_tables.md \
        docex/doctrine_excerpts/ \
        docex/plans/core/ \
        docex/plans/modifications/118_artifact_alignment_sweep/ \
        docex/test_projects/ \
        skill_iter/
```

Verify with `git status --short` that nothing outside those paths is staged —
in particular that no `src/docex/**` or `tests/**` file crept in. The scratchpad
harness must not appear anywhere.

Commit message: `mod 118 complete; designed, implemented, and documented.`

**Do not push. Do not tag.**

---

# Reporting requirements

Beyond the verdict table, your summary must state:

1. **The `queries.json` outcome explicitly** — the operator asked to be told
   which way it went. Confirm the query text was kept and that the label landed
   on the `note` field (a real, read, surfaced field), not on an invented key.
2. **The `bootstrap`/`up`/`down` assessment** — that it was mechanical rename
   residue, fixed, and that `doctrine/infrastructure/docex.md` was already
   current and served as the transcription source.
3. **That A2 was found by a mechanical link check**, so the next sweep runs one.
4. **The `release_flow.md:262` lesson** — the message it restates is
   parameterized in code precisely so it could not go stale, and the doc went
   stale by restating rather than quoting it.
5. Anything you found that is **not** in this document, with the same
   file:line precision.

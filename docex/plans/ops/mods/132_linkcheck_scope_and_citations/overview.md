# Mod 132 — `linkcheck.py` scopes its checks independently and reads prose citations

Advance 006, mod 8 of 9. Folded in from advance 005's deferrals by operator
ruling. Territory is **`skills/cohere/executor/linkcheck.py`** in the
`jean_baudrillard` repo root — doctrine-shipped verification tooling, not `docex`
code. Mod docs live here because this is where the project's mod history lives.

Baseline: branch `006_surfaces_and_health`, HEAD `2a1997d`, tree clean.
`docex/.venv/bin/python -m pytest tests` from `docex/` → **1174 passed, 18
deselected** (re-run and confirmed at design time, 458 s).
`linkcheck doctrine skills` → green, 76 files.

---

## 1. The central design finding: the obvious arm reports 98 false positives

The first prototype did exactly what the brief described — find `<file>.md §
<Heading>` in prose, resolve the heading, report a miss — and reported **98
findings across `doctrine/` + `skills/` alone, every single one a false
positive.**

The cause is that the dominant citation form in this corpus is a citation
**inside markdown link text**:

```
[cicl.md § Service Fields](./infrastructure/cicl.md#service-fields)
```

There are **177** of these at the scope this mod adopts. Check 1 already resolves
every one of their anchors through the real anchor machinery. An arm that fires on
them is not finding drift — it is **duplicating a check that already works, and
reporting 98 findings on a clean tree.** That is the "tool configured to always
exit non-zero" failure this mod exists to prevent, arriving from the inside rather
than from scope, and it would have shipped had the prototype not been measured
against the real corpus before being believed.

So the finding narrows the arm's subject, and the narrowing is what makes it worth
shipping. **The arm's subject is a citation's *words* — the human-readable
`§ <Heading>` — which nothing in the toolchain verifies today, whether or not
those words sit inside a link.** Three classes exist, and they are distinguished
by *who checks what*:

| Class | Count | Anchor checked today? | Words checked today? |
| ----- | ----: | --------------------- | -------------------- |
| **In link text** — `[cicl.md § Surfaces](…#surfaces)` | 177 | **yes**, check 1 | **no** |
| **In an inline-code span** — `` `cicl.md § Surfaces` `` | 75 | n/a — there is no link | **no** |
| **Bare prose, running into the sentence** — `` `tests.md` § Integration Tests and § Contract Tests`` | 27 | n/a | **no**, and it cannot be (§ 4) |

The arm checks the words in all three, to the extent each form permits. It never
re-checks an anchor check 1 already owns.

## 2. The mixed case: link text is checked, and the measurement says the separation is reliable

When a citation sits in link text, the anchor and the words are **two independent
claims**. Check 1 verifies the anchor. Nothing verifies the words — so the anchor
can resolve while the words name a heading that is gone, and a reader following
the sentence rather than the hyperlink is misled. Whether that separation can be
made reliably was the open question; it is now measured.

### 2.1 The matching ladder

Applied to a citation whose text extent is **bounded** (see § 4), against the real
headings of the resolved target file, in order:

| # | Rule | Accepts | Measured |
| - | ---- | ------- | -------: |
| 1 | slug equals a heading's anchor | the ordinary case | **237** |
| 2 | candidate is a *prefix* of a heading | **truncated titles**, which are idiomatic and correct: `§ Per-core-service env` → *Per-core-service env (both foundations)* | **7** |
| 3 | a heading is a prefix of the candidate | citation carrying trailing words | **2** |
| 4 | candidate is a single all-lowercase token | **identifier references**, not headings: `[transfer_tables.md § env](…#anatomy-of-a-role-definition)` cites the `env` *field* documented inside the linked section | **5** (skipped, counted) |
| 5 | otherwise | **finding** | **1** |

Rules 2 and 3 are the only laxity, and both are *authorial shorthand for a heading
that exists*. Rule 4 is a named class, discovered by measurement: five citations
name a field or resource (`env`, `provides`, `ecs_cluster` ×3) rather than a
section title, and their anchors are correct. The all-lowercase-single-token test
is what keeps rule 4 from swallowing real findings — `§ Fan-out` and `§ Standards`
are single tokens too, and both stay checked because they are capitalized.

### 2.2 The one finding, and it is real

Across **127 files and 279 citations**, the final design reports exactly **one**:

```
BAD CITATION docex/test_projects/PRE_CUT_CHECKLIST.md:182
  -> infrastructure.md § Codebase Structure
  (heading not found in doctrine/infrastructure/infrastructure.md)
```

The line reads
`` [`infrastructure.md § Codebase Structure`](../../doctrine/infrastructure/infrastructure.md#repository-structure) ``.
**The anchor is live** — `#repository-structure` resolves, so check 1 passes it
and always would have. The words name a section that does not exist:
`infrastructure.md` has *Repository Structure* and *Codebase Containers*, and no
*Codebase Structure*. It is in `PRE_CUT_CHECKLIST.md`, the artifact mod 131
rewrote last week and the artifact this mod exists to bring into reach, and it is
a fourth instance of the drift class this advance has now found four times by
hand and once by tooling.

The repair is one word (`Codebase` → `Repository`) and it changes no claim. That
this mod's own tool found a live instance, in the file it was built to reach,
inside the check the brief was unsure was worth building, is the answer to sarge's
question: **the separation is reliable, so link-text citations are checked.**

## 3. A fail-open defect **in the tool we verify the doctrine with**

Raised at top level rather than as a numbered sub-point, because a check that
fails open is the defect class advance 005 catalogued eight times, and this one is
inside the verifier itself.

`linkcheck.py:152` reads:

```python
if rp in anchors and anchor.lower() not in anchors[rp]:
```

`anchors` is built **only from the scanned files**. So when a link points at a
markdown file *outside* the scanned roots, `rp not in anchors` is true and **the
anchor check is skipped entirely** — silently, with no output, and the tool prints
"No broken links, bad anchors, or duplicate filenames found." The existing
docstring is candid that "an unknown target fails open"; nothing in the *output*
is.

**Measured exposure, because a defect's severity is a number and not an
adjective:** at the shipped default scope (`doctrine` + `skills`), exactly **one**
anchor is silently unverified — `credentials.md:40` → `docex/plans/core/masterplan.md#the-shim`
— and it is **live**. At the new five-root scope, again exactly one — the
checklist's link into `RELEASING.md#the-cut-procedure` — also live. So the defect
is real and is hiding nothing today.

The fix costs three lines and is free given § 2 needs on-demand anchor extraction
anyway: the guard becomes "resolve the target's anchors, computing them if the
file was not scanned." Both remaining cases then verify rather than skip. This is
the third change in the mod and I am claiming it deliberately, because "reports
clean when it cannot answer" is precisely the property the rest of this design is
built to avoid, and shipping an arm that refuses to guess while leaving a
fail-open guard two functions above it would be incoherent.

## 4. Bounded vs. unbounded, and why 27 citations get their file checked but not their heading

A citation's text can only be checked if its **extent** is known. Two forms bound
it: link text ends at `]`, and an inline-code span ends at its closing backtick.
Bare prose does not end — the heading runs into the sentence — and I measured
three distinct shapes that each defeat a different guess about where it stops:

| Real line | Guess it defeats |
| --------- | ---------------- |
| `test_projects/PRE_CUT_CHECKLIST.md` § A.2.1 is the pre-walk audit for this structure — confirm… | reference **by section number**, then prose |
| `infrastructure/cicl.md § Container Registry.` (heading: *Container Registry and Service Images*) | **truncated** title with a sentence period |
| `projinfra.md §35): \`up production\` after…` | number, **no space**, inside a parenthetical |

The § 2.1 ladder accepts the second and rejects the other two. Adding sub-rules
to swallow them buys coverage and costs a new false-positive shape each time, and
**this advance has now produced two tooling false positives** — mod 131's ad-hoc
checker stripped `_` as markdown emphasis and nearly "fixed" two correct links,
and this mod's first prototype reported 98 findings on a clean tree. The trade is
not symmetric: a wrong finding provokes a wrong repair and burns the tool's
credibility, while a stated blind spot does neither.

So unbounded citations get their **file** verified (which is unambiguous) and
their heading **counted, not guessed** — the arm prints
`27 unbounded (file checked, heading not)`, so the blind spot is a reported number
rather than a silence. This also creates the right incentive: bounding a citation
in one backtick span, or writing it as a link, is what brings its words into
checked scope.

## 5. Released `CHANGELOG.md` sections are excluded from both checks

Hard constraint from mods 130 and 131, load-bearing on day one: with the exclusion
off, the arm reports **four permanent findings** in the seeds' frozen history —
`fixed/CHANGELOG.md:230,235` and `elastic/CHANGELOG.md:266,271`, exactly the four
mod 130 predicted, all bounded `contracts.md § …` citations against a file that
now has one heading. The repo-root `CHANGELOG.md` additionally carries **14 broken
relative link paths**, all in released sections; `[Unreleased]` is clean.

Mechanism: in any file named `CHANGELOG.md`, a `## ` heading matching `[<version>]`
opens a frozen section and `## [Unreleased]` closes it; frozen lines are skipped by
check 1 and by the arm. The preamble before the first `##` stays in scope. **545
lines** are skipped at the new default scope. The rule is general rather than
pointed at one path, because the governing distinction is a property of content,
not of location: per
[`advances/007_small_edges/changelog_released_section_link_paths.md`](../../advances/007_small_edges/changelog_released_section_link_paths.md),
**a link target may be repointed where a claim may not.**

## 6. Scoping: check 3's scope is *the doctrine corpus*, by rule

Check 3 (identical filenames) no longer walks "every root except `skills`". It
walks **exactly those scanned files that lie under `$jb/doctrine/`** — an
allowlist of one tree. Checks 1 and the arm walk every passed root.

**Why an allowlist and not a wider blocklist.** The exemption list has had to grow
twice for the *same* reason. `skills/` was exempted because the Agent Skills
Standard mandates one `SKILL.md` per skill; the seed trees must be exempted
because audit box B.14 mandates their `core/` trees be byte-identical (**9 `DUP
FILENAME` lines** at that scope); and `docex/doctrine_excerpts/`, which this mod
brings into check-1 scope, mirrors doctrine filenames by design as well
(`container_registry.md` exists in both). A rule whose exception list grows every
time the scan widens was never "all roots minus exceptions" — it was always "the
doctrine tree", written backwards.

Three gains over "exclude the seed trees from check 3":

- **The failure this mod exists to prevent becomes structurally impossible.**
  Under an allowlist, adding a check-1 root can never make check 3 fire. Under a
  blocklist, the next person to widen the scan must remember to extend the
  exemption, and the penalty for forgetting is a tool that always exits non-zero.
- **The rule states its own reason.** Doctrine filenames must be unique because
  doctrine files are cited *by bare filename* across the corpus. That is not a
  property of any other tree.
- **It is what makes the arm's resolution deterministic.** The arm resolves
  `cicl.md § Surfaces` by unique basename; check 3 is the guarantee that a bare
  doctrine filename resolves to one file. Where uniqueness genuinely does not hold
  (the mirrored trees), the arm reports **ambiguous** rather than guessing. The two
  checks become load-bearing for each other rather than merely adjacent.

**Rejected:** a plain root widening (cannot exit 0 — the thing not to ship); a
`--dup-root` flag (a knob whose only correct setting is the default); "check 3
always scans `doctrine/` regardless of args" (then `linkcheck.py skills` checks a
tree it was not pointed at — arguments should mean what they say; under the chosen
design a root outside `doctrine/` yields a printed "0 files").

### 6.1 The new default roots

| Root | Why in scope |
| ---- | ------------ |
| `doctrine/` | the corpus itself (unchanged) |
| `skills/` | thread-skill router pointers — `doctrine.md` calls keeping them valid "the one ongoing cost of this structure" (mod 121) |
| `docex/doctrine_excerpts/` | **required for the arm to be able to catch its own motivating instance** — `service_discovery.md`'s dead citation lived here. The sixth aligned artifact, and the only one with no automated consumer. |
| `docex/plans/core/` | `docex`'s live core planning docs — 5 files, 16 citations |
| `docex/test_projects/` | `PRE_CUT_CHECKLIST.md`, the mod's stated target, plus both seeds' `plans/core` (mod 130 § *Design questions* 3 logged that gap) |

Measured at that scope: **127 files; one finding** (§ 2.2), which this mod repairs;
zero from check 1 and check 3.

**What stays out — stated as a criterion so the next widening has one:** *live
doctrine-adjacent artifacts are in scope; frozen records and deliberately-broken
fixtures are not.*

- `docex/plans/modifications/` and `plans/advances/` — frozen design records
  (~60 stale links by construction; repointing them would falsify the record).
- Released `CHANGELOG.md` sections — same argument (§ 5).
- `upgrades/` — frozen release guides; two findings live there (a dead anchor in
  `upgrade_1.1.0.md`, a path to the deleted `core/reaper` in `upgrade_1.6.0.md`).
  `upgrades/README.md`'s own rule would permit repointing a *target*, so this is
  available future work, not a refusal.
- `skill_iter/eval/outcome/**/fixtures/` — fixtures whose broken links **are the
  fixture** (`masterplan-drift` exists to be drifted).
- `engineer/` — operator notes; one broken relative path.
- Generated residue — the walker now skips `.git/`, `.venv/`, `node_modules/`,
  `__pycache__/`, `.pytest_cache/`. Today it counts two untracked
  `.pytest_cache/README.md` files inside the seed trees as documents.
- Repo-root `CHANGELOG.md` / `README.md` / `RELEASING.md` — live, and I wanted
  them; held back for one measured reason (§ 11, decision 2).

## 7. What the tool prints

Exit code unchanged (non-zero iff findings). Two new labels in the existing column
style, plus a summary that reports **each check's scope and its counts** — because
`verify_examples.py` established the house rule for this tool family (*read the
counts, not just the exit code*), and because a regex regression in the arm would
otherwise show up as nothing at all: the citation count would fall to zero while
the exit code stayed 0.

```
BAD CITATION docex/test_projects/PRE_CUT_CHECKLIST.md:182  -> infrastructure.md § Codebase Structure  (heading not found in doctrine/infrastructure/infrastructure.md)
NO CITE FILE docex/plans/core/release_flow.md:118  -> nope.md § Teardown  (no file matches 'nope.md')

No broken links, bad anchors, dead citations, or duplicate filenames found.

Scanned 127 markdown files under doctrine, skills, docex/doctrine_excerpts, docex/plans/core, docex/test_projects
  links, anchors, citations : 127 files
  duplicate filenames       : 54 files (the doctrine corpus only)
  citations                 : 246 checked, 5 identifier refs skipped, 27 unbounded (file checked, heading not), 0 ambiguous
  frozen changelog lines    : 545 skipped
```

## 8. Demonstrating the arm failing

Per the standing rule that a pass never contrasted against a fail is not a check,
in two places:

1. **Live, against a real instance.** Reverse mod 131's repair: restore
   `docex/doctrine_excerpts/service_discovery.md`'s pre-131 citation
   `` `cicl.md § Resilience covers reachability, not resolvability` `` (verified:
   `cicl.md` has no heading beginning "Resilience", so it fails all four accepting
   rules), run the shipped default invocation, capture the `BAD CITATION` line and
   exit 1; then `git checkout` the file and capture exit 0 with the repaired
   citation passing. Both transcripts go into the implementation record.
2. **Permanently, as a fixture** — the same instance as a hermetic test, because a
   live demonstration passes once and a fixture passes forever.

Plus a third, unplanned: § 2.2's finding is itself the arm failing on text nobody
suspected, and its repair is the passing contrast.

## 9. Tests: `skills/cohere/executor/tests/`

New: `tests/test_linkcheck.py`, `tests/conftest.py` (a `sys.path` shim), and a
`.gitignore` for `__pycache__/` and `.pytest_cache/` — the repo has no root
`.gitignore` and bytecode residue was its own mod once (119).

`main()` is refactored so the checks are callable as a function taking
`(roots, doctrine_root, index_root)`; `main()` supplies the module defaults. The
CLI and the zero-dependency property are unchanged.

**Why not `docex/tests/`**, the repo's only running suite: `linkcheck.py` is not
`docex` code, and `docex`'s test count is a release-gate figure. Putting
doctrine-tooling tests there would mean a doctrine-corpus tool change churns
`docex`'s gate count, and would let a `docex`-only test run go red on a
doctrine-tree edit. The constraint that the count stay at **1174** says the same.

**Why colocated:** the test travels with the tool inside the skill directory, and
the tool imports nothing but the standard library, so `python3 -m pytest` runs the
tests with **no venv** (system pytest is 9.0.3) — unlike `verify_examples.py`,
which needs `docex` importable. Whoever can run the tool can run its tests.

**How it is gated:** `skills/cohere/SKILL.md` — the one document that tells an
agent to run this executor — gains the invocation, so the tests run on every
`cohere` pass, which `RELEASING.md` already fires whenever doctrine prose moves.
Runtime is well under a second.

### 9.1 The positive control

Both false positives this advance produced were tooling reporting violations where
none existed, and the answer to both is an assertion rather than a clean run. One
fixture corpus asserted to yield **zero** findings, carrying:

- headings with `_` — `` `health_check_path` ``, `verify_clean.sh` — cited as
  markdown-link anchors **and** as citations in link text **and** in code spans
  (underscore handling is where mod 131's false positive came from)
- **citations inside link text** whose words match exactly, are truncated
  (ladder rule 2), and carry trailing words (rule 3) — the 98-false-positive class,
  pinned as a control
- an identifier reference in link text (`§ env` against a section anchor) — rule 4
- a heading with dots and digits — `A.7 Fixed deploy credentials and deploy-target user`
- a heading whose text contains backticks — ``` `uses` Relationships ```
- a heading whose stripped punctuation must **not** collapse its hyphens —
  `Elastic × Production` → `elastic--production` (the original false-positive bug
  in this file)
- duplicate headings → GitHub's `-1` suffixing
- a citation inside a **fenced block** and one inside a blanked inline span
- a bare `§ Heading` with no file
- all three **unbounded** shapes from § 4 — none may be reported
- an **elided** path (`doctrine/.../x.md`) resolved by unique basename
- two mirrored non-doctrine trees with identical filenames
- a released changelog section carrying a dead citation *and* a broken link

### 9.2 The negative controls

Each asserted to produce **exactly one** finding of the right class: the § 8
citation; a **live anchor with dead words in link text** (the § 2.2 class, which
is the arm's whole justification); a dead markdown anchor; a missing file link; a
citation whose file exists nowhere; an anchor into a file **outside** the scanned
roots (§ 3 — must now report rather than skip); two identical filenames **inside**
`doctrine/`; and a dead citation in a changelog `[Unreleased]` section — the
contrast proving § 5's exclusion keys on the section and not on the filename. Plus
one ambiguity test: an ambiguous bare-filename citation is counted, not reported.

## 10. Out of scope

- **Doctrine.** Nothing under `doctrine/` is edited; findings are raised.
- **`docex/` source, tables, tests.** Untouched; the suite stays at 1174.
- **The seed inner repos** (`test_projects/{fixed,elastic}/`) — see § 11.
- Repairing `upgrades/`, `engineer/`, or the changelog's 14 released paths.

## 11. Decisions I made, and the one item for you

Sarge's three questions from the first draft, answered on my own authority where
the measurement settled them.

1. **The mixed case is checked** (§ 2). Measured: 279 citations, one finding, and
   the finding is real. The separation sarge asked me to test is reliable, and the
   thing that makes it reliable is nameable — rules 2–4 each correspond to a real
   authorial form, not to a tolerance dialled until the noise stopped.
2. **Repo-root `CHANGELOG.md` / `README.md` / `RELEASING.md` stay out**, deferred
   into the existing 007 brief rather than decided here. Reason, measured: all
   three are clean **except** `CHANGELOG.md:633`, inside `[Unreleased]`, which
   reads "``specifics/release_mechanism.md § Secrets`` — a file and a heading that
   have **never existed**" — a changelog entry describing mod 118's *repair* of a
   dead citation. **A quoted dead citation is indistinguishable from a live one**,
   so bringing those files in needs either an inline suppression marker
   (`<!-- linkcheck-ignore -->`, two lines of code and exactly one user today) or
   the 14-path repair that
   [`changelog_released_section_link_paths.md`](../../advances/007_small_edges/changelog_released_section_link_paths.md)
   already owns and already calls "strictly better for a reader". Supporting a
   *file* as a root is five lines whenever 007 wants it. I am appending this
   finding to that brief rather than opening a new one.
3. **Unbounded citations stay file-only** (§ 4).

**The one item for you, cheap to overrule.** The prototype found **two more dead
citations, in the seed trees**, both unbounded and therefore *not* flagged by the
shipped arm — nothing is blocked either way:

| File | Cites | Reality |
| ---- | ----- | ------- |
| `test_projects/fixed/infra/deploy_creds/README.md:12` | `§ "Fixed deploy credentials"` | heading is `A.7 Fixed deploy credentials and deploy-target user` |
| `test_projects/elastic/infra/deploy_creds/README.md:8` | `§ "Elastic AWS credentials"` | **no such section**; AWS credentials are covered by `A.1 Tooling` |

**I am not fixing them, and the reason is the walk rather than the words.** Both
files live *inside* the seed inner repos, so an edit obliges
`test_projects.md § Commit cadence`'s inner-repo commit in each — and it would add
commits on top of the git state mod 130 prepared for two expensive real-AWS walks
that start days from now. I checked that `containerize` only requires the tag to
*exist*, not to sit at HEAD, so the risk is genuinely small; it is not zero, and it
buys two lines of prose in files the tool will not flag. Say the word and I will
fix them in bounded form (both repaired citations verify); otherwise they belong
to whoever next touches those trees, and this table is the record.

> **Ruled (§ 12.3): sarge takes them**, accepting the reasoning and overriding the
> conclusion — the debt is owed because downstream projects copy those trees, and
> the vehicle is mod 130's full cadence (inner commit, `git tag -f`, outer
> catchup), which exists to keep audit box A.2.1's "on `main`, clean, tag at HEAD"
> true across exactly this kind of edit. Neither seed repo was entered by this mod;
> both remain clean.

## 12. Rulings at design review

Recorded so they are not re-litigated during implementation.

1. **Design approved as written**, including the link-text arm (§ 2), unbounded
   citations staying file-only (§ 4), and check 3 as a doctrine-tree allowlist
   (§ 6) — sarge's note on the last: an allowlist "closes a class" where the brief
   only asked to fix an instance.
2. **One addition, and it is now a rule this file states about itself.** The § 3
   replacement behavior must be visible in the output, not merely correct: an
   anchor that cannot be checked is **counted and reported**, never skipped in
   silence. Generalised by sarge past the one line: *a verifier may decline to
   answer, but it may not decline quietly.* Implemented as a **Declined** block —
   printed, counted, non-fatal — carrying unverifiable anchors, ambiguous
   citations, and the unbounded-citation count, and as a summary line reporting
   how many anchors resolved **outside** the scanned roots (the population the old
   guard silently skipped).
3. **Both of § 11's outstanding items are sarge's, not this mod's.** The two dead
   citations in the seeds' `deploy_creds/README.md` — he takes them, overriding my
   *conclusion* while accepting the reasoning: the fix is owed (downstream projects
   copy those trees) but it needs mod 130's full cadence (inner commit,
   `git tag -f`, outer catchup) to keep audit box A.2.1's "on `main`, clean, tag at
   HEAD" true, which is git surgery with a two-repo blast radius and not a
   linkcheck mod's business. `RELEASING.md:74`'s "five-artifact" undercount is his
   as well. **Neither is in this mod's tree.**
4. **The `CHANGELOG.md:633` observation lands in the 007 brief as a third end
   state** neither of that brief's two options contemplated: some dead citations
   exist *in order to be dead*, as evidence of a repair, so any checker reaching
   released history needs a suppression marker rather than a fix.

## 13. Implementation review

Zero design drift. `linkcheck.py` is **byte-identical** to the specification in
`implementation.md` (verified by extracting the spec's code fence and diffing).
Every figure in § 1.1's expected table came out exactly — 127 files, 54 check-3
files, 237/7/2 exact/truncated/extended, 5 identifier refs, 27 unbounded, 0
ambiguous, 545 frozen lines, one finding. **No matching rule was loosened to make
a test pass**, which was the one thing the implementor was told to escalate.

The demonstration is recorded in `implementation.md § Demonstration` with three
runs, and the count movement is the part that carries it: the reconstructed dead
citation moved from `exact` (237) into a finding (236), and the repair moved it
back and then to 238 once `PRE_CUT_CHECKLIST.md` was fixed. **A repair that merely
deleted a citation would have left `exact` at 237** — so the census, not just the
exit code, distinguishes fixing a citation from removing one. The implementor also
mutated three properties in a throwaway copy to prove the positive control is not
a tautology: stripping `_` → 3 failures, collapsing hyphen runs → 2, scanning the
raw line instead of the link-collapsed one → 2. Each of the advance's two real
false-positive classes trips `assert problems == []`.

### 13.1 One thing the design got wrong: there was already a test file

**`docex/tests/unit/test_linkcheck.py` exists** — 7 tests for this executor, in
`docex`'s suite, and its docstring says why: *"this suite is the only harness the
release gates actually run."* § 9's argument for colocating ("`linkcheck.py` is
not `docex` code") was made in ignorance of a deliberate prior decision, and the
1174 baseline **already included** these tests. One of them,
`test_two_same_named_doctrine_files_still_reported`, failed under the new rule —
correctly: it built a fake `tmp_path/doctrine` and passed under the old
**root-basename** scoping, which a directory *named* `doctrine` satisfied by
coincidence. § 6's allowlist keys on the real `$jb/doctrine`, so check 3 reported
`0 files` and exited 0.

Resolved inside this mod, in the territory sarge's kickoff named ("`linkcheck.py`,
**its tests**"), and the resolution keeps every constraint: the test now
monkeypatches `DOCTRINE_ROOT` onto the fixture, so it asserts the *rule* rather
than the coincidence, and the gate count stays at **1174**.

**Both suites stay, and the division is now written into both docstrings** rather
than left as an accident:

| Home | Seam | Runner |
| ---- | ---- | ------ |
| `docex/tests/unit/test_linkcheck.py` (7) | `main()` — argv, exit codes, the module's real defaults | `docex`'s suite, which the release gates habitually run |
| `skills/cohere/executor/tests/` (21) | `run_checks` — the ladder, slugify, the declined classes, the controls | bare `python3`, no venv; gated from `cohere`'s body |

Two homes for one tool would be drift if they covered the same seam. They do not:
the colocated tests inject `doctrine_root`, which is precisely what the CLI tests
cannot do. **A gating gap surfaced while writing that down and is recorded in both
files:** `RELEASING.md`'s table fires `pytest` on a *docex* change and `cohere` on
a *doctrine-prose* change, and a change to `linkcheck.py` alone is **neither** —
it is a `skills/` change, which gates the skill evals. Neither suite is
automatically gated for the one change class that most needs them.

### 13.2 Three corrections made during review

1. **`SKILL.md`'s preamble contradicted the bullet two lines below it** — "Run
   both executors first … defaults to `doctrine/` + `skills/`" where there are now
   three invocations and `linkcheck.py` defaults to five roots. My step 6 told the
   implementor to leave every other line alone; the instruction was wrong and it
   correctly reported rather than exceeded it.
2. **The test invocation gained `-p no:cacheprovider`, and it is load-bearing.**
   `verify_examples.py` has no skip-dirs guard, so it counts every `.md` under its
   roots — including `.pytest_cache/README.md`. Telling a cohere agent to run
   pytest *in the executor directory* would therefore have made the very next
   bullet's file count read 77 instead of 76: a defect introduced by this mod's own
   instructions, in the count that bullet tells readers to trust. Suppressing the
   cache directory fixes it without reaching into a file outside this territory.
3. **The old fixture comment justifying `sys.dont_write_bytecode`** ("the skills
   tree has no `.gitignore` covering it") is now stale — this mod adds one. The
   guard stays, with the reason restated: residue on disk still inflates
   `verify_examples.py`'s census.

## 14. Findings raised rather than fixed

1. **`verify_examples.py` is RED at HEAD: seven doctrine CICL examples no longer
   validate — and this advance is what invalidated them.** The failures name
   **rules 31, 32, and 33** and the `graphql`-format-not-implemented rule, i.e.
   every rule mod 125 introduced: the examples still declare a `port` on a
   surface-less worker, a `web` service with no `health_check_path`, and `uses`
   edges onto core services declaring no `surfaces:`. Fences at
   `cicl.md:386`, `cicl.md:433`, `shape.md:100`, `specifics/clock.md:17`, and
   `specifics/transfer_tables.md:553`, `:624`, `:695`.

   Proven independent of mod 132 (the implementor reproduced it byte-identically
   under `git stash --include-untracked`, and no file under `doctrine/` is touched
   by this mod). **It is invisible because nothing has run that harness since the
   doctrine edits landed at `9b16937`** — the standing instruction for this advance
   has been "`linkcheck doctrine skills` must stay green", and `linkcheck` cannot
   see a fence that fails to compile. This is precisely the failure the cohere
   skill's own text warns about: *"Advance 005 found the canonical `cicl.md` example
   broken twice … and neither was a shipped check at the time."* It is now a shipped
   check and it is red.

   **Doctrine prose, so untouched by me, and it is a cut blocker rather than a
   note:** Goal 3 SC 4 requires cohere findings resolved, and a project author
   copying `cicl.md`'s example writes an `infra.yml` this compiler rejects.
2. **`RELEASING.md` says "five-artifact alignment check"** at **two** lines, `:10`
   and `:73` — not the single `:74` my design recorded. `docex_process.md` and the
   advance plan's Goal 3 SC 1 both say **six** (`doctrine_excerpts` is the sixth,
   added by mod 111). A release gate that under-counts the artifacts it gates is
   worth one word. Assigned to sarge at § 12.3; the location is corrected here.
3. **`verify_examples.py` has no skip-dirs guard** (`rglob("*.md")` at `:315`), so
   generated residue enters its census: with a `.pytest_cache/README.md` present it
   reports 77 markdown files where `linkcheck` reports 76. Pre-existing and
   harmless to correctness — a README has no yml fences — but it inflates a count
   the `cohere` body tells readers to trust. This mod neutralised the *interaction*
   it would otherwise have caused (§ 13.2.2) rather than reaching into that file.
4. **The fail-open anchor guard** (§ 3) — fixed in this mod, but recorded as a
   *finding about the verifier* because that is the more transferable fact: the
   tool the doctrine uses to check itself contained the defect class the doctrine
   spent an advance cataloguing, and it was invisible because failing open prints
   nothing. Sharpened by review: **mod 121's changelog entry already reports this
   fail-open as addressed** ("its anchor check silently *failed open* on any target
   outside the scanned root … anchors resolve across both trees"). Adding `skills/`
   as a root closed the *instance* and left the guard — and therefore the class —
   in place. A defect described as fixed in a changelog is harder to find twice
   than one never mentioned.
5. **A quoted dead citation cannot be told from a live one** (decision 2 above) —
   appended to the 007 changelog brief, because it is the one structural obstacle
   between this tool and full repo coverage.

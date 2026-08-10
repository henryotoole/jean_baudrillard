---
name: cohere
description: Instructions for assessing the coherency of the doctrine. This skill is a sort of refinement step for the doctrine. It finds logical inconsistencies, improper wording, grammar and link failures, etc. This command will be operator-triggered.
metadata:
  type: conventional
---

The doctrine's many different documents form a single corpus of text. It's critical that this corpus be both internally consistent (with itself) and externally consistent (with the agent's model and the broader world). This skill provides a sort of checklist for assessing the doctrine.

# What To Check For

## Conceptual Problems

Check for:
1. Any internal inconsistencies
	+ Places where lexicon words are used inconsistently
	+ concepts and patterns represented in the text do not contradict
	+ text does not contain concepts which are untrue or contradict the agent's model
2. Check for skill coverage of the conditional stratum.
3. Check for detail creep into the resident stratum.

**Do this pass yourself. Do NOT delegate it to a subagent.** The conceptual check is a single whole-corpus judgment: contradictions, vocabulary drift, and stratum creep only surface when every doctrine file is held in *one* context at once and reasoned across. A subagent can only hand back a summary — that strips out the cross-file connective tissue this pass depends on, and tends to produce false positives you then have to re-verify anyway.

So load the corpus into **your own** context: read every markdown file under `$jb/doctrine/` and all subfolders — the full set, not a sample, not via a subagent. There are a few dozen files; reading all of them is expected and necessary for master-level editing.

Enumerate each problem you find for the operator. Do **not** fix conceptual problems yourself unless directed — the operator will fix them (or point you at specific ones to fix), then clear context and re-run.

## Mechanical Problems

Check for:
1. Broken links or references
2. Spelling and grammar problems
3. Identical filenames (all filenames should be unique)
4. Examples that do not compile (fences that are not valid `infra.yml`)

Unlike the conceptual pass, you *should* delegate and automate the mechanical pass, as the changes are generally localized and you'll get a chance to double check delegated work with full-corpus context.

Run all three of the below first, in the order given, from this skill's directory. Both executors take optional root paths; `verify_examples.py` defaults to `doctrine/` + `skills/`, and `linkcheck.py` defaults to five roots (see its first sub-bullet) because a hand check that passes once is not a check:

- `python3 executor/linkcheck.py` — deterministically reports check 1 (broken links / bad heading anchors), check 3 (duplicate filenames), and a third arm: **dead citations**, where the words of a `<file>.md § <Heading>` reference name a heading that no longer exists. Do not hand-derive GitHub anchor slugs; the executor already encodes them correctly. Two things to know before reading its output:
	- **The two scopes are independent.** Checks 1 and the citation arm walk five roots by default (`doctrine/`, `skills/`, and `docex/`'s `doctrine_excerpts/`, `plans/core/`, and `test_projects/`); the duplicate-filename check walks the doctrine corpus only, because `skills/`, the two seed projects, and `doctrine_excerpts/` all carry mirrored filenames *by design*. Released `CHANGELOG.md` sections are frozen history and are excluded from both.
	- **Read the counts, not just the exit code**, and read the `Declined` block. The tool prints what it *could not* check — unverifiable anchors, ambiguous filenames, and citations whose heading text has no closing delimiter — because a verifier may decline to answer but must not decline quietly. A citation count that falls to zero is a regression in the tool, not a clean corpus.
- `python3 -m pytest executor/tests -p no:cacheprovider` — `linkcheck.py`'s own unit tests, ~1 s, no virtualenv needed. Run these **first**. A checker that reports violations where none exist is as corrosive as one that misses them: this advance produced two such false positives, one of which nearly "fixed" two correct links, and these tests are the positive control that pins the classes they came from. (`-p no:cacheprovider` is load-bearing, not tidiness: pytest's cache directory contains a `README.md`, and `verify_examples.py` counts every `.md` under its roots — so caching here would silently inflate the file count the bullet below tells you to read. `linkcheck.py` skips generated residue; `verify_examples.py` does not.) A second suite of end-to-end CLI tests for the same executor lives in `docex/tests/unit/test_linkcheck.py` and runs with `docex`'s suite.
- `python3 executor/verify_examples.py` — check 4. Extracts every `yml`/`yaml` fence and pushes the `infra.yml`-shaped ones through docex's real CICL parse + validate path, so an example is proven by compiling rather than by reading.

`verify_examples.py` **classifies** each fence, and the class decides what "pass" means: `COMPLETE` (validates as-is), `FRAGMENT` (spliced into a skeleton first), `PROJECT-LOCAL` (declares a role/engine the bundled tables cannot know, so only target resolution must be clean), and two classes that are *deliberately not standalone documents* — `ILLUSTRATIVE` (contains `...` placeholders) and `EXCERPT` (quotes part of a larger document, borrowing an `&anchor` defined in another fence, e.g. `logging: *default-logging`). Neither of the last two is counted as a pass, and both are reported on their own line. If a genuinely broken fence ever trips one of those conditions, **the count is what catches it** — so read the counts, not just the exit code.

Both exit non-zero if anything is found. **Prove examples by compiling them, not by reading them.** Advance 005 found the canonical `cicl.md` example broken *twice* — once by a compile harness and once by an independent tab census — and *neither* was a shipped check at the time.

Then dispatch a subagent for check 2 (spelling and grammar), which is not deterministic.

Review every reported problem yourself. If fixing it does not change the meaning of the text, just fix it. *However*, if there's any ambiguity as to whether the intent or concept may change as a result of the fix, *always ask the operator* — note the problem and propose the solution in multiple-choice form.
# Mod 139 — QA instrument hygiene

Two coherent halves, each cleaning a *quality-assurance instrument* whose blind
spot let a real defect hide. Neither changes `docex` runtime behavior; both harden
the tooling that watches the repo.

- **Half A** — bring the three repo-root markdown files (`CHANGELOG.md`,
  `README.md`, `RELEASING.md`) into `linkcheck.py`'s default scan, and repair the
  historical link residue that blocked that.
- **Half B** — close the collection hole that let 60 fast compile tests sit in a
  directory named `integration`, invisible to both standard pytest invocations,
  and add a guard so the hole can never silently reopen.

Design records for the two halves are the briefs at
`docex/plans/advances/008_housekeeping/references/changelog_released_section_link_paths.md`
and `.../misfiled_compile_tests.md`. This overview records the design *decisions*
and the investigation that fixed the ambiguities the briefs left to judgment.

---

## Half A — linkcheck scope + CHANGELOG link repair

`linkcheck.py` lives at `skills/cohere/executor/linkcheck.py` (repo-root
relative). Four code/doc changes plus a payoff step.

### A1. Repair the 16 dead relative links in released CHANGELOG sections

**Key fact established during design: all 16 links are in FROZEN (released)
sections.** `[Unreleased]` spans lines 18–76; every one of the 16 sits below line
77 (sections `[2.0.0]` down to `[0.6.0]`). `scannable_lines` frozen-skips released
changelog sections (mod 132, `CHANGELOG_RELEASED_RE`), so **none of these 16 is
linkcheck-enforced**. The repairs are pure courtesy for human readers — exactly as
the brief's item-5 note says. This means no repair can *break* the linkcheck
payoff, and a link whose live target genuinely no longer exists can be left as
frozen record without failing anything.

The residue falls into patterns (line numbers re-grepped 2026-08-21; they will
drift again as the file is edited — match on link text, not line number):

**Pattern 1 — `../doctrine/...` → `./doctrine/...` (escapes repo root).** The file
used to sit at `docex/`; `../doctrine` resolved then, escapes the repo root now.
Fix the prefix only. Targets verified to exist:

| Line | Link text | Fixed target |
| ---- | --------- | ------------ |
| 2492 | `elastic_route53_zone.md` | `./doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md` |
| 2552 | `contracts.md § Health Checks` | `./doctrine/infrastructure/contracts.md#health-checks` (see note) |
| 2677 | `projinfra/ec2_traefik.md` | `./doctrine/infrastructure/specifics/projinfra/ec2_traefik.md` |
| 2687 | `docex.md` | `./doctrine/infrastructure/docex.md` |
| 2704 | `projinfra/fixed_reverse_proxy.md` | `./doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md` |
| 2751 | `docex.md` | `./doctrine/infrastructure/docex.md` |
| 2787 | `cicl.md § Simplifications` | `./doctrine/infrastructure/cicl.md#simplifications` |
| 2879 | `cicd.md § Rollback` | `./doctrine/infrastructure/cicd.md#rollback` |
| 2904 | `cicd.md § Rollback` | `./doctrine/infrastructure/cicd.md#rollback` |
| 3590 | `shape.md` | `./doctrine/infrastructure/shape.md` |
| 3591 | `elastic_bootstrap.md` | see special-case below |

- Anchors `#simplifications` (cicl.md `### Simplifications`) and `#rollback`
  (cicd.md `### Rollback`) verified present.
- **Line 2552 note:** `contracts.md` no longer has a Health Checks section — that
  content moved to `healthchecks.md`. The link *text* `contracts.md § Health
  Checks` is the frozen historical CLAIM and stays verbatim; the anchor
  `#health-checks` no longer resolves in `contracts.md`. Because the link text
  names `contracts.md` specifically, the least-surprising courtesy target is
  `contracts.md` itself (matches the visible claim). Only the `../`→`./` prefix is
  repaired. The stale anchor is left as frozen record (unenforced). *Rejected
  alternative:* repointing to `healthchecks.md` — the visible text says
  `contracts.md`, so that would mismatch text and target.

**Pattern 2 — `plans/...` → `docex/plans/...` (only resolved from `docex/`).**

| Line | Fixed target | Status |
| ---- | ------------ | ------ |
| 2465 | `docex/plans/modifications/048_elastic_walk_polish/` | dir exists ✓ |
| 2528 | `docex/plans/modifications/047_smoke_walk_polish/` | dir exists ✓ |
| 2663 | `docex/plans/campaigns/shape_overhaul_mod_list.md` | **file deleted, no replacement** — see below |

**Pattern 3 — relocated / retired triage briefs.**

| Line | Link text | Decision |
| ---- | --------- | -------- |
| 384 | `007_small_edges/contract_spec_version_ungated.md` | **Repoint** to `./docex/plans/advances/008_housekeeping/references/contract_spec_version_ungated.md`. Same file, relocated during advance setup — a sanctioned target repoint (the filename is unchanged; only the advance folder moved). |
| 638 | `007_small_edges/doctrine_excerpts_stale_entries.md` | **Leave unchanged.** The file was *retired* (not relocated) and subsumed by `doctrine_excerpts_overhaul.md`. The link text embeds the retired filename as part of a frozen claim ("four booked at `…stale_entries.md`"). Repointing to a *differently-named* brief would misrepresent that claim (reader sees one filename, lands on another). Per the brief's own conditional ("suppress if repointing would misrepresent"), and because the line is frozen (linkcheck never evaluates it), no repoint and no marker is warranted — a `<!-- linkcheck-ignore -->` marker is inert on a frozen line. The dead reference is the historical record. |

**Special cases — targets that are genuinely gone with no live replacement:**

- **Line 3591 `elastic_bootstrap.md`** — the doc no longer exists anywhere. The
  prose is about the two-phase elastic bootstrap and NS delegation. The closest
  live home is `./doctrine/infrastructure/specifics/projinfra/projinfra.md` (the
  projinfra overview that now documents the bootstrap phases). **Repoint to
  `projinfra.md`** as a best-effort courtesy target; the implementor confirms
  `projinfra.md` actually covers the two-phase bootstrap and, if the delegation
  content is better homed in `elastic_route53_zone.md`, uses that instead. Frozen,
  so unenforced — a sensible live landing spot is the whole goal.
- **Line 2663 `shape_overhaul_mod_list.md`** — the campaign file was deleted with
  no replacement. **Leave unchanged.** There is no live target to repoint to;
  fixing the `plans/`→`docex/plans/` prefix would still point at a nonexistent
  file, buying nothing. Frozen record stands.

**Hard rule for A1: repair link TARGETS only. Do not change one word of prose,
including the visible link text (the § claims).**

### A2. File-as-root capability in `linkcheck.py`

`main()` rejects any root that is not a directory (`os.path.isdir`), and
`markdown_files()` only `os.walk`s directories. Two small changes:

- `markdown_files(root)`: if `root` is a file, return `[realpath(root)]` when it
  ends in `.md`, else `[]`.
- `main()`: accept a root that is a directory *or* an existing `.md` file; reject
  only genuinely-missing paths.

`display_base` (via `os.path.commonpath`), `scannable_lines`, and check 3 all
already tolerate file paths — no other change needed.

### A3. Inline suppression marker `<!-- linkcheck-ignore -->`

In `scannable_lines`, skip any physical line containing the literal marker
`<!-- linkcheck-ignore -->` (per-line suppression, for live lines that *quote* a
dead reference as evidence and cannot be repaired without destroying it). To honor
this file's stated ethos ("nothing skipped in silence"), the skip increments a
`stats["suppressed"]` counter that is printed in the summary — not skipped
silently. This is a few lines beyond the brief's "~2", justified by the file's own
"a verifier may decline to answer; it may not decline quietly" doctrine.

### A4. State the target-vs-claim rule once, in a shared location

The rule — *a link **target** may be repointed in frozen history; a **claim** may
not* — is currently stated locally in `upgrades/README.md` (the "One narrow
exception" paragraph) and paraphrased inside `linkcheck.py`'s `scannable_lines`
docstring. **Canonical home: `RELEASING.md`**, which already governs the changelog
roll (Cut Procedure step 3). Add a short subsection stating the rule crisply, then
add a one-line pointer from `upgrades/README.md`'s local statement to the
canonical one. Kept to a small insertion in each; wording treated with
doctrine-level care (exact text specified in `implementation.md`).

### A5. Payoff — add the three root files to `DEFAULT_ROOTS`

Add `CHANGELOG.md`, `README.md`, `RELEASING.md` (repo-root file roots) to
`DEFAULT_ROOTS`, and update the "WHY these five" scoping comment (now eight) and
the module docstring to reflect file-roots + the suppression marker + that
released changelog sections remain frozen-skipped even though `CHANGELOG.md` is
now a scanned root.

**Pre-verified during design (so the payoff cannot design in a failure):**
- `CHANGELOG.md` `[Unreleased]` (18–76): no relative links at all.
- `RELEASING.md`: all 12 relative links resolve at the file level (including
  `:74`, repaired by the operator during setup); anchors
  `#running-the-automated-tests` and `#branch-conventions` verified present.
- `README.md`: no links.

The implementor still runs `linkcheck` to confirm green. If any *live* (non-frozen)
link in `RELEASING.md`/`README.md` breaks, it is repaired (those files are not
frozen).

---

## Half B — close the compile-test collection hole

`docex/tests/integration/test_compile.py` holds 61 test functions; exactly one
carries `@pytest.mark.integration` (`test_mod062_ec2_traefik_hcl_is_tofu_valid`,
line 1501, which shells out to `tofu validate` — a genuine boundary crossing). The
other 60 are fast, hermetic, in-process compile tests. Sitting in a dir named
`integration` but unmarked, they are collected by `pytest tests` yet invisible to
both `pytest tests/unit` (wrong dir) and `pytest tests -m integration` (unmarked).

### Investigation findings (collection-only, no execution)

Baseline collection counts:

| Bucket | Count |
| ------ | ----- |
| `pytest tests/unit` | 1172 |
| `pytest tests -m integration` | 21 |
| `pytest tests` (all markers, `-m ""`) | 1257 |
| `pytest tests` (default, `-m 'not integration'`) | 1236 |

Partition today: `1172 + 21 = 1193 ≠ 1257`. **The hole is exactly 64 items** =
1236 − 1172 (60 functions, 4 of them parametrized ×2 = 64 collected items).

**The tree is clean beyond `test_compile.py`.** Only `tests/unit/` and
`tests/integration/` hold tests (fixtures are `norecursedir`'d; no top-level test
files). Every *other* file in `tests/integration/` is fully integration-marked
(per-function or a file-level `pytestmark`). So relocating `test_compile.py`'s 60
fast tests is sufficient to make the partition hold — **no surprising set of
additional misfiles exists**, so no escalation on that front.

### B1. Relocate — the move (decided at plan review)

- `git mv tests/integration/test_compile.py tests/unit/test_compile.py`, then
  **remove** the single integration test (and the `_tofu_validate` helper, used
  only by it) from the unit copy.
- Create a new integration file holding *only* the integration test plus the
  helpers it needs (`_copy_fixture`, `_FIXTURE_ELASTIC`,
  `_compile_elastic_with_reverse_proxy`, `_tofu_validate`, imports, the
  `@pytest.mark.integration` + `skipif(tofu)` + `parametrize` stack). Using
  `git mv` for the bulk (60/61 tests) keeps history legible on the majority.

The 64 relocated items were already in `pytest tests`; moving them to `tests/unit/`
keeps them there. **So the relocation alone changes neither `pytest tests` (1236)
nor `-m integration` (21)** — it only lifts `pytest tests/unit` from 1172 → 1236.

### B2. The durable fix — a partition guard

A new fast, hermetic test `docex/tests/unit/test_collection_partition.py` asserting:

```
collected(tests/unit) + collected(-m integration) == collected(tests, all markers)
```

**Form:** three `--collect-only` subprocesses (`sys.executable -m pytest …
--collect-only -q -p no:cacheprovider`, cwd = docex root), counting collected node
ids by lines containing `::` (robust: every node id contains `::`, no summary or
fixture line does). Collection does **not** execute tests, so there is zero docker
contention — safe to live in the default suite. The three invocations:

1. `pytest tests/unit --collect-only` → unit bucket (default `-m 'not integration'`
   applies; unit has no marks). Matches the real operator invocation.
2. `pytest tests -m integration --collect-only` → integration bucket (CLI `-m`
   overrides `addopts`).
3. `pytest tests --collect-only -m ""` → all (empty markexpr disables filtering).

**Why subprocess, not in-process:** pytest is not reentrant within a running
session. **Why it catches the class:** an unmarked test in `tests/integration/`
lands in neither bucket (sum < all → fail); an integration-marked test under
`tests/unit/` double-counts (sum > all → fail). The guard fires wherever the hole
opens, which is the property the relocation alone cannot buy.

The guard test is unmarked and lives in `tests/unit/`, so it adds +1 to *both* the
unit bucket and the all bucket, +0 to integration — the equation stays balanced.

### Count reconciliation (important for the report)

The relocation is total-neutral for `pytest tests` and `-m integration`, as
stated. But the mod also **adds new tests** (an intended, gate-required addition,
not drift):

- +1 partition guard (`tests/unit/test_collection_partition.py`).
- +N file-as-root CLI tests in `docex/tests/unit/test_linkcheck.py` (the release
  gate for a `cohere` executor change *requires* colocated tests; the `main()`
  seam is tested in the docex suite — see that file's docstring).

So after the mod: `pytest tests` = **1236 + (1 + N)** passed, 21 deselected;
`pytest tests -m integration` = **21** passed. The suppression-marker test (A3)
goes in the *executor* suite (`skills/cohere/executor/tests/test_linkcheck.py`,
run without a venv) and does **not** touch the docex counts. The final
counts and the guard's actual equation are reported after execution. The 64
relocated items remain green and present — verifiable precisely because the
partition equation now balances.

---

## Cross-artifact / drift notes (handled in the documentation step, not implementation)

Per `modifications.md`, implementation must not edit core planning docs. These are
the corporal's to update in the doc step:

- **`docex/plans/core/docex_process.md` § Running the automated tests, item 2** —
  currently describes the 60-test hole as the *unfixed* structural cause and cites
  `misfiled_compile_tests.md`. Update to: the compile tests now live in
  `tests/unit/`; the partition is guarded by
  `test_collection_partition.py` asserting the buckets partition the suite. Keep
  the mod-128 "twelve red behind a green report" as motivation, in past tense.
- **`RELEASING.md` (A4)** and **`upgrades/README.md` (A4)** are *not* core planning
  docs (repo-root process docs), so their edits are substantive deliverables and
  belong in `implementation.md`.
- **`doctrine_excerpts/`** — no resource introduced/retired/renamed; no `index.yml`
  change. Confirmed.
- **`linkcheck.py` docstring** — updated as part of A2/A3/A5 (scope + behavior).

## Escalation check

None of the three escalation conditions in the kickoff is met: the guard surfaces
only `test_compile.py` (no large/surprising set); the target-vs-claim shared home
is a small insertion; the briefs' delegated judgment calls (lines 638, 2663, 3591,
2552) are resolved above within corporal authority. Per the C.O.'s explicit
instruction ("Decisions are made; run the full cycle"), this cycle does **not**
pause for design approval — it proceeds through implementation, execution, review,
and documentation.

## Design questions

None outstanding.

# Releasing the Doctrine

This document defines the **doctrine-wide release process** — how the whole
`jean_baudrillard` repo (doctrine prose, skills, and `docex`) advances from one
version to the next as a single, coherent unit.

It generalizes what used to be `docex`-only. The cut procedure originally lived
in [`docex/plans/core/docex_process.md`](./docex/plans/core/docex_process.md)
§ *Cutting a version*; that section now points here, and `docex_process.md`
keeps only the `docex`-**development** specifics (mod cycles, the six-artifact
alignment, expensive tests). A release is the event that bundles a development
campaign into a versioned snapshot of the entire repo.

## One Version for the Whole Repo

There is exactly one version number, stored on a single line in
[`VERSION`](./VERSION) at the repo root. It is the source of truth. Three other
places carry the same number and are **synced to `VERSION` at release time**, never
edited independently:

| Artifact | Why it carries the version |
| -------- | -------------------------- |
| [`VERSION`](./VERSION) | The source of truth. |
| `docex/pyproject.toml` (`version`) | Python packaging metadata for the `docex` package. |
| `docex/src/docex/__init__.py` (`__version__`) | Runtime version `docex` reports (`docex --version`). |
| `.claude-plugin/plugin.json` (`version`) | **Load-bearing.** The Claude plugin cache is keyed on this value — bumping it is what makes an operator's `setup.sh` re-run pick up changed/added/removed skills (a fresh cache snapshot). A stale value silently strands skill updates. |

The `docex` **image** is tagged with the same number: `docex:<version>`. A
project pins it through `project.yml`'s `docex_version` field, so a project's
pin *is* the doctrine version that project sits on. (The field keeps its
`docex_version` name for now; renaming it to `doctrine_version` is a future
shim change.)

### Lockstep, including no-op `docex` rebuilds

Every release re-tags and rebuilds the `docex` image at the new version **even
when no `docex` code changed** (e.g. a skill-only or doctrine-only release). The
rebuilt image is byte-identical apart from the embedded `__version__`; the cost
is near-zero and deterministic, and the payoff is a clean invariant: *doctrine
version `X` ⟺ `docex:X`*, with no version-mapping table to maintain. This is the
deliberate trade chosen when the version was unified (see the design discussion
that produced this document).

A project is **not** forced to repin on a doctrine-only release — projects move
their `docex_version` pin when they choose (via the `project-upgrade` skill).
The new image simply exists, available, when they do.

## Versioning Semantics (SemVer over the whole repo)

The version is SemVer, but the "public contract" it tracks is the whole repo's
observable surface, not just `docex`'s CLI:

- **MAJOR** — a breaking change to any consumed contract: `docex` CLI/behavior,
  the CICL surface, a doctrine **rule** that invalidates existing projects, or a
  resident/skill change that breaks an established operator workflow. A MAJOR
  almost always ships a `kind: rebuild` upgrade guide (see
  [`upgrades/README.md`](./upgrades/README.md)).
- **MINOR** — backward-compatible additions: a new skill, a new transfer-table
  role, a new `docex` command, new doctrine guidance that doesn't invalidate
  existing projects. Will always ship with an upgrade guide.
- **PATCH** — fixes that change no contract: a `docex` bug fix, doctrine-prose
  corrections, skill wording. Usually needs no upgrade guide.

When a change spans categories, the **highest** applicable level wins.

## What Gates a Release (by what changed)

A release bundles one or more completed development campaigns. Which validations
gate the cut depends on which of the three strata the campaign touched:

| If the release changed… | Gate before cutting |
| ----------------------- | ------------------- |
| `docex` behavior (code/tables) | The six-artifact alignment check + `cd docex && python -m pytest tests`, then `python -m pytest tests -m integration` **as a separate invocation**. Three ways to get a number that looks like an answer and is not, all documented at [`docex_process.md § Running the automated tests`](./docex/plans/core/docex_process.md#running-the-automated-tests): never bare `pytest`; never both `-m` flags in one run (`pyproject.toml`'s `addopts` already carries `-m 'not integration'`, so a combined run matches nothing and still exits 0); and **run from `docex/`, not the repo root** — `pytest docex/tests` cannot import `tests.conftest`, so it reports a deselect count one short of the truth, collects nothing, and does not fail loudly. For **MINOR/MAJOR**, the two-foundation **test-project smoke walks** per [`docex/test_projects/PRE_CUT_CHECKLIST.md`](./docex/test_projects/PRE_CUT_CHECKLIST.md). PATCH skips the smoke walk. |
| Skills (`skills/`) | `skill-iteration` trigger eval (do descriptions still fire correctly, suite-level) + outcome eval for materially-changed skills. **Gate on `run_suite.py`, not `run_eval.py`.** `run_suite.py` runs each query in an empty temp cwd, so loading a skill is the only route to the doctrine — which is the thing a trigger eval claims to measure. `run_eval.py` still runs the child inside this repo, where the model can `grep doctrine/` instead of reaching for a skill and the run scores a false ∅. Advance 006's gate was measured before that fix and produced one **invented** hole and one **mischaracterized** one (a sibling poaching 5/5 read as ∅), and a skill description was edited on the strength of each: [`trigger_eval_cwd_confound_run_eval.md`](./docex/plans/advances/floating_todo/surprise_discovered/trigger_eval_cwd_confound_run_eval.md). A confounded instrument is worse than no instrument, because its output looks like a finding. |
| Doctrine prose (`doctrine/`) | `cohere` static audit (dangling links, skill-pointer resolution, resident discipline, contradictions). **Plus `skills/cohere/executor/verify_examples.py` green** — a doctrine rule change can invalidate the doctrine's own worked `infra.yml` examples, and no other gate can see a fence that fails to compile. Advance 006 left seven of them invalid for the length of an advance because the standing check was `linkcheck`, which reads links and not YAML. |
| `cohere`'s executor tooling (`skills/cohere/executor/`) | Its own colocated tests, plus a green run of each tool at its default scope. This row exists because a change to `linkcheck.py` or `verify_examples.py` fires **neither** of the two rows above — it is not `docex` behavior and it is not doctrine prose — so before it was written, the verifiers were the only thing in the repo with no gate of their own. |

A release that only adds skills and top-level docs (no `docex` behavior change,
no doctrine-rule change) is a MINOR and skips the smoke walk.

## The Cut Procedure

Run from a clean tree on `main` (trunk-based, per
[`doctrine/infrastructure/version_control.md`](./doctrine/infrastructure/version_control.md#branch-conventions)),
after the campaign's mod cycles are complete and the applicable gates above are green.

1. **Assign the version `<v>`** per the SemVer semantics above.
2. **Author the upgrade guide** that ships with `<v>` —
   `upgrades/upgrade_<v>.md`, per [`upgrades/README.md`](./upgrades/README.md).
   Skip only for a PATCH with literally no upgrade action (the chain treats a
   missing release as "no action").
3. **Roll the changelog.** In [`CHANGELOG.md`](./CHANGELOG.md), move
   `[Unreleased]` → `[<v>]` with today's date (Keep a Changelog format).
4. **Set the version.** Write `<v>` to [`VERSION`](./VERSION) and sync the three
   tracked artifacts: `docex/pyproject.toml`, `docex/src/docex/__init__.py`,
   `.claude-plugin/plugin.json`.
5. **Commit** the version bump and changelog roll.
6. **Tag the cut commit `v<v>`.** (Historical `docex-v*` tags predate the
   unified scheme and remain for archaeology; new cuts use the bare `v<v>` form.)
7. **Build the image:** `docker build -t docex:<v> ./docex` from the repo root —
   always, even on a no-op `docex` rebuild (see *Lockstep* above).
8. **Refresh consumers** as needed: `bash docex_install.sh <project>` repins a
   project; the `project-upgrade` skill drives a full project move across an
   upgrade chain.

### The first cut bootstraps the scheme

The release that first introduces this document is special: it has no prior
`VERSION` file, no prior `v<v>` tag, and authors `RELEASING.md`,
`upgrades/README.md`, and the two upgrade/update skills as part of its own
payload. It is performed by following this procedure against itself — once it
lands, every subsequent release is ordinary.

## Editing Frozen History: Targets vs. Claims

Released `CHANGELOG.md` sections and shipped `upgrades/` guides are **frozen
history** — the record of what was true at a past release, never revised. One
narrow, mechanical exception governs both: a link **target** may be repointed when
a later release moves or renames the file it addresses; a **claim** — any prose,
including the visible link text and any version it asserts — may not change. The
target is a pointer into living doctrine, and a dangling one preserves nothing
while making the record unusable; the words are the artifact and stand as written.
Where a target's file is gone with no honest replacement, or repointing would
misrepresent the claim (e.g. the link text names the file that moved), the dead
reference is left as record rather than falsified.

Stated here once so both [`upgrades/README.md`](./upgrades/README.md) and
[`CHANGELOG.md`](./CHANGELOG.md) can cite it.

## How Operators Consume a Release

Two operator-triggered skills close the loop; they are the consumer-side mirror
of this producer-side process:

- **`doctrine-update`** — refreshes an operator's *machine*: pull `main`, run
  `setup.sh` (re-merges settings, regenerates `RESIDENT.md`, reinstalls the
  plugin so the new skill set lands), build the new `docex` image if needed,
  report the version delta.
- **`project-upgrade`** — moves a single *project* from its current
  `docex_version` pin onto the installed doctrine version, by walking the
  applicable chain of [`upgrades/`](./upgrades/) guides.

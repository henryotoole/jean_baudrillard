# Mod 105 — Rollback `cicl_version` precondition

**Advance:** 004 — service process types. Last code mod (106/107 are closeout).

## Goal

Move discovery of the "cannot recompile a CICL v1 `infra.yml` with a v2 compiler"
failure from the middle of a rollback to its pre-flight band, so an operator
mid-outage learns it before anything is touched and is told what to do instead.

## The problem, precisely

[`cicd.md § Rollback`](../../../../doctrine/infrastructure/cicd.md#rollback) step
3 recompiles the target version's `infra.yml` **with the current docex**, and
precondition 1.3 permits any target within one minor version. Mod 096 made
`cicl_version: "1"` a hard rejection in `CICLDocument` (rule 21). So once 1.6.0
ships:

```
./bin/docex rollback prod <pre-1.6.0-version>
  → preconditions pass                        (rollback.py:86-132)
  → git worktree add v<target>                (rollback.py:139)
  → load_project_context(worktree)            (rollback.py:148)
  → run_compile(worktree_ctx)                 → ValueError: cicl_version '1' …
```

Today the abort happens at `run_compile`, which is *safe* (the recompile precedes
every apply, and the `finally` block still tears the worktree down) but arrives
after a worktree has been created and after the registry probe has run — i.e.
during the outage, at the point of maximum cost per second.

**This mod adds no rule — it pays a debt.** The rule of record already exists:
`cicl.md § CICL Version` (added in Mod 094) states "a rollback recompiles the
target version's `infra.yml` with the *current* compiler, so rollback across the
v1 → v2 boundary is not possible. It aborts at pre-flight, before anything is
applied, with a fix-forward message." That sentence is a promise the code does
not currently keep: today the abort happens at `run_compile`, which is neither
pre-flight nor a fix-forward message. So the design question here is not "should
rollback refuse" — that was settled in Mod 094 and written into the doctrine —
but only *where* the refusal fires and *what it says*. `cicd.md`'s own
precondition list is Mod 106's to amend; this mod touches no doctrine file.

**This is a precondition, not a capability.** For exactly one release cycle after
1.6.0 ships, prod has no rollback path. That window is accepted and documented
(design record § CICL Version and Rollback; § Rejected Alternatives item 11 —
read-only flat-form parser). The deliverable is that the refusal is *early* and
*actionable*, not that rollback works.

## Design

### 1. Where the check goes

Into the cheap pre-flight band, **after** `validate_one_minor_back` and
**before** `_missing_images`:

| Order | Check | Why here |
| ----- | ----- | -------- |
| 5 | `v<target>` tag exists | must precede — we read a blob out of that tag |
| 6 | `validate_one_minor_back` | pure string compare, free |
| **6.5** | **target's `cicl_version` is compilable** | one local `git show`; no network |
| 7 | core-service images present in registry | network/registry probe, fail-aggregated |

Two placement arguments, both pointing the same way. It must sit before the
worktree (`:139`) — that is the whole point of the mod, and the test asserts the
worktree is never created, not merely that the call returns non-zero. And it
should sit before the registry probe because it is strictly cheaper (a local
object read vs. N `docker manifest inspect` / ECR `describe_images` calls) and
strictly more decisive: a missing image might be rebuilt from the tag, whereas a
v1 boundary crossing cannot be resolved by any action other than fixing forward.
There is no diagnostic value in showing the operator a list of missing images for
a rollback that was impossible on other grounds.

### 2. How the target's `cicl_version` is read

`git show v<target>:infra/infra.yml` → `yaml.safe_load` → read the top-level
`cicl_version` key. Nothing more.

Explicitly **not** `load_project_context` / `CICLDocument`: a pre-1.6.0
`infra.yml` fails full model validation for many reasons at once (no
`processes:`, `domain_default_service` instead of `domain_default_process`,
service-level `resources:` against `extra="forbid"`, …), and pydantic's error
ordering decides which one the operator sees. "Flat form — you are across the v1
boundary" is the one fact that matters, and it is the one fact a single-key read
cannot get wrong. The read must also survive a file that is *not* a valid CICL
document at all, which validation by construction cannot do.

`yaml.safe_load` rather than a regex because YAML is already a dependency at
every layer of docex, and a regex over an arbitrary old document invites a
false positive from a commented-out or nested occurrence of the key.

Failure taxonomy — every branch raises `RollbackPreconditionFailed`, so the
dispatcher's existing rendering applies and no branch can surface as a traceback:

| At the target tag | Verdict |
| ----------------- | ------- |
| `cicl_version: "2"` | proceed |
| `cicl_version: "1"` | abort — the v1→v2 boundary message |
| key absent | abort — same boundary message, phrased as "declares no `cicl_version`" (a document predating the field is by definition pre-v2) |
| any other value | abort — "declares unrecognized `cicl_version` `<x>`; this docex compiles `"2"`" |
| `git show` fails (no `infra/infra.yml` at that tag) | abort — names the tag and the path, says rollback cannot verify the target's CICL generation |
| YAML unparseable, or top level is not a mapping | abort — names the tag, reports the parse failure |

The last three all end with the same fix-forward instruction. A target whose
`infra.yml` cannot even be read is not a target rollback should apply.

### 3. The message

The design record's wording is *"cannot roll back across the CICL v1→v2 boundary
— fix forward"*. That is the headline; the body has to be usable by someone with
a broken prod. Shape (exact text lands in `implementation.md`):

```
rollback aborted — cannot roll back across the CICL v1→v2 boundary.

Target v1.5.2's infra/infra.yml declares cicl_version "1". This docex
compiles only cicl_version "2", and rollback recompiles the target's
infra.yml with the *current* docex (cicd.md § Rollback step 3) — so no
rollback to this target can succeed, and nothing has been touched.

Fix forward instead:
  1. On main, fix the defect and bump project.yml past the broken version.
  2. ./bin/docex check  →  merge  →  containerize  →  release <env>

Once a second cicl_version "2" release exists, rollback works normally.
```

Three properties it needs and the bare headline lacks: it says *nothing has been
touched* (an operator who has just seen an abort mid-emergency needs to know the
env is unchanged, not half-converged); it names the concrete next commands rather
than the concept "fix forward"; and it bounds the window, so the operator knows
this is a one-cycle condition and not a permanent loss of rollback.

### 4. Mechanism: `GitClient.show`

`rollback.py` receives an injected `git: GitClient`, and the precondition band is
unit-tested through `FakeGitClient`. The protocol has no read-a-blob method, so:

- **`GitClient` protocol** gains `show(cwd, ref, path) -> str | None` — content
  at `<ref>:<path>`, `None` when it does not resolve.
- **`SubprocessGitClient`** implements it over the existing `_capture` helper.
- **`FakeGitClient`** implements it against `file_at_ref`, a field that already
  exists on the fake (`tests/conftest.py:324`) and is currently referenced by
  nothing — it was scaffolded for exactly this and never wired.

The alternative was `check.py:295`'s `_git_show`, which reaches around the
injected client, instantiates `SubprocessGitClient` inline, and pokes its private
`_capture` (with a `noqa: SLF001`). Copying that into `rollback.py` would make
the new precondition untestable through the fake — the unit tests would need a
real git repo with a real tag to exercise a *pre-flight* check, which is the one
band that should be cheapest to test. Since the protocol method has to exist
anyway, `_git_show` should then delegate to it: same behavior, one fewer private
access, one mechanism for "read a file out of a ref" instead of two. That is the
whole of the `check.py` change.

`FakeGitClient.show` returns a minimal `cicl_version: "2"` document when
`file_at_ref` has no entry for the key. This keeps existing rollback tests
asserting their own subjects (image probes, worktree cleanup, ansible flags)
rather than each acquiring a boilerplate git-content script, and it is consistent
with how the fake already models "an established repo" by default (see its
`refs` default). Boundary tests populate `file_at_ref` explicitly; the
unreadable-file test maps the key to `None`.

### 5. One source of truth for `"2"`

`model.py:298-309` hardcodes `"2"` in the rule-21 validator. The rollback
precondition needs the same fact. Two literals for one fact is precisely the
drift `docex_process.md § Additional Artifacts` warns about, so: a module-level
`CURRENT_CICL_VERSION = "2"` in `cicl/model.py`, consumed by the validator and by
`rollback.py`. No behavior change; the constant makes the next bump a one-line
edit with a compile-time consumer list.

## Scope

**Touched**

| File | Change |
| ---- | ------ |
| `src/docex/pipeline/rollback.py` | the precondition + its helper; docstring's step list |
| `src/docex/git/client.py` | `show` on the protocol |
| `src/docex/git/subprocess_client.py` | `show` implementation |
| `src/docex/cicl/model.py` | `CURRENT_CICL_VERSION` constant; validator reads it |
| `src/docex/pipeline/check.py` | `_git_show` delegates to `GitClient.show` |
| `tests/conftest.py` | `FakeGitClient.show` |
| `tests/unit/test_pipeline_rollback.py` | new tests (below) |
| `docex/plans/core/release_flow.md` | precondition table row, failure-mode row, where-to-look row |

**Not touched:** any doctrine file (Mod 106 owns `cicd.md`'s precondition prose;
`cicl.md § CICL Version` already carries the rule) · any version artifact (Mod
107) · `describe`, emitters, transfer tables · the release path (`run_release`
never recompiles an old tag, so it has no exposure).

## Tests

Added to `tests/unit/test_pipeline_rollback.py`:

1. **v1 target aborts** — `file_at_ref[("v0.0.5", "infra/infra.yml")]` set to a
   flat `cicl_version: "1"` document; asserts `RollbackPreconditionFailed`, the
   "CICL v1→v2 boundary" phrase, and the fix-forward instruction.
2. **v1 target aborts before the worktree exists** — the C.O.'s explicit
   requirement, and the actual point of the mod: asserts `"worktree_add"` is
   absent from `fake_git.calls` and that the worktree path does not exist on
   disk. A non-zero return is not sufficient evidence.
3. **v1 target aborts before the registry probe** — asserts `fake_docker` /
   `fake_aws` recorded no image probe, pinning the ordering decision in § 1 so a
   later reshuffle of the band cannot silently undo it.
4. **v2 target proceeds** — the existing green-path tests already cover this via
   the fake's default; one explicit test sets `cicl_version: "2"` and asserts the
   rollback reaches the release call.
5. **missing `infra.yml` at the target tag** — `file_at_ref[key] = None`;
   asserts `RollbackPreconditionFailed`, that the message names the tag and
   `infra/infra.yml`, and that it is not a traceback.
6. **unparseable YAML at the target tag** — asserts a comprehensible message
   naming the tag, no `yaml.YAMLError` escaping.
7. **absent `cicl_version` key** — a document with no such key gets the boundary
   message.
8. **unrecognized `cicl_version`** (`"3"`) — distinct message, distinguishable
   from the v1 boundary case, mirroring the rule-21 validator's own split.

Green bar: **974 unit / 1038 full** or higher. Both reported.

## Carry-forwards addressed

- **Mod 104's reachable rule-24-illegal core→core `depends_on`.** This mod does
  touch the recompile path, but only by *guarding entry to it*. Nothing here
  changes what `compile_env` validates, and a v1 target never reaches the
  compiler at all after this mod, so the reachability neither widens nor
  narrows. No interaction; no action requested.
- **The one-cycle no-rollback window.** Accepted, documented, unchanged by this
  mod. Recorded in `release_flow.md`'s failure-mode table so the next operator
  to hit it finds it in the *how* doc, not only the design record.

## Design questions

**Resolved — design approved by the advance C.O., including both scope
extensions below.** Recorded rather than deleted, since they are the two places
this mod exceeds the implementation plan's stated touch list.

Two scope notes, both outside the plan's stated
"**Touches:** `pipeline/rollback.py`":

1. **`GitClient.show` on the protocol** (§ 4) rather than copying `check.py`'s
   private-access `_git_show` into `rollback.py`. Buys unit-testability of the
   new precondition through the existing fake and collapses two read-a-blob
   mechanisms into one. Widens a protocol by one structurally-typed read method;
   existing fakes are unaffected at runtime.
2. **`CURRENT_CICL_VERSION` in `cicl/model.py`** (§ 5) rather than a second
   `"2"` literal in `rollback.py`. One line, no behavior change.

Both approved. On (1) the decisive argument is testability, not tidiness: a
precondition that needs a real git repo with a real tag to exercise is a
precondition that rots, and this is the cheapest check in the band. The
`_git_show` delegation is what makes it a net simplification rather than an
addition — one read-a-blob mechanism, and the `noqa: SLF001` goes away.

One observation, no action requested (and not mine to fix): `shape.md:101`'s
example still reads `cicl_version: "1"`. `shape.md` is on Mod 106's sweep list,
so it is already owned — flagging only so it is not missed, since it is the one
place the doctrine still shows the rejected value as if it were current.

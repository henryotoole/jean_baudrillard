# Mod 136 — the shim preserves the git-credential repo path

**Advance:** 007 (`nco_and_lpc_lessons`). In practice a single mod cycle, not a full advance.
**Type:** bug fix (PATCH). Ships in the **2.0.1** cut.
**Source:** [`../../advances/007_nco_and_lpc_lessons/TODO/git_creds_issue.md`](../../advances/007_nco_and_lpc_lessons/TODO/git_creds_issue.md) — root cause found and verified end-to-end on a real dev box.

## Problem

On any environment that opts into per-call brokered git credentials
(`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`, set only by the Periscope runner image),
`docex merge` dies at its first network op:

```
fatal: could not read Username for 'https://github.com': No such device or address
error: 'git fetch origin' exited 128.
```

Plain host `git` against the same remote works, which is what makes it look mysterious.

### Root cause

The shim injects `credential.useHttpPath=false` into the container (`bin/docex:224`).
With `useHttpPath=false`, git sends its credential helper only `protocol=https` +
`host=github.com` — **no `path=`**. The shim's `forward.py` relays that pathless
request to the host's real helper, which on a dev box is a **path-scoped broker**
whose whole job is to confirm *which repo* is being requested. With no path it sees
the repo as literally `github.com` and fails closed. Git gets nothing back.

The line is **residue of a retired design**. Mod 061 baked a static, pathless `store`
file into the container; a `store` entry is keyed pathlessly, so forcing
`useHttpPath=false` made the container's lookups match that docex-written store —
correct then. Mod 068 replaced the store with per-call forwarding to the host's real
helper but **carried the line across verbatim** ("same reasons as mod 061"). The
premise was gone: the request now reaches a helper that may be path-scoped, and
stripping the path destroys information that helper needs. The bug has survived
1.4.3 → 1.4.4 → 2.0.0.

There is a secondary tension worth naming: mod 068's stated goal was *"docex stays
agnostic to the host's helper,"* yet forcing `useHttpPath` is docex imposing policy
on a helper it claims to be agnostic about. This mod resolves that in the direction
of **supporting** path-scoped helpers rather than silently defeating them.

## The fix

**One value flip is the whole functional fix**, plus a belt-and-suspenders second
gate and the docs/tests that stop it from silently recurring.

The credential path has **two gates** where the repo path can be stripped:

| Gate | Where | Governed by |
| ---- | ----- | ----------- |
| 1 | container git → `forward.py` | the shim's injected `credential.useHttpPath` (`bin/docex:224`) |
| 2 | `responder.py` → `git … credential fill` → real helper | the **host's** git config, unless overridden |

- **Gate 1 (required, the fix):** `bin/docex:224` `GIT_CONFIG_VALUE_2=false` → **`true`**.
  Git's built-in default for `credential.useHttpPath` is `false`, so *omitting* the
  line behaves exactly as today — an explicit `true` is required.
- **Gate 2 (hardening, approved):** inside the `responder.py` heredoc (`bin/docex:177`),
  invoke the host's credential fill as `git -C <root> -c credential.useHttpPath=true
  credential fill`. This makes both gates agree **by construction** instead of relying
  on the host's git config (the dev box already sets gate 2 in `/etc/gitconfig`, but the
  shim mounts only `~/.gitconfig`, so nothing guarantees it). Trade-off accepted: this
  overrides a host that deliberately wants pathless matching — no such host is known to
  exist, and the broker fails *closed*, so the failure mode has only ever been
  availability, never over-granting.

The comment at `bin/docex:219` currently justifies the line with mod 061's model,
which no longer exists; it is rewritten to explain path preservation for path-scoped
host helpers.

### Files changed

**Code — the shim, in three byte-identical copies (must stay identical):**

- `docex/bin/docex` — the canonical shim (lines 224, 219, and 177).
- `docex/test_projects/fixed/bin/docex` — fixture, same three edits.
- `docex/test_projects/elastic/bin/docex` — fixture, same three edits.

`docex_install.sh` copies the canonical shim into each project's `bin/docex`, so a
project picks up the fix by re-running that script (the shim is version-independent;
this is the distribution path).

**Docs:**

- `docex/plans/core/masterplan.md` § The Shim (line 86) — currently documents *"forcing
  `useHttpPath=false`"* as the design of record. Reword to describe forcing **`true`**
  and preserving the repo path for path-scoped host helpers.
- **`doctrine/infrastructure/credentials.md` § Git Host Credentials (DOCTRINE — needs
  operator sign-off).** The current text says docex *"stays agnostic to which helper is
  configured."* That was never quite true and is now the wrong claim to make: this mod's
  whole point is that **path-scoped helpers are supported** — docex preserves the repo
  path so a per-repo broker can authorize the request. Proposed edit adds one sentence
  affirming path-scoped helper support; the "brokers through git's own machinery" framing
  stays. Exact wording is in `implementation.md` for approval.

**Not touched (deliberately):** `docex/plans/modifications/061_*/` and `068_*/` still
contain the old value. Modification docs are historical artifacts (like upgrade guides)
and are not retro-edited.

## Also in scope: fault #4 — `check` must not green a fetch failure

Folded in at the operator's request (it is the more valuable of the two separate faults
the TODO recorded). `check` and `merge` diverge on an *identical* `git fetch origin`:

- `merge` (`merge.py:69-74`) guards the fetch on `remote_exists("origin")` and treats a
  fetch **failure** as fatal (`return rc`).
- `check` (`check.py:718-725`) fetches *unconditionally*, downgrades any failure to a
  `warning: … continuing with potentially stale origin/main`, and then — because the
  failed fetch means `origin/main` was never populated locally — its
  `empty_origin = not ref_exists("origin/main")` probe misfires **first-release mode**,
  skipping the trunk-comparing gates and printing advice ("`docex merge` will seed
  origin/main") for a `merge` that will die at the very same fetch. Result: `check`
  reports **9/9 gates green** on a box where the pipeline cannot proceed.

This is the failure that let the git-creds bug land mid-pipeline instead of at the gate.

**Fix** — make `check`'s fetch block mirror `merge` (`check.py`, step 2 only; the
`empty_origin`/first-release logic below it is unchanged):

- If there is **no `origin` remote** (the test projects), skip the fetch and note it —
  no error. This *preserves* today's test-project behavior (they reach first-release
  mode via `origin/main` being absent), and removes the spurious fetch-failure warning
  they currently emit.
- If `origin` **exists and the fetch fails**, print an error and `return rc` — exactly
  as `merge` does. `check` exists to predict whether `merge` will succeed, so it must
  fail where `merge` fails.

This is a `src/docex/pipeline/check.py` change, which takes the mod **out of "shim-only"**
(see gates below). Still a PATCH — a bug fix that changes no contract, CICL, or CLI
surface. **Out of scope:** the deeper `check`-vs-`merge` divergence on which trunk ref the
*no-origin* case compares against (merge → local `main`; check → first-release skip). That
is pre-existing, orthogonal to the false-green, and would change test-project gate coverage;
left alone. Also out of scope: TODO fault (b), intermittent `remote: Repository not found`
on host pushes that already carry the path.

**Test:**

- `docex/tests/unit/test_shim_exit_code.py` (or a sibling) gains a **regression test**.
  Today nothing tests credential *content* — which is exactly why the bug survived three
  versions. The required test captures the `docker run` argv (a fake `docker` on PATH that
  records `"$@"`) and asserts that, in the passthrough branch, the shim injects
  `GIT_CONFIG_VALUE_2=true` (never `false`). This pins the line that broke.
  A second, cheap behavioral test is recommended for gate 2: that
  `git -C <proj> -c credential.useHttpPath=true credential fill` preserves `path=` through
  git's request normalization (recording-helper stand-in, config-isolated, no container,
  no network). The full container-level repro (TODO § "Reproducing it locally") stays as
  documented manual verification — it needs the real image and is too heavy/flaky for CI.

## The 2.0.1 cut (in scope)

Per `RELEASING.md`, a PATCH:

1. `VERSION`, `docex/pyproject.toml`, `docex/src/docex/__init__.py`,
   `.claude-plugin/plugin.json` → `2.0.1`.
2. `CHANGELOG.md` — new `## [2.0.1] - 2026-08-20` section describing the fix.
3. `upgrades/upgrade_2.0.1.md` — a small guide (`severity: patch`,
   `kind: incremental`, `scope: [machine, project]`). This release **has** an upgrade
   action (re-run `docex_install.sh` to redistribute the fixed shim), so it is not a
   zero-action PATCH and warrants a guide, matching the `upgrade_1.6.1.md` precedent.
4. Commit the version bump + changelog; tag `v2.0.1`; `docker build -t docex:2.0.1 ./docex`.

**Gates.** Folding in fault #4 adds a `src/docex/pipeline/check.py` change, so this is
**no longer shim-only**: per `RELEASING.md`, the full `docex`-behavior gate set applies —
the six-artifact alignment check (scoped to the artifacts touched: shim ↔ `check.py` ↔
masterplan ↔ credentials.md ↔ tests; `tables`/`doctrine_excerpts` untouched), then
`cd docex && python -m pytest tests`, then `python -m pytest tests -m integration` **as a
separate invocation** (it exercises `test_check_real.py` / `test_merge_real.py`, which the
check change touches). Never bare `pytest`; never both `-m` flags in one run; always run
from `docex/`. It remains a **PATCH**, so the two-foundation smoke walk is still skipped.

## Blast radius

Small and well-characterized. The changed lines live entirely inside the
`if [[ -n "${DOCEX_GIT_CREDENTIAL_PASSTHROUGH:-}" ]]` block; an environment that does not
set that flag never executes them, and the static key/agent path is untouched. Exactly one
thing sets the flag (the Periscope runner image), so functionally this is a
Periscope-only behavior change — verified unset on operator dev machines and box hosts.

## Design questions

1. **Doctrine edit approval.** `credentials.md` is a doctrine file; `docex_process.md`
   requires operator sign-off before editing one. The proposed change is a one-sentence
   correction (path-scoped helpers are supported). **Approve before implementation.** Exact
   wording will be in `implementation.md`.
2. **Gate-2 hardening** — approved (included).
3. **Cut scope** — approved (mod + patch cut 2.0.1).
4. **Fault #4** (`check` greens a fetch failure) — approved and now **in scope** (see the
   fold-in section above). TODO fault (b) — intermittent `remote: Repository not found` on
   host pushes that already carry the path — remains booked and out of scope.

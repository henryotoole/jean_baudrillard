# Mod 136 — implementation steps

Two bug fixes shipping in the **2.0.1** PATCH cut:

- **A.** The docex shim preserves the git-credential repo path (the git-creds fix).
- **B.** `docex check` fails on a fetch failure instead of reporting green (fault #4).

Read `overview.md` in this folder first. All line numbers below are as of the pre-mod
tree; re-anchor by content, not by number, if they have shifted.

**Do not** edit `docex/plans/modifications/061_*/` or `068_*/` — historical mod docs.

---

## A. Shim: force `useHttpPath=true` at both gates

The shim exists in **three byte-identical copies**. Edit the canonical one, then copy it
over the two fixtures so they stay byte-identical (verified in step A.4).

### A.1 — `docex/bin/docex`, comment at ~line 219

Replace:

```bash
      # git appends the operation (get/store/erase) as the final arg, so
      # forward.py sees argv = [forward.py, <sock>, <op>]. Reset any inherited
      # helper and force useHttpPath=false (same reasons as mod 061).
```

with:

```bash
      # git appends the operation (get/store/erase) as the final arg, so
      # forward.py sees argv = [forward.py, <sock>, <op>]. Reset any inherited
      # helper, and force useHttpPath=true so the repo PATH survives into the
      # credential request: a path-scoped host helper (e.g. a per-repo broker)
      # cannot authorize a request that names no repo. Mod 061 forced =false to
      # match a static pathless `store` file it baked into the container; mod 068
      # deleted that store but carried the line over verbatim, silently breaking
      # path-scoped helpers. Fixed in mod 136.
```

### A.2 — `docex/bin/docex`, ~line 224 (the functional fix)

Replace:

```bash
        -e GIT_CONFIG_KEY_2=credential.useHttpPath -e GIT_CONFIG_VALUE_2=false
```

with:

```bash
        -e GIT_CONFIG_KEY_2=credential.useHttpPath -e GIT_CONFIG_VALUE_2=true
```

### A.3 — `docex/bin/docex`, responder heredoc at ~line 176 (gate-2 hardening)

Replace:

```python
            proc = subprocess.run(
                ["git", "-C", project_root, "credential", "fill"],
                input=request, capture_output=True, env=env,
            )
```

with:

```python
            proc = subprocess.run(
                # -c useHttpPath=true so the repo PATH survives git's normalization
                # of the incoming request before the host helper sees it (gate 2).
                # Makes both gates agree by construction instead of depending on the
                # host's git config (the shim mounts only ~/.gitconfig, not the
                # box's --system config where this often lives). Mod 136.
                ["git", "-C", project_root, "-c", "credential.useHttpPath=true",
                 "credential", "fill"],
                input=request, capture_output=True, env=env,
            )
```

Keep the surrounding lines (`env = dict(...)`, `conn.sendall(proc.stdout)`, the
`except`) exactly as they are.

### A.4 — propagate to the two fixtures, then verify byte-identity

```bash
cd ~/.claude/jean_baudrillard
cp docex/bin/docex docex/test_projects/fixed/bin/docex
cp docex/bin/docex docex/test_projects/elastic/bin/docex
chmod +x docex/test_projects/fixed/bin/docex docex/test_projects/elastic/bin/docex
md5sum docex/bin/docex docex/test_projects/{fixed,elastic}/bin/docex   # all three must match
```

---

## B. `check.py`: mirror `merge`'s fetch handling

### B.1 — `docex/src/docex/pipeline/check.py`, step 2 (~lines 718-725)

Replace:

```python
    # 2. Fetch ----------------------------------------------------------
    rc = git.fetch(project_root, remote="origin")
    if rc != 0:
        print(
            f"warning: 'git fetch origin' exited {rc}; "
            "continuing with potentially stale origin/main.",
            file=sys.stderr,
        )
```

with:

```python
    # 2. Fetch (only when an origin remote exists) ----------------------
    # A fetch *failure* is fatal here, exactly as it is in `merge` (which runs
    # `check` defensively first). `check` exists to predict whether `merge` will
    # succeed; if `merge` would die at `git fetch origin` — a path-scoped
    # credential helper, or a genuine network/auth failure — `check` must not
    # report green. Downgrading it to a warning let a failed fetch masquerade as
    # an empty origin/main and misfire first-release mode (mod 136). A repo with
    # no `origin` (the test projects) skips the fetch and does NOT error.
    if git.remote_exists(project_root, "origin"):
        rc = git.fetch(project_root, remote="origin")
        if rc != 0:
            print(
                f"error: 'git fetch origin' exited {rc}; cannot verify against "
                "the trunk. `docex merge` would fail at the same fetch — resolve "
                "git credentials/network and retry.",
                file=sys.stderr,
            )
            return rc
    else:
        print(
            "check: no 'origin' remote — comparing against local trunk only.",
            file=sys.stderr,
        )
```

Leave everything from the worktree-creation block (step 3) and the
`empty_origin = not git.ref_exists(...)` probe onward **unchanged**.

---

## C. Tests

### C.1 — shim credential content (new file `docex/tests/unit/test_shim_git_credentials.py`)

Nothing currently tests the shim's credential *content* — the reason A survived three
versions. Add a file with the same `skipif(bash, git, python3)` guard as
`test_shim_exit_code.py`. Three tests:

1. **`test_shim_forces_usehttppath_true_in_passthrough`** — the gate-1 regression. Build a
   minimal project (`project.yml` + `git init` + an `https://` origin) and a fake `docker`
   on `PATH` that records its argv to a file and exits 0:

   ```python
   docker.write_text('#!/usr/bin/env bash\nprintf "%%s\\n" "$@" > %r\nexit 0\n' % str(record))
   ```

   Run the real shim with `DOCEX_GIT_CREDENTIAL_PASSTHROUGH=1` and `--version`; read the
   recorded argv and assert:
   - `"GIT_CONFIG_VALUE_2=true" in argv`
   - `"GIT_CONFIG_VALUE_2=false" not in argv`
   - `"GIT_CONFIG_KEY_2=credential.useHttpPath" in argv`

   (Model the project/fake-docker setup on `test_shim_exit_code.py::_project`; the
   passthrough branch runs docker as a child, not `exec`, so the recording survives.)

2. **`test_git_credential_fill_preserves_path_with_usehttppath_true`** — gate-2 behavior.
   Prove the responder's `-c credential.useHttpPath=true` keeps the path through git's
   request normalization, with **no container**. Isolate hard from the real machine's git
   config or the machine's own helper will answer and may print a real token:

   ```python
   env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null",
              GIT_CONFIG_SYSTEM="/dev/null", GIT_TERMINAL_PROMPT="0")
   ```

   `git init` a temp repo; set `credential.helper` to a shell stand-in that dumps its stdin
   (the request git hands it) to a file; run
   `git -C <proj> -c credential.useHttpPath=true credential fill` feeding
   `protocol=https\nhost=github.com\npath=owner/repo.git\n\n` on stdin (stdout/stderr →
   DEVNULL, returncode unchecked — we only assert the helper was called with the path).
   Assert the recorded request contains `path=owner/repo.git`.

3. **`test_git_credential_fill_strips_path_by_default`** — the companion control: same as
   (2) but **without** the `-c` flag; assert the recorded request contains no `path=`.
   Together (2)+(3) show the flag is exactly what preserves the path.

### C.2 — `check` fetch-failure is fatal (add to `docex/tests/unit/test_pipeline_check.py`)

Use the existing `worktree_setup` fixture + `FakeGitClient` (`has_origin`, `refs`,
`exit_codes` are already supported — see `tests/conftest.py`).

1. **`test_check_fetch_failure_is_fatal`** — `worktree_setup` (origin present by default);
   set `fake_git.exit_codes[("fetch", "origin")] = 128`. `run_check(...)` must return
   `128`. Assert the output contains no `"skipped (empty origin/main)"` and no
   `"first-release"` banner, and that `worktree_add` was never called (the fetch aborts at
   step 2, before step 3): `assert not [c for c in fake_git.calls if c[0] == "worktree_add"]`.

2. **`test_check_no_origin_skips_fetch`** — `worktree_setup` + `stub_test_and_compile`; set
   `fake_git.has_origin = False` and `fake_git.refs = {"main", "HEAD"}` (no `origin/main`).
   `run_check(...)` must return `0`, `fetch` must **not** appear in `fake_git.calls`, and the
   output must contain `"no 'origin' remote"`. (This reaches first-release mode via absent
   `origin/main`, matching today's test-project behavior — now without the spurious
   fetch-failure warning.)

Confirm the two existing fetch-path tests still pass unchanged:
`test_check_happy_path_aggregates_all_passing` (origin present, fetch succeeds) and
`test_check_empty_origin_skips_trunk_gates` (origin present, `refs=set()`, fetch succeeds,
first-release mode).

---

## D. Docs

### D.1 — `docex/plans/core/masterplan.md` § The Shim (~line 86)

In the long "Host-resolved git credentials (opt-in)" paragraph, the mechanism sentence
ends "...and points in-container git at `forward.py` (resetting any inherited helper and
**forcing `useHttpPath=false`**)." Change that parenthetical to describe the true design:

> ...and points in-container git at `forward.py` (resetting any inherited helper and
> forcing `useHttpPath=true`, so the repository **path** survives into the credential
> request and a path-scoped host helper — one that authorizes per repository — can serve
> it; the host-side `git credential fill` forces the same, so both gates agree by
> construction).

Do not otherwise rewrite the paragraph.

### D.2 — `doctrine/infrastructure/credentials.md` § Git Host Credentials (line 38) — DOCTRINE (operator-approved)

Replace this clause in the second paragraph:

> ...`docex` brokers git credentials **on the host** — through git's own credential
> machinery (`git credential fill`), so it stays agnostic to which helper is configured —
> and makes that resolution available to the in-container git **per network operation**,
> so each fetch/push obtains a *fresh* short-lived credential rather than a single one
> captured up front.

with:

> ...`docex` brokers git credentials **on the host** — through git's own credential
> machinery (`git credential fill`), driving whatever helper the host has configured — and
> makes that resolution available to the in-container git **per network operation**, so
> each fetch/push obtains a *fresh* short-lived credential rather than a single one
> captured up front. The in-container request preserves the repository path, so a
> **path-scoped** helper — one that authorizes per repository rather than per host — is
> supported.

Nothing else in the section changes. (The old "stays agnostic to which helper is
configured" wording is the claim mod 136 corrects: docex is agnostic to *which* helper,
but it was silently defeating *path-scoped* ones.)

### D.3 — verify no other doc asserts the old behavior

```bash
cd ~/.claude/jean_baudrillard
grep -rn "useHttpPath\|stays agnostic\|potentially stale origin" doctrine/ docex/plans/core/ \
  | grep -v modifications
```

Expect only the two edited spots. Also grep `doctrine/infrastructure/cicd.md` and
`docex/plans/core/{masterplan,release_flow}.md` for any statement that `check` *continues
on* / *warns about* a fetch failure; there is not expected to be one — if there is, update
it to match B. Report either way.

---

## E. Run the gates (from `docex/`)

```bash
cd ~/.claude/jean_baudrillard/docex
python -m pytest tests                 # full default suite (unit + unmarked compile tests)
python -m pytest tests -m integration  # SEPARATE run — exercises check_real / merge_real
```

Never bare `pytest`; never both `-m` flags in one run; always from `docex/` (not the repo
root). Both must be green. The new C tests must be collected and pass.

---

## F. Contracts

No core-service contract changes: this mod changes the shim, `check.py`, docs, and tests
only — no `infra.yml`, surface, or CICL change in any project or test project.

---

## G. The 2.0.1 cut (per RELEASING.md — done after review + green gates)

These are the **cut** steps; the mod-implementor stops after E/F unless told to cut. The
designer/operator runs G once drift review is clean.

1. Set version `2.0.1` in all four tracked artifacts:
   - `VERSION` → `2.0.1`
   - `docex/pyproject.toml` `version = "2.0.1"`
   - `docex/src/docex/__init__.py` `__version__ = "2.0.1"`
   - `.claude-plugin/plugin.json` `"version": "2.0.1"`
2. `CHANGELOG.md` — add a `## [2.0.1] - 2026-08-20` section above `## [2.0.0]`:

   ```markdown
   ## [2.0.1] - 2026-08-20

   ### Fixed
   - **The docex shim preserves the git-credential repo path** (`bin/docex`). The per-call
     credential passthrough (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`) forced
     `credential.useHttpPath=false`, stripping the repository path from the credential
     request; a **path-scoped** host helper (e.g. a per-repo broker) cannot authorize a
     request that names no repo, so `docex merge` died at its first fetch with
     `fatal: could not read Username`. The shim now forces `useHttpPath=true` at both the
     container gate and the host `git credential fill` call, so the path survives and
     path-scoped helpers are supported. Residue of mod 061's retired pathless-`store`
     design, carried across mod 068; it survived 1.4.3 → 2.0.0. (mod 136)
   - **`docex check` fails on a git-fetch failure instead of reporting green.** `check` had
     downgraded a failed `git fetch origin` to a warning and then misfired "first-release
     mode", reporting all gates green on a box where `merge` — which runs `check`
     defensively and treats the same failure as fatal — could not proceed. `check` now
     mirrors `merge`: it skips the fetch when there is no `origin` remote and treats a real
     fetch failure as fatal. (mod 136)
   ```

3. Author `upgrades/upgrade_2.0.1.md` (content below).
4. Commit the version bump + changelog + upgrade guide.
5. Tag the cut commit `v2.0.1`.
6. `docker build -t docex:2.0.1 ./docex` from the repo root.
7. Note for consumers: re-run `bash docex_install.sh <project>` per project to pick up the
   fixed shim (the shim is version-independent; repinning is what recopies it).

### `upgrades/upgrade_2.0.1.md`

```markdown
---
version: "2.0.1"
severity: patch
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 2.0.1

Two bug fixes in the git-facing pipeline; see the
[2.0.1 CHANGELOG entry](../CHANGELOG.md). The load-bearing one lives in the
**version-independent `docex` shim** (`bin/docex`), so — unlike an ordinary release — it
reaches a project only when the shim is recopied, not when the `docex_version` pin moves.
No `infra.yml`, CICL, or contract change.

## Machine sync

Run **`doctrine-update`** (or by hand): `git pull` in `~/.claude/jean_baudrillard`, then
`bash setup.sh`. That builds `docex:2.0.1` (a real rebuild — `docex` source changed:
`pipeline/check.py`) and regenerates `RESIDENT.md` (no resident-stratum change expected).

## Project upgrade

### Recopy the shim (this is the actual fix)

    bash ~/.claude/jean_baudrillard/docex_install.sh .

This repins `project.yml` to `2.0.1` **and** overwrites `bin/docex` with the fixed shim —
the latter carries the credential fix. Re-run it in **every** project whose box brokers git
through a path-scoped credential helper (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH` set — e.g.
Periscope runner boxes). Projects on static SSH keys or agents are unaffected by the shim
fix but should repin for hygiene.

No recompile or redeploy is required — the fixes are in the shim and in `docex check`,
neither of which changes emitted infrastructure.

## Doctrine / behavior notes

- The shim now supports **path-scoped** git credential helpers (per-repo brokers), per
  [`credentials.md § Git Host Credentials`](../doctrine/infrastructure/credentials.md#git-host-credentials).
- `docex check` no longer reports success on a git-fetch failure; it fails the same way
  `docex merge` does, so a green `check` again means the pipeline can proceed.

## Verification

    # The shim carries the fix.
    grep -n "useHttpPath" ./bin/docex   # want GIT_CONFIG_VALUE_2=true and the responder's -c ...=true

    # On a passthrough box, check reaches the network without the pathless-cred failure,
    # and no longer warns-and-continues past a fetch failure.
    ./bin/docex check
```

---

## H. Cleanup

- Update the **Status** line of
  `docex/plans/advances/007_nco_and_lpc_lessons/TODO/git_creds_issue.md` from
  "root cause found... Not yet applied." to note it was applied in **mod 136 / 2.0.1**, and
  that separate fault #1 (`check` vs `merge`) was fixed alongside while fault #2 (host-push
  `Repository not found`) remains open. (Advance-tracking doc, safe to edit — not a
  historical mod doc.)
- After manual review + green gates, the designer updates core planning docs (D.1 already
  covers `masterplan.md`; confirm nothing else in `plans/core/` drifted) and commits
  `mod 136 complete; designed, implemented, and documented.`

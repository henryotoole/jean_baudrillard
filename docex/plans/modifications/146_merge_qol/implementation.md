# Mod 146 — Implementation steps

Merge QoL: a fail-fast `git ls-remote origin` preflight at the top of
`docex merge`, and unbuffered docex output via `PYTHONUNBUFFERED=1` in the image.

This document is self-contained; it can be handed to a fresh context. It covers
**source + tests only**. Do **not** edit any doctrine prose
(`doctrine/**`) and do **not** edit docex core planning docs
(`docex/plans/core/**`) — those are handled separately by the coordinating
corporal at the documentation step. There are no contract changes.

All paths are relative to the docex project root
`/home/ubuntu/.claude/jean_baudrillard/docex`.

---

## Step 1 — Add `ls_remote` to the `GitClient` Protocol

File: `src/docex/git/client.py`

Add a method declaration to the `GitClient` Protocol, placed next to `fetch`
(the other remote-touching read). Match the existing docstring style:

```python
def ls_remote(self, cwd: Path, *, remote: str = "origin") -> int:
    """``git ls-remote <remote>``. Returns exit code.

    A cheap remote reachability + auth probe: it exercises the same
    credential path fetch/push use and returns non-zero (git's 128) when
    the remote is unreachable or authentication fails. ``merge`` runs it
    as a fail-fast preflight before any expensive work. Stdout (the ref
    listing) is discarded; stderr is inherited so the real auth error is
    visible.
    """
    ...
```

## Step 2 — Implement `ls_remote` in the subprocess client

File: `src/docex/git/subprocess_client.py`

Add the concrete method. It must **discard stdout** (the ref listing is noise in
merge's log) but **inherit stderr** (the auth failure message must reach the
operator). Return the exit code; return `127` on `FileNotFoundError`, consistent
with `_run`. Place it near `fetch`:

```python
def ls_remote(self, cwd: Path, *, remote: str = "origin") -> int:
    try:
        res = subprocess.run(  # noqa: S603
            [self._git, "ls-remote", remote],
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,  # ref listing is noise
            # stderr inherited: the auth/reachability error must be visible
            check=False,
        )
    except FileNotFoundError:
        return 127
    return res.returncode
```

Note: the module's chokepoint rule means this is the only place `subprocess` may
be imported for git — it already is. Do not add a new import.

## Step 3 — Add the preflight to `run_merge`

File: `src/docex/pipeline/merge.py`

Two edits to `run_merge`:

**(a) Hoist `has_origin` to the top and add the preflight** as the first action,
*before* the defensive `run_check`. Insert immediately after `project_root =
ctx.project_root` and before the `# 1. Defensive recheck` block:

```python
    # 0. Remote preflight (fail fast) ----------------------------------
    # Prove origin is reachable + authenticated BEFORE any expensive work
    # (defensive check builds an image and runs the full suite). git
    # ls-remote exercises the identical credential path the later
    # fetch/push need, so a broken-auth environment dies here in seconds
    # instead of after a ~34-min check. On a repo with no origin (e.g. the
    # test projects) there is nothing to prove — skip and take the
    # local-only merge path. Resolving origin here also guarantees check's
    # best-effort fetch succeeds, so the defensive recheck validates
    # against fresh main rather than a stale one.
    has_origin = git.remote_exists(project_root, "origin")
    if has_origin:
        rc = git.ls_remote(project_root, remote="origin")
        if rc != 0:
            print(
                f"error: git remote 'origin' is unreachable or "
                f"unauthenticated ('git ls-remote origin' exited {rc}). "
                "Fix network / git credentials (SSH key or token) and retry. "
                "No image was built and no test was run.",
                file=sys.stderr,
            )
            return rc
```

**(b) Remove the now-duplicate `has_origin` resolution lower down.** In the
existing `# 3. Resolve the trunk ref...` block, delete the line
`has_origin = git.remote_exists(project_root, "origin")` (it is now computed at
the top). The `if has_origin:` / `else:` fetch logic that follows it stays exactly
as-is and consumes the hoisted value. Keep the explanatory comment block on that
step.

Do not change anything else in the state machine (rebase / fast-forward / tag /
push / delete-branch all stay identical).

## Step 4 — Add `ls_remote` to `FakeGitClient`

File: `tests/conftest.py`, class `FakeGitClient`

Add a scriptable recorder next to `fetch`, following the exit-code-map pattern:

```python
def ls_remote(self, cwd, *, remote="origin"):
    key = ("ls_remote", remote)
    self.calls.append(("ls_remote", str(cwd), remote))
    return self.exit_codes.get(key, self.default_exit)
```

Default exit 0 means existing merge tests (working auth) are unaffected.

## Step 5 — Set `PYTHONUNBUFFERED=1` in the image

File: `Dockerfile`

Add an `ENV PYTHONUNBUFFERED=1` line. Put it in the environment-config block near
the other `ENV` lines (the `ANSIBLE_*` group is a fine home), with a short WHY
comment:

```dockerfile
# Run docex's own Python output unbuffered so its narration interleaves
# with the live output of the subprocesses it launches (git, docker,
# pytest) in true chronological order — critical when a run's output is
# redirected to a file (block buffering otherwise clumps narration at
# process exit). Covers stdout + stderr for every docex invocation.
ENV PYTHONUNBUFFERED=1
```

## Step 6 — Tests for the merge preflight

File: `tests/unit/test_pipeline_merge.py`

Add these tests (reuse the existing `sample_ctx`, `fake_docker`, `fake_git`
fixtures and the `patched_check` fixture where useful):

1. **Broken auth ⇒ fast exit, no check, no mutation** (the SC1 assertion):

   ```python
   def test_merge_preflight_fails_fast_on_broken_auth(
       sample_ctx, fake_docker, fake_git, monkeypatch
   ):
       # run_check must be a spy we can prove is NEVER called.
       called = []
       monkeypatch.setattr(
           merge_mod, "run_check",
           lambda *a, **kw: (called.append(True), 0)[1],
       )
       fake_git.branch = "feature/x"
       fake_git.exit_codes[("ls_remote", "origin")] = 128

       rc = run_merge(sample_ctx, fake_docker, fake_git)

       assert rc == 128
       assert called == [], "defensive check ran despite failed preflight"
       # No mutating git op — and no fetch — may have run.
       mutating = {c[0] for c in fake_git.calls} & {
           "fetch", "rebase", "fast_forward", "tag", "push", "delete_branch",
       }
       assert mutating == set(), fake_git.calls
       # The preflight itself must have run.
       assert any(c[0] == "ls_remote" for c in fake_git.calls)
   ```

2. **Preflight runs before the defensive check** (ordering / SC1 correctness gap):

   ```python
   def test_merge_preflight_runs_before_check(
       sample_ctx, fake_docker, fake_git, monkeypatch
   ):
       order: list[str] = []
       monkeypatch.setattr(
           merge_mod, "run_check",
           lambda *a, **kw: (order.append("check"), 0)[1],
       )
       # ls_remote records into fake_git.calls; capture its relative order.
       original_ls = fake_git.ls_remote

       def tracking_ls(*a, **kw):
           order.append("ls_remote")
           return original_ls(*a, **kw)

       fake_git.ls_remote = tracking_ls  # type: ignore[method-assign]
       fake_git.branch = "feature/x"

       rc = run_merge(sample_ctx, fake_docker, fake_git)
       assert rc == 0
       assert order.index("ls_remote") < order.index("check")
   ```

3. **No-origin repo skips the preflight** (test-project path unchanged):

   ```python
   def test_merge_no_origin_skips_preflight(
       sample_ctx, fake_docker, fake_git, patched_check
   ):
       fake_git.branch = "feature/x"
       fake_git.has_origin = False
       # A scripted ls_remote failure must be irrelevant when there's no origin.
       fake_git.exit_codes[("ls_remote", "origin")] = 128
       rc = run_merge(sample_ctx, fake_docker, fake_git)
       assert rc == 0
       assert not any(c[0] == "ls_remote" for c in fake_git.calls)
       # Local-only merge still integrates + tags.
       assert any(c[0] == "tag" for c in fake_git.calls)
   ```

4. **Working auth ⇒ preflight passes, merge proceeds** (happy path calls it once):

   ```python
   def test_merge_preflight_passes_then_merges(
       sample_ctx, fake_docker, fake_git, patched_check
   ):
       fake_git.branch = "feature/x"
       rc = run_merge(sample_ctx, fake_docker, fake_git)
       assert rc == 0
       ls_calls = [c for c in fake_git.calls if c[0] == "ls_remote"]
       assert len(ls_calls) == 1
       assert ls_calls[0] == ("ls_remote", str(sample_ctx.project_root), "origin")
   ```

The existing happy-path / defensive-check / rebase-failure tests must remain green
unchanged (default `ls_remote` exit 0 keeps them passing).

## Step 7 — Guard test for the unbuffered image setting

File: `tests/unit/test_dockerfile_unbuffered.py` (new)

A cheap alignment guard, matching docex's existing guard-test pattern, asserting
the image declares unbuffered Python:

```python
"""Guard: the docex image must run Python unbuffered.

Mod 146 (F1). PYTHONUNBUFFERED=1 is what makes docex's narration
interleave with subprocess output in true chronological order when a run
is redirected to a file. If this line is ever dropped from the Dockerfile,
logs silently scramble again — so assert its presence loudly here.
"""

from __future__ import annotations

from pathlib import Path


def test_dockerfile_sets_pythonunbuffered():
    # tests/unit/ -> tests/ -> project root
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    text = dockerfile.read_text()
    assert "ENV PYTHONUNBUFFERED=1" in text, (
        "Dockerfile must set ENV PYTHONUNBUFFERED=1 so docex output is "
        "unbuffered (mod 146). Without it, redirected logs scramble."
    )
```

Confirm `parents[2]` resolves to the project root from `tests/unit/` (it does:
`tests/unit/x.py` → `parents[0]=unit`, `[1]=tests`, `[2]=root`). Adjust only if the
file is placed elsewhere.

---

## Step 8 — Run the suite

From the project root, run the full default suite and confirm green:

```sh
python -m pytest tests
```

(Use `python -m pytest`, never bare `pytest` — see `docex_process.md` §Running the
automated tests.) The integration suite need not be run for this mod — no behavior
crosses a real docker/AWS/git boundary; the preflight is exercised through the
fake git client, and the image setting through the guard test. If you do run
`-m integration`, run it **alone**.

## Acceptance

- `ls_remote` exists on the Protocol, the subprocess client (stdout discarded,
  stderr inherited, 127 on missing git), and `FakeGitClient`.
- `run_merge` runs the preflight first, returns the failure code before `run_check`
  on broken auth, and skips it entirely with no origin.
- `Dockerfile` declares `ENV PYTHONUNBUFFERED=1`.
- All new tests pass and the pre-existing merge tests stay green under
  `python -m pytest tests`.

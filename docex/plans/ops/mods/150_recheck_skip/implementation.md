# Mod 150 — Implementation steps

Redundant-recheck elimination (F2 / SC4). `check` writes a provenance record on
success; `merge` trusts it forward and skips its defensive recheck when nothing has
moved. Design + rationale: [`overview.md`](./overview.md). This document is
self-contained; read `overview.md` only if a *why* is unclear.

Repo root for all paths below: `/home/ubuntu/.claude/jean_baudrillard/docex`.
Work on branch `advance_009_test_overhaul` (already checked out; do **not** branch or
commit — the corporal owns the commits).

Run the suite the doctrine-mandated way when done: `python -m pytest tests` (never
bare `pytest`; the default suite is `tests`, not `tests/unit`).

---

## Step 1 — `GitClient`: add `rev_parse` and `ls_remote_sha`

### 1a. Protocol — `src/docex/git/client.py`

Add two method stubs to the `GitClient` Protocol. Place `rev_parse` near `merge_base`
(both are read/rev helpers) and `ls_remote_sha` right after `ls_remote`.

```python
    def rev_parse(self, cwd: Path, rev: str) -> str:
        """``git rev-parse <rev>``. Returns the resolved SHA (stripped), or the
        empty string if ``rev`` does not resolve.

        Used to record and compare commit tips (``origin/main``, local ``main``,
        a feature tip) and tree SHAs (``HEAD^{tree}``) for the ``.docex/checks/``
        provenance record.
        """
        ...

    def ls_remote_sha(
        self, cwd: Path, ref: str, *, remote: str = "origin"
    ) -> tuple[int, str]:
        """``git ls-remote <remote> <ref>`` → ``(exit_code, sha)``.

        Folds the reachability/auth preflight together with learning a remote
        ref's tip in one round-trip: a non-zero exit code means the remote is
        unreachable or auth failed (``sha == ""``); an exit code of 0 with the
        ref absent also yields ``sha == ""``. ``merge`` uses this in place of the
        bare ``ls_remote`` preflight so it can learn ``origin/main``'s current tip
        without an extra fetch. Stderr is inherited so the auth error stays visible.
        """
        ...
```

Leave the existing `ls_remote` method on the protocol unchanged (still declared; just
no longer used by `merge`).

### 1b. Implementation — `src/docex/git/subprocess_client.py`

Add `rev_parse` beside `merge_base` (both `_capture`-backed reads):

```python
    def rev_parse(self, cwd: Path, rev: str) -> str:
        res = self._capture(["rev-parse", rev], cwd=cwd)
        return (res or "").strip()
```

Add `ls_remote_sha` right after the existing `ls_remote`. It must capture stdout (to
read the sha) while inheriting stderr (so the auth error is visible), mirroring
`ls_remote`'s subprocess shape:

```python
    def ls_remote_sha(
        self, cwd: Path, ref: str, *, remote: str = "origin"
    ) -> tuple[int, str]:
        try:
            res = subprocess.run(  # noqa: S603
                [self._git, "ls-remote", remote, ref],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                # stderr inherited: the auth/reachability error must be visible
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return 127, ""
        if res.returncode != 0:
            return res.returncode, ""
        # ls-remote prints "<sha>\t<refname>" lines; take the first field of the
        # first line. Empty stdout (ref absent on the remote) ⇒ "".
        line = (res.stdout or "").strip().splitlines()
        sha = line[0].split()[0] if line and line[0].split() else ""
        return 0, sha
```

(`subprocess` is already imported at module top.)

---

## Step 2 — New module: `src/docex/pipeline/check_record.py`

Create the module. It owns the `.docex/checks/` provenance artifact. Model it on
`src/docex/jobs/record.py` (atomic write, degrade-safe reads). Full file:

```python
"""The ``.docex/checks/`` provenance record — what a passing ``check`` blessed.

Written by ``check`` on a fully-green run; read by ``merge`` to decide whether it
may skip its defensive recheck (see [cicd.md § Merge] and [overview.md]). This is
a **performance cache, never a correctness gate**: every read degrades safely to
``None`` (missing dir/file, unreadable, or corrupt JSON), so a missing record
forces ``merge`` to run the full recheck.

Distinct from the SC3 job record under ``.docex/runs/``: ``runs/`` answers "did
this invocation pass"; ``checks/`` answers "what tree a passing check blessed, for
``merge`` to trust forward." One latest-wins file — ``merge`` only ever trusts the
most recent green.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


CHECKS_RELDIR = ".docex/checks"
RECORD_FILENAME = "latest.json"


@dataclass
class CheckRecord:
    """What a successful ``check`` validated. Exactly SC4's five fields.

    ``merged_tree_sha`` is the git tree SHA of the validated (rebased) worktree —
    the authoritative "what was tested", recorded for audit and a possible future
    stronger comparison. It is NOT part of the v1 commit-based skip predicate.
    """

    feature_tip: str
    origin_main: str
    merged_tree_sha: str
    checked_at: str
    docex_version: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "CheckRecord":
        raw = json.loads(text)
        return cls(
            feature_tip=raw["feature_tip"],
            origin_main=raw["origin_main"],
            merged_tree_sha=raw["merged_tree_sha"],
            checked_at=raw["checked_at"],
            docex_version=raw["docex_version"],
        )


def now_iso() -> str:
    """UTC timestamp, ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def checks_dir(project_root: Path) -> Path:
    return project_root / ".docex" / "checks"


def record_path(project_root: Path) -> Path:
    return checks_dir(project_root) / RECORD_FILENAME


def write_check_record(project_root: Path, rec: CheckRecord) -> None:
    """Atomically write the latest-wins record (temp file + ``os.replace``)."""
    d = checks_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{RECORD_FILENAME}.{secrets.token_hex(4)}.tmp"
    tmp.write_text(rec.to_json())
    os.replace(tmp, record_path(project_root))


def read_check_record(project_root: Path) -> CheckRecord | None:
    """Return the recorded provenance, or ``None`` if absent/unreadable/corrupt.

    Degrade-safe by design: any failure ⇒ ``None`` ⇒ ``merge`` runs the full
    recheck (the safe default).
    """
    try:
        text = record_path(project_root).read_text()
    except OSError:
        return None
    try:
        return CheckRecord.from_json(text)
    except (ValueError, KeyError):
        return None
```

---

## Step 3 — `check` writes the record on success

Edit `src/docex/pipeline/check.py`, function `run_check`.

### 3a. Import

Add near the other `docex.pipeline` imports at the top:

```python
from docex.pipeline import check_record
```

### 3b. Compute + write the record on the green path

`run_check`'s success path currently ends (inside the `try`) with:

```python
        # All good.
        print(_aggregate_check_report(report))
        print("check: all gates and tests passed.")
        return 0
```

Immediately **before** `print(_aggregate_check_report(report))` on that green path,
insert the record write. The trunk sha follows the same three-way logic `check`
already uses to decide its mode (`git.remote_exists`, `empty_origin`):

```python
        # Provenance record (SC4): record what this green check validated so
        # `merge` can trust it forward and skip a redundant recheck. Written
        # ONLY here, on the fully-green path. `.docex/` is gitignored, so this
        # write does not dirty the tree (it cannot disturb the worktree_clean
        # gate above or merge's is_clean guard).
        if git.remote_exists(project_root, "origin") and not empty_origin:
            trunk_sha = git.rev_parse(project_root, "origin/main")
        elif not git.remote_exists(project_root, "origin"):
            trunk_sha = git.rev_parse(project_root, "main")
        else:
            trunk_sha = ""  # empty-origin / first-release: no trunk to trust
        check_record.write_check_record(
            project_root,
            check_record.CheckRecord(
                feature_tip=git.head_sha(project_root),
                origin_main=trunk_sha,
                merged_tree_sha=git.rev_parse(worktree, "HEAD^{tree}"),
                checked_at=check_record.now_iso(),
                docex_version=ctx.project.docex_version,
            ),
        )
```

Notes for the implementor:
- `project_root`, `worktree`, `empty_origin`, `git`, `ctx` are all in scope at that
  point in `run_check`.
- `feature_tip` uses `git.head_sha(project_root)` (full sha, `short=False`) — the
  operator-tree feature tip, unchanged by the worktree rebase.
- Do **not** move the write outside the `try` / into the `finally`: it must run only
  on success, and the `finally` also runs on every failure path.

---

## Step 4 — `merge` skip predicate

Edit `src/docex/pipeline/merge.py`, function `run_merge`.

### 4a. Import

```python
from docex.pipeline import check_record
```

### 4b. Upgrade the preflight to learn the trunk tip, and add the predicate

Replace the current **step 0 preflight** and **step 1 defensive recheck** blocks.
Today they read:

```python
    # 0. Remote preflight (fail fast) ----------------------------------
    # ...
    has_origin = git.remote_exists(project_root, "origin")
    if has_origin:
        rc = git.ls_remote(project_root, remote="origin")
        if rc != 0:
            print( ... )
            return rc

    # 1. Defensive recheck ---------------------------------------------
    print("merge: running 'docex check' defensively before rebase...")
    rc = run_check(ctx, docker, git)
    if rc != 0:
        print( ... )
        return rc
```

Change them to:

```python
    # 0. Remote preflight (fail fast) + learn origin/main's tip ---------
    # The ls-remote preflight (mod 146) proves origin is reachable+authed
    # BEFORE any expensive work. We narrow its refspec to refs/heads/main so
    # the SAME round-trip also yields origin/main's current tip for the
    # recheck-skip predicate below — no extra fetch (SC4). A non-zero exit
    # still fails fast exactly as before (auth path is unchanged). On a repo
    # with no origin (e.g. the test projects) the trunk tip is local `main`.
    has_origin = git.remote_exists(project_root, "origin")
    if has_origin:
        rc, origin_main_now = git.ls_remote_sha(
            project_root, "refs/heads/main", remote="origin"
        )
        if rc != 0:
            print(
                f"error: git remote 'origin' is unreachable or "
                f"unauthenticated ('git ls-remote origin' exited {rc}). "
                "Fix network / git credentials (SSH key or token) and retry. "
                "No image was built and no test was run.",
                file=sys.stderr,
            )
            return rc
    else:
        origin_main_now = git.rev_parse(project_root, "main")

    # 1. Defensive recheck — unless a trusted green makes it redundant --
    # SC4 trust-forward: skip the recheck IFF the last successful check's
    # record still describes reality — origin/main and the feature tip at the
    # recorded commits, the tree clean, and the docex version matched. ANY
    # staleness forces the full recheck. The recorded green is a performance
    # cache, never a correctness gate: the safe default is always to run. The
    # empty-string guards forbid a spurious skip on a first-release/empty-origin
    # record (origin_main == "").
    rec = check_record.read_check_record(project_root)
    skip_recheck = (
        rec is not None
        and rec.docex_version == ctx.project.docex_version
        and bool(rec.feature_tip)
        and rec.feature_tip == git.head_sha(project_root)
        and bool(rec.origin_main)
        and rec.origin_main == origin_main_now
        and git.is_clean(project_root)
    )
    if skip_recheck:
        print(
            "merge: trunk and feature unmoved since the last successful check "
            f"(feature {rec.feature_tip[:8]} @ trunk {rec.origin_main[:8]}), "
            "tree clean, docex version matched — skipping the defensive recheck "
            "(trusting the recorded green forward)."
        )
    else:
        print("merge: running 'docex check' defensively before rebase...")
        rc = run_check(ctx, docker, git)
        if rc != 0:
            print(
                "merge: 'docex check' failed; refusing to merge. "
                "Fix the failing gates and retry.",
                file=sys.stderr,
            )
            return rc
```

Everything downstream of this (steps 2–7: feature-branch identity, fetch, rebase,
fast-forward, tag, push, delete) is **unchanged**. In particular the existing
`if has_origin: rc = git.fetch(...)` at step 3 stays — the fetch that precedes the
actual rebase is still needed to update the local `origin/main` ref the rebase uses.

---

## Step 5 — Test doubles: extend `FakeGitClient`

Edit `tests/conftest.py`, class `FakeGitClient`.

### 5a. New scriptable attributes (add beside the other fields, e.g. near `head`)

```python
    # Mod 150: scripted `rev_parse` results, keyed by rev string. A rev absent
    # from the map falls back to `head` (a permissive default so existing tests
    # that don't care get the repo's HEAD sha).
    rev_parse_map: dict[str, str] = field(default_factory=dict)
    # Mod 150: the sha `ls_remote_sha` yields for refs/heads/main (the trunk tip
    # merge's skip predicate compares against).
    remote_main_sha: str = "abc1234"
```

### 5b. New methods (add in the reads section, near `merge_base` / `ls_remote`)

```python
    def rev_parse(self, cwd, rev):
        self.calls.append(("rev_parse", str(cwd), rev))
        return self.rev_parse_map.get(rev, self.head)

    def ls_remote_sha(self, cwd, ref, *, remote="origin"):
        key = ("ls_remote_sha", remote)
        self.calls.append(("ls_remote_sha", str(cwd), ref, remote))
        rc = self.exit_codes.get(key, self.default_exit)
        return (rc, "" if rc != 0 else self.remote_main_sha)
```

Keep the existing `ls_remote` method as-is.

---

## Step 6 — Tests

### 6a. New file: `tests/unit/test_check_record.py`

Cover the artifact in isolation:
- **round-trip:** `write_check_record` then `read_check_record` returns an equal
  `CheckRecord` (all five fields).
- **missing dir / missing file:** `read_check_record(tmp_path)` on a fresh dir →
  `None`.
- **corrupt JSON:** write `"{ not json"` to `record_path(root)` (after creating
  `checks_dir`) → `read_check_record` → `None`.
- **partial JSON:** write `'{"feature_tip": "x"}'` (missing keys) → `None`.
- **atomic overwrite:** write record A, then record B, then read → B; assert no
  leftover `.latest.json.*.tmp` files remain in `checks_dir`.

Use `tmp_path` as `project_root`.

### 6b. `tests/unit/test_pipeline_check.py` — check writes the record

Find the existing green/happy-path `run_check` test (it stubs compile/build/test —
reuse that exact harness/fixtures). Add two tests:
- **writes on success:** after a green `run_check`, `check_record.read_check_record(
  project_root)` is not `None` and its `feature_tip` == the fake git head,
  `origin_main` == the resolved trunk sha the fake returns for `origin/main` (script
  `fake_git.rev_parse_map["origin/main"] = "<trunk>"`, or rely on the default), and
  `docex_version` == the ctx's docex_version.
- **no record on failure:** force one gate to fail (e.g. make `_compose_build` or a
  gate return non-zero via the harness's existing failure hook, or a rebase failure)
  and assert `read_check_record` returns `None` (no file written). Use a fresh
  `project_root` so a prior test's record can't leak in.

If the existing check happy-path harness makes writing a record awkward (e.g. it
doesn't give a real `project_root` on disk), prefer a focused test that calls
`run_check` with the real fakes over a `tmp_path` project, stubbing
`docex.pipeline.check.run_test` and `_compose_build` and `run_compile` to return 0 —
mirror whatever the existing happy-path test already does.

### 6c. `tests/unit/test_pipeline_merge.py` — the seven cases

Add a helper to build a matching record and a `run_check` spy. The default
`fake_git` has `head = "abc1234"`, `remote_main_sha = "abc1234"`, `clean = True`,
`branch = "feature/x"`. A record is "matching" when `feature_tip == fake_git.head`,
`origin_main == fake_git.remote_main_sha`, `docex_version == sample_ctx.project.
docex_version`.

Pattern for each test: monkeypatch `merge_mod.check_record.read_check_record` to
return the crafted record (or `None`), and monkeypatch `merge_mod.run_check` with a
spy that appends to a list and returns 0. Then assert whether the spy was called.

- **skip:** matching record, `fake_git.clean = True` → spy **not** called; `rc == 0`;
  `rebase`/`tag`/`push` still in `fake_git.calls` (merge proceeded).
- **forced — no record:** `read_check_record → None` → spy called; `rc == 0`.
- **forced — trunk moved:** record `origin_main = "OLDTRUNK"` (≠ `remote_main_sha`)
  → spy called.
- **forced — feature moved:** record `feature_tip = "OLDFEAT"` (≠ `head`) → spy
  called.
- **forced — tree dirty:** matching record but `fake_git.clean = False` → spy called.
- **forced — unreadable/corrupt record:** do **not** monkeypatch the reader — instead
  point `sample_ctx.project_root` at a real `tmp_path`, create `checks_dir`, write
  corrupt bytes to `record_path`, and let the real `read_check_record` return `None`
  → spy called. (This exercises the real degrade-safe path end-to-end.)
- **forced — version mismatch:** matching record but `docex_version = "0.0.0-old"`
  (≠ ctx) → spy called.

For every forced case also assert `rc == 0` (the stubbed check passes, merge
completes). For the skip and no-origin interplay: the default `fake_git.has_origin =
True` uses `ls_remote_sha`; you don't need a separate no-origin skip test, but if you
add one, set `fake_git.has_origin = False` and script `rev_parse_map["main"]` to
equal the record's `origin_main`.

Update any existing merge test that asserts `git.ls_remote` was called in the
preflight (search `test_pipeline_merge.py` and `test_jobs_check_merge.py` for
`ls_remote`) to assert `ls_remote_sha` instead. The auth-fail preflight test: script
`fake_git.exit_codes[("ls_remote_sha", "origin")] = 128` and assert merge returns 128
without calling the check spy or any mutating git op.

---

## Step 7 — Verify

From the repo root:

```sh
python -m pytest tests
```

Must be fully green. If iterating on a subset, still finish with the full `tests`
run (the default suite is `tests`, not `tests/unit`; never use bare `pytest`). Then
run `python -m pytest tests -q` and `python -m pytest tests -q -m integration`
**alone** and confirm the collection-partition guard is happy (no
`test_collection_partition` failure), i.e. the new tests are collected in exactly one
bucket (they are unit tests → `tests/unit/`, unmarked).

Do **not** edit core planning docs, the doctrine files, the CHANGELOG, or
`masterplan.md` — those are the corporal's Documentation step, not implementation.

## Summary of files touched

- `src/docex/git/client.py` — +`rev_parse`, +`ls_remote_sha` protocol stubs.
- `src/docex/git/subprocess_client.py` — +`rev_parse`, +`ls_remote_sha` impls.
- `src/docex/pipeline/check_record.py` — **new** module (the `.docex/checks/` artifact).
- `src/docex/pipeline/check.py` — write the record on the green path.
- `src/docex/pipeline/merge.py` — preflight fold + skip predicate.
- `tests/conftest.py` — `FakeGitClient` gains `rev_parse` / `ls_remote_sha` +
  `rev_parse_map` / `remote_main_sha`.
- `tests/unit/test_check_record.py` — **new**.
- `tests/unit/test_pipeline_check.py` — +writes-record / +no-record-on-failure.
- `tests/unit/test_pipeline_merge.py` — +7 recheck-skip/forced cases; preflight
  assertions updated to `ls_remote_sha`.

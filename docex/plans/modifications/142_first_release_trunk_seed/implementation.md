# Mod 142 — Implementation Steps

Establish an empty `main` at inception; remove `merge.py`'s dead seed-trunk
path. Design record: `../../advances/008_housekeeping/references/first_release_merge_bug.md`
and this mod's `overview.md`.

**Scope note for the executor.** Do everything below. Do **NOT** touch
`docex/plans/core/*.md` (core planning docs — the mod owner updates
`test_projects.md` separately) and do **NOT** touch the operator's WIP:
`RELEASING.md` and anything under `docex/plans/advances/floating_todo/`.

**Environment.** `python` is not on PATH. Run pytest as
`docex/.venv/bin/python -m pytest ...` **from the `docex/` directory**.

---

## Step 1 — `doctrine/practices/inception.md`: establish `main` in PART I

The current PART I steps are:
```
4. Clone the new repository ...
5. Change directory into the project folder e.g. `cd ${project_name}`
6. Create a branch called "inception_and_first_draft" and switch to it.
7. Set up some basic structure for the project:
   ...
8. Install `docex` ...
9. Make a commit with the message "Inception Part I: setup complete".
```

**1a.** Insert a NEW step 6 between the current step 5 and the current step 6.
Renumber the current 6→7, 7→8, 8→9, 9→10. The result must read exactly:

```
5. Change directory into the project folder e.g. `cd ${project_name}`
6. Establish `main` as the doctrine trunk. `git init` on a fresh GitHub clone
   already leaves you on the default branch; ensure it is named `main`, make an
   empty initial commit, and push it so `origin/main` exists:
	```
	git commit --allow-empty -m "Initial commit"
	git push -u origin main
	```
	Every Part I–IV commit still lands on the feature branch created next; only
	this empty trunk root is added ahead of it, so the first `docex merge` at
	PART V rebases onto an existing (empty) `origin/main` instead of having to
	invent the trunk.
7. Create a branch called "inception_and_first_draft" and switch to it.
8. Set up some basic structure for the project:
	1. Create or update `.gitignore` file with the [default](#gitignore-defaults) below.
	2. Add the critical `project.yml` file from the [default](#projectyml-default) below.
	3. Add a `README.md` with a brief couple of sentences that describe the project.
	4. Add `CHANGELOG.md` from the [default](#changelogmd-default)
	5. Create the project folder structure as specified in [infra](../infrastructure/infrastructure.md#repository-structure) down to:
		1. `core` folder, no subfolders.
		2. `infra` folder, all direct child subfolders.
			+ `secrets`, `config`, `tte`, and `deploy_creds` should each be given [infra `.gitignore`](#infra-gitignore-files) files.
		3. `plans` folder, all direct child subfolders but no files.
	6. Write `masterplan.md` verbatim into its place at `$pr/plans/core/masterplan.md`.
9. Install `docex` (see [install instructions](../infrastructure/docex.md#project-installation)).
	1. Test that it works with `./bin/docex --version`.
10. Make a commit with the message "Inception Part I: setup complete".
```

Preserve the existing sub-bullet content of the "Set up some basic structure"
and "Install docex" steps verbatim (shown above) — only the top-level numbers
change. Keep tab indentation consistent with the rest of the file.

**1b.** Fix the shifted self-reference at the bottom of `inception.md` (the
`project.yml Default` section, currently ~line 177):
- FROM: ``The `docex_version` field is appended to this file by `docex_install.sh` in PART I step 8 — do not write it by hand.``
- TO:   ``The `docex_version` field is appended to this file by `docex_install.sh` in PART I step 9 — do not write it by hand.``

## Step 2 — `docex/test_projects/PRE_CUT_CHECKLIST.md`: fix shifted step ref

B.1 (currently ~line 195) cites "PART I step 7" for project-root layout. That
step is now step 8. Change exactly:
- FROM: ``Per [`inception.md`](../../doctrine/practices/inception.md) PART I step 7 and``
- TO:   ``Per [`inception.md`](../../doctrine/practices/inception.md) PART I step 8 and``

Leave the rest of the line untouched.

## Step 3 — `docex/src/docex/pipeline/merge.py`: remove the seed-trunk path

Current body (section "4. Decide between rebase-onto-trunk or seed-trunk",
~lines 84–126) has an `if trunk_missing: ... else: <rebase+ff>` shape. Replace
the whole section 4 with a precondition guard + the (unchanged) normal path.

**3a.** Replace this block:
```python
    # 4. Decide between rebase-onto-trunk or seed-trunk ----------------
    trunk_missing = not git.ref_exists(project_root, trunk_ref)
    if trunk_missing:
        # No trunk to rebase onto — either a first release on an empty
        # remote (origin/main absent) or a no-remote repo with no local
        # ``main`` yet. Seed it by fast-forwarding a freshly-created
        # local main to the feature tip; with origin, the push at step 6
        # publishes it. The defensive recheck above already passed in
        # "first-release mode" (gates skipped), so the tree is valid.
        print(
            f"merge: {trunk_ref} does not exist — seeding main from the "
            f"current feature branch ({feature!r}).",
            file=sys.stderr,
        )
        rc = git.fast_forward(project_root, "main", feature)
        if rc != 0:
            print(
                f"error: failed to create 'main' at {feature!r} (exit {rc}). "
                "Manual recovery needed.",
                file=sys.stderr,
            )
            return rc
    else:
        rc = git.rebase(project_root, trunk_ref)
        if rc != 0:
            # Abort so we don't leave the working tree mid-rebase.
            git.rebase_abort(project_root)
            print(
                f"error: 'git rebase {trunk_ref}' exited {rc}. Resolve the "
                "conflict on your feature branch and retry.",
                file=sys.stderr,
            )
            return rc

        # Fast-forward main to the rebased tip -------------------------
        rc = git.fast_forward(project_root, "main", feature)
        if rc != 0:
            print(
                f"error: fast-forward of 'main' to {feature!r} exited {rc}. "
                "Manual recovery needed.",
                file=sys.stderr,
            )
            return rc
```

with:
```python
    # 4. Rebase onto the trunk, then fast-forward it -------------------
    # Inception establishes an empty ``main`` (pushed to origin), so a
    # doctrine project always has a trunk to rebase onto by first release
    # (see inception.md PART I). If it's absent, fail loudly rather than
    # inventing one: a repo with no ``main`` was not set up via inception,
    # which is outside doctrine. This replaces an older seed-trunk path
    # that tried to create ``main`` here and was itself broken (its
    # ``git checkout main`` could not check out a branch that didn't
    # exist).
    if not git.ref_exists(project_root, trunk_ref):
        print(
            f"error: {trunk_ref} not found. A doctrine project is set up via "
            "inception, which establishes an empty 'main'; see inception.md "
            "PART I. Cannot merge without a trunk.",
            file=sys.stderr,
        )
        return 1

    rc = git.rebase(project_root, trunk_ref)
    if rc != 0:
        # Abort so we don't leave the working tree mid-rebase.
        git.rebase_abort(project_root)
        print(
            f"error: 'git rebase {trunk_ref}' exited {rc}. Resolve the "
            "conflict on your feature branch and retry.",
            file=sys.stderr,
        )
        return rc

    # Fast-forward main to the rebased tip -----------------------------
    rc = git.fast_forward(project_root, "main", feature)
    if rc != 0:
        print(
            f"error: fast-forward of 'main' to {feature!r} exited {rc}. "
            "Manual recovery needed.",
            file=sys.stderr,
        )
        return rc
```

Note: `fast_forward` is STILL used by the normal path above — do NOT remove it
from `git/client.py` or `git/subprocess_client.py`.

**3b.** Simplify the remote-delete guard. `trunk_missing` no longer exists, and
past the precondition guard the trunk always exists, so the condition reduces to
`has_origin`. Change:
```python
    # No remote feature branch to delete when there's no origin at all,
    # or on an empty-origin seed (nothing was ever pushed). Skip the
    # remote delete in those cases to avoid a warning operators can't
    # act on.
    if has_origin and not trunk_missing:
```
to:
```python
    # No remote feature branch to delete when there's no origin at all;
    # skip the remote delete then to avoid a warning operators can't act
    # on.
    if has_origin:
```

Leave the normal-path push guard (`if has_origin:` at "6. Push main + the new
tag") and everything else unchanged. Confirm the word `trunk_missing` no longer
appears anywhere in `merge.py` after this step.

## Step 4 — drift: correct two comments that describe the removed seed path

**4a.** `docex/src/docex/pipeline/check.py` — the first-release-mode banner
(currently ~lines 861–867). Change:
```python
            print(
                "check: origin/main does not exist yet — running in "
                "first-release mode (trunk-comparing gates are "
                "skipped). `docex merge` will seed origin/main from "
                "this feature branch.",
                file=sys.stderr,
            )
```
to:
```python
            print(
                "check: origin/main does not exist yet — running in "
                "first-release mode (trunk-comparing gates are skipped).",
                file=sys.stderr,
            )
```
Do NOT change any other logic in check.py — first-release mode stays; only the
now-false sentence about merge seeding is dropped.

**4b.** `docex/src/docex/git/client.py` — the `ref_exists` docstring (currently
~lines 74–81). Change:
```python
    def ref_exists(self, cwd: Path, ref: str) -> bool:
        """Return True iff ``git rev-parse --verify`` resolves ``ref``.

        Used to distinguish a brand-new project (no ``origin/main`` yet
        because the remote is empty) from an established one. Lets
        ``check`` and ``merge`` switch into a "first release on empty
        remote" path that seeds main from the feature branch.
        """
```
to:
```python
    def ref_exists(self, cwd: Path, ref: str) -> bool:
        """Return True iff ``git rev-parse --verify`` resolves ``ref``.

        Used to distinguish a brand-new project (no ``origin/main`` yet
        because the remote is empty) from an established one. Lets
        ``check`` run its "first release on empty remote" mode, which
        skips the trunk-comparing gates.
        """
```

## Step 5 — `docex/tests/unit/test_pipeline_merge.py`: retarget seed-path tests

**5a.** DELETE these three tests entirely (they asserted the removed seed path):
- `test_merge_seeds_main_on_empty_origin`
- `test_merge_skips_remote_feature_delete_on_empty_origin`
- `test_merge_no_origin_seeds_main_when_local_main_absent`

**5b.** ADD two replacement tests asserting the new fail-loud precondition. Add
them where the deleted `test_merge_seeds_main_on_empty_origin` was:
```python
def test_merge_fails_when_origin_main_absent(
    sample_ctx, fake_docker, fake_git, patched_check
):
    """First release with origin present but no origin/main: merge must
    fail loudly (inception should have established main) rather than seed
    a trunk. No rebase, no tag, no push."""
    fake_git.branch = "feature/x"
    fake_git.refs = set()  # origin present (default), but empty — no origin/main
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc != 0
    methods = {c[0] for c in fake_git.calls}
    assert "rebase" not in methods, fake_git.calls
    assert "fast_forward" not in methods, fake_git.calls
    assert "tag" not in methods, fake_git.calls
    assert "push" not in methods, fake_git.calls


def test_merge_fails_when_no_origin_and_no_local_main(
    sample_ctx, fake_docker, fake_git, patched_check
):
    """No origin AND no local main: nothing to rebase onto. Merge fails
    loudly instead of seeding a trunk."""
    fake_git.branch = "feature/x"
    fake_git.has_origin = False
    fake_git.refs = {"HEAD"}  # neither origin/main nor main exist
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc != 0
    methods = {c[0] for c in fake_git.calls}
    assert "rebase" not in methods, fake_git.calls
    assert "fast_forward" not in methods, fake_git.calls
    assert "tag" not in methods, fake_git.calls
```

**5c.** Verify the fake git client (`fake_git`) supports what these tests need.
Find its definition (`grep -rn "class .*Git\|def ref_exists\|has_origin\|self.refs" docex/tests/`).
Confirm `ref_exists` on the fake consults `self.refs` and that the default
`has_origin` is `True`. If `test_merge_fails_when_origin_main_absent` needs the
fake to report an origin while `refs` is empty, that is the fake's default
(`has_origin=True`, `refs=set()`); do not change the fake unless a test can't be
expressed against it. Leave the surviving tests
(`test_merge_no_origin_skips_fetch_and_push`,
`test_merge_no_origin_deletes_local_branch_only`, and all normal-path tests)
untouched.

## Step 6 — run the suites (foreground, from `docex/`)

Run, in order, and report both counts:
```
docex/.venv/bin/python -m pytest tests -q
docex/.venv/bin/python -m pytest tests -q -m integration
```
(Run the second command **alone**, i.e. as its own invocation.) Baseline before
this mod: unit `1254 passed, 21 deselected`; integration `21 passed, 1254
deselected`. Net unit count changes by the test delta (−3 deleted, +2 added ⇒
expect `1253 passed`). Everything must be green. If anything is red, report the
exact failure — do not paper over it.

## Step 7 — linkcheck (from repo root)

Run the repo's `linkcheck` and report the verdict. A BROKEN result confined to
`RELEASING.md` or `docex/plans/advances/floating_todo/` is the operator's
uncommitted WIP — report it but do NOT touch those files. Any broken link your
own edits introduced must be fixed.

## Contracts

No core-service surfaces change in this mod. No contract edits required.

## What NOT to do

- Do not edit `docex/plans/core/*.md` (incl. `test_projects.md`, `masterplan.md`).
- Do not edit `CHANGELOG.md` (the mod owner handles it in the documentation step).
- Do not `git add`/commit anything (the mod owner commits).
- Do not touch `RELEASING.md` or `docex/plans/advances/floating_todo/`.

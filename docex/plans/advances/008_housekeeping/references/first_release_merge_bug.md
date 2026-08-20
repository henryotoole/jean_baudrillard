# First release fails because `origin/main` never exists — fix in inception

On a project's very first release, `docex merge` cannot integrate the feature
branch because `origin/main` does not yet exist. `merge.py`'s seed-trunk path
(the branch taken when `git.ref_exists(trunk_ref)` is false) tries to seed `main`
via `git.fast_forward(project_root, "main", feature)`, but `fast_forward` is
`git checkout <branch> && git merge --ff-only <to_ref>` — the `git checkout main`
fails with `pathspec 'main' did not match` because `main` does not exist to check
out. Merge exits with "Manual recovery needed" and leaves the repo untouched.

The root cause is upstream of merge: inception never establishes `main` at all.
`inception.md` PART I creates the feature branch `inception_and_first_draft`
(step 6) and lands every setup/draft commit on it (Parts I–IV), so the trunk is
absent until the first release's `docex merge` is asked to invent it — the one
path that is broken.

## The fix — establish `main` at inception, not at first merge

Change `inception.md` PART I to start the project on an empty `main` pushed to
origin, then branch off it. `docex merge` then always takes the normal
rebase-onto-`origin/main` path, and the first-release seeding case never arises.

Insert between the clone/`cd` (PART I steps 4–5) and the feature-branch creation
(step 6):

- Ensure the initial branch is named `main` (the doctrine trunk), create an empty
  initial commit, and push it to origin so `origin/main` exists:

  ```
  git commit --allow-empty -m "Initial commit"
  git push -u origin main
  ```

- Then create and switch to `inception_and_first_draft` (existing step 6) off
  `main`. Every Part I–IV commit stays on the feature branch as today; only the
  empty trunk root is added ahead of it.

At PART V, the first `docex merge` rebases the feature onto the (empty but
existing) `origin/main`, tags `v<version>`, pushes, and deletes the feature
branch — the established path, with no seeding.

## Secondary — remove merge's seed-trunk path (decided at plan review)

With inception guaranteeing `origin/main`, `merge.py`'s seed-trunk branch is
unreachable in the sanctioned flow while remaining broken. **Remove it as dead
code** and let `merge` assume `main` exists — honest, with no untested path left
to rot. A repo set up outside inception is outside doctrine anyway. (Repairing it
as defense-in-depth was the alternative; rejected because it leaves an
unexercised path.)

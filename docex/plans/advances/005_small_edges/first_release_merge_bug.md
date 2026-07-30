# `docex merge` — first-release main-seeding bug

## Summary

On a project's **very first release** — when `origin/main` does not yet exist —
`./bin/docex merge` fails while trying to seed `main` from the feature branch,
and leaves the repo untouched with a "Manual recovery needed" message. Observed
on docex **1.5.0** during the `field_radio` inception (first release, `v0.0.1`).

## Symptom

`./bin/docex merge` output (feature branch = `inception_and_first_draft`, empty
`origin/main`):

```
merge: origin/main does not exist — seeding main from the current feature branch ('inception_and_first_draft').
error: pathspec 'main' did not match any file(s) known to git
error: failed to create 'main' at 'inception_and_first_branch' (exit 1). Manual recovery needed.
```

The git-history gate checks are correctly *skipped* in this case
(`no_merge_conflicts`, `worktree_clean`, `latest_main`, `version_bumped`,
`version_not_released` all report "skipped (empty origin/main)"), so detection of
the first-release condition works — it is only the *seeding action* that fails.

## Root cause (hypothesis)

The seeding path emits the right intent ("seeding main from the current feature
branch") but the underlying git invocation assumes `main` already exists — the
`pathspec 'main' did not match` error is the signature of a command like
`git checkout main` / `git switch main` (or a `git branch <x> main` reading
`main` as a start-point) run *before* `main` has been created. The create step
appears to reference `main` as a source rather than creating it from the current
`HEAD` / feature tip.

## Expected behavior

When `origin/main` (and local `main`) do not exist, seed `main` at the current
feature-branch tip, i.e. the equivalent of:

```
git branch main HEAD     # create main AT the feature tip
git switch main
```

then proceed with the normal tag + push + delete-feature flow.

## Manual recovery used (unblocks the first release)

From the feature branch, reproduce merge's intended end-state by hand:

```
git branch main            # main at feature tip
git checkout main
git tag v<version>         # e.g. v0.0.1, from project.yml
git push -u origin main
git push origin v<version>
git branch -d <feature>    # delete the merged feature branch
```

After this, `main` exists on origin and every subsequent `./bin/docex merge`
takes the normal rebase-onto-main path. The rest of the pipeline
(`containerize` → `release stage` → `stagetest` → `release prod`) ran clean.

## Suggested fix

In the merge seeding branch, create `main` from `HEAD` explicitly
(`git branch main HEAD` / `git switch -c main`) rather than treating `main` as an
existing start-point, then push with `-u`. Add a regression test that runs
`docex merge` against a repo whose origin has no `main` and asserts `main` +
`v<version>` land on origin and the feature branch is deleted.

# Releases

A release is a versioned, stable snapshot of the codebase — a deliberate decision that the work accumulated on `main` is ready to ship. Releases are distinct from [deployment](./deployment.md), which is the act of making a release pushing release code into the production machinery.

## Key Words and Definitions

Reference [Lexicon](../lexicon.md) for special words and phrases that have unique context for all markdown files in this folder.

## Process

A release is a deliberate act on `main`. The steps:

1. **Ensure `main` is stable** — all tests pass in the docker test stack.
2. **Create a release commit** on `main` that does exactly two things:
   - Bumps `$pr/VERSION` to the new version.
   - Promotes `[Unreleased]` in `$pr/CHANGELOG.md` to the new version with today's date, and adds a fresh empty `[Unreleased]` section above it.
3. **Tag the commit** with an annotated git tag matching the version:
   ```bash
   git tag -a v0.1.0 -m "Release 0.1.0"
   ```
4. **Push** the commit and tag:
   ```bash
   git push origin main --tags
   ```

The release commit should contain *only* the version bump and changelog update — no code changes. This keeps the tag clean and the release easily identifiable in history.

## Tag Format

Use a `v` prefix on tags (`v1.2.0`) to distinguish version tags from any other tags. The `VERSION` file itself stays bare (`1.2.0`).

## Justfile

```just
release version:
  git tag -a v{{version}} -m "Release {{version}}"
  git push origin main --tags
```

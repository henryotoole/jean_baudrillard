---
version: "2.1.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 2.1.0

## Summary

A backlog-clearing "housekeeping" release (advance 008): many small, mostly
independent correctness fixes, one new `docex` feature, and two deferred CICL
scope decisions. See the [changelog](../CHANGELOG.md#210---2026-08-24) for the
full narrative. It is a **minor** release, but it introduces **two new hard
compile rejections** that are breaking *in principle* — each enforces a rule the
doctrine already stated, so no conforming project trips either. The two are the
only project-side action; everything else is machine-side or automatic.

## Machine sync

`git pull` + `setup.sh` handle it: the plugin-cache version bump reinstalls the
skill set, `RESIDENT.md` regenerates, and `doctrine-update` builds the new
`docex:2.1.0` image. No manual machine step. (No skill *description* changed this
release; the excerpt/doctrine content refreshes with the pull and the rebuilt
image.)

## Project upgrade

Repin and recompile:

```sh
bash ~/.claude/jean_baudrillard/docex_install.sh <project>   # moves docex_version → 2.1.0
cd <project> && ./bin/docex compile
```

If `compile` was green on 2.0.x it stays green **unless** the project trips one
of the two new rejections below. Both enforce pre-existing doctrine rules; a
conforming project needs no edit. Run the two grep-checks first to be sure:

1. **Project name must already be a valid DNS label** (`rule` in
   `context.py` / `ProjectManifest.name`, pattern `^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$`).
   A non-conforming name — in practice a capital letter — is now rejected at load
   rather than silently compiling to two disagreeing spellings of its own project
   segment (a case-sensitive-AWS split-brain). Check:
   ```sh
   grep -E '^name:' project.yml            # the value must be lowercase; no [A-Z]
   ```
   If the name carries a capital, you must rename the project (its name is
   immutable by convention, so this is a deliberate, deploy-affecting change —
   coordinate it; renaming changes every derived resource identity).

2. **A backing service must declare `version:` when its engine pins an image/version
   from it** (`rule_version_required`). This affects an `object_store` on the
   `minio` (fixed) engine, which now pins `minio/minio:${version}` instead of a
   hardcoded `:latest`. `s3` (elastic, no image) is exempt structurally. Check:
   ```sh
   # any object_store backing service must carry a `version:`
   grep -nA6 'role: *object_store' infra/infra.yml | grep -q 'version:' || \
     echo "object_store missing version: — add one (a minio RELEASE tag)"
   ```
   Add a `version:` (a minio `RELEASE.YYYY-MM-DDTHH-MM-SSZ` tag) to any
   `object_store` that lacks one. This closes a determinism hole (an unpinned
   `:latest` against a persistent data volume).

Nothing else in `infra.yml` changes; `cicl_version` stays `"3"`.

## Doctrine / behavior notes

- **New `docex secrets` capability — value fingerprints.** `docex secrets status
  <env> --fingerprint` adds a non-revealing salted `sha256[:8]` column, and
  `docex secrets fingerprints` prints a cross-env matrix, for verifying a secret's
  propagation/drift across environments without exposing its value. It is an
  equality/drift check, **not** a confidentiality guarantee for a low-entropy
  value. No action; available when you want it.
- **Fixed `stage`/`prod` releases now migrate before the stack comes up.** The
  emitted ansible playbook previously started the stack at the image-pull step, so
  the real ordering was up→migrate; it now pulls without starting, so migration
  runs first and a failed migration aborts before the new code is live. No action;
  behavior-only, and it restores the abort guarantee `migrations.md` always
  described. (mod 144)
- **A new `docex check` gate rejects a contract below its spec floor** (OpenAPI ≥
  3.2, AsyncAPI ≥ 3.0). If a project ships an older contract spec version, `check`
  now fails and the fix is to raise the `openapi:`/`asyncapi:` version in the
  contract file. (mod 137)

## Verification

```sh
cd <project> && ./bin/docex --version     # prints 2.1.0
./bin/docex compile                        # green; no name / version rejection
```

Both grep-checks above return nothing (or you have added the missing `version:` /
renamed the project). On a fixed `stage`/`prod` release, a `docex migrate` runs
before `docker compose up -d` in the emitted playbook.

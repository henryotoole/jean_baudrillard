# Mod 056 — .gitignore standards

Third mod of the `001_skill_update` advance. Closes the planner's ".gitignore
standards" item ("start adding things like `*.pyc` to gitignore in inception.md").

## Nature of this mod

This mod is **doctrine + seed files only** — no `docex` code or tests change.
`docex` does not generate the project `.gitignore`; the inception flow's agent
creates it from the default block in `inception.md`. So there is no compiler/
orchestration counterpart to implement, and no sub-agent execution step. The
change is small and mechanical, applied directly.

## What changed

1. **`doctrine/practices/inception.md` § `.gitignore` Defaults** — added:
   - `.docex/` (ephemeral worktrees — was missing from the canonical default
     though the smoke seeds already had it).
   - A Python bytecode + tool-cache block (`__pycache__/`, `*.py[cod]`,
     `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.venv/`, `venv/`).
   - Editor/IDE (`.idea/`, `.vscode/`) and `*.log`.
   - A note that projects add language-specific patterns for their stack
     (`node_modules/`, Rust `target/`, Go `bin/`).
   - Clarified the OpenTofu comment: `.terraform.lock.hcl` is **committed**, not
     ignored — the provider lock pins versions, which the doctrine's determinism
     promise wants. (Fixed a stale `elastic_bootstrap` reference too.)

2. **`docex/test_projects/{fixed,elastic}/.gitignore`** — reconciled both
   doctrine-faithful seeds to the new canonical default. This closed three drifts:
   the seeds carried a stale `elastic_bootstrap` comment; they had only `*.pyc`
   (now `*.py[cod]` + caches); and the **elastic** seed ignored
   `.terraform.lock.hcl` (now removed — the lock is committed per the decision
   above), which the fixed seed never did.

## Inner-repo follow-up (operator)

The smoke projects under `test_projects/` are their own inner git repos with a
`v<version>` tag at HEAD for `docex containerize`. Editing their `.gitignore`
dirties those inner repos. This mod commits the change only in the **outer**
`jean_baudrillard` repo (the advance history). The inner-repo commit — and any
tag handling per `test_projects.md` § Commit cadence — is left to the operator's
pre-cut audit (`PRE_CUT_CHECKLIST.md` § A.2.1), so this mod doesn't move version
tags out from under a future smoke walk.

## Doctrine status

Doctrine edit (inception.md) approved by the operator before applying, per
`docex_process.md`.

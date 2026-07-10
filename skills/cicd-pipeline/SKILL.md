---
name: cicd-pipeline
description: Doctrine for running the CI/CD pipeline — check, merge, containerize, release, migrate, stagetest, and rollback — across fixed and elastic foundations. Use this whenever you are building, testing, releasing, migrating, or rolling back a project, or driving any docex pipeline command, even if you do not name the step.
metadata:
  type: thread
---

# cicd-pipeline

The pipeline is one activity spanning many `docex` commands; read the pipeline overview and the credential model first, and descend into the release, migrate, or secret mechanism when you reach that step.

## General Information

The pipeline shape and how credentials and secrets are handled. **Read these now.**

[`cicd.md`](../../doctrine/infrastructure/cicd.md) — the full pipeline: check → merge → containerize → release → stagetest → rollback, with each step's process and `docex` command.

[`credentials.md`](../../doctrine/infrastructure/credentials.md) — how deploy credentials are stored and how they flow into each environment.

## Specific Information

The mechanism behind the heavier steps. **Read on demand.**

[`release.md`](../../doctrine/infrastructure/specifics/release.md) — how `docex release` drives a build into an env: ansible (fixed) vs. SSM-push plus tofu (elastic), first-release vs. steady-state ordering, and failure modes.

[`migrations.md`](../../doctrine/infrastructure/specifics/migrations.md) — the `migrate.sh` contract and how migrations run per env category and foundation.

[`config_and_secrets.md`](../../doctrine/infrastructure/specifics/config_and_secrets.md) — how `<env>.env` materializes into compose env vars (fixed) or SSM `secrets[]` entries (elastic).

## Thread

- The pipeline acts on *compiled* output and *contracts*: regenerate output via `infra-compile`; the check step verifies contracts (`contracts`) and runs the build tests (`testing`).
- Release targets standing infrastructure — `preinfra-setup` and `projinfra-setup` must be in place first.
- Every step is driven through the executor; the command reference is [`docex.md`](../../doctrine/infrastructure/docex.md) (`./bin/docex <command>`). Changing `docex` itself is `docex-edit`.

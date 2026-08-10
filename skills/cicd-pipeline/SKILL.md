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

[`elastic_release_pattern.md`](../../doctrine/infrastructure/reasoning/elastic_release_pattern.md) — why the elastic release carries a post-apply reconcile step at all: ECS's three name-resolution mechanisms and why Service Connect is the only one available, why dependency ordering cannot fix the resulting race, and why the fix observes durable state rather than enforcing an order. Read alongside `release.md` when the reconcile step surprises you.

[`migrations.md`](../../doctrine/infrastructure/specifics/migrations.md) — the `migrate.sh` contract and how migrations run per env category and foundation.

[`exec_service.md`](../../doctrine/infrastructure/specifics/exec_service.md) — the per-codebase one-off container `build`, `test`, and `migrate` all run inside: why it exists, what the compiled block carries, and how to invoke it by hand. Read when a pipeline step's one-off container behaves unexpectedly, or when a job needs running against a codebase's image with no `docex` command of its own.

[`config_and_secrets.md`](../../doctrine/infrastructure/specifics/config_and_secrets.md) — how `<env>.env` materializes into compose env vars (fixed) or SSM `secrets[]` entries (elastic).

[`healthchecks.md`](../../doctrine/infrastructure/healthchecks.md) — what `stagetest` reads from the orchestrator before it runs a single test, and what the `health.sh` probe it is reading actually proves. Read when a release or stagetest fails on a service's health rather than on a test.

## Thread

- The pipeline acts on *compiled* output and *contracts*: regenerate output via `infra-compile`; the check step verifies contracts (`contracts`) and runs the build tests (`testing`).
- Release targets standing infrastructure — `preinfra-setup` and `projinfra-setup` must be in place first.
- Every step is driven through the executor; the command reference is [`docex.md`](../../doctrine/infrastructure/docex.md) (`./bin/docex <command>`). Changing `docex` itself is `docex-edit`.

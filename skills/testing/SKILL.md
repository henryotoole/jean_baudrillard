---
name: testing
description: Doctrine for a project's test taxonomy and harness — which tier a test belongs to (service-level unit/integration/contract vs. project-level staging), where each tier runs (the test env vs. against a deployed stage), and the test.sh / stage_test.sh shims. Use this when deciding what kinds of tests a core service needs, where a test should run, or wiring the test/stage shims. Not for how to write a specific test of a class or function — that is the Resident hexagonal-architecture doctrine.
metadata:
  type: thread
---

# testing

A single file defines the infrastructure-level test taxonomy and where each tier runs.

## General Information

The test tiers and how they are invoked. **Read this now.**

[`tests.md`](../../doctrine/infrastructure/tests.md) — service tests (unit / integration / contract) run in the `test` env via `test.sh`, and staging tests run against a deployed env via `stage_test.sh`; what belongs in each tier, and the env vars docex injects into the stage tester.

## Thread

- The four hexagonal test types (domain / alogic / adapter / module) are the Resident architecture doctrine, already in context; this skill is the infrastructure framing around them.
- Contract tests realize the boundaries defined in `contracts`.
- Tests are executed by the pipeline — build tests in the check/test step, staging tests in stagetest — see `cicd-pipeline`.

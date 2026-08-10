---
name: testing
description: Doctrine for a project's test taxonomy and harness — which tier a test belongs to (codebase-level unit / integration / contract, where integration spans module- and codebase-level "flow" tests, vs. project-level staging), where each tier runs (the test env vs. against a deployed stage), and the test.sh / stage_test.sh shims. Use this when deciding what kinds of tests a codebase needs, whether to write a flow test vs. a contract test, where a test should run, or wiring the test/stage shims. Not for how to write a specific test of a class or function — that is the Resident hexagonal-architecture doctrine.
metadata:
  type: thread
---

# testing

A single file defines the infrastructure-level test taxonomy and where each tier runs.

## General Information

The test tiers and how they are invoked. **Read this now.**

[`tests.md`](../../doctrine/infrastructure/tests.md) — codebase tests (unit / integration / contract) run in the `test` env via `test.sh`, and staging tests run against a deployed env via `stage_test.sh`; what belongs in each tier, and the env vars docex injects into the stage tester.

## Thread

- The five hexagonal test types (domain / alogic / adapter / module / codebase-flow) are the Resident architecture doctrine, already in context; this skill is the infrastructure framing around them.
- Contract tests realize the boundaries defined in `contracts`.
- Flow tests vs. contract tests: a flow test asserts *behavior* (correct values + side effects for a hand-authored scenario) while a contract test asserts *shape* conformance to the contract — a schema-valid response can still be the wrong answer. See `tests.md` § Integration Tests (Codebase-Level) and § Contract Tests.
- **Scope, across the three axes:** a flow test is scoped to the **codebase** (one composition root, so a scenario entering at `web` can reach `worker`'s handler in-process); a contract test asserts about one **surface**, of which a core service may declare several. Both nonetheless *run* in the codebase's [exec-service](../../doctrine/infrastructure/specifics/exec_service.md) one-off container, under the single `test.sh`. Contracts track surfaces; test suites track codebases.
- **Staging tests do not assert liveness.** `docex` reads every core service's health and version from the orchestrator before the stage tester is built, so staging tests cover only what requires being outside — TLS, DNS, routing, and critical-path smoke tests. They cannot reach a non-`web` core service at all.
- Tests are executed by the pipeline — build tests in the check/test step, staging tests in stagetest — see `cicd-pipeline`.

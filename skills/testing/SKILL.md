---
name: testing
description: Doctrine for a project's test taxonomy and harness — which tier a test belongs to (codebase-level unit / integration / contract, where integration spans module- and codebase-level "flow" tests and folds in contract, vs. project-level staging), which of the two execution shims runs it (no-infra test_unit.sh vs. stack-backed test_integration.sh), where each runs (the test env vs. against a deployed stage), and the test_unit.sh / test_integration.sh / stage_test.sh shims. Use this when deciding what kinds of tests a codebase needs, whether to write a flow test vs. a contract test, where a test should run, or wiring the test/stage shims, and the two execution modes `docex test` exposes (the no-stack `docex test unit` fast lane for iterating on a failing test vs. the fresh-throwaway full run), including the `DOCEX_TEST_SELECTOR` subset contract, and the full-vs-scoped test-selection policy (a mod cycle iterates scoped and closes full; an advance closes full; CI/CD is always full). Not for how to write a specific test of a class or function — that is the Resident hexagonal-architecture doctrine.
metadata:
  type: thread
---

# testing

A single file defines the infrastructure-level test taxonomy and where each tier runs.

## General Information

The test tiers and how they are invoked. **Read this now.**

[`tests.md`](../../doctrine/infrastructure/tests.md) — codebase tests (unit / integration / contract) run in the `test` env via **two shims**, `test_unit.sh` (no-infra) and `test_integration.sh` (stack-backed, folding in contract), and staging tests run against a deployed env via `stage_test.sh`; what belongs in each tier, and the env vars docex injects into the stage tester.

## Thread

- The five hexagonal test types (domain / alogic / adapter / module / codebase-flow) are the Resident architecture doctrine, already in context; this skill is the infrastructure framing around them.
- Contract tests realize the boundaries defined in `contracts`.
- Flow tests vs. contract tests: a flow test asserts *behavior* (correct values + side effects for a hand-authored scenario) while a contract test asserts *shape* conformance to the contract — a schema-valid response can still be the wrong answer. See `tests.md` § Integration Tests (Codebase-Level) and § Contract Tests.
- **Scope, across the three axes:** a flow test is scoped to the **codebase** (one composition root, so a scenario entering at `web` can reach `worker`'s handler in-process); a contract test asserts about one **surface**, of which a core service may declare several. Both nonetheless *run* in the codebase's [exec-service](../../doctrine/infrastructure/specifics/exec_service.md) one-off container, under `test_integration.sh` (both are stack-backed — flow needs the live stack, contract spins a provider/mock in a container). Contracts track surfaces; test suites track codebases.
- **Staging tests do not assert liveness.** `docex` reads every core service's health and version from the orchestrator before the stage tester is built, so staging tests cover only what requires being outside — TLS, DNS, routing, and critical-path smoke tests. They cannot reach a non-`web` core service at all.
- Tests are executed by the pipeline — build tests in the check/test step, staging tests in stagetest — see `cicd-pipeline`.
- **`docex test` is a durable job.** The suite runs in a detached vessel container, so a killed monitor leaves the run alive and re-attachable (`docex test --detach` + `docex job wait`); the blocking default still exits with the run's code. The async command surface lives in [`docex.md § Command Lifecycle`](../../doctrine/infrastructure/docex.md#command-lifecycle) / the `cicd-pipeline` skill, not here.
- **Two execution modes + subset.** `docex test unit [subset]` runs the unit tier
  with **no stack** (the fast inner loop); `docex test integration [subset]` runs
  the stack-backed tier; a `[subset]` narrows within the tier and reaches the
  project shim as the injected `DOCEX_TEST_SELECTOR`. Both the modes and the
  injected-variable contract are in [`tests.md § Two execution modes`](../../doctrine/infrastructure/tests.md#two-execution-modes)
  / [§ Injected environment](../../doctrine/infrastructure/tests.md#injected-environment).
- **Test-selection policy (scope is a sanctioned choice).** A mod cycle may
  iterate with scoped runs but **closes on the full `unit` tier plus the relevant
  `integration` tests**; an **advance closes on a full run of both tiers** across
  the project; **CI/CD (`check` / `merge`) is always full**. Scope is agent
  judgment via the subset mechanism above — and `docex test --slots N` sharding
  is what makes closing on full `integration` affordable. **No computed
  "affected" selector exists**, by design: cross-module driving-port imports,
  `shared/` blast radius, and domain changes with no test mirror make a computed
  set give false confidence. The process side lives in
  [`modifications.md`](../../doctrine/practices/modifications.md) (mod cycle) and
  [`advance.md`](../../doctrine/practices/advance.md) (advance).

---
stratum: conditional
---

# Tests

This document describes the different kinds of automated tests which ship with a project, where they belong, and when they are supposed to be run.

## Service Tests

Service tests describe all unit tests and integration tests which cover a single **codebase** — its `tests/` tree, run by its `test.sh` inside its test-stage container. The scope is the codebase and not one of its core services because the test suite, like the artifact, is a property of the source tree: one `test.sh` per codebase covers every core service that codebase declares. The tier keeps the name "service tests" to distinguish it from project-wide [staging tests](#staging-tests). When we perform tests in the `test` environment, we are running every codebase's service tests.

These tests test the code itself - that functions behave correctly, modules within a codebase can communicate, etc. They *don't* test inter-core-service communication. They can, however, interact with a backing service for the purpose of testing a single codebase (required for some integration tests).

Service tests are written in whatever language, and with whatever tooling, is appropriate for the codebase. A codebase written in python would have tests also written in python and perhaps run with `pytest`.

Unit, integration, and contract tests should all be run by the [standard service test script](./cicd.md#build-test-step)

The folder structure of service tests (and more details on how to write them) is described here: [hex_overview.md](../hexagonal_architecture/hex_overview.md#tests)

### Unit Tests
These are very fast tests which test a piece of code in isolation. Dependencies are mocked. The purpose is to determine if the unit's internal logic is correct.

### Integration Tests
These tests verify that multiple pieces work *together*. Tests might fire against real backing service containers (in a `test` env) rather than mocked ones.

#### Module-Level
Module-level integration tests verify that a single module behaves as expected.

#### Service-Level
Service-level integration tests (e.g. "flow" tests) verify that the entire core service behaves as expected, often from the "outside" (e.g. by applying requests against an actual backend's api). It tests all modules, often in an end-to-end form. We call these "flow" tests because they test the flow of information across the entire service's codebase as a hand-authored scenario plays out.

Flow tests are similar to contract tests. Both test the whole service as a unit. The distinction is in *purpose*. A contract test ensures the service's external shape is consistent with the contract (e.g. that a JSON POST response has code 200 and `some_field`). A flow test ensures the service's *behavior* is correct (e.g. that the JSON POST response has the actual correct value for `some_field`) and that the expected effects occur as a result (e.g. the correct record is persisted as a result of the POST). A schema-valid response can still be the wrong answer; that gap is what flow tests cover.

### Contract Tests
[On contracts](./infrastructure.md#contracts).

Contract tests ensure core service modularity. They check that the boundary of a core service is well-defined, and ensure that consumers of that core service can expect the interior machinery to behave as defined by the contract. They don't literally test communications between multiple core services, but they do ensure that core services *will communicate correctly* in production.

Good contract tests spare the developer from needing to write and maintain a bunch of complex and brittle end-to-end staging tests. Staging tests ideally test only *infrastructure* and shouldn't be burdened by concern over the application logic within a service.

The tricky thing about contract tests is that they can run on both sides of the contract. The provider side ensures that the provider reacts correctly to simulated contract-appropriate requests from "outside" the service. The consumer side ensures that the consumer acts and reacts correctly when working with a provider that is mocked in accordance with the contract.

This doctrine requires provider-side contract tests for core services with defined contracts, and encourages consumer-side contract tests for larger projects with many different core services.

#### Provider Side
- Runs inside the provider codebase's test Dockerfile stage container.
- Test starts the provider's HTTP server inside the container.
- A schema-validation tool (e.g., schemathesis for OpenAPI) hits the real running endpoints.
- Verifies that actual responses conform to what contract.*.yml declares.
- Invoked by provider's test.sh.

#### Consumer Side
- Runs inside the consumer codebase's test Dockerfile stage container.
- A mock server is generated from the provider's contract - either via a separate container (Prism, AsyncAPI mock) or as an in-process mock library (e.g., httpx_mock for Python clients).
- consumer's tests hit the mock instead of the real backend.
- Verifies consumer can work against any contract-conformant provider.
- Invoked by consumer's test.sh.

The consumer side is *especially* tricky because it can require spinning up a separate container. If this is done, it should be done as a subcontainer *within* the codebase's test container. That way it does not become an infrastructural concern.

## Staging Tests

Staging tests verify that a deployed release functions correctly on its infrastructure. They catch problems that service tests can not because service tests run isolated within a singular codebase. 

Staging tests should at least perform the following:
+ Liveness Checks - Each `web`-network core service responds to its own `GET /health` at its own hostname. Core services that are not on `web` are not reachable from the stage tester at all, so their liveness is asserted through the `/health/<codebase>/<service>` [fan-out](./contracts.md#fan-out) on the `web` core service that `consumes` them. `scheduler` core services are exempt — they have no long-running container to probe.
+ TLS / DNS - Can requests reach the [reverse proxy](./shape.md#general)?
+ Critical-path smoke-tests - one or two end-to-end smoke tests that span the system. These should be sufficient to ensure:
	1. Secrets and environmental variables are wired up properly.
	2. Services can actually reach each other over the network.

Staging tests are run per-project, not per-codebase. They are run *by* the project-wide `$pr/infra/stage/stage_test.sh` [stage test shim](./cicd.md#staging-tests) and are run *in* a special "test environment" image that is launched by the `./bin/docex stagetest` command and described by `$pr/infra/stage/Dockerfile`. The tests themselves are written by the developer and go in the `$pr/infra/stage/tests` folder.

While the `doctrine` describes these files, it is the project developer's responsibility to write and maintain them. The developer writes the tests, ensures they are called by `stage_test.sh`, and ensures that if any of them fail, `stage_test.sh` will return a non-0 exit code. 

The developer must also ensure that the Dockerfile produces an environment with the necessary libraries and tooling to run those tests. Bind-mounting `$pr/infra/stage` directory is handled by `./bin/docex stagetest`.

### Injected environment

`./bin/docex stagetest` injects a small set of doctrine-defined env vars into the stage tester container so the project's tests can stay free of values that have to be hand-synced on every release:

| Variable | Source | Purpose |
| -------- | ------ | ------- |
| `STAGING_URL` | derived from `infra.yml`'s `apex_domain` field and [domain rules](./cicl.md#domain) | The public URL of the deployed staging environment. Tests issue HTTPS calls against this. |
| `PROJECT_VERSION` | `project.yml` `version:` field | The version of the build under test. Tests that assert a deployed `/health` returns the expected version read this rather than maintaining a hardcoded `EXPECTED_VERSION` that drifts on every release. |

The contract is one-way and stable: docex injects these on every `stagetest` run; the project's tests are free to read or ignore them. Adding new doctrine-injected variables is a doctrine change, not a project change.
# Tests

This document describes the different kinds of automated tests which ship with a project, where they belong, and when they are supposed to be run.

## Service Tests

Service tests describe all unit tests and integration tests which cover a single core service container. When we perform tests in the `test` environment, we are running all service tests for all service containers.

These tests test the code itself - that functions behave correctly, modules within a service can communicate, etc. They *don't* test inter-core service communication. They can, however, interact with a backing service for the purpose of testing a single core service (required for some integration tests).

Service tests are written in whatever language, and with whatever tooling, that is appropriate for the service. A `web` core service written in python would have tests also written in python and perhaps run with `pytest`.

Unit, integration, and contract tests should all be run by the [standard service test script](./cicd.md#build-test-step)

### Unit Tests
These are very fast tests which test a piece of code in isolation. Dependencies are mocked. The purpose is to determine if the units internal logic is correct.

### Integration Tests
These tests verify that multiple pieces work *together*. Tests might fire against real backing service containers (in a `test` env) rather than mocked ones.

### Contract Tests
[On contracts](./infrastructure.md#contracts).

Contract tests ensure core service modularity. They check that the boundary of a core service is well-defined, and ensure that consumers of that core service can expect the interior machinery to behave as defined by the contract. They don't literally test communications between multiple core services, but they do ensure that core services *will communicate correctly* in production.

Good contract tests spare the developer from needing to write and maintain a bunch of complex and brittle end-to-end staging tests. Staging tests ideally test only *infrastructure* and shouldn't be burdened by concern over the application logic within a service.

The tricky thing about contract tests is that they can run on both sides of the contract. The provider side ensures that the provider reacts correctly to simulated contract-appropriate requests from "outside" the service. The consumer side ensures that the consumer acts and reacts correctly when working with a provider that is mocked in accordance with the contract.

This doctrine requires provider-side contract tests for core services with defined contracts, and encourages consumer-side contract tests for larger projects with many different core services.

#### Provider Side
- Runs inside the provider service's test Dockerfile stage container.
- Test starts the provider's HTTP server inside the container.
- A schema-validation tool (e.g., schemathesis for OpenAPI) hits the real running endpoints.
- Verifies that actual responses conform to what contract.*.yml declares.
- Invoked by provider's test.sh.

#### Consumer Side
- Runs inside the consumer service's test Dockerfile stage container.
- A mock server is generated from the provider's contract - either via a separate container (Prism, AsyncAPI mock) or as an in-process mock library (e.g., httpx_mock for Python clients).
- consumer's tests hit the mock instead of the real backend.
- Verifies consumer can work against any contract-conformant provider.
- Invoked by consumer's test.sh.

The consumer side is *especially* tricky because it can require spinning up a separate container. If this is done, it should be done as a subcontainer *within* the core service container. That way it does not become an infrastructural concern.

## Staging Tests

Staging tests verify that a deployed release functions correctly on its infrastructure. They catch problems that service tests can not because service tests run isolated within a singular service. 

Staging tests should at least perform the following:
+ Liveness Checks - Each core service responds to its [health-check endpoint](./contracts.md#health-checks).
+ TLS / DNS - Can requests reach the [reverse proxy](./shape2.md#general)
+ Critical-path smoke-tests - one or two end-to-end smoke tests that span the system. These should be sufficient to ensure:
	1. Secrets and environmental variables are wired up properly.
	2. Services can actually reach each other over the network.

Staging tests are run per-project, not per-service. They are run *by* the project-wide `$pr/infra/stage/stage_test.sh` [stage test shim](./cicd.md#staging-tests) and are run *in* a special "test environment" image that is launched by the `./bin/docex stagetest` command and described by `$pr/infra/stage/Dockerfile`. The tests themselves are written by the developer and go in the `$pr/infra/stage/tests` folder.

While the `doctrine` describes these files, it is the project developer's responsibility to write and maintain them. The developer writes the tests, ensures they are called by `stage_test.sh`, and ensures that if any of them fail, `stage_test.sh` will return a non-0 exit code. 

The developer must also ensure that the Dockerfile produces an environment with the necessary libraries and tooling to run those tests. Bind-mounting `$pr/infra/stage` directory is handled by `./bin/docex stagetest`.
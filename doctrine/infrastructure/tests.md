---
stratum: conditional
---

# Tests

This document describes the different kinds of automated tests which ship with a project, where they belong, and when they are supposed to be run.

## Codebase Tests

Codebase tests describe all unit tests and integration tests which cover a single **codebase** — its `tests/` tree, run by its `test.sh` inside its test-stage container. The tier is named for its scope, which is the codebase and not one of its core services: the test suite, like the artifact, is a property of the source tree, so one `test.sh` per codebase covers every core service that codebase declares. That scope is what distinguishes this tier from project-wide [staging tests](#staging-tests). When we perform tests in the `test` environment, we are running every codebase's tests.

These tests test the code itself - that functions behave correctly, modules within a codebase can communicate, etc. They *don't* test inter-core-service communication. They can, however, interact with a backing service for the purpose of testing a single codebase (required for some integration tests).

Codebase tests are written in whatever language, and with whatever tooling, is appropriate for the codebase. A codebase written in python would have tests also written in python and perhaps run with `pytest`.

Unit, integration, and contract tests should all be run by the [standard test script](./cicd.md#build-test-step)

The folder structure of codebase tests (and more details on how to write them) is described here: [hex_overview.md](../hexagonal_architecture/hex_overview.md#tests)

### Unit Tests
These are very fast tests which test a piece of code in isolation. Dependencies are mocked. The purpose is to determine if the unit's internal logic is correct.

### Integration Tests
These tests verify that multiple pieces work *together*. Tests might fire against real backing service containers (in a `test` env) rather than mocked ones.

#### Module-Level
Module-level integration tests verify that a single module behaves as expected.

#### Codebase-Level
Codebase-level integration tests (e.g. "flow" tests) verify that the entire codebase behaves as expected across all modules. These are often done "from outside", for example by applying real requests against codebase `api`'s core service `web`. The resulting test ensures that the "flow" of information across the codebase's modules and even core services behaves correctly as a hand-authored scenario plays out.

A flow test *enters* through one core service's driving adapter, but what it can *reach* is the whole codebase: every core service of a codebase is assembled by the same [composition root](../hexagonal_architecture/internal_dependency_rules.md#composition-root), so a scenario driven at the `web` edge may legitimately land in the handler that `worker` would normally host. It does so **in-process** — the queue hop between the two is elided. A flow test therefore proves the codebase's composed *behavior* while proving nothing about the transport between core services. Code reachability crosses core services; the wire between them does not, which is what reconciles this tier with "these tests don't test inter-core-service communication" above. That remaining gap is covered by contract tests below and by [staging tests](#staging-tests).

Flow tests can look similar to contract tests. A key distinction is in *purpose*. A contract test ensures the core service's external shape is consistent with the contract (e.g. that a JSON POST response has code 200 and `some_field`). A flow test ensures the codebase's *behavior* is correct (e.g. that the JSON POST response has the actual correct value for `some_field`) and that the expected effects occur as a result (e.g. the correct record is persisted as a result of the POST or the correct worker job ran). A schema-valid response can still be the wrong answer; that gap is what flow tests cover.

### Contract Tests
[On contracts](./infrastructure.md#contracts).

Contract tests ensure core service modularity. They check that a core service's surfaces are well-defined, and ensure that consumers across those surfaces can expect the interior machinery to behave as defined by the contract. They don't literally test communications between multiple core services, but they do ensure that core services *will communicate correctly* in production.

Keep in mind that a codebase can have multiple core services and that a core service can have multiple surfaces. A contract test *tests* a single core service's surface. However, it *runs* in the codebase's [exec service](./specifics/exec_service.md).

A codebase declaring two core services (each declaring one surface) therefore has two contract files but one test suite, one `test.sh`, and one container. `api` declaring `api.web` (OpenAPI) and `api.worker` (AsyncAPI) verifies both contracts in a single `pytest` run inside `<project>-test-api-exec`.

A core service declaring two surfaces is the same story from the other direction: `api.web` declaring `rest` and `events` has two contract files, both verified in that one run. The count of contracts tracks surfaces; the count of test suites tracks codebases.

Good contract tests spare the developer from needing to write and maintain a bunch of complex and brittle end-to-end staging tests. Staging tests ideally test only *infrastructure* and shouldn't be burdened by concern over the application logic within a codebase.

The tricky thing about contract tests is that they can run on both sides of the contract. The provider side ensures that the provider reacts correctly to simulated contract-appropriate requests from "outside" the service. The consumer side ensures that the consumer acts and reacts correctly when working with a provider that is mocked in accordance with the contract.

This doctrine requires provider-side contract tests for core service surfaces, and encourages consumer-side contract tests for larger projects with many different core services.

#### Provider Side
- Runs in a one-off container of the provider's **codebase** exec service, built from that codebase's `test` Dockerfile stage — the same container every other test in that codebase's suite runs in.
- Test starts the provider's server *inside* that container. It does not call the core service's own long-running container in the `test` stack: schema-fuzzing tools generate large volumes of traffic, and aiming that at a shared container makes the suite order-dependent and pollutes state other tests rely on.
- A schema-validation tool (e.g., schemathesis for OpenAPI) hits the real running endpoints.
- Verifies that actual responses conform to what the surface's contract declares.
- Invoked by the codebase's `test.sh`.

#### Consumer Side
- Runs in a one-off container of the consumer's **codebase** exec service, as above.
- A mock server is generated from the provider's contract - either via a separate container (Prism, AsyncAPI mock) or as an in-process mock library (e.g., httpx_mock for Python clients).
- Consumer's tests hit the mock instead of the real backend.
- Verifies consumer can work against any contract-conformant provider.
- Invoked by the codebase's `test.sh`.

The consumer side is codebase-scoped in a second sense as well. It exercises a driven gateway adapter, and that adapter is shared by every core service the codebase declares — so two core services consuming the same provider want *one* consumer-side test, not two, even though [`uses`](./cicl.md#uses-relationships) is declared per core service.

Where a provider declares more than one surface, [`uses`](./cicl.md#uses-relationships) does not say which one a consumer depends on. In practice the consumer's gateway adapter makes it obvious, and the mock is generated from that surface's contract. If a project finds this genuinely ambiguous, that is the signal the two surfaces should have been two core services.

The consumer side is *especially* tricky because it can require spinning up a separate container. If this is done, it should be done as a subcontainer *within* the codebase's exec container. That way it does not become an infrastructural concern.

## Staging Tests

Staging tests verify that a deployed release functions correctly on its infrastructure. They catch problems that codebase tests can not because codebase tests run isolated within a singular codebase. 

Staging tests assert what can only be seen **from outside** the deployed stack. They should at least perform the following:
+ TLS / DNS - Can requests reach the [reverse proxy](./shape.md#general)?
+ Critical-path smoke-tests - one or two end-to-end smoke tests that span the system. These should be sufficient to ensure:
	1. Secrets and environmental variables are wired up properly.
	2. Services can actually reach each other over the network.

**Liveness is not among them.** Before the stage tester is even built, `./bin/docex stagetest` reads every core service's health and version from the orchestrator — `docker inspect` on `fixed`, `describe_tasks` on `elastic` — and fails there if anything is unhealthy or running the wrong version. See [healthchecks.md](./healthchecks.md). A staging test therefore never probes a service to find out whether it is alive, and never reaches a non-`web` core service at all: a scenario that must exercise a worker drives the public edge and observes the effect.

Staging tests are run per-project, not per-codebase. They are run *by* the project-wide `$pr/infra/stage/stage_test.sh` [stage test shim](./cicd.md#staging-tests) and are run *in* a special "test environment" image that is launched by the `./bin/docex stagetest` command and described by `$pr/infra/stage/Dockerfile`. The tests themselves are written by the developer and go in the `$pr/infra/stage/tests` folder.

While the `doctrine` describes these files, it is the project developer's responsibility to write and maintain them. The developer writes the tests, ensures they are called by `stage_test.sh`, and ensures that if any of them fail, `stage_test.sh` will return a non-0 exit code. 

The developer must also ensure that the Dockerfile produces an environment with the necessary libraries and tooling to run those tests. Bind-mounting `$pr/infra/stage` directory is handled by `./bin/docex stagetest`.

### Injected environment

`./bin/docex stagetest` injects a small set of doctrine-defined env vars into the stage tester container so the project's tests can stay free of values that have to be hand-synced on every release:

| Variable | Source | Purpose |
| -------- | ------ | ------- |
| `STAGING_URL` | derived from `infra.yml`'s `apex_domain` field and [domain rules](./cicl.md#domain) | The public URL of the deployed staging environment. Tests issue HTTPS calls against this. |
| `PROJECT_VERSION` | `project.yml` `version:` field | The version of the build under test. A test asserting that a `web` service's `/health` returns the expected version reads this rather than maintaining a hardcoded `EXPECTED_VERSION` that drifts on every release. This is the project's own assertion through the public edge; `docex` has already checked the deployed version against the orchestrator. |

The contract is one-way and stable: docex injects these on every `stagetest` run; the project's tests are free to read or ignore them. Adding new doctrine-injected variables is a doctrine change, not a project change.

The **codebase `test.sh`** receives injected variables on the same one-way,
stable footing:

| Variable | Source | Purpose |
| -------- | ------ | ------- |
| `DOCEX_TEST_SELECTOR` | the `[subset]` argument to `docex test` | An opaque, runner-native selector the shim forwards to its test runner to narrow the run to a subset of the suite. **Unset ⇒ run the whole suite** (the default). Set ⇒ the shim runs only the named tests. |
| `DOCEX_TEST_SLOT` | the current shard index under `docex test --slots N` | The **1-based** index (`1..N`) of this shard. Injected only when sharding (`N ≥ 2`). **Unset ⇒ not sharding ⇒ run the whole suite.** |
| `DOCEX_TEST_SLOTS` | the shard count `N` from `docex test --slots N` | The total number of shards. Together with `DOCEX_TEST_SLOT` it tells the shim to run only its `1/N` share of the suite. |

The shim decides how to forward `DOCEX_TEST_SELECTOR` in a way idiomatic to its
runner (a `pytest` shim splices it as an args fragment — a path and/or `-m`/`-k`
expression); the contract fixes only the variable and its meaning, never the runner.

`DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS` compose cleanly with `DOCEX_TEST_SELECTOR` —
a shim may be both subset-narrowed and sharded at once. docex **recommends but does
not mandate** a sharding pattern: it fixes only the two variables and their meaning,
and a project shards however is idiomatic to its runner (the reference shims ship a
deterministic modulo split over collected node-ids, so the union of the `N` shards
is exactly the whole suite).

Like the stage injections, this whole contract is one-way and stable — adding to it
(as parallel test sharding did, with `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS`) is a
doctrine change, not a project change.
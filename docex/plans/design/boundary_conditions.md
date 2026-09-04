# Intro and Goals

> **A note on shape.** These design docs do not look quite like a typical
> doctrine-adherent project's. The standard corpus (per
> [`doctrine/practices/docs.md`](../../../doctrine/practices/docs.md)) describes a
> multi-service, hexagonally-architectured project organized around core/backing
> services and inter-module flows. `docex` is a single-process tool that *executes*
> the doctrine against other projects; it has no backing services, no inter-service
> flows, and is not hexagonally-architectured. A doctrine-based product cannot
> structurally *produce* a tool like `docex`, so these docs only *resemble* the arc42
> corpus for ergonomics rather than complying with it — there is no per-codebase or
> per-module L3 layer, and `docex` maintains this corpus by hand (it has no
> `infra.yml`/`project.yml`, so the docex docs CLI cannot run against itself). See
> [`specifics/docex_process.md`](./specifics/docex_process.md) for the development
> process this design hangs off.

`docex` is the executor of the [doctrine](../../../doctrine/doctrine.md). It is a
single, versioned container image that bundles every deterministic doctrine-shipped
tool — the [CICL](../../../doctrine/infrastructure/cicl.md) compiler, the
[transfer tables](../../../doctrine/infrastructure/specifics/transfer_tables.md), the
CI/CD orchestration ([cicd.md](../../../doctrine/infrastructure/cicd.md)), the
foundation-specific release machinery
([release.md](../../../doctrine/infrastructure/specifics/release.md)), and the elastic
state-backend bootstrap
([elastic_state_backend.md](../../../doctrine/infrastructure/specifics/projinfra/elastic_state_backend.md)) —
behind one cohesive command-line surface. Each project pins one `docex` version, ships
one `./bin/docex` shim, and never carries doctrine source code in its own repository.

The name is intentional: `docex` is *not* the doctrine. The doctrine is the body of
rules and principles; `docex` is what executes those rules deterministically against a
project.

## Requirements

1. **Zero infra burden on the developer.** Setting up a new project should not require
   installing OpenTofu, Ansible, the AWS CLI, OpenAPI tooling, or writing
   docker-compose by hand. Everything deterministic lives in the image.
2. **Determinism.** A project pinned to `docex:1.2.3` produces identical infrastructure
   outputs forever, regardless of when or where it runs.
3. **Coherence.** All doctrine-shipped tooling evolves in lockstep behind a single
   version pin. No drift between the CICL compiler, the transfer tables, the
   containerize step, and the release flow.
4. **Reproducibility without machine state.** Clone the project, install Docker, run
   `./bin/docex compile`. Nothing else.
5. **Foundation parity.** The same set of commands works identically across `fixed` and
   `elastic` foundations. Foundation-specific behavior is hidden behind the command
   surface, not exposed to the developer.

# Constraints

- **Implementation language.** `docex` is written entirely in Python 3.12+.
  Single-codebase coherence beats a polyglot split between "compiler" and
  "orchestration". Where `docex` needs to invoke a CLI (docker, tofu, ansible, aws,
  git), it does so as a subprocess from Python — never by shelling into bash scripts
  that themselves shell into other CLIs.
- **Executor, not product.** `docex` is driven by the doctrine, which forms its product
  documentation. A doctrine change should always land first; `docex` then changes to
  match (see [`specifics/docex_process.md`](./specifics/docex_process.md)).
- **Single machine per env (for now).** Multi-machine `fixed` foundations are deferred;
  see Context and Scope below.

# Context and Scope

`docex` runs on the operator's development machine and acts on:
- the **project repository** it is invoked within (reads `project.yml`, `infra.yml`,
  secrets/config, codebase source; writes compiled output),
- the **host docker daemon** (over a mounted socket — see
  [`concepts_and_decisions.md § Docker-outside-of-Docker`](./concepts_and_decisions.md#docker-outside-of-docker)),
- **operator credentials and ambient host state** (`~/.aws`, `~/.docker`, `~/.ssh`,
  `~/.gitconfig`), and
- **external targets** — container registries, the AWS API (elastic), and SSH hosts
  (fixed).

The system-context picture is [`project_diagram.mmd`](./project_diagram.mmd).

## Out of Scope

These align with the
[Deferred section of infrastructure.md](../../../doctrine/infrastructure/infrastructure.md#deferred)
plus a few `docex`-specific items:

1. **Multi-machine fixed foundation.** Single host per env for now; multi-host (docker
   swarm or otherwise) waits on a future doctrine extension.
2. **Automated CI/CD triggers.** `docex` is invoked manually or by a thin CI runner that
   just shells out to it. PR-triggered pipelines, GitHub Actions wrappers, etc. are out
   of scope.
3. **Publishing the image to a public registry.** The image is built locally for now;
   cross-machine sharing (and a published registry) is deferred until needed — see
   [`concepts_and_decisions.md § Distribution`](./concepts_and_decisions.md#distribution).

# Quality Requirements

The Requirements above are also the project's quality goals, in priority order:
**determinism** and **coherence** are the load-bearing pair — a pinned `docex` version
must produce byte-stable outputs and evolve all bundled tooling in lockstep — followed
by **reproducibility without machine state**, **foundation parity**, and **zero infra
burden** on the developer. Every design decision downstream is measured against these;
where a mechanism exists chiefly to protect one of them, the rationale is captured in an
ADR (see [`adr_index.md`](./adr_index.md)).

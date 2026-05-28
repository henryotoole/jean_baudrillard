# `docex` — Design Proposal

`docex` is the executor of the [doctrine](../doctrine/overview.md). It is a single, versioned container image that bundles every deterministic doctrine-shipped tool — the [CICL](../doctrine/infrastructure/cicl.md) compiler, the [transfer tables](../doctrine/infrastructure/specifics/transfer_tables.md), the CI/CD orchestration ([cicd.md](../doctrine/infrastructure/cicd.md)), the foundation-specific release machinery ([release_mechanism.md](../doctrine/infrastructure/specifics/release_mechanism.md)), and the elastic state-backend bootstrap ([elastic_bootstrap.md](../doctrine/infrastructure/specifics/elastic_bootstrap.md)) — behind one cohesive command-line surface. Each project pins one `docex` version, ships one `./bin/docex` shim, and never carries doctrine source code in its own repository.

The name is intentional: `docex` is *not* the doctrine. The doctrine is the body of rules and principles; `docex` is what executes those rules deterministically against a project.

## Goals

1. **Zero infra burden on the developer.** Setting up a new project should not require installing OpenTofu, Ansible, the AWS CLI, OpenAPI tooling, or writing docker-compose by hand. Everything deterministic lives in the image.
2. **Determinism.** A project pinned to `docex:1.2.3` produces identical infrastructure outputs forever, regardless of when or where it runs.
3. **Coherence.** All doctrine-shipped tooling evolves in lockstep behind a single version pin. No drift between the CICL compiler, the transfer tables, the containerize step, and the release flow.
4. **Reproducibility without machine state.** Clone the project, install Docker, run `./bin/docex compile`. Nothing else.
5. **Foundation parity.** The same set of commands works identically across `fixed` and `elastic` foundations. Foundation-specific behavior is hidden behind the command surface, not exposed to the developer.

## Architecture

`docex` is delivered as **a container image + a project-local shim**.

```
┌─────────────────────────────────────────────────────────────────┐
│  Project repository                                             │
│  ├── project.yml          (pins docex_version: "1.2.3")         │
│  ├── infra/infra.yml      (CICL source)                         │
│  ├── infra/...            (output, secrets, deploy_creds, etc.) │
│  ├── core/...             (project code)                        │
│  └── bin/docex            (~10-line shim, checked into git)     │
└────────────────────┬────────────────────────────────────────────┘
                     │  reads version, builds mount set,
                     │  invokes docker run
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  docex container (ghcr.io/<org>/docex:1.2.3)                    │
│  - Python CLI (compiler + command dispatcher + orchestration)   │
│  - Bundled transfer tables (canonical)                          │
│  - CLI deps: docker, tofu, ansible, aws, git, jq                │
│  - Operates on /project (bind-mounted from host)                │
└────────┬──────────────────┬───────────────────────┬─────────────┘
         │ docker.sock      │ ~/.aws, ~/.docker     │ network egress
         ▼                  ▼                       ▼
   Host docker daemon   Operator credentials   Registries, AWS, SSH targets
```

### Distribution

- The image is built from the `docex/` subtree of the `jean_baudrillard` repo. For now, this happens **locally** on the developer's machine; the resulting image lives in the host's Docker image store and projects reference it from there. Publishing to a public registry is deferred until cross-machine sharing is needed.
- Tags are **patch-level only**: `docex:1.2.3`. No floating tags (`docex:1`, `docex:1.2`, `docex:latest`). Floating tags silently re-point on every release, which directly undermines doctrine's promise of deterministic execution.
- The base image is pinned **by digest** (`FROM python:3.12-slim@sha256:...`), not tag, to immunize old releases against upstream base-layer churn.

### The Shim

`./bin/docex` is a small bash script, checked into every project. Its responsibilities:

1. Read `docex_version` from `project.yml`.
2. Construct the `docker run` invocation with the full [mount set](#filesystem-surface):
   - `--rm` so containers don't accumulate
   - `-v "$PWD":/project` — project tree
   - `-v /var/run/docker.sock:/var/run/docker.sock` — [DooD](#docker-outside-of-docker)
   - `-v "$HOME/.docker/config.json":/root/.docker/config.json:ro` — registry auth
   - `-v "$HOME/.aws":/root/.aws:ro` — elastic foundation creds
   - `-v "$HOME/.gitconfig":/root/.gitconfig:ro` and `-v "$HOME/.ssh":/root/.ssh:ro` — git ops (`merge`, ephemeral worktree)
   - `-w /project` — working directory
3. Pass through all CLI args.

Mounts that don't exist on the host (e.g. `~/.aws` on a fixed-only developer's box) are skipped by the shim — docex will fail loudly inside the container if a missing mount is actually needed by the requested command.

The shim never changes between `docex` versions. The `docex_install.sh` script in the `jean_baudrillard` repo copies it into projects and writes the `docex_version` pin into their `project.yml`. The same script is used to upgrade a project from one `docex` version to another.

### Version Pinning

The single version pin lives in `project.yml`:

```yml
name: my-project
version: "0.4.2"
docex_version: "1.2.3"
```

When the shim runs, it reads this field and uses it as the image tag. Bumping `docex` for a project is a one-line PR.

## Subcommand Surface

The subcommand surface is the full set of commands defined in [docex.md](../doctrine/infrastructure/docex.md). Every command listed here is in scope for the design; [Implementation Order](#implementation-order) phases the actual build.

| Command | Foundation behavior | Reads | Writes / acts on |
| ------- | ------------------- | ----- | ---------------- |
| `compile` | both | `infra.yml`, transfer tables (bundled + project-local), `project.yml` | `infra/output/<env>/...`, `infra/secrets/example.env` |
| `describe [<env>] [--format <format>]` | both | `infra.yml`, transfer tables | stdout (DAG or LLM-JSON) |
| `why <resource>` | both | bundled doctrine excerpts | stdout |
| `bootstrap` | elastic only (no-op on fixed) | `project.yml`, AWS creds | AWS: S3 bucket + DynamoDB table for tofu state |
| `up <env>` | fixed envs only (`dev`/`test`) | `infra/output/<env>/docker-compose.yml`, `infra/secrets/<env>.env` | host docker (compose up; runs migrations after) |
| `down <env>` | fixed envs only | running compose stack | host docker (compose down; keeps named volumes) |
| `build [<svc>]` | dev iteration | running `dev` containers, `core/<svc>/{src,build.sh}` | `core/<svc>/dist/` via bind mount |
| `test` | fresh `test` env | full project | host docker (ephemeral test stack), exit code |
| `migrate <env>` | both | service images at current version, `infra/secrets/<env>.env` | target env's database(s) via `migrate.sh` |
| `check` | both | feature branch + origin/main | ephemeral git worktree, runs git/version/contract checks, build, test |
| `merge` | both | feature branch, `project.yml` | rebases onto main, tags `v<version>`, pushes both |
| `containerize` | both | clean `main` tip, `project.yml`, `infra.yml` | `docker buildx` per core service, tag, push to registry |
| `release <env>` | both, branches internally | `infra/output/<env>/`, `infra/secrets/<env>.env`, deploy creds | fixed: ansible over SSH; elastic: SSM push + `tofu apply` |
| `stagetest` | both | `infra/stage/{Dockerfile,stage_test.sh,tests/}`, deployed stage URL | ephemeral stage-tester container, exit code |

Each command's authoritative behavior lives in [docex.md](../doctrine/infrastructure/docex.md) and the cross-referenced specifics; this table is a navigation aid, not a re-spec.

### Cross-command orchestration

A few commands compose others rather than duplicate logic:

- `check` invokes `compile` (to verify it succeeds), `build` (via `docker build` during test), and `test`.
- `up` and `test` cause `docker build` to run as needed, which in turn runs each service's `build.sh` inside the `build` stage.
- `release` invokes `migrate` against the target env before applying new application state.
- The manual CI/CD chain — `docex merge && docex containerize && docex release stage && docex stagetest && docex release prod` — is a documented sequence, not a megacommand. Keeping it explicit preserves the doctrine's "developer can drive the pipeline by hand" property.

## What `docex` Bundles vs. What It Doesn't

**Bundled (lives in the image):**
- The Python CLI: command dispatcher, CICL compiler, all orchestration code.
- The canonical [transfer tables](../doctrine/infrastructure/specifics/transfer_tables.md) (`/opt/docex/tables/`).
- The Ansible playbook template used by fixed-foundation releases (rendered per project by `compile`).
- CLI dependencies: `docker`, `tofu`, `ansible`, `aws`, `git`, `jq`, plus the Python runtime.
- Doctrine prose excerpts that back `docex why`.

**Not bundled (lives in the project):**
- Per-service `build.sh`, `test.sh`, `migrate.sh` — bespoke per service and per language.
- Per-service `Dockerfile`s.
- Language runtimes and toolchains for project code — those live inside each service's image.
- Project-local transfer table extensions at `infra/transfer_tables/` (deep-merged with bundled tables at compile time).
- The stage-tester image definition at `infra/stage/Dockerfile` and the stage tests themselves.

**Principle:** `docex` orchestrates; per-service containers do language-specific work. The `docex` image never needs Node, Go, or a service-specific build environment — it just invokes `docker` and friends correctly.

## Filesystem Surface

Every path `docex` reads or writes inside `/project`. All paths are relative to the project root.

**Read:**
- `project.yml` — name, version, docex_version
- `infra/infra.yml` — CICL source
- `infra/transfer_tables/` (optional) — project-local table extensions
- `infra/contracts/<svc>.<fmt>.yml` — per-provider contracts (validated during `check`)
- `infra/secrets/<env>.env` — operator-maintained secret values
- `infra/deploy_creds/<env>` — SSH private key for fixed `release`
- `infra/stage/{Dockerfile, stage_test.sh, tests/}` — stage tester definition and tests
- `core/<svc>/{Dockerfile, build.sh, test.sh, migrate.sh, src/, migrations/, tests/}` — per-service source and shims
- `CHANGELOG.md` — referenced by `merge` for version-bump validation
- `.git/` — required by `check`, `merge`, and any command that needs commit identity

**Write:**
- `infra/output/<env>/...` — `compile` output (compose + ansible for fixed envs; HCL for elastic envs)
- `infra/secrets/example.env` — `compile` output, committed
- `core/<svc>/dist/` — `build` output (dev iteration only; formal builds keep artifacts inside `docker build`)
- Ephemeral git worktrees under `.docex/worktrees/` (or similar) — created and destroyed by `check`

**Conspicuously not touched by docex:** anything outside `/project`. The container is sandboxed to the project tree plus the explicitly-mounted credential paths.

## Foundation-Aware Behavior

Several commands branch internally on `foundation:` from `infra.yml`. The shim and command surface stay symmetric; the divergence is internal.

| Command | Fixed | Elastic |
| ------- | ----- | ------- |
| `bootstrap` | no-op | creates `<project>-tofu-state` S3 bucket + `<project>-tofu-locks` DynamoDB table (idempotent) |
| `compile` | emits `docker-compose.yml` per env, plus `playbook.yml` / `inventory.yml` / `ansible.cfg` for stage/prod | emits `main.tf` per env (stage/prod); `dev`/`test` still get compose |
| `containerize` | pushes to project-configured `container_registry` | pushes to project's auto-provisioned ECR (or override) |
| `release` | `ansible-playbook` over SSH using `infra/deploy_creds/<env>` | SSM push → `RunTask` migration → `tofu apply` |
| `migrate` (during release) | one-off container in the existing internal docker network on the host | ECS `RunTask` against the migration task definition |

The `dev` and `test` environments are always fixed regardless of declared foundation, per [shape2.md § Shape and Environment](../doctrine/infrastructure/shape2.md#shape-and-environment).

## Credentials & Ambient Host State

`docex` consumes credentials and host state from well-known locations. It does **not** manage credential storage itself.

| Need | Source | Used by |
| ---- | ------ | ------- |
| Container registry push/pull | `~/.docker/config.json` | `containerize`, `release` (fixed pull side is the *target host*'s config, not the operator's) |
| AWS API access | `~/.aws/credentials` (or env vars / OIDC if present) | `bootstrap`, `release` (elastic), `containerize` (when ECR) |
| SSH to fixed-foundation hosts | `infra/deploy_creds/<env>` (private key) + `~/.ssh/known_hosts` | `release` (fixed) |
| Git identity & remote push | `~/.gitconfig`, `~/.ssh/` | `merge`, `check` (worktree creation) |
| Docker daemon | `/var/run/docker.sock` | every command that touches docker |

If a required credential is missing, `docex` fails loudly with a message pointing at the conventional location, never with a silent fallback.

## Docker-outside-of-Docker

`docex` needs to build, tag, push, and run containers on behalf of the project. It does this via the **DooD** pattern: the `docex` container runs the `docker` CLI, but the CLI talks to the **host's** docker daemon over a mounted socket. No nested daemon, no `--privileged`, no special VM tricks.

Two consequences worth being explicit about:

1. **Containers `docex` spawns are siblings, not children.** When `docex up dev` runs `docker compose up`, the resulting containers attach to the host's docker, not to docex. They outlive the docex invocation, which is exactly what we want — `docex up` returns immediately and the dev stack keeps running.
2. **Paths are host-relative for spawned containers.** When `docex` runs `docker compose -f infra/output/dev/docker-compose.yml up`, the compose file references project paths (e.g. bind-mounts for `src/` and `dist/`); those paths must resolve on the *host*, not inside docex. The shim addresses this by ensuring `/project` inside docex maps to `$PWD` outside, and by passing through any necessary host-path env vars (e.g. `COMPOSE_PROJECT_DIR`) so docker compose generates correct bind mounts. This is a subtle DooD pitfall; the implementation must get it right and have tests for it.

DinD is rejected as slower, more dangerous (requires `--privileged`), and unnecessary for our use case.

## Ephemeral Git Worktrees

`docex check` (and defensively, `docex merge`) needs to perform git operations against a merged state without disturbing the developer's working tree. The mechanism:

1. Create a temporary worktree under `.docex/worktrees/check-<sha>/` (gitignored by convention; the bootstrap adds the entry).
2. Inside the worktree, rebase the feature branch tip onto a fresh fetch of `origin/main`.
3. Run gate checks (working-tree-clean, version bumped, contracts aligned, etc.), then `compile`, `build` (via `docker build`), and `test` against the worktree.
4. On success, the worktree is removed. On failure, the worktree is removed *and* a structured error report points at what failed; the developer's branch and main are untouched either way.

The worktree directory is namespaced (`.docex/`) so multiple in-flight `check` invocations don't collide, and so the developer never has to think about cleanup.

## Repository Structure

`docex` lives in `jean_baudrillard/docex/`:

```
jean_baudrillard/docex/
├── design_proposal.md       (this file)
├── change_process.md        (how docex itself is changed — read before editing docex)
├── CHANGELOG.md             (per-version change record; Keep a Changelog + SemVer)
├── src/
│   └── docex/               (Python package; CLI entrypoint + all subcommands)
│       ├── __main__.py      (argparse dispatcher)
│       ├── compile/         (CICL compiler)
│       ├── orchestrate/     (up, down, build, test, migrate, …)
│       ├── pipeline/        (check, merge, containerize, release, stagetest)
│       ├── bootstrap/       (elastic state-backend setup)
│       └── describe/        (describe + why)
├── tables/                  (canonical transfer tables, copied to /opt/docex/tables/)
├── ansible/                 (playbook template rendered by compile for fixed releases)
├── doctrine_excerpts/       (data feeding `docex why`)
├── Dockerfile
├── tests/
└── release/                 (publishing automation)
```

### Implementation language

`docex` is written entirely in Python 3.12+. Single-codebase coherence beats a polyglot split between "compiler" and "orchestration". Where docex needs to invoke a CLI (docker, tofu, ansible, aws, git), it does so as a subprocess from Python — never by shelling into bash scripts that themselves shell into other CLIs.

## Implementation Order

The full surface above is *design-complete* — every command's contract and foundation behavior is settled. What's left is to build it in an order that lets the doctrine become usable as early as possible. Each phase produces a docex that is end-to-end useful for a real project at the stated scope.

**Phase 1 — Static analysis & compile.** `compile`, `describe`, `why`. Implements the CICL compiler, transfer table loading + project-local merging, and the descriptive surface. After this phase, a project can author `infra.yml` and inspect what it would produce.

**Phase 2 — Fixed dev loop.** `up`, `down`, `build`, `test`, `migrate`. After this phase, a developer can iterate locally end-to-end on a fixed foundation: bring up a stack, edit code, rebuild artifacts, run tests, apply migrations. This is the minimum useful surface for active development.

**Phase 3 — Fixed CI/CD.** `check`, `merge`, `containerize`, `release` (fixed branch only), `stagetest`. After this phase, a project with a fixed foundation can be released end-to-end.

**Phase 4 — Elastic.** `bootstrap`, `release` (elastic branch). After this phase, elastic-foundation projects are fully supported.

Phasing exists to sequence implementation, not to defer design. The image's command dispatcher should reject not-yet-implemented commands with `"<command> is part of <phase>; not yet implemented in this docex version"`, never with a generic "unknown command" error. This makes the version compatibility surface visible to users on day one.

## Maintenance & Long-Term Risk

### Edge cases in projects

Rigidity is the doctrine's promise; total flexibility would undermine it. Three layers of escape hatch, in order of preference:

1. **Project-local transfer tables.** `infra/transfer_tables/` is deep-merged with the bundled tables at compile time. This is the primary valve for project-specific quirks — adding an engine, overriding a default, declaring a new role.
2. **Upstream the fix.** If a project hits a genuine doctrine gap, the right answer is usually to fix it in `docex` itself, cut a new version, and let other projects benefit.
3. **Fork and pin.** A project that genuinely needs different compiler or orchestration behavior can fork the image, build their own, and pin to that. Painful by design — friction forces honest answers to "is my project really that special?"

### Upstream tool drift

The container model is the doctrine's friend here. `docex:1.2.3` bakes in specific versions of `tofu`, `ansible`, the docker CLI, the AWS CLI, and the Python runtime — even if any of those releases a breaking change tomorrow, projects pinned to `1.2.3` keep working. The doctrine maintainer absorbs the work of testing new upstream versions and cutting new `docex` releases; downstream projects opt in at their own pace.

**Real risks to plan for:**
- **Base layer rot:** mitigated by pinning the base image by digest and (optionally) mirroring published images to a registry under our own control.
- **Catastrophic upstream changes:** unlikely for OpenTofu (Linux Foundation) or Ansible (Red Hat), but if either happened, the doctrine would need a new backend. Existing projects on old `docex` versions are unaffected; they keep working.
- **AWS API churn:** the elastic foundation depends on the AWS API surface for SSM, ECS, S3, DynamoDB, ECR, RDS, etc. Breaking changes here would force a docex release; existing projects on old versions would need to upgrade only if they need to talk to a newly-changed API.

### Compatibility matrix

`docex` publishes an explicit compatibility matrix in the doctrine repo: which OpenTofu, Docker, Ansible, AWS CLI, and Python versions each `docex` minor supports. This makes the dependency surface visible, gives users a sane deprecation story, and lets old-version users know what they're locked into.

## Out of Scope (For This Proposal)

These align with the [Deferred section of infrastructure.md](../doctrine/infrastructure/infrastructure.md#deferred) plus a few proposal-specific items.

1. **Multi-machine fixed foundation.** Single host per env for now; multi-host (docker swarm or otherwise) waits on a future doctrine extension.
2. **Automated CI/CD triggers.** `docex` is invoked manually or by a thin CI runner that just shells out to it. PR-triggered pipelines, GitHub Actions wrappers, etc. are out of scope.
3. **Fundamental stage tests.** Stage test content is entirely the developer's responsibility. Doctrine-provided baseline stage tests (DNS, TLS, per-service health) are a future addition.
4. **Observability.** Logging servers, metrics, error tracking. Highest-priority future addition but not in this version.
5. **Rollback.** `docex rollback` is anticipated but not yet specified.
6. **Public image hosting.** `docex` images are built locally and consumed from the local Docker store. Hosting on a public registry — and the per-provider auth that implies — is deferred until multi-machine teams need it.
7. **Externally-rotated secrets.** All secrets are project-controlled and clobbered on each release; AWS-managed RDS rotation and friends are deferred per [release_mechanism.md § Caveats](../doctrine/infrastructure/specifics/release_mechanism.md#caveats).
8. **The full CICL spec.** Covered in [cicl.md](../doctrine/infrastructure/cicl.md) and [transfer_tables.md](../doctrine/infrastructure/specifics/transfer_tables.md); not duplicated here.
9. **Hexagonal architecture concerns.** Separate doctrine track; orthogonal to `docex`.

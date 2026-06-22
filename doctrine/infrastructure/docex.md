---
stratum: conditional
---

# `docex` Overview

`docex` is the executor of the [doctrine](../doctrine.md). It is a single, versioned container image that bundles all deterministic doctrine-shipped tooling - the [CICL](./cicl.md) compiler, [CI/CD](./cicd.md) actions, and any future glue - into one cohesive command-line surface. Each project pins one `docex` version, gets one `./bin/docex` shim, and never carries doctrine source code in its own repository.

This file clearly documents all `docex` usage and commands for two purposes:
1. To act as the source of truth for the development of the `docex` project itself.
2. To provide the developer with a clear understanding of how to use `docex` during development and release.

## Project Installation

`docex` is installed into a project by the doctrine-side `docex_install.sh` script. The project must already have a `project.yml` — produced by the [inception flow](../practices/inception.md), which handles all project-structure scaffolding. From the project root:

```bash
bash ~/.claude/jean_baudrillard/docex_install.sh .
```

The single argument is the target directory (use `.` when already at the project root). The script:
1. Copies the canonical shim to `./bin/docex` and makes it executable.
2. Writes the currently-shipped `docex_version` into `project.yml`, replacing any prior pin.

Both writes are idempotent. Re-running the script is also the supported way to upgrade a project from one `docex` version to another — no other steps required.

The shim itself never changes between `docex` versions; the `docex_version` pin in `project.yml` is what selects which `docex` image the shim runs. After installation, verify with `./bin/docex --version`; this requires the pinned image to already exist in the host's Docker image store.

## Usage
Docex is run from the terminal e.g. `./bin/docex <command>`. Commands will perform a variety of tasks spanning the entire `doctrine`. It does so by providing a "command" for each task; `./bin/docex build` builds all core services, `./bin/docex check` performs CI gate checks. Some commands will call others as part of their execution (e.g. `build` is called as part of `check`).

## Provided Tools

| Command | Purpose |
| ------- | ------- |
| `compile` | Translate the `infra.yml` into foundational infra config for docker compose and OpenTofu. |
| `describe <env>` | Describe an environment's infrastructure for human or LLM consumption. |
| `why <resource>` | Describe *why* the `doctrine` handles an infrastructural resource the way that it does. |
| `roles` | List the available service roles, with short descriptions. |
| `role <name>` | Describe a role: engines, provided parts (magic-ref targets), env vars, and fields. |
| `preinfra <side>` | Checks that the necessary prerequisite infrastructure resources exist for this project to launch on the indicated infrastructure side |
| `projinfra <direction> <side>` | Idempotently controls project-tier infrastructure for a given side. |
| `envinfra <direction> <env>` | Bring up or tear down a fixed-foundation environment locally. |
| `build <core_service>` | Run `build.sh` for one or all core services. |
| `test` | Run build-time tests (unit, integration, contract) in a fresh `test` environment. |
| `migrate <env>` | Apply database migrations for each schema-owning core service in `<env>`. |
| `check` | Run the full CI/CD gate-check sequence in an ephemeral worktree. |
| `merge` | Rebase the feature branch onto main, tag the release commit, and push. |
| `containerize` | Build and push core service prod images to the container registry. |
| `release <env>` | Deploy the containerized build to `<env>` (`stage` or `prod`). |
| `stagetest` | Run staging tests against the deployed staging environment. |
| `rollback <env> <target_version>` | Roll a deployed environment back to a prior version. |

### `compile`
`./bin/docex compile`
Compile takes the infrastructure definition at `infra.yml` and translates it to configuration files which can be used to drive `fixed` (docker compose config) or `elastic` (HCL files) infrastructure. Everything needed to perform this translation is either set by the project in [`infra.yml`](./cicl.md#the-cicl-format) or defined by the `doctrine` in [shape](./shape.md) and [transfer tables](./cicl.md#cicl-transfer-tables).

The output of this command is stored in `$pr/infra/output/${env}` on the basis of environment. All environments are compiled and placed in output every time.

### `describe`
`./bin/docex describe` to simply describe the production environment in DAG format.
`./bin/docex describe <env>` to describe a specific environment in DAG format.
`./bin/docex describe <env> --format <format>` to describe a specific environment in a specific format.
Describes the project infrastructure shape across all three [tiers](./infrastructure.md#infrastructure-tiers) of infrastructure for a certain environment. This is purely illustrative - the purpose of this command is to show the developer the shape of infrastructure without requiring them to read config files.

The formats available are:
`dag` - Describe the infrastructure shape with a directional acyclic graph.
`llm` - Describe the infrastructure in JSON-form so that an LLM can easily parse it.

### `why`
`./bin/docex why <resource>`
Describes why we do a certain infrastructure resource the way we do in plain language - pairs with describe.

### `roles`
`./bin/docex roles [--format text|llm]`
Lists every service role the transfer tables define, each with a short description. Pairs with `./bin/docex role <name>` for detail. The `llm` format emits JSON for tooling.

### `role`
`./bin/docex role <name> [--format text|llm]`
Describes one role: its engines (and foundations), the **provided parts** that magic refs target (`${backing_services.<svc>.<part>}`), which parts are secrets, the required `infra/secrets/<env>.env` variables, and the role-specific fields settable in `infra.yml`. This is the canonical way to discover what a magic ref can reference, since the parts live in the transfer tables rather than the doctrine prose. The `llm` format emits JSON.

### `preinfra`
`./bin/docex preinfra <side>`
Checks that the necessary prerequisite infrastructure resources exist for this project to launch on the indicated infrastructure side. Side can be "development" or "production"; "development" will select necessary development-side infrastructure for the project's foundation and "production" will select necessary production-side infrastructure.

For example, one preinfra resource needed for the `development` side is the [HAProxy web demux](./shape.md#fixed-foundation) on the development machine, whether `fixed` or `elastic`. Production-adjacent environments have their own requirements, like the master VPC for `elastic` or the "observability backend" for both.

Command does not fix or create preinfra. It only checks status.

### `projinfra`
`./bin/docex projinfra <direction> <side>`
Idempotently controls project-tier infrastructure. Direction can be "up" or "down"; "up" will construct required infrastructure and "down" will remove. Side can be "development" or "production"; "development" will select necessary development-side infrastructure for the project's foundation and "production" will select necessary production-side infrastructure.

**Elastic `down production`** tears down the project tier (Route53 zone, ACM/ALB or EC2-traefik, ECR, IAM, state backend) via `tofu destroy` plus cleanup of SSM parameters and the state backend (S3 bucket + DynamoDB lock table). It **refuses if any env-tier resources for the project still exist** (probed per env) — tear envs down first with `./bin/docex envinfra down <env>`. A pre-flight scan refuses-and-reports on project-tier blockers (e.g. a non-empty ECR repo) rather than force-destroying; the operator clears them and re-runs. Full retirement sequence: `envinfra down prod` → `envinfra down stage` → `projinfra down production`.

TODO write deeper specifics of behavior on `fixed` and `elastic`.
TODO remark on the two-step nature of `elastic` when NS delegation is required of the operator.

Command refuses to run with `direction="up"` if `./bin/docex preinfra <side>` fails.

### `envinfra` 
`./bin/docex envinfra up <env>` — `dev`/`test` only.
`./bin/docex envinfra down <env>` — any env.

**`up`** brings up a `dev` or `test` environment locally via docker-compose, using the compiled config at `$pr/infra/output/${env}/docker-compose.yml`. Docker rebuilds any out-of-date images as a prerequisite, so containers always have fresh artifacts (the image's `build` stage invokes `build.sh` — see [cicd.md § Build Step](./cicd.md#build-step)). Most commonly invoked as `./bin/docex envinfra up dev`. `up` is **not** valid for `stage`/`prod`: those are brought up by [`release`](#release) — an elastic env's ECS/RDS/etc. are created by the release `tofu apply`, which also requires a versioned build. Refuses with `direction="up"` if `./bin/docex preinfra development` fails.

**`down`** tears down env-tier infrastructure for **any** environment:
- `dev`/`test`, and `stage`/`prod` on **fixed**-foundation projects: stops and removes the compose stack's containers and networks; named volumes are preserved so persistent data survives the teardown.
- `stage`/`prod` on **elastic**-foundation projects: `tofu destroy` against the env's `infra/output/${env}/main.tf` (its ECS/RDS/SG/records). A **pre-flight scan refuses before destroying anything** if any env resource is deletion-protected (e.g. an RDS with `deletion_protection=true`), reporting the full list — `docex` never disables a protection itself; the operator does so deliberately and re-runs.

**The up/down asymmetry is intentional:** bringing an env *up* needs a versioned build (so `stage`/`prod` up is `release`'s job), but teardown is build-agnostic, so `down` is uniform across all envs. See [projinfra/projinfra.md](./specifics/projinfra/projinfra.md) for the teardown ordering (envs down before `projinfra down production`).

### `build`
`./bin/docex build` to refresh `dist/` for all core services in the running dev environment.
`./bin/docex build <core_service_name>` to refresh a specific core service.

Runs each core service's `build.sh` inside its running `dev`-stage container, depositing artifacts in `$pr/core/<service>/dist/` via bind-mount. The `dist/` folder is cleared before each run and verified non-empty afterward — if `build.sh` exits 0 but `dist/` is empty, the build fails with an error pointing at likely causes (misconfigured bind mount, wrong output path in `build.sh`).

**This command is for dev iteration only.** The canonical, ship-worthy build happens inside `docker build` during `./bin/docex containerize` (and during `./bin/docex envinfra up` and `./bin/docex test`, where Docker rebuilds images as needed and `build.sh` runs in the image's `build` stage). Direct invocation of `./bin/docex build` is useful when iterating on source against an already-running dev environment without paying for a container rebuild. See [cicd.md § Build Step](./cicd.md#build-step) for the full two-path model.

### `test`
`./bin/docex test`
Performs the CI/CD [build test step](./cicd.md#build-test-step). Brings up the `test` environment, runs each core service's `test.sh` inside its test-stage container, then tears the environment down. Covers unit, integration, and contract tests across the project. Docker rebuilds images as needed; `build.sh` runs inside each image's `build` stage so the test-stage container contains the same artifact a prod image would. Exits 0 if every service's tests pass; non-zero on the first failure.

### `check`
`./bin/docex check`
Runs the full CI/CD gate-check sequence: creates an ephemeral git worktree merging the current feature branch with the latest main, then runs git/version checks, `depends_on`-to-contract alignment checks, build, and the full test suite against the merged state. If any check fails, the worktree is discarded; main and the feature branch remain untouched. Used by developers locally before beginning CI and by CI runners as the PR gate. See [cicd.md](./cicd.md#check-step).

### `merge`
`./bin/docex merge`
Rebases the current feature branch onto the latest main, fast-forwards main, tags the new tip with `v<version>` from `project.yml`, and pushes both main and the new tag to origin. Re-runs gate checks defensively before merging to catch race conditions where main moved between `./bin/docex check` and `./bin/docex merge`. Refuses to merge if the working tree is dirty, the branch is not rebaseable, or any check fails. See [cicd.md](./cicd.md#merge).

### `containerize`
`./bin/docex containerize`
Formally containerizes the build for release: `docker buildx build --platform <target> --target prod` for each core service, tag each resulting image as `<container_registry>/<project_name>/<service_name>:<version>` (with `<container_registry>` from `infra.yml` and `<version>` from `project.yml`), and push to the registry. When an elastic project omits `container_registry`, the registry host is the project's default ECR (`<account>.dkr.ecr.us-east-1.amazonaws.com`); `containerize` resolves the account ID, authenticates to ECR, and ensures each service's repository exists before pushing. The `build` Dockerfile stage runs `build.sh` on the target platform as part of `docker build`, so the artifact embedded in each prod image always matches the production runtime regardless of host architecture. One image per core service; all share the project-wide version. Requires a clean working tree on `main` to ensure the resulting images correspond to a real, tagged commit. Image tags are 1:1 with `project.yml` versions — no floating tags. See [cicd.md](./cicd.md#containerize-step).

### `migrate`
`./bin/docex migrate <env>`
Applies database migrations for each schema-owning core service in `<env>`. For `dev` and `test`, runs `migrate.sh` inside each service's already-running container via `docker compose exec`. For `stage` and `prod` on fixed-foundation projects, runs the emitted Ansible playbook with `--tags migrate`, which spawns a one-off migrate container per schema owner on the target host using the current build image. For `stage` and `prod` on elastic-foundation projects, dispatches an ECS `RunTask` per schema owner against the migration task definition emitted by `compile`, polling each task to completion and aborting on the first non-zero container exit. Schema ownership comes from each backing service's `schema_owned_by` field; the command is a no-op when the project has no schema owners. Most of the time `migrate` runs implicitly — `envinfra up dev`, `test`, and `release` all invoke it at the appropriate point — but the command is available standalone for re-running a failed migration or for hand-driven flows. See [migrations.md](./specifics/migrations.md).

### `release`
`./bin/docex release <env>`
Releases the previously-containerized build to `<env>` (typically `stage` or `prod`). For fixed-foundation projects, runs the emitted Ansible playbook against the env's host(s) to pull the new image and reconcile the deployment. For elastic-foundation projects, pushes secrets from `infra/secrets/<env>.env` to SSM Parameter Store and then runs `tofu apply` against the env's HCL. Both paths are push-initiated and idempotent — re-running on an already-converged target is a no-op. See [release.md](./specifics/release.md).

### `stagetest`
`./bin/docex stagetest`
Runs the project's staging tests against the deployed staging environment via HTTPS, from outside the env. Spawns an ephemeral container from the project's `$pr/infra/stage/Dockerfile` definition, bind-mounts the project root to `/project`, injects `STAGING_URL` and `PROJECT_VERSION`, and invokes `/project/infra/stage/stage_test.sh` over the host network. Tests cover deployment-shape concerns (DNS, TLS, network reachability), per-service liveness, and critical-path smoke flows. Inter-service interaction concerns are intentionally not covered here — those are caught at build-test time via contract tests. See [cicd.md](./cicd.md#staging-tests).

### `rollback`
`./bin/docex rollback <env> <target_version>`
Rolls `<env>` (`stage` or `prod`) back to a prior `<target_version>` in emergency situations where a recent release has surfaced a serious problem. Resolves the `v<target_version>` git tag in an ephemeral worktree, recompiles that version's `infra.yml` using the current `docex`, and applies the recompiled output via the standard release machinery with the migrate step skipped. Code-only by design — the database schema is not reversed; the rolled-back code is expected to be backward-compatible with the current schema per the [backward-compatibility requirement](./specifics/migrations.md#backward-compatibility-requirement). Rejects targets more than one minor version behind `project.yml`'s current version and targets whose images are missing from the registry. The operator's working tree, `project.yml`, and `main` are untouched; the natural recovery path is a fix-forward release through the normal pipeline. See [cicd.md](./cicd.md#rollback).
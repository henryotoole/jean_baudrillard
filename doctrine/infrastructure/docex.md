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

The shim is **version-independent** — one shim serves every `docex` version, and the `docex_version` pin in `project.yml` is what selects which `docex` image it runs. Changes to the shim are kept **additive and backward-compatible** (an image of any version tolerates a newer shim), so it is not pinned per version; a project adopts an updated shim simply by re-running `docex_install.sh`. After installation, verify with `./bin/docex --version`; this requires the pinned image to already exist in the host's Docker image store.

## Usage
Docex is run from the terminal e.g. `./bin/docex <command>`. Commands will perform a variety of tasks spanning the entire `doctrine`. Docex does so by providing a "command" for each task; `./bin/docex build` builds all codebases, `./bin/docex check` performs CI gate checks. Some commands will call others as part of their execution (e.g. `build` is called as part of `check`).

All commands by default run synchronously and block until they complete and return an exit code. Additionally, certain long-running commands can be run with the `--detach` flag, which keeps the command running as a durable job in an independent, temporary container.

### Synchronous Usage

Simply run the command plain e.g. `./bin/docex <command>`. An exit code is returned when the command's task is complete.

Note that the detachable commands *behave* synchronously when run without `--detach`, but still leverage a detached container to run in. Killing a detachable command (e.g. with CTRL+C) does not kill the container.

### Asynchronous Usage

Run a valid command in detached mode by passing the `--detach` flag e.g. `./bin/docex test --detach`. The command will return a handle that can be used to query the job's status once it starts.

Wait for the job to complete by running `./bin/docex job wait <handle>` in the background. <CHECK> Did I write this correctly? </CHECK>. Check the output of a job with `./bin/docex job logs <handle>`.

If you lose the handle, you can rediscover it with `./bin/docex job ls`.

Under the hood, detaching is achieved by spinning up a deterministically named container (the "vessel") that actually runs the process. `docex` keeps track of these jobs via an on-disk record stored in `$pr/.docex/runs/<id>`. The full mechanics — vessels, run records, the deterministic-name lock, and the preflight reaper — are discussed in [detachable.md](./specifics/detachable.md).

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
| `secrets <op> <env> [...]` | Manage an environment's secrets file without exposing secret values to the caller. |
| `config <op> <env> [...]` | Manage an environment's non-secret config file. |
| `build <codebase>` | Run `build.sh` for one or all codebases. |
| `test [subset]` | Run build-time tests (unit, integration, contract) in a fresh `test` environment. A [durable job](#asynchronous-usage); `--detach` returns a handle. `test [subset]` narrows the run; `--slots N` shards it. |
| `job <op> [<handle>]` | Operate on durable run handles: `ls`, `status`, `wait`, `logs`, `result`. |
| `migrate <env>` | Apply database migrations for each schema-owning codebase in `<env>`. |
| `check` | Run the full CI/CD gate-check sequence in an ephemeral worktree. A [durable job](#asynchronous-usage); `--detach` returns a handle instead of blocking. |
| `merge` | Rebase the feature branch onto main, tag the release commit, and push. A [durable job](#asynchronous-usage); `--detach` returns a handle instead of blocking. |
| `containerize` | Build and push codebase prod images to the container registry. |
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
`dag` - Describe the infrastructure shape with a directed graph. It renders the [`uses`](./cicl.md#uses-relationships) relation with the edge kind distinguished by **target kind**: solid to a backing service, dashed to a core service. The graph is *directed*, not acyclic — `uses` may legally contain cycles among core services, so the rendered graph may too; the backing-targeted edges alone are acyclic, since a backing service is a sink. Node ids use the dotted reference form (`api.web`).
`llm` - Describe the infrastructure in JSON-form so that an LLM can easily parse it.

### `why`
`./bin/docex why <resource>`
Describes why we do a certain infrastructure resource the way we do in plain language - pairs with describe.

### `roles`
`./bin/docex roles [--format text|llm]`
Lists every service role the transfer tables define, each with a short description. Pairs with `./bin/docex role <name>` for detail. The `llm` format emits JSON for tooling.

### `role`
`./bin/docex role <name> [--format text|llm]`
Describes one role: its engines (and foundations), the **provided parts** that magic refs target (`${backing_services.<svc>.<part>}` for a backing role, `${codebases.<cb>.core_services.<svc>.<part>}` for a core one), which parts are secrets, the required `infra/secrets/<env>.env` variables, and the role-specific fields settable in `infra.yml`. This is the canonical way to discover what a magic ref can reference, since the parts live in the transfer tables rather than the doctrine prose. The `llm` format emits JSON.

### `preinfra`
`./bin/docex preinfra <side>`
Checks that the necessary prerequisite infrastructure resources exist for this project to launch on the indicated infrastructure side. Side can be "development" or "production"; "development" will select necessary development-side infrastructure for the project's foundation and "production" will select necessary production-side infrastructure.

For example, one preinfra resource needed for the `development` side is the [`docex-ingress` bridge](./preinfra/fixed_master_network.md#the-docex-ingress-network) on the development machine, whether `fixed` or `elastic`. Production-adjacent environments have their own requirements, like the master VPC for `elastic` or the "observability backend" for both.

The `development` side additionally verifies that every `dev` `web`-network hostname resolves in public DNS — one per `web` [core service](./cicl.md#core-services), plus any `web`-network backing service, plus the bare-env host when `domain_default_service` is set. Bringing `dev` up issues per-host Let's Encrypt certs via HTTP-01; if the hostnames don't resolve, every challenge fails and trips LE's failed-authorization rate limit (which then blocks legitimate issuance). Failing the check here — before `envinfra up dev` — surfaces missing dev DNS as an actionable preinfra gap instead of a rate-limit lockout. The operator routes `dev` DNS per [inception.md PART III](../practices/inception.md); `test` is excluded since it is not accessed over TLS.

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

### `secrets`
`./bin/docex secrets scaffold <env>`
`./bin/docex secrets status <env> [--format json] [--fingerprint]`
`./bin/docex secrets set <env> <KEY>`
`./bin/docex secrets copy <src_env> <tgt_env> <KEY>`
`./bin/docex secrets fingerprints [--format json]`

Manages the per-environment secrets file `$pr/infra/secrets/<env>.env` without ever exposing secret **values** to the caller — the tooling that lets an LLM agent drive secret handling while remaining structurally unable to read a value. The full model (the three configurable-value categories, the standard file form, aggregation) lives in [config_and_secrets.md](./specifics/config_and_secrets.md); this is the command surface.

- **`scaffold`** reconciles the file's key set against the deterministic set derived from `infra.yml` + doctrine (codebase `secrets:` blocks, backing engines' `kind: secret` env vars, doctrine-injected keys): it adds every required key (empty), removes stale ones, and preserves existing values. Idempotent.
- **`status`** is a redacted read — per key it reports `SET`/`UNSET`, the declaring codebase, and the description, **never the value**. `--format json` yields a machine-readable shape for detecting "required but never set." There is deliberately **no** value-printing command; a value leaves the file only at [materialization](./specifics/config_and_secrets.md#materialization-at-release).
- **`set`** writes one key. Its value channel is a **no-echo tty prompt** or `--from-file <path>`, **never a positional argument** — so the agent invokes the command while the human supplies the value, which never transits the agent's context.
- **`copy`** copies one key's value between environments **without surfacing it** (no value channel at all). Secrets and config only — **never TTE** (minted per env). A same-side copy (`dev`↔`test`, `stage`↔`prod`) is the intended use; a cross-side copy warns; an unset source errors; the target is overwritten.
 - **`fingerprints`** prints a cross-env matrix of non-revealing value fingerprints. One row per key, one column per env. Lets values be compared without literally seeing them.

All operate on the local `<env>.env` — secrets are `<env>.env`-canonical on every foundation, so none reach out to SSM or a host.

### `config`
`./bin/docex config scaffold <env>`
`./bin/docex config status <env> [--format json]`
`./bin/docex config set <env> <KEY> [<value>]`
`./bin/docex config get <env> <KEY>`
`./bin/docex config copy <src_env> <tgt_env> <KEY>`

Manages the per-environment config file `$pr/infra/config/<env>.env` — declared, **non-secret**, per-env values (e.g. a URL that differs by environment). Same command shape as [`secrets`](#secrets), but with the permission asymmetry inverted, because config values are not secret: this asymmetry *is* the secret/config category boundary made operational. The full model lives in [config_and_secrets.md](./specifics/config_and_secrets.md); this is the command surface.

- **`scaffold`** reconciles the file's key set against the keys declared in each codebase's `config:` block (adds missing empty, removes stale, preserves values). Idempotent.
- **`status`** shows each key's `SET`/`UNSET` state, source, description, **and — unlike `secrets` — its value** (`--format json` includes the value too). Config is not secret, so surfacing it is fine.
- **`set`** writes one key. It accepts the value as a **positional argument** (as well as `--from-file` / a prompt) — an agent may write config from its own context, since the value isn't secret.
- **`get`** prints one key's value to stdout. There is deliberately no `secrets get`; `config get` exists precisely because config is readable.
- **`copy`** is identical to [`secrets copy`](#secrets) — value-blind env→env copy, secrets/config only (**never TTE**), same-side blessed / cross-side warns / unset-source errors / target overwritten — just lower-stakes for non-secret values.

### `build`
`./bin/docex build` to refresh `dist/` for all codebases in the `dev` environment.
`./bin/docex build <codebase_name>` to refresh a specific codebase.

Runs each codebase's `build.sh` in a one-off container of that codebase's [exec service](./specifics/exec_service.md) (`docker compose run --rm … ./build.sh`), depositing artifacts in `$pr/core/<codebase>/dist/` via bind-mount. One exec service per codebase, so there is no per-core-service container to choose between, and the dev stack need not be running. The `dist/` folder is cleared before each run and verified non-empty afterward — if `build.sh` exits 0 but `dist/` is empty, the build fails with an error pointing at likely causes (misconfigured bind mount, wrong output path in `build.sh`).

**This command is for dev iteration only.** The canonical, ship-worthy build happens inside `docker build` during `./bin/docex containerize` (and during `./bin/docex envinfra up` and `./bin/docex test`, where Docker rebuilds images as needed and `build.sh` runs in the image's `build` stage). Direct invocation of `./bin/docex build` is useful when iterating on source without paying for a container rebuild; because the exec service is profile-gated, it does not require the dev stack to be up. See [cicd.md § Build Step](./cicd.md#build-step) for the full two-path model.

### `test`
`./bin/docex test [subset] [--detach] [--slots N]`
Performs the CI/CD [build test step](./cicd.md#build-test-step). Brings up the `test` environment, migrates, runs each codebase's `test.sh` inside its test-stage container, then tears the environment down. Covers unit, integration, and contract tests across the project. Docker rebuilds images as needed; `build.sh` runs inside each image's `build` stage so the test-stage container contains the same artifact a prod image would. Exits 0 if every codebase's tests pass; non-zero on the first failure.

`test` is a **durable job** (see [Asynchronous Usage](#asynchronous-usage)) and can be `--detach`ed.

The `[subset]` optional arg indicates that the test run should be narrowed to a subset of the suite. However, `docex` merely forwards this to the project codebase's `test.sh` as `DOCEX_TEST_SELECTOR` (see
[tests.md](./tests.md#injected-environment)); it does not enforce usage. It is up to the project to actually wire this subset into the project test infrastructure.

`docex test --slots N` **shards** the whole suite across `N` fully-isolated `test` stacks on one host: every physical resource name carries a slot segment (`_s{k}`). Each slot's `test.sh` receives `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS` (see [tests.md](./tests.md#injected-environment)) and runs its `1/N` share. `--slots 1` (or omitting it) is identical to the plain `docex test` above. There is a hard limit of 8 slots max.

### `job`
`./bin/docex job ls`
`./bin/docex job status <handle>`
`./bin/docex job wait <handle> [--timeout <seconds>]`
`./bin/docex job logs <handle> [-f]`
`./bin/docex job result <handle>`

Operates on the durable run handles produced by a durable command (see [Asynchronous Usage](#asynchronous-usage)). A handle is a run id — a unique prefix, or the literal `latest`, resolves too.
- **`ls`** enumerates every run under `.docex/runs/` — id, kind, scope, state, start time, exit code — reconciling each record against its vessel's liveness. The durable, non-fragile way to rediscover a run whose monitor was lost.
- **`status`** prints one run's recorded status reconciled with vessel liveness.
- **`wait`** blocks until the run's authoritative `exit` file appears (optionally bounded by `--timeout`) and exits with its code — the re-attach path for a killed monitor.
- **`logs`** prints (or, with `-f`, follows) the run's captured output.
- **`result`** prints and exits with the run's authoritative exit code (a distinct non-zero if the run has not finished).

### `check`
`./bin/docex check [--detach]`
Runs the full CI/CD gate-check sequence: creates an ephemeral git worktree merging the current feature branch with the latest main, then runs git/version checks, surface-to-contract alignment checks, build, and the full test suite against the merged state. If any check fails, the worktree is discarded; main and the feature branch remain untouched. Used by developers locally before beginning CI and by CI runners as the PR gate.

A [durable job](#asynchronous-usage) (the suite is long): `--detach` returns the run handle immediately, and a killed monitor leaves the run **alive and re-attachable** via `docex job wait`. On a fully-green run, `check` records what it validated to `.docex/checks/` (the feature tip, the `origin/main` commit, the merged tree SHA, a timestamp, and the docex version); `merge` uses this record to skip a redundant defensive recheck. The record is written only on success and is gitignored. The vessel-reaper behavior and the reserved defensive slot (`CHECK_SLOT`, which closes the `--project-name` DB-volume collision) are covered in [detachable.md § `check`](./specifics/detachable.md#check).

Also see [cicd.md](./cicd.md#check-step).

### `merge`
`./bin/docex merge [--detach]`
Rebases the current feature branch onto the latest main, fast-forwards main, tags the new tip with `v<version>` from `project.yml`, and pushes both main and the new tag to origin. If git conditions have changed since the last green `check`, will re-run gate checks defensively before merging. Refuses to merge if the working tree is dirty, the branch is not rebaseable, or any check fails. 

A [durable job](#asynchronous-usage), same as `check`: `--detach` returns a handle, and a killed monitor leaves the run re-attachable via `docex job wait`. Two detachment specifics are particular to `merge` — a git-credential-passthrough caveat that makes `merge --detach` refuse up front, and the reserved `MERGE_SLOT` its in-process defensive check runs at — both covered in [detachable.md § `merge`](./specifics/detachable.md#merge).

Also see [cicd.md](./cicd.md#merge).

### `containerize`
`./bin/docex containerize`
Formally containerizes the build for release: `docker buildx build --platform <target> --target prod` for each codebase, tag each resulting image as `<container_registry>/<project_name>/<codebase_name>:<version>` (with `<container_registry>` from `infra.yml` and `<version>` from `project.yml`), and push to the registry. When an elastic project omits `container_registry`, the registry host is the project's default ECR (`<account>.dkr.ecr.us-east-1.amazonaws.com`); `containerize` resolves the account ID, authenticates to ECR, and ensures each codebase's repository exists before pushing. The `build` Dockerfile stage runs `build.sh` on the target platform as part of `docker build`, so the artifact embedded in each prod image always matches the production runtime regardless of host architecture. One image per codebase; all share the project-wide version. Requires a clean working tree on `main` to ensure the resulting images correspond to a real, tagged commit. Image tags are 1:1 with `project.yml` versions — no floating tags. See [cicd.md](./cicd.md#containerize-step).

### `migrate`
`./bin/docex migrate <env>`
Applies database migrations for each schema-owning codebase in `<env>`. For `dev` and `test`, runs `migrate.sh` as a one-off container of each schema-owning codebase's exec service via `docker compose run --rm`. For `stage` and `prod` on fixed-foundation projects, runs the emitted Ansible playbook with `--tags migrate`, which spawns a one-off migrate container per schema owner on the target host using the current build image. For `stage` and `prod` on elastic-foundation projects, dispatches an ECS `RunTask` per schema owner against the migration task definition emitted by `compile`, polling each task to completion and aborting on the first non-zero container exit. Schema ownership comes from each backing service's `schema_owned_by` field; the command is a no-op when the project has no schema owners. Most of the time `migrate` runs implicitly — `envinfra up dev`, `test`, and `release` all invoke it at the appropriate point — but the command is available standalone for re-running a failed migration or for hand-driven flows. See [migrations.md](./specifics/migrations.md).

### `release`
`./bin/docex release <env>`
Releases the previously-containerized build to `<env>` (typically `stage` or `prod`). For fixed-foundation projects, runs the emitted Ansible playbook against the env's host(s) to pull the new image and reconcile the deployment. For elastic-foundation projects, pushes aggregated configurable vars to SSM Parameter Store and then runs `tofu apply` against the env's HCL. Both paths are push-initiated and idempotent — re-running on an already-converged target is a no-op. See [release.md](./specifics/release.md).

### `stagetest`
`./bin/docex stagetest`
Runs the project's staging tests against the deployed staging environment via HTTPS, from outside the env. Spawns an ephemeral container from the project's `$pr/infra/stage/Dockerfile` definition, bind-mounts the project root to `/project`, injects `STAGING_URL` and `PROJECT_VERSION`, and invokes `/project/infra/stage/stage_test.sh` over the host network. Tests cover deployment-shape concerns (DNS, TLS, network reachability) and critical-path smoke flows. Before building the tester, the command reads every core service's health and version from the orchestrator and fails there if any is unhealthy or on the wrong version — liveness is asserted by `docex`, not by the project's tests. Inter-service interaction concerns are intentionally not covered here — those are caught at build-test time via contract tests. See [cicd.md](./cicd.md#staging-tests) and [healthchecks.md](./healthchecks.md).

### `rollback`
`./bin/docex rollback <env> <target_version>`
Rolls `<env>` (`stage` or `prod`) back to a prior `<target_version>` in emergency situations where a recent release has surfaced a serious problem. Resolves the `v<target_version>` git tag in an ephemeral worktree, recompiles that version's `infra.yml` using the current `docex`, and applies the recompiled output via the standard release machinery with the migrate step skipped. Code-only by design — the database schema is not reversed; the rolled-back code is expected to be backward-compatible with the current schema per the [backward-compatibility requirement](./specifics/migrations.md#backward-compatibility-requirement). Rejects targets more than one minor version behind `project.yml`'s current version and targets whose images are missing from the registry. The operator's working tree, `project.yml`, and `main` are untouched; the natural recovery path is a fix-forward release through the normal pipeline. See [cicd.md](./cicd.md#rollback).
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

## Command Lifecycle

Most `docex` commands are **synchronous**: they run, block, and exit with a status code. A few long-running commands are instead **durable jobs** — the work outlives the invoking call.

`docex test` is the first. It still **blocks and exits with the run's code by default** (the exit-code contract CI relies on is preserved), but the suite runs in a **detached, deterministically-named "vessel" container** that docex launches over the docker socket. Because the work lives in the vessel and not in the foreground call, a foreground monitor that is **killed does not kill the run** — the run stays alive and re-attachable.

Every durable job writes an **on-disk run record** under `.docex/runs/<id>/` (`meta.json`, `status.json`, an atomically-written `exit` file, and a `log`). The `exit` file is the **authoritative terminal signal**: it survives vessel teardown and a killed monitor, and is what `docex job result` and `docex job wait` read. This reuses the exit-file half of the liveness pattern that [`healthchecks.md § What the probe must actually check`](./healthchecks.md#what-the-probe-must-actually-check) and [`internal_dependency_rules.md § Entrypoints`](../hexagonal_architecture/internal_dependency_rules.md#entrypoints) (rule 6) fix for long-running loops; the tick/staleness half is deliberately **not** used here, because a finite suite differs from a perpetual loop.

Two additions make the durability usable:

- **`--detach`** on a durable command launches the vessel and returns the run **handle** immediately instead of blocking.
- **`docex job <verb> <handle>`** operates on a handle after the fact — `ls` / `status` / `wait` / `logs` / `result`. `job ls` is the durable, non-fragile way to **rediscover** an in-flight run: a killed or freshly-spawned agent recovers the handle here rather than via a `docker ps` / `pgrep` proxy.

Concurrency is bounded by the vessel's **deterministic name, which is the lock**: a second run against the same scope loses the `docker run --name` create race and **refuses** rather than contending over the shared stack. Each durable command has its **own per-command lock scope** — `test`, `check`, and `merge` runners are independent, so two `test`s (or two `check`s, or two `merge`s) refuse each other while a `check` alongside a `merge` is allowed. `docex test --slots N` does **not** change this: the `N` slot stacks are internal parallelism inside one `test` vessel, not `N` lock scopes, so a slots-`N` run and a plain `docex test` still refuse each other. The three commands that *can* co-occur (distinct locks) are kept name-disjoint by a **reserved slot band**: `test` uses slots `1..MAX_TEST_SLOTS`, while `check` and `merge` each run their defensive `test` stack at a reserved slot just above the band (`CHECK_SLOT` / `MERGE_SLOT`) — so a `check`, a `merge`, and a `docex test` all running at once never collide on an explicit `container_name:` or the DB volume `name:` (the closure of the `--project-name` collision; see [§ `check`](#check)). A vessel that was hard-killed leaves an orphaned record and a leaked resource; the next run's **preflight reaper** clears both (writing an authoritative `exit`, then reclaiming what that run owned) and proceeds. The `./bin/docex` shim is **unchanged** — the vessel is launched by docex itself over the socket, so no shim update is required.

`test`, `check`, and `merge` are all durable jobs. **One vessel kind serves every durable job — a detached sibling container.** There is no second vessel kind (a "host process" cannot be durable under docex's Docker-outside-of-Docker model: the foreground `docex` runs inside the `--rm` container the shim launched, so a child process spawned there dies with it when the call is killed, and an in-container docex can spawn only a *container* over the socket, never a bare host process). What varies by job **kind** is instead two things: the **body** the vessel runs (the suite for `test`; the gate/build/test sequence for `check`; the rebase/tag/push for `merge`), and the **resource the reaper reclaims** on orphan — a `test` run's throwaway compose stack (under `--slots N`, the **fleet** teardown: all `N` deterministic slot stacks the run leaked, `N` read from the run record), or a `check`/`merge` run's ephemeral [worktree](#check) and the throwaway build/test stack its defensive run brought up. The reaper never unwinds `merge`'s real git mutations (an interrupted rebase, a partial fast-forward/tag); those are left for the operator, as `merge` already specifies. One `test`-specific property follows from sharding: a slot whose integration shard **fails** is deliberately **left up** for debugging (the passing slots are torn down), and is reclaimed by the next run that touches that slot number — either its per-slot pre-up teardown or the fleet reaper — so a failed **higher-numbered** slot can persist across a subsequent **smaller-`N`** run until an `N ≥ k` run touches slot `k`, or the operator tears it down by hand. The `docex test unit` fast lane is the deliberate exception: a stackless unit run touches no shared infra, so it is a plain synchronous run — no vessel, no lock, no run record — not a durable job.

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
| `test` | Run build-time tests (unit, integration, contract) in a fresh `test` environment. A [durable job](#command-lifecycle); `--detach` returns a handle. `test unit [subset]` is a synchronous no-stack fast lane; `test integration [subset]` runs the stack-backed tier, optionally subset. |
| `job <op> [<handle>]` | Operate on durable run handles: `ls`, `status`, `wait`, `logs`, `result`. |
| `migrate <env>` | Apply database migrations for each schema-owning codebase in `<env>`. |
| `check` | Run the full CI/CD gate-check sequence in an ephemeral worktree. A [durable job](#command-lifecycle); `--detach` returns a handle instead of blocking. |
| `merge` | Rebase the feature branch onto main, tag the release commit, and push. A [durable job](#command-lifecycle); `--detach` returns a handle instead of blocking. |
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
`./bin/docex test`
`./bin/docex test --detach`
`./bin/docex test unit [subset]`
`./bin/docex test integration [subset]`
`./bin/docex test --slots N`
Performs the CI/CD [build test step](./cicd.md#build-test-step). Brings up the `test` environment, runs each codebase's `test_unit.sh` then each codebase's `test_integration.sh` inside its test-stage container, then tears the environment down. Covers the unit tier (no-infra) and the integration tier (stack-backed, including contract tests) across the project. Docker rebuilds images as needed; `build.sh` runs inside each image's `build` stage so the test-stage container contains the same artifact a prod image would. Exits 0 if every codebase's tests pass; non-zero on the first failure.

`test` is a **durable job** (see [Command Lifecycle](#command-lifecycle)): the suite runs in a detached, deterministically-named vessel container, so the blocking default preserves the exit-code contract while a killed foreground monitor leaves the run **alive and re-attachable** via `docex job wait`. `--detach` returns the run handle immediately instead of blocking. The vessel's deterministic name is a per-`(project, test)` lock — a second concurrent run **refuses** rather than contending — and a hard-killed run is **reaped** by the next invocation's preflight. `test` still runs both shims in the fresh `test` stack, exactly as above.

`test` has two **execution modes** beyond the full run. `docex test unit [subset]`
runs only the no-infra unit tier in a throwaway container with **no compose stack
brought up** — the fast inner loop for iterating on a failing unit test; it is a
plain **synchronous** run (seconds, no shared infra to contend over, so no lock
and no durable-job vessel — `--detach` does not apply). `docex test integration
[subset]` runs the stack-backed integration tier against a fresh `test` stack and
**is** a durable job, sharing `test`'s lock scope (a full `docex test` and a
`docex test integration` refuse each other — they contend over the same stack). An
optional `[subset]` narrows the run within the chosen tier; docex forwards it to
the codebase's test shim as `DOCEX_TEST_SELECTOR` (see
[tests.md § Injected environment](./tests.md#injected-environment)). Omitting the
subset runs the whole tier.

`docex test --slots N` **shards** the run across `N` fully-isolated `test` stacks
on one host: every physical resource name carries a slot segment (`_s{k}`) and the
web network is a per-slot bridge, so the `N` stacks coexist with no collision. The
**integration** tier is sharded across the slots — each slot's integration shim
receives `DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS` (see
[tests.md § Injected environment](./tests.md#injected-environment)) and runs its
`1/N` share — while the no-infra **unit** tier runs **once**. `--slots 1` (or
omitting it) is **byte-identical** to the plain `docex test` above. `N` is capped
at `MAX_TEST_SLOTS`; `docex test --slots N` with `N > MAX_TEST_SLOTS` is a **usage
error** — the `test` band is slots `1..MAX_TEST_SLOTS`, and `check` / `merge`
reserve the slots just above it for their defensive stacks (see [§ `check`](#check)).
The slot is a general compiler primitive (any fixed env can be instantiated into multiple isolated
slots — see [infrastructure.md § Environments](./infrastructure.md#environments)),
but the CLI exposes it **only for `test`**.

### `job`
`./bin/docex job ls`
`./bin/docex job status <handle>`
`./bin/docex job wait <handle> [--timeout <seconds>]`
`./bin/docex job logs <handle> [-f]`
`./bin/docex job result <handle>`

Operates on the durable run handles produced by a durable command (see [Command Lifecycle](#command-lifecycle)). A handle is a run id — a unique prefix, or the literal `latest`, resolves too.
- **`ls`** enumerates every run under `.docex/runs/` — id, kind, scope, state, start time, exit code — reconciling each record against its vessel's liveness. The durable, non-fragile way to rediscover a run whose monitor was lost.
- **`status`** prints one run's recorded status reconciled with vessel liveness.
- **`wait`** blocks until the run's authoritative `exit` file appears (optionally bounded by `--timeout`) and exits with its code — the re-attach path for a killed monitor.
- **`logs`** prints (or, with `-f`, follows) the run's captured output.
- **`result`** prints and exits with the run's authoritative exit code (a distinct non-zero if the run has not finished).

### `check`
`./bin/docex check`
`./bin/docex check --detach`
Runs the full CI/CD gate-check sequence: creates an ephemeral git worktree merging the current feature branch with the latest main, then runs git/version checks, surface-to-contract alignment checks, build, and the full test suite against the merged state. If any check fails, the worktree is discarded; main and the feature branch remain untouched. Used by developers locally before beginning CI and by CI runners as the PR gate. A [durable job](#command-lifecycle) (the suite is long): the blocking default preserves the exit-code contract while a killed foreground monitor leaves the run **alive and re-attachable** via `docex job wait`; `--detach` returns the run handle immediately. A hard-killed `check` vessel's ephemeral worktree and throwaway stack are reclaimed by the next run's preflight reaper. On a fully-green run, `check` records what it validated to `.docex/checks/` (the feature tip, the `origin/main` commit, the merged tree SHA, a timestamp, and the docex version); `merge` trusts that record to skip a redundant defensive recheck. The record is written only on success and is machine-local (gitignored). `check`'s defensive build + test compile and run the worktree's `test` env at a **reserved slot (`CHECK_SLOT`) above the `docex test --slots N` band**, so the throwaway stack's compiled physical names — especially the DB volume `name:` — are name-disjoint from any `docex test` run. **This closes the `--project-name` DB-volume collision:** Compose's `--project-name` does **not** namespace an explicit `container_name:` or a top-level volume `name:`, so two stacks compiling `test` at the same slot would collide on the DB volume; the slot segment (`_s{k}`) does namespace them, so a `check` running beside a `docex test` no longer shares a database volume. See [cicd.md](./cicd.md#check-step).

### `merge`
`./bin/docex merge`
`./bin/docex merge --detach`
Rebases the current feature branch onto the latest main, fast-forwards main, tags the new tip with `v<version>` from `project.yml`, and pushes both main and the new tag to origin. Re-runs gate checks defensively before merging to catch race conditions where main moved between `./bin/docex check` and `./bin/docex merge`. Refuses to merge if the working tree is dirty, the branch is not rebaseable, or any check fails. Before any of this, it preflights the remote with `git ls-remote origin` and exits non-zero in seconds if `origin` is unreachable or auth fails — without building an image or running a test (skipped when the repo has no `origin`). `merge` **trusts a recent green forward**: it skips its defensive recheck when `origin/main` and the feature tip are at the commits `check` last recorded in `.docex/checks/`, the working tree is clean, and the docex version matches — reusing the `git ls-remote` preflight to learn the trunk tip rather than fetching again. **Any** staleness (trunk or feature moved, dirty tree, a missing or unreadable record, a version mismatch) forces the full recheck; the record is a performance cache, never a correctness gate, so the safe default is always to run. A [durable job](#command-lifecycle), same as `check`: `--detach` returns a handle, and a killed monitor leaves the run re-attachable via `docex job wait`. **One caveat is specific to `merge`:** brokered git-credential passthrough (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`, see [credentials.md § Git Host Credentials](./credentials.md#git-host-credentials)) does **not** survive `--detach` or a killed monitor — the shim's host-side credential responder is scoped to the foreground call, so a detached vessel's later `push` cannot re-broker. `merge --detach` therefore **refuses up front** when passthrough is active; run `merge` attached (blocking), or use a static credential (SSH key / `gitconfig` / file-based token), which is cloned into the vessel and does survive. `merge`'s defensive check is an **in-process** call — it does **not** take the `check`-runner lock — so it can co-occur with a standalone `docex check`; it therefore runs at a **reserved `MERGE_SLOT`, distinct from `check`'s `CHECK_SLOT`**, keeping the two defensive stacks name-disjoint too. See [cicd.md](./cicd.md#merge).

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
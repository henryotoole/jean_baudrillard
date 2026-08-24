# `docex` — Masterplan

> **A note on shape.** This masterplan does not look quite like a typical
> doctrine-adherent masterplan. The standard masterplan (per
> [`doctrine/practices/docs.md`](../../../doctrine/practices/docs.md))
> describes a multi-service, hexagonally-architectured project organized
> around core/backing services and inter-module flows. `docex` is a
> single-process tool that *executes* the doctrine against other projects;
> it has no backing services, no inter-service flows, and is not
> hexagonally-architectured. The document below therefore reads more like
> a design proposal — goals, architecture, command surface, distribution
> model — because that is what a masterplan for `docex` actually is. See
> [`docex_process.md`](./docex_process.md) for the development process
> this masterplan hangs off, and why `docex`'s documentation layout
> deliberately diverges from the standard in other small ways.

`docex` is the executor of the [doctrine](../../../doctrine/doctrine.md). It is a single, versioned container image that bundles every deterministic doctrine-shipped tool — the [CICL](../../../doctrine/infrastructure/cicl.md) compiler, the [transfer tables](../../../doctrine/infrastructure/specifics/transfer_tables.md), the CI/CD orchestration ([cicd.md](../../../doctrine/infrastructure/cicd.md)), the foundation-specific release machinery ([release.md](../../../doctrine/infrastructure/specifics/release.md)), and the elastic state-backend bootstrap ([elastic_state_backend.md](../../../doctrine/infrastructure/specifics/projinfra/elastic_state_backend.md)) — behind one cohesive command-line surface. Each project pins one `docex` version, ships one `./bin/docex` shim, and never carries doctrine source code in its own repository.

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
│  - Project + HOME mirrored at their host paths inside container │
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
2. Construct the `docker run` invocation with the full [mount set](#filesystem-surface). Mounts mirror their host paths inside the container — the project root, the operator's HOME, and credential directories are visible at the same path the host sees them. This makes DooD path resolution agree in both directions: build contexts and bind-mount sources resolve consistently for compose's in-container client and the host's docker daemon (see [DooD](#docker-outside-of-docker)). Concrete flags:
   - `--rm` so containers don't accumulate.
   - `--user "$(id -u):$(id -g)"` so writes to the project tree land operator-owned on the host (not root) and so `git` doesn't trip on dubious-ownership.
   - `--group-add` for the host's docker-socket gid so the non-root in-container user can use `/var/run/docker.sock`.
   - `-t -i` allocated **only** when the caller has an interactive terminal (both stdin and stdout are ttys) — needed for `docex secrets set`'s no-echo prompt; skipped for piped/non-interactive runs (which must use `--from-file`). Additive and backward-compatible: an older image tolerates the extra `-it` (mod 084).
   - `-e "HOME=$HOME"` — mirror host HOME inside the container.
   - `-w "$PROJECT_ROOT"` — working directory matches the host's project path.
   - `-v "$PROJECT_ROOT:$PROJECT_ROOT"` — project tree at its host path.
   - `-v /etc/passwd:/etc/passwd:ro` and `-v /etc/group:/etc/group:ro` so `getpwuid()` resolves the running uid (ssh requires this).
   - `-v /var/run/docker.sock:/var/run/docker.sock` — DooD.
   - `-v "$HOME/.docker:$HOME/.docker"` — rw so docker CLI can write buildx state, credential cache, etc.
   - `-v "$HOME/.aws:$HOME/.aws:ro"` — elastic foundation creds.
   - `-v "$HOME/.gitconfig:$HOME/.gitconfig:ro"` and `-v "$HOME/.ssh:$HOME/.ssh:ro"` — git ops (`check`, `merge`).
   - `-v "$SSH_AUTH_SOCK:/ssh-agent.sock" -e "SSH_AUTH_SOCK=/ssh-agent.sock"` when an ssh-agent is present, so agent-only authentication setups work.
3. Pass through all CLI args.

Mounts that don't exist on the host (e.g. `~/.aws` on a fixed-only developer's box) are skipped by the shim — docex will fail loudly inside the container if a missing mount is actually needed by the requested command. `~/.docker` is the exception: the shim creates it on the host if missing so the in-container docker CLI always has a writable state dir.

**Host-resolved git credentials (opt-in).** The static credential mounts above cover git auth that is a *file* or an *agent key*. They cannot cover an environment whose git auth is brokered by a `credential.helper` that talks to host-local state (a helper binary, a socket) — that machinery does not exist inside the container. When the **environment** sets `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` (never the project repo), the shim forwards **each** in-container `git credential` request back out to the host's own `git credential fill` (git's own machinery, driving whatever helper the host has configured), so every in-container fetch/push mints a **fresh** short-lived credential rather than reusing one captured up front. This matters because brokered tokens are hard-capped at ~1h: a resolve-once copy could expire during a long command (e.g. `merge`, whose defensive `check` may run for minutes before its `push`), and in-container git cannot re-broker. The mechanism: the shim writes two tiny helper scripts into a mode-700 host temp dir at runtime (heredocs, not image subcommands) — a host-side `responder.py` that binds a Unix socket and pipes each request through `git credential fill`, and an in-container `forward.py` set as git's `credential.helper` (a transparent pipe over the socket; `store`/`erase` are no-ops since nothing is persisted). It starts the responder in the background, mounts the temp dir (socket + `forward.py`) into the container at its host path, and points in-container git at `forward.py` (resetting any inherited helper and forcing `useHttpPath=true`, so the repository **path** survives into the credential request and a path-scoped host helper — one that authorizes per repository — can serve it; the host-side `git credential fill` forces the same, so both gates agree by construction). So the cleanup actually runs, the shim **does not `exec`** when this is staged (an `exec` would replace the shell and the cleanup trap would never fire) — it runs docex as a child, then kills the responder and removes the dir afterward. Passthrough mode requires **`python3` on the host** for the responder (the container's python3 is always present); the path is scoped to `https` origins, fails open to the static behavior when nothing resolves, and is a complete no-op when the signal is unset. See [credentials.md § Git Host Credentials](../../../doctrine/infrastructure/credentials.md#git-host-credentials).

The shim is **version-independent** — one shim serves every `docex` version. Changes to it are kept **additive and backward-compatible** (an image of any version tolerates a newer shim), so it is not pinned per version. The `docex_install.sh` script in the `jean_baudrillard` repo copies it into projects and writes the `docex_version` pin into their `project.yml`. The same script is used to upgrade a project from one `docex` version to another, and to pick up an updated shim.

### Version Pinning

The single version pin lives in `project.yml`:

```yml
name: my-project
version: "0.4.2"
docex_version: "1.2.3"
```

When the shim runs, it reads this field and uses it as the image tag. Bumping `docex` for a project is a one-line PR.

## Subcommand Surface

The subcommand surface is the full set of commands defined in [docex.md](../../../doctrine/infrastructure/docex.md). Every command listed here is in scope for the design.

| Command | Foundation behavior | Reads | Writes / acts on |
| ------- | ------------------- | ----- | ---------------- |
| `compile` | both | `infra.yml`, transfer tables (bundled + project-local), `project.yml` | `infra/output/<env>/...` |
| `secrets <scaffold\|status\|set\|copy\|fingerprints> <env>` | both | `infra.yml` + transfer tables (via `secret_manifest`), `infra/secrets/<env>.env` | `infra/secrets/<env>.env` (value-blind: `set` reads a no-echo tty prompt or `--from-file`; `status` never prints a value; `status --fingerprint` / `fingerprints` show non-revealing value fingerprints for cross-env drift) |
| `config <scaffold\|status\|set\|get\|copy> <env>` | both | `infra.yml` + transfer tables (via `config_manifest`), `infra/config/<env>.env` | `infra/config/<env>.env` (values visible: `set` takes a positional value, `get`/`status` print them) |
| `describe [<env>] [--format <format>]` | both | `infra.yml`, transfer tables | stdout (DAG or LLM-JSON) |
| `why <resource>` | both | bundled doctrine excerpts | stdout |
| `roles [--format]` | both | bundled + project-local transfer tables | stdout (role list with descriptions) |
| `role <name> [--format]` | both | the named role's `tables/roles/<name>.yml` | stdout (engines, provided parts, env vars, fields) |
| `preinfra <side>` | both, branches internally | `project.yml`, `infra.yml`; docker daemon, DNS; AWS (elastic + production), SSH (fixed + production), the container registry + `~/.docker/config.json` (fixed + development) | nothing — read-only probe of prerequisite infrastructure; exit code, plus a `Declined` block for questions it will not answer (see below) |
| `projinfra <direction> <side>` | both, branches internally | `project.yml`, `infra.yml`, `infra/output/project/<side>/` | fixed: project-tier compose stack (four `-web` networks + per-project traefik); elastic `up production`: runs `preinfra` as a gate, then the state-backend setup (S3 bucket + DynamoDB table for tofu state), then the two-phase project-tier `tofu apply` — phase 1 the Route53 hosted zone alone so the operator can NS-delegate, phase 2 the full project tier; both idempotent |
| `envinfra <direction> <env>` | fixed envs for `up` (`dev`/`test` only); `down` covers all envs | `infra/output/<env>/docker-compose.yml`, and the whole aggregate at bring-up — TTE ∪ secrets ∪ config (`infra/tte/`, `infra/secrets/`, `infra/config/`); for `down`, the running stack | host docker — `up`: compose up, runs migrations after; `down`: compose down, keeps named volumes (elastic stage/prod `down` `tofu destroy`s the env tier behind a deletion-protection gate) |
| `build [<cb>]` | dev iteration | a running `dev` stack, `core/<cb>/{src,build.sh}` | `core/<cb>/dist/` via bind mount, written by a one-off run of the codebase's exec service |
| `test` | fresh `test` env | full project | host docker (ephemeral test stack), exit code |
| `migrate <env>` | both | service images at current version, `infra/output/<env>/docker-compose.yml`, `infra.yml` (for the schema owners), and the whole aggregate — TTE ∪ secrets ∪ config | target env's database(s) via `migrate.sh` |
| `check` | both | feature branch + origin/main | ephemeral git worktree, runs git/version/contract checks, build, test |
| `merge` | both | feature branch, `project.yml` | preflights origin reachability/auth (`git ls-remote`, skipped no-origin), rebases onto main, tags `v<version>`, pushes both |
| `containerize` | both | clean `main` tip, `project.yml`, `infra.yml` | `docker buildx` per codebase, tag, push to registry |
| `release <env>` | both, branches internally | `infra/output/<env>/`, `infra/secrets/<env>.env`, deploy creds | fixed: ansible over SSH; elastic: SSM push + `tofu apply` |
| `stagetest` | both, branches internally for the pre-step | `infra/stage/{Dockerfile,stage_test.sh,tests/}`, deployed stage URL, plus the orchestrator's own state (fixed: `docker inspect` over SSH; elastic: ECS `list_tasks`/`describe_tasks`) | ephemeral stage-tester container, exit code — **preceded** by a liveness/version gate that fails before the tester is built |
| `rollback <env> <target_version>` | both, branches internally | `v<target_version>` git tag, target version's `infra.yml` (via ephemeral worktree), `infra/secrets/<env>.env` | recompiled output (in worktree), foundation-specific apply with migrations skipped |

Each command's authoritative behavior lives in [docex.md](../../../doctrine/infrastructure/docex.md) and the cross-referenced specifics; this table is a navigation aid, not a re-spec.

### `preinfra` distinguishes failing from declining

`preinfra` is the only command with two kinds of negative outcome, and the
distinction is load-bearing rather than cosmetic. Its own scope excludes registry
*reachability* and *auth* — `containerize` surfaces both naturally — while
`preinfra development` is the gate `envinfra up dev` runs. So an outcome that is
really a statement about reachability must not block a dev stack that never
touches a registry.

- **Failures** are in-scope questions answered wrong: a missing `docex-ingress`
  bridge, an unresolved `dev` hostname, a master VPC without its subnets, or a
  registry that answers a manifest `DELETE` with `405 UNSUPPORTED` — a
  *configuration* fact, and the one the delete probe exists to catch. These set
  exit code 1.
- **Declinations** are out-of-scope questions the command will not answer: no
  registry credential, an unreachable host, a timeout, a `401`, or any response
  no verdict can be read from (notably a bare `405` from a proxy the registry may
  never have seen). Each is **printed by name with its own resolution** under a
  `Declined` heading, and none affects the exit code.

A verifier may decline to answer but may not decline quietly; what the split adds
is that declining an out-of-scope question is a different act from failing an
in-scope one, and one exit code cannot express both. The corollary that matters
when reading a green run: a declination is *not* a pass, and the registry
delete-capability check can only ever fail against a registry it could actually
reach and authenticate to.

### Cross-command orchestration

A few commands compose others rather than duplicate logic:

- `check` invokes `compile` (to verify it succeeds), `build` (via `docker build` during test), and `test`.
- `up` and `test` cause `docker build` to run as needed, which in turn runs each codebase's `build.sh` inside the `build` stage. Two gaps in that sentence are closed explicitly, both because **`compose up --build` does not build a `profiles:`-gated service** and `compose run` builds only when an image is *absent* (never when a present one is stale):
  - **`test`-env one-offs pass `--build`.** In `test` the image *is* the artifact under test, and for a codebase with no non-gated compose service nothing else ever refreshes its tag. `dev` deliberately does not: there the source arrives by bind mount and the `dev` stage exists precisely so `build.sh` can be re-invoked *without* an image rebuild, so `docex build` — the hot iteration loop — must not pay for one.
  - **`up dev` pre-populates each codebase's host `dist/`** before bringing the stack up, since the bind mount shadows the `dev` stage's in-image `dist/` and the container's command would otherwise have nothing to execute. Every codebase gets this; mod 116 retired the one exception, a codebase whose core services were all the old cron role and which therefore had no bind-mounted compose service at all. That shape can no longer be constructed — every core-service role is long-running — so `compose up --build` builds every codebase's *compose* tag and `docex` builds none of those itself. It does issue one build of its own here: `orchestrate/up.py:58` runs `docker build --target build` under the throwaway tag `docex-initial-build-<cb>:latest` purely to copy the artifact out into the host `dist/`. That image is never run as a service and never becomes a codebase's tag.
- `release` invokes `migrate` against the target env **before** applying new application state in the steady-state case, which is what preserves zero-downtime. Two exceptions: on a **first release** the order inverts to apply-then-migrate, because migrate needs the env's services and database to exist; and **`rollback` never migrates at all**, since the doctrine's migrations are forward-only. Both are set out in [`release_flow.md § The four sequences`](./release_flow.md#the-four-sequences).
- `release` on elastic ends with a **Service Connect consumer reconcile** — the only step that reads AWS state written by its own apply, and the only one that mutates a service it did not just deploy. It runs on every elastic branch including rollback. See [`release_flow.md § Elastic-foundation flow`](./release_flow.md#elastic-foundation-flow) step 4.
- The manual CI/CD chain — `docex merge && docex containerize && docex release stage && docex stagetest && docex release prod` — is a documented sequence, not a megacommand. Keeping it explicit preserves the doctrine's "developer can drive the pipeline by hand" property.

## What `docex` Bundles vs. What It Doesn't

**Bundled (lives in the image):**
- The Python CLI: command dispatcher, CICL compiler, all orchestration code.
- The canonical [transfer tables](../../../doctrine/infrastructure/specifics/transfer_tables.md) (`/opt/docex/tables/`).
- The Ansible playbook template used by fixed-foundation releases, rendered per project by `compile` (lives with the other emit templates under `src/docex/emit/templates/`, bundled into the image via the `src/` copy).
- CLI dependencies: `docker`, `tofu`, `ansible`, `aws`, `git`, `jq`, plus the Python runtime.
- Doctrine prose excerpts that back `docex why`.

**Not bundled (lives in the project):**
- Per-codebase `build.sh`, `test.sh`, `health.sh`, `migrate.sh` — bespoke per codebase and per language (`migrate.sh` only where the codebase owns a schema).
- Per-codebase `Dockerfile`s.
- Language runtimes and toolchains for project code — those live inside each codebase's image.
- Project-local transfer table extensions at `infra/transfer_tables/` (deep-merged with bundled tables at compile time).
- The stage-tester image definition at `infra/stage/Dockerfile` and the stage tests themselves.

**Principle:** `docex` orchestrates; per-codebase containers do language-specific work. The `docex` image never needs Node, Go, or a codebase-specific build environment — it just invokes `docker` and friends correctly.

## Filesystem Surface

Every path `docex` reads or writes lives inside the project tree. The shim bind-mounts the project root at the same path inside the container as on the host (rather than at a fixed in-container path like `/project`), so paths reported in docex output match what the operator sees on disk and so DooD path resolution agrees in both directions. All paths below are relative to the project root.

**Read:**
- `project.yml` — name, version, docex_version
- `infra/infra.yml` — CICL source
- `infra/transfer_tables/` (optional) — project-local table extensions
- `infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>` — one contract per declared surface (validated during `check`)
- `infra/secrets/<env>.env` — operator-maintained secret values
- `infra/config/<env>.env` — operator-maintained non-secret per-env config values
- `infra/tte/<env>.env` — dev/test TTE (transient-to-env) store, read during aggregation (see [`config_and_secrets.md`](../../../doctrine/infrastructure/specifics/config_and_secrets.md))
- `infra/deploy_creds/<env>` — SSH private key for fixed `release`
- `infra/stage/{Dockerfile, stage_test.sh, tests/}` — stage tester definition and tests
- `core/<codebase>/{Dockerfile, build.sh, test.sh, health.sh, migrate.sh, src/, migrations/, tests/}` — per-codebase source and shims
- `.git/` — required by `check`, `merge`, and any command that needs commit identity

**Write:**
- `infra/output/<env>/...` — `compile` output (compose + ansible for fixed envs; HCL for elastic envs)
- `core/<codebase>/dist/` — `build` output (dev iteration only; formal builds keep artifacts inside `docker build`)
- `infra/tte/<env>.env` — dev/test TTE minting (mint-if-absent during aggregation)
- `.docex/agg/<env>.env` — the derived container-facing aggregate (gitignored, under the existing `.docex/`)
- Ephemeral git worktrees under `.docex/worktrees/` (or similar) — created and destroyed by `check`

**Conspicuously not touched by docex:** anything outside the project tree. The container is sandboxed to the project root plus the explicitly-mounted credential paths under the operator's HOME.

## Foundation-Aware Behavior

Several commands branch internally on `foundation:` from `infra.yml`. The shim and command surface stay symmetric; the divergence is internal.

| Command | Fixed | Elastic |
| ------- | ----- | ------- |
| `projinfra` | brings the project-tier compose stack (four `-web` networks + per-project traefik) up or down | `up production` creates `<project>-tofu-state` S3 bucket + `<project>-tofu-locks` DynamoDB table, then applies the project tier in two phases (Route53 zone alone → full tier), pausing between them for NS delegation; all idempotent. `down production` tears the project tier down |
| `compile` | emits `docker-compose.yml` per env, plus `playbook.yml` / `inventory.yml` / `ansible.cfg` for stage/prod | emits `main.tf` per env (stage/prod); `dev`/`test` still get compose |
| `containerize` | pushes to project-configured `container_registry` | pushes to project's auto-provisioned ECR (or override) |
| `release` | `ansible-playbook` over SSH using `infra/deploy_creds/<env>` | SSM push → `RunTask` migration → `tofu apply` → Service Connect consumer reconcile (`forceNewDeployment` on any consumer whose deployment predates a name it `uses`) |
| `migrate` (during release) | `compose run --rm` of the codebase's exec service on the host, in the existing internal docker network | ECS `RunTask` against the per-codebase migration task definition |
| `stagetest` (the pre-step only) | `docker inspect` **over SSH** to the deployed host — `stage`/`prod` containers do not run on the operator's machine | ECS `list_tasks` / `describe_tasks` / `describe_task_definition` |

The `dev` and `test` environments are always fixed regardless of declared foundation, per [shape.md § Shape and Environment](../../../doctrine/infrastructure/shape.md#shape-and-environment).

### The orchestrator liveness/version gate

`docex stagetest` reads every core service's health and version from the
orchestrator **before it builds the stage-tester image**, and fails there if
anything is unhealthy, on the wrong version, **or unreadable**. Rule of record:
[`healthchecks.md § Version`](../../../doctrine/infrastructure/healthchecks.md#version)
and [`cicd.md § Staging Tests`](../../../doctrine/infrastructure/cicd.md#staging-tests)
step 1. Implemented in `src/docex/pipeline/orchestrator_health.py`
(`assert_deployed_healthy`), which `stagetest.py` calls.

Three properties of this gate are design commitments rather than incidental, and
each exists because the alternative is a check that appears to answer and does
not:

- **Probe output is never parsed.** Liveness comes from the orchestrator's
  aggregated state and version from the deployment record. Docker captures a
  healthcheck's stdout; ECS surfaces only a status — so anything read out of
  probe output would work on one foundation and silently not on the other.
- **Two error classes, deliberately distinct.** `DeployedServiceUnhealthy` is the
  orchestrator's honest bad answer; `OrchestratorStateUnreadable` is `docex`
  being unable to obtain an answer at all. Keeping them separate is what makes
  "the gate broke" untypeable as "the env is fine" — the structural fix for the
  whole can't-answer class, and worth more than any individual guard.
- **There is no flag that disables it.** A parameter whose only function is
  switching off a health gate is the artifact advance 005 found eight times; once
  it exists in a signature the next caller in a hurry uses it. Tests inject a
  scripted transport instead. **Do not add one**, including under pressure from a
  smoke walk: if the walk hurts, the gate is reporting something.

An **empty result set never reads as healthy** anywhere in this gate — zero core
services, zero RUNNING tasks, and an unreadable container all fail loudly. On
elastic, a task set that shrinks between `list_tasks` and `describe_tasks` gets
**one** bounded re-read (ECS replaces tasks on its own schedule, so one unlucky
replacement mid-read is not evidence about the release) and then fails. The
re-read is scoped to a *shrinking task set* only, never to a task that was
returned and reported unhealthy — which is what makes it structurally unable to
mask an unhealthy service.

One asymmetry is known and accepted: on `fixed` the version comes from
`.Config.Image`, which proves the image *ref* and not the bytes — a re-pushed tag
would pass. Nothing in a project records an expected digest to compare against,
and `healthchecks.md` specifies the ref, so there is no stronger check available
to write.

## Credentials & Ambient Host State

`docex` consumes credentials and host state from well-known locations. It does **not** manage credential storage itself.

| Need | Source | Used by |
| ---- | ------ | ------- |
| Container registry push/pull | `~/.docker/config.json` | `containerize`, `release` (fixed pull side is the *target host*'s config, not the operator's), `preinfra development` (fixed — authenticates the manifest-delete probe; absent credential *declines*, never fails) |
| AWS API access | `~/.aws/credentials` (or env vars / OIDC if present) | `projinfra`, `release` (elastic), `containerize` (when ECR) |
| SSH to fixed-foundation hosts | `infra/deploy_creds/<env>` (private key) + `~/.ssh/known_hosts`; and on the target host, passwordless `sudo` for the `deploy` user | `release` (fixed); `preinfra production` (fixed — probes the target host for registry creds); `stagetest`'s pre-step (fixed — `docker inspect` per core container, which needs the sudo above because the playbook runs `become: true` and the containers are root-owned) |
| Git identity & remote push | `~/.gitconfig`, `~/.ssh/` | `merge`, `check` (worktree creation) |
| Git remote auth via a host credential helper (opt-in) | host `git credential fill` for `origin`, brokered per-op via a forwarding socket — see [The Shim](#the-shim) | `merge`, `check`, `rollback` when `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` is set |
| Docker daemon | `/var/run/docker.sock` | every command that touches docker |

If a required credential is missing, `docex` fails loudly with a message pointing at the conventional location, never with a silent fallback.

## Docker-outside-of-Docker

`docex` needs to build, tag, push, and run containers on behalf of the project. It does this via the **DooD** pattern: the `docex` container runs the `docker` CLI, but the CLI talks to the **host's** docker daemon over a mounted socket. No nested daemon, no `--privileged`, no special VM tricks.

Four consequences worth being explicit about:

1. **Containers `docex` spawns are siblings, not children.** When `docex envinfra up dev` runs `docker compose up`, the resulting containers attach to the host's docker, not to docex. They outlive the docex invocation, which is exactly what we want — `docex envinfra up` returns immediately and the dev stack keeps running.
2. **Paths are host-relative for spawned containers.** When `docex` runs `docker compose -f .../dev/docker-compose.yml up`, the compose file references project paths (build contexts, bind-mount sources for `src/` and `dist/`); those paths must resolve to something the host's docker daemon can find. The shim solves this by mirroring the host project path inside the container — `$PROJECT_ROOT` is mounted at `$PROJECT_ROOT` (not at a fixed `/project`), so any path docex emits is simultaneously a valid in-container path (for compose's client-side reads) and a valid host path (for the daemon's bind-mount resolution). Compose itself receives the project directory via `--project-directory` on the CLI rather than via env var — docker compose v2 does NOT honor `COMPOSE_PROJECT_DIR`.
3. **The in-container user matches the host user.** The shim passes `--user "$(id -u):$(id -g)"`, mounts `/etc/passwd`/`/etc/group` from the host, and mirrors `$HOME` inside the container. The result: files docex writes to the project tree are operator-owned on the host (no `sudo chown -R` after every compile), `git` doesn't trip on dubious-ownership, and tools that resolve the running user via `getpwuid()` (ssh) find a coherent home directory matching the credential mounts.
4. **The compose project name is pinned explicitly, not derived.** `--project-directory` (point 2) governs *path resolution* only; it does **not** decide the Compose **project name** (the `com.docker.compose.project` label Compose uses to track which resources belong to a stack across `up`/`down`). docex passes an explicit `--project-name` on every compose invocation — `<project_dns_label>-<env>` for env stacks, `<project_dns_label>-projinfra` for the project tier — rather than letting Compose derive one from the project directory's basename. The project-tier name is deliberately side-independent so that on a single-machine fixed host the dev and prod sides converge on one Compose project (per projinfra.md §35): `up production` after `up development` adopts the existing resources and reconciles to a no-op instead of colliding on the shared traefik container. It remains an explicit, project-scoped name (mod 053) rather than the path-derived `infra`. The derived name was project-unscoped (every project's projinfra stack resolved to the literal `infra`, since project-tier compose lives at `infra/output/project/<side>/`) and unstable across docex versions, which broke idempotent re-runs and left `-web` networks unremoved on `down`. Pinning the name makes Compose's adopt-on-rerun and teardown deterministic and project-scoped (mod 053; side-independent since mod 087).

DinD is rejected as slower, more dangerous (requires `--privileged`), and unnecessary for our use case.

## Ephemeral Git Worktrees

`docex check` (and defensively, `docex merge`) needs to perform git operations against a merged state without disturbing the developer's working tree. `docex rollback` uses the same `pipeline/_worktree` helpers for a different reason: it checks out `v<target_version>` and recompiles that version's `infra.yml` with the *current* `docex`, which is the point of the command rather than a precaution (see [`release_flow.md § Worktree mechanism`](./release_flow.md#worktree-mechanism)). The mechanism:

1. Create a temporary worktree under `.docex/worktrees/<command>-<discriminator>/` — `check-<sha>`, `rollback-<version>` — gitignored by convention.
2. Inside the worktree, rebase the feature branch tip onto a fresh fetch of `origin/main`.
3. Run gate checks (working-tree-clean, version bumped, contracts aligned, etc.), then `compile`, `build` (via `docker build`), and `test` against the worktree.
4. On success, the worktree is removed. On failure, the worktree is removed *and* a structured error report points at what failed; the developer's branch and main are untouched either way.

The worktree directory is namespaced (`.docex/`) so multiple in-flight `check` invocations don't collide, and so the developer never has to think about cleanup.

### The contract and shim gates

Three of those gates read a project's declared boundaries and its codebase layout.
Their criteria are worth stating here because they are easy to get subtly wrong,
and because an earlier generation of them got several things wrong for months. The
rule of record is [`contracts.md`](../../../doctrine/infrastructure/contracts.md)
and [`healthchecks.md`](../../../doctrine/infrastructure/healthchecks.md); this is
how `pipeline/check.py` implements it.

- **Provider set = the core services that declare `surfaces:`.** Nothing else.
  Declaring a surface is what makes a core service a provider, and a `uses` edge
  onto one that declares none is a **compile error** (rule 31) rather than a
  silently-missing contract. The previous two-armed union —
  `(core-targeted uses entries) ∪ (web-network core services)` — is gone, and its
  second arm was **wrong rather than merely redundant**: it forced a contract onto
  every publicly-reachable core service, including a `frontend.web` that serves a
  browser and describes no boundary at all.
- **Format follows the surface's `api_styles`, and the check is derived rather
  than tabulated** — `len(surface.formats()) == 1` over
  `model.py::API_STYLE_FORMATS`. `[rest, stream, webhook]` resolves to one format
  and passes; `[rest, rpc]` fails rule 29 telling the author to split. There is
  **no fallback**: the retired `_FALLBACK_CONTRACT_FORMAT = "openapi"` meant an
  unrecognized role silently received the wrong format, and an unrecognized
  `api_style` is now `rule_29_unknown_api_style` at *compile* time — so by the
  time the gate runs there is nothing left to guess at.
- **Contract paths are parsed right-anchored on four segments** —
  `<codebase>.<service>.<surface>.<format>.<ext>` — and the extension is checked
  against the **resolved format** rather than against a list of accepted suffixes,
  because `contracts.md § Standards` fixes exactly one extension per format. So
  `api.web.rest.openapi.yml` resolves while both `api.web.openapi.yml` (the
  retired three-segment form) and `api.web.rest.openapi.yaml` do not. The path
  stays service-keyed unconditionally: one codebase may run two HTTP core services
  and both are genuine boundaries.
- **The gate has an orphan arm, and it is the arm that earns its keep on an
  upgrade.** A contract file matching no declared surface *fails*, naming the
  four-segment form and saying to rename or delete. This is the only thing that
  can see a leftover `api.web.openapi.yml` sitting **beside** a correct
  `api.web.rest.openapi.yml` — an existence-only check is structurally blind to
  it, because the file it wants is also present.
- **One health assertion survives, narrowed to a contract-content check.** Where a
  `web`-network core service *also* declares an `openapi` surface, one of its
  openapi contracts declares a `GET` on that core service's **declared
  `health_check_path`** — read from the field, never hardcoded to `/health`, so a
  project declaring `/healthz` conforms. *Any one* openapi surface satisfies it:
  requiring the path in **every** surface would force a `rest_admin` contract to
  document a route outside its own boundary, and a contract that describes
  something it does not own is a worse defect than one omitting something
  documented next door. Keyed on `web`-network membership rather than role, for
  rule 33's reason — the field is what a reverse proxy reads, and a `role: web`
  core service off the `web` network has nothing in front of it.
- **A contract's declared spec version meets the doctrine floor** (`_gate_contract_spec_version`,
  mod 137) — OpenAPI ≥ 3.2, AsyncAPI ≥ 3.0, transcribed from `contracts.md § Standards`
  into `_FORMAT_MIN_SPEC_VERSION` beside `_FORMAT_EXTENSIONS`. Each floor is what makes a
  promised `api_style` *implementable* — openapi 3.2 for `stream`'s `itemSchema`, asyncapi
  3.0 for `rpc`'s `reply` — so a project shipping `openapi: "2.0"` that previously passed
  green now fails. It iterates the **same** `list[ContractExpectation]` the two gates above
  materialize (no second directory walk), covers the two versioned formats only (`graphql` /
  `proto` are SDL/IDL with no version key), and reports a malformed/absent version key **once**
  as its own defect rather than also as a below-floor consequence it cannot compute.
- **`health.sh` is the fourth codebase shim gate**, required unconditionally
  alongside `build.sh` and `test.sh`; `migrate.sh` stays conditional on schema
  ownership. One file per codebase like the others, but invoked **per core
  service** as `./health.sh <service>` — the compiler emits the argv, so the shim
  never guesses which core service it is running in.

**Two gates were deleted rather than repaired, and the distinction matters.**

- `_gate_health_endpoints` went **whole**: the `/health/<codebase>/<service>`
  fan-out, the one-hop recursion rule that existed solely to stop the fan-out
  looping on the legal `web ↔ worker` cycle, and the probeability arm that
  demanded both `port` and `health_check_path` on every core `uses` target — which
  rules 32 and 33 now respectively make conditional and forbid.
- `_gate_healthcheck_tooling` — the `curl`-in-the-image gate — was **deleted, not
  narrowed.** `infrastructure.md § Codebase Containers` no longer mandates `curl`;
  it mandates that the image can run `./health.sh <service>` and leaves the tool
  to the project. A gate enforcing a requirement the rule of record has withdrawn
  is worse than no gate, because it reads as a live constraint.

The roster was **nine** gates after those two deletions; mod 137 added
`_gate_contract_spec_version`, so it is now **ten** — the third contract gate,
beside `_gate_contracts` and `_gate_contract_health_path`.

**History, because it explains how a real defect hid for months.** Mod 101 wrote
the two-armed union and the fan-out; before it, `_infer_contract_format` had
returned `openapi` **unconditionally since the day it was written** — its asyncapi
branch looked a *codebase* name up in `backing_services`, which `model.py` forbids
from overlapping — so the async-contract path had never once executed, and the
fan-out flaw went unnoticed behind it. That is why format stayed keyed on `role`
for as long as it did: nothing had ever exercised the branch that would have shown
the keying was wrong. Retained as the record of a defect class, not as live
description.

## Repository Structure

`docex` lives in `jean_baudrillard/docex/`:

```
jean_baudrillard/docex/
├── CHANGELOG.md             (pointer stub → the doctrine-wide ../CHANGELOG.md; version is doctrine-wide as of 1.3.0)
├── pyproject.toml
├── Dockerfile
├── plans/                   (doctrine-shaped planning tree — see docex_process.md for the divergences)
│   ├── core/                (flat; no per-module subfolders since docex isn't hexagonal)
│   │   ├── masterplan.md    (this file)
│   │   ├── docex_process.md (how docex itself is changed; read before editing docex)
│   │   ├── compiler.md      (the CICL compiler: expansion, magic refs, emit)
│   │   ├── release_flow.md  (release + rollback: preconditions, worktree, apply)
│   │   └── test_projects.md (the two nested smoke projects: why, shape, cadence)
│   ├── modifications/       (one folder per mod; same shape as the doctrine prescribes)
│   └── references/          (external API / spec docs the project relies on)
├── src/
│   └── docex/               (Python package; CLI entrypoint + all subcommands)
│       ├── __main__.py      (argparse dispatcher)
│       ├── cicl/            (CICL parse, validate, expand, magic refs)
│       ├── emit/            (compose / HCL rendering from compiled objects)
│       ├── orchestrate/     (up, down, build, test, migrate, aggregate)
│       ├── pipeline/        (preinfra, projinfra, bootstrap, check, merge,
│       │                     containerize, release, stagetest, rollback,
│       │                     orchestrator_health — stagetest's pre-step)
│       ├── describe/        (describe)
│       ├── why/             (why — serves doctrine_excerpts/)
│       ├── roles/           (roles + role)
│       ├── aws/             (boto3 adapter)
│       ├── docker/          (docker CLI adapter)
│       ├── git/             (git CLI adapter)
│       ├── ssh/             (ssh adapter)
│       ├── dns/             (resolver adapter)
│       ├── ansible/         (ansible adapter)
│       ├── opentofu/        (tofu CLI adapter)
│       ├── secretsmgmt/     (SSM / .env secret backends)
│       ├── registry/        (container-registry HTTP adapter)
│       ├── context.py       (project context load)
│       ├── naming.py        (name policies)
│       ├── errors.py        (error taxonomy)
│       └── envfile.py       (.env read/write)
├── tables/                  (canonical transfer tables, copied to /opt/docex/tables/)
├── doctrine_excerpts/       (data feeding `docex why`)
├── bin/                     (the project-installed shim, sourced from here)
└── tests/
```

### Implementation language

`docex` is written entirely in Python 3.12+. Single-codebase coherence beats a polyglot split between "compiler" and "orchestration". Where docex needs to invoke a CLI (docker, tofu, ansible, aws, git), it does so as a subprocess from Python — never by shelling into bash scripts that themselves shell into other CLIs.

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

These align with the [Deferred section of infrastructure.md](../../../doctrine/infrastructure/infrastructure.md#deferred) plus a few proposal-specific items.

1. **Multi-machine fixed foundation.** Single host per env for now; multi-host (docker swarm or otherwise) waits on a future doctrine extension.
2. **Automated CI/CD triggers.** `docex` is invoked manually or by a thin CI runner that just shells out to it. PR-triggered pipelines, GitHub Actions wrappers, etc. are out of scope.
3. **Fundamental stage tests.** Stage test content is entirely the developer's responsibility. Doctrine-provided baseline stage tests (DNS, TLS, per-service health) are a future addition.
4. **Public image hosting.** `docex` images are built locally and consumed from the local Docker store. Hosting on a public registry — and the per-provider auth that implies — is deferred until multi-machine teams need it.
5. **Externally-rotated secrets.** All secrets are project-controlled and clobbered on each release; AWS-managed RDS rotation and friends are deferred per [config_and_secrets.md § Caveats](../../../doctrine/infrastructure/specifics/config_and_secrets.md#caveats).
6. **The full CICL spec.** Covered in [cicl.md](../../../doctrine/infrastructure/cicl.md) and [transfer_tables.md](../../../doctrine/infrastructure/specifics/transfer_tables.md); not duplicated here.
7. **Hexagonal architecture concerns.** Separate doctrine track; orthogonal to `docex`.
